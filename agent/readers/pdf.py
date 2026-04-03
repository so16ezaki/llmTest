"""
readers/pdf.py — PDF → Markdown変換

大規模PDF（100ページ以上）は並列チャンク処理で高速化する。
小規模PDFは従来通りpymupdf4llmで一括変換。
"""

from __future__ import annotations

import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

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

    # 大きいPDFはチャンク並列処理
    print(f"  大規模PDF検出（{total_pages}ページ）— 並列処理を使用", file=sys.stderr)
    return _convert_parallel(filepath, total_pages)


def _convert_all(filepath: str) -> str:
    """pymupdf4llmで全ページを一括変換する。"""
    try:
        import pymupdf4llm
        return pymupdf4llm.to_markdown(filepath)
    except ImportError:
        return _convert_fitz_fallback(filepath, 0, None)


def _convert_chunk(args: tuple) -> tuple[int, str]:
    """
    1チャンク分のページをMarkdownに変換する（ワーカープロセスで実行）。

    Returns: (chunk_index, markdown_text)
    """
    filepath, chunk_idx, page_start, page_end = args
    try:
        import pymupdf4llm
        pages = list(range(page_start, page_end))
        md = pymupdf4llm.to_markdown(filepath, pages=pages)
        return (chunk_idx, md)
    except (ImportError, TypeError):
        # pymupdf4llmがpagesパラメータ未対応、またはインポート失敗
        return (chunk_idx, _convert_fitz_fallback(filepath, page_start, page_end))


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


def _convert_parallel(filepath: str, total_pages: int) -> str:
    """ページ範囲ごとに並列でMarkdown変換する。"""
    # チャンク分割
    chunks = []
    for idx, start in enumerate(range(0, total_pages, PDF_CHUNK_PAGES)):
        end = min(start + PDF_CHUNK_PAGES, total_pages)
        chunks.append((filepath, idx, start, end))

    total_chunks = len(chunks)
    results: dict[int, str] = {}

    # 並列実行
    with ProcessPoolExecutor(max_workers=PDF_WORKERS) as executor:
        futures = {
            executor.submit(_convert_chunk, chunk): chunk[1]
            for chunk in chunks
        }
        completed = 0
        for future in as_completed(futures):
            chunk_idx, md = future.result()
            results[chunk_idx] = md
            completed += 1
            _print_progress(completed, total_chunks)

    # チャンク順で結合
    ordered = [results[i] for i in range(total_chunks)]
    return "\n\n".join(ordered)


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

    先頭sample_pages分のページを解析し、本文より大きいフォントを見出しと判定する。

    Returns: [{"text": str, "page": int, "font_size": float, "level": int}, ...]
    """
    import fitz

    doc = fitz.open(filepath)
    total = min(len(doc), sample_pages)

    # フォントサイズ→出現回数を集計
    font_sizes: dict[float, int] = {}
    blocks_info: list[dict] = []

    for page_idx in range(total):
        page = doc[page_idx]
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        for block in blocks:
            if block.get("type") != 0:  # テキストブロックのみ
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    size = round(span["size"], 1)
                    text = span["text"].strip()
                    if not text:
                        continue
                    font_sizes[size] = font_sizes.get(size, 0) + len(text)
                    blocks_info.append({
                        "text": text,
                        "page": page_idx,
                        "font_size": size,
                    })
    doc.close()

    if not font_sizes:
        return []

    # 最頻出フォントサイズ = 本文サイズと推定
    body_size = max(font_sizes, key=font_sizes.get)

    # 本文より大きいフォントを見出し候補とする
    heading_sizes = sorted(
        [s for s in font_sizes if s > body_size + 0.5], reverse=True
    )

    if not heading_sizes:
        return []

    # サイズ→レベルのマッピング（大きい順に1, 2, ...）
    size_to_level = {s: i + 1 for i, s in enumerate(heading_sizes[:3])}

    # 全ページを再スキャンして見出しを抽出
    headings = []
    doc = fitz.open(filepath)
    for page_idx in range(len(doc)):
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
                    # 短すぎる行や数字のみは見出しとしない
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
