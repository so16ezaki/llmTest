"""
tools/planning.py — 計画・管理ツール群

todo_write, memory_write, memory_read を実装する。
TODOはtodo.mdに、メモリはproject_memory.mdに保存する。
"""

from __future__ import annotations

import os
import re

from config import MEMORY_FILE, MEMORY_LIMIT_BYTES

TODO_FILE = "todo.md"


# ── todo_write ────────────────────────────────────────────────────

def todo_write(todos: list[dict]) -> str:
    """
    TODOリストを全体上書き保存する。

    Parameters
    ----------
    todos:
        [{"id": str, "content": str, "status": "pending"|"in_progress"|"done",
          "priority": "high"|"medium"|"low"}]
    """
    lines = ["# TODO\n"]
    status_icons = {"pending": "[ ]", "in_progress": "[~]", "done": "[x]"}
    priority_icons = {"high": "🔴", "medium": "🟡", "low": "🟢"}

    for item in todos:
        icon = status_icons.get(item.get("status", "pending"), "[ ]")
        priority = item.get("priority", "medium")
        pri_icon = priority_icons.get(priority, "")
        item_id = item.get("id", "")
        content = item.get("content", "")
        lines.append(f"- {icon} {pri_icon} [{item_id}] {content}")

    content = "\n".join(lines) + "\n"
    _write_file(TODO_FILE, content)

    done = sum(1 for t in todos if t.get("status") == "done")
    total = len(todos)
    return f"TODOを更新しました（{done}/{total} 完了）。\n\n{content}"


def read_todo() -> str:
    """現在のTODO内容を返す（system_prompt.pyから呼び出し用）。"""
    if not os.path.isfile(TODO_FILE):
        return ""
    try:
        with open(TODO_FILE, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


# ── memory_write ──────────────────────────────────────────────────

def memory_write(key: str, content: str) -> str:
    """
    project_memory.mdにキー付きセクションを追記/更新する。

    既存のキーがある場合は上書き、ない場合は末尾に追加する。

    Parameters
    ----------
    key:
        メモリキー（セクション見出し）
    content:
        保存する内容
    """
    existing = _read_memory_raw()
    section_pattern = re.compile(
        rf"^## {re.escape(key)}\n(.*?)(?=\n## |\Z)",
        re.MULTILINE | re.DOTALL,
    )

    new_section = f"## {key}\n{content.strip()}\n"

    if section_pattern.search(existing):
        updated = section_pattern.sub(new_section, existing)
    else:
        updated = existing.rstrip() + "\n\n" + new_section if existing else new_section

    _write_file(MEMORY_FILE, updated)
    return f"メモリを保存しました: [{key}]"


# ── memory_read ───────────────────────────────────────────────────

def memory_read(key: str | None = None) -> str:
    """
    project_memory.mdから読み出す。

    Parameters
    ----------
    key:
        読み出すキー（省略時は先頭25KBを全て返す）
    """
    existing = _read_memory_raw()
    if not existing:
        return "（project_memory.mdは空です）"

    if not key:
        # 先頭25KB
        if len(existing.encode("utf-8")) > MEMORY_LIMIT_BYTES:
            existing = existing.encode("utf-8")[:MEMORY_LIMIT_BYTES].decode("utf-8", errors="ignore")
            existing += "\n\n... [25KB上限でトリム] ..."
        return existing

    # キー指定時はそのセクションのみ
    section_pattern = re.compile(
        rf"^## {re.escape(key)}\n(.*?)(?=\n## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = section_pattern.search(existing)
    if match:
        return f"## {key}\n{match.group(1).strip()}"
    return f"「{key}」というキーのメモリが見つかりませんでした。"


# ── ユーティリティ ────────────────────────────────────────────────

def _read_memory_raw() -> str:
    if not os.path.isfile(MEMORY_FILE):
        return ""
    try:
        with open(MEMORY_FILE, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _write_file(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
