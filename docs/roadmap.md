# 次期解析機能の設計

## 目的と前提

この文書は、現在の3D線形静解析MVPから、FreeCAD 1.1.xの新しい
`Fem::SolverCalculiX`フレームワークだけを使って解析機能を拡張する方針を定めます。
旧`SolverCcxTools`、`femtools.ccxtools`、任意のCalculiX INP挿入は対象外です。

FreeCAD 1.1.3の実装で、次のネイティブ機能を確認しています。

- `SolverCalculiX.AnalysisType`: `static`、`frequency`、`buckling`など
- 幾何学的非線形、材料非線形、時間増分、固有値・座屈パラメータ
- `Fem::MaterialMechanicalNonlinear`
- `Fem::ConstraintTie`と`Fem::ConstraintContact`
- CalculiX結果の固有モード・座屈係数のimport

これはFreeCAD本体の`femobjects/solver_calculix.py`、
`material_mechanicalnonlinear.py`、`FemConstraintContact.cpp`およびCalculiX writerを
基準にした設計です。各機能は、実際のFreeCAD 1.1.x GUIと新solver pipelineで
統合試験に合格するまでMCPの公開capabilityに含めません。

## API設計の原則

公開ツールは用途別の固定スキーマにします。FreeCADの任意プロパティ名、Python、
シェル、CalculiXキーワードをクライアントから渡せる汎用APIは追加しません。

1. `get_status`は、実行中のFreeCADで検証済みの`analysis_types`、`materials`、
   `loads`、`boundary_conditions`、`connections`、`mpc_types`、`result_kinds`を返します。
2. `create_analysis`の`analysis_type`は、実装済みのLiteralだけを段階的に増やします。
3. solver固有値は、新しい`configure_solver`で解析種別ごとのdiscriminated unionとして
   受け取ります。無関係な組み合わせはPydanticとAddonの両方で拒否します。
4. 非線形材料は`assign_nonlinear_material`、面間相互作用は`add_interaction`として、
   既存の`add_constraint`から分離します。
5. `validate_analysis`はFreeCADの事前検証に加えて、解析種別ごとの構成、単位、参照、
   数値範囲、結果要求を検査します。
6. `get_results`は値だけでなく、モード番号、座屈係数、収束状態、増分、警告を
   boundedな構造化データで返します。
7. 一般構造解析の入力は、`add_load`、`add_boundary_condition`、`add_connection`、
   `add_mpc`の少数の分類済みツールへ整理し、各ツール内をdiscriminated unionにします。
   種類ごとにMCPツールを増殖させず、荷重と拘束を同じ曖昧な辞書にも混在させません。
8. 座標依存の入力はグローバル、直交ローカル、円筒座標を明示し、方向ベクトル、軸、
   原点を正規化・検証します。GUI選択順や暗黙の現在座標系には依存しません。

想定する入力の形は次のとおりです。名称は実装時にcontract testで固定します。

```json
{
  "analysis_name": "Analysis",
  "analysis_type": "buckling",
  "options": {
    "factors": 5,
    "accuracy": 0.01
  }
}
```

```json
{
  "connection_type": "contact",
  "slave": {"object_name": "Upper", "subelements": ["Face3"]},
  "master": {"object_name": "Lower", "subelements": ["Face7"]},
  "surface_behavior": "hard"
}
```

線形拘束方程式を公開する場合も、任意のCalculiX文ではなく、次のような有界の項リストを
受け取ります。自由度、係数、項数、右辺値を検証し、同じ自由度の重複や循環を拒否します。

```json
{
  "kind": "linear_equation",
  "terms": [
    {"target": {"object_name": "PartA", "subelements": ["Vertex1"]}, "dof": "ux", "coefficient": 1.0},
    {"target": {"object_name": "PartB", "subelements": ["Vertex2"]}, "dof": "ux", "coefficient": -1.0}
  ],
  "right_hand_side": {"value": 0.0, "unit": "mm"}
}
```

