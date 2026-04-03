"""
readers/pdf.py — PDF → Markdown変換

大規模PDF（100ページ以上）はチャンク逐次処理で高速化する。
小規模PDFは従来通りpymupdf4llmで一括変換。

メモリ安全設計:
  - ProcessPoolExecutor ではなく逐次チャンク処理（各チャンク変換後にGC）
  - detect_headings_by_fontはサンプリングベースで全ページスキャンしない
  - 巨大文字列の一括結合を避け、ファイル書き出し型のAPIも提供
"""

from __future__ import annotations

import gc
import sys

from config import PDF_CHUNK_PAGES, PDF_PARALLEL_THRESHOLD, PDF_WORKERS


def read(filepath: str) -> str:
    """PDFをMarkdown形式に変換して返す。"""
    try:
        import fitz
    except ImportError:
        raise ImportError(
            "PDFの読み込みにはPyMuPDFが必要です。\npip install pymupdf pymupdf4llm"
        )

    doc = fitz.open(filepath)
    total_pages = len(doc)
    doc.close()

    # 小さいPDFは一括処理
    if total_pages <= PDF_PARALLEL_THRESHOLD:
        return _convert_all(filepath)

    # 大きいPDFはチャンク逐次処理（メモリ安全）
    print(f"  大規模PDF検出（{total_pages}ページ）— チャンク逐次処理を使用", file=sys.stderr)
    return _convert_chunked_sequential(filepath, total_pages)


def _convert_all(filepath: str) -> str:
    """pymupdf4llmで全ページを一括変換する。"""
    try:
        import pymupdf4llm
        return pymupdf4llm.to_markdown(filepath)
    except ImportError:
        return _convert_fitz_fallback(filepath, 0, None)


def _convert_chunk_single(filepath: str, page_start: int, page_end: int) -> str:
    """
    1チャンク分のページをMarkdownに変換する。

    変換完了後にGCを実行してメモリを解放する。
    """
    try:
        import pymupdf4llm
        pages = list(range(page_start, page_end))
        md = pymupdf4llm.to_markdown(filepath, pages=pages)
        gc.collect()
        return md
    except (ImportError, TypeError):
        md = _convert_fitz_fallback(filepath, page_start, page_end)
        gc.collect()
        return md


def _convert_fitz_fallback(
    filepath: str, page_start: int, page_end: int | None
) -> str:
    """PyMuPDF（fitz）で直接テキスト抽出するフォールバック。"""
    import fitz

    doc = fitz.open(filepath)
    if page_end is None:
        page_end = len(doc)

    pages = []
    for i in range(page_start, min(page_end, len(doc))):
        page = doc[i]
        text = page.get_text()
        if text.strip():
            pages.append(f"## Page {i + 1}\n\n{text}")
    doc.close()
    return "\n\n".join(pages)


def _convert_chunked_sequential(filepath: str, total_pages: int) -> str:
    """
    チャンク逐次処理でMarkdown変換する。

    メモリ安全: 1チャンクずつ変換し、変換済みチャンクの結果のみ保持。
    ProcessPoolExecutorを使わないことで、複数プロセスが同時にPDFを開くメモリ爆発を防ぐ。
    """
    chunk_size = PDF_CHUNK_PAGES
    chunks = []
    for start in range(0, total_pages, chunk_size):
        end = min(start + chunk_size, total_pages)
        chunks.append((start, end))

    total_chunks = len(chunks)
    results: list[str] = []

    for i, (start, end) in enumerate(chunks):
        md = _convert_chunk_single(filepath, start, end)
        results.append(md)
        _print_progress(i + 1, total_chunks)

    # 結合
    combined = "\n\n".join(results)
    # 個別チャンク結果を解放
    results.clear()
    gc.collect()
    return combined


def _print_progress(completed: int, total: int) -> None:
    """進捗を表示する。"""
    pct = completed * 100 // total
    bar_len = 30
    filled = bar_len * completed // total
    bar = "█" * filled + "░" * (bar_len - filled)
    print(
        f"\r  PDF変換: [{bar}] {pct:3d}% ({completed}/{total}チャンク)",
        end="" if completed < total else "\n",
        file=sys.stderr,
        flush=True,
    )


def get_page_count(filepath: str) -> int:
    """PDFの総ページ数を返す。"""
    import fitz
    doc = fitz.open(filepath)
    count = len(doc)
    doc.close()
    return count


def read_pages(filepath: str, start_page: int, end_page: int) -> str:
    """
    指定ページ範囲をMarkdownに変換して返す。

    Parameters
    ----------
    start_page: 開始ページ番号（1始まり）
    end_page: 終了ページ番号（1始まり、inclusive）
    """
    # 1-basedを0-basedに変換
    return _convert_chunk_single(filepath, start_page - 1, end_page)


def extract_toc(filepath: str) -> list[tuple[int, str, int]]:
    """
    PDFの目次（Table of Contents）を抽出する。

    Returns: [(level, title, page_number), ...]
    """
    import fitz
    doc = fitz.open(filepath)
    toc = doc.get_toc()
    doc.close()
    return toc


def detect_headings_by_font(filepath: str, sample_pages: int = 50) -> list[dict]:
    """
    フォントサイズ解析で見出し候補を検出する。

    メモリ安全設計:
    - 先頭sample_pagesでフォントサイズを統計的にサンプリング
    - 全ページスキャンは行わず、等間隔サンプリングで見出しを検出
    - 各ページ処理後にデータを破棄

    Returns: [{"text": str, "page": int, "font_size": float, "level": int}, ...]
    """
    import fitz

    doc = fitz.open(filepath)
    total = len(doc)
    sample_count = min(total, sample_pages)

    # Phase 1: 先頭sample_pagesでフォントサイズ統計を収集
    font_sizes: dict[float, int] = {}

    for page_idx in range(sample_count):
        page = doc[page_idx]
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        for block in blocks:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    size = round(span["size"], 1)
                    text = span["text"].strip()
                    if text:
                        font_sizes[size] = font_sizes.get(size, 0) + len(text)

    if not font_sizes:
        doc.close()
        return []

    # 最頻出フォントサイズ = 本文サイズと推定
    body_size = max(font_sizes, key=font_sizes.get)

    # 本文より大きいフォントを見出し候補とする
    heading_sizes = sorted(
        [s for s in font_sizes if s > body_size + 0.5], reverse=True
    )

    if not heading_sizes:
        doc.close()
        return []

    # サイズ→レベルのマッピング（大きい順に1, 2, ...）
    size_to_level = {s: i + 1 for i, s in enumerate(heading_sizes[:3])}

    # Phase 2: 等間隔サンプリングで見出しを検出（全ページスキャンしない）
    # 大規模PDFでは最大500ページをサンプリング
    max_scan = 500
    if total <= max_scan:
        scan_pages = range(total)
    else:
        step = total // max_scan
        scan_pages = range(0, total, step)

    headings = []
    for page_idx in scan_pages:
        page = doc[page_idx]
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        for block in blocks:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                line_text_parts = []
                line_size = 0.0
                for span in line.get("spans", []):
                    size = round(span["size"], 1)
                    text = span["text"].strip()
                    if text:
                        line_text_parts.append(text)
                        line_size = max(line_size, size)
                if line_text_parts and line_size in size_to_level:
                    full_text = " ".join(line_text_parts)
                    if len(full_text) < 2 or full_text.replace(" ", "").isdigit():
                        continue
                    headings.append({
                        "text": full_text,
                        "page": page_idx,
                        "font_size": line_size,
                        "level": size_to_level[line_size],
                    })
    doc.close()
    return headings
