# Knowledge Index

このファイルはエージェントが参照するナレッジベースの索引です。
各ナレッジの名前と1行概要のみを含みます（本文はread_knowledgeで取得）。

## フォーマット

```
- path: knowledge/{doc_name}/{section}.md
  name: ナレッジ名
  summary: 1行概要
```

---

## 登録ナレッジ一覧

<!-- ナレッジ取り込み時に knowledge_ingest.py が自動追記 -->

- path: knowledge/example_api_docs/overview.md
  name: Example API Overview
  summary: サンプルAPIの概要・認証・エンドポイント一覧

- path: knowledge/example_api_docs/endpoints.md
  name: Example API Endpoints
  summary: 各エンドポイントのリクエスト・レスポンス仕様詳細

- path: knowledge/example_architecture/system_design.md
  name: Example System Architecture
  summary: システム全体のアーキテクチャ図・コンポーネント構成・データフロー

---

## 使い方

エージェントはこのファイルを参照して関連ナレッジを特定し、`read_knowledge`で本文を取得します。

1. `list_knowledge` — このindex.mdの内容を返す
2. `knowledge_search` — クエリに関連するナレッジを推薦
3. `read_knowledge` — 指定ナレッジの全文を返す
4. `keyword_search` — 全ナレッジファイルをgrep検索
