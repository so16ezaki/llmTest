"""readers/rst.py — reStructuredText リーダー

docutils で HTML に変換し、html リーダーで Markdown に変換する。
"""

from __future__ import annotations


def read(filepath: str) -> str:
    """reStructuredText ファイルを Markdown に変換して返す。"""
    try:
        from docutils.core import publish_parts
    except ImportError:
        # docutils が未インストールの場合はプレーンテキストとして返す
        with open(filepath, encoding="utf-8", errors="replace") as f:
            return f.read()

    with open(filepath, encoding="utf-8", errors="replace") as f:
        source = f.read()

    parts = publish_parts(source=source, writer_name="html")
    html_body = parts.get("html_body", parts.get("body", ""))

    # 既存の HTML リーダーで Markdown に変換
    from readers.html import _html_to_markdown
    return _html_to_markdown(html_body)
