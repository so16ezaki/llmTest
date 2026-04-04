"""
tools/search.py — ナレッジ検索ツール群

list_knowledge, knowledge_search, read_knowledge, keyword_search を実装する。
"""

from __future__ import annotations

import json
import os
import re

from config import KNOWLEDGE_DIR, KNOWLEDGE_INDEX, SEARCH_PAGE_SIZE


# ── list_knowledge ────────────────────────────────────────────────

def list_knowledge(scope: str | None = None) -> str:
    """
    利用可能なナレッジファイルの一覧と概要を返す。

    Parameters
    ----------
    scope:
        サブディレクトリ名でフィルタ（省略時は全て）
    """
    knowledge_root = KNOWLEDGE_DIR
    if scope:
        knowledge_root = os.path.join(KNOWLEDGE_DIR, scope)

    if not os.path.isdir(knowledge_root):
        return f"[error] ディレクトリが見つかりません: {knowledge_root}"

    lines = [f"## ナレッジファイル一覧（{knowledge_root}）\n"]
    for root, dirs, files in os.walk(knowledge_root):
        dirs.sort()
        rel_root = os.path.relpath(root, KNOWLEDGE_DIR)
        md_files = sorted(f for f in files if f.endswith(".md") and f != "index.md")
        if not md_files:
            continue

        if rel_root != ".":
            lines.append(f"\n### {rel_root}/")

        for fname in md_files:
            fpath = os.path.join(root, fname)
            first_line = _get_first_line(fpath)
            rel_path = os.path.relpath(fpath, KNOWLEDGE_DIR)
            lines.append(f"- `{rel_path}` — {first_line}")

    if len(lines) == 1:
        return "ナレッジファイルが見つかりませんでした。"
    return "\n".join(lines)


def _get_first_line(path: str) -> str:
    """ファイルの最初の非空行を返す（タイトル行として使用）。"""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip().lstrip("#").strip()
                if line:
                    return line[:100]
    except OSError:
        pass
    return "（概要なし）"


# ── knowledge_search ──────────────────────────────────────────────

def knowledge_search(query: str) -> str:
    """
    index.mdの内容から、質問に関連するナレッジを推薦する。

    クエリの単語がタイトルや概要に含まれるナレッジをスコアリングして返す。
    """
    index_content = _read_file(KNOWLEDGE_INDEX)
    if not index_content:
        return "index.mdが見つかりません。list_knowledgeで一覧を確認してください。"

    query_words = re.findall(r"\w+", query.lower())
    if not query_words:
        return "検索クエリが空です。"

    results = []
    for line in index_content.splitlines():
        if not line.strip():
            continue
        line_lower = line.lower()
        score = sum(1 for w in query_words if w in line_lower)
        if score > 0:
            results.append((score, line))

    results.sort(key=lambda x: x[0], reverse=True)

    if not results:
        hint = _get_partial_docs_hint()
        return f"「{query}」に関連するナレッジが見つかりませんでした。keyword_searchで横断検索してみてください。{hint}"

    lines = [f"## 「{query}」に関連するナレッジ（関連度順）\n"]
    for score, line in results[:10]:
        lines.append(f"- [{score}点] {line}")
    return "\n".join(lines)


# ── read_knowledge ────────────────────────────────────────────────

def read_knowledge(path: str) -> str:
    """
    指定ナレッジファイルの全文を返す。

    Parameters
    ----------
    path:
        knowledge/ 配下の相対パス（例: "example_api_docs/overview.md"）
    """
    # skills/配下の相対パスとして解釈
    if not path.startswith(KNOWLEDGE_DIR):
        full_path = os.path.join(KNOWLEDGE_DIR, path)
    else:
        full_path = path

    content = _read_file(full_path)
    if content is None:
        return f"[error] ファイルが見つかりません: {full_path}"

    return f"# {path}\n\n{content}"


# ── keyword_search ────────────────────────────────────────────────

