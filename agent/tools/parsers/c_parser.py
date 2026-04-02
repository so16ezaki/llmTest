"""
tools/parsers/c_parser.py — C/C++ 正規表現ベースパーサー

tree-sitterが利用できない場合の正規表現実装。
マクロ展開は対象外。基本的な構造の80%精度を目標。
"""

from __future__ import annotations

import re


# C/C++ 関数定義パターン
# 戻り値型 + 関数名 + ( を検出
_FUNC_DEF = re.compile(
    r"^(?:static\s+|inline\s+|extern\s+|virtual\s+|__\w+\s+)*"
    r"(?:const\s+)?(?:unsigned\s+|signed\s+)?(?:\w+(?:::\w+)?)\s*\*?\s*"
    r"(\w+)\s*\([^;{]*\)\s*(?:const\s*)?\s*\{",
    re.MULTILINE,
)

# struct/enum/union/class 定義
_TYPE_DEF = re.compile(
    r"(?:typedef\s+)?(?:struct|enum|union|class)\s+(\w+)\s*\{",
    re.MULTILINE,
)

# #include
_INCLUDE = re.compile(r"#include\s+[<\"]([^>\"]+)[>\"]", re.MULTILINE)

# 関数呼び出し
_CALL = re.compile(r"\b(\w+)\s*\(", re.MULTILINE)

# 分岐ノード（循環的複雑度用）
_BRANCH_PATTERN = re.compile(
    r"\b(if|else|while|for|do|switch|case|catch|&&|\|\|)\b",
    re.MULTILINE,
)

# グローバル変数定義（先頭カラム）
_GLOBAL_VAR = re.compile(
    r"^(?:static\s+|extern\s+|volatile\s+|const\s+)*"
    r"(?:unsigned\s+|signed\s+)?(?:\w+)\s+(\w+)\s*[=;]",
    re.MULTILINE,
)

_C_KEYWORDS = {
    "if", "else", "while", "for", "do", "switch", "case", "return",
    "break", "continue", "goto", "sizeof", "typedef", "struct", "union",
    "enum", "class", "new", "delete", "main", "void", "int", "char",
    "long", "short", "float", "double", "bool", "true", "false",
}


class CParser:
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
        funcs = []
        seen = set()
        for match in _FUNC_DEF.finditer(self._source):
            name = match.group(1)
            if name in _C_KEYWORDS or name in seen:
                continue
            seen.add(name)
            line = self._source[:match.start()].count("\n") + 1
            body = self._extract_body(match.end() - 1)
            calls = self._get_calls_in(body)
            cyclomatic = 1 + len(_BRANCH_PATTERN.findall(body))
            funcs.append({
                "name": name,
                "line": line,
                "lines": body.count("\n") + 1,
                "calls": calls,
                "cyclomatic": cyclomatic,
                "max_nesting": self._max_nesting(body),
                "qualifiers": [],
            })
        return funcs

    def _extract_body(self, start: int) -> str:
        """波括弧マッチングで関数本体を抽出する。"""
        depth = 0
        i = start
        src = self._source
        while i < len(src):
            if src[i] == "{":
                depth += 1
            elif src[i] == "}":
                depth -= 1
                if depth == 0:
                    return src[start:i+1]
            i += 1
        return src[start:]

    def _get_calls_in(self, body: str) -> list[str]:
        calls = set()
        for match in _CALL.finditer(body):
            name = match.group(1)
            if name not in _C_KEYWORDS and len(name) > 1:
                calls.add(name)
        return list(calls)

    def _max_nesting(self, body: str) -> int:
        depth = max_depth = 0
        for ch in body:
            if ch == "{":
                depth += 1
                max_depth = max(max_depth, depth)
            elif ch == "}":
                depth -= 1
        return max_depth

    def get_imports(self) -> list[dict]:
        imports = []
        for match in _INCLUDE.finditer(self._source):
            header = match.group(1)
            imports.append({
                "module": header,
                "name": header.split("/")[-1].replace(".h", ""),
                "alias": None,
                "type": "include",
            })
        return imports

    def get_all_calls(self) -> set[str]:
        calls = set()
        for match in _CALL.finditer(self._source):
            name = match.group(1)
            if name not in _C_KEYWORDS and len(name) > 1:
                calls.add(name)
        return calls

    def get_variables(self) -> list[dict]:
        vars_ = []
        seen = set()
        for match in _GLOBAL_VAR.finditer(self._source):
            name = match.group(1)
            if name in _C_KEYWORDS or name in seen:
                continue
            seen.add(name)
            line = self._source[:match.start()].count("\n") + 1
            vars_.append({
                "name": name,
                "line": line,
                "scope": "global",
                "type": "variable",
                "qualifiers": [],
            })
        return vars_

    def get_types(self) -> list[dict]:
        types = []
        for match in _TYPE_DEF.finditer(self._source):
            name = match.group(1)
            line = self._source[:match.start()].count("\n") + 1
            types.append({
                "name": name,
                "kind": "struct",
                "members": [],
                "line": line,
            })
        return types

    def get_issues(self) -> list[dict]:
        issues = []
        # gets/strcpy 等の危険関数
        dangerous = re.compile(r"\b(gets|strcpy|strcat|sprintf|scanf)\s*\(")
        for match in dangerous.finditer(self._source):
            line = self._source[:match.start()].count("\n") + 1
            issues.append({
                "severity": "high",
                "type": "dangerous_function",
                "message": f"危険な関数の使用: {match.group(1)}()",
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
