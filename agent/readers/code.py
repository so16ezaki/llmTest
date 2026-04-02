"""readers/code.py — ソースコードリーダー

ソースコードをそのまま読み込み、コメントを抽出してサマリーを付与する。
"""

from __future__ import annotations

import os
import re


def read(filepath: str) -> str:
    """ソースコードを読み込み、コメント付きでMarkdown形式で返す。"""
    ext = os.path.splitext(filepath)[1]

    with open(filepath, encoding="utf-8", errors="replace") as f:
        source = f.read()

    lang = _detect_language(ext)
    comments = _extract_comments(source, ext)

    parts = [f"# {filepath}\n"]
    if comments:
        parts.append("## コメント・ドキュメント\n")
        parts.extend(comments[:20])  # 最大20件
        parts.append("")

    parts.append(f"## ソースコード\n\n```{lang}\n{source}\n```")
    return "\n".join(parts)


def _detect_language(ext: str) -> str:
    mapping = {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".c": "c", ".cpp": "cpp", ".h": "c", ".hpp": "cpp",
        ".java": "java", ".go": "go", ".rs": "rust",
        ".rb": "ruby", ".php": "php", ".cs": "csharp",
        ".sh": "bash", ".yaml": "yaml", ".yml": "yaml",
        ".json": "json", ".toml": "toml", ".ini": "ini",
        ".sql": "sql", ".md": "markdown",
    }
    return mapping.get(ext, "")


def _extract_comments(source: str, ext: str) -> list[str]:
    """ファイルからコメント・docstringを抽出する。"""
    comments = []

    if ext == ".py":
        # docstring抽出
        docstring_pattern = re.compile(r'"""(.*?)"""', re.DOTALL)
        for match in docstring_pattern.finditer(source):
            text = match.group(1).strip()
            if len(text) > 10:
                comments.append(f"- {text[:200]}")
    elif ext in {".c", ".cpp", ".h", ".hpp", ".js", ".ts", ".java"}:
        # ブロックコメント
        block_pattern = re.compile(r"/\*(.*?)\*/", re.DOTALL)
        for match in block_pattern.finditer(source):
            text = match.group(1).strip().replace("\n", " ")
            if len(text) > 5:
                comments.append(f"- {text[:200]}")

    # 行コメント (#, //)
    line_comment_pattern = re.compile(r"(?:^|\s)(?:#|//)\s*(.+)$", re.MULTILINE)
    for match in line_comment_pattern.finditer(source):
        text = match.group(1).strip()
        if len(text) > 10 and not text.startswith("!"):
            comments.append(f"- {text[:150]}")

    return comments[:30]
