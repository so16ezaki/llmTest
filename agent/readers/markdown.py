"""readers/markdown.py — Markdown/テキストリーダー"""

from __future__ import annotations


def read(filepath: str) -> str:
    """Markdown/テキストファイルをそのまま返す。"""
    with open(filepath, encoding="utf-8", errors="replace") as f:
        return f.read()
