"""
dify_client.py — Ollamaバックエンドを使うLLMクライアント

OllamaのOpenAI互換エンドポイント(/v1/chat/completions)を使用する。
インターフェースはDify API互換に保つ（agent.pyからは差し替え透過）。
"""

from __future__ import annotations

import json
from typing import Any

import requests

from config import OLLAMA_BASE_URL, OLLAMA_MODEL


class LLMResponse:
    """LLM応答を統一形式で保持する。"""

    def __init__(self, content: str, tool_calls: list[dict]) -> None:
        self.content = content
        self.tool_calls = tool_calls

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    @property
    def answer(self) -> str:
        return self.content


def chat(
    messages: list[dict],
    tools: list[dict] | None = None,
    model: str | None = None,
) -> LLMResponse:
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


def _parse_response(data: dict) -> LLMResponse:
    """OpenAI互換レスポンスをLLMResponseに変換する。"""
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

    return LLMResponse(content=content, tool_calls=tool_calls)
