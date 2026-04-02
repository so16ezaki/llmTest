"""
tools/parsers/python_parser.py — Python AST ベースのパーサー
"""

from __future__ import annotations

import ast
import os
import re


class PythonParser:
    def __init__(self, filepath: str) -> None:
        self.filepath = filepath
        self._tree: ast.Module | None = None
        self._source: str = ""
        self._load()

    def _load(self) -> None:
        try:
            with open(self.filepath, encoding="utf-8", errors="replace") as f:
                self._source = f.read()
            self._tree = ast.parse(self._source, filename=self.filepath)
        except (SyntaxError, OSError):
            self._tree = None

    def get_functions(self) -> list[dict]:
        if self._tree is None:
            return []
        funcs = []
        source_lines = self._source.splitlines()
        for node in ast.walk(self._tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                calls = self._get_calls_in(node)
                cyclomatic = self._cyclomatic(node)
                end_line = getattr(node, "end_lineno", node.lineno)
                funcs.append({
                    "name": node.name,
                    "line": node.lineno,
                    "lines": end_line - node.lineno + 1,
                    "calls": calls,
                    "cyclomatic": cyclomatic,
                    "max_nesting": self._max_nesting(node),
                    "qualifiers": ["async"] if isinstance(node, ast.AsyncFunctionDef) else [],
                })
        return funcs

    def _get_calls_in(self, node: ast.AST) -> list[str]:
        calls = []
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Name):
                    calls.append(child.func.id)
                elif isinstance(child.func, ast.Attribute):
                    calls.append(child.func.attr)
        return list(set(calls))

    def _cyclomatic(self, node: ast.AST) -> int:
        """循環的複雑度 = 1 + 分岐数。"""
        count = 1
        branch_nodes = (ast.If, ast.While, ast.For, ast.ExceptHandler,
                        ast.With, ast.Assert, ast.comprehension)
        for child in ast.walk(node):
            if isinstance(child, branch_nodes):
                count += 1
            elif isinstance(child, ast.BoolOp):
                count += len(child.values) - 1
        return count

    def _max_nesting(self, node: ast.AST, depth: int = 0) -> int:
        max_d = depth
        nest_nodes = (ast.If, ast.While, ast.For, ast.With, ast.Try)
        for child in ast.iter_child_nodes(node):
            if isinstance(child, nest_nodes):
                max_d = max(max_d, self._max_nesting(child, depth + 1))
        return max_d

    def get_imports(self) -> list[dict]:
        if self._tree is None:
            return []
        imports = []
        for node in ast.walk(self._tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append({
                        "module": alias.name,
                        "alias": alias.asname,
                        "name": alias.name.split(".")[0],
                        "type": "import",
                    })
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    imports.append({
                        "module": module,
                        "name": alias.name,
                        "alias": alias.asname,
                        "type": "from_import",
                    })
        return imports

    def get_all_calls(self) -> set[str]:
        if self._tree is None:
            return set()
        calls = set()
        for node in ast.walk(self._tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    calls.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    calls.add(node.func.attr)
        return calls

    def get_variables(self) -> list[dict]:
        if self._tree is None:
            return []
        vars_ = []
        for node in ast.walk(self._tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        vars_.append({
                            "name": target.id,
                            "line": node.lineno,
                            "scope": "module",
                            "type": "variable",
                        })
            elif isinstance(node, (ast.AnnAssign,)) and isinstance(node.target, ast.Name):
                vars_.append({
                    "name": node.target.id,
                    "line": node.lineno,
                    "scope": "module",
                    "type": "variable",
                })
        return vars_

    def get_types(self) -> list[dict]:
        if self._tree is None:
            return []
        types = []
        for node in ast.walk(self._tree):
            if isinstance(node, ast.ClassDef):
                bases = []
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        bases.append(base.id)
                    elif isinstance(base, ast.Attribute):
                        bases.append(base.attr)
                types.append({
                    "name": node.name,
                    "kind": "class",
                    "members": [
                        n.name for n in ast.walk(node)
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    ],
                    "line": node.lineno,
                    "bases": bases,
                })
        return types

    def get_issues(self) -> list[dict]:
        if self._tree is None:
            return []
        issues = []
        # 再帰呼び出しの検出
        for node in ast.walk(self._tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        if isinstance(child.func, ast.Name) and child.func.id == node.name:
                            issues.append({
                                "severity": "medium",
                                "type": "recursion",
                                "message": f"再帰呼び出し: {node.name}",
                                "line": child.lineno,
                            })
        # bare except
        for node in ast.walk(self._tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                issues.append({
                    "severity": "low",
                    "type": "bare_except",
                    "message": "bare except: 全例外をキャッチしています",
                    "line": node.lineno,
                })
        return issues
