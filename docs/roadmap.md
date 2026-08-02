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
   `interactions`、`result_kinds`を返します。
2. `create_analysis`の`analysis_type`は、実装済みのLiteralだけを段階的に増やします。
3. solver固有値は、新しい`configure_solver`で解析種別ごとのdiscriminated unionとして
   受け取ります。無関係な組み合わせはPydanticとAddonの両方で拒否します。
4. 非線形材料は`assign_nonlinear_material`、面間相互作用は`add_interaction`として、
   既存の`add_constraint`から分離します。
5. `validate_analysis`はFreeCADの事前検証に加えて、解析種別ごとの構成、単位、参照、
   数値範囲、結果要求を検査します。
6. `get_results`は値だけでなく、モード番号、座屈係数、収束状態、増分、警告を
   boundedな構造化データで返します。

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
  "kind": "contact",
  "primary": {"object_name": "Upper", "subelements": ["Face3"]},
  "secondary": {"object_name": "Lower", "subelements": ["Face7"]},
  "parameters": {
    "surface_behavior": "hard",
    "friction_coefficient": 0.2
  }
}
```

## 実装順序

### R1: 固有振動と線形座屈

最初に`frequency`と`buckling`を追加します。既存の線形静解析と同じ材料・拘束・
メッシュ経路を再利用でき、非線形収束や面の主従関係を導入せずに、解析種別ごとの
設定・結果APIを検証できるためです。

- 固有振動: モード数1〜100、下限・上限周波数、モード別変位表示
- 線形座屈: 座屈係数1〜100、正の精度、モード別形状表示
- 不正なモード番号、剛体モードだけのモデル、質量密度不足を明示的に診断

### R2: 幾何学的非線形と材料非線形

静解析に限定して、solverの`GeometricalNonlinearity`と`MaterialNonlinearity`を
有効化します。時間増分は安全な範囲を持つ明示フィールドとし、CalculiXの自由形式
iteration control文字列は初期段階では公開しません。

- 幾何学的非線形: 自動増分、初期・最小・最大増分、期間、最大増分数
- 材料非線形: 等方硬化または移動硬化、線形母材へのLink、応力・塑性ひずみ点列
- 降伏点は件数を制限し、有限値、応力増加、塑性ひずみ非減少、単位を検査
- job結果に収束/未収束、最終増分、CalculiXの安全に要約した診断を含める

### R3: Tie

`Fem::ConstraintTie`を先に公開します。2面を厳密に要求し、GUIで選択順を確認できる
`primary`/`secondary`表現を使います。許可する初期パラメータは非負の`tolerance`と
`adjust`に限定し、周期対称は別機能として後回しにします。

### R4: Contact

接触は最も不安定になりやすいため最後に追加します。初期版は3D solid-to-solid、
面1枚対面1枚、静解析だけに限定します。

- surface behaviorは`hard`から開始し、検証後に`linear`を追加
- 摩擦係数は0以上の有限値で上限を設ける
- contact stiffness、stick slope、clearance adjustmentは単位付き・有界入力
- thermal contact、shell contact、多面自動ペアリングは初期対象外
- 主従面の向き、初期gap/penetration、面の重複、同一面指定を事前診断

## 受け入れ条件

各リリースは、既存の線形静解析を壊さないことに加え、次を満たす必要があります。

| 領域 | 必須条件 |
|---|---|
| Contract | MCP schema、annotation、二重入力検証、未知フィールド拒否のテスト |
| FreeCAD | FreeCAD 1.1.x GUIで作成物、solver設定、結果表示を目視確認 |
| Native solver | `SolverCalculiX`と`CalculiXTools`だけを使用し、旧symbol scanに合格 |
| 数値 | 解析種別ごとに理論値または信頼できる参照値との誤差基準を固定 |
| 異常系 | 非収束、不正参照、単位誤り、欠落材料、cancel、GUI再接続を検証 |
| 安全性 | 任意コード/INP/パスを受けず、入力・ログ・結果がboundedかつsecret-redacted |
| CI | pytest、Ruff、Bandit、pip-audit、repository scan、Gitleaksが合格 |

基準問題は、固有振動の片持ちはり、Euler座屈柱、単軸弾塑性棒、2部品のtie、
圧縮接触ブロックを用意します。結果はGUIのスクリーンショットだけに頼らず、周波数、
座屈係数、荷重変位曲線、反力、接触圧を数値で判定します。

## リリース境界

一つのMCPツールに未完成機能をまとめて露出しません。R1〜R4は個別にfeature gateを
持ち、`get_status`が実行環境で合格済みの機能だけを通知します。FreeCAD 1.1.x内で
API差が見つかった場合は、バージョンごとのallowlistで安全側に拒否し、旧solverへ
fallbackしません。
