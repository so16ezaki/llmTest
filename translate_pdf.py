"""
translate_pdf.py — PDF 英語→日本語 翻訳スクリプト（並列・バッチ高速版）

実行:
    python translate_pdf.py

依存: pip install pymupdf pymupdf4llm requests
"""

import json
import os
import sys
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed

import fitz
import pymupdf4llm
import requests

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ★ 設定（ここを編集）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

INPUT_PDF   = r"C:\Users\so16e\Documents\vscode\python\llmtest\llmTest\test_data\S32K3XXRM.pdf"
OUTPUT_PDF  = r"test_data\S32K3XXRM_ja.pdf"
PAGES       = None          # None=全ページ、"1-100"、"50-" なども可
MODEL       = "gemma4:e4b"
OLLAMA_URL  = "http://localhost:11434"

WORKERS      = 4            # 並列バッチ数（Ollama の OLLAMA_NUM_PARALLEL に合わせる）
BATCH_CHARS  = 40000        # 1リクエストあたりの目標文字数（大きいほど呼び出し回数が減る）
SAVE_EVERY   = 20           # Nページごとに中間保存
EXTRACT_BATCH = 100         # MD抽出を何ページごとに区切って保存するか

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  内部定数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CHECKPOINT = OUTPUT_PDF + ".checkpoint.json"
MD_CACHE   = OUTPUT_PDF + ".md_cache.json"
SEP_BLOCK  = "---BLOCK---"
SEP_PAGE   = "===PAGE_{n}==="

JP_FONTS = [
    r"C:\Windows\Fonts\YUGOTHB.TTC",
    r"C:\Windows\Fonts\YUGOTHM.TTC",
    r"C:\Windows\Fonts\meiryo.ttc",
    r"C:\Windows\Fonts\msgothic.ttc",
]

BATCH_PROMPT = """\
以下の英語テキストを日本語に翻訳してください。
ページは「===PAGE_N===」、ブロックは「---BLOCK---」で区切られています。
翻訳後も必ず同じ区切り文字をそのまま使って出力してください。
技術用語・型番・数字・コード・単位はそのまま保持してください。
翻訳テキストのみ出力してください。

{content}"""

MD_PROMPT = """\
以下の英語テキスト（Markdown形式）を日本語に翻訳してください。
技術用語・型番・数字・コード・単位はそのまま保持してください。
Markdownの書式はそのまま維持してください。翻訳テキストのみ出力してください。

{text}"""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  進捗表示
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def stage(name: str) -> float:
    """ステージ開始を表示し、開始時刻を返す。"""
    print(f"\n┌─ {name}")
    return time.time()

def stage_done(t0: float, extra: str = ""):
    elapsed = time.time() - t0
    suffix  = f"  {extra}" if extra else ""
    print(f"└─ 完了 ({elapsed:.1f}秒){suffix}")

def progress(current: int, total: int, label: str = "", eta_sec: float = 0.0):
    pct    = current / total * 100 if total else 0
    filled = int(30 * current / total) if total else 0
    bar    = "█" * filled + "░" * (30 - filled)
    eta    = f"  残り{eta_sec/60:.1f}分" if eta_sec > 0 else ""
    print(f"\r│  [{bar}] {current:>5}/{total}  {pct:5.1f}%{eta}  {label}",
          end="", flush=True)

def progress_done():
    print()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Ollama 呼び出し
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _ollama(prompt: str) -> str:
    r = requests.post(
        OLLAMA_URL.rstrip("/") + "/api/generate",
        json={"model": MODEL, "prompt": prompt,
              "stream": False, "options": {"temperature": 0.1}},
        timeout=600,
    )
    r.raise_for_status()
    return r.json().get("response", "").strip()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  テキストブロック ユーティリティ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _block_info(b: dict) -> tuple[str, float]:
    """ブロックのテキストと最大フォントサイズを1パスで返す。"""
    text_parts = []
    max_size   = 9.0
    for ln in b.get("lines", []):
        for sp in ln.get("spans", []):
            text_parts.append(sp.get("text", ""))
            sz = sp.get("size", 9.0)
            if sz > max_size:
                max_size = sz
    return " ".join(text_parts).strip(), max_size

