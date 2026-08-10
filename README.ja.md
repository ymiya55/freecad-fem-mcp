# FreeCAD FEM MCP

[![CI](https://github.com/ymiya55/freecad-fem-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/ymiya55/freecad-fem-mcp/actions/workflows/ci.yml)
[![Security checks](https://github.com/ymiya55/freecad-fem-mcp/actions/workflows/security.yml/badge.svg)](https://github.com/ymiya55/freecad-fem-mcp/actions/workflows/security.yml)
[![CodeQL](https://github.com/ymiya55/freecad-fem-mcp/actions/workflows/codeql.yml/badge.svg)](https://github.com/ymiya55/freecad-fem-mcp/actions/workflows/codeql.yml)

[English](README.md)

FreeCAD FEM MCPは、AIアシスタントからFreeCAD GUI上のFEM解析を準備・実行・確認するためのMCPサーバーです。FreeCAD 1.1の`SolverCalculiX`、Gmsh、CalculiXを使用し、旧`SolverCcxTools`経路は使用しません。

> [!IMPORTANT]
> このMCPはFEM解析専用であり、CADモデリング機能はありません。FreeCADのアクティブドキュメント、または許可パスから開いたモデルに、解析対象の形状があらかじめ必要です。形状はFreeCADで手動作成するか、別のモデリングツールやMCPで準備してからFEM解析を開始してください。

## 使える解析機能

| 分類 | 現在の対応範囲 |
|---|---|
| 解析種類 | 静解析、固有振動解析、線形座屈解析 |
| モデル次元 | 3D solid、2D shell/membrane、1D beam/truss |
| 材料 | 等方線形弾性、単一step非線形静解析の等方硬化・移動硬化 |
| 拘束 | 固定、規定変位・回転、ピン、ローラー、リモート変位 |
| 荷重 | 力、圧力、重力、加速度、遠心力、リモート力・モーメント |
| 接触・結合 | Tie、native Contact、cyclic symmetry Tie、native共面性MPC |
| メッシュ・ソルバー | FreeCAD native Gmsh、CalculiX |
| 結果 | 変位、応力、ひずみ、von Mises応力、固有振動モード、座屈モード |

対応する組み合わせ、工学的な意味、現在の制限は[解析機能](docs/capabilities.ja.md)を参照してください。

## 必要環境

- Windows
- FreeCAD `>=1.1.3,<1.2`
- Python 3.11以上
- [uv](https://docs.astral.sh/uv/)
- FreeCADで設定されたGmshとCalculiX

検証済み環境はFreeCAD 1.1.3、Python 3.11.14、Gmsh 4.15.0、CalculiX 2.22です。

## Codexですぐに試す

PowerShellでこのリポジトリへ移動し、次を実行します。

```powershell
uv sync
.\scripts\install.ps1 -SkipMcpConfig
codex mcp add freecad-fem -- uv run --project "$PWD" freecad-fem-mcp
codex mcp get freecad-fem
```

続いて次の手順を行います。

1. FreeCADを再起動し、形状を含む`FCStd`モデルを開きます。
2. Codexを再起動するか、新しいタスクを開始します。
3. Codexへ次の接続確認を依頼します。

```text
freecad-fem MCPだけを使ってget_statusとinspect_documentを実行し、
FreeCADのバージョン、アクティブドキュメント、モデルオブジェクトを報告して。
シェルコマンドは使わないこと。
```

[最初の解析](docs/first-analysis.ja.md)では、片持ちはりを使って解析完了まで進めます。

Claude Desktop、その他のMCPクライアント、導入確認、更新、削除、インストーラースクリプトを使わない導入方法については、[セットアップ](docs/setup.ja.md)の[手動インストール](docs/setup.ja.md#手動インストール)を参照してください。

## 基本的な解析の流れ

1. FreeCADで既存モデルを開きます。
2. ドキュメントを確認し、GUIで面やエッジを選択します。
3. 解析を作成し、SI単位で材料を割り当てます。
4. 拘束、荷重、要素特性、接触・結合を設定します。
5. Gmshメッシュを作成し、メッシュジョブの完了を確認します。
6. 解析実行前の検証を行います。
7. CalculiXを開始し、ソルバージョブを監視します。
8. 数値結果を取得してFreeCADへ結果コンターを表示し、必要に応じて撮影対象のメッシュまたは結果objectだけを表示します。
9. 内容を確認した後、必要な場合だけ明示的に保存します。

## ドキュメント

### CAE技術者向け

- [セットアップ](docs/setup.ja.md) · [English](docs/setup.md)
- [構造解析例（英語）](docs/examples/README.md)
- [最初の解析](docs/first-analysis.ja.md) · [English](docs/first-analysis.md)
- [解析機能](docs/capabilities.ja.md) · [English](docs/capabilities.md)
- [トラブルシューティング](docs/troubleshooting.ja.md) · [English](docs/troubleshooting.md)
- [ツールリファレンス](docs/tool-reference.ja.md) · [English](docs/tool-reference.md)
- [日常的な解析ワークフロー](docs/daily-workflow.ja.md) · [English](docs/daily-workflow.md)

### 開発者向け（英語）

- [Architecture](docs/developer/architecture.md)
- [Development guide](docs/developer/development.md)
- [Security design](docs/developer/security.md)

## 安全性

公開するのは型が固定されたFEM操作だけです。任意Python、シェルコマンド、任意のCalculiX入力断片、動的import、無制限のファイルアクセスは提供しません。モデル変更はFreeCADのUndoトランザクションに入り、自動保存されません。既存ファイルの上書きには明示的な指定と一致するドキュメントrevisionが必要です。

## ライセンス

MIT License
