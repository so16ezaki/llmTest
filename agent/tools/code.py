"""
tools/code.py — コード解析ツール群

scan_project, read_source, grep_source, extract_structure, static_analysis を実装する。
"""

from __future__ import annotations

import ast
import json
import os
import re
from datetime import datetime

from config import SEARCH_PAGE_SIZE

# 無視するディレクトリ・ファイルパターン
_IGNORE_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules",
    ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
}
_IGNORE_EXTENSIONS = {".pyc", ".pyo", ".pyd", ".so", ".dll", ".exe"}


# ── scan_project ──────────────────────────────────────────────────

_CODE_EXTS_FOR_ANALYZE = {
    ".py", ".js", ".ts", ".c", ".cpp", ".h", ".hpp",
    ".java", ".go", ".rs", ".rb", ".php", ".cs",
}


def scan_project(path: str, sort_by: str = "name", analyze: bool = False) -> str:
    """
    ディレクトリのファイル構成をツリー形式で返す。

    analyze=False（デフォルト）の場合、ファイルツリーのみを返す。
    analyze=True の場合、コードファイルを含むディレクトリで
    static_analysis(analysis='all') を自動実行して結果を付加する。

    Parameters
    ----------
    path:
        スキャン対象のディレクトリパス
    sort_by:
        ソート方法。"name"（デフォルト、ツリー形式）または "mtime"（更新日時順フラットリスト）
    analyze:
        True のとき、コードプロジェクトを自動検出し static_analysis(analysis='all') を実行する。
        タスクに必要な解析を個別に指定する場合は False（デフォルト）のままにすること。
    """
    if not os.path.exists(path):
        return f"[error] パスが見つかりません: {path}"

    if os.path.isfile(path):
        size = os.path.getsize(path)
        return f"ファイル: {path} ({size:,} bytes)"

    if sort_by == "mtime":
        result = _scan_by_mtime(path)
    else:
        lines = [f"## {path}/\n"]
        _build_tree(path, lines, prefix="", depth=0, max_depth=5)

        # ファイル数・行数の統計
        stats = _count_stats(path)
        lines.append(f"\n**統計:** {stats['files']}ファイル, {stats['dirs']}ディレクトリ")
        if stats["total_lines"]:
            lines.append(f"(コードファイル合計 {stats['total_lines']:,}行)")

        result = "\n".join(lines)

    # ── 自動静的解析 ──────────────────────────────────────────────────
    if analyze and os.path.isdir(path):
        has_code = any(
            os.path.splitext(fname)[1] in _CODE_EXTS_FOR_ANALYZE
            for _, _, fnames in os.walk(path)
            for fname in fnames
        )
        if has_code:
            try:
                from tools.static_analysis import static_analysis as _sa
                analysis_json = _sa(path, "all")
                result += "\n\n## 静的解析結果 (analysis='all')\n" + analysis_json
            except Exception as e:  # noqa: BLE001
                result += f"\n\n[warn] 自動静的解析に失敗しました: {e}"

    return result


def _scan_by_mtime(path: str) -> str:
    """ファイルを更新日時の降順でフラットリスト表示する。"""
    files = []
    for root, dirs, fnames in os.walk(path):
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS]
        for fname in fnames:
            ext = os.path.splitext(fname)[1]
            if ext in _IGNORE_EXTENSIONS:
                continue
            fpath = os.path.join(root, fname)
            try:
                mtime = os.path.getmtime(fpath)
                files.append((fpath, mtime))
            except OSError:
                pass

    files.sort(key=lambda x: x[1], reverse=True)
    lines = [f"## {path}/ (更新日時順)\n"]
    for fpath, mtime in files[:50]:
        dt = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
        rel = os.path.relpath(fpath, path)
        size = os.path.getsize(fpath)
        lines.append(f"  {dt}  {rel} ({size:,}B)")
    if len(files) > 50:
        lines.append(f"\n... 他 {len(files) - 50} ファイル")

    stats = _count_stats(path)
    lines.append(f"\n**統計:** {stats['files']}ファイル, {stats['dirs']}ディレクトリ")
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
        result = f"# {path} ({len(lines)}行)\n\n```\n{numbered}\n```"
        # import/include 追跡を付与
        imports = _extract_imports(content, path)
        if imports:
            result += f"\n\n**依存ファイル:** {', '.join(imports)}"
        return result

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

