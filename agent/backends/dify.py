"""
backends/dify.py — Dify Cloud API バックエンド

Dify の /v1/chat-messages エンドポイントを使用する。
SSE streaming でレスポンスを受信し、XMLタグ形式のツール呼び出しをパースする。

Dify は OpenAI 形式の function calling に対応していないため、
ツール定義はシステムプロンプトにテキストとして含め、
LLM に XML タグでツール呼び出しを出力させる。
"""

from __future__ import annotations

import json
from typing import Any

import requests

from config import DIFY_API_KEY, DIFY_API_URL, DIFY_RESPONSE_MODE, DIFY_USER
from tool_parser import parse_xml_tool_calls, strip_tool_calls


def chat(
    messages: list[dict],
    tools: list[dict] | None = None,
    conversation_id: str = "",
) -> "LLMResponse":
    """
    Dify /v1/chat-messages を呼び出す。

    Parameters
    ----------
    messages:
        エージェント内部形式のメッセージリスト。
        末尾のメッセージから Dify に送る query を構築する。
    tools:
        未使用（Dify は function calling 非対応）。
        ツール定義はシステムプロンプト内にテキストとして含まれる。
    conversation_id:
        Dify の会話ID。空文字で新規会話を開始する。

    Returns
    -------
    LLMResponse
        .content         : テキスト応答（XMLタグ除去済み）
        .tool_calls      : ツール呼び出しリスト [{id, name, args}]
        .conversation_id : Dify の会話ID（次ターンで再利用）
    """
    from dify_client import LLMResponse

    url = f"{DIFY_API_URL}/chat-messages"
    headers = {
        "Authorization": f"Bearer {DIFY_API_KEY}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "inputs": {},
        "query": _build_query(messages),
        "response_mode": DIFY_RESPONSE_MODE,
        "conversation_id": conversation_id,
        "user": DIFY_USER,
    }

    try:
        resp = requests.post(
            url,
            json=payload,
            headers=headers,
            stream=(DIFY_RESPONSE_MODE == "streaming"),
            timeout=300,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        raise RuntimeError(f"Dify API error: {e}") from e

    if DIFY_RESPONSE_MODE == "streaming":
        return _parse_streaming_response(resp)
    else:
        return _parse_blocking_response(resp.json())


def _build_query(messages: list[dict]) -> str:
    """
    messages リストから Dify に送る query 文字列を構築する。

    Dify は会話履歴を conversation_id でサーバー側管理するため、
    毎回全メッセージを送る必要はない。末尾の新しいメッセージのみ送る。

    - 末尾が tool 結果: ツール実行結果をテキストとして整形
    - 末尾が user（初回）: system prompt の内容は Dify 側の会話に含まれるため、
      user メッセージの content のみを返す
    """
    if not messages:
        return ""

    # 末尾から連続する tool 結果メッセージを収集
    tool_results: list[dict] = []
    for msg in reversed(messages):
        if msg.get("role") == "tool":
            tool_results.insert(0, msg)
        else:
            break

    if tool_results:
        # ツール結果をテキストとして整形
        parts = []
        for msg in tool_results:
            name = msg.get("name", "tool")
            content = msg.get("content", "")
            parts.append(f"[{name} の実行結果]\n{content}")
        return "\n\n".join(parts)

    # tool 結果がなければ、最後の user メッセージを返す
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
                content = "\n".join(
                    c.get("text", "") if isinstance(c, dict) else str(c)
                    for c in content
                )
            return content

    # フォールバック: 最後のメッセージの content
    last = messages[-1]
    return str(last.get("content", ""))


def _parse_streaming_response(resp: requests.Response) -> "LLMResponse":
    """SSE streaming レスポンスをパースする。"""
    from dify_client import LLMResponse

    full_answer = ""
    conversation_id = ""

    for line in resp.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue
        raw = line[6:]  # "data: " を除去
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue

        event = data.get("event", "")
        if event == "message":
            full_answer += data.get("answer", "")
            conversation_id = data.get("conversation_id", conversation_id)
        elif event == "message_end":
            conversation_id = data.get("conversation_id", conversation_id)
        elif event == "error":
            code = data.get("code", "unknown")
            msg = data.get("message", "")
            raise RuntimeError(f"Dify stream error [{code}]: {msg}")

    # XML ツール呼び出しをパース
    tool_calls = parse_xml_tool_calls(full_answer)
    content = strip_tool_calls(full_answer) if tool_calls else full_answer

    return LLMResponse(
        content=content,
        tool_calls=tool_calls,
        conversation_id=conversation_id,
    )


def _parse_blocking_response(data: dict) -> "LLMResponse":
    """blocking モードのレスポンスをパースする。"""
    from dify_client import LLMResponse

    answer: str = data.get("answer", "")
    conversation_id: str = data.get("conversation_id", "")

    # XML ツール呼び出しをパース
    tool_calls = parse_xml_tool_calls(answer)
    content = strip_tool_calls(answer) if tool_calls else answer

    return LLMResponse(
        content=content,
        tool_calls=tool_calls,
        conversation_id=conversation_id,
    )
