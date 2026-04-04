"""
進捗表示のイベントフロー検証テスト。

テスト対象:
  - gui.py の IngestBarState / apply_progress_event / apply_progress_line
  - knowledge_to_skills.py の _emit_progress / _write_sections_parallel / _process_file

実行方法:
  cd agent
  python -m pytest test_progress.py -v
  # または
  python test_progress.py
"""

import os
import sys
import tempfile
import unittest

# agent/ ディレクトリをパスに追加
sys.path.insert(0, os.path.dirname(__file__))


# ──────────────────────────────────────────────────────────────
# gui.py から tkinter 不要のクラス/関数だけをインポート
# ──────────────────────────────────────────────────────────────

def _import_gui_logic():
    """tkinter の import を回避しながら gui.py の純粋関数をインポートする。"""
    import importlib, types, unittest.mock as mock

    # tkinter 系モジュールをモックで差し替え
    for mod in ["tkinter", "tkinter.ttk", "tkinter.filedialog",
                "tkinter.messagebox", "tkinter.font"]:
        sys.modules.setdefault(mod, mock.MagicMock())

    # PIL も不要なのでモック
    sys.modules.setdefault("PIL", mock.MagicMock())
    sys.modules.setdefault("PIL.Image", mock.MagicMock())

    import gui as _gui
    return _gui

_gui = _import_gui_logic()
IngestBarState      = _gui.IngestBarState
apply_progress_event = _gui.apply_progress_event
apply_progress_line  = _gui.apply_progress_line


# ──────────────────────────────────────────────────────────────
# 1. IngestBarState の初期値
# ──────────────────────────────────────────────────────────────

class TestIngestBarStateInit(unittest.TestCase):
    def test_initial_modes_are_indeterminate(self):
        s = IngestBarState()
        self.assertEqual(s.prog_ch_mode, "indeterminate")
        self.assertEqual(s.prog_tk_mode, "indeterminate")

    def test_initial_bars_not_initialized(self):
        s = IngestBarState()
        self.assertFalse(s.bars_initialized)


# ──────────────────────────────────────────────────────────────
# 2. apply_progress_event — init イベント
# ──────────────────────────────────────────────────────────────

class TestApplyProgressEventInit(unittest.TestCase):
    def setUp(self):
        self.s = IngestBarState()
        apply_progress_event(self.s, {"event": "init", "ch_n": 10, "tk_n": 50000})

    def test_bars_initialized(self):
        self.assertTrue(self.s.bars_initialized)

    def test_ch_mode_becomes_determinate(self):
        self.assertEqual(self.s.prog_ch_mode, "determinate")

    def test_tk_mode_becomes_determinate(self):
        self.assertEqual(self.s.prog_tk_mode, "determinate")

    def test_ch_max_set(self):
        self.assertEqual(self.s.prog_ch_max, 10)

    def test_tk_max_set(self):
        self.assertEqual(self.s.prog_tk_max, 50000)

    def test_ch_txt_shows_zero_percent(self):
        self.assertIn("0%", self.s.prog_ch_txt)
        self.assertIn("0/10", self.s.prog_ch_txt)

    def test_tk_txt_shows_zero_tokens(self):
        self.assertIn("0/", self.s.prog_tk_txt)
        self.assertIn("50,000", self.s.prog_tk_txt)

    def test_hier_txt_set(self):
        self.assertEqual(self.s.hier_txt, "処理開始...")


# ──────────────────────────────────────────────────────────────
# 3. apply_progress_event — chunk イベント（init 後）
# ──────────────────────────────────────────────────────────────