def grep_source(
    pattern: str, path: str, context_lines: int = 3, page: int = 1,
) -> str:
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
    page:
        結果ページ番号（1始まり）
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

    # ページネーション
    total = len(results)
    page_size = SEARCH_PAGE_SIZE
    start = (page - 1) * page_size
    paged = results[start:start + page_size]

    header = f"## grep_source: `{pattern}`\n\n"
    if total > page_size:
        end_idx = min(start + page_size, total)
        header += f"{total}ファイル中 {start + 1}-{end_idx}件 (page {page})\n"
        if start + page_size < total:
            header += f"次ページ: grep_source(pattern=\"{pattern}\", path=\"{path}\", page={page + 1})\n"
    else:
        header += f"{total}ファイルでマッチ\n"

    return header + "\n".join(paged)


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


# ── generate_skeleton ────────────────────────────────────────────

def generate_skeleton(path: str) -> str:
    """
    ファイルからシグネチャ+Docstring+インターフェースのみを抽出したスケルトンを返す。

    Parameters
    ----------
    path:
        対象のソースファイルパス
    """
    if not os.path.isfile(path):
        return f"[error] ファイルが見つかりません: {path}"

    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError as e:
        return f"[error] 読み込みエラー: {e}"

    ext = os.path.splitext(path)[1]
    if ext == ".py":
        skeleton = _python_skeleton(content)
    elif ext in (".c", ".cpp", ".h", ".hpp"):
        skeleton = _c_skeleton_text(path)
    else:
        skeleton = _generic_skeleton(content, ext)

    if not skeleton.strip():
        return f"[info] {path} にはシグネチャ抽出可能な定義が見つかりませんでした。"

    return f"# {path} — スケルトン\n\n```\n{skeleton}\n```"


def _python_skeleton(content: str) -> str:
    """Pythonファイルからast を使ってスケルトンを生成する。"""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return _generic_skeleton(content, ".py")

    source_lines = content.splitlines()
    output: list[str] = []

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            output.append(ast.get_source_segment(content, node) or "")
        elif isinstance(node, ast.ImportFrom):
            output.append(ast.get_source_segment(content, node) or "")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _append_python_func(node, source_lines, content, output, indent="")
        elif isinstance(node, ast.ClassDef):
            _append_python_class(node, source_lines, content, output)

    return "\n".join(output)


def _append_python_func(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    source_lines: list[str],
    content: str,
    output: list[str],
    indent: str,
) -> None:
    """関数定義のスケルトン行を出力に追加する。"""
    # 定義行を抽出
    sig_line = source_lines[node.lineno - 1].rstrip()
    # デコレータ
    for dec in node.decorator_list:
        dec_line = source_lines[dec.lineno - 1].rstrip()
        output.append(f"{dec_line}")
    output.append(f"{sig_line}")
    # 複数行シグネチャ
    if ")" not in sig_line:
        for i in range(node.lineno, min(node.lineno + 10, len(source_lines))):
            line = source_lines[i].rstrip()
            output.append(f"{line}")
            if ")" in line:
                break
    docstring = ast.get_docstring(node)
    if docstring:
        output.append(f'{indent}    """{docstring}"""')
    output.append(f"{indent}    ...")
    output.append("")


def _append_python_class(
    node: ast.ClassDef,
    source_lines: list[str],
    content: str,
    output: list[str],
) -> None:
    """クラス定義のスケルトン行を出力に追加する。"""
    for dec in node.decorator_list:
        output.append(source_lines[dec.lineno - 1].rstrip())
    output.append(source_lines[node.lineno - 1].rstrip())
    docstring = ast.get_docstring(node)
    if docstring:
        output.append(f'    """{docstring}"""')
    # メソッド
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _append_python_func(child, source_lines, content, output, indent="    ")
    output.append("")