def _block_text(b: dict) -> str:
    return _block_info(b)[0]

def _block_size(b: dict) -> float:
    return _block_info(b)[1]

def _text_blocks(page_dict: dict) -> list[dict]:
    """ページ dict からテキストブロック（type==0）のみ返す。"""
    return [b for b in page_dict.get("blocks", []) if b.get("type") == 0]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  バッチ翻訳（複数ページを1リクエストに集約）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def translate_batch(page_blocks: dict[int, list[str]]) -> dict[int, list[str]]:
    """
    {page_num: [block_text, ...]} を1リクエストで翻訳し
    {page_num: [translated_text, ...]} を返す。
    """
    parts             = []
    non_empty_by_page: dict[int, list[int]] = {}  # pn → 非空ブロックの元インデックス

    for pn, blocks in page_blocks.items():
        idx = [i for i, t in enumerate(blocks) if t.strip()]
        if not idx:
            continue
        non_empty_by_page[pn] = idx
        body = f"\n{SEP_BLOCK}\n".join(blocks[i] for i in idx)
        parts.append(f"{SEP_PAGE.format(n=pn)}\n{body}")

    if not parts:
        return {pn: list(bl) for pn, bl in page_blocks.items()}

    result = _ollama(BATCH_PROMPT.format(content="\n\n".join(parts)))

    # ── 結果パース：ページ区切りで分割 ──
    segments:    dict[int, str] = {}
    current_pn:  int | None     = None
    current_buf: list[str]      = []

    for line in result.splitlines():
        stripped = line.strip()
        if stripped.startswith("===PAGE_") and stripped.endswith("==="):
            if current_pn is not None:
                segments[current_pn] = "\n".join(current_buf).strip()
            try:
                current_pn = int(stripped[8:-3])
            except ValueError:
                current_pn = None
            current_buf = []
        else:
            current_buf.append(line)

    if current_pn is not None:
        segments[current_pn] = "\n".join(current_buf).strip()

    # ── ブロック区切りで分割 → 元インデックスに戻す ──
    output = {pn: list(bl) for pn, bl in page_blocks.items()}
    for pn, seg in segments.items():
        idx = non_empty_by_page.get(pn)
        if idx is None:
            continue
        for list_pos, orig_idx in enumerate(idx):
            parts_list = [p.strip() for p in seg.split(SEP_BLOCK)]
            if list_pos < len(parts_list):
                output[pn][orig_idx] = parts_list[list_pos]

    return output


def translate_md_single(text: str) -> str:
    """表ページ用：Markdown全体を1リクエストで翻訳。"""
    return _ollama(MD_PROMPT.format(text=text)) if text.strip() else text

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ページデータ分類・バッチ化
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def make_batches(
    page_list:  list[int],
    chunk_map:  dict[int, dict],
    page_dicts: dict[int, dict],
) -> list[dict]:
    """
    ページリストを BATCH_CHARS 以下になるよう複数ページバッチに束ねる。
    表ページは単独バッチとして分離する。

    各バッチ dict:
      {"type": "normal", "pages": {pn: [block_text,...]}, "blocks": {pn: [block_dict,...]}}
      {"type": "table",  "page": pn, "text": str, "blocks": [block_dict,...]}
    """
    batches:       list[dict]         = []
    cur_texts:     dict[int, list[str]]  = {}
    cur_blocks:    dict[int, list[dict]] = {}
    cur_chars:     int               = 0

    def _flush():
        nonlocal cur_texts, cur_blocks, cur_chars
        if cur_texts:
            batches.append({"type": "normal", "pages": cur_texts, "blocks": cur_blocks})
            cur_texts  = {}
            cur_blocks = {}
            cur_chars  = 0

    for pn in page_list:
        chunk  = chunk_map.get(pn, {})
        blocks = _text_blocks(page_dicts[pn])
        if not blocks:
            continue

        if chunk.get("tables"):
            _flush()
            md = chunk.get("text", "") or _block_text(blocks[0])
            batches.append({"type": "table", "page": pn, "text": md, "blocks": blocks})
        else:
            texts = [_block_text(b) for b in blocks]
            chars = sum(len(t) for t in texts)
            if cur_texts and cur_chars + chars > BATCH_CHARS:
                _flush()
            cur_texts[pn]  = texts
            cur_blocks[pn] = blocks
            cur_chars     += chars

    _flush()
    return batches