class TestApplyProgressEventChunkAfterInit(unittest.TestCase):
    def setUp(self):
        self.s = IngestBarState()
        apply_progress_event(self.s, {"event": "init", "ch_n": 10, "tk_n": 50000})

    def test_chunk_updates_progress_bar(self):
        apply_progress_event(self.s, {
            "event": "chunk", "ch_i": 3, "ch_n": 10, "tk_cum": 15000, "title": "第3章"
        })
        self.assertEqual(self.s.prog_ch_val, 3)
        self.assertIn("30%", self.s.prog_ch_txt)
        self.assertIn("3/10", self.s.prog_ch_txt)

    def test_chunk_updates_token_bar(self):
        apply_progress_event(self.s, {
            "event": "chunk", "ch_i": 3, "ch_n": 10, "tk_cum": 15000, "title": "第3章"
        })
        # トークンバーが determinate なので更新されるべき
        self.assertEqual(self.s.prog_tk_val, 15000)
        self.assertIn("15,000/50,000", self.s.prog_tk_txt)

    def test_chunk_with_title_updates_hierarchy(self):
        apply_progress_event(self.s, {
            "event": "chunk", "ch_i": 3, "ch_n": 10, "tk_cum": 15000, "title": "第3章"
        })
        self.assertEqual(self.s.hier_txt, "第3章")

    def test_chunk_with_level_and_title(self):
        apply_progress_event(self.s, {
            "event": "chunk", "ch_i": 1, "ch_n": 10, "tk_cum": 0,
            "level": 2, "title": "設定方法"
        })
        self.assertEqual(self.s.hier_txt, "Lv2: 設定方法")

    def test_chunk_without_title_does_not_change_hier(self):
        self.s.hier_txt = "処理開始..."
        apply_progress_event(self.s, {
            "event": "chunk", "ch_i": 1, "ch_n": 10, "tk_cum": 0
        })
        self.assertEqual(self.s.hier_txt, "処理開始...")  # 変わらない

    def test_token_bar_capped_at_max(self):
        apply_progress_event(self.s, {
            "event": "chunk", "ch_i": 10, "ch_n": 10, "tk_cum": 999999, "title": "最終章"
        })
        self.assertEqual(self.s.prog_tk_val, 50000)  # max に clamp される


# ──────────────────────────────────────────────────────────────
# 4. apply_progress_event — init なしで chunk が先に来る場合
# ──────────────────────────────────────────────────────────────

class TestApplyProgressEventChunkBeforeInit(unittest.TestCase):
    def test_chunk_without_init_initializes_ch_bar(self):
        s = IngestBarState()
        apply_progress_event(s, {
            "event": "chunk", "ch_i": 1, "ch_n": 10, "tk_cum": 5000, "title": "第1章"
        })
        self.assertTrue(s.bars_initialized)
        self.assertEqual(s.prog_ch_mode, "determinate")

    def test_chunk_without_init_token_bar_stays_indeterminate(self):
        """init なしでは tk_mode が indeterminate のまま → /-- 表示"""
        s = IngestBarState()
        apply_progress_event(s, {
            "event": "chunk", "ch_i": 1, "ch_n": 10, "tk_cum": 5000, "title": "第1章"
        })
        self.assertEqual(s.prog_tk_mode, "indeterminate")
        self.assertIn("/--", s.prog_tk_txt)


# ──────────────────────────────────────────────────────────────
# 5. apply_progress_line — stderr テキスト解析
# ──────────────────────────────────────────────────────────────