def _generic_skeleton(content: str, ext: str) -> str:
    """汎用：正規表現で関数/クラス定義行+直後のコメントを抽出する。"""
    lines = content.splitlines()
    output: list[str] = []

    # 言語に応じたパターン
    if ext in (".c", ".cpp", ".h", ".hpp"):
        patterns = [
            re.compile(r"^\s*(?:static\s+|extern\s+|inline\s+)*\w[\w\s*]+\s+\w+\s*\("),
            re.compile(r"^\s*(?:struct|class|enum|typedef)\s+\w+"),
            re.compile(r"^#include\s+"),
        ]
    elif ext in (".js", ".ts"):
        patterns = [
            re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+\w+"),
            re.compile(r"^\s*(?:export\s+)?class\s+\w+"),
            re.compile(r"^\s*(?:const|let|var)\s+\w+\s*=\s*(?:async\s+)?\("),
            re.compile(r"^import\s+"),
        ]
    else:
        patterns = [
            re.compile(r"^\s*(?:def|func|fn|function|class|struct|enum|interface)\s+\w+"),
            re.compile(r"^(?:import|require|use|include)\s+"),
        ]

    i = 0
    while i < len(lines):
        line = lines[i]
        matched = any(p.search(line) for p in patterns)
        if matched:
            output.append(f"L{i+1}: {line.rstrip()}")
            # 直後のコメント/docstringを収集
            j = i + 1
            while j < len(lines) and j < i + 5:
                next_line = lines[j].strip()
                if next_line.startswith(("//", "/*", "*", "#", '"""', "'''", ";")):
                    output.append(f"      {lines[j].rstrip()}")
                    j += 1
                else:
                    break
            output.append("")
        i += 1

    return "\n".join(output)


def _c_skeleton_text(path: str) -> str:
    """C/C++ ファイルから tree-sitter を使ってスケルトンテキストを生成する。"""
    try:
        from tools.parsers.c_parser import CParser
        parser = CParser(path)
        sk = parser.get_skeleton()
    except Exception:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            return ""
        return _generic_skeleton(content, ".c")

    lines: list[str] = []

    # Includes
    if sk.get("includes"):
        lines.append("// === Includes ===")
        for inc in sk["includes"]:
            lines.append(f"#include {inc}")
        lines.append("")

    # Macros
    if sk.get("macros"):
        lines.append("// === Macros ===")
        for m in sk["macros"]:
            if m.get("params"):
                lines.append(f"#define {m['name']}{m['params']} {m['value']}")
            else:
                lines.append(f"#define {m['name']} {m['value']}")
        lines.append("")

    # Types
    if sk.get("types"):
        lines.append("// === Types ===")
        for t in sk["types"]:
            kind = t.get("kind", "struct")
            name = t["name"]
            if kind in ("struct", "union"):
                members = t.get("members", [])
                if members:
                    lines.append(f"typedef {kind} {{")
                    for m in members:
                        lines.append(f"    {m['type']} {m['name']};")
                    lines.append(f"}} {name};")
                else:
                    lines.append(f"{kind} {name};")
            elif kind == "enum":
                values = t.get("values", [])
                lines.append(f"typedef enum {{")
                for v in values:
                    val_str = f" = {v['value']}" if v.get("value") else ""
                    lines.append(f"    {v['name']}{val_str},")
                lines.append(f"}} {name};")
            elif kind == "typedef":
                lines.append(f"typedef {t.get('aliased_type', '')} {name};")
        lines.append("")

    # Function signatures
    if sk.get("function_signatures"):
        lines.append("// === Function Signatures ===")
        for sig in sk["function_signatures"]:
            qualifiers = " ".join(sig.get("qualifiers", []))
            ret = sig["return_type"]
            prefix = f"{qualifiers} {ret}".strip() if qualifiers else ret
            params = ", ".join(
                f"{p['type']} {p['name']}".strip() if p.get("type") and p["type"] != "..."
                else p.get("name", "...")
                for p in sig.get("params", [])
            ) or "void"
            lines.append(f"{prefix} {sig['name']}({params});")
        lines.append("")

    return "\n".join(lines)