def run_batch(batch: dict) -> dict:
    """バッチを翻訳して結果を返す（ThreadPoolExecutor で並列実行）。"""
    if batch["type"] == "table":
        return {
            "type":   "table",
            "page":   batch["page"],
            "blocks": batch["blocks"],
            "result": translate_md_single(batch["text"]),
        }
    translated = translate_batch(batch["pages"])
    return {
        "type":    "normal",
        "results": translated,
        "blocks":  batch["blocks"],   # {pn: [block_dict,...]}
    }

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PDF 書き込み
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _insert(page, rect, text: str, fontname: str, size: float):
    while size >= 6.0:
        if page.insert_textbox(rect, text, fontname=fontname,
                               fontsize=size, color=(0, 0, 0), align=0) >= 0:
            return
        size -= 1.0
    step  = max(len(text) // 20, 5)
    trunc = text
    while len(trunc) > step:
        trunc = trunc[:-step]
        if page.insert_textbox(rect, trunc + "…", fontname=fontname,
                               fontsize=6.0, color=(0, 0, 0), align=0) >= 0:
            return


def _prepare_page(doc: fitz.Document, pn: int,
                  blocks: list[dict], font_buf: bytes) -> fitz.Page:
    """フォント登録・Redact を行い、書き込み可能な Page を返す。"""
    page = doc[pn]
    try:
        page.insert_font(fontname="jpfont", fontbuffer=font_buf)
    except Exception:
        pass
    for b in blocks:
        page.add_redact_annot(fitz.Rect(b["bbox"]), fill=(1, 1, 1))
    page.apply_redactions()
    return page


def apply_normal(doc: fitz.Document, pn: int,
                 blocks: list[dict], translations: list[str], font_buf: bytes):
    page = _prepare_page(doc, pn, blocks, font_buf)
    for b, tr in zip(blocks, translations):
        if tr.strip():
            _, size = _block_info(b)
            _insert(page, fitz.Rect(b["bbox"]), tr, "jpfont", size)


def apply_table(doc: fitz.Document, pn: int,
                blocks: list[dict], translated: str, font_buf: bytes):
    page = _prepare_page(doc, pn, blocks, font_buf)
    if translated.strip():
        rs  = [fitz.Rect(b["bbox"]) for b in blocks]
        box = fitz.Rect(min(r.x0 for r in rs), min(r.y0 for r in rs),
                        max(r.x1 for r in rs), max(r.y1 for r in rs))
        _insert(page, box, translated, "jpfont", 8.0)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  チェックポイント・保存
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _parse_pages(s, total: int) -> list[int]:
    if not s:
        return list(range(total))
    if "-" in s:
        l, r  = s.split("-", 1)
        start = (int(l) - 1) if l.strip() else 0
        end   = (int(r) - 1) if r.strip() else total - 1
        return list(range(max(0, start), min(total - 1, end) + 1))
    return [int(s) - 1]

def _load_cp() -> int:
    try:
        with open(CHECKPOINT, encoding="utf-8") as f:
            return int(json.load(f).get("last", -1))
    except Exception:
        return -1

def _save_cp(page: int):
    with open(CHECKPOINT, "w", encoding="utf-8") as f:
        json.dump({"last": page}, f)

def _ensure_dir(path: str):
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)

def _save_md_cache(chunk_map: dict[int, dict]):
    _ensure_dir(MD_CACHE)
    with open(MD_CACHE, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in chunk_map.items()}, f, ensure_ascii=False)