def keyword_search(
    pattern: str,
    scope: str | None = None,
    context_lines: int = 3,
    page: int = 1,
) -> str:
    """
    全ナレッジファイルをgrep検索する。正規表現対応、前後N行の文脈付き。

    Parameters
    ----------
    pattern:
        検索パターン（正規表現）
    scope:
        検索対象のサブディレクトリ（省略時はknowledge/全体）
    context_lines:
        前後に含める行数
    """
    search_root = os.path.join(KNOWLEDGE_DIR, scope) if scope else KNOWLEDGE_DIR

    if not os.path.isdir(search_root):
        return f"[error] ディレクトリが見つかりません: {search_root}"

    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return f"[error] 正規表現エラー: {e}"

    results = []
    for root, dirs, files in os.walk(search_root):
        dirs.sort()
        for fname in sorted(files):
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(root, fname)
            matches = _grep_file(fpath, regex, context_lines)
            if matches:
                rel = os.path.relpath(fpath, KNOWLEDGE_DIR)
                results.append(f"\n### {rel}\n" + "\n---\n".join(matches))

    if not results:
        hint = _get_partial_docs_hint()
        return f"「{pattern}」はナレッジファイル内に見つかりませんでした。{hint}"

    # ページネーション
    total = len(results)
    page_size = SEARCH_PAGE_SIZE
    start = (page - 1) * page_size
    paged = results[start:start + page_size]

    header = f"## keyword_search: `{pattern}`\n\n"
    if total > page_size:
        end_idx = min(start + page_size, total)
        header += f"{total}ファイル中 {start + 1}-{end_idx}件 (page {page})\n"
        if start + page_size < total:
            header += f"次ページ: keyword_search(pattern=\"{pattern}\", page={page + 1})\n"
    else:
        header += f"{total}ファイルでマッチ\n"

    return header + "\n".join(paged)


def _grep_file(path: str, regex: re.Pattern, context_lines: int) -> list[str]:
    """ファイルをgrep検索し、前後context_lines行を含む結果を返す。"""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []

    matches = []
    matched_ranges: set[int] = set()

    for i, line in enumerate(lines):
        if regex.search(line):
            start = max(0, i - context_lines)
            end = min(len(lines), i + context_lines + 1)
            for j in range(start, end):
                matched_ranges.add(j)

    if not matched_ranges:
        return []

    # 連続範囲をグループ化してスニペット生成
    sorted_indices = sorted(matched_ranges)
    groups = []
    group = [sorted_indices[0]]
    for idx in sorted_indices[1:]:
        if idx == group[-1] + 1:
            group.append(idx)
        else:
            groups.append(group)
            group = [idx]
    groups.append(group)

    for group in groups:
        snippet_lines = []
        for idx in group:
            prefix = ">>> " if regex.search(lines[idx]) else "    "
            snippet_lines.append(f"{idx + 1:4d} {prefix}{lines[idx].rstrip()}")
        matches.append("\n".join(snippet_lines))

    return matches


# ── ユーティリティ ────────────────────────────────────────────────

def _read_file(path: str) -> str | None:
    """ファイルを読み込む。存在しない場合はNoneを返す。"""
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _get_partial_docs_hint() -> str:
    """部分処理されたドキュメントがあればヒント文字列を返す。"""
    if not os.path.isdir(KNOWLEDGE_DIR):
        return ""

    hints = []
    for entry in os.scandir(KNOWLEDGE_DIR):
        if not entry.is_dir():
            continue
        coverage_path = os.path.join(entry.path, ".coverage.json")
        if not os.path.isfile(coverage_path):
            continue
        try:
            with open(coverage_path, encoding="utf-8") as f:
                cov = json.load(f)
            if cov.get("partial"):
                processed = cov.get("processed_pages", [])
                total = cov.get("total_pages", "?")
                if processed:
                    p = processed[0]
                    hints.append(f"  - {entry.name}: ページ {p[0]}-{p[1]}/{total} 処理済み")
                else:
                    hints.append(f"  - {entry.name}: 部分処理済み（{total}ページ）")
        except (json.JSONDecodeError, OSError):
            continue

    if not hints:
        return ""
    return (
        "\n\n[hint] 以下のドキュメントは部分的にしか処理されていません。"
        "未処理部分に情報がある可能性があります。\n"
        "get_knowledge_coverageで詳細を確認し、read_pdf_pagesで直接読み取れます。\n"
        + "\n".join(hints)
    )
