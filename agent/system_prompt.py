"""
system_prompt.py — システムプロンプトの動的生成

セッション開始時に以下を埋め込む:
  - エージェントの役割・ルール
  - knowledge/index.md（ナレッジ一覧）
  - project_memory.md（永続メモリ、先頭25KB）
  - TODO状態
"""

from __future__ import annotations

import os

from config import (
    LLM_BACKEND,
    MEMORY_FILE,
    MEMORY_LIMIT_BYTES,
    PROJECT_SUMMARY_KEY,
    KNOWLEDGE_INDEX,
)


_BASE_PROMPT = """\
あなたはローカルPythonエージェントです。
大規模な技術ドキュメント（ナレッジファイル）をナレッジとして使い、
ユーザーの質問・指示に対して自律的に検索・解析・ドキュメント生成を行います。

## 行動原則

- ツールを積極的に使い、情報が不足していると感じたらすぐ検索してください。
- 一度で全てを解決しようとせず、ターンを重ねて段階的に深掘りしてください。
- 最終回答はツール呼び出しなしのテキストのみで返してください。
- 必要に応じて todo_write でタスクを整理し、memory_write で重要な発見を保存してください。

## ツール使用ガイド

- まず list_knowledge や knowledge_search で関連ナレッジを特定してください。
- 詳細が必要なら read_knowledge でナレッジファイルの全文を読んでください。
- キーワードで横断検索したい場合は keyword_search を使ってください。
- コード解析は scan_project → read_source → extract_structure の順で進めてください。
- 成果物は write_file で保存してください。
- 部分処理されたドキュメントがある場合、get_knowledge_coverageで未処理範囲を確認できます。
- 未処理部分の情報が必要なら read_pdf_pages で直接読み取れます（自動でmd変換されます）。
- 重要な情報を見つけたら convert_pages_to_knowledge でナレッジファイルに変換してください。

## コンテキスト管理

- get_status でトークン使用状況を確認できます。
- compact_now でコンテキストを手動圧縮できます。

## サブエージェント

複雑なタスクでは sub_agent ツールで専門エージェントに委任できます:
- sub_agent(role="explorer"): ファイル探索・コード構造調査（読み取り専用）
- sub_agent(role="planner"): 計画策定・TODO作成・メモリ管理
- sub_agent(role="executor"): ファイル書き込み・編集実行

各サブエージェントには十分なコンテキスト（ファイルパス、調査結果など）を渡してください。

## 推奨ワークフロー

複雑なタスクでは以下のフェーズで進めてください:

1. **探索**: sub_agent(role="explorer") でファイル構成・コード構造を調査
2. **計画**: sub_agent(role="planner") でTODO作成・作業計画を策定
3. **実行**: sub_agent(role="executor") でファイル作成・編集を実行
4. **検証**: explorerに再調査を依頼するか、直接ツールで成果を確認

シンプルな質問にはサブエージェントを使わず直接回答してください。
"""

_AUTO_SUMMARY_PROMPT = """\

## 初回プロジェクト探索

永続メモリに project_summary が見つかりません。
最初のタスクの前に、以下を実行してプロジェクト全体像を把握してください:

1. sub_agent(role="explorer") で scan_project と extract_structure を実行
2. 結果をもとに memory_write(key="project_summary") でプロジェクト概要を保存
   - ディレクトリ構成と各ディレクトリの役割
   - 主要モジュール/ファイルの責務
   - データフロー・依存関係の概要
   - コーディング規約（命名規則、言語、フレームワーク等）

この概要は以後のセッションで自動的にロードされます。
"""


def build_system_prompt(todo_content: str = "") -> str:
    """
    現在のナレッジインデックス・メモリ・TODOを埋め込んだシステムプロンプトを生成する。
    """
    parts = [_BASE_PROMPT]

    # Difyバックエンドの場合、ツール定義をプロンプトに含める
    # (Difyは function calling 非対応のため、テキスト+XMLで呼び出す)
    if LLM_BACKEND == "dify":
        from tool_registry import TOOL_DEFINITIONS_TEXT
        parts.append(f"\n{TOOL_DEFINITIONS_TEXT}")

    # skills/index.md
    index_content = _read_file_safe(KNOWLEDGE_INDEX)
    if index_content:
        parts.append(f"\n## 利用可能なナレッジ\n\n{index_content}")
    else:
        parts.append("\n## 利用可能なナレッジ\n\n（まだナレッジが登録されていません）")

    # project_memory.md
    memory_content = _read_file_safe(MEMORY_FILE, max_bytes=MEMORY_LIMIT_BYTES)
    if memory_content:
        parts.append(f"\n## 永続メモリ (project_memory.md)\n\n{memory_content}")

    # project_summary が未生成の場合、自動生成を促す
    if not memory_content or PROJECT_SUMMARY_KEY not in memory_content:
        parts.append(_AUTO_SUMMARY_PROMPT)

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
