# 安全性

## 脅威モデル

MCPクライアント、モデル生成入力、FCStd内のLabel/メタデータ、プロセスログ、ファイルパスを信頼しません。一方、FreeCADとMCPクライアントは同じWindowsユーザー権限で実行されるローカルアプリケーションとして扱います。

この初期リリースはstdio専用です。HTTP待受、OAuth、外部サービスへの資格情報転送はありません。

## セキュリティ境界

- Addonは`127.0.0.1`だけにbindします。
- FreeCAD起動ごとに暗号学的乱数トークンを生成します。
- トークン比較は一定時間方式で行います。
- トークンはMCP結果・ログ・例外へ出しません。
- 接続レコードはユーザーのLocalAppDataに原子的に書き込みます。
- NDJSONは1フレーム、キュー、ログ、画像、文字列、配列に上限があります。
- 重複JSONキー、NaN/Infinity、未知フィールド、未知method/actionを拒否します。
- 全FreeCAD操作はmethod allowlistと型付きパラメーターを通ります。

## 禁止機能

- `eval` / `exec`
- `shell=True`
- ユーザー入力による動的import
- 任意Python・シェル・外部コマンド
- 任意CalculiX INP断片
- 任意ファイル・環境変数の列挙
- loopback以外へのbridge bind
- 旧CalculiX solver経路

## ファイル安全性

モデルのopen/saveは許可ルート内の正規化済みパスに限定します。次を拒否します。

- `..`による脱出
- UNCパス
- Windowsデバイスパス
- 代替データストリーム
- symlink/junction/reparse pointを経由する脱出
- 許可されていない拡張子

解析変更はメモリ上だけで、自動保存しません。既存ファイルの上書きには明示的な`overwrite`とドキュメントrevisionの一致が必要です。

## リリースゲート

以下をすべて満たさないビルドは配布しません。

- 全pytest成功
- adversarial/path/NDJSON/fuzz試験成功
- repository security scanner成功
- Bandit Medium/High未解決0件
- pip-audit既知脆弱性0件
- CodeQL High/Critical 0件
- secret scan検出0件
- 旧solver、任意コード実行、外部bind禁止チェック成功

ローカルの依存不要チェック:

```powershell
python scripts/security_scan.py
```

開発依存を含む安全性試験:

```powershell
.\scripts\run_security_tests.ps1 -Python ".\.venv\Scripts\python.exe"
```

方針は[MCP Security Best Practices](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices)を基準にします。
