"""パーサーのユニットテスト。"""

import os
import tempfile

import pytest

# conftest.py が sys.path を設定するので直接使える
C_PROJECT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "test_data", "c_project")


class TestPythonParser:
    """Python パーサーのテスト。"""

    def _make_parser(self, code: str):
        from tools.parsers.python_parser import PythonParser
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()
            parser = PythonParser(f.name)
        os.unlink(f.name)
        return parser

    def test_get_functions_basic(self):
        parser = self._make_parser("def hello():\n    pass\n\ndef world():\n    hello()\n")
        funcs = parser.get_functions()
        names = [f["name"] for f in funcs]
        assert "hello" in names
        assert "world" in names

    def test_get_functions_calls(self):
        parser = self._make_parser("def foo():\n    bar()\n\ndef bar():\n    pass\n")
        funcs = {f["name"]: f for f in parser.get_functions()}
        assert "bar" in funcs["foo"]["calls"]

    def test_get_functions_has_blocks(self):
        code = "def check(x):\n    if x > 0:\n        for i in range(x):\n            pass\n"
        parser = self._make_parser(code)
        funcs = parser.get_functions()
        assert len(funcs) == 1
        blocks = funcs[0]["blocks"]
        assert len(blocks) > 0
        assert blocks[0]["type"] == "if"

    def test_cyclomatic_complexity(self):
        code = "def complex_fn(x):\n    if x:\n        pass\n    elif x > 1:\n        pass\n    for i in range(x):\n        pass\n"
        parser = self._make_parser(code)
        funcs = parser.get_functions()
        assert funcs[0]["cyclomatic"] > 1

    def test_get_imports(self):
        parser = self._make_parser("import os\nfrom sys import path\n")
        imports = parser.get_imports()
        modules = [i["module"] for i in imports]
        assert "os" in modules
        assert "sys" in modules

    def test_get_variables(self):
        parser = self._make_parser("x = 10\ny: int = 20\n")
        vars_ = parser.get_variables()
        names = [v["name"] for v in vars_]
        assert "x" in names
        assert "y" in names

    def test_get_types(self):
        code = "class MyClass:\n    def method(self):\n        pass\n"
        parser = self._make_parser(code)
        types = parser.get_types()
        assert len(types) == 1
        assert types[0]["name"] == "MyClass"
        assert "method" in types[0]["members"]

    def test_get_issues_recursion(self):
        code = "def rec(n):\n    return rec(n - 1)\n"
        parser = self._make_parser(code)
        issues = parser.get_issues()
        types = [i["type"] for i in issues]
        assert "recursion" in types

    def test_get_issues_bare_except(self):
        code = "try:\n    pass\nexcept:\n    pass\n"
        parser = self._make_parser(code)
        issues = parser.get_issues()
        types = [i["type"] for i in issues]
        assert "bare_except" in types

    def test_get_issues_resource_leak(self):
        code = "f = open('test.txt')\ndata = f.read()\n"
        parser = self._make_parser(code)
        issues = parser.get_issues()
        types = [i["type"] for i in issues]
        assert "resource_leak" in types

    def test_get_issues_infinite_loop(self):
        code = "def run():\n    while True:\n        do_something()\n"
        parser = self._make_parser(code)
        issues = parser.get_issues()
        types = [i["type"] for i in issues]
        assert "infinite_loop" in types

    def test_get_data_flow(self):
        code = "x = 10\nx += 5\nprint(x)\n"
        parser = self._make_parser(code)
        flow = parser.get_data_flow()
        x_flow = [f for f in flow if f["variable"] == "x"]
        assert len(x_flow) == 1
        assert len(x_flow[0]["definitions"]) > 0
        assert len(x_flow[0]["references"]) > 0

    def test_syntax_error_graceful(self):
        parser = self._make_parser("def broken(\n")
        assert parser.get_functions() == []
        assert parser.get_issues() == []


