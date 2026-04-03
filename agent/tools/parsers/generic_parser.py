"""
tools/parsers/generic_parser.py — 汎用正規表現ベースのパーサー

C/C++/JS/TS以外の言語や、tree-sitter非対応時のフォールバック。
関数定義・呼び出しの基本検出のみ実装。
"""

from __future__ import annotations

import re


# 関数定義パターン（複数言語に対応）
_FUNC_PATTERNS = [
    # Python
    re.compile(r"^(?:async\s+)?def\s+(\w+)\s*\(", re.MULTILINE),
    # JavaScript/TypeScript
    re.compile(r"(?:function\s+(\w+)|const\s+(\w+)\s*=\s*(?:async\s*)?\(?.*?\)?\s*=>)", re.MULTILINE),
    # Go
    re.compile(r"^func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)\s*\(", re.MULTILINE),
    # Rust
    re.compile(r"^(?:pub\s+)?(?:async\s+)?fn\s+(\w+)\s*[<(]", re.MULTILINE),
    # Java/C#
    re.compile(r"(?:public|private|protected|static|void|int|string)\s+(\w+)\s*\(", re.MULTILINE),
    # Ruby
    re.compile(r"^def\s+(\w+)", re.MULTILINE),
    # Generic
    re.compile(r"^(?:\w+\s+)+(\w+)\s*\([^)]*\)\s*\{", re.MULTILINE),
]

_CALL_PATTERN = re.compile(r"\b(\w+)\s*\(", re.MULTILINE)
_IMPORT_PATTERNS = [
    re.compile(r"^import\s+['\"]([^'\"]+)['\"]", re.MULTILINE),
    re.compile(r"^require\s*\(['\"]([^'\"]+)['\"]\)", re.MULTILINE),
    re.compile(r"^#include\s+[<\"]([^>\"]+)[>\"]", re.MULTILINE),
    re.compile(r"^use\s+([\w:]+)", re.MULTILINE),
    re.compile(r"^import\s+([\w.]+)", re.MULTILINE),
    re.compile(r"^from\s+([\w.]+)\s+import", re.MULTILINE),
]

_VAR_PATTERNS = [
    re.compile(r"^(?:var|let|const)\s+(\w+)\s*[=;]", re.MULTILINE),
    re.compile(r"^(\w+)\s*:=\s*", re.MULTILINE),  # Go
]


class GenericParser:
    def __init__(self, filepath: str) -> None:
        self.filepath = filepath
        self._source = ""
        self._lines: list[str] = []
        self._load()

    def _load(self) -> None:
        try:
            with open(self.filepath, encoding="utf-8", errors="ignore") as f:
                self._source = f.read()
            self._lines = self._source.splitlines()
        except OSError:
            pass

    def get_functions(self) -> list[dict]:
        funcs = {}
        for pattern in _FUNC_PATTERNS:
            for match in pattern.finditer(self._source):
                # グループのどれかがマッチ
                name = next((g for g in match.groups() if g), None)
                if not name or len(name) < 2:
                    continue
                if name in funcs:
                    continue
                line = self._source[:match.start()].count("\n") + 1
                calls = self._get_calls_near(match.start())
                funcs[name] = {
                    "name": name,
                    "line": line,
                    "lines": 0,
                    "calls": calls,
                    "cyclomatic": 1,
                    "max_nesting": 0,
                    "qualifiers": [],
                    "blocks": self._get_control_flow_blocks(match.start()),
                }
        return list(funcs.values())

    def _get_calls_near(self, start: int, window: int = 500) -> list[str]:
        """関数定義から window 文字以内の呼び出しを収集する。"""
        snippet = self._source[start:start + window]
        keywords = {
            "if", "while", "for", "switch", "return", "new", "class",
            "function", "def", "var", "let", "const", "import", "export",
        }
        calls = set()
        for match in _CALL_PATTERN.finditer(snippet):
            name = match.group(1)
            if name not in keywords and len(name) > 1:
                calls.add(name)
        return list(calls)

    def _get_control_flow_blocks(self, start: int, window: int = 500) -> list[dict]:
        """関数定義付近の制御フロー構造を簡易抽出する。"""
        snippet = self._source[start:start + window]
        base_line = self._source[:start].count("\n") + 1
        cf_pattern = re.compile(r"\b(if|while|for|switch)\b", re.MULTILINE)
        blocks = []
        for match in cf_pattern.finditer(snippet):
            line = base_line + snippet[:match.start()].count("\n")
            blocks.append({"type": match.group(1), "line": line, "children": []})
        return blocks

    def get_data_flow(self) -> list[dict]:
        """変数の定義→代入→参照の簡易追跡。"""
        var_info: dict[str, dict] = {}
        for var in self.get_variables():
            name = var["name"]
            var_info[name] = {
                "definitions": [{"line": var["line"]}],
                "assignments": [],
                "references": [],
            }
        return [{"variable": k, **v} for k, v in var_info.items()]

    def get_imports(self) -> list[dict]:
        imports = []
        for pattern in _IMPORT_PATTERNS:
            for match in pattern.finditer(self._source):
                imports.append({
                    "module": match.group(1),
                    "name": match.group(1).split("/")[-1].split(".")[-1],
                    "alias": None,
                    "type": "import",
                })
        return imports

    def get_all_calls(self) -> set[str]:
        keywords = {
            "if", "while", "for", "switch", "return", "new", "class",
            "function", "def", "var", "let", "const", "import", "export",
            "print", "len", "range", "type",
        }
        calls = set()
        for match in _CALL_PATTERN.finditer(self._source):
            name = match.group(1)
            if name not in keywords and len(name) > 1:
                calls.add(name)
        return calls

    def get_variables(self) -> list[dict]:
        vars_ = []
        for pattern in _VAR_PATTERNS:
            for match in pattern.finditer(self._source):
                line = self._source[:match.start()].count("\n") + 1
                vars_.append({
                    "name": match.group(1),
                    "line": line,
                    "scope": "module",
                    "type": "variable",
                })
        return vars_

    def get_types(self) -> list[dict]:
        class_pattern = re.compile(r"^(?:class|struct|enum|interface)\s+(\w+)", re.MULTILINE)
        types = []
        for match in class_pattern.finditer(self._source):
            line = self._source[:match.start()].count("\n") + 1
            types.append({
                "name": match.group(1),
                "kind": "class",
                "members": [],
                "line": line,
            })
        return types

    def get_issues(self) -> list[dict]:
        issues = []
        # TODO コメントの検出
        todo_pattern = re.compile(r"#.*\b(TODO|FIXME|HACK|XXX)\b.*", re.IGNORECASE)
        for i, line in enumerate(self._lines, 1):
            match = todo_pattern.search(line)
            if match:
                issues.append({
                    "severity": "low",
                    "type": "todo_comment",
                    "message": line.strip(),
                    "line": i,
                })
        return issues
