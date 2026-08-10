# ツールリファレンス

[English](tool-reference.md) · [READMEへ戻る](../README.ja.md)

MCPは以下の固定ツールを公開します。必須field、値の範囲、戻り値の正確な形は実行時MCP schemaが正です。このページではCAE技術者が各ツールをいつ使うかを説明します。

このツール群にCADモデリングツールはありません。`open_model`は既存形状を開くもので、形状の作成、変更、defeaturing、repairは行いません。

## 共通規則

- field名に`mm`と明記されない限り、工学値はSI単位です。
- アクティブドキュメントでは`document_id`を省略できますが、複数ドキュメントを開く場合は明示する方が安全です。
- `analysis_id`と`job_id`は作成・開始ツールが返します。名前を推測せず、返された値を使います。
- entity参照には正確なFreeCAD object nameとsubelementを使用します。

```json
{
  "object_name": "Cantilever",
  "subelements": ["Face1"]
}
```

- 対応ツールでは空の`targets`が現在のFreeCAD GUI選択を意味します。remote条件と要素特性には明示的なtargetsが必要です。
- モデル変更は自動保存されません。

## 状態とGUI

| ツール | 用途 | 主な入力・注意点 |
|---|---|---|
| `get_status` | bridge、FreeCAD版、実行時capabilityを確認 | 最初に実行し、`future_gates`は非対応機能として扱う |
| `inspect_document` | アクティブドキュメント、object、analysis、revisionを取得 | 任意の`document_id` |
| `get_selection` | 現在のGUI選択を取得 | 選択を使う変更操作の直前に実行 |
| `set_view` | FreeCADカメラを変更 | `front`、`rear`、`left`、`right`、`top`、`bottom`、`isometric`、任意のfit |
| `set_visibility` | FreeCADツリーobjectを表示、非表示、または単独表示 | `inspect_document`の正確なobject名と、`show`、`hide`、`isolate`、`show_all`、`hide_all` |
| `capture_gui` | viewportまたはFreeCAD windowを取得 | 幅・高さ16〜8192、PNG/JPEG |

## ファイル

| ツール | 用途 | 主な入力・注意点 |
|---|---|---|
| `open_model` | 許可ルート内のモデルを開く | boundedな絶対パス |
| `save_document` | 許可パスへ保存 | 既存ファイル上書きには`overwrite=true`と一致する`expected_revision`が必要 |

## 解析定義

| ツール | 用途 | 主な入力・注意点 |
|---|---|---|
| `create_analysis` | native `SolverCalculiX`解析を作成 | `static`、`frequency`、`buckling`。非線形・増分設定はstatic用 |
| `assign_material` | globalまたは領域材料を割当 | Pa、kg/m³、任意の硬化則・降伏点 |
| `assign_element_geometry` | shell/membrane板厚、beam/truss断面を定義 | shellは明示Face、beamは明示Edge、寸法はm |
| `add_boundary_condition` | fixed、displacement、pin、rollerを追加 | 推奨する型付き支持API。回転はbeamを含む解析だけ |
| `add_load` | force、pressure、gravity、acceleration、centrifugalを追加 | field名に応じてN、Pa、m/s²、Hz |
| `add_remote_load` | global remote force/momentを追加 | 明示結合領域と参照点、NとN·m |
| `add_remote_displacement` | global remote translation/rotationを追加 | 明示結合領域、mとrad、`null`は自由DOF |
| `add_connection` | Tie、Contact、cyclic symmetryを追加 | slave Faceとmaster Faceを各一面 |
| `add_constraint` | 共面性MPC、座標変換、互換用constraintを追加 | 新規手順では型付きboundary/loadツールを優先 |
| `create_mesh` | native Gmsh mesh jobを開始 | 要素サイズmm、一次/二次、`1d`/`2d`/`3d` |
| `validate_analysis` | 解析前検証 | すべての解析前に`strict=true`を使用 |

### `create_analysis`の主な設定

- `analysis_type="static"`: 任意の`geometrical_nonlinearity`、`material_nonlinearity`、自動増分、四つの時間値、最大increment数。
- `analysis_type="frequency"`: `eigenmodes_count`、任意の周波数下限・上限pair。
- `analysis_type="buckling"`: `buckling_factors`、`buckling_accuracy`。

時間値を明示する場合はinitial、minimum、maximum、periodをすべて指定し、`minimum ≤ initial ≤ maximum ≤ period`を満たします。

### `assign_element_geometry`の種類

- `kind="shell"`: `thickness_m`、任意の`offset`、`formulation="shell"|"membrane"`。
- `kind="beam_section"`: `rectangular`、`circular`、`pipe`、`elliptical`、`box`、`truss`と、その断面だけに必要な寸法。
- `kind="beam_rotation"`: 明示beam Edgeの`rotation_rad`。

### 境界条件

- `fixed`: 適用可能な全自由度を固定。
- `displacement`: nullableな並進3成分、beamでは回転3成分も指定可能。数値0は固定、`null`は自由。
- `pin`: 並進を固定し、回転を自由にする。
- `roller`: `axis`または軸方向単位`normal_m`でglobal並進1自由度を固定。

### 荷重

- `force`: 明示targetまたは現在選択へ`force_n`。
- `pressure`: Faceへ`pressure_pa`。
- `gravity` / `acceleration`: 3成分の`acceleration_m_s2`。
- `centrifugal`: `rotation_frequency_hz`と一本の直線Edge軸。空targetsで全要素を指定可能。

### 接触・結合

- Tieには`tolerance_m`と`adjust`が必要です。
- Contactは`surface_behavior="hard"|"linear"|"tied"`を使います。Linear/Tiedには正のnormal stiffnessが必要です。摩擦にはさらに摩擦係数と正のstick stiffnessが必要です。
- Cyclic symmetryにはtolerance、adjust、`sectors`、`connected_sectors`が必要で、現在はnative原点/global +Z軸を使います。

## ジョブ

| ツール | 用途 | 主な入力・注意点 |
|---|---|---|
| `start_analysis` | native CalculiX jobを開始 | validation成功後だけ実行 |
| `get_job` | mesh/solver jobを一件取得 | 返された`job_id`をterminal stateまで確認 |
| `list_jobs` | boundedなjob一覧を取得 | 任意の`analysis_id` filter |
| `cancel_job` | queued/running jobをキャンセル | analysis定義自体は削除しない |

terminal stateは不変として扱います。失敗した場合は、報告されたモデルまたは環境原因を修正してから再実行します。

## 結果

| ツール | 用途 | 主な入力・注意点 |
|---|---|---|
| `get_results` | boundedな数値結果を取得 | `displacement`、`stress`、`strain`、`von_mises`、`max_items`最大10,000 |
| `show_result` | FreeCADへ結果fieldを表示 | 静解析`frame`、または固有振動・座屈`mode` |

静解析pipeline frameは0始まり、固有振動・座屈modeは1始まりです。非ゼロstatic frameとmodeは同時指定できません。reactionは公開結果ではありません。

## 推奨呼出し順序

```text
get_status
→ inspect_document
→ create_analysis
→ assign_material
→ assign_element_geometry（必要な1D/2D解析）
→ add_boundary_condition / add_load / add_connection
→ create_mesh → get_job
→ validate_analysis
→ start_analysis → get_job
→ get_results → show_result → set_visibility（任意）→ capture_gui
→ save_document（任意）
```