class TestCParser:
    """C パーサーのテスト。"""

    def test_get_functions_from_test_data(self):
        from tools.parsers.c_parser import CParser
        main_c = os.path.join(C_PROJECT_DIR, "src", "main.c")
        if not os.path.exists(main_c):
            pytest.skip("test_data/c_project not available")
        parser = CParser(main_c)
        funcs = parser.get_functions()
        names = [f["name"] for f in funcs]
        # init_system, run_monitor, print_summary are static functions
        assert len(names) >= 3
        assert "init_system" in names

    def test_get_functions_has_blocks(self):
        from tools.parsers.c_parser import CParser
        main_c = os.path.join(C_PROJECT_DIR, "src", "main.c")
        if not os.path.exists(main_c):
            pytest.skip("test_data/c_project not available")
        parser = CParser(main_c)
        funcs = {f["name"]: f for f in parser.get_functions()}
        # run_monitor has while/if blocks
        if "run_monitor" in funcs:
            assert len(funcs["run_monitor"]["blocks"]) > 0

    def test_get_types_with_members(self):
        from tools.parsers.c_parser import CParser
        with tempfile.NamedTemporaryFile(mode="w", suffix=".c", delete=False) as f:
            f.write("struct Point {\n    int x;\n    int y;\n};\n\nenum Color { RED, GREEN, BLUE };\n")
            f.flush()
            parser = CParser(f.name)
        os.unlink(f.name)
        types = parser.get_types()
        names = [t["name"] for t in types]
        assert "Point" in names
        assert "Color" in names
        point = [t for t in types if t["name"] == "Point"][0]
        assert point["kind"] == "struct"
        assert "x" in point["members"]
        assert "y" in point["members"]
        color = [t for t in types if t["name"] == "Color"][0]
        assert color["kind"] == "enum"
        assert "RED" in color["members"]

    def test_get_issues_dangerous_function(self):
        from tools.parsers.c_parser import CParser
        with tempfile.NamedTemporaryFile(mode="w", suffix=".c", delete=False) as f:
            f.write("void foo() {\n    char buf[10];\n    gets(buf);\n}\n")
            f.flush()
            parser = CParser(f.name)
        os.unlink(f.name)
        issues = parser.get_issues()
        types = [i["type"] for i in issues]
        assert "dangerous_function" in types

    def test_get_imports(self):
        from tools.parsers.c_parser import CParser
        main_c = os.path.join(C_PROJECT_DIR, "src", "main.c")
        if not os.path.exists(main_c):
            pytest.skip("test_data/c_project not available")
        parser = CParser(main_c)
        imports = parser.get_imports()
        modules = [i["module"] for i in imports]
        assert "stdio.h" in modules


class TestJsParser:
    """JavaScript パーサーのテスト。"""

    def _make_parser(self, code: str):
        from tools.parsers.js_parser import JsParser
        with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as f:
            f.write(code)
            f.flush()
            parser = JsParser(f.name)
        os.unlink(f.name)
        return parser

    def test_get_functions(self):
        parser = self._make_parser("function hello() { return 1; }\nconst greet = () => 'hi';\n")
        funcs = parser.get_functions()
        names = [f["name"] for f in funcs]
        assert "hello" in names

    def test_get_functions_has_blocks(self):
        parser = self._make_parser("function check(x) { if (x > 0) { for (let i = 0; i < x; i++) {} } }\n")
        funcs = parser.get_functions()
        assert len(funcs) > 0
        assert len(funcs[0]["blocks"]) > 0

    def test_get_imports(self):
        parser = self._make_parser("import React from 'react';\nconst fs = require('fs');\n")
        imports = parser.get_imports()
        modules = [i["module"] for i in imports]
        assert "react" in modules
        assert "fs" in modules

    def test_get_types_class(self):
        parser = self._make_parser("class Animal extends Base {}\ninterface Shape {}\n")
        types = parser.get_types()
        names = [t["name"] for t in types]
        assert "Animal" in names
        assert "Shape" in names

    def test_get_issues_eval(self):
        parser = self._make_parser("const x = eval('1 + 2');\n")
        issues = parser.get_issues()
        types = [i["type"] for i in issues]
        assert "eval_usage" in types

    def test_get_issues_loose_equality(self):
        parser = self._make_parser("if (x == null) {}\n")
        issues = parser.get_issues()
        types = [i["type"] for i in issues]
        assert "loose_equality" in types

    def test_get_issues_innerHTML(self):
        parser = self._make_parser("el.innerHTML = userInput;\n")
        issues = parser.get_issues()
        types = [i["type"] for i in issues]
        assert "xss_risk" in types


class TestGenericParser:
    """汎用パーサーのテスト。"""

    def _make_parser(self, code: str, ext: str = ".go"):
        from tools.parsers.generic_parser import GenericParser
        with tempfile.NamedTemporaryFile(mode="w", suffix=ext, delete=False) as f:
            f.write(code)
            f.flush()
            parser = GenericParser(f.name)
        os.unlink(f.name)
        return parser

    def test_get_functions_go(self):
        parser = self._make_parser("func main() {\n    fmt.Println(\"hello\")\n}\n")
        funcs = parser.get_functions()
        names = [f["name"] for f in funcs]
        assert "main" in names

    def test_get_imports_go(self):
        parser = self._make_parser("import \"fmt\"\n")
        imports = parser.get_imports()
        assert len(imports) > 0
