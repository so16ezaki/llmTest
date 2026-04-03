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
                    "blocks": self._get_control_flow_blocks(node),
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

    def _get_control_flow_blocks(self, node: ast.AST) -> list[dict]:
        """関数内の制御フロー構造を再帰的に抽出する。"""
        blocks = []
        cf_types = {
            ast.If: "if", ast.While: "while", ast.For: "for",
            ast.With: "with", ast.Try: "try",
        }
        for child in ast.iter_child_nodes(node):
            node_type = type(child)
            if node_type in cf_types:
                block = {
                    "type": cf_types[node_type],
                    "line": child.lineno,
                    "children": self._get_control_flow_blocks(child),
                }
                blocks.append(block)
        return blocks

    def get_data_flow(self) -> list[dict]:
        """変数の定義→代入→参照を追跡する。"""
        if self._tree is None:
            return []
        # 変数ごとの情報を集約
        var_info: dict[str, dict] = {}

        for node in ast.walk(self._tree):
            # 定義・代入: Assign
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        name = target.id
                        if name not in var_info:
                            var_info[name] = {"definitions": [], "assignments": [], "references": []}
                        var_info[name]["definitions"].append({"line": node.lineno})
            # 定義・代入: AnnAssign
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                name = node.target.id
                if name not in var_info:
                    var_info[name] = {"definitions": [], "assignments": [], "references": []}
                var_info[name]["definitions"].append({"line": node.lineno})
            # 代入: AugAssign (+=, -= etc.)
            elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
                name = node.target.id
                if name not in var_info:
                    var_info[name] = {"definitions": [], "assignments": [], "references": []}
                var_info[name]["assignments"].append({"line": node.lineno})
            # 参照: Name with Load context
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                name = node.id
                if name not in var_info:
                    var_info[name] = {"definitions": [], "assignments": [], "references": []}
                var_info[name]["references"].append({"line": node.lineno})

        # 定義が存在する変数のみ返す（import名やbuiltinを除外）
        results = []
        for name, info in var_info.items():
            if info["definitions"]:
                results.append({"variable": name, **info})
        return results

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

        # open() without with statement (resource leak)
        for node in ast.walk(self._tree):
            if isinstance(node, ast.Assign):
                if isinstance(node.value, ast.Call):
                    func = node.value.func
                    if isinstance(func, ast.Name) and func.id == "open":
                        issues.append({
                            "severity": "medium",
                            "type": "resource_leak",
                            "message": "open()がwith文の外で使用されています。close()漏れの可能性",
                            "line": node.lineno,
                        })

        # while True without break/return (possible infinite loop)
        for node in ast.walk(self._tree):
            if isinstance(node, ast.While):
                if isinstance(node.test, ast.Constant) and node.test.value is True:
                    has_exit = False
                    for child in ast.walk(node):
                        if isinstance(child, (ast.Break, ast.Return)):
                            has_exit = True
                            break
                    if not has_exit:
                        issues.append({
                            "severity": "high",
                            "type": "infinite_loop",
                            "message": "while True にbreak/returnがありません",
                            "line": node.lineno,
                        })

        # 未使用変数の簡易検出（関数スコープ内）
        for node in ast.walk(self._tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assigned: dict[str, int] = {}
                referenced: set[str] = set()
                for child in ast.walk(node):
                    if isinstance(child, ast.Assign):
                        for target in child.targets:
                            if isinstance(target, ast.Name) and not target.id.startswith("_"):
                                assigned[target.id] = child.lineno
                    elif isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                        referenced.add(child.id)
                for name, line in assigned.items():
                    if name not in referenced:
                        issues.append({
                            "severity": "low",
                            "type": "unused_variable",
                            "message": f"未使用変数: {name} (関数 {node.name} 内)",
                            "line": line,
                        })

        return issues
