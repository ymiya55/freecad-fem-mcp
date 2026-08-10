# MCPクライアント設定

このサーバーはローカルSTDIO MCPです。MCPクライアントは`freecad-fem-mcp`プロセスを起動し、そのプロセスが起動済みFreeCAD GUI内のAddonへ認証付きlocalhost bridgeで接続します。先にFreeCAD 1.1.xを起動してください。

すべての例で`<repository path>`をこのリポジトリの絶対パスへ置き換えます。Windowsでは空白を含むパスを引用符で囲んでください。

## Codex

Codex CLI、Codexデスクトップ、IDE拡張は同じMCP設定を共有します。CLIから登録する場合:

```powershell
codex mcp add freecad-fem -- uv run --project "<repository path>" freecad-fem-mcp
codex mcp get freecad-fem
```

登録後はCodexを再起動するか、新しいタスクを開始します。デスクトップではSettingsのMCP serversから同じSTDIO commandとargsを登録することもできます。

FreeCADドキュメントを変更するツールはCodexの承認対象になります。日常利用では承認を有効にしたままにしてください。CIなど管理された非対話試験でのみ、必要なツールを限定して明示承認します。

`codex exec --sandbox read-only`では、Windowsサンドボックスから`%LOCALAPPDATA%`の接続レコードやlocalhost bridgeへ到達できない場合があります。接続レコードには短期の認証トークンが含まれるため、ネットワーク許可と同時にそのディレクトリを広く公開する設定は推奨しません。通常のCodexデスクトップまたは対話CLIでMCPサーバーを登録し、FreeCAD操作だけを個別承認してください。管理された自動試験では、MCPサーバープロセスに限定したローカル接続権限を用意し、モデルがシェルや接続レコードを直接読めないことを受け入れ条件にします。

## Claude Desktop

インストーラーで既存JSONをバックアップして登録できます。

```powershell
.\scripts\install.ps1 -McpConfigPath "$env:APPDATA\Claude\claude_desktop_config.json"
```

手動設定は次と同等です。

```json
{
  "mcpServers": {
    "freecad-fem": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "<repository path>",
        "freecad-fem-mcp"
      ]
    }
  }
}
```

保存後にClaude Desktopを完全に再起動します。既存の`mcpServers`項目は削除せず、`freecad-fem`だけを追加してください。

## MCP Inspector

モデルを介さずツールスキーマと応答を確認する場合は、公式MCP Inspectorを使用できます。

```powershell
npx.cmd -y @modelcontextprotocol/inspector `
  uv run --project "<repository path>" freecad-fem-mcp
