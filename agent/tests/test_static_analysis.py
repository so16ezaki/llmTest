"""静的解析のユニットテスト。"""

import json
import os
import tempfile

import pytest

C_PROJECT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "test_data", "c_project")


class TestStaticAnalysis:
    """static_analysis モジュールのテスト。"""

    def test_metrics(self):
        from tools.static_analysis import static_analysis
        if not os.path.exists(C_PROJECT_DIR):
            pytest.skip("test_data/c_project not available")
        result = json.loads(static_analysis(C_PROJECT_DIR, "metrics"))
        assert "error" not in result
        assert result["total_files"] > 0
        assert result["total_lines"] > 0

    def test_call_graph(self):
        from tools.static_analysis import static_analysis
        if not os.path.exists(C_PROJECT_DIR):
            pytest.skip("test_data/c_project not available")
        result = json.loads(static_analysis(C_PROJECT_DIR, "call_graph"))
        assert "nodes" in result
        assert "edges" in result
        assert len(result["nodes"]) > 0

    def test_dependency_graph(self):
        from tools.static_analysis import static_analysis
        if not os.path.exists(C_PROJECT_DIR):
            pytest.skip("test_data/c_project not available")
        result = json.loads(static_analysis(C_PROJECT_DIR, "dependency_graph"))
        assert "nodes" in result
        assert "edges" in result

    def test_complexity(self):
        from tools.static_analysis import static_analysis
        if not os.path.exists(C_PROJECT_DIR):
            pytest.skip("test_data/c_project not available")
        result = json.loads(static_analysis(C_PROJECT_DIR, "complexity"))
        assert "functions" in result
        assert len(result["functions"]) > 0
        # 複雑度でソートされているはず
        complexities = [f["cyclomatic"] for f in result["functions"]]
        assert complexities == sorted(complexities, reverse=True)

    def test_dead_code(self):
        from tools.static_analysis import static_analysis
        if not os.path.exists(C_PROJECT_DIR):
            pytest.skip("test_data/c_project not available")
        result = json.loads(static_analysis(C_PROJECT_DIR, "dead_code"))
        assert "unused_functions" in result
        assert "unused_variables" in result
        assert "unused_imports" in result

    def test_symbol_table(self):
        from tools.static_analysis import static_analysis
        if not os.path.exists(C_PROJECT_DIR):
            pytest.skip("test_data/c_project not available")
        result = json.loads(static_analysis(C_PROJECT_DIR, "symbol_table"))
        assert "symbols" in result
        assert len(result["symbols"]) > 0

    def test_type_info(self):
        from tools.static_analysis import static_analysis
        if not os.path.exists(C_PROJECT_DIR):
            pytest.skip("test_data/c_project not available")
        result = json.loads(static_analysis(C_PROJECT_DIR, "type_info"))
        assert "types" in result

    def test_issues(self):
        from tools.static_analysis import static_analysis
        if not os.path.exists(C_PROJECT_DIR):
            pytest.skip("test_data/c_project not available")
        result = json.loads(static_analysis(C_PROJECT_DIR, "issues"))
        assert "issues" in result

    def test_data_flow(self):
        from tools.static_analysis import static_analysis
        if not os.path.exists(C_PROJECT_DIR):
            pytest.skip("test_data/c_project not available")
        result = json.loads(static_analysis(C_PROJECT_DIR, "data_flow"))
        assert "data_flow" in result

    def test_control_flow(self):
        from tools.static_analysis import static_analysis
        if not os.path.exists(C_PROJECT_DIR):
            pytest.skip("test_data/c_project not available")
        result = json.loads(static_analysis(C_PROJECT_DIR, "control_flow"))
        assert "functions" in result
        assert len(result["functions"]) > 0
        # some functions should have blocks
        has_blocks = any(len(f.get("blocks", [])) > 0 for f in result["functions"])
        assert has_blocks

    def test_data_flow_python(self):
        """Python ファイルで data_flow が assignments/references を返すことを確認。"""
        from tools.static_analysis import static_analysis
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("x = 10\nx += 5\nprint(x)\n")
            f.flush()
            result = json.loads(static_analysis(f.name, "data_flow"))
        os.unlink(f.name)
        assert "data_flow" in result
        x_entries = [e for e in result["data_flow"] if e["variable"] == "x"]
        assert len(x_entries) > 0
        assert len(x_entries[0]["definitions"]) > 0
        assert len(x_entries[0]["references"]) > 0

    def test_unknown_analysis(self):
        from tools.static_analysis import static_analysis
        result = json.loads(static_analysis(C_PROJECT_DIR, "unknown_type"))
        assert "error" in result

    def test_nonexistent_path(self):
        from tools.static_analysis import static_analysis
        result = json.loads(static_analysis("/nonexistent/path", "metrics"))
        assert "error" in result
