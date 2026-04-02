"""
tools/static_analysis.py — 静的解析ディスパッチャー

解析種別を受け取り、言語別パーサーに委譲する。
"""

from __future__ import annotations

import json
import os

# 解析対象として収集する拡張子
_CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".c", ".cpp", ".h", ".hpp",
    ".java", ".go", ".rs", ".rb", ".php", ".cs",
}

_IGNORE_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules",
    ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
}


def static_analysis(path: str, analysis: str) -> str:
    """
    指定した解析を実行し結果をJSONで返す。

    Parameters
    ----------
    path:
        解析対象のファイルまたはディレクトリ
    analysis:
        解析種別（call_graph / dependency_graph / complexity /
                   dead_code / symbol_table / type_info /
                   metrics / issues / data_flow / control_flow）
    """
    if not os.path.exists(path):
        return json.dumps({"error": f"パスが見つかりません: {path}"}, ensure_ascii=False)

    files = _collect_files(path)
    if not files:
        return json.dumps({"error": "解析対象のソースファイルが見つかりません"}, ensure_ascii=False)

    dispatch = {
        "metrics":          _analyze_metrics,
        "call_graph":       _analyze_call_graph,
        "dependency_graph": _analyze_dependency_graph,
        "complexity":       _analyze_complexity,
        "dead_code":        _analyze_dead_code,
        "symbol_table":     _analyze_symbol_table,
        "type_info":        _analyze_type_info,
        "issues":           _analyze_issues,
        "data_flow":        _analyze_data_flow,
        "control_flow":     _analyze_control_flow,
    }

    if analysis not in dispatch:
        return json.dumps({"error": f"未知の解析種別: {analysis}"}, ensure_ascii=False)

    try:
        result = dispatch[analysis](files)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:  # noqa: BLE001
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def _collect_files(path: str) -> list[str]:
    if os.path.isfile(path):
        return [path]
    files = []
    for root, dirs, fnames in os.walk(path):
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS]
        for fname in sorted(fnames):
            if os.path.splitext(fname)[1] in _CODE_EXTENSIONS:
                files.append(os.path.join(root, fname))
    return files


def _get_parser(filepath: str):
    """ファイル拡張子からパーサーモジュールを選択する。"""
    ext = os.path.splitext(filepath)[1]
    if ext == ".py":
        from tools.parsers.python_parser import PythonParser
        return PythonParser(filepath)
    elif ext in {".c", ".cpp", ".h", ".hpp"}:
        from tools.parsers.c_parser import CParser
        return CParser(filepath)
    elif ext in {".js", ".ts"}:
        from tools.parsers.js_parser import JsParser
        return JsParser(filepath)
    else:
        from tools.parsers.generic_parser import GenericParser
        return GenericParser(filepath)


# ── 各解析の実装 ──────────────────────────────────────────────────

