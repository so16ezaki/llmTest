"""
system_prompt.py — システムプロンプトの動的生成

セッション開始時に以下を埋め込む:
  - エージェントの役割・ルール
  - skills/index.md（スキル一覧）
  - project_memory.md（永続メモリ、先頭25KB）
  - TODO状態
"""

from __future__ import annotations

import os

from config import LLM_BACKEND, MEMORY_FILE, MEMORY_LIMIT_BYTES, SKILLS_INDEX


_BASE_PROMPT = """\
あなたはローカルPythonエージェントです。
大規模な技術ドキュメント（スキルファイル）をナレッジとして使い、
ユーザーの質問・指示に対して自律的に検索・解析・ドキュメント生成を行います。

## 行動原則

- ツールを積極的に使い、情報が不足していると感じたらすぐ検索してください。
- 一度で全てを解決しようとせず、ターンを重ねて段階的に深掘りしてください。
- 最終回答はツール呼び出しなしのテキストのみで返してください。
- 必要に応じて todo_write でタスクを整理し、memory_write で重要な発見を保存してください。

## ツール使用ガイド

- まず list_skills や skill_search で関連スキルを特定してください。
- 詳細が必要なら read_skill でスキルファイルの全文を読んでください。
- キーワードで横断検索したい場合は keyword_search を使ってください。
- コード解析は scan_project → read_source → extract_structure の順で進めてください。
- 成果物は write_file で保存してください。

## コンテキスト管理

- get_status でトークン使用状況を確認できます。
- compact_now でコンテキストを手動圧縮できます。
"""


def build_system_prompt(todo_content: str = "") -> str:
    """
    現在のスキルインデックス・メモリ・TODOを埋め込んだシステムプロンプトを生成する。
    """
    parts = [_BASE_PROMPT]

    # Difyバックエンドの場合、ツール定義をプロンプトに含める
    # (Difyは function calling 非対応のため、テキスト+XMLで呼び出す)
    if LLM_BACKEND == "dify":
        from tool_registry import TOOL_DEFINITIONS_TEXT
        parts.append(f"\n{TOOL_DEFINITIONS_TEXT}")

    # skills/index.md
    index_content = _read_file_safe(SKILLS_INDEX)
    if index_content:
        parts.append(f"\n## 利用可能なスキル\n\n{index_content}")
    else:
        parts.append("\n## 利用可能なスキル\n\n（まだスキルが登録されていません）")

    # project_memory.md
    memory_content = _read_file_safe(MEMORY_FILE, max_bytes=MEMORY_LIMIT_BYTES)
    if memory_content:
        parts.append(f"\n## 永続メモリ (project_memory.md)\n\n{memory_content}")

    # TODO
    if todo_content:
        parts.append(f"\n## 現在のTODO\n\n{todo_content}")

    return "\n".join(parts)


def _read_file_safe(path: str, max_bytes: int | None = None) -> str:
    """ファイルを安全に読み込む。存在しない場合は空文字を返す。"""
    if not os.path.exists(path):
        return ""
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read(max_bytes) if max_bytes else f.read()
        return content
    except OSError:
        return ""
