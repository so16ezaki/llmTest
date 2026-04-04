"""
compactor.py — 3層コンパクション

Tier 1（毎ターン自動）: 古いツール結果を [cleared] に置換（直近5件保持）
Tier 2（Tier1で不足）: テーブル・装飾除去、長い結果を先頭+末尾に切り詰め
Tier 3（Tier2で不足）: LLM要約 + コンテキスト再構成

トークンカウントは tiktoken を使用。Claudeとの差分には +10% マージンを適用。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import tiktoken

from config import (
    COMPACTION_THRESHOLD,
    CONTEXT_LIMIT,
    TIER1_KEEP_RESULTS,
    TIER2_MAX_RESULT_TOKENS,
    TIER3_KEEP_RESULTS,
    TIER3_MAX_RESULT_TOKENS,
    TOKEN_SAFETY_MARGIN,
)

if TYPE_CHECKING:
    pass


# tiktokenはgpt-2エンコーダーを使用（Claude近似）
_ENCODER = tiktoken.get_encoding("cl100k_base")


# ── トークンカウント ──────────────────────────────────────────────

def count_tokens(text: str) -> int:
    """テキストのトークン数を返す（安全マージン適用済み）。"""
    return int(len(_ENCODER.encode(text)) * TOKEN_SAFETY_MARGIN)


def count_messages_tokens(messages: list[dict]) -> int:
    """メッセージリスト全体のトークン数を返す。"""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            for c in content:
                if isinstance(c, dict):
                    total += count_tokens(c.get("text", ""))
                else:
                    total += count_tokens(str(c))
        elif content:
            total += count_tokens(str(content))
        # tool_callsフィールドも計上
        if "tool_calls" in msg:
            import json
            total += count_tokens(json.dumps(msg["tool_calls"]))
    return total


def usage_ratio(messages: list[dict]) -> float:
    """現在のコンテキスト使用率（0.0〜1.0）を返す。"""
    used = count_messages_tokens(messages)
    return used / CONTEXT_LIMIT


def needs_compaction(messages: list[dict]) -> bool:
    """コンパクションが必要かどうかを返す。"""
    return usage_ratio(messages) >= COMPACTION_THRESHOLD


# ── Tier 1: 古いツール結果をクリア ───────────────────────────────

def tier1_compact(messages: list[dict]) -> list[dict]:
    """
    ツール結果（role=tool）のうち、古いものを [cleared] に置換する。
    直近 TIER1_KEEP_RESULTS 件は保持。
    """
    # tool メッセージのインデックスを収集
    tool_indices = [
        i for i, m in enumerate(messages) if m.get("role") == "tool"
    ]
    if len(tool_indices) <= TIER1_KEEP_RESULTS:
        return messages

    # 古い件数分をクリア
    to_clear = tool_indices[: len(tool_indices) - TIER1_KEEP_RESULTS]
    result = list(messages)
    for idx in to_clear:
        result[idx] = {**result[idx], "content": "[cleared]"}
    return result


# ── Tier 2: テキスト圧縮 ──────────────────────────────────────────

_TABLE_PATTERN = re.compile(r"\|.*\|.*\n", re.MULTILINE)
_DECORATION_PATTERN = re.compile(r"^[=\-*]{3,}$", re.MULTILINE)
_BLANK_LINES_PATTERN = re.compile(r"\n{3,}")


def _compress_text(text: str) -> str:
    """テーブル・装飾・余分な空行を除去してテキストを圧縮する。"""
    text = _TABLE_PATTERN.sub("", text)
    text = _DECORATION_PATTERN.sub("", text)
    text = _BLANK_LINES_PATTERN.sub("\n\n", text)
    return text.strip()


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """テキストを先頭+末尾に切り詰めてmax_tokens以内に収める。"""
    tokens = _ENCODER.encode(text)
    if len(tokens) <= max_tokens:
        return text
    half = max_tokens // 2
    head = _ENCODER.decode(tokens[:half])
    tail = _ENCODER.decode(tokens[-half:])
    return f"{head}\n\n... [中略] ...\n\n{tail}"


def tier2_compact(messages: list[dict]) -> list[dict]:
    """
    ツール結果のテキストを圧縮・切り詰めする。
    """
    result = []
    for msg in messages:
        if msg.get("role") == "tool" and msg.get("content") != "[cleared]":
            content = msg.get("content", "")
            content = _compress_text(content)
            content = truncate_to_tokens(content, TIER2_MAX_RESULT_TOKENS)
            result.append({**msg, "content": content})
        else:
            result.append(msg)
    return result


# ── Tier 3: LLM要約 + 再構成 ─────────────────────────────────────

_SUMMARY_PROMPT = """\
これまでの会話を要約してください。以下のセクションを含めてください:

1. セッションの目的
2. これまでに分かったこと
3. 参照したナレッジファイルと重要な情報
4. 実行した解析とその結果
5. 生成したファイル
6. 未解決の問題
7. 次にやるべきこと
8. TODOリストの現在の状態

要約は簡潔かつ情報密度が高いものにしてください。
"""


def tier3_compact(messages: list[dict], system_prompt: str) -> list[dict]:
    """
    LLMに会話の構造化サマリーを生成させ、コンテキストを再構成する。

    再構成後のメッセージ:
      [system] [context compacted]
      [assistant] <要約>
      [直近TIER3_KEEP_RESULTS件のtool結果]
    """
    import dify_client  # ローカルインポートで循環回避

    # 要約リクエスト用のメッセージを構築
    summary_messages = [
        {"role": "system", "content": system_prompt},
        *messages,
        {"role": "user", "content": _SUMMARY_PROMPT},
    ]

    try:
        response = dify_client.chat(summary_messages)
        summary = response.content or "（要約の生成に失敗しました）"
    except Exception as e:  # noqa: BLE001
        summary = f"（要約エラー: {e}）"

    # 直近のツール結果を保持
    tool_messages = [m for m in messages if m.get("role") == "tool"]
    recent_tools = tool_messages[-TIER3_KEEP_RESULTS:]

    # ツール結果もトークン上限内に収める
    compressed_tools = []
    for msg in recent_tools:
        content = truncate_to_tokens(
            msg.get("content", ""), TIER3_MAX_RESULT_TOKENS // len(recent_tools)
        )
        compressed_tools.append({**msg, "content": content})

    return [
        {"role": "system", "content": "[context compacted]\n\n" + system_prompt},
        {"role": "assistant", "content": summary},
        *compressed_tools,
    ]


# ── メインインターフェース ─────────────────────────────────────────

def compact(
    messages: list[dict],
    system_prompt: str,
    force_tier: int | None = None,
) -> list[dict]:
    """
    必要に応じてTier1→Tier2→Tier3の順でコンパクションを実行する。

    Parameters
    ----------
    messages:
        現在のメッセージリスト
    system_prompt:
        Tier3再構成に使うシステムプロンプト
    force_tier:
        強制的に指定Tierから実行する（テスト・手動用）

    Returns
    -------
    コンパクション後のメッセージリスト
    """
    start_tier = force_tier or 1

    if start_tier <= 1:
        messages = tier1_compact(messages)
        if not needs_compaction(messages):
            return messages

    if start_tier <= 2:
        messages = tier2_compact(messages)
        if not needs_compaction(messages):
            return messages

    # Tier3
    return tier3_compact(messages, system_prompt)
