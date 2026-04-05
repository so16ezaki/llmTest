"""
tools/parsers/c_parser.py — C/C++ パーサー

tree-sitter が利用可能な場合は AST ベースの高精度解析を使用する。
利用不可の場合は正規表現ベースの実装（約80%精度）にフォールバックする。
"""

from __future__ import annotations

import re
from typing import Any

# ── tree-sitter 初期化（オプション） ────────────────────────────────────
try:
    from tree_sitter import Language, Parser as TSParser
    import tree_sitter_c as tsc
    _C_LANGUAGE = Language(tsc.language())
    _TS_AVAILABLE = True
except Exception:
    _TS_AVAILABLE = False

# ── 正規表現定数（フォールバック用） ──────────────────────────────────────

_FUNC_DEF = re.compile(
    r"^(?:static\s+|inline\s+|extern\s+|virtual\s+|__\w+\s+)*"
    r"(?:const\s+)?(?:unsigned\s+|signed\s+)?(?:\w+(?:::\w+)?)\s*\*?\s*"
    r"(\w+)\s*\([^;{]*\)\s*(?:const\s*)?\s*\{",
    re.MULTILINE,
)

_TYPE_DEF = re.compile(
    r"(?:typedef\s+)?(?:struct|enum|union|class)\s+(\w+)\s*\{",
    re.MULTILINE,
)

_INCLUDE = re.compile(r"#include\s+[<\"]([^>\"]+)[>\"]", re.MULTILINE)
_DEFINE = re.compile(r"^#define\s+(\w+)(\([^)]*\))?\s+(.*)", re.MULTILINE)
_CALL = re.compile(r"\b(\w+)\s*\(", re.MULTILINE)

_BRANCH_PATTERN = re.compile(
    r"\b(if|else\s+if|while|for|do|switch|case|catch|&&|\|\|)\b",
    re.MULTILINE,
)

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
    "NULL", "nullptr", "auto", "const", "static", "extern", "volatile",
    "register", "unsigned", "signed", "inline",
}

_DANGEROUS_FUNCS = {"gets", "strcpy", "strcat", "sprintf", "scanf",
                    "sscanf", "vsprintf", "stpcpy", "strncpy"}
_FORMAT_FUNCS = {"printf", "fprintf", "sprintf", "snprintf",
                 "vprintf", "vfprintf", "vsprintf", "vsnprintf"}


# ── ユーティリティ ────────────────────────────────────────────────────────

def _find_all(node: Any, node_type: str) -> list:
    """指定タイプの全ノードをDFSで収集する。"""
    results = []
    if node.type == node_type:
        results.append(node)
    for child in node.children:
        results.extend(_find_all(child, node_type))
    return results


def _find_all_multi(node: Any, node_types: set) -> list:
    """複数タイプの全ノードをDFSで収集する。"""
    results = []
    if node.type in node_types:
        results.append(node)
    for child in node.children:
        results.extend(_find_all_multi(child, node_types))
    return results


def _get_declarator_name(node: Any) -> str | None:
    """pointer_declarator / identifier / type_identifier / array_declarator などから名前を取り出す。"""
    if node is None:
        return None
    if node.type in ("identifier", "type_identifier", "field_identifier"):
        return node.text.decode("utf-8", errors="replace")
    if node.type in ("pointer_declarator", "array_declarator",
                     "function_declarator", "init_declarator",
                     "parenthesized_declarator"):
        inner = node.child_by_field_name("declarator")
        return _get_declarator_name(inner)
    return None


def _get_full_type(node: Any) -> str:
    """型ノードのテキストを返す（pointer修飾を含む）。"""
    if node is None:
        return ""
    return node.text.decode("utf-8", errors="replace").strip()


def _get_qualifiers_from_fd(fd_node: Any) -> list[str]:
    """function_definition ノードの修飾子（static, inline 等）を取得する。"""
    qualifiers = []
    for i, child in enumerate(fd_node.children):
        fname = fd_node.field_name_for_child(i)
        if fname is None and child.type in (
            "storage_class_specifier", "type_qualifier", "function_specifier"
        ):
            qualifiers.append(child.text.decode("utf-8", errors="replace"))
    return qualifiers