## 一般構造解析のカバレッジ目標

現在のMVPはfixed、displacement、remote displacement、force、pressure、gravity、
任意加速度、遠心力、remote force / momentを提供しています。
FreeCAD 1.1.xの新solver frameworkでネイティブに生成・検証・結果importできることを条件に、
次の範囲まで拡張します。

| 分類 | 対象にする種類 | 方針 |
|---|---|---|
| 集中荷重 | 節点・頂点・参照点への力、モーメント | 並進3成分と回転3成分、global/local座標、合力配分を明示 |
| 分布荷重 | 面圧、面traction、線・辺荷重 | normal/vector方向、総荷重/単位長さ/単位面積を別schemaにする |
| 物体荷重 | 重力、任意加速度、遠心力 | 密度必須、加速度ベクトルまたは回転軸・角速度を検証 |
| 温度起因荷重 | 規定温度、初期温度、温度差、熱ひずみ | thermomech対応段階で追加し、熱膨張係数と参照温度を必須化 |
| 規定変位 | 3軸並進、beam/shellの3軸回転、非ゼロ変位 | 自由/固定/指定値を自由度ごとに区別 |
| 理想支持 | 完全固定、ピン、ローラー、摩擦なし、対称・反対称 | 法線・軸・局所座標を明示し、形状種別との整合を検査 |
| 機械支持 | bearing、弾性支持・spring | 半径/軸方向、並進・回転剛性、単位と正値を検証 |
| リモート条件 | rigid body、remote force/moment、remote displacement | 参照点と結合領域を分離し、kinematic/distributing方式を列挙型にする |
| 接続 | tie、contact、spring/connector、gear、pulley | FreeCADネイティブobjectごとに専用schemaとGUI表示を持つ |
| 拘束方程式 | equal DOF、周期対称、rigid coupling、一般線形MPC | 代表的presetを優先し、一般式は有界項リストだけを許可 |
| 荷重履歴 | ramp、step、表形式amplitude | 時刻を単調増加、値を有限、点数を制限してFreeCADのamplitudeへ写像 |
| 荷重ケース | case、解析step、線形組合せ、結果envelope | solver実行単位と後処理組合せを区別し、係数と参照を固定schema化 |

追加候補には、bolt pretension、初期応力・初期ひずみ、基礎変位、質量・慣性要素、
damper、beam/connector releaseも含めます。ただしFreeCAD 1.1.xの新solver frameworkに
安全なネイティブ表現がないものはcapabilityを公開しません。任意INPや旧solverへの
fallbackでは補完せず、上流APIの追加または検証可能な専用adapterを待ちます。

### 拘束と荷重の事前診断

種類を増やすだけでなく、`validate_analysis`に次のモデル診断を追加します。

- 荷重または支持の参照が空、対象形状と自由度が不整合、方向ベクトルがゼロ
- 剛体運動が残る可能性、反対に同じ自由度を複数条件が矛盾して拘束する過拘束
- MPCの項不足、ゼロ係数、重複自由度、自己参照、循環、次元の異なる右辺
- tie/contact/remote coupling領域の重複と、同じ節点への競合する接続
- mass/densityが必要な固有振動・遠心力・重力解析で材料値が欠落
- beam/shell回転自由度をsolidだけの節点へ指定するなど、要素自由度との不整合
- amplitudeの時刻順、重複時刻、過大な点数、解析期間外のデータ
- 荷重ケース・組合せの循環参照、未知case、非線形caseの不正な線形重ね合わせ

## 実装順序

### R1: 荷重・境界条件の共通基盤

まず既存5種を分類済みAPIへ写像し、結果を変えないcontract testを固定します。その上で、
局所座標、集中モーメント、面traction、線荷重、任意加速度、遠心力、bearing、spring、
rigid body/remote条件を追加します。荷重振幅とcase識別子もこの段階でデータモデルを
確定しますが、非線形stepや組合せ実行は後続段階までfeature gateします。

