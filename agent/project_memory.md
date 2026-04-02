# Project Memory

このファイルはセッションを跨いで保持すべき情報を記録します（CLAUDE.md相当）。
エージェントが `memory_write` ツールで書き込み、セッション開始時に先頭25KBがロードされます。

---

## [project_info]

- プロジェクト名: Dify ナレッジエージェント
- 作成日: 2026-04-03
- 設計原則: "The agent is the model. The code is the harness."
- LLM: Dify Cloud API（モデルはconfig.pyで設定）

---

## [architecture_decisions]

- エージェントループ: while(tool_call) 単一ループ（マルチエージェント不使用）
- ツール結果リマインダー: TOOL_REMINDERS辞書でツール別に固定テキストを付与
- スキルロード: セッション開始時はindex.mdの概要のみ、本文はread_skill時にオンデマンドロード
- コンパクション: 3層（Tier1: ツール結果クリア / Tier2: ローカル圧縮 / Tier3: LLM要約）

---

## [open_questions]

- Difyのfunction calling対応可否（未確認）
- budget_usd制限の導入要否
- keyword_searchの事前インデックス要否（スキル数次第）

---

<!-- エージェントはここに新しい情報を memory_write ツールで追記します -->
