"""
gui.py — ナレッジエージェント GUI
標準ライブラリ（tkinter）のみ。ダーク / ライトモード対応。
"""

from __future__ import annotations

import io
import os
import queue
import re
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  カラーパレット
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LIGHT: dict[str, str] = {
    "bg":        "#F8FAFC",
    "surface":   "#FFFFFF",
    "input":     "#FFFFFF",
    "border":    "#E2E8F0",
    "text":      "#0F172A",
    "muted":     "#64748B",
    "inv":       "#FFFFFF",
    "primary":   "#3B82F6",
    "primary_h": "#2563EB",
    "danger":    "#EF4444",
    "danger_h":  "#DC2626",
    "ghost_h":   "#E2E8F0",
    "sel_bg":    "#DBEAFE",
    "sel_fg":    "#1D4ED8",
    "log_bg":    "#1E1E2E",
    "log_fg":    "#CDD6F4",
    "c_turn":    "#89B4FA",
    "c_tool":    "#F9E2AF",
    "c_answer":  "#A6E3A1",
    "c_err":     "#F38BA8",
    "c_ok":      "#A6E3A1",
    "c_thinking":    "#CBA6F7",
    "c_tool_args":   "#94E2D5",
    "c_tool_result": "#9399B2",
}

DARK: dict[str, str] = {
    "bg":        "#0F172A",
    "surface":   "#1E293B",
    "input":     "#1E293B",
    "border":    "#334155",
    "text":      "#F1F5F9",
    "muted":     "#94A3B8",
    "inv":       "#FFFFFF",
    "primary":   "#3B82F6",
    "primary_h": "#60A5FA",
    "danger":    "#EF4444",
    "danger_h":  "#F87171",
    "ghost_h":   "#334155",
    "sel_bg":    "#1E3A5F",
    "sel_fg":    "#93C5FD",
    "log_bg":    "#0D1117",
    "log_fg":    "#C9D1D9",
    "c_turn":    "#79C0FF",
    "c_tool":    "#FFD700",
    "c_answer":  "#7EE787",
    "c_err":     "#FF7B72",
    "c_ok":      "#7EE787",
    "c_thinking":    "#D2A8FF",
    "c_tool_args":   "#7EE8CF",
    "c_tool_result": "#8B949E",
}

C: dict[str, str] = dict(LIGHT)
_is_dark = False

FONT       = ("Yu Gothic UI", 10)
FONT_SM    = ("Yu Gothic UI", 9)
FONT_MONO  = ("Consolas", 9)
FONT_TITLE = ("Yu Gothic UI", 11, "bold")
FONT_SECT  = ("Yu Gothic UI", 8, "bold")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  テーマエンジン
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_TM: list[tuple[tk.Widget, dict[str, str]]] = []   # (widget, {config_attr: C_key})
_TM_OBJ: list = []                                  # apply_theme() を持つカスタムオブジェクト
_STYLE: list[ttk.Style | None] = [None]
_TOGGLE_BTN: list[tk.Widget | None] = [None]


def _tag(w: tk.Widget, **roles: str) -> tk.Widget:
    """ウィジェットにカラーロールを登録してそのまま返す。"""
    _TM.append((w, roles))
    return w


def _obj(o):
    """apply_theme() を持つオブジェクトを登録してそのまま返す。"""
    _TM_OBJ.append(o)
    return o


def _apply_style(s: ttk.Style) -> None:
    s.theme_use("clam")
    s.configure(".",
        background=C["bg"], foreground=C["text"],
        font=FONT, borderwidth=0, relief="flat")
    s.configure("TFrame",    background=C["bg"])
    s.configure("TLabel",    background=C["bg"],  foreground=C["text"])
    s.configure("Muted.TLabel",  background=C["bg"],  foreground=C["muted"], font=FONT_SM)
    s.configure("Surf.TLabel",   background=C["surface"], foreground=C["text"])
    s.configure("Sect.TLabel",
        background=C["bg"], foreground=C["muted"], font=FONT_SECT)
    s.configure("TNotebook",   background=C["bg"], borderwidth=0, tabmargins=0)
    s.configure("TNotebook.Tab",
        background=C["bg"], foreground=C["muted"],
        font=("Yu Gothic UI", 10), padding=[18, 9], borderwidth=0)
    s.map("TNotebook.Tab",
        background=[("selected", C["surface"]), ("active", C["surface"])],
        foreground=[("selected", C["primary"]), ("active", C["text"])],
    )
    s.configure("TEntry",
        fieldbackground=C["input"], foreground=C["text"],
        bordercolor=C["border"], insertcolor=C["text"],
        lightcolor=C["border"], darkcolor=C["border"], padding=6)
    s.map("TEntry",
        bordercolor=[("focus", C["primary"])],
        lightcolor=[("focus", C["primary"])],
        darkcolor=[("focus", C["primary"])],
    )
    s.configure("TCheckbutton",
        background=C["surface"], foreground=C["text"], focuscolor="")
    s.map("TCheckbutton", background=[("active", C["surface"])])
    s.configure("TScrollbar",
        background=C["border"], troughcolor=C["bg"],
        borderwidth=0, arrowsize=11, width=8)
    s.map("TScrollbar", background=[("active", C["muted"])])
    s.configure("TSeparator", background=C["border"])
    # Treeview（ナレッジ管理用）
    s.configure("Mgr.Treeview",
        background=C["surface"], foreground=C["text"],
        fieldbackground=C["surface"], rowheight=26,
        font=FONT, borderwidth=0)
    s.configure("Mgr.Treeview.Heading",
        background=C["bg"], foreground=C["muted"],
        font=FONT_SECT, relief="flat", borderwidth=0)
    s.map("Mgr.Treeview",
        background=[("selected", C["sel_bg"])],
        foreground=[("selected", C["sel_fg"])],
    )


def _refresh_all() -> None:
    """現在の C を全ウィジェットに適用する。"""
    if _STYLE[0]:
        _apply_style(_STYLE[0])
    for w, roles in _TM:
        try:
            w.configure(**{a: C[k] for a, k in roles.items()})
        except Exception:
            pass
    for obj in _TM_OBJ:
        try:
            obj.apply_theme()
        except Exception:
            pass


