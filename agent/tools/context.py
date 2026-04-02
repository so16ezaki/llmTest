"""
tools/context.py — コンテキスト管理ツール

compact_now, get_status を実装する。

これらのツールはagent.pyのメッセージリストを直接操作する必要があるため、
グローバルステートへのアクセサを通じて動作する。
"""

from __future__ import annotations

# agent.pyのメッセージリストへの参照を保持するモジュールレベル変数
# agent.pyがset_context_ref()で登録する
_messages_ref: list[dict] | None = None
_system_prompt_ref: str = ""


def set_context_ref(messages: list[dict], system_prompt: str) -> None:
    """agent.pyから呼び出し、コンテキスト参照を登録する。"""
    global _messages_ref, _system_prompt_ref
    _messages_ref = messages
    _system_prompt_ref = system_prompt


def compact_now() -> str:
    """手動でコンテキストのコンパクションを発火する。"""
    if _messages_ref is None:
        return "[error] コンテキスト参照が未設定です。"

    import compactor
    original_count = len(_messages_ref)
    original_tokens = compactor.count_messages_tokens(_messages_ref)

    compacted = compactor.compact(_messages_ref, _system_prompt_ref, force_tier=1)

    # in-placeで更新
    _messages_ref.clear()
    _messages_ref.extend(compacted)

    new_tokens = compactor.count_messages_tokens(_messages_ref)
    reduction = original_tokens - new_tokens
    return (
        f"コンパクション完了。\n"
        f"  メッセージ数: {original_count} → {len(_messages_ref)}\n"
        f"  トークン数: {original_tokens:,} → {new_tokens:,} (削減: {reduction:,})"
    )


def get_status() -> str:
    """現在のトークン使用量・残りバジェット・TODO状態を返す。"""
    import compactor
    from config import COMPACTION_THRESHOLD, CONTEXT_LIMIT
    from tools.planning import read_todo

    if _messages_ref is None:
        used_tokens = 0
        ratio = 0.0
    else:
        used_tokens = compactor.count_messages_tokens(_messages_ref)
        ratio = used_tokens / CONTEXT_LIMIT

    remaining = CONTEXT_LIMIT - used_tokens
    threshold_tokens = int(CONTEXT_LIMIT * COMPACTION_THRESHOLD)

    todo = read_todo()
    todo_section = f"\n## TODO\n{todo}" if todo else "\n## TODO\n（なし）"

    status = (
        f"## コンテキスト状態\n\n"
        f"- 使用量: {used_tokens:,} / {CONTEXT_LIMIT:,} トークン ({ratio:.1%})\n"
        f"- 残り: {remaining:,} トークン\n"
        f"- コンパクション閾値: {threshold_tokens:,} トークン ({COMPACTION_THRESHOLD:.0%})\n"
        f"- コンパクション必要: {'**はい**' if ratio >= COMPACTION_THRESHOLD else 'いいえ'}"
        f"{todo_section}"
    )
    return status
