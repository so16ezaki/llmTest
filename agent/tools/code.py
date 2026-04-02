"""
tools/code.py — コード解析ツール群

scan_project, read_source, grep_source, extract_structure, static_analysis を実装する。
"""

from __future__ import annotations

import os
import re

# 無視するディレクトリ・ファイルパターン
_IGNORE_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules",
    ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
}
_IGNORE_EXTENSIONS = {".pyc", ".pyo", ".pyd", ".so", ".dll", ".exe"}


# ── scan_project ──────────────────────────────────────────────────

def scan_project(path: str) -> str:
    """
    ディレクトリのファイル構成をツリー形式で返す。

    Parameters
    ----------
    path:
        スキャン対象のディレクトリパス
    """
    if not os.path.exists(path):
        return f"[error] パスが見つかりません: {path}"

    if os.path.isfile(path):
        size = os.path.getsize(path)
        return f"ファイル: {path} ({size:,} bytes)"

    lines = [f"## {path}/\n"]
    _build_tree(path, lines, prefix="", depth=0, max_depth=5)

    # ファイル数・行数の統計
    stats = _count_stats(path)
    lines.append(f"\n**統計:** {stats['files']}ファイル, {stats['dirs']}ディレクトリ")
    if stats["total_lines"]:
        lines.append(f"(コードファイル合計 {stats['total_lines']:,}行)")

    return "\n".join(lines)


def _build_tree(
    path: str, lines: list[str], prefix: str, depth: int, max_depth: int
) -> None:
    if depth >= max_depth:
        lines.append(f"{prefix}... (省略)")
        return
    try:
        entries = sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name))
    except PermissionError:
        return

    entries = [e for e in entries if e.name not in _IGNORE_DIRS]

    for i, entry in enumerate(entries):
        is_last = i == len(entries) - 1
        connector = "└── " if is_last else "├── "
        child_prefix = prefix + ("    " if is_last else "│   ")

        if entry.is_dir():
            lines.append(f"{prefix}{connector}{entry.name}/")
            _build_tree(entry.path, lines, child_prefix, depth + 1, max_depth)
        else:
            ext = os.path.splitext(entry.name)[1]
            if ext not in _IGNORE_EXTENSIONS:
                size = entry.stat().st_size
                lines.append(f"{prefix}{connector}{entry.name} ({size:,}B)")


def _count_stats(path: str) -> dict:
    stats = {"files": 0, "dirs": 0, "total_lines": 0}
    code_exts = {".py", ".js", ".ts", ".c", ".cpp", ".h", ".java", ".go", ".rs"}
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS]
        stats["dirs"] += len(dirs)
        for f in files:
            ext = os.path.splitext(f)[1]
            if ext in _IGNORE_EXTENSIONS:
                continue
            stats["files"] += 1
            if ext in code_exts:
                try:
                    with open(os.path.join(root, f), encoding="utf-8", errors="ignore") as fp:
                        stats["total_lines"] += sum(1 for _ in fp)
                except OSError:
                    pass
    return stats


# ── read_source ───────────────────────────────────────────────────

def read_source(path: str, symbol: str | None = None) -> str:
    """
    ソースコードを読む。symbol指定時はその関数/クラスのみ返す。

    Parameters
    ----------
    path:
        ファイルパス
    symbol:
        関数名またはクラス名（省略時はファイル全体）
    """
    if not os.path.isfile(path):
        return f"[error] ファイルが見つかりません: {path}"

    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError as e:
        return f"[error] 読み込みエラー: {e}"

    if not symbol:
        lines = content.splitlines()
        numbered = "\n".join(f"{i+1:4d} | {line}" for i, line in enumerate(lines))
        return f"# {path} ({len(lines)}行)\n\n```\n{numbered}\n```"

    # シンボル抽出
    extracted = _extract_symbol(content, symbol, path)
    if extracted is None:
        return f"[error] シンボル '{symbol}' が {path} に見つかりませんでした。"
    return f"# {path} — {symbol}\n\n```\n{extracted}\n```"


def _extract_symbol(content: str, symbol: str, path: str) -> str | None:
    """ファイルから指定シンボル（関数/クラス）のコードブロックを抽出する。"""
    ext = os.path.splitext(path)[1]

    if ext == ".py":
        return _extract_python_symbol(content, symbol)
    else:
        return _extract_generic_symbol(content, symbol)


