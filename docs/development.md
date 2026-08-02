# 開発ガイド

## リポジトリ構成

```text
src/freecad_fem_mcp/       stdio MCPサーバー
addon/FreeCADFEMMCP/       FreeCAD Addon
security/                  依存なしの安全性ポリシー
scripts/                   Windows導入・検査・安全性ツール
tests/                     単体・契約・安全性試験
docs/                      Sol管理ドキュメント
```

## 開発環境

```powershell
uv sync --extra dev
uv run pytest
```

FreeCAD内で動くAddonはサードパーティ依存を持ちません。FreeCAD 1.1.3同梱のPython 3.11、PySide、FEMモジュールだけを使用します。FreeCADを使わないprotocol/securityテストは通常のPythonで実行可能に保ちます。

## コード上の不変条件

- FreeCAD APIはAddonからのみ呼ぶ。
- FreeCADドキュメント操作はQt GUIスレッドだけで行う。
- 変更操作はUndoトランザクションで囲む。
- 外部プロセスを直接組み立てず、FreeCAD 1.1の`GmshTools` / `CalculiXTools`を使う。
- `stdout`はMCPプロトコル専用とし、診断は`stderr`へ出す。
- 公開MCPツールとbridge methodをallowlistに追加せず、汎用実行経路を作らない。
- 旧solver関連symbolを追加しない。

## テスト

```powershell
uv run --extra dev pytest
uv run --extra dev ruff check .
uv run --extra dev bandit -c .bandit -r src addon security scripts
uv run --extra dev pip-audit --skip-editable
uv run python scripts/security_scan.py
```

実FreeCADのheadless統合スモーク:

```powershell
$freecadRoot = Join-Path $env:LOCALAPPDATA "Programs\FreeCAD 1.1\bin"
& (Join-Path $freecadRoot "FreeCADCmd.exe") ".\tests\freecad_integration.py"
```

軸力棒の定量精度ベンチマーク:

```powershell
& (Join-Path $freecadRoot "FreeCADCmd.exe") ".\tests\freecad_accuracy_benchmark.py"
```

## FreeCAD統合試験

検証対象:

```text
%LOCALAPPDATA%\Programs\FreeCAD 1.1\bin\freecad.exe
%LOCALAPPDATA%\Programs\FreeCAD 1.1\bin\FreeCADCmd.exe
```

受入シナリオ:

1. AddonをユーザーModディレクトリへ導入する。
2. FreeCAD GUIを起動し、bridge-v1.jsonの生成とloopback待受を確認する。
3. 軸力棒またはカンチレバーfixtureを開く。
4. MCP経由でAnalysis、新Solver、材料を作り、`add_boundary_condition`と`add_load`でfixed、displacement、force、pressure、gravityを作る。
5. Gmshジョブを完了させ、ネイティブFemMeshが非空であることを確認する。
6. 公式CalculiX事前検証を成功させる。
7. CalculiXジョブを完了させる。
8. `solver.Results`に`Fem::FemPostPipeline`とテキスト出力があることを確認する。
9. 数値結果、GUI表示、スクリーンショットを確認する。
10. 無認証・不正入力・キャンセル・再接続時にドキュメント整合性が維持されることを確認する。

ジョブ試験では、queuedの即時キャンセル、runningのterminateとkillフォールバック、完了済み状態の不変性、未知job拒否、stdout/stderrのUTF-8正規化・上限・資格情報除去を確認します。再接続試験では同じMCP bridge clientを維持したままFreeCADを再起動し、新しいPID・port・トークンへ1回だけ更新されることを確認します。

現在のGUI縦切りリリースゲートは、Gmsh/CalculiXの正常終了、有限な結果値、非空の結果フィールド、GUI表示・画像取得、および安全性試験の全合格です。定量精度ベンチマークは、軸力棒の応力`F/A`と変位`FL/EA`に対して2.5 mmメッシュで2%以内を合格基準とします。

## 検証済みベースライン（2026-08-02）

- FreeCAD 1.1.3 / Python 3.11.14 / Gmsh 4.15.0 / CalculiX 2.22
- GUI自動起動した認証bridge経由でGmshとCalculiXが完了
- `Fem::FemPostPipeline`から13の解析結果フィールドと334値を取得
- 変位結果のGUI表示と1280×720 PNGキャプチャに成功
- 分類済みAPIからfixed、displacement、force、pressure、gravityをFreeCAD 1.1.3 GUI文書へ生成し、重力をグローバル`Fem::ConstraintPython`として確認
- 不正トークンによる解析変更を拒否し、FreeCADドキュメントが不変
- 軸力棒の応力10.0 MPa（理論10.0 MPa、誤差0%）
- 荷重端変位0.00473854 mm（理論0.00476190 mm、誤差0.4907%）
- 20公開ツールのroute/action対応、閉じたschema、未知フィールド・偽装action・非有限値・ゼロ重力・ネストした余剰フィールド拒否を安全性試験で確認
- 通常pytest（1件skip）、Ruff、repository scanner、敵対的security pytest、Bandit、pip-auditが合格

## ドキュメント

READMEと`docs/`は公開API・安全性境界と同時に更新します。コード変更によってツール名、単位、保存条件、対応FreeCAD版が変わる場合、同じ変更でドキュメントも更新してください。
