# Example API Endpoints

<!-- サンプルナレッジファイル: 実際のAPIドキュメントから knowledge_ingest.py で生成 -->

## GET /users

ユーザー一覧を取得します。

**クエリパラメータ:**

| パラメータ | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| page | integer | No | ページ番号（デフォルト: 1） |
| limit | integer | No | 1ページあたりの件数（デフォルト: 20, 最大: 100） |
| sort | string | No | ソートキー（created_at, name） |

**レスポンス例:**

```json
{
  "data": [
    { "id": "u_123", "name": "Alice", "email": "alice@example.com" }
  ],
  "pagination": { "page": 1, "limit": 20, "total": 42 }
}
```

## POST /users

新しいユーザーを作成します。

**リクエストボディ:**

```json
{
  "name": "string (必須)",
  "email": "string (必須)",
  "role": "admin | member (デフォルト: member)"
}
```

**レスポンス:** 201 Created + 作成されたユーザーオブジェクト

## エラーレスポンス共通フォーマット

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "name is required",
    "details": []
  }
}
```

| HTTPステータス | コード | 意味 |
|--------------|--------|------|
| 400 | VALIDATION_ERROR | リクエストパラメータ不正 |
| 401 | UNAUTHORIZED | 認証失敗 |
| 404 | NOT_FOUND | リソースが存在しない |
| 429 | RATE_LIMIT_EXCEEDED | レート制限超過 |
| 500 | INTERNAL_ERROR | サーバー内部エラー |
