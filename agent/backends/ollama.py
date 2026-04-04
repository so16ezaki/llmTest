"""
backends/ollama.py — OllamaバックエンドのLLMクライアント

OllamaのOpenAI互換エンドポイント(/v1/chat/completions)を使用する。
"""

from __future__ import annotations

import json
import re
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

    # function callingに非対応のモデルがcontentにJSON/XMLでツール呼び出しを
    # 出力した場合のフォールバック
    if not tool_calls and content:
        fallback = _extract_tool_calls_from_text(content)
        if fallback:
            tool_calls = fallback
            content = _strip_tool_call_text(content)

    return LLMResponse(content=content, tool_calls=tool_calls)


# JSONツール呼び出しを検出するパターン群
_JSON_BLOCK_RE = re.compile(
    r"```(?:json)?\s*(\[.*?\]|\{.*?\})\s*```",
    re.DOTALL,
)
_JSON_BARE_RE = re.compile(
    r"(\[\s*\{.*?\}\s*\]|\{\s*\"(?:name|function)\"\s*:.*?\})",
    re.DOTALL,
)


def _extract_tool_calls_from_text(text: str) -> list[dict]:
    """
    contentテキスト中に埋め込まれたツール呼び出しを抽出する。

    対応形式:
      1. XMLタグ形式: <tool_call><name>...</name><args>...</args></tool_call>
      2. JSONコードブロック: ```json [{"name":..., "arguments":{...}}] ```
      3. 裸のJSON: {"name":..., "arguments":{...}} または配列形式
    """
    from tool_parser import parse_xml_tool_calls

    # 1. XMLフォールバック
    xml_calls = parse_xml_tool_calls(text)
    if xml_calls:
        return xml_calls

    # 2. JSONコードブロック
    for m in _JSON_BLOCK_RE.finditer(text):
        calls = _try_parse_json_tool_calls(m.group(1))
        if calls:
            return calls

    # 3. 裸のJSON
    for m in _JSON_BARE_RE.finditer(text):
        calls = _try_parse_json_tool_calls(m.group(1))
        if calls:
            return calls

    return []


def _try_parse_json_tool_calls(raw: str) -> list[dict]:
    """
    JSON文字列をパースしてツール呼び出しリストに変換する。
    {"name":..., "arguments":{...}} または [{"name":..., ...}] 形式を想定。
    """
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return []

    if isinstance(obj, dict):
        obj = [obj]
    if not isinstance(obj, list):
        return []

    calls = []
    for i, item in enumerate(obj):
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("function")
        if not name:
            continue
        args = item.get("arguments") or item.get("args") or item.get("parameters") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"raw": args}
        calls.append({"id": f"fallback_{i}", "name": name, "args": args})
    return calls


def _strip_tool_call_text(text: str) -> str:
    """contentからツール呼び出しテキストを除去して本文だけ返す。"""
    from tool_parser import strip_tool_calls

    # XMLタグを除去
    text = strip_tool_calls(text)
    # JSONコードブロックを除去
    text = _JSON_BLOCK_RE.sub("", text)
    # 裸のJSONを除去
    text = _JSON_BARE_RE.sub("", text)
    return text.strip()
