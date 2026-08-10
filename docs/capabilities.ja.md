# 解析機能

[English](capabilities.md) · [READMEへ戻る](../README.ja.md)

FreeCAD FEM MCPは、FreeCAD 1.1がnative FEMオブジェクト、Gmsh、`SolverCalculiX`で表現できる範囲を自動化します。追跡可能な解析手順を目的としており、FreeCADやCalculiXの任意スクリプト実行環境ではありません。

## 解析専用であり、モデリング機能はない

このMCPはCAD形状を作成・編集しません。FEM解析を始める前に、次のいずれかで形状を準備します。

- FreeCADで手動作成・編集する。
- 既存の`FCStd`モデルを開く。
- 準備済みCAD形状をFreeCADへimportする。
- 別のモデリングツールやMCPで形状を作成し、そのFreeCADドキュメントをこのMCPへ引き継ぐ。

既存objectとFace/Edgeは確認できますが、作成対象はanalysis、material、element property、拘束、荷重、接触・結合、mesh、resultなどのFEM objectに限定されます。

## 解析種類

| 解析 | 対応範囲 | 主な出力 |
|---|---|---|
| 線形静解析 | 単一step構造解析 | 変位、応力、ひずみ、von Mises応力 |
| 非線形静解析 | boundedな時間増分を持つ単一stepの幾何学的・材料非線形 | 構造結果、native出力に存在する場合はboundedな収束要約 |
| 固有振動解析 | 指定モード数、任意の周波数範囲 | 1始まりのモード番号による固有振動数とモード形状 |
| 線形座屈解析 | 指定座屈係数数とソルバー精度 | 1始まりのモード番号による座屈係数とモード形状 |

固有振動解析には密度が必要です。座屈解析には有効な支持と事前荷重が必要です。すべての解析で実行前に`validate_analysis`を使用してください。

## モデル次元

| モデル | Native定義 |
|---|---|
| 3D solid | native 3D Gmsh経路でメッシュ化するSolid形状 |
| 2D shell | 明示Face参照、板厚、offset、曲げ剛性を持つshell formulation |
| 2D membrane | 明示Face参照、板厚、offset、面内剛性だけを持つmembrane formulation |
| 1D beam | 明示Edge参照、矩形・円形・Pipe・楕円・Box断面、任意の断面回転 |
| 1D truss | 明示Edge参照、断面積、曲げ剛性を除外したtruss |

1Dと2D解析ではメッシュ次元を明示します。beam/trussとshell/membraneはソルバーのelement modelを共有するため、一つの解析へ曖昧に混在できません。3Dへ展開表示されたbeam/shell結果でも、元モデルが1D/2Dである情報を保持します。

## 材料

次の材料値をSI単位で指定します。

- ヤング率: Pa
- ポアソン比: 無次元
- 密度: kg/m³
- 任意の降伏応力: Pa
- 等方硬化または移動硬化
- 材料非線形用の1〜64点の応力・塑性ひずみ点列

材料はglobal、または明示したEdge、Face、Solid領域へ割り当てられます。領域重複、globalと領域材料の曖昧な混在、stale参照、複数材料時の未割当領域は検証で拒否されます。

## 拘束と運動学的条件

- 固定支持
- 規定並進変位
- 1D beamを含む解析の規定回転
- ピン支持: 並進3自由度を固定し、回転を自由にする
- Cartesianローラー: global並進1自由度を固定する
- global参照点を介したリモート並進・回転
- 直交または円筒節点座標変換
- native CalculiX `*MPC,PLANE`共面性条件

共面性MPCは参照節点を移動可能な同一平面に保ちます。frictionless support、固定対称面、反対称支持ではありません。

## 荷重と振幅

- FreeCAD native forceオブジェクトによる集中または分布荷重
- 面圧
- 重力または任意加速度ベクトル
- 明示した一本の直線Edge軸まわりの遠心力
- globalリモート力・モーメント
- 対応するforce、pressure、規定変位、remote条件のboundedなtabular amplitude

振幅は2〜256点の時刻・倍率で指定します。時刻は0から始まり厳密増加、倍率は無次元です。独立LoadCase、任意のCalculiX step文字列、複数解析stepは公開しません。

## 接触・結合

| 種類 | 現在の対応範囲 |
|---|---|
| Tie | slave Faceとmaster Faceを各一面、toleranceとadjustを指定 |
| Contact | static・non-thermal、Hard・Linear・Tied法線挙動、任意のboundedな摩擦と剛性 |
| Cyclic symmetry | sector数を指定したnative tie、FreeCAD native原点とglobal +Z軸を使用 |

shell同士のTie/Contactも同じAPIを使用します。shell/solid混在pair、thermal contact、initial gap、penetration、接触面の自動探索、任意native property、任意のcyclic軸配置には対応しません。

## メッシュと解析実行

- FreeCAD native `GmshTools`
- 一次または二次メッシュ
- 明示的な1D、2D、3D経路
- FreeCAD native `CalculiXTools`
- 状態取得、一覧、キャンセルが可能な非同期メッシュ・ソルバージョブ
- FreeCAD/CalculiX公式の解析前検証

AddonはGmshやCalculiXの生のシェルコマンドを組み立てません。

## 結果と表示

- 変位、応力、ひずみ、von Mises応力のboundedな数値取得
- pipeline frameによる静解析結果の選択
- 1始まりのmode番号による固有振動・座屈結果の選択
- FreeCAD GUIへの結果表示
- 正面、背面、左、右、上、下、isometric表示
- 名前を指定したFreeCADツリーobjectの表示、非表示、単独表示、全表示、全非表示
- viewportまたはFreeCAD windowのPNG/JPEGキャプチャ

FreeCAD 1.1.3の検証済みnative結果オブジェクトに必要なreaction配列がないため、反力は公開していません。ゼロ値を作ったり、無制限の出力解析で補ったりしません。

## ファイルとドキュメント

- パス設定なしで、FreeCADですでに開いているドキュメントを操作
- 設定した許可ルート内だけでモデルをopen/save
- 明示的な保存だけを実行し、自動保存しない
- 既存ファイルの上書きには`overwrite=true`と一致するdocument revisionが必要
- モデル変更をFreeCAD Undoトランザクションへ登録

## 現在の非対応範囲

現在のリリースは次を提供しません。

- CAD形状の作成、編集、defeaturing、repair
- 熱、熱構造連成、電磁、静電解析
- 独立LoadCase、荷重組合せ、Envelope、複数解析step
- bolt pretension、集中質量・回転慣性、damper、connector release
- 一般的なfrictionless・symmetry・antisymmetry支持
- 任意Python、シェルコマンド、CalculiX INP断片、無制限ファイル読取り
- 旧`SolverCcxTools`または`femtools.ccxtools`

バージョン固有の対応機能と`future_gates`は実行時の`get_status`が正です。`future_gates`にある機能は部分対応ではなく、明示的な非対応機能です。
