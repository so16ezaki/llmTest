"""
tools/parsers/js_parser.py — JavaScript/TypeScript 正規表現ベースパーサー
"""

from __future__ import annotations

import re


# 関数定義パターン
_FUNC_PATTERNS = [
    # function 宣言
    re.compile(r"(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(", re.MULTILINE),
    # const/let/var = 関数式・アロー
    re.compile(r"(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:function|\([^)]*\)\s*=>|\w+\s*=>)", re.MULTILINE),
    # クラスメソッド
    re.compile(r"^\s+(?:async\s+)?(\w+)\s*\([^)]*\)\s*\{", re.MULTILINE),
    # TypeScript: メソッド定義
    re.compile(r"^\s+(?:public|private|protected|static|async|override)(?:\s+(?:public|private|protected|static|async|override))*\s+(\w+)\s*\(", re.MULTILINE),
]

_CLASS_PATTERN = re.compile(r"(?:export\s+)?class\s+(\w+)(?:\s+extends\s+(\w+))?", re.MULTILINE)
_IMPORT_PATTERNS = [
    re.compile(r"import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]", re.MULTILINE),
    re.compile(r"require\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", re.MULTILINE),
]

_CALL_PATTERN = re.compile(r"\b(\w+)\s*\(", re.MULTILINE)
_BRANCH_PATTERN = re.compile(r"\b(if|else|while|for|switch|case|catch|&&|\|\|)\b", re.MULTILINE)

_JS_KEYWORDS = {
    "if", "else", "while", "for", "do", "switch", "case", "return",
    "break", "continue", "typeof", "instanceof", "new", "delete",
    "void", "throw", "catch", "finally", "class", "extends", "super",
    "import", "export", "from", "const", "let", "var", "function",
    "async", "await", "yield", "true", "false", "null", "undefined",
    "console", "require", "module",
}


class JsParser:
    def __init__(self, filepath: str) -> None:
        self.filepath = filepath
        self._source = ""
        self._lines: list[str] = []
        self._load()

    def _load(self) -> None:
        try:
            with open(self.filepath, encoding="utf-8", errors="ignore") as f:
                self._source = f.read()
            # ブロックコメントを除去
            self._source = re.sub(r"/\*.*?\*/", "", self._source, flags=re.DOTALL)
            # 行コメントを除去
            self._source = re.sub(r"//.*$", "", self._source, flags=re.MULTILINE)
            self._lines = self._source.splitlines()
        except OSError:
            pass

    def get_functions(self) -> list[dict]:
        funcs = {}
        for pattern in _FUNC_PATTERNS:
            for match in pattern.finditer(self._source):
                name = match.group(1)
                if not name or name in _JS_KEYWORDS or name in funcs:
                    continue
                line = self._source[:match.start()].count("\n") + 1
                snippet = self._source[match.start():match.start() + 1000]
                calls = self._get_calls_in(snippet)
                cyclomatic = 1 + len(_BRANCH_PATTERN.findall(snippet))
                funcs[name] = {
                    "name": name,
                    "line": line,
                    "lines": snippet.count("\n"),
                    "calls": calls,
                    "cyclomatic": cyclomatic,
                    "max_nesting": 0,
                    "qualifiers": [],
                }
        return list(funcs.values())

    def _get_calls_in(self, code: str) -> list[str]:
        calls = set()
        for match in _CALL_PATTERN.finditer(code):
            name = match.group(1)
            if name not in _JS_KEYWORDS and len(name) > 1:
                calls.add(name)
        return list(calls)

    def get_imports(self) -> list[dict]:
        imports = []
        for pattern in _IMPORT_PATTERNS:
            for match in pattern.finditer(self._source):
                mod = match.group(1)
                imports.append({
                    "module": mod,
                    "name": mod.split("/")[-1].replace(".js", "").replace(".ts", ""),
                    "alias": None,
                    "type": "import",
                })
        return imports

    def get_all_calls(self) -> set[str]:
        calls = set()
        for match in _CALL_PATTERN.finditer(self._source):
            name = match.group(1)
            if name not in _JS_KEYWORDS and len(name) > 1:
                calls.add(name)
        return calls

    def get_variables(self) -> list[dict]:
        var_pattern = re.compile(r"(?:const|let|var)\s+(\w+)\s*[=;]", re.MULTILINE)
        vars_ = []
        for match in var_pattern.finditer(self._source):
            line = self._source[:match.start()].count("\n") + 1
            vars_.append({
                "name": match.group(1),
                "line": line,
                "scope": "module",
                "type": "variable",
            })
        return vars_

    def get_types(self) -> list[dict]:
        types = []
        for match in _CLASS_PATTERN.finditer(self._source):
            line = self._source[:match.start()].count("\n") + 1
            types.append({
                "name": match.group(1),
                "kind": "class",
                "members": [],
                "line": line,
                "bases": [match.group(2)] if match.group(2) else [],
            })
        # TypeScript interface/type
        ts_type_pattern = re.compile(r"(?:interface|type)\s+(\w+)", re.MULTILINE)
        for match in ts_type_pattern.finditer(self._source):
            line = self._source[:match.start()].count("\n") + 1
            types.append({
                "name": match.group(1),
                "kind": "interface",
                "members": [],
                "line": line,
            })
        return types

    def get_issues(self) -> list[dict]:
        issues = []
        # eval() の使用
        eval_pattern = re.compile(r"\beval\s*\(")
        for match in eval_pattern.finditer(self._source):
            line = self._source[:match.start()].count("\n") + 1
            issues.append({
                "severity": "high",
                "type": "eval_usage",
                "message": "eval()の使用は危険です",
                "line": line,
            })
        # TODO コメント
        todo_pattern = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b.*", re.IGNORECASE)
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