def _analyze_metrics(files: list[str]) -> dict:
    """プロジェクト全体の統計情報。"""
    from collections import defaultdict
    loc_by_file = {}
    lang_count: dict[str, int] = defaultdict(int)
    total_functions = 0

    for fpath in files:
        try:
            with open(fpath, encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except OSError:
            continue
        code_lines = sum(
            1 for l in lines if l.strip() and not l.strip().startswith("#")
        )
        loc_by_file[fpath] = code_lines
        ext = os.path.splitext(fpath)[1]
        lang_count[ext] += 1

        parser = _get_parser(fpath)
        total_functions += len(parser.get_functions())

    return {
        "total_files": len(files),
        "total_lines": sum(loc_by_file.values()),
        "total_functions": total_functions,
        "languages": dict(lang_count),
        "loc_by_file": loc_by_file,
    }


def _analyze_call_graph(files: list[str]) -> dict:
    """関数/メソッドの呼び出しグラフ。"""
    nodes = []
    edges = []
    seen_nodes: set[str] = set()

    for fpath in files:
        parser = _get_parser(fpath)
        for func in parser.get_functions():
            key = f"{fpath}::{func['name']}"
            if key not in seen_nodes:
                nodes.append({
                    "name": func["name"],
                    "file": fpath,
                    "line": func.get("line", 0),
                })
                seen_nodes.add(key)
            for callee in func.get("calls", []):
                edges.append({"from": func["name"], "to": callee, "file": fpath})

    return {"nodes": nodes, "edges": edges}


def _analyze_dependency_graph(files: list[str]) -> dict:
    """ファイル/モジュール間の依存関係。"""
    nodes = list(files)
    edges = []

    for fpath in files:
        parser = _get_parser(fpath)
        for dep in parser.get_imports():
            edges.append({
                "from": fpath,
                "to": dep["module"],
                "type": dep.get("type", "import"),
            })

    return {"nodes": nodes, "edges": edges}


def _analyze_complexity(files: list[str]) -> dict:
    """循環的複雑度・ネスト深度・関数長。"""
    functions = []
    for fpath in files:
        parser = _get_parser(fpath)
        for func in parser.get_functions():
            functions.append({
                "name": func["name"],
                "file": fpath,
                "line": func.get("line", 0),
                "cyclomatic": func.get("cyclomatic", 1),
                "max_nesting": func.get("max_nesting", 0),
                "lines": func.get("lines", 0),
            })

    # 複雑度でソート
    functions.sort(key=lambda f: f["cyclomatic"], reverse=True)
    return {"functions": functions}


def _analyze_dead_code(files: list[str]) -> dict:
    """未使用の関数・変数・import。"""
    all_defined: dict[str, list[str]] = {}
    all_called: set[str] = set()
    unused_imports = []

    for fpath in files:
        parser = _get_parser(fpath)
        defined = [f["name"] for f in parser.get_functions()]
        all_defined[fpath] = defined

        calls = parser.get_all_calls()
        all_called.update(calls)

        for imp in parser.get_imports():
            name = imp.get("alias") or imp.get("name") or imp.get("module", "")
            if name and name not in calls:
                unused_imports.append({"file": fpath, "import": imp.get("module", ""), "name": name})

    unused_functions = []
    for fpath, funcs in all_defined.items():
        for fname in funcs:
            if fname not in all_called and not fname.startswith("_"):
                unused_functions.append({"file": fpath, "function": fname})

    return {
        "unused_functions": unused_functions,
        "unused_variables": [],  # 簡易実装
        "unused_imports": unused_imports,
    }


def _analyze_symbol_table(files: list[str]) -> dict:
    """スコープ付きシンボル一覧。"""
    symbols = []
    for fpath in files:
        parser = _get_parser(fpath)
        for func in parser.get_functions():
            symbols.append({
                "name": func["name"],
                "type": "function",
                "scope": "module",
                "file": fpath,
                "line": func.get("line", 0),
                "qualifiers": func.get("qualifiers", []),
            })
        for var in parser.get_variables():
            symbols.append({
                "name": var["name"],
                "type": var.get("type", "variable"),
                "scope": var.get("scope", "module"),
                "file": fpath,
                "line": var.get("line", 0),
                "qualifiers": var.get("qualifiers", []),
            })

    return {"symbols": symbols}


def _analyze_type_info(files: list[str]) -> dict:
    """型情報・struct/enum定義。"""
    types = []
    for fpath in files:
        parser = _get_parser(fpath)
        for t in parser.get_types():
            types.append({**t, "file": fpath})
    return {"types": types}


def _analyze_issues(files: list[str]) -> dict:
    """潜在的問題の検出。"""
    issues = []
    for fpath in files:
        parser = _get_parser(fpath)
        for issue in parser.get_issues():
            issues.append({**issue, "file": fpath})
    issues.sort(key=lambda i: {"high": 0, "medium": 1, "low": 2}.get(i.get("severity", "low"), 2))
    return {"issues": issues}


def _analyze_data_flow(files: list[str]) -> dict:
    """変数の定義→代入→参照の追跡（簡易実装）。"""
    results = []
    for fpath in files:
        parser = _get_parser(fpath)
        for var in parser.get_variables():
            results.append({
                "variable": var["name"],
                "file": fpath,
                "definitions": [{"line": var.get("line", 0)}],
                "assignments": [],
                "references": [],
            })
    return {"data_flow": results}


def _analyze_control_flow(files: list[str]) -> dict:
    """関数内の分岐・ループ構造（簡易実装）。"""
    functions = []
    for fpath in files:
        parser = _get_parser(fpath)
        for func in parser.get_functions():
            functions.append({
                "function": func["name"],
                "file": fpath,
                "blocks": func.get("blocks", []),
            })
    return {"functions": functions}