def _extract_python_symbol(content: str, symbol: str) -> str | None:
    """Pythonファイルから関数/クラスを抽出する（インデントベース）。"""
    lines = content.splitlines()
    # def/class の定義行を探す
    pattern = re.compile(rf"^(def|class)\s+{re.escape(symbol)}\b")
    start_idx = None
    for i, line in enumerate(lines):
        if pattern.match(line):
            start_idx = i
            break

    if start_idx is None:
        return None

    # インデントを基準にブロック末尾を特定
    base_indent = len(lines[start_idx]) - len(lines[start_idx].lstrip())
    end_idx = len(lines)
    for i in range(start_idx + 1, len(lines)):
        stripped = lines[i].strip()
        if not stripped:
            continue
        indent = len(lines[i]) - len(lines[i].lstrip())
        if indent <= base_indent and stripped:
            end_idx = i
            break

    block = lines[start_idx:end_idx]
    numbered = "\n".join(f"{start_idx+j+1:4d} | {line}" for j, line in enumerate(block))
    return numbered


def _extract_generic_symbol(content: str, symbol: str) -> str | None:
    """汎用：関数/クラス定義をブレース/インデントで抽出する。"""
    lines = content.splitlines()
    patterns = [
        re.compile(rf"\b(function|def|class|func|fn)\s+{re.escape(symbol)}\b"),
        re.compile(rf"\b{re.escape(symbol)}\s*[=({{]"),
    ]

    start_idx = None
    for i, line in enumerate(lines):
        for p in patterns:
            if p.search(line):
                start_idx = i
                break
        if start_idx is not None:
            break

    if start_idx is None:
        return None

    # 最大100行を返す
    end_idx = min(start_idx + 100, len(lines))
    block = lines[start_idx:end_idx]
    numbered = "\n".join(f"{start_idx+j+1:4d} | {line}" for j, line in enumerate(block))
    return numbered


# ── grep_source ───────────────────────────────────────────────────

def grep_source(pattern: str, path: str, context_lines: int = 3) -> str:
    """
    ソースコードをgrep検索する。

    Parameters
    ----------
    pattern:
        検索パターン（正規表現）
    path:
        検索対象のファイルまたはディレクトリ
    context_lines:
        前後に含める行数
    """
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return f"[error] 正規表現エラー: {e}"

    if os.path.isfile(path):
        targets = [path]
    elif os.path.isdir(path):
        targets = _collect_source_files(path)
    else:
        return f"[error] パスが見つかりません: {path}"

    results = []
    for fpath in targets:
        matches = _grep_file(fpath, regex, context_lines)
        if matches:
            results.append(f"\n### {fpath}\n" + "\n---\n".join(matches))

    if not results:
        return f"「{pattern}」は {path} 内に見つかりませんでした。"

    header = f"## grep_source: `{pattern}`\n\n{len(results)}ファイルでマッチ\n"
    return header + "\n".join(results)


def _collect_source_files(directory: str) -> list[str]:
    """ディレクトリ配下のソースファイルを収集する。"""
    code_exts = {
        ".py", ".js", ".ts", ".c", ".cpp", ".h", ".hpp",
        ".java", ".go", ".rs", ".rb", ".php", ".cs", ".swift",
    }
    files = []
    for root, dirs, fnames in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS]
        for fname in sorted(fnames):
            if os.path.splitext(fname)[1] in code_exts:
                files.append(os.path.join(root, fname))
    return files


def _grep_file(path: str, regex: re.Pattern, context_lines: int) -> list[str]:
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except OSError:
        return []

    matched_ranges: set[int] = set()
    for i, line in enumerate(lines):
        if regex.search(line):
            start = max(0, i - context_lines)
            end = min(len(lines), i + context_lines + 1)
            matched_ranges.update(range(start, end))

    if not matched_ranges:
        return []

    sorted_indices = sorted(matched_ranges)
    groups: list[list[int]] = []
    group = [sorted_indices[0]]
    for idx in sorted_indices[1:]:
        if idx == group[-1] + 1:
            group.append(idx)
        else:
            groups.append(group)
            group = [idx]
    groups.append(group)

    snippets = []
    for grp in groups:
        snippet_lines = []
        for idx in grp:
            prefix = ">>>" if regex.search(lines[idx]) else "   "
            snippet_lines.append(f"{idx+1:4d} {prefix} {lines[idx].rstrip()}")
        snippets.append("\n".join(snippet_lines))
    return snippets


# ── extract_structure ─────────────────────────────────────────────

def extract_structure(path: str) -> str:
    """
    関数/クラス/変数の一覧と呼び出し関係をJSONで返す。

    Parameters
    ----------
    path:
        解析対象のファイルまたはディレクトリ
    """
    import json
    from tools.static_analysis import static_analysis

    result = static_analysis(path, "call_graph")
    try:
        data = json.loads(result)
        return json.dumps(data, ensure_ascii=False, indent=2)
    except (json.JSONDecodeError, TypeError):
        return result


# ── static_analysis（ディスパッチャー） ─────────────────────────

def static_analysis(path: str, analysis: str) -> str:
    """tools/static_analysis.py への委譲。"""
    from tools.static_analysis import static_analysis as _static_analysis
    return _static_analysis(path, analysis)
