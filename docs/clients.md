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

Codexの設定仕様は[Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp.md)、Inspectorの操作は[MCP Inspector documentation](https://modelcontextprotocol.io/docs/tools/inspector)を参照してください。