class TestApplyProgressLine(unittest.TestCase):
    def test_pdf_line_updates_progress_text(self):
        s = IngestBarState()
        # 16/108 → 16*100//108 = 14%
        apply_progress_line(s, "\r  PDF変換: [████░░░░░] 14% (16/108チャンク)")
        self.assertIn("14%", s.prog_ch_txt)
        self.assertIn("16/108", s.prog_ch_txt)

    def test_pdf_line_sets_hierarchy_to_pdf_converting(self):
        s = IngestBarState()
        apply_progress_line(s, "\r  PDF変換: [████░░░░░] 14% (15/108チャンク)")
        self.assertEqual(s.hier_txt, "PDF変換中...")

    def test_pdf_line_sets_token_to_loading(self):
        s = IngestBarState()
        apply_progress_line(s, "\r  PDF変換: [████░░░░░] 14% (15/108チャンク)")
        self.assertEqual(s.prog_tk_txt, "読み込み中...")

    def test_pdf_line_ignored_after_init(self):
        """init 後は PDF 行を無視する（bars_initialized=True）"""
        s = IngestBarState()
        apply_progress_event(s, {"event": "init", "ch_n": 10, "tk_n": 50000})
        s.hier_txt = "処理開始..."
        apply_progress_line(s, "\r  PDF変換: [████░░░░░] 14% (15/108チャンク)")
        # init 後なので hier_txt は変わらない
        self.assertEqual(s.hier_txt, "処理開始...")

    def test_init_stderr_line_switches_to_determinate(self):
        s = IngestBarState()
        apply_progress_line(s, "  セクション処理: 20章 / 予算100,000トークン")
        self.assertTrue(s.bars_initialized)
        self.assertEqual(s.prog_ch_mode, "determinate")
        self.assertEqual(s.prog_tk_mode, "determinate")
        self.assertEqual(s.prog_ch_max, 20)
        self.assertEqual(s.prog_tk_max, 100000)

    def test_step_1_sets_label(self):
        s = IngestBarState()
        apply_progress_line(s, "  [1/4] ファイル読み込み...")
        self.assertEqual(s.hier_txt, "読み込み中...")

    def test_step_2_sets_label(self):
        s = IngestBarState()
        apply_progress_line(s, "  [2/4] セクション分割...")
        self.assertEqual(s.hier_txt, "分割中...")

    def test_step_line_ignored_after_init(self):
        s = IngestBarState()
        apply_progress_event(s, {"event": "init", "ch_n": 10, "tk_n": 50000})
        s.hier_txt = "処理開始..."
        apply_progress_line(s, "  [2/4] セクション分割...")
        self.assertEqual(s.hier_txt, "処理開始...")  # 変わらない

    def test_token_limit_exceeded_fills_bar(self):
        s = IngestBarState()
        apply_progress_event(s, {"event": "init", "ch_n": 10, "tk_n": 50000})
        apply_progress_line(s, "  トークン予算超過: Lv2章'...'で停止")
        self.assertEqual(s.prog_tk_val, 50000)

    def test_ch_line_updates_bars(self):
        s = IngestBarState()
        apply_progress_event(s, {"event": "init", "ch_n": 10, "tk_n": 50000})
        apply_progress_line(s, "  [3/10] Lv2: 第3章 — 5セクション, 3,000トークン（累計8,500）")
        self.assertEqual(s.prog_ch_val, 3)
        self.assertIn("30%", s.prog_ch_txt)
        self.assertEqual(s.prog_tk_val, 8500)


# ──────────────────────────────────────────────────────────────
# 6. knowledge_to_skills — イベント送信の検証
# ──────────────────────────────────────────────────────────────

class TestKnowledgeToSkillsEvents(unittest.TestCase):
    def setUp(self):
        import knowledge_to_skills as k2s
        self.k2s = k2s
        self.events = []
        k2s._on_progress = lambda ev, **kw: self.events.append({"event": ev, **kw})

    def tearDown(self):
        self.k2s._on_progress = None

    def test_emit_progress_sends_event(self):
        self.k2s._emit_progress("init", ch_n=5, tk_n=10000)
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0]["event"], "init")
        self.assertEqual(self.events[0]["ch_n"], 5)
        self.assertEqual(self.events[0]["tk_n"], 10000)

    def test_emit_progress_chunk_with_title(self):
        self.k2s._emit_progress("chunk", ch_i=1, ch_n=5, tk_cum=1000, title="第1章")
        self.assertEqual(self.events[0]["title"], "第1章")

    def test_emit_progress_chunk_with_level(self):
        self.k2s._emit_progress("chunk", ch_i=1, ch_n=5, tk_cum=1000,
                                 level=2, title="第1章")
        self.assertEqual(self.events[0]["level"], 2)

    def test_emit_progress_silent_when_no_callback(self):
        self.k2s._on_progress = None
        # 例外なく実行されるべき
        self.k2s._emit_progress("init", ch_n=5, tk_n=10000)
        self.assertEqual(len(self.events), 0)


