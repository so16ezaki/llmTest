# Dify ナレッジエージェント 実装計画

## プロジェクト概要

大規模技術ドキュメントをナレッジとして取り込み、自然言語で検索・解析・ドキュメント生成を行うローカルPythonエージェント。LLM推論のみDify Cloud APIを使用し、それ以外は全てローカル実行。

---

## フェーズ構成

```
Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → Phase 6 → Phase 7
 基盤       APIクライアント  ツール群   静的解析   リーダー   取り込みCLI  統合テスト
```

---

## Phase 1: 基盤設定（優先度: 最高）

**目標:** プロジェクト全体の設定・骨格を確立する

### タスク

| # | ファイル | 内容 | 工数目安 |
|---|---------|------|---------|
| 1-1 | `requirements.txt` | 依存ライブラリ定義 | 0.5h |
| 1-2 | `config.py` | 全設定値の一元管理 | 1h |
| 1-3 | `agent/` ディレクトリ構成 | 全ディレクトリ・空ファイル作成 | 0.5h |
| 1-4 | `knowledge/index.md` | ナレッジインデックス初期ファイル | 0.5h |
| 1-5 | `project_memory.md` | 永続メモリ初期ファイル | 0.5h |

### config.py 主要設定値

```python
DIFY_API_URL = "https://api.dify.ai/v1"
DIFY_API_KEY = ""           # 環境変数 DIFY_API_KEY から読み込み
CONTEXT_LIMIT = 100000      # トークン上限（モデルに合わせて調整）
COMPACTION_THRESHOLD = 0.92 # コンパクション発火閾値
MAX_TURNS = 30              # ループ上限
MEMORY_LIMIT_KB = 25        # project_memory.md 読み込み上限
KNOWLEDGE_DIR = "knowledge/"
MEMORY_FILE = "project_memory.md"
```

---

## Phase 2: Dify APIクライアント（優先度: 高）

**目標:** Dify Cloud APIとの通信を抽象化する

### タスク

| # | ファイル | 内容 | 工数目安 |
|---|---------|------|---------|
| 2-1 | `dify_client.py` | APIクライアント実装 | 2h |
| 2-2 | `tool_parser.py` | ツール呼び出しのパース | 1.5h |
| 2-3 | `tool_registry.py` | ツール名→関数マッピング + JSON Schema | 2h |

### 実装方針

- `dify_client.py`: `requests`ライブラリでREST呼び出し。function calling対応確認後、非対応時はXMLパースモードにフォールバック
- `tool_parser.py`: Difyがfunction callingネイティブ対応 → ネイティブ利用。非対応 → LLM出力からXMLタグ（`<tool_call>`, `<args>` 等）を正規表現でパース
- `tool_registry.py`: 全ツールのJSON Schemaを一元管理。`execute_tool(name, args)` を提供

### 確認事項（未決）

> Difyのfunction calling対応可否を最初に確認する。ネイティブ対応ならtool_parser.pyは最小実装で済む。

---

## Phase 3: ツール群実装（優先度: 高）

**目標:** エージェントが使う全ツールを実装する

### 3-1: ナレッジ検索ツール（`tools/search.py`）

| ツール | 実装内容 | 工数目安 |
|--------|---------|---------|
| `list_knowledge` | `knowledge/index.md` を読んで構造化して返す | 0.5h |
| `knowledge_search` | index.mdの内容をクエリでフィルタ・スコアリング | 1h |
| `read_knowledge` | 指定パスのナレッジファイル全文読み込み + リマインダー付与 | 0.5h |
| `keyword_search` | `knowledge/`配下を再帰的にgrep（正規表現対応）、前後N行付き | 1h |

### 3-2: コード解析ツール（`tools/code.py`）

| ツール | 実装内容 | 工数目安 |
|--------|---------|---------|
| `scan_project` | `os.walk`でファイルツリー構成を整形して返す | 0.5h |
| `read_source` | ファイル全文またはsymbol指定で関数/クラスのみ抽出 | 1h |
| `grep_source` | 指定パス配下をgrep（正規表現、前後行付き） | 0.5h |
| `extract_structure` | Phase 4のパーサーを呼び出し、JSON構造を返す | 1h |
| `static_analysis` | Phase 4の解析種別ディスパッチャーを呼び出す | 0.5h |