- **R1.1 完了:** `add_load`と`add_boundary_condition`、capability契約、既存5種のFreeCAD 1.1.3 GUI写像、旧`add_constraint`互換、安全性境界
- **R1.2 調査完了・feature gate:** FreeCAD 1.1.3には独立した荷重座標系、集中モーメント、面traction、線・辺荷重のnative object/writerがないため未公開。任意INPでは補完しない
- **R1.3 完了:** `ConstraintRigidBody`によるglobal remote force / moment / displacement、selfweight写像による任意加速度、`ConstraintCentrif`による遠心力を実装し、FreeCAD 1.1.3 GUIで確認。bearingとspringはCalculiX writerがないためfeature gateを維持
- **R1.4 完了:** force、pressure、displacement、remote条件へ2〜256点のboundedなtabular amplitudeを追加し、FreeCADの`EnableAmplitude` / `AmplitudeValues`へnative写像。独立LoadCase・複数Stepのnative object/writerはないため、case識別子・実行・組合せはfeature gateを維持
- **R1.5 完了:** native `ConstraintDisplacement`とCalculiX `*BOUNDARY` writerを使い、pin（並進3自由度固定・回転自由）とglobal Cartesian roller（指定並進1自由度固定）を追加。explicit参照の形式・実在性、ゼロ自由度、明白な重複拘束、剛体運動、荷重方向、amplitude、body-load密度の事前診断も追加
- **R1将来計画:** frictionless、symmetry、antisymmetry、任意法線rollerは、FreeCAD 1.1.3に固定基準面の法線変位を表すnative object/writerがないため未実装。`ConstraintPlaneRotation` / CalculiX `*MPC,PLANE`は移動可能な節点群の共面性拘束であり、これらの支持条件の代用にはしない

### R2: 固有振動と線形座屈

次に`frequency`と`buckling`を追加します。既存の線形静解析と同じ材料・拘束・
メッシュ経路を再利用でき、非線形収束や面の主従関係を導入せずに、解析種別ごとの
設定・結果APIを検証できるためです。

- 固有振動: モード数1〜100、下限・上限周波数、モード別変位表示
- 線形座屈: 座屈係数1〜100、正の精度、モード別形状表示
- 不正なモード番号、剛体モードだけのモデル、質量密度不足を明示的に診断

**R2完了:** `create_analysis`で`frequency`と`buckling`を選択でき、
モード数1〜100、対で指定する周波数上下限、座屈係数数1〜100、正の精度を
`SolverCalculiX`のnative propertyへ写像します。FreeCAD 1.1.3 GUIで両解析objectを確認し、
strict validationへfrequencyの密度不足、bucklingの支持・荷重不足診断を追加しました。
`get_results` / `show_result`へ1始まりのboundedな`mode`選択を追加し、frequencyでは
`frequency_hz`、bucklingでは`buckling_factor`を返します。FreeCAD 1.1.3 native importerの
frequency mode N = Frame/Data block N−1、buckling mode N = Frame/Data block N（block 0は
preload）という差を吸収し、modeと非ゼロframeの曖昧な同時指定を拒否します。実CalculiX
ベンチマークでは一次固有振動数のEuler理論差0.146%、一次座屈係数差0.175%で、各5%以内の
受け入れ基準を満たしました。

### R3: 幾何学的非線形、材料非線形、荷重履歴

静解析に限定して、solverの`GeometricalNonlinearity`と`MaterialNonlinearity`を
有効化します。時間増分は安全な範囲を持つ明示フィールドとし、CalculiXの自由形式
iteration control文字列は初期段階では公開しません。

- 幾何学的非線形: 自動増分、初期・最小・最大増分、期間、最大増分数
- 材料非線形: 等方硬化または移動硬化、線形母材へのLink、応力・塑性ひずみ点列
- 降伏点は件数を制限し、有限値、応力増加、塑性ひずみ非減少、単位を検査
- force、pressure、displacement、rigid body条件のboundedなamplitudeを公開
- 独立した荷重caseと解析stepを導入し、非線形結果を線形重ね合わせしない
- job結果に収束/未収束、最終増分、CalculiXの安全に要約した診断を含める

