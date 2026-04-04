"""
backends/ollama.py — OllamaバックエンドのLLMクライアント

OllamaのOpenAI互換エンドポイント(/v1/chat/completions)を使用する。
"""

from __future__ import annotations

import json
from typing import Any

import requests

from config import OLLAMA_BASE_URL, OLLAMA_MODEL
from tool_parser import sanitize_content


_known_names: set[str] | None = None


def _get_known_tool_names() -> set[str]:
    """TOOL_DEFINITIONSから既知ツール名のセットを遅延構築する。"""
    global _known_names
    if _known_names is None:
        from tool_registry import TOOL_DEFINITIONS
        _known_names = {
            t["function"]["name"]
            for t in TOOL_DEFINITIONS
            if "function" in t
        }
    return _known_names


def chat(
    messages: list[dict],
    tools: list[dict] | None = None,
    model: str | None = None,
) -> "LLMResponse":
    """
    Ollama chat/completions を呼び出す。

    Parameters
    ----------
    messages:
        OpenAI形式のメッセージリスト
        [{"role": "user"|"assistant"|"system"|"tool", "content": "..."}]
    tools:
        JSON Schemaツール定義リスト（OpenAI形式）
    model:
        使用するOllamaモデル名。省略時はconfig.OLLAMA_MODELを使用

    Returns
    -------
    LLMResponse
        .content     : テキスト応答
        .tool_calls  : ツール呼び出しリスト [{name, args}]
        .has_tool_calls : ツール呼び出しがあるか
    """
    from dify_client import LLMResponse

    url = f"{OLLAMA_BASE_URL}/v1/chat/completions"
    payload: dict[str, Any] = {
        "model": model or OLLAMA_MODEL,
        "messages": _normalize_messages(messages),
        "stream": False,
    }
    if tools:
        payload["tools"] = tools

    try:
        resp = requests.post(url, json=payload, timeout=300)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise RuntimeError(f"Ollama API error: {e}") from e

    data = resp.json()
    return _parse_response(data)


def _normalize_messages(messages: list[dict]) -> list[dict]:
    """
    agent.py 内部形式 → OpenAI API形式に変換する。

    tool_callのメッセージは OpenAI形式:
      assistant: {"role": "assistant", "tool_calls": [...]}
      tool:      {"role": "tool", "tool_call_id": "...", "content": "..."}
    """
    normalized = []
    for msg in messages:
        role = msg.get("role", "")
        if role == "tool":
            # tool_call_idがなければ補完
            normalized.append({
                "role": "tool",
                "tool_call_id": msg.get("tool_call_id", "call_0"),
                "content": str(msg.get("content", "")),
            })
        elif role == "assistant" and "tool_calls" in msg:
            normalized.append(msg)
        else:
            content = msg.get("content", "")
            if isinstance(content, list):
                # contentがリストの場合は文字列に変換
                content = "\n".join(
                    c.get("text", "") if isinstance(c, dict) else str(c)
                    for c in content
                )
            normalized.append({"role": role, "content": content})
    return normalized


def _parse_response(data: dict) -> "LLMResponse":
    """OpenAI互換レスポンスをLLMResponseに変換する。"""
    from dify_client import LLMResponse

    choice = data.get("choices", [{}])[0]
    message = choice.get("message", {})

    content: str = message.get("content") or ""
    raw_tool_calls = message.get("tool_calls") or []

    tool_calls: list[dict] = []
    for tc in raw_tool_calls:
        fn = tc.get("function", {})
        name = fn.get("name", "")
        raw_args = fn.get("arguments", "{}")
        if isinstance(raw_args, str):
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError:
                args = {"raw": raw_args}
        else:
            args = raw_args
        tool_calls.append({
            "id": tc.get("id", "call_0"),
            "name": name,
            "args": args,
        })

    # contentのサニタイズ（JSON漏れ・<think>タグ除去）
    cleaned, fallback_calls = sanitize_content(
        content,
        has_tool_calls=bool(tool_calls),
        known_tool_names=_get_known_tool_names(),
    )
    if not tool_calls and fallback_calls:
        tool_calls = fallback_calls

    return LLMResponse(content=cleaned, tool_calls=tool_calls)
