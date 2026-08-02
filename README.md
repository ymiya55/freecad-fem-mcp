# FreeCAD FEM MCP

[![CI](https://github.com/ymiya55/freecad-fem-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/ymiya55/freecad-fem-mcp/actions/workflows/ci.yml)
[![Security checks](https://github.com/ymiya55/freecad-fem-mcp/actions/workflows/security.yml/badge.svg)](https://github.com/ymiya55/freecad-fem-mcp/actions/workflows/security.yml)
[![CodeQL](https://github.com/ymiya55/freecad-fem-mcp/actions/workflows/codeql.yml/badge.svg)](https://github.com/ymiya55/freecad-fem-mcp/actions/workflows/codeql.yml)

FreeCAD 1.1.x の新しい `SolverCalculiX` フレームワークを、MCPクライアントからGUI付きで操作するためのWindows向けMCPサーバーです。外部のstdio MCPプロセスと、FreeCAD内で動く最小Addonを、認証付きlocalhostブリッジで接続します。

旧 `SolverCcxTools` / `femtools.ccxtools` には対応しません。

## 対応環境

- Windows
- FreeCAD `>=1.1.3,<1.2`
- Python 3.11以上
- [uv](https://docs.astral.sh/uv/)
- FreeCADに同梱または設定されたGmsh / CalculiX

検証環境はFreeCAD 1.1.3、Python 3.11.14、Gmsh 4.15.0、CalculiX 2.22です。

## 現在の範囲

初期リリースは既存形状に対する3D線形静解析の縦切りを対象にします。

- 開いているFCStd、または許可ルート内のモデルを使用
- GUI選択または明示的なObject/Face参照
- 等方線形弾性材料
- fixed / displacement / force / pressure / selfweight
- FreeCAD 1.1のネイティブGmshメッシャー
- FreeCAD 1.1のネイティブ`CalculiXTools`
- `Fem::FemPostPipeline`による結果照会とGUI表示
- GUIビューポートまたはウィンドウのキャプチャ

非線形・接触、固有値・座屈、熱連成、電磁解析は同じ公開設計上で段階的に追加します。

## セットアップ

依存関係を作成します。

```powershell
uv sync --extra dev
```

まず変更内容を確認できます。

```powershell
.\scripts\install.ps1 -WhatIf
```

AddonだけをユーザーのFreeCAD Modディレクトリへ導入する場合:

```powershell
.\scripts\install.ps1 -SkipMcpConfig
```

FreeCAD 1.1.xではAddonは`%APPDATA%\FreeCAD\v1-1\Mod\FreeCADFEMMCP`へ導入されます。更新時のバックアップは、FreeCADが古いコピーをAddonとして読み込まないよう`%APPDATA%\FreeCAD\v1-1\FreeCADFEMMCP-backups`へ保存します。

特定のMCPクライアント設定へ登録する場合は、設定ファイルを明示します。既存ファイルは変更前にバックアップされます。

```powershell
.\scripts\install.ps1 -McpConfigPath "<MCP client config path>"
```

登録されるstdioコマンドは次と同等です。

```json
{
  "command": "uv",
  "args": ["run", "--project", "<repository path>", "freecad-fem-mcp"]
}
```

その後FreeCADを起動します。AddonはFreeCAD起動時にloopbackブリッジを開始し、MCPサーバーは `%LOCALAPPDATA%\freecad-fem-mcp\bridge-v1.json` から接続情報を検出します。

`open_model`を使う場合は許可ルートが必須です。環境変数`FREECAD_FEM_ALLOWED_ROOTS`へWindowsではセミコロン区切りで設定するか、FreeCADの`User parameter:BaseApp/Preferences/Mod/FreeCADFEMMCP`にある`AllowedRoots`を設定します。未設定でも、GUIで既に開いているドキュメントは操作できます。

導入状態の確認と削除:

```powershell
.\scripts\check.ps1 -SkipMcpConfig
.\scripts\uninstall.ps1 -SkipMcpConfig
```

## MCPツール

| 分類 | ツール |
|---|---|
| 状態・GUI | `get_status`, `inspect_document`, `get_selection`, `set_view`, `capture_gui` |
| ファイル | `open_model`, `save_document` |
| 解析構築 | `create_analysis`, `assign_material`, `add_constraint`, `create_mesh`, `validate_analysis` |
| ジョブ | `start_analysis`, `get_job`, `list_jobs`, `cancel_job` |
| 結果 | `get_results`, `show_result` |

公開ツールごとに入力スキーマと副作用annotationを固定しています。汎用action、任意Python、任意シェル、任意INP、任意ファイル読取ツールはありません。

## 基本ワークフロー

1. FreeCADでFCStdを開くか、`open_model`を使います。
2. 拘束を与える面をGUIで選択し、`get_selection`で確認します。
3. `create_analysis`でAnalysisと新`SolverCalculiX`を作成します。
4. `assign_material`でPa・kg/m³単位の材料値を設定します。
5. `add_constraint`で拘束を追加します。targetsを省略した場合は現在のGUI選択を使います。
6. `create_mesh`でGmshジョブを開始し、`get_job`で完了を待ちます。
7. `validate_analysis`でFreeCAD公式のCalculiX事前検証を通します。
8. `start_analysis`でCalculiXジョブを開始します。
9. `get_results` / `show_result` / `capture_gui`で数値とGUIを検証します。
10. 保存が必要な場合だけ`save_document`を明示的に呼びます。

解析オブジェクトの変更はFreeCADのUndoトランザクションに入ります。自動保存は行いません。既存ファイルを上書きする場合は`overwrite=true`と一致する`expected_revision`が必要です。

## 開発・検証

```powershell
uv run --extra dev pytest
uv run --extra dev ruff check .
uv run --extra dev bandit -c .bandit -r src addon security scripts
uv run --extra dev pip-audit --skip-editable
.\scripts\run_security_tests.ps1 -Python ".\.venv\Scripts\python.exe"
```

詳細は[アーキテクチャ](docs/architecture.md)、[安全性](docs/security.md)、[開発ガイド](docs/development.md)を参照してください。

Codex、Claude Desktop、MCP Inspectorへの接続方法と検証プロンプトは[MCPクライアント設定](docs/clients.md)にまとめています。

非線形、接触、固有振動、座屈へ拡張する順序と安全なAPI境界は[次期解析機能の設計](docs/roadmap.md)を参照してください。

## ライセンス

MIT License