def _count_branches(body_node: Any) -> int:
    """循環的複雑度のための分岐カウント。"""
    branch_types = {
        "if_statement", "while_statement", "for_statement", "do_statement",
        "switch_statement", "conditional_expression", "case_statement",
    }
    count = 0
    for node in _find_all_multi(body_node, branch_types):
        if node.type in ("if_statement", "while_statement", "for_statement",
                         "do_statement", "switch_statement",
                         "conditional_expression", "case_statement"):
            count += 1
    # && と || もカウント
    src = body_node.text.decode("utf-8", errors="replace") if body_node.text else ""
    count += src.count("&&") + src.count("||")
    return count


def _max_nesting_ts(body_node: Any) -> int:
    """compound_statement の最大ネスト深度。"""
    def _depth(node: Any, current: int) -> int:
        best = current
        for child in node.children:
            if child.type == "compound_statement":
                best = max(best, _depth(child, current + 1))
            else:
                best = max(best, _depth(child, current))
        return best
    return _depth(body_node, 1)


def _enclosing_function(node: Any) -> str | None:
    """ノードの親を辿って、最も近い function_definition の名前を返す。"""
    current = node.parent
    while current is not None:
        if current.type == "function_definition":
            decl = current.child_by_field_name("declarator")
            if decl:
                inner = decl.child_by_field_name("declarator")
                name = _get_declarator_name(inner)
                return name
        current = current.parent
    return None


# ── CParser クラス ────────────────────────────────────────────────────────