**R3 native範囲完了:** static解析に限定し、`create_analysis`からnative
`GeometricalNonlinearity` / `MaterialNonlinearity`、自動増分、初期・最小・最大increment、期間、
最大increment数を設定できます。4つの時間値はすべて指定またはすべて省略とし、有限値・上限と
minimum ≤ initial ≤ maximum ≤ periodを三層で検証します。`assign_material`は1〜64点の
応力・塑性ひずみ列からnative `MaterialMechanicalNonlinear`を作り、等方／移動硬化writerへ
写像します。明示的なnative収束句だけをboundedなjob/result要約へ変換します。

**R3将来計画:** FreeCAD 1.1.3に独立LoadCase・複数解析Stepのnative object/writerがないため、
これらとstep間荷重履歴は実装しません。既存のbounded amplitudeは単一native step内だけで使い、
任意iteration control文字列や線形重ね合わせで補完しません。

### R4: 拘束方程式、remote coupling、Tie

equal DOF、rigid coupling、周期対称など、式を直接入力しなくて済むpresetから
実装します。一般線形MPCは、FreeCAD 1.1.xの新solver framework上でdocument object、
GUI表示、事前検証、CalculiX writer、結果再現がすべて確認できた場合だけ公開します。

`Fem::ConstraintTie`は2面を厳密に要求し、GUIで選択順を確認できる
`slave`/`master`表現を使います。許可する初期パラメータは非負の`tolerance`と
`adjust`に限定します。remote coupling、MPC、tieが同じ領域を重複拘束しないことも
検査します。

**R4 Tie初期実装完了:** `add_connection`の`slave`/`master`各1 Face、0〜1e6 mの
`tolerance_m`、strict boolの`adjust`を`ConstraintTie`へnative写像しました。cyclic symmetry、
plane rotationはnative object/writerがあるため後続実装対象です。equal DOF、一般線形MPC、
true rigid/distributing couplingはnative object/writerがないため将来計画です。

**R4 native範囲完了:** `add_constraint`の`plane_rotation`をnative
`ConstraintPlaneRotation` / CalculiX `*MPC,PLANE`へ写像し、実在するVertex・Edge・Face・Solid・
whole-shape参照だけを許可します。これは節点群の共面性MPCであり、frictionless/symmetry support
ではありません。`add_connection`の`cyclic_symmetry`はnative `ConstraintTie`のFace主従順序、
`CyclicSymmetry`、`Sectors`、`ConnectedSectors`へ写像します。対称軸は検証済みnative既定値の
原点・global +Zに限定し、任意Placementは公開しません。

**R4将来計画:** equal DOF、一般線形MPC、true rigid/distributing couplingにはFreeCAD 1.1.3の
native object/writerがないため実装しません。cyclic symmetryの任意軸入力も、GUI表示・writer・
数値ベンチマークを含む単位付きpresetを定義できるまで公開しません。

### R5: Contact

接触は最も不安定になりやすいため最後に追加します。初期版は3D solid-to-solid、
面1枚対面1枚、静解析だけに限定します。

- surface behaviorは`hard`から開始し、検証後に`linear`を追加
- 摩擦係数は0以上の有限値で上限を設ける
- contact stiffness、stick slope、clearance adjustmentは単位付き・有界入力
- thermal contact、shell contact、多面自動ペアリングは初期対象外
- 主従面の向き、初期gap/penetration、面の重複、同一面指定を事前診断

**R5 Contact初期実装完了:** static 3D Face-to-Face、Hard、frictionless、non-thermalに
限定した`ConstraintContact`を`add_connection`へ追加しました。同一面・stale Faceを拒否し、
摩擦、linear/tied挙動、熱接触は単位付き契約と数値ベンチマーク完了までfeature gateします。

