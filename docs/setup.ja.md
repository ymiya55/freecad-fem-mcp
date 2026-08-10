# セットアップ

[English](setup.md) · [READMEへ戻る](../README.ja.md)

このページは、WindowsワークステーションへFreeCAD FEM MCPを導入するCAE技術者向けです。内部的には次の二つを使用します。

- FreeCAD GUIが読み込む`FreeCADFEMMCP` Addon
- AIクライアントが起動するローカルMCPプロセス`freecad-fem-mcp`

付属スクリプトは現在のユーザープロファイル内だけにインストールし、管理者権限を必要としません。

次のいずれかの導入方法を選びます。

- **推奨:** 以下の手順1〜4に従い、`install.ps1`でAddonを導入する。
- **インストーラースクリプトを使わない:** [手動インストール](#手動インストール)へ進む。

## 1. 解析ソフトウェアを確認する

FreeCAD `>=1.1.3,<1.2`をインストールして起動します。FreeCADの設定で、FEMワークベンチからGmshとCalculiXを使用できることを確認してください。

Python 3.11以上と[uv](https://docs.astral.sh/uv/)もインストールし、PowerShellで確認します。

```powershell
python --version
uv --version
```

## 2. MCPサーバーを準備する

PowerShellでこのリポジトリへ移動し、実行に必要な依存関係を導入します。

```powershell
uv sync
```

`uv sync --extra dev`が必要なのは、開発やテストを行う場合だけです。

## 3. FreeCAD Addonをインストールする

最初に変更予定を確認できます。

```powershell
.\scripts\install.ps1 -SkipMcpConfig -WhatIf
```

Addonをインストールします。

```powershell
.\scripts\install.ps1 -SkipMcpConfig
```

FreeCAD 1.1では次の場所へ導入されます。

```text
%APPDATA%\FreeCAD\v1-1\Mod\FreeCADFEMMCP
```

インストーラーが管理している既存Addonは、置換前に`%APPDATA%\FreeCAD\v1-1\FreeCADFEMMCP-backups`へバックアップされます。インストールまたは更新後はFreeCADを再起動してください。

## 4. MCPクライアントへ登録する

### Codex

リポジトリのディレクトリで実行します。

```powershell
codex mcp add freecad-fem -- uv run --project "$PWD" freecad-fem-mcp
codex mcp get freecad-fem
```

登録後、Codexを再起動するか新しいタスクを開始します。

### Claude Desktop

インストーラーは既存のJSON設定をバックアップしてから安全に更新します。

```powershell
.\scripts\install.ps1 `
  -SkipAddon `
  -McpConfigPath "$env:APPDATA\Claude\claude_desktop_config.json"
```

登録後、Claude Desktopを完全に再起動します。

### その他のSTDIO MCPクライアント

次と同等のcommandと引数配列を設定します。

```json
{
  "command": "uv",
  "args": [
    "run",
    "--project",
    "C:\\absolute\\path\\to\\freecad-fem-mcp",
    "freecad-fem-mcp"
  ]
}
```

リポジトリには絶対パスを使用します。commandと引数を一つのシェル文字列へ結合しないでください。

## 手動インストール

付属の`install.ps1`でAddonをコピーしたり、MCPクライアント設定を変更したりしたくない場合は、次の手順で導入します。

### 1. Python環境を準備する

PowerShellでリポジトリへ移動し、次を実行します。

```powershell
uv sync
```

MCPサーバーはこのリポジトリ内に置いたまま、`uv run --project <repository path> freecad-fem-mcp`で起動します。FreeCAD同梱Pythonへインストールするものではありません。

### 2. FreeCAD Addonを手動コピーする

最初にFreeCADを終了します。次のコピー元が存在することを確認します。

```text
<repository>\addon\FreeCADFEMMCP
```

コピー先は次の場所です。

```text
%APPDATA%\FreeCAD\v1-1\Mod\FreeCADFEMMCP
```

コピー先がすでに存在する場合は作業を止め、先にrenameまたはbackupしてください。異なるAddonバージョンをmergeしないでください。コピー先が存在しない状態で、リポジトリのディレクトリから次を実行できます。

```powershell
$freecadModRoot = Join-Path $env:APPDATA "FreeCAD\v1-1\Mod"
New-Item -ItemType Directory -Path $freecadModRoot -Force | Out-Null
Copy-Item -LiteralPath ".\addon\FreeCADFEMMCP" `
  -Destination $freecadModRoot `
  -Recurse
```

最終的な配置を確認します。次のファイルがコピー先フォルダーの直下に必要です。`FreeCADFEMMCP`フォルダーが二重にならないよう注意してください。

```text
FreeCADFEMMCP\Init.py
FreeCADFEMMCP\InitGui.py
FreeCADFEMMCP\package.xml
```

### 3. MCPコマンドを手動登録する

Codexの場合:

```powershell
codex mcp add freecad-fem -- uv run --project "C:\absolute\path\to\freecad-fem-mcp" freecad-fem-mcp
codex mcp get freecad-fem
```

JSON設定を使用するクライアントでは、既存serverを残したまま`freecad-fem`だけを追加します。

```json
{
  "mcpServers": {
    "freecad-fem": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "C:\\absolute\\path\\to\\freecad-fem-mcp",
        "freecad-fem-mcp"
      ]
    }
  }
}
```

編集前にクライアント設定をバックアップしてください。クライアントによっては`mcpServers`ではなく`servers`など別のschemaを使用します。

### 4. 再起動して確認する

手動コピーしたAddonのentry pointを確認します。

```powershell
Test-Path "$env:APPDATA\FreeCAD\v1-1\Mod\FreeCADFEMMCP\InitGui.py"
```

期待される結果は`True`です。手動コピーにはインストーラーの所有マーカーがないため、`check.ps1`は「installer-managedではない」と報告します。これは想定どおりで、手動管理ディレクトリを自動アンインストーラーが勝手に所有しないための動作です。

FreeCADを起動し、MCPクライアントを再起動するか新しいタスクを開始します。続いて以下のMCP接続確認を実施します。

## 5. インストールを確認する

`install.ps1`で導入したAddonは、特定のMCPクライアント設定を仮定せずに次で確認できます。

```powershell
.\scripts\check.ps1 -SkipMcpConfig
```

続いてFreeCADを起動してモデルを開き、AIクライアントへ次のように依頼します。

```text
freecad-fem MCPだけを使ってget_statusとinspect_documentを実行し、
FreeCADのバージョン、アクティブドキュメント、モデルオブジェクトを報告して。
シェルコマンドは使わないこと。
```

正常ならFreeCADのバージョン、bridge状態、アクティブドキュメントが返ります。

## MCPからモデルを開く場合

最初はFreeCAD GUIから手動でモデルを開く方法が最も簡単です。`open_model`を使用する場合は、次のいずれかで許可ルートを設定します。

- 環境変数`FREECAD_FEM_ALLOWED_ROOTS`。Windowsでは複数パスをセミコロンで区切ります。
- FreeCADパラメーター`User parameter:BaseApp/Preferences/Mod/FreeCADFEMMCP/AllowedRoots`。

許可ルートが未設定でも、FreeCAD GUIですでに開いているモデルは操作できます。

## 更新

リポジトリを更新した後、次を実行します。

```powershell
uv sync
.\scripts\install.ps1 -SkipMcpConfig
```

FreeCADを再起動し、MCPクライアントでも新しいタスクを開始してください。

## アンインストール

インストーラー管理下のAddonについて、削除予定を確認します。

```powershell
.\scripts\uninstall.ps1 -SkipMcpConfig -WhatIf
```

削除を実行します。

```powershell
.\scripts\uninstall.ps1 -SkipMcpConfig
```

Claude Desktopの登録とAddonを一緒に削除する場合:

```powershell
.\scripts\uninstall.ps1 `
  -McpConfigPath "$env:APPDATA\Claude\claude_desktop_config.json"
```

Codexの登録は次のコマンドで削除します。

```powershell
codex mcp remove freecad-fem
```

アンインストーラーはFreeCAD、Python、uv、Gmsh、CalculiX、解析モデル、Addonバックアップを削除しません。

手動コピーしたAddonは意図的にinstaller-managedではありません。手動で削除する前に、正確な`%APPDATA%\FreeCAD\v1-1\Mod\FreeCADFEMMCP`ディレクトリを確認してバックアップしてください。周囲の`Mod`ディレクトリや他のAddonは削除しないでください。

導入できない場合は[トラブルシューティング](troubleshooting.ja.md)へ進んでください。