class CParser:
    def __init__(self, filepath: str) -> None:
        self.filepath = filepath
        self._source = ""
        self._raw = b""
        self._lines: list[str] = []
        self._tree = None
        self._use_ts = False
        self._load()

    def _load(self) -> None:
        try:
            with open(self.filepath, "rb") as f:
                self._raw = f.read()
            self._source = self._raw.decode("utf-8", errors="replace")
            # tree-sitterはオリジナルソースを使う
            if _TS_AVAILABLE:
                ts_parser = TSParser(_C_LANGUAGE)
                self._tree = ts_parser.parse(self._raw)
                self._use_ts = True
            # 正規表現パス用にコメントを除去したソースを用意
            src_no_comment = re.sub(r"/\*.*?\*/", "", self._source, flags=re.DOTALL)
            src_no_comment = re.sub(r"//.*$", "", src_no_comment, flags=re.MULTILINE)
            self._source_stripped = src_no_comment
            self._lines = self._source.splitlines()
        except OSError:
            pass

    # ── 公開メソッド ──────────────────────────────────────────────────────

    def get_functions(self) -> list[dict]:
        if self._use_ts and self._tree:
            return self._ts_get_functions()
        return self._regex_get_functions()

    def get_imports(self) -> list[dict]:
        if self._use_ts and self._tree:
            return self._ts_get_imports()
        return self._regex_get_imports()

    def get_all_calls(self) -> set[str]:
        if self._use_ts and self._tree:
            return self._ts_get_all_calls()
        return self._regex_get_all_calls()

    def get_variables(self) -> list[dict]:
        if self._use_ts and self._tree:
            return self._ts_get_variables()
        return self._regex_get_variables()

    def get_types(self) -> list[dict]:
        if self._use_ts and self._tree:
            return self._ts_get_types()
        return self._regex_get_types()

    def get_issues(self) -> list[dict]:
        if self._use_ts and self._tree:
            return self._ts_get_issues()
        return self._regex_get_issues()

    def get_skeleton(self) -> dict:
        """関数シグネチャ + 型定義のみを返す（スケルトン）。"""
        if self._use_ts and self._tree:
            return self._ts_get_skeleton()
        return self._regex_get_skeleton()

    def get_called_by(self) -> dict[str, list[dict]]:
        """callee名 → [{caller: str, line: int}] のマップを返す。"""
        result: dict[str, list[dict]] = {}
        for func in self.get_functions():
            caller = func["name"]
            for site in func.get("call_sites", []):
                callee = site["name"]
                if callee not in result:
                    result[callee] = []
                result[callee].append({"caller": caller, "line": site["line"]})
        return result

    def get_control_flow(self) -> list[dict]:
        """関数ごとの制御フロー構造を返す（tree-sitter専用）。"""
        if not (self._use_ts and self._tree):
            return []
        return self._ts_get_control_flow()

    # ── tree-sitter 実装 ──────────────────────────────────────────────────

    def _ts_get_functions(self) -> list[dict]:
        funcs = []
        seen: set[str] = set()
        root = self._tree.root_node

        for fd in _find_all(root, "function_definition"):
            decl = fd.child_by_field_name("declarator")
            if decl is None:
                continue
            inner_decl = decl.child_by_field_name("declarator")
            name = _get_declarator_name(inner_decl)
            if not name or name in _C_KEYWORDS or name in seen:
                continue
            seen.add(name)

            ret_type_node = fd.child_by_field_name("type")
            ret_type = _get_full_type(ret_type_node)
            qualifiers = _get_qualifiers_from_fd(fd)

            # パラメータ
            params_node = decl.child_by_field_name("parameters")
            params = self._ts_parse_params(params_node)

            body = fd.child_by_field_name("body")
            line = fd.start_point[0] + 1
            end_line = fd.end_point[0] + 1
            lines = end_line - line + 1

            # 呼び出しサイト
            call_sites = []
            calls_set: set[str] = set()
            if body:
                for call_expr in _find_all(body, "call_expression"):
                    fn_node = call_expr.child_by_field_name("function")
                    if fn_node is None:
                        continue
                    # 直接呼び出し (identifier) のみ
                    callee_name = None
                    if fn_node.type == "identifier":
                        callee_name = fn_node.text.decode("utf-8", errors="replace")
                    elif fn_node.type == "field_expression":
                        field = fn_node.child_by_field_name("field")
                        if field:
                            callee_name = field.text.decode("utf-8", errors="replace")
                    if callee_name and callee_name not in _C_KEYWORDS:
                        call_sites.append({
                            "name": callee_name,
                            "line": call_expr.start_point[0] + 1,
                        })
                        calls_set.add(callee_name)

            cyclomatic = 1 + _count_branches(body) if body else 1
            max_nesting = _max_nesting_ts(body) if body else 0
            recursive = name in calls_set

            funcs.append({
                "name": name,
                "line": line,
                "end_line": end_line,
                "lines": lines,
                "return_type": ret_type,
                "params": params,
                "calls": list(calls_set),
                "call_sites": call_sites,
                "cyclomatic": cyclomatic,
                "max_nesting": max_nesting,
                "qualifiers": qualifiers,
                "recursive": recursive,
            })

        return funcs

    def _ts_parse_params(self, params_node: Any) -> list[dict]:
        params = []
        if params_node is None:
            return params
        for p in params_node.named_children:
            if p.type == "parameter_declaration":
                t_node = p.child_by_field_name("type")
                d_node = p.child_by_field_name("declarator")
                # type qualifiers (const, volatile) の前置き
                qualifiers = []
                for i, c in enumerate(p.children):
                    if c.type == "type_qualifier":
                        qualifiers.append(c.text.decode("utf-8", errors="replace"))
                p_type = _get_full_type(t_node)
                if qualifiers:
                    p_type = " ".join(qualifiers) + " " + p_type
                p_name = _get_declarator_name(d_node) or ""
                # pointer_declarator の場合、型に * を付ける
                if d_node and d_node.type == "pointer_declarator":
                    p_type = p_type + " *"
                params.append({"name": p_name, "type": p_type})
            elif p.type == "variadic_parameter":
                params.append({"name": "...", "type": "..."})
        return params

    def _ts_get_imports(self) -> list[dict]:
        imports = []
        root = self._tree.root_node
        for inc in _find_all(root, "preproc_include"):
            path_node = inc.child_by_field_name("path")
            if path_node is None:
                continue
            raw = path_node.text.decode("utf-8", errors="replace").strip('"<>')
            imports.append({
                "module": raw,
                "name": raw.split("/")[-1].replace(".h", ""),
                "alias": None,
                "type": "include",
            })
        return imports

    def _ts_get_all_calls(self) -> set[str]:
        calls: set[str] = set()
        root = self._tree.root_node
        for call_expr in _find_all(root, "call_expression"):
            fn_node = call_expr.child_by_field_name("function")
            if fn_node and fn_node.type == "identifier":
                name = fn_node.text.decode("utf-8", errors="replace")
                if name not in _C_KEYWORDS:
                    calls.add(name)
        return calls

    def _ts_get_variables(self) -> list[dict]:
        vars_: list[dict] = []
        seen: set[tuple] = set()
        root = self._tree.root_node

        # グローバル変数: translation_unit の直接子の declaration
        for child in root.children:
            if child.type == "declaration":
                self._collect_declaration(child, "global", None, vars_, seen)

        # ローカル変数・パラメータ: function_definition 内
        for fd in _find_all(root, "function_definition"):
            decl = fd.child_by_field_name("declarator")
            inner = decl.child_by_field_name("declarator") if decl else None
            func_name = _get_declarator_name(inner)
            body = fd.child_by_field_name("body")
            if body is None:
                continue

            # パラメータ
            params_node = decl.child_by_field_name("parameters") if decl else None
            if params_node:
                for p in params_node.named_children:
                    if p.type == "parameter_declaration":
                        t_node = p.child_by_field_name("type")
                        d_node = p.child_by_field_name("declarator")
                        p_name = _get_declarator_name(d_node) or ""
                        if not p_name or p_name in _C_KEYWORDS:
                            continue
                        p_type = _get_full_type(t_node)
                        if d_node and d_node.type == "pointer_declarator":
                            p_type = p_type + " *"
                        key = (p_name, func_name, "parameter")
                        if key not in seen:
                            seen.add(key)
                            vars_.append({
                                "name": p_name,
                                "type": p_type,
                                "scope": "parameter",
                                "function": func_name,
                                "line": p.start_point[0] + 1,
                                "qualifiers": [],
                                "written_by": [],
                                "read_by": [],
                            })

            # ローカル宣言
            for decl_node in _find_all(body, "declaration"):
                self._collect_declaration(decl_node, "local", func_name, vars_, seen)

        # 代入・参照の収集
        self._collect_write_read(root, vars_)

        return vars_

    def _collect_declaration(
        self,
        decl_node: Any,
        scope: str,
        func_name: str | None,
        vars_: list[dict],
        seen: set[tuple],
    ) -> None:
        t_node = decl_node.child_by_field_name("type")
        d_node = decl_node.child_by_field_name("declarator")
        if t_node is None or d_node is None:
            return
        raw_type = _get_full_type(t_node)

        # 修飾子を収集
        qualifiers = []
        for i, c in enumerate(decl_node.children):
            if c.type in ("storage_class_specifier", "type_qualifier"):
                qualifiers.append(c.text.decode("utf-8", errors="replace"))

        # init_declarator の場合は内部の declarator を取り出す
        actual_decl = d_node
        if d_node.type == "init_declarator":
            actual_decl = d_node.child_by_field_name("declarator") or d_node

        name = _get_declarator_name(actual_decl)
        if not name or name in _C_KEYWORDS:
            return

        var_type = raw_type
        if actual_decl.type == "pointer_declarator":
            var_type = raw_type + " *"

        key = (name, func_name, scope)
        if key in seen:
            return
        seen.add(key)

        vars_.append({
            "name": name,
            "type": var_type,
            "scope": scope,
            "function": func_name,
            "line": decl_node.start_point[0] + 1,
            "qualifiers": qualifiers,
            "written_by": [],
            "read_by": [],
        })

    def _collect_write_read(self, root: Any, vars_: list[dict]) -> None:
        """代入式からwritten_by、識別子参照からread_byを収集する（ベストエフォート）。"""
        # 変数名→varsエントリのマップ（最初の一致）
        var_map: dict[str, dict] = {}
        for v in vars_:
            if v["name"] not in var_map:
                var_map[v["name"]] = v

        for fd in _find_all(root, "function_definition"):
            decl = fd.child_by_field_name("declarator")
            inner = decl.child_by_field_name("declarator") if decl else None
            func_name = _get_declarator_name(inner)
            body = fd.child_by_field_name("body")
            if body is None:
                continue

            # 代入
            for assign in _find_all(body, "assignment_expression"):
                left = assign.child_by_field_name("left")
                if left and left.type == "identifier":
                    vname = left.text.decode("utf-8", errors="replace")
                    if vname in var_map:
                        entry = {"function": func_name, "line": assign.start_point[0] + 1}
                        var_map[vname]["written_by"].append(entry)

    def _ts_get_types(self) -> list[dict]:
        types: list[dict] = []
        seen: set[str] = set()
        root = self._tree.root_node

        # struct_specifier と union_specifier
        for kind_type in ("struct_specifier", "union_specifier"):
            for node in _find_all(root, kind_type):
                name_node = node.child_by_field_name("name")
                body_node = node.child_by_field_name("body")
                if body_node is None:
                    continue

                # typedef 内の無名 struct → typedef の declarator から名前を取る
                name = None
                if name_node:
                    name = name_node.text.decode("utf-8", errors="replace")
                else:
                    parent = node.parent
                    if parent and parent.type == "type_definition":
                        d = parent.child_by_field_name("declarator")
                        name = _get_declarator_name(d) if d else None

                if not name or name in seen:
                    continue
                seen.add(name)

                members = []
                for fd_node in _find_all(body_node, "field_declaration"):
                    ft = fd_node.child_by_field_name("type")
                    fdecl = fd_node.child_by_field_name("declarator")
                    m_type = _get_full_type(ft)
                    m_name = _get_declarator_name(fdecl) or ""
                    if fdecl and fdecl.type == "pointer_declarator":
                        m_type = m_type + " *"
                    members.append({"name": m_name, "type": m_type})

                kind = "struct" if kind_type == "struct_specifier" else "union"
                types.append({
                    "name": name,
                    "kind": kind,
                    "members": members,
                    "line": node.start_point[0] + 1,
                })

        # enum_specifier
        for node in _find_all(root, "enum_specifier"):
            name_node = node.child_by_field_name("name")
            body_node = node.child_by_field_name("body")
            if body_node is None:
                continue
            name = None
            if name_node:
                name = name_node.text.decode("utf-8", errors="replace")
            else:
                parent = node.parent
                if parent and parent.type == "type_definition":
                    d = parent.child_by_field_name("declarator")
                    name = _get_declarator_name(d) if d else None
            if not name or name in seen:
                continue
            seen.add(name)

            values = []
            for enumerator in _find_all(body_node, "enumerator"):
                ename = enumerator.child_by_field_name("name")
                eval_ = enumerator.child_by_field_name("value")
                values.append({
                    "name": ename.text.decode("utf-8", errors="replace") if ename else "",
                    "value": eval_.text.decode("utf-8", errors="replace") if eval_ else None,
                })

            types.append({
                "name": name,
                "kind": "enum",
                "values": values,
                "members": [],
                "line": node.start_point[0] + 1,
            })

        # typedef（struct/enum 以外のエイリアス）
        for td_node in _find_all(root, "type_definition"):
            t_node = td_node.child_by_field_name("type")
            d_node = td_node.child_by_field_name("declarator")
            if t_node is None or d_node is None:
                continue
            if t_node.type in ("struct_specifier", "union_specifier", "enum_specifier"):
                continue  # 上で処理済み
            alias_name = _get_declarator_name(d_node)
            if not alias_name or alias_name in seen:
                continue
            seen.add(alias_name)
            types.append({
                "name": alias_name,
                "kind": "typedef",
                "aliased_type": _get_full_type(t_node),
                "members": [],
                "line": td_node.start_point[0] + 1,
            })

        return types

    def _ts_get_issues(self) -> list[dict]:
        issues: list[dict] = []
        root = self._tree.root_node

        # ── 危険な関数 ────────────────────────────────────────────────────
        for call_expr in _find_all(root, "call_expression"):
            fn_node = call_expr.child_by_field_name("function")
            if fn_node and fn_node.type == "identifier":
                fname = fn_node.text.decode("utf-8", errors="replace")
                if fname in _DANGEROUS_FUNCS:
                    enclosing = _enclosing_function(call_expr)
                    issues.append({
                        "severity": "high",
                        "type": "dangerous_function",
                        "message": f"危険な関数の使用: {fname}()",
                        "line": call_expr.start_point[0] + 1,
                        "column": call_expr.start_point[1],
                        "function": enclosing,
                    })

                # ── フォーマット文字列問題 ────────────────────────────────
                if fname in _FORMAT_FUNCS:
                    args_node = call_expr.child_by_field_name("arguments")
                    if args_node:
                        fmt_args = [c for c in args_node.named_children
                                    if c.type != "comment"]
                        # printf系: 第1引数がフォーマット
                        # fprintf等: 第2引数がフォーマット
                        fmt_idx = 1 if fname.startswith("f") and fname != "fflush" else 0
                        if len(fmt_args) > fmt_idx:
                            fmt_node = fmt_args[fmt_idx]
                            if fmt_node.type not in (
                                "string_literal", "concatenated_string"
                            ):
                                enclosing = _enclosing_function(call_expr)
                                issues.append({
                                    "severity": "high",
                                    "type": "format_string",
                                    "message": (
                                        f"フォーマット文字列が文字列リテラルでない: {fname}()"
                                    ),
                                    "line": call_expr.start_point[0] + 1,
                                    "column": call_expr.start_point[1],
                                    "function": enclosing,
                                })

        # ── 各関数内の問題 ────────────────────────────────────────────────
        for fd in _find_all(root, "function_definition"):
            decl = fd.child_by_field_name("declarator")
            inner = decl.child_by_field_name("declarator") if decl else None
            func_name = _get_declarator_name(inner) or "?"
            ret_type_node = fd.child_by_field_name("type")
            ret_type = _get_full_type(ret_type_node)
            body = fd.child_by_field_name("body")
            if body is None:
                continue

            # ── 再帰呼び出し ──────────────────────────────────────────────
            for call_expr in _find_all(body, "call_expression"):
                fn_node = call_expr.child_by_field_name("function")
                if fn_node and fn_node.type == "identifier":
                    if fn_node.text.decode("utf-8", errors="replace") == func_name:
                        issues.append({
                            "severity": "medium",
                            "type": "recursion",
                            "message": f"再帰呼び出し: {func_name}()",
                            "line": call_expr.start_point[0] + 1,
                            "column": call_expr.start_point[1],
                            "function": func_name,
                        })
                        break  # 1関数につき1回だけ報告

            # ── non-void 関数の return 不在 ──────────────────────────────
            is_ptr_return = (
                decl and decl.type == "pointer_declarator"
            )
            is_void = "void" in ret_type and not is_ptr_return
            if not is_void:
                named_stmts = [
                    c for c in body.named_children
                    if c.type not in ("comment",)
                ]
                last = named_stmts[-1] if named_stmts else None
                if last and last.type != "return_statement":
                    issues.append({
                        "severity": "medium",
                        "type": "missing_return",
                        "message": f"non-void関数の末尾にreturnがない: {func_name}()",
                        "line": body.end_point[0] + 1,
                        "column": 0,
                        "function": func_name,
                    })

            # ── switch フォールスルー ──────────────────────────────────────
            for sw in _find_all(body, "switch_statement"):
                sw_body = sw.child_by_field_name("body")
                if sw_body is None:
                    continue
                cases = [
                    c for c in sw_body.children
                    if c.type in ("case_statement", "default_statement")
                ]
                for case_node in cases:
                    # case の直接の文（case_statement/default_statement 以外）
                    case_stmts = [
                        c for c in case_node.children
                        if c.is_named
                        and c.type not in (
                            "case_statement", "default_statement",
                            "comment",
                        )
                    ]
                    if not case_stmts:
                        continue  # 空 case（意図的フォールスルー）
                    last = case_stmts[-1]
                    if last.type not in (
                        "break_statement", "return_statement",
                        "goto_statement", "continue_statement",
                    ):
                        issues.append({
                            "severity": "medium",
                            "type": "switch_fallthrough",
                            "message": (
                                f"switchのフォールスルー（break/return がない）: "
                                f"{func_name}() line {case_node.start_point[0] + 1}"
                            ),
                            "line": case_node.start_point[0] + 1,
                            "column": case_node.start_point[1],
                            "function": func_name,
                        })

        # ── TODO/FIXME コメント ───────────────────────────────────────────
        todo_pattern = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b.*", re.IGNORECASE)
        for i, line_text in enumerate(self._lines, 1):
            m = todo_pattern.search(line_text)
            if m:
                issues.append({
                    "severity": "low",
                    "type": "todo_comment",
                    "message": line_text.strip(),
                    "line": i,
                    "column": m.start(),
                    "function": None,
                })

        return issues

    def _ts_get_skeleton(self) -> dict:
        root = self._tree.root_node

        # includes
        includes = []
        for inc in _find_all(root, "preproc_include"):
            path_node = inc.child_by_field_name("path")
            if path_node:
                includes.append(
                    path_node.text.decode("utf-8", errors="replace")
                )

        # macros
        macros = []
        for d in _find_all(root, "preproc_def"):
            name_node = d.child_by_field_name("name")
            val_node = d.child_by_field_name("value")
            macros.append({
                "name": name_node.text.decode("utf-8", errors="replace") if name_node else "",
                "params": None,
                "value": val_node.text.decode("utf-8", errors="replace").strip() if val_node else "",
            })
        for d in _find_all(root, "preproc_function_def"):
            name_node = d.child_by_field_name("name")
            params_node = d.child_by_field_name("parameters")
            val_node = d.child_by_field_name("value")
            macros.append({
                "name": name_node.text.decode("utf-8", errors="replace") if name_node else "",
                "params": params_node.text.decode("utf-8", errors="replace") if params_node else None,
                "value": val_node.text.decode("utf-8", errors="replace").strip() if val_node else "",
            })

        # types（get_types()を再利用）
        types = self.get_types()

        # function signatures (definitions + prototypes)
        sigs = []
        seen: set[str] = set()

        # function_definition（実装）
        for fd in _find_all(root, "function_definition"):
            decl = fd.child_by_field_name("declarator")
            if decl is None:
                continue
            inner = decl.child_by_field_name("declarator")
            name = _get_declarator_name(inner)
            if not name or name in _C_KEYWORDS or name in seen:
                continue
            seen.add(name)

            ret_type_node = fd.child_by_field_name("type")
            ret_type = _get_full_type(ret_type_node)
            qualifiers = _get_qualifiers_from_fd(fd)
            params_node = decl.child_by_field_name("parameters")
            params = self._ts_parse_params(params_node)

            sigs.append({
                "name": name,
                "return_type": ret_type,
                "params": params,
                "line": fd.start_point[0] + 1,
                "qualifiers": qualifiers,
            })

        # declaration（プロトタイプ: ヘッダーファイル用）
        for d in _find_all(root, "declaration"):
            decl = d.child_by_field_name("declarator")
            if decl is None:
                continue
            # function_declarator が直接または pointer_declarator 内にある場合
            fn_decl = None
            if decl.type == "function_declarator":
                fn_decl = decl
            elif decl.type == "pointer_declarator":
                inner_d = decl.child_by_field_name("declarator")
                if inner_d and inner_d.type == "function_declarator":
                    fn_decl = inner_d
            if fn_decl is None:
                continue

            inner = fn_decl.child_by_field_name("declarator")
            name = _get_declarator_name(inner)
            if not name or name in _C_KEYWORDS or name in seen:
                continue
            seen.add(name)

            ret_type_node = d.child_by_field_name("type")
            ret_type = _get_full_type(ret_type_node)
            qualifiers = []
            for i, c in enumerate(d.children):
                if c.type in ("storage_class_specifier", "type_qualifier"):
                    qualifiers.append(c.text.decode("utf-8", errors="replace"))
            params_node = fn_decl.child_by_field_name("parameters")
            params = self._ts_parse_params(params_node)

            sigs.append({
                "name": name,
                "return_type": ret_type,
                "params": params,
                "line": d.start_point[0] + 1,
                "qualifiers": qualifiers,
            })

        return {
            "file": self.filepath,
            "includes": includes,
            "macros": macros,
            "types": types,
            "function_signatures": sigs,
        }

    def _ts_get_control_flow(self) -> list[dict]:
        """関数ごとの制御フロー構造（木形式）。"""
        result = []
        root = self._tree.root_node
        for fd in _find_all(root, "function_definition"):
            decl = fd.child_by_field_name("declarator")
            inner = decl.child_by_field_name("declarator") if decl else None
            func_name = _get_declarator_name(inner) or "?"
            body = fd.child_by_field_name("body")
            if body is None:
                continue
            blocks = self._build_cf_blocks(body)
            result.append({
                "function": func_name,
                "blocks": blocks,
            })
        return result

    def _build_cf_blocks(self, node: Any) -> list[dict]:
        blocks = []
        cf_types = {
            "if_statement": "branch",
            "while_statement": "loop",
            "for_statement": "loop",
            "do_statement": "loop",
            "switch_statement": "switch",
            "return_statement": "exit",
            "break_statement": "exit",
            "goto_statement": "exit",
        }
        for child in node.children:
            if child.type in cf_types:
                block: dict = {
                    "type": cf_types[child.type],
                    "line": child.start_point[0] + 1,
                    "children": [],
                }
                # 再帰的に子ブロックを収集
                for sub in child.children:
                    if sub.type == "compound_statement":
                        block["children"].extend(self._build_cf_blocks(sub))
                blocks.append(block)
        return blocks

    # ── 正規表現フォールバック実装 ────────────────────────────────────────

    def _regex_get_functions(self) -> list[dict]:
        funcs = []
        seen: set[str] = set()
        src = self._source_stripped
        for match in _FUNC_DEF.finditer(src):
            name = match.group(1)
            if name in _C_KEYWORDS or name in seen:
                continue
            seen.add(name)
            line = src[:match.start()].count("\n") + 1
            body = self._extract_body(match.end() - 1)
            calls = self._get_calls_in(body)
            cyclomatic = 1 + len(_BRANCH_PATTERN.findall(body))
            funcs.append({
                "name": name,
                "line": line,
                "end_line": line + body.count("\n"),
                "lines": body.count("\n") + 1,
                "return_type": "",
                "params": [],
                "calls": calls,
                "call_sites": [{"name": c, "line": 0} for c in calls],
                "cyclomatic": cyclomatic,
                "max_nesting": self._max_nesting(body),
                "qualifiers": [],
                "recursive": name in set(calls),
            })
        return funcs

    def _regex_get_imports(self) -> list[dict]:
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

    def _regex_get_all_calls(self) -> set[str]:
        calls: set[str] = set()
        for match in _CALL.finditer(self._source_stripped):
            name = match.group(1)
            if name not in _C_KEYWORDS and len(name) > 1:
                calls.add(name)
        return calls

    def _regex_get_variables(self) -> list[dict]:
        vars_: list[dict] = []
        seen: set[str] = set()
        for match in _GLOBAL_VAR.finditer(self._source_stripped):
            name = match.group(1)
            if name in _C_KEYWORDS or name in seen:
                continue
            seen.add(name)
            line = self._source_stripped[:match.start()].count("\n") + 1
            vars_.append({
                "name": name,
                "type": "variable",
                "line": line,
                "scope": "global",
                "function": None,
                "qualifiers": [],
                "written_by": [],
                "read_by": [],
            })
        return vars_

    def _regex_get_types(self) -> list[dict]:
        types = []
        for match in _TYPE_DEF.finditer(self._source_stripped):
            name = match.group(1)
            line = self._source_stripped[:match.start()].count("\n") + 1
            types.append({
                "name": name,
                "kind": "struct",
                "members": [],
                "line": line,
            })
        return types

    def _regex_get_issues(self) -> list[dict]:
        issues = []
        dangerous_re = re.compile(
            r"\b(gets|strcpy|strcat|sprintf|scanf)\s*\("
        )
        for match in dangerous_re.finditer(self._source_stripped):
            line = self._source_stripped[:match.start()].count("\n") + 1
            issues.append({
                "severity": "high",
                "type": "dangerous_function",
                "message": f"危険な関数の使用: {match.group(1)}()",
                "line": line,
                "column": 0,
                "function": None,
            })
        todo_re = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b.*", re.IGNORECASE)
        for i, line_text in enumerate(self._lines, 1):
            m = todo_re.search(line_text)
            if m:
                issues.append({
                    "severity": "low",
                    "type": "todo_comment",
                    "message": line_text.strip(),
                    "line": i,
                    "column": m.start(),
                    "function": None,
                })
        return issues

    def _regex_get_skeleton(self) -> dict:
        sigs = []
        seen: set[str] = set()
        src = self._source_stripped
        for match in _FUNC_DEF.finditer(src):
            name = match.group(1)
            if name in _C_KEYWORDS or name in seen:
                continue
            seen.add(name)
            line = src[:match.start()].count("\n") + 1
            sigs.append({
                "name": name,
                "return_type": "",
                "params": [],
                "line": line,
                "qualifiers": [],
            })
        includes = [m.group(1) for m in _INCLUDE.finditer(self._source)]
        macros = [
            {"name": m.group(1), "params": m.group(2), "value": m.group(3).strip()}
            for m in _DEFINE.finditer(self._source)
        ]
        return {
            "file": self.filepath,
            "includes": includes,
            "macros": macros,
            "types": self._regex_get_types(),
            "function_signatures": sigs,
        }

    # ── 正規表現ヘルパー ──────────────────────────────────────────────────

    def _extract_body(self, start: int) -> str:
        depth = 0
        i = start
        src = self._source_stripped
        while i < len(src):
            if src[i] == "{":
                depth += 1
            elif src[i] == "}":
                depth -= 1
                if depth == 0:
                    return src[start:i + 1]
            i += 1
        return src[start:]

    def _get_calls_in(self, body: str) -> list[str]:
        calls: set[str] = set()
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