```

InspectorのToolsタブで、まず`get_status`と`inspect_document`を実行します。変更ツールを試す場合は、保存していないテスト用FreeCADドキュメントを使用してください。

## その他のSTDIO MCPクライアント

クライアントがcommand/args形式を採用している場合、次を設定します。

```text
command: uv
args: run --project <repository path> freecad-fem-mcp
```

シェル文字列ではなく、commandと引数配列を分離して渡してください。サーバーのstdoutはMCP専用で、診断はstderrへ出力されます。

## 動作確認プロンプト

読み取りだけの接続確認:

```text
freecad-fem MCPだけを使ってget_statusとinspect_documentを実行し、
FreeCADのバージョン、ドキュメント名、オブジェクト一覧を報告して。
シェルコマンドは使わないこと。
```

線形静解析の縦切り:

```text
freecad-fem MCPだけを使うこと。開いているCantileverに対して、
Analysisを作成し、E=210 GPa、ν=0.3、密度7850 kg/m³の鋼材を割り当てる。
CantileverのFace1を固定し、Face6へ1000 Nを与える。
Gmshメッシュを5 mmで作成して完了を待ち、validate_analysis後に
CalculiXを実行する。完了後、変位結果を取得してGUIへ表示する。
失敗したツールがあればそこで停止し、エラーを報告すること。
```

新しい分類済みAPIを明示する場合は、固定面に`add_boundary_condition`、荷重面に
`add_load`を使うよう指示します。重力はグローバル荷重なので`targets=[]`が有効です。

`add_boundary_condition`の`pin`は並進3自由度を拘束して回転を自由にします。`roller`は
`axis`へ`x`、`y`、`z`のいずれかを指定するか、同じ軸に平行な単位`normal_m`を指定し、
そのglobal並進自由度だけを拘束します。FreeCADの`ConstraintPlaneRotation`は節点群を
移動可能な同一平面に保つCalculiX MPCであり、固定基準面へのfrictionless supportや
一般的なsymmetry supportではないため、それらの別名としては公開しません。

remote force / momentは`add_remote_load`で指定します。結合領域の`targets`は1件以上を
必須とし、`reference_point_m`はglobal座標のm、`force_n`はN、`moment_n_m`はN·mです。
FreeCADのモード名やプロパティ名は入力しません。

```text
Pocket002のFace1を結合領域として、global参照点[0.1, 0.2, 0.3] mに
force [100, 0, -50] Nとmoment [0, 25, 0] N·mを与えるremote loadを追加して。
```

remote displacementは`add_remote_displacement`を使います。`translation_m`と
`rotation_rad`の各成分は、数値なら指定値、`null`なら自由です。少なくとも1成分を
指定する必要があります。遠心力は`add_load`の`centrifugal`を使い、周波数はHz、
軸は実在する直線`EdgeN`を1本、対象は`SolidN`または全要素を表す空配列で指定します。

force、pressure、displacement、remote load / displacementには`amplitude`を指定できます。
点列は2〜256点、先頭の`time_s`は0.0、以後は厳密増加、`scale`は無次元です。FreeCADの
文字列プロパティは直接指定せず、MCPが検証済み点列から生成します。独立LoadCaseや
複数解析StepはFreeCAD 1.1.3のnative writerにないため、現在は公開していません。

固有振動では`create_analysis`の`analysis_type`を`frequency`にし、
`eigenmodes_count`を1〜100で指定します。`frequency_low_hz`と`frequency_high_hz`は
両方指定または両方省略で、指定時は上限が下限より大きい必要があります。線形座屈では
`analysis_type=buckling`、`buckling_factors`（1〜100）、`buckling_accuracy`（0より大きく
1以下）を指定します。frequencyには密度、bucklingには支持と荷重が必要です。

解析完了後は`get_results`または`show_result`の`mode`へ1始まりのモード番号を指定します。
frequencyの応答には`frequency_hz`、bucklingの応答には`buckling_factor`が含まれます。
`mode`は1〜100に制限され、存在しないモードは拒否されます。静解析との互換用`frame`は
0始まりですが、意味の混同を防ぐため`mode`と非ゼロ`frame`は同時指定できません。
FreeCAD 1.1.3のnative importerでは、frequencyはmode NがFrame/Data block N−1、bucklingは
先頭にpreload結果があるためmode NがFrame/Data block Nに対応します。この差はMCP側で吸収します。

static解析で幾何学的非線形を使う場合は`create_analysis`へ
`geometrical_nonlinearity=nonlinear`を指定します。材料非線形は`material_nonlinearity=nonlinear`
を指定し、`assign_material`へ`hardening_model`（`isotropic`または`kinematic`）と1〜64点の
`yield_points`を渡します。各点はSI単位の`stress_pa`と無次元の`plastic_strain`で、先頭ひずみは
0、応力は厳密増加、塑性ひずみは非減少でなければなりません。MCPはnative
`MaterialMechanicalNonlinear`を同時に作る線形母材へリンクし、Paをwriter用MPaへ変換します。

single-step増分を明示する場合は`time_initial_increment_s`、`time_minimum_increment_s`、
`time_maximum_increment_s`、`time_period_s`の4値をすべて指定し、minimum ≤ initial ≤ maximum ≤
periodを満たします。`automatic_incrementation`と`increments_maximum`もboundedです。任意のCalculiX
iteration文字列、独立LoadCase、複数解析Stepは受け付けません。native出力に明示的な収束句が
ある場合だけ、job/result応答にboundedな`convergence`要約を含めます。

1D beamまたは2D shellの準備では、`create_mesh.element_dimension`へ`1d`または`2d`を明示します。
`assign_element_geometry`の`targets`は省略できず、beamでは実在するEdge、shellでは実在するFaceだけを
指定します。`kind=shell`はSIの`thickness_m`、-1〜1の`offset`、`shell`または`membrane`の
`formulation`を受け付けます。`kind=beam_rotation`は
`rotation_rad`を受け付けます。`kind=beam_section`の`section_type`は`rectangular`、`circular`、
`pipe`、`elliptical`、`box`、`truss`です。各断面に必要なSI寸法だけを指定し、別断面の寸法field、
空参照、whole-object、Face/Edgeの取り違え、重複参照は拒否されます。Pipeは外径の半分未満の肉厚、
Boxは内側寸法が正になる肉厚を必要とします。beam/trussとshell/membraneはsolver全体のelement modelを
共有するため、同一analysisへ曖昧に混在させることはできません。
CalculiXのM3D3 membrane要素は面圧`*DLOAD,P`を受け付けないため、membrane解析への`pressure`は
`validate_analysis`で拒否します。曲げ剛性を持つshell解析ではFaceへのpressureを使用できます。

beamの規定自由度は`add_boundary_condition(boundary_type="displacement")`で指定します。
`displacement_m`と`rotation_rad`はいずれも3成分で、各成分の数値は拘束値、`null`は自由を表します。
両方を同時に指定できますが、少なくとも1成分は数値でなければなりません。`rotation_rad`は1D beamを
含む解析だけで許可され、3D solidだけの解析では事前検証で拒否されます。通常beamの最初の断面は
native `BeamReducedIntegration=false`、Pipeは`true`へ安全に設定され、trussは
`ExcludeBendingStiffness=true`の独立presetとして扱われます。

TieとContactは`add_connection`を使い、`slave`と`master`へ実在するFaceを各1面指定します。
Tieは`tolerance_m`と`adjust`が必須です。Contactはstatic・non-thermalに限定し、
`surface_behavior`へ`hard`、`linear`、`tied`を指定します。Linear/Tiedでは正の
`normal_stiffness_pa_per_m`が必須です。摩擦を使う場合は`friction=true`とし、0より大きく10以下の
`friction_coefficient`、正の`stick_stiffness_pa_per_m`を指定します。`adjust_m`は0〜1e6 mです。
剛性はSIのPa/mで入力し、MCPがFreeCAD native quantityへ変換します。摩擦fieldはTie/Cyclicへ、
Tie fieldはContactへ指定できません。同一面、stale参照、Edge/Vertexは拒否します。

cyclic symmetryも`add_connection`を使い、`connection_type=cyclic_symmetry`、Faceのslave/master、
`tolerance_m`、`adjust`、`sectors`、`connected_sectors`を指定します。`sectors`は2〜1,000,000、
`connected_sectors`は1以上かつ`sectors`未満です。現在はFreeCAD native既定の原点・global +Z
対称軸だけを使用し、任意Placement入力は公開しません。

`add_constraint`の`plane_rotation`は、Vertex/Edge/Face/Solidまたはwhole-shapeから得たmesh node
setを同一平面に保つnative CalculiX `*MPC,PLANE`です。移動・回転可能な平面なので、固定基準面の
frictionless、symmetry、antisymmetry supportの代用にはしません。表示専用のnormal/point propertyや
任意MPC式は入力できません。

拘束対象を明示的に呼ぶ場合、`targets`の要素は次の形です。`object_id`ではなく`object_name`を使用します。

```json
{
  "object_name": "Cantilever",
  "subelements": ["Face1"]
}
```

## 接続できない場合

1. FreeCAD 1.1.xが起動していることを確認する。
2. `.\scripts\check.ps1 -SkipMcpConfig`でAddon導入を確認する。
3. FreeCADを再起動し、`get_status`を再実行する。
4. MCPクライアントを再起動してツール一覧を更新する。
5. MCP InspectorでSTDIOサーバー単体の初期化を確認する。

長時間動作するMCPクライアントは、FreeCAD再起動後の最初の接続失敗時に新しい接続レコードを1回だけ再読込します。複数のFreeCAD GUIを同時起動すると最後に起動したbridgeが接続レコードを所有するため、MCP操作対象のFreeCADは1プロセスにすることを推奨します。

`get_status.capabilities.future_gates`は、現在のFreeCAD 1.1.3 native経路では利用できない機能です。
LoadCase、複数Step、Combination、Envelope、bolt pretension、機械的初期応力／ひずみ、集中質量／
回転慣性、damper、connector releaseを含みます。これらの名前を他のツールへ入力してもunknown field
として拒否され、任意INPや旧solverへfallbackしません。

Codexの設定仕様は[Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp.md)、Inspectorの操作は[MCP Inspector documentation](https://modelcontextprotocol.io/docs/tools/inspector)を参照してください。
