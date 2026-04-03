"""readers/html.py — HTML → Markdown変換（BeautifulSoup使用）"""

from __future__ import annotations

import re


def read(filepath: str) -> str:
    """HTMLをMarkdown形式に変換して返す。"""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        raise ImportError("HTMLの読み込みにはbeautifulsoup4が必要です。\npip install beautifulsoup4")

    with open(filepath, encoding="utf-8", errors="replace") as f:
        content = f.read()

    soup = BeautifulSoup(content, "lxml" if _has_lxml() else "html.parser")

    # 不要タグを除去
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    return _to_markdown(soup)


def _has_lxml() -> bool:
    try:
        import lxml  # noqa: F401
        return True
    except ImportError:
        return False


def _to_markdown(soup) -> str:
    """BeautifulSoupのツリーをMarkdownに変換する。"""
    lines = []
    _process_node(soup.body or soup, lines)
    text = "\n".join(lines)
    # 連続する空行を最大2行に
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _process_node(node, lines: list[str]) -> None:
    from bs4 import NavigableString, Tag
    if isinstance(node, NavigableString):
        text = str(node).strip()
        if text:
            lines.append(text)
        return

    tag = node.name
    if not tag:
        return

    if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
        level = int(tag[1])
        text = node.get_text(strip=True)
        lines.append(f"\n{'#' * level} {text}\n")
    elif tag == "p":
        text = node.get_text(strip=True)
        if text:
            lines.append(f"\n{text}\n")
    elif tag in ("ul", "ol"):
        lines.append("")
        for li in node.find_all("li", recursive=False):
            lines.append(f"- {li.get_text(strip=True)}")
        lines.append("")
    elif tag == "pre":
        code = node.get_text()
        lines.append(f"\n```\n{code}\n```\n")
    elif tag == "code" and node.parent.name != "pre":
        text = node.get_text(strip=True)
        lines.append(f"`{text}`")
    elif tag in ("strong", "b"):
        text = node.get_text(strip=True)
        lines.append(f"**{text}**")
    elif tag in ("em", "i"):
        text = node.get_text(strip=True)
        lines.append(f"*{text}*")
    elif tag == "a":
        text = node.get_text(strip=True)
        href = node.get("href", "")
        lines.append(f"[{text}]({href})")
    elif tag == "table":
        lines.append(_table_to_md(node))
    elif tag in ("br",):
        lines.append("\n")
    elif tag in ("div", "section", "article", "main", "body"):
        for child in node.children:
            _process_node(child, lines)
    else:
        for child in node.children:
            _process_node(child, lines)


def _html_to_markdown(html_str: str) -> str:
    """HTML文字列をMarkdownに変換する。rstリーダー等から利用。"""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        # BeautifulSoup がない場合はタグを除去して返す
        return re.sub(r"<[^>]+>", "", html_str)
    soup = BeautifulSoup(html_str, "lxml" if _has_lxml() else "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return _to_markdown(soup)


def _table_to_md(table_node) -> str:
    rows = []
    for tr in table_node.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
        rows.append("| " + " | ".join(cells) + " |")

    if not rows:
        return ""
    header = rows[0]
    separator = "|" + "|".join(["---"] * header.count("|")) + "|"
    return "\n".join([header, separator] + rows[1:])
