"""
gui.py のレイアウトモックアップ画像を生成するスクリプト。
tkinterが利用できない環境でGUI画面を確認するために使用。
"""
from PIL import Image, ImageDraw, ImageFont

W, H = 780, 740

# カラーパレット (LIGHT)
BG       = "#F8FAFC"
SURFACE  = "#FFFFFF"
INPUT    = "#FFFFFF"
BORDER   = "#E2E8F0"
TEXT     = "#0F172A"
MUTED    = "#64748B"
INV      = "#FFFFFF"
PRIMARY  = "#3B82F6"
PRIMARY_H= "#2563EB"
LOG_BG   = "#1E1E2E"
LOG_FG   = "#CDD6F4"
SEL_BG   = "#DBEAFE"

def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def draw_tab(img_draw, tab_name):
    """共通ヘッダー + タブバーを描画"""
    # ヘッダー
    img_draw.rectangle([0, 0, W, 46], fill=hex_to_rgb(PRIMARY))
    img_draw.text((20, 13), "ナレッジエージェント", fill=hex_to_rgb(INV))
    img_draw.text((W-120, 13), "☾  ダーク", fill=hex_to_rgb(INV))
    # タブバー
    img_draw.rectangle([0, 46, W, 82], fill=hex_to_rgb(BG))
    tabs = ["  ナレッジ管理  ", "  エージェント  "]
    x = 10
    for t in tabs:
        tw = len(t) * 9
        if t.strip() == tab_name:
            img_draw.rectangle([x, 50, x+tw, 82], fill=hex_to_rgb(SURFACE))
            img_draw.text((x+8, 58), t, fill=hex_to_rgb(PRIMARY))
        else:
            img_draw.text((x+8, 58), t, fill=hex_to_rgb(MUTED))
        x += tw + 4

def draw_btn(d, x, y, text, role="primary", w=None):
    bw = w or (len(text) * 10 + 24)
    bh = 30
    color = {"primary": PRIMARY, "danger": "#EF4444", "neutral": BORDER}[role]
    fg = INV if role != "neutral" else MUTED
    d.rounded_rectangle([x, y, x+bw, y+bh], radius=4, fill=hex_to_rgb(color))
    d.text((x+12, y+7), text, fill=hex_to_rgb(fg))
    return bw

def draw_ghost(d, x, y, text):
    d.text((x, y), text, fill=hex_to_rgb(MUTED))

def draw_section(d, y, text):
    d.text((20, y), text, fill=hex_to_rgb(MUTED))
    return y + 20

def draw_input(d, x, y, w, h, text=""):
    d.rectangle([x, y, x+w, y+h], outline=hex_to_rgb(BORDER), fill=hex_to_rgb(INPUT))
    if text:
        d.text((x+6, y+4), text, fill=hex_to_rgb(MUTED))
    return y + h

def draw_separator(d, y):
    d.line([(20, y), (W-20, y)], fill=hex_to_rgb(BORDER), width=1)
    return y + 14

def draw_log_area(d, y, h, lines=None):
    d.rectangle([20, y, W-20, y+h], fill=hex_to_rgb(LOG_BG))
    if lines:
        ly = y + 8
        for text, color in lines:
            d.text((30, ly), text, fill=hex_to_rgb(color))
            ly += 16
    return y + h


# ─── タブ1: ナレッジ管理 ───
img1 = Image.new("RGB", (W, H), hex_to_rgb(BG))
d1 = ImageDraw.Draw(img1)
draw_tab(d1, "ナレッジ管理")

y = 92
# 取り込みパネル
y = draw_section(d1, y+16, "取り込み")
y += 6
bx = 20
bw = draw_btn(d1, bx, y, "ファイル…"); bx += bw + 8
bw = draw_btn(d1, bx, y, "フォルダ…", "neutral"); bx += bw + 20
d1.text((bx, y+7), "スキル名", fill=hex_to_rgb(MUTED)); bx += 70
draw_input(d1, bx, y, 130, 28); bx += 145
d1.text((bx, y+7), "☐ LLM", fill=hex_to_rgb(TEXT)); bx += 60
draw_btn(d1, W-120, y, "▶  実行")
y += 38
d1.text((20, y), "ファイルまたはフォルダを選択してください", fill=hex_to_rgb(MUTED))
y += 20
y = draw_separator(d1, y+8)

# ナレッジ一覧
y = draw_section(d1, y, "ナレッジ一覧")
# ツールバー
d1.text((W-310, y-2), "全選択  全解除  更新", fill=hex_to_rgb(MUTED))
draw_btn(d1, W-120, y-6, "選択を削除", "danger", 100)
y += 14
# Treeviewヘッダー
d1.rectangle([20, y, W-20, y+26], fill=hex_to_rgb(BG), outline=hex_to_rgb(BORDER))
cols = ["ナレッジ名", "ファイル数", "サイズ", "カバレッジ", "取り込み元"]
cx = [22, 220, 310, 400, 510]
for i, col in enumerate(cols):
    d1.text((cx[i], y+5), col, fill=hex_to_rgb(MUTED))
