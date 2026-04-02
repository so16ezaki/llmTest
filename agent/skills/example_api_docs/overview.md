# Example API Overview

<!-- このファイルはスキルファイルのサンプルです -->
<!-- knowledge_to_skills.py で実際のドキュメントから生成されます -->

## 概要

このスキルファイルはAPIドキュメントから生成されたナレッジの例です。
実際の運用では、PDFやMarkdownのAPIドキュメントを `knowledge_to_skills.py` で
変換したファイルがここに配置されます。

## 認証

- 認証方式: Bearer Token
- ヘッダー: `Authorization: Bearer {API_KEY}`
- APIキーの取得: 管理画面 > Settings > API Keys

## ベースURL

```
https://api.example.com/v1
```

## エンドポイント一覧

| メソッド | パス | 説明 |
|---------|------|------|
| GET | /users | ユーザー一覧取得 |
| POST | /users | ユーザー作成 |
| GET | /users/{id} | ユーザー詳細取得 |
| PUT | /users/{id} | ユーザー更新 |
| DELETE | /users/{id} | ユーザー削除 |

## レート制限

- 1分あたり: 60リクエスト
- 1日あたり: 10,000リクエスト
- 超過時: HTTP 429 (Too Many Requests)