def _save_doc(doc: fitz.Document) -> fitz.Document:
    _ensure_dir(OUTPUT_PDF)
    tmp = OUTPUT_PDF + ".tmp"
    doc.save(tmp, deflate=True)
    doc.close()
    os.replace(tmp, OUTPUT_PDF)
    return fitz.open(OUTPUT_PDF)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  メイン
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    total_t0 = time.time()

    font_path = next((p for p in JP_FONTS if os.path.exists(p)), None)
    if not font_path:
        sys.exit(f"[ERROR] 日本語フォントが見つかりません: {JP_FONTS}")
    font_buf = fitz.Font(fontfile=font_path).buffer

    print("=" * 60)
    print(f"  PDF 翻訳ツール")
    print(f"  モデル      : {MODEL}  ({OLLAMA_URL})")
    print(f"  並列バッチ  : {WORKERS} workers  /  {BATCH_CHARS} chars/batch")
    print(f"  フォント    : {os.path.basename(font_path)}")
    print("=" * 60)

    # チェックポイント
    last_done = _load_cp()
    if last_done >= 0 and os.path.exists(OUTPUT_PDF):
        print(f"  ♻  チェックポイント: ページ {last_done + 2} から再開")
        doc = fitz.open(OUTPUT_PDF)
    else:
        last_done = -1
        doc = fitz.open(INPUT_PDF)

    total     = len(doc)
    page_list = _parse_pages(PAGES, total)
    page_list = [p for p in page_list if p > last_done]

    if not page_list:
        print("  ✓  全ページ翻訳済みです。")
        return

    print(f"  対象        : {len(page_list)} ページ"
          f"  ({page_list[0]+1}〜{page_list[-1]+1} / 全{total})")

    # ══════════════════════════════════════════════════
    #  Stage 1: pymupdf4llm 抽出（MD キャッシュ利用）
    # ══════════════════════════════════════════════════
    t0 = stage("Stage 1/4  テキスト抽出 (pymupdf4llm)")

    chunk_map: dict[int, dict] = {}

    try:
        with open(MD_CACHE, encoding="utf-8") as f:
            chunk_map = {int(k): v for k, v in json.load(f).items()}
        missing = [p for p in page_list if p not in chunk_map]
        status  = f"{len(chunk_map)}ページ読込済み"
        status += f"、{len(missing)}ページ追加抽出…" if missing else "（全キャッシュ済み）"
        print(f"│  キャッシュ: {status}", flush=True)
    except Exception:
        missing = page_list

    if missing:
        _save_md_cache(chunk_map)   # 既存分を先に確定保存
        n_missing = len(missing)
        extracted = 0
        try:
            for batch_start in range(0, n_missing, EXTRACT_BATCH):
                batch = missing[batch_start : batch_start + EXTRACT_BATCH]
                new_chunks = pymupdf4llm.to_markdown(
                    INPUT_PDF, page_chunks=True, pages=batch, show_progress=False
                )
                for c in new_chunks:
                    pn = c["metadata"].get("page")
                    if pn is not None:
                        chunk_map[pn] = {"text":   c.get("text", ""),
                                         "tables": bool(c.get("tables"))}
                extracted += len(batch)
                _save_md_cache(chunk_map)
                print(f"│  抽出・保存: {extracted}/{n_missing} ページ完了", flush=True)
        except KeyboardInterrupt:
            _save_md_cache(chunk_map)
            print(f"\n│  中断 — {len(chunk_map)} ページ分を保存しました → {MD_CACHE}")
            sys.exit(0)
        except Exception as e:
            _save_md_cache(chunk_map)
            print(f"│  警告: {e}  → 取得済み {len(chunk_map)} ページで続行")

    stage_done(t0, f"{len(chunk_map)} ページ分")

    # ══════════════════════════════════════════════════
    #  Stage 2: fitz テキストブロック位置取得
    # ══════════════════════════════════════════════════
    t0 = stage("Stage 2/4  テキストブロック位置取得 (fitz)")
    page_dicts: dict[int, dict] = {}
    for i, pn in enumerate(page_list):
        page_dicts[pn] = doc[pn].get_text("dict")
        progress(i + 1, len(page_list))
    progress_done()
    stage_done(t0)

    # ══════════════════════════════════════════════════
    #  Stage 3: バッチ構築 → 並列翻訳
    # ══════════════════════════════════════════════════
    batches   = make_batches(page_list, chunk_map, page_dicts)
    n_batches = len(batches)
    avg_pages = len(page_list) / n_batches if n_batches else 1

    t0 = stage(f"Stage 3/4  翻訳 ({n_batches} バッチ × {WORKERS} 並列"
               f"  avg {avg_pages:.1f} p/batch)")

    # {pn: {"mode": "normal"|"table", "blocks": [...], "translations": ...}}
    tr_results:  dict[int, dict] = {}
    t3_start     = time.time()
    n_pages      = len(page_list)
    recent_times: deque[tuple[float, int]] = deque(maxlen=WORKERS * 3)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(run_batch, b): b for b in batches}
        for fut in as_completed(futures):
            try:
                res = fut.result()
            except Exception as e:
                b = futures[fut]
                affected = (list(b.get("pages", {}).keys())
                            if b["type"] == "normal" else [b["page"]])
                print(f"\n│  警告: バッチ失敗 (pages={affected}): {e}")
                continue

            if res["type"] == "normal":
                batch_pages = len(res["results"])
                for pn, trs in res["results"].items():
                    tr_results[pn] = {"mode": "normal",
                                      "blocks": res["blocks"][pn],
                                      "translations": trs}
            else:
                batch_pages = 1
                pn = res["page"]
                tr_results[pn] = {"mode": "table",
                                   "blocks": res["blocks"],
                                   "translations": res["result"]}

            done_pages = len(tr_results)
            recent_times.append((time.time(), batch_pages))

            eta = 0.0
            if len(recent_times) >= WORKERS and done_pages > 0:
                window_pages = sum(p for _, p in recent_times)
                window_time  = recent_times[-1][0] - recent_times[0][0]
                if window_time > 0 and window_pages > 0:
                    eta = (n_pages - done_pages) / (window_pages / window_time)

            elapsed = time.time() - t3_start
            ppm     = done_pages / elapsed * 60 if elapsed > 0 else 0
            progress(done_pages, n_pages,
                     f"{ppm:.1f}p/min  バッチ{len(recent_times)}/{n_batches}",
                     eta_sec=eta)

    progress_done()
    stage_done(t0, f"{len(tr_results)} ページ翻訳完了")

    # ══════════════════════════════════════════════════
    #  Stage 4: PDF 書き込み・保存
    # ══════════════════════════════════════════════════
    t0 = stage("Stage 4/4  PDF 書き込み・保存")

    for i, pn in enumerate(page_list):
        res = tr_results.get(pn)
        if res is None:
            progress(i + 1, len(page_list), f"p.{pn+1} スキップ")
            continue

        if res["mode"] == "normal":
            apply_normal(doc, pn, res["blocks"], res["translations"], font_buf)
        else:
            apply_table(doc, pn, res["blocks"], res["translations"], font_buf)

        progress(i + 1, len(page_list), f"p.{pn+1}")

        if (i + 1) % SAVE_EVERY == 0 and i + 1 < len(page_list):
            progress_done()
            print(f"│  [中間保存] ページ {pn+1} まで…", end="", flush=True)
            doc = _save_doc(doc)
            _save_cp(pn)
            print(" 完了")

    progress_done()
    print("│  最終保存中…", end="", flush=True)
    _save_doc(doc)
    _save_cp(page_list[-1])
    if os.path.exists(CHECKPOINT):
        os.remove(CHECKPOINT)
    print(" 完了")
    stage_done(t0, OUTPUT_PDF)

    total_elapsed = time.time() - total_t0
    pps = len(page_list) / total_elapsed if total_elapsed > 0 else 0
    print("\n" + "=" * 60)
    print(f"  ✓  翻訳完了")
    print(f"  出力        : {OUTPUT_PDF}")
    print(f"  MDキャッシュ: {MD_CACHE}")
    print(f"  所要時間    : {total_elapsed/60:.1f} 分"
          f"  ({len(page_list)} ページ, {pps:.2f} p/s)")
    print("=" * 60)


if __name__ == "__main__":
    main()