### 3-3: 計画・管理ツール（`tools/planning.py`）

| ツール | 実装内容 | 工数目安 |
|--------|---------|---------|
| `todo_write` | TODOリストをJSONまたはMarkdownで全体上書き保存 | 0.5h |
| `memory_write` | `project_memory.md`にキー付きセクションを追記/更新 | 1h |
| `memory_read` | `project_memory.md`から先頭25KB読み込み、キー指定時はセクション抽出 | 0.5h |

### 3-4: 出力・コンテキストツール

| ツール | ファイル | 実装内容 | 工数目安 |
|--------|---------|---------|---------|
| `write_file` | `tools/output.py` | 指定パスにファイル書き出し（md/mermaid/json等） | 0.5h |
| `compact_now` | `tools/context.py` | 手動コンパクション発火（compactor.py呼び出し） | 0.5h |
| `get_status` | `tools/context.py` | トークン使用量・残りバジェット・TODO状態を返す | 1h |

---

## Phase 4: 静的解析エンジン（優先度: 中）

**目標:** ローカルPythonで多言語静的解析を実現する

### ファイル構成

```
tools/
├── static_analysis.py     # 解析種別ディスパッチャー
└── parsers/
    ├── c_parser.py        # C/C++（tree-sitter優先、正規表現フォールバック）
    ├── python_parser.py   # Python（ast標準ライブラリ）
    ├── js_parser.py       # JS/TS（tree-sitter優先、正規表現フォールバック）
    └── generic_parser.py  # 汎用（正規表現ベース）
```

### 解析種別と実装優先度

| analysis | 優先度 | 実装方針 |
|----------|--------|---------|
| `metrics` | 最高 | 全言語共通。行数・関数数カウントのみ |
| `call_graph` | 高 | Python: ast。C: tree-sitter/正規表現 |
| `dependency_graph` | 高 | import/include文のパース |
| `complexity` | 高 | 制御フロー分岐カウント（if/for/while/switch） |
| `dead_code` | 中 | 定義と呼び出しの差分 |
| `symbol_table` | 中 | 全シンボル抽出 |
| `data_flow` | 低 | 変数の定義→参照追跡（複雑） |
| `control_flow` | 低 | 関数内ブロックグラフ（複雑） |
| `type_info` | 中 | typedef/struct/enum抽出 |
| `issues` | 中 | ヒューリスティック問題検出 |

### 実装方針

- tree-sitterは `try/except ImportError` でオプション扱い
- Python解析は `ast` モジュール（標準ライブラリ）を最大活用
- C/C++は正規表現ベースで80%精度を目標（マクロ展開は対象外）

---

## Phase 5: ドキュメントリーダー（優先度: 中）

**目標:** 各形式のドキュメントをMarkdownに変換する

### ファイル構成

```
readers/
├── pdf.py      # pymupdf4llm → Markdown
├── markdown.py # そのまま返す（前処理のみ）
├── html.py     # BeautifulSoup → Markdown変換
├── docx.py     # python-docx → Markdown
├── csv.py      # pandas → Markdownテーブル
└── code.py     # そのまま + コメント抽出
```

### リーダー選択ロジック

```python
EXTENSION_MAP = {
    ".pdf": pdf_reader,
    ".md": markdown_reader,
    ".txt": markdown_reader,
    ".html": html_reader, ".htm": html_reader,
    ".rst": rst_reader,   # docutils → md
    ".docx": docx_reader,
    ".xlsx": csv_reader, ".csv": csv_reader,
    # それ以外: code_reader（ソースコード扱い）
}
```

---

## Phase 6: ナレッジ取り込みCLI（優先度: 中）

**目標:** 任意ドキュメントをナレッジファイルに変換するCLIを実装する

### ファイル: `knowledge_ingest.py`

**処理フロー:**

