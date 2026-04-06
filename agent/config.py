"""
config.py — Dify ナレッジエージェント 設定
全設定値はここで一元管理。環境変数でオーバーライド可能。

LLM_BACKEND で Ollama / Dify を切り替える。
  - "ollama": OllamaのOpenAI互換API (/v1/chat/completions)
  - "dify":   Dify Cloud API (/v1/chat-messages, SSE streaming)

NOTE: .envファイルは意図的に読み込まない。
      python-dotenv等のライブラリは使用せず、os.getenv()でプロセス環境変数のみ参照する。
      設定を変更する場合はシェルで直接環境変数をセットするか、
      このファイルのデフォルト値を編集すること。
"""

import os


# ── LLMバックエンド選択 ──────────────────────────────────────
LLM_BACKEND: str = os.getenv("LLM_BACKEND", "ollama")  # "ollama" | "dify"

# ── Ollama API ────────────────────────────────────────────
# OllamaのOpenAI互換エンドポイント
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen3:4b")

# ── Dify Cloud API ────────────────────────────────────────
DIFY_API_URL: str = os.getenv("DIFY_API_URL", "https://api.dify.ai/v1")
DIFY_API_KEY: str = os.getenv("DIFY_API_KEY", "")
DIFY_RESPONSE_MODE: str = os.getenv("DIFY_RESPONSE_MODE", "streaming")
DIFY_USER: str = os.getenv("DIFY_USER", "agent-user")

# ── エージェントループ ────────────────────────────────────
MAX_TURNS: int = int(os.getenv("MAX_TURNS", "30"))

# ── コンテキスト管理 ──────────────────────────────────────
# モデルの最大コンテキスト長（トークン）
CONTEXT_LIMIT: int = int(os.getenv("CONTEXT_LIMIT", "60000"))

# コンパクション発火閾値（CONTEXT_LIMIT に対する割合）
COMPACTION_THRESHOLD: float = float(os.getenv("COMPACTION_THRESHOLD", "0.92"))

# Tier1: 保持するツール結果の直近件数
TIER1_KEEP_RESULTS: int = 5

# Tier2: ツール結果の最大トークン数（超過時に先頭+末尾に切り詰め）
TIER2_MAX_RESULT_TOKENS: int = 2000

# Tier3: 再構成時に保持するツール結果の直近件数・最大トークン数
TIER3_KEEP_RESULTS: int = 5
TIER3_MAX_RESULT_TOKENS: int = 50000

# tiktokenとClaudeのトークン差安全マージン（+10%）
TOKEN_SAFETY_MARGIN: float = 1.10

# ── 永続メモリ ─────────────────────────────────────────────
MEMORY_FILE: str = os.getenv("MEMORY_FILE", "project_memory.md")
MEMORY_LIMIT_BYTES: int = 25 * 1024  # 25KB

# ── スキル ────────────────────────────────────────────────
SKILLS_DIR: str = os.getenv("SKILLS_DIR", "skills")
SKILLS_INDEX: str = os.path.join(SKILLS_DIR, "index.md")

# ── ナレッジ取り込み ──────────────────────────────────────
# 章分割の最小文字数（これ未満は前後と統合）
SECTION_MIN_CHARS: int = 500

# 章分割の最大文字数（これ超過は分割）
SECTION_MAX_CHARS: int = 30000

# ── PDF並列処理 ──────────────────────────────────────────
# この値以上のページ数で並列処理を有効化
PDF_PARALLEL_THRESHOLD: int = int(os.getenv("PDF_PARALLEL_THRESHOLD", "100"))

# 並列処理時のチャンクサイズ（ページ数）
PDF_CHUNK_PAGES: int = int(os.getenv("PDF_CHUNK_PAGES", "50"))

# 並列ワーカー数
PDF_WORKERS: int = int(os.getenv("PDF_WORKERS", "4"))

# ページベース分割時のセクションあたりページ数（TOC/フォントサイズ検出失敗時のフォールバック）
PAGES_PER_SECTION_FALLBACK: int = int(os.getenv("PAGES_PER_SECTION_FALLBACK", "10"))

# ── ナレッジ処理上限 ─────────────────────────────────────
# 1回の取り込みで処理するスキルの累計トークン数上限（0 = 無制限）
# 上限到達時はセクション境界で停止し、残りは未処理として記録する
KNOWLEDGE_MAX_TOKENS: int = int(os.getenv("KNOWLEDGE_MAX_TOKENS", "0"))

# PDF読み込みページ数推定の基準（トークン/ページ）
# KNOWLEDGE_MAX_TOKENS > 0 の場合、max_pages = KNOWLEDGE_MAX_TOKENS // この値 で読み込みページ数を制限する
PDF_TOKENS_PER_PAGE_ESTIMATE: int = int(os.getenv("PDF_TOKENS_PER_PAGE_ESTIMATE", "500"))

# エージェント実行時のPDF直接読み取り最大ページ数（1回のツール呼び出しあたり）
PDF_RAW_READ_MAX_PAGES: int = int(os.getenv("PDF_RAW_READ_MAX_PAGES", "50"))

# ── キャッシュ ────────────────────────────────────────────
SKILLS_CACHE_FILE: str = os.getenv("SKILLS_CACHE_FILE", ".skills_cache.json")
ENABLE_CACHE: bool = os.getenv("ENABLE_CACHE", "1") == "1"

# ── ツール結果プレコンパクション ──────────────────────────
# 1ツール結果あたりのトークン上限（超過時は先頭+末尾に切り詰め）
TOOL_RESULT_MAX_TOKENS: int = int(os.getenv("TOOL_RESULT_MAX_TOKENS", "8000"))

# ── 検索ページネーション ─────────────────────────────────
SEARCH_PAGE_SIZE: int = int(os.getenv("SEARCH_PAGE_SIZE", "20"))

# ── サブエージェント ─────────────────────────────────────
SUB_AGENT_MAX_TURNS: int = int(os.getenv("SUB_AGENT_MAX_TURNS", "10"))
PIPELINE_VERIFY_RETRIES: int = int(os.getenv("PIPELINE_VERIFY_RETRIES", "2"))

# ── プロジェクト概要 ─────────────────────────────────────
PROJECT_SUMMARY_FILENAME: str = "_overview.md"
PROJECT_SUMMARY_KEY: str = "project_summary"

# ── 書き込み承認 ─────────────────────────────────────────
REQUIRE_WRITE_APPROVAL: bool = os.getenv("REQUIRE_WRITE_APPROVAL", "0") == "1"

# ── コスト管理（オプション・未実装） ──────────────────────
# BUDGET_USD: float = float(os.getenv("BUDGET_USD", "0"))  # 0 = 無制限
