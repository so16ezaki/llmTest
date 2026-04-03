"""
backends/ollama.py — OllamaバックエンドのLLMクライアント

OllamaのOpenAI互換エンドポイント(/v1/chat/completions)を使用する。
"""

from __future__ import annotations

import json
from typing import Any

import requests

from config import OLLAMA_BASE_URL, OLLAMA_MODEL


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

    resp = _request_with_retry(url, payload)
    if resp is None:
        raise RuntimeError("Ollama API error: all retries exhausted")

    data = resp.json()
    return _parse_response(data)


def _request_with_retry(
    url: str,
    payload: dict,
    max_retries: int = 3,
    timeout: int = 300,
) -> requests.Response:
    """リトライ付きHTTPリクエスト。exponential backoff。"""
    import time

    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
            if resp.status_code == 429:
                # レート制限: リトライ
                wait = 2 ** attempt
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        except (requests.ConnectionError, requests.Timeout) as e:
            last_err = e
            if attempt < max_retries:
                wait = 2 ** attempt
                time.sleep(wait)
            continue
        except requests.RequestException as e:
            raise RuntimeError(f"Ollama API error: {e}") from e
    raise RuntimeError(f"Ollama API error after {max_retries} retries: {last_err}")


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

    return LLMResponse(content=content, tool_calls=tool_calls)