```
入力ファイル/ディレクトリ
  → 拡張子でリーダー選択
  → Markdown変換
  → 章分割（H1/H2境界）
  → 小章統合（500文字未満を前後に結合）
  → 大章分割（30,000文字超を分割）
  → [オプション] Dify APIでLLM構造化
  → knowledge/{doc_name}/section_N.md として保存
  → knowledge/index.md を更新（ナレッジ名 + 1行概要を追記）
```

**CLIインターフェース:**

```bash
python knowledge_ingest.py <input_path> [--llm] [--name <doc_name>]
# --llm: LLMによる構造化を有効化
# --name: ナレッジ名を手動指定（省略時はファイル名から自動生成）
```

---

## Phase 7: エージェントループ + コンパクション（優先度: 最高）

**目標:** コアとなるエージェントループと3層コンパクションを実装する

### 7-1: `system_prompt.py` — システムプロンプト動的生成

- セッション開始時に `knowledge/index.md` + `project_memory.md`（先頭25KB）を読み込み
- ツール定義（JSON Schema）を埋め込み
- TODO状態を埋め込み

### 7-2: `compactor.py` — 3層コンパクション

| Tier | トリガー | 処理 | LLM使用 |
|------|---------|------|--------|
| Tier 1 | 毎ターン自動 | 古いツール結果を`[cleared]`に置換（直近5件保持） | なし |
| Tier 2 | Tier1で不足 | テーブル・装飾除去、長い結果を先頭+末尾に切り詰め | なし |
| Tier 3 | Tier2で不足 | LLMに構造化サマリーを生成させ、コンテキスト再構成 | あり |

### 7-3: `agent.py` — メインループ

```
エントリーポイント: agent_loop(user_input: str)

1. system_prompt.py でシステムプロンプト生成
2. while ループ開始（上限: MAX_TURNS）
   a. トークン使用量チェック（92%超でコンパクション発火）
   b. Dify API呼び出し
   c. tool_call なし → 最終回答を返してループ終了
   d. tool_call あり → execute_tool() 実行
   e. ツール結果 + TOOL_REMINDERS をメッセージに追加
3. MAX_TURNS超過 → エラーメッセージ返却
```

---

## Phase 8: 統合・テスト（優先度: 最高）

**目標:** エンドツーエンドで動作確認する

### テストシナリオ

| # | シナリオ | 確認項目 |
|---|---------|---------|
| T1 | PDFドキュメント取り込み | knowledge/配下にファイル生成, index.md更新 |
| T2 | 単純な質問（1ターン） | list_knowledge → knowledge_search → read_knowledge → 回答 |
| T3 | 複数ターンの検索 | keyword_search → read_knowledge → さらにkeyword_search |
| T4 | コード解析 | scan_project → extract_structure → static_analysis |
| T5 | コンパクション動作 | 長い会話でTier1→Tier2→Tier3が順に発火 |
| T6 | メモリ永続化 | memory_write後にセッション再起動してmemory_read確認 |

---

## 実装順序（推奨）

```
Week 1: Phase 1（基盤）+ Phase 2（APIクライアント）
Week 2: Phase 3（ツール群）+ Phase 7（エージェントループ）→ 最小動作版
Week 3: Phase 4（静的解析）+ Phase 5（リーダー）
Week 4: Phase 6（取り込みCLI）+ Phase 8（統合テスト）
```

> **最小動作版の定義:** `list_knowledge` / `read_knowledge` / `keyword_search` / `write_file` / `todo_write` の5ツールのみ実装し、エージェントループを動かす。静的解析・リーダーはPhase 4-5で後追い。

---

## 未決事項（要確認）

| # | 事項 | 影響範囲 |
|---|------|---------|
| U1 | Difyのfunction calling対応可否 | tool_parser.py の実装量が変わる |
| U2 | budget_usd制限を入れるか | config.py, agent.py |
| U3 | keyword_searchの事前インデックス構築 | ナレッジ数が多い場合にgrep速度が問題になる |
| U4 | tiktokenのClaudeトークン差（+10%マージン） | config.pyのCONTEXT_LIMIT設定 |
| U5 | サブエージェント導入タイミング | 単一ループで限界が来てから検討 |
