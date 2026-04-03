"""コンパクションのユニットテスト。"""

import pytest

tiktoken = pytest.importorskip("tiktoken", reason="tiktoken not installed")


class TestCompactor:
    """compactor モジュールのテスト。"""

    def _make_messages(self, n_tool_results: int, result_size: int = 500) -> list[dict]:
        """テスト用メッセージリストを生成する。"""
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Analyze this project."},
        ]
        for i in range(n_tool_results):
            messages.append({"role": "assistant", "content": f"Calling tool {i}"})
            messages.append({
                "role": "tool",
                "name": f"tool_{i}",
                "content": f"Result {i}: " + "x" * result_size,
            })
        return messages

    def test_tier1_clears_old_results(self):
        from compactor import _tier1
        messages = self._make_messages(10)
        original_len = len(messages)
        result = _tier1(messages)
        # メッセージ数は変わらないが、古いtool結果が[cleared]に
        assert len(result) == original_len
        cleared = [m for m in result if m.get("role") == "tool" and m["content"] == "[cleared]"]
        assert len(cleared) > 0

    def test_tier1_keeps_recent(self):
        from compactor import _tier1
        from config import TIER1_KEEP_RESULTS
        messages = self._make_messages(10)
        result = _tier1(messages)
        tool_msgs = [m for m in result if m.get("role") == "tool" and m["content"] != "[cleared]"]
        assert len(tool_msgs) == TIER1_KEEP_RESULTS

    def test_usage_ratio(self):
        from compactor import usage_ratio
        messages = self._make_messages(5)
        ratio = usage_ratio(messages)
        assert 0.0 < ratio < 1.0

    def test_needs_compaction_below_threshold(self):
        from compactor import needs_compaction
        messages = self._make_messages(2)
        assert not needs_compaction(messages)

    def test_tier2_truncates(self):
        from compactor import _tier2
        messages = self._make_messages(5, result_size=10000)
        result = _tier2(messages)
        # Tier2後のtool結果は元より短くなっているはず
        for msg in result:
            if msg.get("role") == "tool" and msg["content"] != "[cleared]":
                assert len(msg["content"]) < 10000