**R5 native範囲完了:** static・non-thermal・Face-to-Faceのまま、native writerが持つHard／
Linear／Tiedへ拡張しました。Linear/Tiedでは正の法線剛性をSI `Pa/m`で要求します。摩擦は明示的な
bool、0より大きく10以下の無次元係数、正のstick剛性を同時に要求し、adjustは0〜1e6 mです。
FreeCAD 1.1.3実writerで、1e9 Pa/m→1 MPa/mm、3e9 Pa/m→3 MPa/mm、0.004 m→4 mmの
変換とHard／Linear／Tied出力を確認しました。異なるconnection種別のfieldは値がfalseでも存在で
拒否し、未知native propertyを通しません。

**R5将来計画:** thermal contact、shell contact、多面・自動ペアリング、任意native property、
自動gap/penetration修正は公開しません。接触圧・摩擦力の定量ベンチマークとGUIでの面方向診断を
追加できるまで、現在の明示Face対契約を維持します。

### R6: 荷重組合せと専門的な構造機能

線形静解析について、名称付き荷重case、係数付き組合せ、最大・最小・絶対値envelopeを
追加します。その後、FreeCAD 1.1.xでネイティブ対応を確認できたものからbolt
pretension、初期応力/ひずみ、質量・慣性、damper、connector releaseを個別に追加します。
設計基準固有の自動組合せ生成はMCP coreへ埋め込まず、検証済み係数を入力する層と分けます。

**FreeCAD 1.1.3 native監査:** LoadCase・複数解析Step・Combination・Envelope、bolt
pretension、機械的な初期応力/ひずみ、集中質量/回転慣性、damper、connector releaseには、
新solver frameworkのnative document objectとCalculiX writerの組がありません。したがって
R6は現行対応範囲ではすべて将来計画とし、任意INPや旧solverで補完しません。

**R6 gate実装完了:** 解析ツールや入力fieldは追加せず、上記9分類を
`get_status.capabilities.future_gates`へ安定したstatus-onlyリストとして公開します。全23公開routeで
同名fieldがunknownとして拒否されることをsecurity testで固定し、future gateが任意INP・native
property・legacy solverへの実行経路にならないことを確認します。

## 受け入れ条件

各リリースは、既存の線形静解析を壊さないことに加え、次を満たす必要があります。

| 領域 | 必須条件 |
|---|---|
| Contract | MCP schema、annotation、二重入力検証、未知フィールド拒否のテスト |
| FreeCAD | FreeCAD 1.1.x GUIで作成物、solver設定、結果表示を目視確認 |
| Native solver | `SolverCalculiX`と`CalculiXTools`だけを使用し、旧symbol scanに合格 |
| 数値 | 解析種別・荷重・支持・MPCごとに理論値または信頼できる参照値との誤差基準を固定 |
| 異常系 | 非収束、不正参照、単位誤り、欠落材料、過拘束、剛体運動、cancel、GUI再接続を検証 |
| 安全性 | 任意コード/INP/パスを受けず、入力・ログ・結果がboundedかつsecret-redacted |
| CI | pytest、Ruff、Bandit、pip-audit、repository scan、Gitleaksが合格 |

基準問題は、集中荷重を受ける片持ちはり、単純支持はり、内圧円筒、遠心回転円板、
弾性支持はり、remote coupling、線形MPC patch test、固有振動の片持ちはり、Euler
座屈柱、単軸弾塑性棒、2部品のtie、圧縮接触ブロックを用意します。結果はGUIの
スクリーンショットだけに頼らず、変位、反力、合力・合モーメント、ひずみエネルギー、
周波数、座屈係数、荷重変位曲線、接触圧を数値で判定します。

## リリース境界

一つのMCPツールに未完成機能をまとめて露出しません。R1〜R6は個別にfeature gateを
持ち、`get_status`が実行環境で合格済みの機能だけを通知します。FreeCAD 1.1.x内で
API差が見つかった場合は、バージョンごとのallowlistで安全側に拒否し、旧solverへ
fallbackしません。
