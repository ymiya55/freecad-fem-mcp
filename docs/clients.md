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

Codexの設定仕様は[Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp.md)、Inspectorの操作は[MCP Inspector documentation](https://modelcontextprotocol.io/docs/tools/inspector)を参照してください。