# ── dependency_map ───────────────────────────────────────────────

def dependency_map(path: str, format: str = "mermaid") -> str:
    """
    ファイル/モジュール間の依存関係をMermaid図またはJSONで返す。

    Parameters
    ----------
    path:
        解析対象のファイルまたはディレクトリ
    format:
        出力形式。"mermaid"（デフォルト）または "json"
    """
    from tools.static_analysis import static_analysis as _sa

    result_str = _sa(path, "dependency_graph")
    try:
        result = json.loads(result_str)
    except (json.JSONDecodeError, TypeError):
        return result_str

    if "error" in result:
        return json.dumps(result, ensure_ascii=False)

    if format == "json":
        return json.dumps(result, ensure_ascii=False, indent=2)

    # Mermaid形式で出力
    edges = result.get("edges", [])
    nodes = result.get("nodes", [])

    if not edges and not nodes:
        return "[info] 依存関係が検出されませんでした。"

    lines = ["```mermaid", "graph TD"]
    seen_ids: set[str] = set()

    for edge in edges:
        src = _safe_mermaid_id(edge.get("from", ""))
        dst = _safe_mermaid_id(edge.get("to", ""))
        edge_type = edge.get("type", "")
        label = f"|{edge_type}|" if edge_type else ""
        lines.append(f"    {src} -->{label} {dst}")
        seen_ids.add(src)
        seen_ids.add(dst)

    # エッジに含まれないノードを追加
    for node in nodes:
        nid = _safe_mermaid_id(node if isinstance(node, str) else node.get("file", ""))
        if nid and nid not in seen_ids:
            lines.append(f"    {nid}")

    lines.append("```")
    return "\n".join(lines)


def _safe_mermaid_id(name: str) -> str:
    """Mermaidノード名として安全な文字列に変換する。"""
    # パス区切り・特殊文字を置換
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", os.path.basename(name))
    return safe or "unknown"


# ── import追跡 ───────────────────────────────────────────────────

_IMPORT_PATTERNS: dict[str, list[re.Pattern]] = {
    ".py": [
        re.compile(r"^\s*import\s+([\w.]+)"),
        re.compile(r"^\s*from\s+([\w.]+)\s+import"),
    ],
    ".c": [re.compile(r'^\s*#include\s+[<"]([^>"]+)[>"]')],
    ".cpp": [re.compile(r'^\s*#include\s+[<"]([^>"]+)[>"]')],
    ".h": [re.compile(r'^\s*#include\s+[<"]([^>"]+)[>"]')],
    ".hpp": [re.compile(r'^\s*#include\s+[<"]([^>"]+)[>"]')],
    ".js": [
        re.compile(r"""^\s*import\s+.*?from\s+['"]([^'"]+)['"]"""),
        re.compile(r"""^\s*(?:const|let|var)\s+.*?=\s*require\s*\(\s*['"]([^'"]+)['"]"""),
    ],
    ".ts": [
        re.compile(r"""^\s*import\s+.*?from\s+['"]([^'"]+)['"]"""),
        re.compile(r"""^\s*(?:const|let|var)\s+.*?=\s*require\s*\(\s*['"]([^'"]+)['"]"""),
    ],
    ".go": [re.compile(r'^\s*"([^"]+)"')],
    ".rs": [re.compile(r"^\s*(?:use|mod)\s+([\w:]+)")],
    ".java": [re.compile(r"^\s*import\s+([\w.]+)")],
}


def _extract_imports(content: str, path: str) -> list[str]:
    """ファイルからimport/include対象を抽出する。"""
    ext = os.path.splitext(path)[1]
    patterns = _IMPORT_PATTERNS.get(ext, [])
    if not patterns:
        return []

    imports: list[str] = []
    for line in content.splitlines():
        for pattern in patterns:
            m = pattern.match(line)
            if m:
                imports.append(m.group(1))
                break

    return imports