class TestWriteSectionsParallelEvents(unittest.TestCase):
    def setUp(self):
        import knowledge_to_skills as k2s
        self.k2s = k2s
        self.events = []
        k2s._on_progress = lambda ev, **kw: self.events.append({"event": ev, **kw})

    def tearDown(self):
        self.k2s._on_progress = None

    def test_chunk_events_emitted_for_each_section(self):
        sections = [
            {"title": f"章{i}", "content": "A" * 200}
            for i in range(5)
        ]
        with tempfile.TemporaryDirectory() as d:
            self.k2s._write_sections_parallel(
                sections, d, source_name="test.pdf", _report_progress=True
            )
        chunk_events = [e for e in self.events if e["event"] == "chunk"]
        self.assertEqual(len(chunk_events), 5)

    def test_chunk_events_have_title(self):
        sections = [
            {"title": "テスト章", "content": "B" * 200}
        ]
        with tempfile.TemporaryDirectory() as d:
            self.k2s._write_sections_parallel(
                sections, d, source_name="test.pdf", _report_progress=True
            )
        ev = self.events[0]
        self.assertIn("title", ev)
        self.assertTrue(ev["title"])

    def test_chunk_events_sequential_ch_i(self):
        """max_workers=1 なので ch_i は 1,2,3... の順になるはず"""
        sections = [
            {"title": f"章{i}", "content": "C" * 200}
            for i in range(5)
        ]
        with tempfile.TemporaryDirectory() as d:
            self.k2s._write_sections_parallel(
                sections, d, source_name="test.pdf", _report_progress=True
            )
        ch_is = [e["ch_i"] for e in self.events if e["event"] == "chunk"]
        self.assertEqual(ch_is, [1, 2, 3, 4, 5])

    def test_no_events_when_report_progress_false(self):
        sections = [{"title": "章", "content": "D" * 200}]
        with tempfile.TemporaryDirectory() as d:
            self.k2s._write_sections_parallel(
                sections, d, source_name="test.pdf", _report_progress=False
            )
        self.assertEqual(len(self.events), 0)

    def test_token_cumulative_increases(self):
        sections = [
            {"title": f"章{i}", "content": "E" * 400}
            for i in range(3)
        ]
        with tempfile.TemporaryDirectory() as d:
            self.k2s._write_sections_parallel(
                sections, d, source_name="test.pdf", _report_progress=True
            )
        cums = [e["tk_cum"] for e in self.events if e["event"] == "chunk"]
        for i in range(1, len(cums)):
            self.assertGreater(cums[i], cums[i - 1], "累計トークンは単調増加すべき")


