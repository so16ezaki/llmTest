# Skills Index

このファイルはエージェントが参照するナレッジベースの索引です。
各スキルの名前と1行概要のみを含みます（本文はread_skillで取得）。

## フォーマット

```
- path: skills/{doc_name}/{section}.md
  name: スキル名
  summary: 1行概要
```

---

## 登録スキル一覧

<!-- ナレッジ取り込み時に knowledge_to_skills.py が自動追記 -->

- path: skills/example_api_docs/overview.md
  name: Example API Overview
  summary: サンプルAPIの概要・認証・エンドポイント一覧

- path: skills/example_api_docs/endpoints.md
  name: Example API Endpoints
  summary: 各エンドポイントのリクエスト・レスポンス仕様詳細

- path: skills/example_architecture/system_design.md
  name: Example System Architecture
  summary: システム全体のアーキテクチャ図・コンポーネント構成・データフロー

---

## 使い方

エージェントはこのファイルを参照して関連スキルを特定し、`read_skill`で本文を取得します。

1. `list_skills` — このindex.mdの内容を返す
2. `skill_search` — クエリに関連するスキルを推薦
3. `read_skill` — 指定スキルの全文を返す
4. `keyword_search` — 全スキルファイルをgrep検索
