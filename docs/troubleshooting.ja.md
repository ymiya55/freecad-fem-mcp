# トラブルシューティング

[English](troubleshooting.md) · [READMEへ戻る](../README.ja.md)

該当する症状から確認してください。`%LOCALAPPDATA%\freecad-fem-mcp\bridge-v1.json`の内容はコピーまたは公開しないでください。短期認証トークンが含まれます。

## インストール確認に失敗する

次を実行します。

```powershell
.\scripts\check.ps1 -SkipMcpConfig
```

Addonがない、またはこのリポジトリを指していない場合は再インストールします。

```powershell
.\scripts\install.ps1 -SkipMcpConfig
```

再インストール後はFreeCADを再起動します。インストーラー管理外のAddonが導入先に存在する場合は、確認とバックアップを行ってから`-Force`を使用するか判断してください。

## MCPクライアントに`freecad-fem`ツールが表示されない

1. `uv sync`が完了していることを確認します。
2. MCP登録にリポジトリの絶対パスが使われていることを確認します。
3. Codexでは`codex mcp get freecad-fem`を実行します。
4. MCPクライアントを再起動するか、新しいタスクを開始します。
5. 設定コマンドが`uv run --project <repository> freecad-fem-mcp`と同等か確認します。

サーバーはSTDIOを使用します。stdoutへメッセージを追加したり、バナーを表示するスクリプトで包んだりしないでください。

## `get_status`がFreeCADへ接続できない

次の順に確認します。

1. FreeCAD `>=1.1.3,<1.2`のGUIが起動している。
2. `%APPDATA%\FreeCAD\v1-1\Mod\FreeCADFEMMCP`にAddonがある。
3. 最新Addonのインストール後にFreeCADを再起動した。
4. 操作対象のFreeCAD GUIが一つだけ起動している。
5. 登録後にMCPクライアントを再起動した。

最後にbridgeを開始したFreeCADプロセスが接続レコードを所有します。ベンチマーク用の`FreeCADCmd`が一時的に接続先を置き換えることがあります。操作対象のFreeCAD GUIを再起動し、MCPクライアントでも新しいタスクを開始してください。

## Bridge authentication is not configuredと表示される

実行中FreeCADのbridgeレコードがないか、以前のFreeCADプロセスが終了した場合に発生します。操作対象のFreeCAD GUIを再起動してください。トークンを手動で環境変数やログへコピーしないでください。

## 別のFreeCADドキュメントが変更される

- MCP操作中はFreeCAD GUIを一つだけ起動します。
- 解析設定の主要段階ごとに`inspect_document`を実行します。
- 複数ドキュメントを開く場合は返された`document_id`を指定します。
- 材料、荷重、拘束を追加する前にanalysis IDを確認します。

## 選択したFaceまたはEdgeが拒否される

変更操作の直前に`get_selection`を実行します。主な原因は次のとおりです。

- 何も選択されていない。
- Faceが必要な場所でEdgeを選ぶなど、entity種別が異なる。
- 形状変更により以前の`FaceN`または`EdgeN`参照がstaleになった。
- 同じentityが重複している。
- 正確な`object_name`ではなくLabelや`object_id`を使っている。

現在のFreeCAD GUIで選択し直してください。明示参照は次の形式です。

```json
{
  "object_name": "Cantilever",
  "subelements": ["Face1"]
}
```

## メッシュ作成に失敗する

次を確認します。

- FreeCAD FEMワークベンチからGmshを使用できる。
- `element_dimension`がモデルの`1d`、`2d`、`3d`と一致する。
- 必要なEdgeへbeam断面が割り当てられている。
- 必要なFaceへshell板厚が割り当てられている。
- メッシュサイズが正で、形状に対して適切である。
- 対象形状が有効でanalysisから参照できる。

`get_job`でboundedなジョブ状態と診断要約を確認します。原因を修正せずに繰り返し再実行しないでください。

## `validate_analysis`に失敗する

不完全または矛盾したモデルでCalculiXを開始しないための検証です。代表的な指摘は次のとおりです。

- 材料、密度、支持、荷重、メッシュ、beam断面、shell板厚の不足
- 剛体運動または拘束重複
- 領域材料の重複または未割当
- membraneモデルへの非対応pressure
- 無効なContact pairまたはproperty組合せ
- 密度のない固有振動解析
- 支持または事前荷重のない座屈解析

モデルを修正して再度検証します。raw INPやPythonで検証を迂回することはできません。

## ソルバージョブが失敗する、または終了しない

返されたjob IDで`get_job`を使用します。実行中ジョブを停止する必要があれば`cancel_job`を使います。その後、次を確認します。

- FreeCADのCalculiX設定
- 直前のstrict validation結果
- 材料・断面の単位
- 接触剛性と摩擦値
- 非線形incrementの大小関係と最大increment数
- FreeCAD作業ディレクトリの空き容量

ジョブログはサイズ制限とsanitize処理を受けます。要約だけで原因が分からないnative FreeCAD/CalculiXエラーは、破棄可能なモデルを使ってFreeCAD FEM GUIから再現してください。

## 結果が空、またはmodeが拒否される

- solver jobが`completed`になるまで待ちます。
- fieldが`displacement`、`stress`、`strain`、`von_mises`のいずれかであることを確認します。
- 固有振動・座屈では、実際に計算した1始まりの`mode`を使います。
- 静解析ではpipeline `frame`を使い、modeと非ゼロframeを同時に指定しません。
- 検証済みFreeCAD 1.1.3経路ではreactionは公開結果ではありません。

beam/shell結果では`result_layout`を確認します。元解析が1D/2DでもFreeCADが3D展開結果を表示することがあります。

## `open_model`または`save_document`がパスを拒否する

設定した許可ルート内の絶対パスを使用します。path traversal、UNC、device path、alternate data stream、非対応拡張子、reparse pointを介した脱出は拒否されます。

最初の解析ではFreeCADから手動でモデルを開いてください。既存ファイルの上書きには`overwrite=true`と、document inspectionが返す現在の`expected_revision`が必要です。

## 安全な問題報告に含める情報

- FreeCAD、Python、Gmsh、CalculiXのバージョン
- `check.ps1 -SkipMcpConfig`の出力
- 失敗したMCPツール名とsanitize済みエラー
- 解析種類とモデル次元
- 機密情報を含まない最小再現モデル

bridge token、接続レコード全体、非公開モデルパス、意図せず共有する proprietary geometryは含めないでください。