def toggle_theme() -> None:
    global _is_dark
    _is_dark = not _is_dark
    C.update(DARK if _is_dark else LIGHT)
    _refresh_all()
    if _TOGGLE_BTN[0]:
        _TOGGLE_BTN[0].configure(
            text=("☀  ライト" if _is_dark else "☾  ダーク"),
            bg=C["primary"], fg=C["inv"],
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ウィジェットヘルパー
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _fr(parent, bg="bg", **kw) -> tk.Frame:
    return _tag(tk.Frame(parent, bg=C[bg], **kw), bg=bg)


def _lb(parent, text="", fg="text", bg="bg", font=FONT, **kw) -> tk.Label:
    return _tag(tk.Label(parent, text=text, bg=C[bg], fg=C[fg], font=font, **kw), bg=bg, fg=fg)


def _sect(parent, text: str) -> tk.Label:
    """セクションヘッダーラベル（小文字太字・ミュートカラー）。"""
    return _lb(parent, text=text, fg="muted", bg="bg", font=FONT_SECT, anchor="w")


def _input_frame(parent) -> tuple[tk.Frame, tk.Frame]:
    """
    入力エリア用のボーダー付きフレームを返す。
    border_frame, content_frame のタプル。
    content_frame に子ウィジェットを詰める。
    """
    outer = _fr(parent, bg="border")
    inner = _fr(outer,  bg="input")
    inner.pack(fill="both", expand=True, padx=1, pady=1)
    return outer, inner


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  カスタムボタン
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_BTN_ROLES = {
    "primary": ("primary",  "primary_h", "inv"),
    "danger":  ("danger",   "danger_h",  "inv"),
    "neutral": ("border",   "ghost_h",   "muted"),
}


class _Btn(tk.Label):
    """フラットボタン（primary / danger / neutral）。"""

    def __init__(self, parent, text, cmd, role="primary", px=14, py=7, **kw):
        self._role = role
        self._disabled = False
        bg_k, _, fg_k = self._palette()
        super().__init__(
            parent, text=text, bg=C[bg_k], fg=C[fg_k],
            font=FONT, padx=px, pady=py, cursor="hand2", **kw)
        self.bind("<Button-1>", self._click)
        self.bind("<Enter>",    self._enter)
        self.bind("<Leave>",    self._leave)
        _obj(self)

    def _palette(self):
        return _BTN_ROLES[self._role]  # (bg_key, bg_h_key, fg_key)

    def _click(self, _e):
        if not self._disabled and hasattr(self, "_cmd"):
            self._cmd()

    def _enter(self, _e):
        if not self._disabled:
            self.configure(bg=C[self._palette()[1]])

    def _leave(self, _e):
        if not self._disabled:
            self.configure(bg=C[self._palette()[0]])

    def set_cmd(self, cmd):
        self._cmd = cmd
        return self

    def enable(self, on: bool):
        self._disabled = not on
        if on:
            self.configure(bg=C[self._palette()[0]], fg=C[self._palette()[2]],
                           cursor="hand2")
        else:
            self.configure(bg=C["border"], fg=C["muted"], cursor="")

    def apply_theme(self):
        if self._disabled:
            self.configure(bg=C["border"], fg=C["muted"])
        else:
            bg_k, _, fg_k = self._palette()
            self.configure(bg=C[bg_k], fg=C[fg_k])


class _Ghost(tk.Label):
    """テキストのみのサブアクションボタン（ホバーで背景）。"""

    def __init__(self, parent, text, cmd, **kw):
        self._cmd = cmd
        super().__init__(
            parent, text=text, bg=C["bg"], fg=C["muted"],
            font=FONT_SM, padx=10, pady=5, cursor="hand2", **kw)
        self.bind("<Button-1>", lambda _e: self._cmd())
        self.bind("<Enter>",    lambda _e: self.configure(bg=C["ghost_h"], fg=C["text"]))
        self.bind("<Leave>",    lambda _e: self.configure(bg=C["bg"],     fg=C["muted"]))
        _tag(self, bg="bg", fg="muted")

    def apply_theme(self):
        self.configure(bg=C["bg"], fg=C["muted"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ログパネル（常時ダーク端末）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class _Log(tk.Frame):
    # tag_name → C パレットキー のマッピング
    _TAG_COLOR_KEYS: dict[str, str] = {
        "turn": "c_turn", "tool": "c_tool",
        "answer": "c_answer", "err": "c_err", "ok": "c_ok",
        "thinking": "c_thinking",
        "call_tool": "c_tool_args",
    }

    def __init__(self, parent, **tag_colors: str):
        super().__init__(parent, bg=C["log_bg"])
        _tag(self, bg="log_bg")
        self._tag_names = list(tag_colors.keys())
        self._txt = tk.Text(
            self, state="disabled", wrap="word",
            font=FONT_MONO, bg=C["log_bg"], fg=C["log_fg"],
            insertbackground=C["log_fg"], selectbackground="#334155",
            borderwidth=0, relief="flat", padx=10, pady=8)
        sb = ttk.Scrollbar(self, orient="vertical", command=self._txt.yview)
        self._txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._txt.pack(side="left", fill="both", expand=True)
        for name, color in tag_colors.items():
            self._txt.tag_config(name, foreground=color)
        _obj(self)

    def append(self, text: str, tag: str | None = None):
        self._txt.configure(state="normal")
        self._txt.insert("end", text, (tag,) if tag else ())
        self._txt.see("end")
        self._txt.configure(state="disabled")

    def clear(self):
        self._txt.configure(state="normal")
        self._txt.delete("1.0", "end")
        self._txt.configure(state="disabled")

    def apply_theme(self):
        self.configure(bg=C["log_bg"])
        self._txt.configure(bg=C["log_bg"], fg=C["log_fg"])
        for name in self._tag_names:
            c_key = self._TAG_COLOR_KEYS.get(name)
            if c_key and c_key in C:
                self._txt.tag_config(name, foreground=C[c_key])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ストリームリダイレクト
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class _Writer(io.TextIOBase):
    """stdout/stderr をキューへ転送しつつ、元のストリームにもエコーする。"""
    def __init__(self, q: queue.Queue, tag: str = "",
                 echo: "io.TextIOBase | None" = None):
        self._q, self._tag, self._echo = q, tag, echo
    def write(self, t: str) -> int:
        if t:
            self._q.put((self._tag, t))
            if self._echo:
                try:
                    self._echo.write(t)
                    self._echo.flush()
                except Exception:
                    pass
        return len(t)
    def flush(self):
        if self._echo:
            try:
                self._echo.flush()
            except Exception:
                pass


class _StderrRouter(io.TextIOBase):
    """agent.py の stderr をタグ付きでキューへ振り分ける。

    [thinking], [tool_args], [tool_result] は複数行にまたがるため、
    プレフィックスで開始されたタグを次のプレフィックスが来るまで維持する。
    """

    # (prefix, tag, multi-line?) — 順序は優先度順
    _RULES = (
        ("[thinking]",   "thinking",  True),
        ("[call Tool ",  "call_tool", False),
        ("[turn",        "turn",      False),
        ("[compaction]", "turn",      False),
    )

    def __init__(self, q: queue.Queue):
        self._q = q
        self._buf = ""
        self._multi_tag = ""   # 複数行タグの継続用

    def write(self, t: str) -> int:
        self._buf += t
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            line += "\n"
            stripped = line.strip()

            # ルールにマッチするかチェック
            matched = False
            for prefix, tag, multi in self._RULES:
                if stripped.startswith(prefix):
                    self._multi_tag = tag if multi else ""
                    self._q.put((tag, line))
                    matched = True
                    break

            if not matched:
                if stripped.startswith("["):
                    # 新しいプレフィックスが来たら複数行モードを終了
                    self._multi_tag = ""
                    self._q.put(("tool", line))
                elif self._multi_tag:
                    # 複数行タグの継続中
                    self._q.put((self._multi_tag, line))
                else:
                    self._q.put(("", line))
        return len(t)

    def flush(self):
        pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  タブ1 — ナレッジ取り込み
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class KnowledgeTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self._path = ""
        self._running = False
        self._q: queue.Queue = queue.Queue()
        self._manager: KnowledgeManagerTab | None = None
        _tag(self, background="bg")
        self._build()
        self._poll()

    def _build(self):
        P = dict(padx=20, pady=0)

        # ── 入力 ──
        _sect(self, "入力ファイル / ディレクトリ").pack(
            fill="x", padx=20, pady=(16, 6))

        btn_row = _fr(self)
        btn_row.pack(fill="x", **P)
        _Btn(btn_row, "ファイルを選択…", self._pick_file, px=12, py=6
             ).set_cmd(self._pick_file).pack(side="left", padx=(0, 8))
        _Btn(btn_row, "フォルダを選択…", self._pick_dir, role="neutral", px=12, py=6
             ).set_cmd(self._pick_dir).pack(side="left")

        self._path_var = tk.StringVar(value="未選択")
        path_row = _fr(self)
        path_row.pack(fill="x", padx=20, pady=(6, 0))
        _tag(tk.Label(
            path_row, textvariable=self._path_var,
            bg=C["bg"], fg=C["muted"],
            font=FONT_MONO, anchor="w", wraplength=600,
        ).pack(fill="x"), bg="bg", fg="muted")

        ttk.Separator(self, orient="horizontal").pack(
            fill="x", padx=20, pady=14)

        # ── オプション ──
        _sect(self, "オプション").pack(fill="x", padx=20, pady=(0, 8))

        opt = _fr(self)
        opt.pack(fill="x", **P)
        _lb(opt, "スキル名（省略可）", fg="muted", font=FONT_SM).pack(side="left")

        self._name_var = tk.StringVar()
        ttk.Entry(opt, textvariable=self._name_var, width=22).pack(
            side="left", padx=(8, 24))

        self._llm_var = tk.BooleanVar()
        cb = ttk.Checkbutton(
            opt, text="LLM で構造化（Ollama 必要）", variable=self._llm_var)
        cb.pack(side="left")

        ttk.Separator(self, orient="horizontal").pack(
            fill="x", padx=20, pady=14)

        # ── アクション ──
        act = _fr(self)
        act.pack(fill="x", **P)
        self._run_btn = _Btn(act, "▶  取り込み実行", None, px=18, py=8)
        self._run_btn.set_cmd(self._run)
        self._run_btn.pack(side="left")
        _Ghost(act, "ログをクリア", self._log_clear).pack(side="left", padx=(10, 0))

        # ── ログ ──
        _sect(self, "ログ").pack(fill="x", padx=20, pady=(16, 6))
        self._log = _Log(self,
            err=C["c_err"], ok=C["c_ok"])
        self._log.pack(fill="both", expand=True, padx=20, pady=(0, 16))

    # ── ファイル選択 ──

    def _pick_file(self):
        p = filedialog.askopenfilename(
            title="取り込むファイルを選択",
            filetypes=[
                ("対応ファイル",
                 "*.pdf *.md *.txt *.html *.htm *.rst "
                 "*.docx *.xlsx *.xls *.csv *.tsv "
                 "*.py *.js *.ts *.c *.cpp *.h *.java *.go"),
                ("すべて", "*.*"),
            ])
        if p:
            self._path = p
            self._path_var.set(p)

    def _pick_dir(self):
        p = filedialog.askdirectory(title="取り込むフォルダを選択")
        if p:
            self._path = p
            self._path_var.set(p)

    # ── 実行 ──

    def _run(self):
        if self._running: return
        if not self._path:
            messagebox.showwarning("未選択", "ファイルまたはフォルダを選択してください。")
            return
        self._running = True
        self._run_btn.enable(False)
        self._log.append(f"=== 開始: {self._path} ===\n", "ok")
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self):
        import knowledge_to_skills as k2s
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = _Writer(self._q)
        sys.stderr = _Writer(self._q, "err")
        try:
            p = self._path
            name = self._name_var.get().strip() or None
            if os.path.isdir(p):
                for f in k2s._collect_files(p):
                    k2s._process_file(f, doc_name=None)
            else:
                k2s._process_file(p, doc_name=name)
            self._q.put(("ok", "=== 完了 ===\n"))
        except Exception as e:
            self._q.put(("err", f"[error] {e}\n"))
        finally:
            sys.stdout, sys.stderr = old_out, old_err
            self._q.put(("__done__", ""))

    def _poll(self):
        try:
            while True:
                tag, text = self._q.get_nowait()
                if tag == "__done__":
                    self._running = False
                    self._run_btn.enable(True)
                    if self._manager:
                        self._manager.refresh()
                else:
                    self._log.append(text, tag or None)
        except queue.Empty:
            pass
        self.after(80, self._poll)

    def _log_clear(self):
        self._log.clear()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  タブ2 — ナレッジ管理
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# ── 進捗状態を保持するデータクラス（tkinter不要・テスト可能） ──
# NOTE: IngestBarState / apply_progress_event / apply_progress_line は
#       test_progress.py から参照されるため、クラス・関数としては残す。
#       GUI側の進捗表示はログ欄（ターミナル出力のエコー）に一本化された。

class IngestBarState:
    """進捗バーの論理状態。tkinter非依存でテスト可能。"""
    __slots__ = (
        "prog_ch_mode", "prog_ch_max", "prog_ch_val", "prog_ch_txt",
        "prog_tk_mode", "prog_tk_max", "prog_tk_val", "prog_tk_txt",
        "hier_txt", "bars_initialized",
    )

    def __init__(self):
        self.prog_ch_mode = "indeterminate"
        self.prog_ch_max  = 100
        self.prog_ch_val  = 0
        self.prog_ch_txt  = "読み込み中..."
        self.prog_tk_mode = "indeterminate"
        self.prog_tk_max  = 100
        self.prog_tk_val  = 0
        self.prog_tk_txt  = "計算中..."
        self.hier_txt     = "読み込み中..."
        self.bars_initialized = False


_RE_INGEST_INIT  = re.compile(r"(?:階層並列処理|セクション処理): (\d+)章.*予算([\d,]+)トークン")
_RE_INGEST_CH    = re.compile(r"\[(\d+)/(\d+)\].*累計([\d,]+)")
_RE_INGEST_LIMIT = re.compile(r"トークン予算超過")
_RE_INGEST_STEP  = re.compile(r"\[(\d)/4\]")
_RE_INGEST_PDF   = re.compile(r"PDF変換:.*\((\d+)/(\d+)チャンク\)")
_INGEST_STEP_LABEL = {1: "読み込み中...", 2: "分割中...", 3: "構造化中...", 4: "書き出し中..."}


def apply_progress_event(state: "IngestBarState", event: dict) -> None:
    """
    __progress__ イベント辞書を受け取り、IngestBarState を更新する。
    tkinter に依存しないため単体テスト可能。
    """
    ev = event.get("event", "")
    if ev == "init":
        ch_n = int(event.get("ch_n", 1))
        tk_n = int(event.get("tk_n", 1))
        state.prog_ch_mode = "determinate"
        state.prog_ch_max  = max(ch_n, 1)
        state.prog_ch_val  = 0
        state.prog_ch_txt  = f"0% (0/{ch_n})"
        state.prog_tk_mode = "determinate"
        state.prog_tk_max  = max(tk_n, 1)
        state.prog_tk_val  = 0
        state.prog_tk_txt  = f"0/{tk_n:,} トークン"
        state.hier_txt     = "処理開始..."
        state.bars_initialized = True

    elif ev == "chunk":
        ch_i   = int(event.get("ch_i", 0))
        ch_n   = int(event.get("ch_n", 1))
        tk_cum = int(event.get("tk_cum", 0))
        if not state.bars_initialized:
            state.prog_ch_mode = "determinate"
            state.prog_ch_max  = max(ch_n, 1)
            state.bars_initialized = True
        pct = ch_i * 100 // max(ch_n, 1)
        state.prog_ch_val = ch_i
        state.prog_ch_txt = f"{pct}% ({ch_i}/{ch_n})"
        if state.prog_tk_mode == "determinate":
            tk_max = state.prog_tk_max
            state.prog_tk_val = min(tk_cum, tk_max)
            state.prog_tk_txt = f"{tk_cum:,}/{tk_max:,} トークン"
        else:
            state.prog_tk_txt = f"{tk_cum:,}/-- トークン"
        level = event.get("level", "")
        title = event.get("title", "")
        if level and title:
            state.hier_txt = f"Lv{level}: {title}"
        elif title:
            state.hier_txt = str(title)


def apply_progress_line(state: "IngestBarState", line: str) -> None:
    """
    stderr テキスト1行を受け取り、IngestBarState を更新する。
    tkinter に依存しないため単体テスト可能。
    """
    line = line.strip()
    if not line:
        return

    m = _RE_INGEST_INIT.search(line)
    if m:
        ch_n = int(m.group(1))
        tk_n = int(m.group(2).replace(",", ""))
        state.prog_ch_mode = "determinate"
        state.prog_ch_max  = max(ch_n, 1)
        state.prog_ch_val  = 0
        state.prog_ch_txt  = f"0% (0/{ch_n})"
        state.prog_tk_mode = "determinate"
        state.prog_tk_max  = max(tk_n, 1)
        state.prog_tk_val  = 0
        state.prog_tk_txt  = f"0/{tk_n:,} トークン"
        state.hier_txt     = "処理開始..."
        state.bars_initialized = True
        return

    m = _RE_INGEST_CH.search(line)
    if m:
        ch_i   = int(m.group(1))
        ch_n   = int(m.group(2))
        tk_cum = int(m.group(3).replace(",", ""))
        if not state.bars_initialized:
            state.prog_ch_mode = "determinate"
            state.prog_ch_max  = max(ch_n, 1)
            state.bars_initialized = True
        pct = ch_i * 100 // max(ch_n, 1)
        state.prog_ch_val = ch_i
        state.prog_ch_txt = f"{pct}% ({ch_i}/{ch_n})"
        if state.prog_tk_mode == "determinate":
            tk_max = state.prog_tk_max
            state.prog_tk_val = min(tk_cum, tk_max)
            state.prog_tk_txt = f"{tk_cum:,}/{tk_max:,} トークン"
        else:
            state.prog_tk_txt = f"{tk_cum:,}/... トークン"
        state.hier_txt = line[:80]
        return

    if _RE_INGEST_LIMIT.search(line):
        state.prog_tk_val = state.prog_tk_max
        state.prog_tk_txt = f"{state.prog_tk_max:,}/{state.prog_tk_max:,} トークン"
        return

    mp = _RE_INGEST_PDF.search(line)
    if mp and not state.bars_initialized:
        c_i = int(mp.group(1))
        c_n = int(mp.group(2))
        pct = c_i * 100 // max(c_n, 1)
        state.prog_ch_txt = f"{pct}% ({c_i}/{c_n} チャンク)"
        state.prog_tk_txt = "読み込み中..."
        state.hier_txt    = "PDF変換中..."
        return

    ms = _RE_INGEST_STEP.search(line)
    if ms and not state.bars_initialized:
        step  = int(ms.group(1))
        label = _INGEST_STEP_LABEL.get(step, "処理中...")
        state.prog_ch_txt = label
        state.prog_tk_txt = label
        state.hier_txt    = label

class KnowledgeManagerTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self._ingest_running = False
        self._ingest_q: queue.Queue = queue.Queue()
        _tag(self, background="bg")
        self._build()
        self.after(100, self.refresh)
        self._ingest_poll()

    def _build(self):
        # ━━ 取り込みパネル ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

        _sect(self, "取り込み").pack(fill="x", padx=20, pady=(16, 6))

        ing_row = _fr(self)
        ing_row.pack(fill="x", padx=20)

        self._ing_run_btn = _Btn(ing_row, "▶  実行", None, px=12, py=6)
        self._ing_run_btn.set_cmd(self._ingest_run)
        self._ing_run_btn.pack(side="right")

        _Btn(ing_row, "ファイル…", self._ingest_pick_file,
             px=10, py=6).set_cmd(self._ingest_pick_file).pack(side="left", padx=(0, 6))
        _Btn(ing_row, "フォルダ…", self._ingest_pick_dir, role="neutral",
             px=10, py=6).set_cmd(self._ingest_pick_dir).pack(side="left", padx=(0, 12))

        _lb(ing_row, "スキル名", fg="muted", font=FONT_SM).pack(side="left")
        self._ing_name = tk.StringVar()
        ttk.Entry(ing_row, textvariable=self._ing_name, width=16).pack(
            side="left", padx=(6, 12))

        self._ing_llm = tk.BooleanVar()
        ttk.Checkbutton(ing_row, text="LLM", variable=self._ing_llm).pack(side="left")

        self._ing_force = tk.BooleanVar(value=True)
        ttk.Checkbutton(ing_row, text="再処理", variable=self._ing_force).pack(side="left", padx=(6, 0))

        # 2行目: トークン上限
        ing_row2 = _fr(self)
        ing_row2.pack(fill="x", padx=20, pady=(4, 0))
        _lb(ing_row2, "トークン上限", fg="muted", font=FONT_SM).pack(side="left")
        from config import KNOWLEDGE_MAX_TOKENS as _default_mt
        self._ing_max_tokens = tk.StringVar(
            value=f"{_default_mt:,}" if _default_mt else "0")
        ttk.Entry(ing_row2, textvariable=self._ing_max_tokens, width=10).pack(
            side="left", padx=(6, 4))
        _lb(ing_row2, "(0 = 無制限)", fg="muted", font=FONT_SM).pack(side="left")

        # 選択パス（1行）
        self._ing_path = ""
        self._ing_status = tk.StringVar(value="ファイルまたはフォルダを選択してください")
        status_lbl = _tag(
            tk.Label(self, textvariable=self._ing_status,
                     bg=C["bg"], fg=C["muted"],
                     font=FONT_MONO, anchor="w"),
            bg="bg", fg="muted")
        status_lbl.pack(fill="x", padx=20, pady=(4, 0))

        # ── ログ出力欄（ターミナル出力をそのまま表示） ──
        log_frame = _fr(self, bg="border")
        log_frame.pack(fill="x", padx=20, pady=(4, 0))
        log_inner = _fr(log_frame, bg="surface")
        log_inner.pack(fill="both", expand=False, padx=1, pady=1)

        self._ing_log = tk.Text(
            log_inner, height=8, wrap="word",
            bg=C["surface"], fg=C["text"], font=FONT_MONO,
            relief="flat", borderwidth=0,
            state="disabled",            # 読み取り専用
            insertwidth=0,
        )
        _scrollbar = ttk.Scrollbar(log_inner, orient="vertical",
                                   command=self._ing_log.yview)
        self._ing_log.configure(yscrollcommand=_scrollbar.set)
        self._ing_log.pack(side="left", fill="both", expand=True)
        _scrollbar.pack(side="right", fill="y")

        # タグ設定（stderr は赤系で表示）
        self._ing_log.tag_configure("err", foreground="#e06060")

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=20, pady=12)

        # ━━ 一覧ツールバー ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

        bar = _fr(self)
        bar.pack(fill="x", padx=20, pady=(0, 8))

        _sect(bar, "ナレッジ一覧").pack(side="left")
        self._del_btn = _Btn(bar, "選択を削除", None, role="danger", px=12, py=6)
        self._del_btn.set_cmd(self._delete)
        self._del_btn.pack(side="right")
        _Ghost(bar, "更新",   self.refresh).pack(side="right", padx=(0, 4))
        _Ghost(bar, "全解除", self._desel ).pack(side="right", padx=(0, 2))
        _Ghost(bar, "全選択", self._selall).pack(side="right")

        # ── Treeview ──
        tree_wrap = _fr(self, bg="border")
        tree_wrap.pack(fill="both", expand=True, padx=20, pady=(0, 0))

        inner = _fr(tree_wrap, bg="surface")
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        cols = ("files", "size", "coverage", "source")
        self._tree = ttk.Treeview(
            inner, columns=cols, selectmode="extended",
            style="Mgr.Treeview", show="headings tree")
        self._tree.heading("#0",       text="ナレッジ名",   anchor="w")
        self._tree.heading("files",    text="ファイル数",   anchor="center")
        self._tree.heading("size",     text="サイズ",       anchor="e")
        self._tree.heading("coverage", text="カバレッジ",   anchor="center")
        self._tree.heading("source",   text="取り込み元",   anchor="w")
        self._tree.column("#0",       width=200, minwidth=120, stretch=True)
        self._tree.column("files",    width=80,  minwidth=60,  stretch=False, anchor="center")
        self._tree.column("size",     width=90,  minwidth=70,  stretch=False, anchor="e")
        self._tree.column("coverage", width=100, minwidth=80,  stretch=False, anchor="center")
        self._tree.column("source",   width=300, minwidth=100, stretch=True)

        vsb = ttk.Scrollbar(inner, orient="vertical",   command=self._tree.yview)
        hsb = ttk.Scrollbar(inner, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        inner.grid_rowconfigure(0, weight=1)
        inner.grid_columnconfigure(0, weight=1)
        self._tree.bind("<<TreeviewSelect>>", self._on_sel)

        # ── ステータス ──
        self._status = tk.StringVar(value="")
        _tag(tk.Label(self, textvariable=self._status,
                      bg=C["bg"], fg=C["muted"], font=FONT_SM, anchor="w"
                      ).pack(fill="x", padx=20, pady=(6, 14)),
             bg="bg", fg="muted")

    # ── 取り込み ──

    def _ingest_pick_file(self):
        p = filedialog.askopenfilename(
            title="取り込むファイルを選択",
            filetypes=[
                ("対応ファイル",
                 "*.pdf *.md *.txt *.html *.htm *.rst "
                 "*.docx *.xlsx *.xls *.csv *.tsv "
                 "*.py *.js *.ts *.c *.cpp *.h *.java *.go"),
                ("すべて", "*.*"),
            ])
        if p:
            self._ing_path = p
            self._ing_status.set(p)

    def _ingest_pick_dir(self):
        p = filedialog.askdirectory(title="取り込むフォルダを選択")
        if p:
            self._ing_path = p
            self._ing_status.set(p)

    def _ingest_run(self):
        if self._ingest_running:
            return
        if not self._ing_path:
            messagebox.showwarning("未選択", "ファイルまたはフォルダを選択してください。")
            return
        self._ingest_running = True
        self._ing_run_btn.enable(False)
        # ログ欄をクリア
        self._ing_log.configure(state="normal")
        self._ing_log.delete("1.0", "end")
        self._ing_log.configure(state="disabled")
        self._ing_status.set("処理中...")
        # メインスレッドで tkinter 変数を読み取り（スレッド安全性）
        args = {
            "path": self._ing_path,
            "name": self._ing_name.get().strip() or None,
        }
        threading.Thread(target=self._ingest_work, args=(args,), daemon=True).start()

    def _ingest_work(self, args: dict):
        old_out, old_err = sys.stdout, sys.stderr
        try:
            import knowledge_to_skills as k2s
        except Exception as e:
            old_err.write(f"[ingest] インポートエラー: {e}\n")
            self._ingest_q.put(("err", f"インポートエラー: {e}\n"))
            self._ingest_q.put(("__done__", ""))
            return
        # stdout/stderr をキュー転送しつつターミナルにもエコー
        sys.stdout = _Writer(self._ingest_q, "",    echo=old_out)
        sys.stderr = _Writer(self._ingest_q, "err", echo=old_err)
        k2s._on_progress = None   # GUI専用コールバックは使わない
        try:
            p    = args["path"]
            name = args["name"]
            print(f"[ingest] path={p}", file=sys.stderr)
            if os.path.isdir(p):
                for f in k2s._collect_files(p):
                    k2s._process_file(f, doc_name=None)
            else:
                k2s._process_file(p, doc_name=name)
        except Exception as e:
            import traceback
            traceback.print_exc()  # stderr 経由でキュー＋ターミナル
        finally:
            k2s._on_progress = None
            sys.stdout, sys.stderr = old_out, old_err
            self._ingest_q.put(("__done__", ""))

    def _log_append(self, text: str, tag: str = ""):
        """ログ欄にテキストを追記し、末尾にスクロールする。

        \\r で始まるテキストは最終行を上書きする（ターミナルの動作を再現）。
        """
        self._ing_log.configure(state="normal")
        # \r 処理: 最終行を上書き
        if "\r" in text:
            # 最後の \r 以降だけを表示（上書き動作）
            parts = text.rsplit("\r", 1)
            content = parts[-1]
            if content:
                # 現在の最終行を削除して置き換え
                self._ing_log.delete("end-1c linestart", "end-1c")
                if tag:
                    self._ing_log.insert("end", content, tag)
                else:
                    self._ing_log.insert("end", content)
        else:
            if tag:
                self._ing_log.insert("end", text, tag)
            else:
                self._ing_log.insert("end", text)
        self._ing_log.see("end")
        self._ing_log.configure(state="disabled")

    def _ingest_poll(self):
        try:
            while True:
                tag, text = self._ingest_q.get_nowait()

                if tag == "__done__":
                    self._ingest_running = False
                    self._ing_run_btn.enable(True)
                    self._log_append("--- 完了 ---\n")
                    self._ing_status.set("完了")
                    self.refresh()
                    continue

                # stdout / stderr テキストをログ欄に追記
                if text:
                    self._log_append(text, tag)

        except queue.Empty:
            pass
        except Exception as e:
            import traceback
            print(f"[ingest:poll] 例外: {e}", file=sys.__stderr__)
            traceback.print_exc(file=sys.__stderr__)
            self._ing_status.set(f"[進捗エラー] {e}")
        finally:
            self.after(100, self._ingest_poll)

    # ── データ ──

    def refresh(self):
        import json as _json
        from config import SKILLS_DIR, SKILLS_INDEX
        for item in self._tree.get_children():
            self._tree.delete(item)
        skills_abs = os.path.abspath(SKILLS_DIR)
        if not os.path.isdir(skills_abs):
            self._status.set("0 件")
            return
        sources = _parse_index_sources(SKILLS_INDEX) \
            if os.path.isfile(SKILLS_INDEX) else {}
        rows = []
        for name in sorted(os.listdir(skills_abs)):
            d = os.path.join(skills_abs, name)
            if not os.path.isdir(d): continue
            mds   = [f for f in os.listdir(d) if f.endswith(".md")]
            total = sum(os.path.getsize(os.path.join(d, f)) for f in mds)
            # カバレッジ情報
            coverage_text = "\u2014"
            cov_path = os.path.join(d, ".coverage.json")
            if os.path.isfile(cov_path):
                try:
                    with open(cov_path, encoding="utf-8") as _f:
                        cov = _json.load(_f)
                    if cov.get("partial"):
                        tp = cov.get("total_pages", 0)
                        pp = cov.get("processed_pages", [])
                        if pp and tp:
                            p_count = pp[0][1] - pp[0][0] + 1
                            pct = p_count * 100 // tp
                            coverage_text = f"{pct}% ({pp[0][1]}/{tp}p)"
                    else:
                        coverage_text = "100%"
                except (ValueError, OSError, KeyError):
                    pass
            rows.append((name, len(mds), total, coverage_text, sources.get(name, "")))
        for name, nf, nb, cov_text, src in rows:
            self._tree.insert("", "end", iid=name,
                text=f"  {name}",
                values=(nf, _fmt_size(nb), cov_text, src))
        self._set_status(len(rows), 0)

    # ── 選択操作 ──

    def _on_sel(self, _e=None):
        self._set_status(len(self._tree.get_children()),
                         len(self._tree.selection()))

    def _selall(self):
        self._tree.selection_set(self._tree.get_children())

    def _desel(self):
        self._tree.selection_remove(self._tree.selection())

    def _set_status(self, total, sel):
        self._status.set(
            f"{total} 件  ／  選択中: {sel} 件" if sel else f"{total} 件")

    # ── 削除 ──

    def _delete(self):
        import shutil
        from config import SKILLS_DIR, SKILLS_INDEX
        sel = list(self._tree.selection())
        if not sel:
            messagebox.showinfo("未選択", "削除するナレッジを選択してください。")
            return
        names = "\n".join(f"  • {s}" for s in sel)
        if not messagebox.askyesno("削除の確認",
                f"以下を削除します（元に戻せません）。\n\n{names}\n\n続けますか？",
                icon="warning"):
            return
        errors = []
        for name in sel:
            d = os.path.join(os.path.abspath(SKILLS_DIR), name)
            try:
                if os.path.isdir(d): shutil.rmtree(d)
            except Exception as e:
                errors.append(f"{name}: {e}")
        if os.path.isfile(SKILLS_INDEX):
            try:
                _remove_from_index(SKILLS_INDEX, sel)
            except Exception as e:
                errors.append(f"index.md: {e}")
        if errors:
            messagebox.showerror("エラー", "\n".join(errors))
        self.refresh()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  タブ3 — エージェント
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class AgentTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self._running = False
        self._q: queue.Queue = queue.Queue()
        self._paths: list[tuple[str, str]] = []  # (path, "ro"|"rw")
        _tag(self, background="bg")
        self._build()
        self._poll()

    def _build(self):
        P = dict(padx=20, pady=0)

        # ── スコープ ──
        _sect(self, "作業スコープ  —  アクセスを許可するファイル / フォルダ").pack(
            fill="x", padx=20, pady=(16, 8))

        sc_bar = _fr(self)
        sc_bar.pack(fill="x", **P)
        _Btn(sc_bar, "ファイル（読）", None,
             px=12, py=6).set_cmd(lambda: self._add_file("ro")).pack(side="left", padx=(0, 4))
        _Btn(sc_bar, "ファイル（読書）", None, role="neutral",
             px=12, py=6).set_cmd(lambda: self._add_file("rw")).pack(side="left", padx=(0, 8))
        _Btn(sc_bar, "フォルダ（読）", None,
             px=12, py=6).set_cmd(lambda: self._add_dir("ro")).pack(side="left", padx=(0, 4))
        _Btn(sc_bar, "フォルダ（読書）", None, role="neutral",
             px=12, py=6).set_cmd(lambda: self._add_dir("rw")).pack(side="left")
        _Btn(sc_bar, "リセット", None, role="danger",
             px=12, py=6).set_cmd(self._clr_scope).pack(side="right")

        sc_box, sc_inner = _input_frame(self)
        sc_box.pack(fill="x", padx=20, pady=(8, 0))
        self._scope_lb = tk.Listbox(
            sc_inner, height=3, font=FONT_MONO,
            bg=C["input"], fg=C["text"],
            selectbackground=C["sel_bg"], selectforeground=C["sel_fg"],
            borderwidth=0, highlightthickness=0, activestyle="none",
            state="disabled")
        _tag(self._scope_lb, bg="input", fg="text",
             selectbackground="sel_bg", selectforeground="sel_fg")
        sb = ttk.Scrollbar(sc_inner, orient="vertical",
                           command=self._scope_lb.yview)
        self._scope_lb.configure(yscrollcommand=sb.set)
        self._scope_lb.pack(side="left", fill="x", expand=True)
        sb.pack(side="right", fill="y")

        _lb(self, "[R] 読み取り専用  [RW] 読み書き  |  skills/  と  project_memory.md  は常に許可",
            fg="muted", font=("Yu Gothic UI", 8)
            ).pack(anchor="w", padx=20, pady=(4, 0))

        ttk.Separator(self, orient="horizontal").pack(
            fill="x", padx=20, pady=14)

        # ── コンテキスト長設定 ──
        _sect(self, "コンテキスト長  —  モデルの最大トークン数に合わせて設定").pack(
            fill="x", padx=20, pady=(0, 8))

        ctx_bar = _fr(self)
        ctx_bar.pack(fill="x", padx=20)

        _tag(tk.Label(ctx_bar, text="コンテキスト長:", bg=C["bg"],
                      fg=C["text"], font=FONT_SM), bg="bg", fg="text"
             ).pack(side="left")

        from config import CONTEXT_LIMIT as _default_ctx
        self._ctx_var = tk.StringVar(value=str(_default_ctx))
        ctx_entry = tk.Entry(
            ctx_bar, textvariable=self._ctx_var, width=10,
            font=FONT_MONO, bg=C["input"], fg=C["text"],
            insertbackground=C["text"], relief="flat",
            borderwidth=1, highlightthickness=1)
        _tag(ctx_entry, bg="input", fg="text", insertbackground="text")
        ctx_entry.pack(side="left", padx=(8, 4))
        _tag(tk.Label(ctx_bar, text="tokens", bg=C["bg"],
                      fg=C["muted"], font=FONT_SM), bg="bg", fg="muted"
             ).pack(side="left")

        # プリセットボタン
        for label, val in [("4K", "4096"), ("8K", "8192"),
                           ("32K", "32768"), ("60K", "60000")]:
            _Ghost(ctx_bar, label,
                   lambda v=val: self._ctx_var.set(v)
                   ).pack(side="left", padx=(6, 0))

        ttk.Separator(self, orient="horizontal").pack(
            fill="x", padx=20, pady=14)

        # ── クエリ ──
        _sect(self, "質問 / 指示").pack(fill="x", padx=20, pady=(0, 8))

        q_box, q_inner = _input_frame(self)
        q_box.pack(fill="x", **P)
        self._query = tk.Text(
            q_inner, height=4, wrap="word", font=FONT,
            bg=C["input"], fg=C["text"], insertbackground=C["text"],
            selectbackground=C["sel_bg"], relief="flat",
            borderwidth=0, padx=8, pady=8)
        _tag(self._query, bg="input", fg="text",
             insertbackground="text", selectbackground="sel_bg")
        self._query.pack(fill="x")
        self._query.bind("<Control-Return>", lambda _e: self._run())

        _lb(self, "Ctrl + Enter で実行", fg="muted",
            font=("Yu Gothic UI", 8)
            ).pack(anchor="e", padx=20, pady=(4, 0))

        ttk.Separator(self, orient="horizontal").pack(
            fill="x", padx=20, pady=14)

        # ── アクション ──
        act = _fr(self)
        act.pack(fill="x", **P)
        self._run_btn = _Btn(act, "▶  エージェント実行", None, px=18, py=8)
        self._run_btn.set_cmd(self._run)
        self._run_btn.pack(side="left")
        _Ghost(act, "ログをクリア", self._log_clear).pack(
            side="left", padx=(10, 0))

        # ── ツール実行インジケーター ──
        ind_row = _fr(self)
        ind_row.pack(fill="x", padx=20, pady=(16, 2))
        _sect(ind_row, "出力").pack(side="left")

        # 現在実行中のツール名を表示するバッジ
        self._tool_var = tk.StringVar(value="")
        badge_outer = _fr(ind_row, bg="border")
        badge_outer.pack(side="left", padx=(10, 0))
        self._badge = _tag(
            tk.Label(badge_outer, textvariable=self._tool_var,
                     bg=C["log_bg"], fg=C["c_tool"],
                     font=FONT_MONO, padx=8, pady=2, anchor="w"),
            bg="log_bg", fg="c_tool")
        self._badge.pack(fill="x", padx=1, pady=1)

        # ── ログ ──
        self._log = _Log(self,
            turn=C["c_turn"], tool=C["c_tool"],
            answer=C["c_answer"], err=C["c_err"],
            thinking=C["c_thinking"],
            call_tool=C["c_tool_args"])
        self._log.pack(fill="both", expand=True, padx=20, pady=(4, 16))

    # ── スコープ管理 ──

    def _add_file(self, mode: str):
        p = filedialog.askopenfilename(title="許可するファイルを選択")
        if p: self._add_scope(p, mode)

    def _add_dir(self, mode: str):
        p = filedialog.askdirectory(title="許可するフォルダを選択")
        if p: self._add_scope(p, mode)

    def _add_scope(self, p: str, mode: str):
        if not any(existing == p for existing, _ in self._paths):
            self._paths.append((p, mode))
            label = f"[{'RW' if mode == 'rw' else 'R '}]  {p}"
            self._scope_lb.configure(state="normal")
            self._scope_lb.insert("end", label)
            self._scope_lb.configure(state="disabled")

    def _clr_scope(self):
        self._paths.clear()
        self._scope_lb.configure(state="normal")
        self._scope_lb.delete(0, "end")
        self._scope_lb.configure(state="disabled")

    # ── 実行 ──

    def _run(self):
        if self._running: return
        query = self._query.get("1.0", "end").strip()
        if not query:
            messagebox.showwarning("未入力", "質問または指示を入力してください。")
            return
        self._running = True
        self._run_btn.enable(False)
        scope = "  ".join(
            f"[{'RW' if m == 'rw' else 'R'}]{p}" for p, m in self._paths
        ) if self._paths else "（外部ファイルなし）"
        sep = "─" * 52
        self._log.append(
            f"\n{sep}\n質問: {query}\nスコープ: {scope}\n{sep}\n", "turn")
        threading.Thread(target=self._work, args=(query,), daemon=True).start()

    def _work(self, query):
        import json as _json

        import agent as ag
        import config
        import sandbox
        import tool_registry
        from config import REQUIRE_WRITE_APPROVAL

        # GUI で設定されたコンテキスト長を反映
        try:
            ctx_val = int(self._ctx_var.get())
            if ctx_val > 0:
                config.CONTEXT_LIMIT = ctx_val
        except ValueError:
            pass  # 不正な値は無視してデフォルトを使用

        ro = [p for p, m in self._paths if m == "ro"]
        rw = [p for p, m in self._paths if m == "rw"]
        sandbox.set_allowed_roots(ro_paths=ro, rw_paths=rw)

        # 書き込み承認コールバック（GUIダイアログ）
        if REQUIRE_WRITE_APPROVAL:
            panel = self

            def _approval_dialog(tool_name, operation, args):
                """メインスレッドで承認ダイアログを表示する（スレッドセーフ）。"""
                result = [False]
                event = threading.Event()

                def ask():
                    args_str = _json.dumps(args, ensure_ascii=False, indent=2)[:200]
                    result[0] = messagebox.askyesno(
                        "操作の承認",
                        f"ツール: {tool_name}\n"
                        f"操作: {operation}\n\n"
                        f"引数:\n{args_str}\n\n"
                        "実行を許可しますか？",
                    )
                    event.set()

                panel.after(0, ask)
                event.wait()
                return result[0]

            tool_registry.set_approval_callback(_approval_dialog)

        old_err = sys.stderr
        sys.stderr = _StderrRouter(self._q)
        try:
            extra_ctx_parts = []
            if self._paths:
                lines = "\n".join(
                    f"- [{'RW' if m == 'rw' else 'R'}] {p}" for p, m in self._paths
                )
                extra_ctx_parts.append(
                    "## 解析対象スコープ\n\n"
                    "以下のパスが解析・操作の対象です。ツール呼び出し時はこれらのパスを使用してください:\n"
                    + lines
                )
            extra_context = "\n\n".join(extra_ctx_parts)
            ans = ag.agent_loop(
                query,
                verbose=True,
                extra_context=extra_context,
                scopes=self._paths if self._paths else None,
            )
            self._q.put(("answer", f"\n【回答】\n{ans}\n"))
        except Exception as e:
            self._q.put(("err", f"[error] {e}\n"))
        finally:
            sys.stderr = old_err
            sandbox.clear()
            tool_registry.set_approval_callback(None)
            self._q.put(("__done__", ""))

    def _poll(self):
        try:
            while True:
                tag, text = self._q.get_nowait()
                if tag == "__done__":
                    self._running = False
                    self._run_btn.enable(True)
                    self._tool_var.set("")
                else:
                    self._log.append(text, tag or None)
                    # ツール実行インジケーター更新
                    if tag == "tool":
                        self._tool_var.set(text.strip())
                    # .md 書き込み検出 → MDビュアーを開く
                    if tag == "tool" and "[write]" in text:
                        stripped = text.strip()
                        path = stripped[len("[write]"):].strip()
                        if path.lower().endswith(".md"):
                            root = self.winfo_toplevel()
                            self.after(200, lambda p=path: _open_md_viewer(root, p))
        except queue.Empty:
            pass
        self.after(80, self._poll)

    def _log_clear(self):
        self._log.clear()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MDビュアー
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class _MdViewer(tk.Toplevel):
    """Markdownファイルを簡易レンダリングして表示するサブウィンドウ。"""

    def __init__(self, root: tk.Tk, path: str) -> None:
        super().__init__(root)
        self._path = path
        self.title(f"MD ビュアー — {os.path.basename(path)}")
        self.geometry("740x580")
        self.minsize(480, 320)
        self.configure(bg=C["bg"])
        self._build()
        self._load()

    def _build(self) -> None:
        # ── ヘッダー ──
        hdr = _fr(self, bg="surface")
        hdr.pack(fill="x")
        _lb(hdr, os.path.basename(self._path),
            bg="surface", fg="text",
            font=("Yu Gothic UI", 10, "bold")
            ).pack(side="left", padx=14, pady=9)
        _Btn(hdr, "システムで開く", self._open_system,
             role="neutral", px=10, py=5
             ).set_cmd(self._open_system).pack(side="right", padx=8, pady=7)
        _Ghost(hdr, "更新", self._load).pack(side="right", padx=(0, 4), pady=7)

        sep = _fr(self, bg="border")
        sep.pack(fill="x")
        sep.configure(height=1)

        # ── 本文エリア ──
        body = _fr(self, bg="surface")
        body.pack(fill="both", expand=True, padx=14, pady=10)

        self._txt = tk.Text(
            body, wrap="word", state="disabled",
            font=FONT, bg=C["surface"], fg=C["text"],
            insertbackground=C["text"],
            selectbackground=C["sel_bg"],
            relief="flat", borderwidth=0,
            padx=4, pady=4)
        _tag(self._txt, bg="surface", fg="text",
             selectbackground="sel_bg")

        sb = ttk.Scrollbar(body, orient="vertical", command=self._txt.yview)
        self._txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._txt.pack(side="left", fill="both", expand=True)

        self._configure_tags()

    def _configure_tags(self) -> None:
        t = self._txt
        t.tag_configure("h1",
            font=("Yu Gothic UI", 18, "bold"), foreground=C["text"],
            spacing1=12, spacing3=6)
        t.tag_configure("h2",
            font=("Yu Gothic UI", 14, "bold"), foreground=C["text"],
            spacing1=10, spacing3=4)
        t.tag_configure("h3",
            font=("Yu Gothic UI", 11, "bold"), foreground=C["text"],
            spacing1=8, spacing3=2)
        t.tag_configure("h4",
            font=("Yu Gothic UI", 10, "bold"), foreground=C["muted"],
            spacing1=6)
        t.tag_configure("code_inline",
            font=FONT_MONO, background=C["input"],
            foreground=C["primary"])
        t.tag_configure("code_block",
            font=FONT_MONO, background=C["log_bg"],
            foreground=C["log_fg"],
            lmargin1=8, lmargin2=8,
            spacing1=6, spacing3=6)
        t.tag_configure("bullet",  lmargin1=16, lmargin2=28)
        t.tag_configure("quote",
            foreground=C["muted"], lmargin1=16, lmargin2=16,
            font=("Yu Gothic UI", 10, "italic"))
        t.tag_configure("bold",    font=("Yu Gothic UI", 10, "bold"))
        t.tag_configure("hr",      foreground=C["border"])
        t.tag_configure("muted",   foreground=C["muted"])

    def _load(self) -> None:
        try:
            with open(self._path, encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            messagebox.showerror("読み込みエラー", str(e), parent=self)
            return
        self._txt.configure(state="normal")
        self._txt.delete("1.0", "end")
        self._render(content)
        self._txt.configure(state="disabled")

    def _render(self, md: str) -> None:
        import re
        in_code = False
        code_buf: list[str] = []

        for line in md.splitlines():
            # コードブロック
            if line.startswith("```"):
                if in_code:
                    self._txt.insert("end", "\n".join(code_buf) + "\n", "code_block")
                    code_buf.clear()
                    in_code = False
                else:
                    in_code = True
                continue
            if in_code:
                code_buf.append(line)
                continue

            # 水平線
            if re.fullmatch(r"[-*_]{3,}", line.strip()):
                self._txt.insert("end", "─" * 64 + "\n", "hr")
                continue

            # 見出し
            m = re.match(r"^(#{1,4})\s+(.*)", line)
            if m:
                lvl = len(m.group(1))
                tag = f"h{lvl}"
                self._txt.insert("end", m.group(2) + "\n", tag)
                continue

            # 引用
            if line.startswith("> "):
                self._txt.insert("end", "  " + line[2:] + "\n", "quote")
                continue

            # リスト
            m = re.match(r"^(\s*)[-*+]\s+(.*)", line)
            if m:
                indent = len(m.group(1)) // 2
                prefix = "    " * indent + "• "
                self._insert_inline(prefix + m.group(2) + "\n", "bullet")
                continue

            # 番号リスト
            m = re.match(r"^(\s*)\d+\.\s+(.*)", line)
            if m:
                self._insert_inline(line + "\n", "bullet")
                continue

            # 通常行（インライン書式）
            self._insert_inline(line + "\n")

        if code_buf:
            self._txt.insert("end", "\n".join(code_buf) + "\n", "code_block")

    def _insert_inline(self, text: str, base_tag: str | None = None) -> None:
        """**bold** と `code` のインライン書式を処理して挿入する。"""
        import re
        pattern = re.compile(r"(\*\*[^*\n]+\*\*|`[^`\n]+`)")
        parts = pattern.split(text)
        for part in parts:
            if part.startswith("**") and part.endswith("**") and len(part) > 4:
                tags = ("bold", base_tag) if base_tag else ("bold",)
                self._txt.insert("end", part[2:-2], tags)
            elif part.startswith("`") and part.endswith("`") and len(part) > 2:
                self._txt.insert("end", part[1:-1], "code_inline")
            else:
                if base_tag:
                    self._txt.insert("end", part, base_tag)
                else:
                    self._txt.insert("end", part)

    def _open_system(self) -> None:
        try:
            os.startfile(self._path)
        except Exception as e:
            messagebox.showerror("エラー", str(e), parent=self)


def _open_md_viewer(root: tk.Tk, path: str) -> None:
    """
    パスを解決してMDビュアーを開く。
    パスはエージェントのカレントディレクトリ基準の相対パスも可。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    if not os.path.isabs(path):
        path = os.path.join(here, path)
    if not os.path.isfile(path):
        return
    _MdViewer(root, path)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ナレッジ管理ヘルパー（GUI非依存）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _fmt_size(n: int) -> str:
    if n < 1024:      return f"{n} B"
    if n < 1024**2:   return f"{n/1024:.1f} KB"
    return f"{n/1024**2:.1f} MB"


def _parse_index_sources(path: str) -> dict[str, str]:
    result: dict[str, str] = {}
    current = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip()
            if line.startswith("### "):
                current = line[4:].strip()
            elif current and line.startswith("*ソース:"):
                result[current] = line.strip().lstrip("*ソース:").rstrip("*").strip()
                current = None
    return result


def _remove_from_index(path: str, names: list[str]) -> None:
    name_set = set(names)
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("### ") and line[4:].strip() in name_set:
            i += 1
            while i < len(lines) and not lines[i].startswith("### "):
                i += 1
            continue
        if line.lstrip().startswith("- path: skills/"):
            parts = line.strip()[len("- path: "):].split("/")
            if len(parts) >= 2 and parts[1] in name_set:
                i += 1
                while i < len(lines) and lines[i].lstrip().startswith(
                        ("name:", "summary:")):
                    i += 1
                continue
        out.append(line)
        i += 1
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(out)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  メインウィンドウ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    # config.py の相対パス（SKILLS_DIR 等）が正しく解決されるよう
    # CWD を agent/ ディレクトリに固定する
    os.chdir(here)

    root = tk.Tk()
    root.title("ナレッジエージェント")
    root.geometry("780x740")
    root.minsize(620, 540)
    root.configure(bg=C["bg"])
    _tag(root, bg="bg")

    style = ttk.Style(root)
    _STYLE[0] = style
    _apply_style(style)

    try:
        root.iconbitmap(os.path.join(here, "icon.ico"))
    except Exception:
        pass

    # ── ヘッダー ──
    hdr = tk.Frame(root, bg=C["primary"], height=46)
    hdr.pack(fill="x")
    hdr.pack_propagate(False)
    tk.Label(hdr, text="ナレッジエージェント",
             bg=C["primary"], fg=C["inv"],
             font=FONT_TITLE, padx=20).pack(side="left", fill="y")

    toggle_btn = tk.Label(
        hdr, text="☾  ダーク",
        bg=C["primary"], fg=C["inv"],
        font=FONT_SM, padx=16, pady=0,
        cursor="hand2")
    toggle_btn.pack(side="right", fill="y")
    toggle_btn.bind("<Button-1>", lambda _e: toggle_theme())
    toggle_btn.bind("<Enter>",
        lambda _e: toggle_btn.configure(bg=C["primary_h"]))
    toggle_btn.bind("<Leave>",
        lambda _e: toggle_btn.configure(bg=C["primary"]))
    _TOGGLE_BTN[0] = toggle_btn

    # ── タブ ──
    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True)

    tab_m = KnowledgeManagerTab(nb)
    tab_a = AgentTab(nb)

    nb.add(tab_m, text="  ナレッジ管理  ")
    nb.add(tab_a, text="  エージェント  ")

    root.mainloop()


if __name__ == "__main__":
    main()