y += 26
# Treeview行サンプル
for row_i, row in enumerate([
    ("embedded_guide", "5", "42.3 KB", "100%", "/docs/embedded.pdf"),
    ("python_tutorial", "8", "67.1 KB", "75% (15/20p)", "/docs/python.pdf"),
    ("api_reference", "12", "128.5 KB", "100%", "/docs/api/"),
]):
    bg = hex_to_rgb(SURFACE)
    d1.rectangle([20, y, W-20, y+26], fill=bg, outline=hex_to_rgb(BORDER))
    for i, val in enumerate(row):
        d1.text((cx[i], y+5), val, fill=hex_to_rgb(TEXT))
    y += 26

# 空行
for _ in range(4):
    d1.rectangle([20, y, W-20, y+26], fill=hex_to_rgb(SURFACE), outline=hex_to_rgb(BORDER))
    y += 26

d1.text((20, y+6), "3 件", fill=hex_to_rgb(MUTED))

img1.save("/home/user/llmTest/gui_tab1_knowledge.png")


# ─── タブ2: エージェント ───
img2 = Image.new("RGB", (W, H), hex_to_rgb(BG))
d2 = ImageDraw.Draw(img2)
draw_tab(d2, "エージェント")

y = 92
# スコープ
y = draw_section(d2, y+16, "作業スコープ  —  読み書きを許可するファイル / フォルダ")
y += 8
bx = 20
bw = draw_btn(d2, bx, y, "ファイル追加…"); bx += bw + 8
draw_btn(d2, bx, y, "フォルダ追加…", "neutral")
draw_btn(d2, W-110, y, "リセット", "danger", 90)
y += 38
draw_input(d2, 20, y, W-40, 52, "  /home/user/project/src\n  /home/user/project/tests")
y += 56
d2.text((20, y+2), "skills/  と  project_memory.md  は常に許可", fill=hex_to_rgb(MUTED))
y += 18
y = draw_separator(d2, y+8)

# セッションナレッジ
y = draw_section(d2, y, "セッションナレッジ  —  このセッション限りのコンテキスト")
d2.text((W-130, y-2), "≈ 12K tokens", fill=hex_to_rgb(MUTED))
y += 8
bx = 20
bw = draw_btn(d2, bx, y, "ファイル追加…"); bx += bw + 8
draw_btn(d2, bx, y, "フォルダ追加…", "neutral")
draw_ghost(d2, W-60, y+7, "クリア")
y += 38
draw_input(d2, 20, y, W-40, 52, "  /docs/spec.md\n  /docs/design_notes.pdf")
y += 56
d2.text((20, y+2), "選択中の行を Delete キーで削除", fill=hex_to_rgb(MUTED))
y += 18
y = draw_separator(d2, y+8)

# 質問
y = draw_section(d2, y, "質問 / 指示")
y += 8
draw_input(d2, 20, y, W-40, 68, "  組み込みシステムのタスク管理について\n  設計ドキュメントを作成してください")
y += 72
d2.text((W-150, y+2), "Ctrl + Enter で実行", fill=hex_to_rgb(MUTED))
y += 18
y = draw_separator(d2, y+8)

# アクション
draw_btn(d2, 20, y, "▶  エージェント実行", w=180)
draw_ghost(d2, 215, y+7, "ログをクリア")
y += 38

# ツール実行インジケーター
y = draw_section(d2, y+8, "出力")
# バッジ
d2.rounded_rectangle([80, y-4, 280, y+16], radius=3, fill=hex_to_rgb(LOG_BG))
d2.text((88, y-1), "[read_skill] rtos/task.md", fill=hex_to_rgb("#FFD700"))
y += 22

# ログ
draw_log_area(d2, y, H-y-16, lines=[
    ("[turn 1] thinking...", "#79C0FF"),
    ("[list_skills] scope=embedded", "#FFD700"),
    ("[read_skill] embedded_guide/task_management.md", "#FFD700"),
    ("[keyword_search] pattern='mutex|semaphore'", "#FFD700"),
    ("", LOG_FG),
    ("【回答】", "#7EE787"),
    ("組み込みシステムのタスク管理について、以下の設計ドキュメント", LOG_FG),
    ("を生成しました: output/task_design.md", LOG_FG),
])

img2.save("/home/user/llmTest/gui_tab2_agent.png")

print("Generated:")
print("  gui_tab1_knowledge.png — ナレッジ管理タブ")
print("  gui_tab2_agent.png — エージェントタブ")
