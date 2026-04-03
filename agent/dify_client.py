"""
dify_client.py — LLMクライアント ファサード

LLM_BACKEND 設定に応じて Ollama / Dify バックエンドにディスパッチする。
LLMResponse クラスを共通インターフェースとして定義する。

使用例:
    import dify_client
    response = dify_client.chat(messages, tools=TOOL_DEFINITIONS)
"""

from __future__ import annotations

from config import LLM_BACKEND


class LLMResponse:
    """LLM応答を統一形式で保持する。"""

    def __init__(
        self,
        content: str,
        tool_calls: list[dict],
        conversation_id: str = "",
    ) -> None:
        self.content = content
        self.tool_calls = tool_calls
        self.conversation_id = conversation_id

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    @property
    def answer(self) -> str:
        return self.content


def chat(
    messages: list[dict],
    tools: list[dict] | None = None,
    conversation_id: str = "",
) -> LLMResponse:
    """
    バックエンドに応じてLLM呼び出しをディスパッチする。

    Parameters
    ----------
    messages:
        メッセージリスト（内部形式）
    tools:
        ツール定義リスト。Ollama: OpenAI形式で送信、Dify: 未使用（プロンプトに含まれる）
    conversation_id:
        Dify の会話ID。Ollama では無視される。

    Returns
    -------
    LLMResponse
    """
    if LLM_BACKEND == "dify":
        from backends.dify import chat as _chat
        return _chat(messages, tools=tools, conversation_id=conversation_id)
    else:
        from backends.ollama import chat as _chat
        return _chat(messages, tools=tools)