class TestProcessFileEventOrder(unittest.TestCase):
    """
    _process_file が init → chunk の順でイベントを送るか検証。
    実際のファイルを使うため統合テスト。
    """

    def setUp(self):
        import knowledge_to_skills as k2s
        self.k2s = k2s
        self.events = []
        k2s._on_progress = lambda ev, **kw: self.events.append({"event": ev, **kw})

    def tearDown(self):
        self.k2s._on_progress = None

    def test_init_before_first_chunk_for_text_file(self):
        """テキストファイル取り込みで init が chunk より先に来るか"""
        import config
        content = "\n".join(
            f"# 章{i}\n\n{'本文テキスト。' * 30}\n"
            for i in range(1, 6)
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            src = os.path.join(tmpdir, "test.txt")
            with open(src, "w", encoding="utf-8") as f:
                f.write(content)

            orig_skills = config.SKILLS_DIR
            config.SKILLS_DIR = os.path.join(tmpdir, "skills")
            try:
                self.k2s._process_file(src, doc_name="test_doc")
            finally:
                config.SKILLS_DIR = orig_skills

        event_types = [e["event"] for e in self.events]
        self.assertIn("init", event_types, "init イベントが送られるべき")
        self.assertIn("chunk", event_types, "chunk イベントが送られるべき")

        first_init  = event_types.index("init")
        first_chunk = event_types.index("chunk")
        self.assertLess(first_init, first_chunk, "init は chunk より前に来るべき")

    def test_chunk_events_have_title_for_text_file(self):
        import config
        content = "\n".join(
            f"# セクション{i}\n\n{'内容テキスト。' * 30}\n"
            for i in range(1, 4)
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            src = os.path.join(tmpdir, "test_title.txt")
            with open(src, "w", encoding="utf-8") as f:
                f.write(content)

            orig_skills = config.SKILLS_DIR
            config.SKILLS_DIR = os.path.join(tmpdir, "skills")
            try:
                self.k2s._process_file(src, doc_name="test_title_doc")
            finally:
                config.SKILLS_DIR = orig_skills

        chunk_events = [e for e in self.events if e["event"] == "chunk"]
        self.assertTrue(len(chunk_events) > 0, "chunk イベントが1件以上あるべき")
        for ev in chunk_events:
            self.assertIn("title", ev, "chunk に title が含まれるべき")
            self.assertTrue(ev["title"], "title は空でないべき")


# ──────────────────────────────────────────────────────────────
# 7. 典型的なイベントシーケンスのシミュレーション
# ──────────────────────────────────────────────────────────────

class TestTypicalSequenceSimulation(unittest.TestCase):
    """
    GUIのポーリングロジックを IngestBarState でシミュレートし、
    典型的なイベントシーケンスで期待通りに動作するか確認する。
    """

    def _process_sequence(self, events_and_lines):
        """
        events_and_lines: list of:
          ("event", dict)   → apply_progress_event
          ("line", str)     → apply_progress_line
        を処理して最終状態を返す。
        """
        s = IngestBarState()
        for kind, payload in events_and_lines:
            if kind == "event":
                apply_progress_event(s, payload)
            else:
                apply_progress_line(s, payload)
        return s

    def test_standard_pdf_flow(self):
        """標準パス（KNOWLEDGE_MAX_TOKENS=0）の典型シーケンス"""
        seq = [
            ("line", "  [1/4] ファイル読み込み・変換..."),
            ("line", "\r  PDF変換: [░░░░░░░░░░]   0% (0/108チャンク)"),
            ("line", "\r  PDF変換: [████░░░░░░]  14% (15/108チャンク)"),
            ("line", "\r  PDF変換: [██████████] 100% (108/108チャンク)\n"),
            ("line", "  [2/4] セクション分割..."),
            ("line", "  [3/4] LLM構造化...スキップ"),
            ("line", "  セクション処理: 50章 / 予算200,000トークン"),
            ("event", {"event": "init", "ch_n": 50, "tk_n": 200000}),
            ("event", {"event": "chunk", "ch_i": 1,  "ch_n": 50, "tk_cum": 4000,  "title": "第1章"}),
            ("event", {"event": "chunk", "ch_i": 25, "ch_n": 50, "tk_cum": 100000, "title": "第25章"}),
            ("event", {"event": "chunk", "ch_i": 50, "ch_n": 50, "tk_cum": 200000, "title": "第50章"}),
        ]
        s = self._process_sequence(seq)

        # 最終状態の検証
        self.assertTrue(s.bars_initialized)
        self.assertEqual(s.prog_ch_mode, "determinate")
        self.assertEqual(s.prog_tk_mode, "determinate")
        self.assertEqual(s.prog_ch_val, 50)
        self.assertIn("100%", s.prog_ch_txt)
        self.assertEqual(s.hier_txt, "第50章")

    def test_hierarchical_pdf_flow(self):
        """階層パス（KNOWLEDGE_MAX_TOKENS>0）の典型シーケンス: Phase1(章処理) → Phase2(書き出し)"""
        seq = [
            # Phase 1: 階層並列処理
            ("line", "  階層並列処理: 30章 / 150ページ / 予算100,000トークン [Lv1:5, Lv2:25]"),
            ("event", {"event": "init", "ch_n": 30, "tk_n": 100000}),
            ("event", {"event": "chunk", "ch_i": 1, "ch_n": 30, "tk_cum": 3000, "level": 1, "title": "第1部"}),
            ("event", {"event": "chunk", "ch_i": 15, "ch_n": 30, "tk_cum": 50000, "level": 2, "title": "第15章"}),
            ("event", {"event": "chunk", "ch_i": 30, "ch_n": 30, "tk_cum": 95000, "level": 2, "title": "第30章"}),
            # Phase 2: 書き出し（init を再送）
            ("event", {"event": "init", "ch_n": 120, "tk_n": 95000}),
            ("event", {"event": "chunk", "ch_i": 60, "ch_n": 120, "tk_cum": 47000, "title": "第60セクション"}),
            ("event", {"event": "chunk", "ch_i": 120, "ch_n": 120, "tk_cum": 95000, "title": "最終セクション"}),
        ]
        s = self._process_sequence(seq)

        self.assertTrue(s.bars_initialized)
        self.assertEqual(s.prog_ch_val, 120)
        self.assertIn("100%", s.prog_ch_txt)
        self.assertEqual(s.prog_tk_val, 95000)
        self.assertEqual(s.hier_txt, "最終セクション")

    def test_token_bar_stays_indeterminate_without_init(self):
        """init なしで chunk が来てもトークンバーは indeterminate のまま"""
        seq = [
            ("event", {"event": "chunk", "ch_i": 1, "ch_n": 10, "tk_cum": 5000, "title": "章1"}),
        ]
        s = self._process_sequence(seq)
        self.assertEqual(s.prog_tk_mode, "indeterminate")
        self.assertIn("/--", s.prog_tk_txt)

    def test_pdf_conversion_does_not_affect_bars_after_init(self):
        """PDF 変換行は init 後に無視される"""
        seq = [
            ("event", {"event": "init", "ch_n": 10, "tk_n": 50000}),
            ("event", {"event": "chunk", "ch_i": 5, "ch_n": 10, "tk_cum": 25000, "title": "第5章"}),
            # この PDF 行は init 後なので無視されるはず
            ("line", "\r  PDF変換: [████░░░░░░]  14% (15/108チャンク)"),
        ]
        s = self._process_sequence(seq)
        # hier_txt は "第5章" のまま（PDF 行に上書きされない）
        self.assertEqual(s.hier_txt, "第5章")


# ──────────────────────────────────────────────────────────────
# 8. 進捗率データの伝搬テスト
# ──────────────────────────────────────────────────────────────

class TestProgressRateDataPropagation(unittest.TestCase):
    """
    進捗率（パーセンテージ・トークン累計）が
    _emit_progress → IngestBarState に正しく伝搬されるかを検証する。
    GUI (tkinter) 不要の純粋関数テスト + 統合テスト。
    """

    # ── 純粋関数テスト ──

    def test_percentage_at_each_step(self):
        """init(ch_n=10) → chunk 1~10 で各ステップの%テキストを検証"""
        s = IngestBarState()
        apply_progress_event(s, {"event": "init", "ch_n": 10, "tk_n": 50000})
        for i in range(1, 11):
            apply_progress_event(s, {
                "event": "chunk", "ch_i": i, "ch_n": 10,
                "tk_cum": i * 5000, "title": f"章{i}",
            })
            expected_pct = i * 100 // 10
            self.assertEqual(s.prog_ch_val, i)
            self.assertIn(f"{expected_pct}%", s.prog_ch_txt)
            self.assertIn(f"{i}/10", s.prog_ch_txt)

    def test_token_cumulative_in_state(self):
        """各 chunk の tk_cum が prog_tk_val に正しく反映されるか"""
        s = IngestBarState()
        apply_progress_event(s, {"event": "init", "ch_n": 5, "tk_n": 20000})
        tk_values = [3000, 7500, 12000, 16000, 20000]
        for i, tk in enumerate(tk_values, 1):
            apply_progress_event(s, {
                "event": "chunk", "ch_i": i, "ch_n": 5,
                "tk_cum": tk, "title": f"章{i}",
            })
            self.assertEqual(s.prog_tk_val, min(tk, 20000))
            self.assertIn(f"{tk:,}", s.prog_tk_txt)
            self.assertIn("20,000", s.prog_tk_txt)

    def test_percentage_boundary_values(self):
        """境界値: ch_n=1, ch_n=3 (非整数%) でのパーセンテージ計算"""
        # ch_n=1
        s = IngestBarState()
        apply_progress_event(s, {"event": "init", "ch_n": 1, "tk_n": 100})
        apply_progress_event(s, {
            "event": "chunk", "ch_i": 1, "ch_n": 1,
            "tk_cum": 100, "title": "only",
        })
        self.assertIn("100%", s.prog_ch_txt)
        self.assertEqual(s.prog_ch_val, 1)

        # ch_n=3 → 33%, 66%, 100%
        s2 = IngestBarState()
        apply_progress_event(s2, {"event": "init", "ch_n": 3, "tk_n": 300})
        expected = [33, 66, 100]
        for i in range(1, 4):
            apply_progress_event(s2, {
                "event": "chunk", "ch_i": i, "ch_n": 3,
                "tk_cum": i * 100, "title": f"s{i}",
            })
            self.assertIn(f"{expected[i-1]}%", s2.prog_ch_txt)

    def test_token_clamping_at_max(self):
        """tk_cum > tk_n の場合 prog_tk_val がクランプされるか"""
        s = IngestBarState()
        apply_progress_event(s, {"event": "init", "ch_n": 2, "tk_n": 10000})
        apply_progress_event(s, {
            "event": "chunk", "ch_i": 2, "ch_n": 2,
            "tk_cum": 15000, "title": "over",
        })
        self.assertEqual(s.prog_tk_val, 10000, "prog_tk_val は tk_max にクランプされるべき")
        self.assertIn("15,000", s.prog_tk_txt, "テキストには実際の累計値を表示")
        self.assertIn("10,000", s.prog_tk_txt, "テキストには上限値も表示")

    # ── 統合テスト ──

    def test_write_sections_rate_to_state(self):
        """_write_sections_parallel のイベントを State に流して最終 100% 確認"""
        import knowledge_to_skills as k2s
        events = []
        k2s._on_progress = lambda ev, **kw: events.append({"event": ev, **kw})
        sections = [
            {"title": f"セクション{i}", "content": f"内容{'あ' * 200}"}
            for i in range(1, 5)
        ]
        try:
            with tempfile.TemporaryDirectory() as d:
                k2s._write_sections_parallel(
                    sections, d, source_name="test.pdf", _report_progress=True
                )
        finally:
            k2s._on_progress = None

        # イベントを State に流す
        s = IngestBarState()
        apply_progress_event(s, {"event": "init", "ch_n": 4, "tk_n": 100000})
        for ev in events:
            apply_progress_event(s, ev)

        self.assertEqual(s.prog_ch_val, 4)
        self.assertIn("100%", s.prog_ch_txt)
        self.assertGreater(s.prog_tk_val, 0, "トークン累計は0より大きいはず")

    def test_process_file_rate_end_to_end(self):
        """_process_file → イベント収集 → State 再生で 100% 到達確認"""
        import knowledge_to_skills as k2s
        import config

        events = []
        k2s._on_progress = lambda ev, **kw: events.append({"event": ev, **kw})

        content = "\n".join(
            f"# 章{i}\n\n{'テスト本文。' * 30}\n"
            for i in range(1, 6)
        )
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                src = os.path.join(tmpdir, "rate_test.txt")
                with open(src, "w", encoding="utf-8") as f:
                    f.write(content)
                orig_skills = config.SKILLS_DIR
                orig_cache = config.SKILLS_CACHE_FILE
                config.SKILLS_DIR = os.path.join(tmpdir, "skills")
                config.SKILLS_CACHE_FILE = os.path.join(tmpdir, ".cache.json")
                try:
                    k2s._process_file(src, doc_name="rate_test", use_cache=False)
                finally:
                    config.SKILLS_DIR = orig_skills
                    config.SKILLS_CACHE_FILE = orig_cache
        finally:
            k2s._on_progress = None

        # init イベントがあるはず
        init_events = [e for e in events if e["event"] == "init"]
        self.assertTrue(len(init_events) > 0, "init イベントが必要")
        ch_n = init_events[0]["ch_n"]
        tk_n = init_events[0]["tk_n"]
        self.assertGreater(ch_n, 0)
        self.assertGreater(tk_n, 0)

        # State に全イベントを流す
        s = IngestBarState()
        for ev in events:
            apply_progress_event(s, ev)

        self.assertEqual(s.prog_ch_val, ch_n, "全章処理で ch_val == ch_n")
        self.assertIn("100%", s.prog_ch_txt)
        self.assertGreater(s.prog_tk_val, 0)

    def test_no_events_when_cached(self):
        """キャッシュ済みファイルで進捗イベントが 0 件であることを確認"""
        import knowledge_to_skills as k2s
        import config

        content = "# Test\n\nCached content.\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            src = os.path.join(tmpdir, "cached_test.txt")
            with open(src, "w", encoding="utf-8") as f:
                f.write(content)

            orig_skills = config.SKILLS_DIR
            orig_cache = config.SKILLS_CACHE_FILE
            config.SKILLS_DIR = os.path.join(tmpdir, "skills")
            config.SKILLS_CACHE_FILE = os.path.join(tmpdir, ".cache.json")
            try:
                # 1回目: キャッシュ登録
                k2s._process_file(src, doc_name="cached_test", use_cache=True)

                # 2回目: キャッシュヒット → イベント0件
                events = []
                k2s._on_progress = lambda ev, **kw: events.append({"event": ev, **kw})
                try:
                    k2s._process_file(src, doc_name="cached_test", use_cache=True)
                finally:
                    k2s._on_progress = None

                self.assertEqual(len(events), 0, "キャッシュ済みなら進捗イベントは発生しない")
            finally:
                config.SKILLS_DIR = orig_skills
                config.SKILLS_CACHE_FILE = orig_cache

    def test_events_emitted_when_force(self):
        """force=True で再処理時に進捗イベントが発生することを確認"""
        import knowledge_to_skills as k2s
        import config

        content = "\n".join(
            f"# Force章{i}\n\n{'強制再処理テスト。' * 20}\n"
            for i in range(1, 4)
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            src = os.path.join(tmpdir, "force_test.txt")
            with open(src, "w", encoding="utf-8") as f:
                f.write(content)

            orig_skills = config.SKILLS_DIR
            orig_cache = config.SKILLS_CACHE_FILE
            config.SKILLS_DIR = os.path.join(tmpdir, "skills")
            config.SKILLS_CACHE_FILE = os.path.join(tmpdir, ".cache.json")
            try:
                # 1回目: キャッシュ登録
                k2s._process_file(src, doc_name="force_test", use_cache=True)

                # 2回目: force=True → イベントが発生するはず
                events = []
                k2s._on_progress = lambda ev, **kw: events.append({"event": ev, **kw})
                try:
                    k2s._process_file(src, doc_name="force_test",
                                      use_cache=False, force=True)
                finally:
                    k2s._on_progress = None

                init_events = [e for e in events if e["event"] == "init"]
                chunk_events = [e for e in events if e["event"] == "chunk"]
                self.assertTrue(len(init_events) > 0, "force 時に init イベントが必要")
                self.assertTrue(len(chunk_events) > 0, "force 時に chunk イベントが必要")
            finally:
                config.SKILLS_DIR = orig_skills
                config.SKILLS_CACHE_FILE = orig_cache


if __name__ == "__main__":
    unittest.main(verbosity=2)
