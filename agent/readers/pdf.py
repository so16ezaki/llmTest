"""
readers/pdf.py — PDF → Markdown変換

大規模PDF（100ページ以上）は並列チャンク処理で高速化する。
小規模PDFは従来通りpymupdf4llmで一括変換。
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import PDF_CHUNK_PAGES, PDF_PARALLEL_THRESHOLD, PDF_WORKERS


def read(filepath: str, max_pages: int | None = None) -> str:
    """PDFをMarkdown形式に変換して返す。

    Args:
        filepath: PDFファイルパス
        max_pages: 読み込む最大ページ数。None または 0 で全ページ。
    """
    try:
        import fitz
    except ImportError:
        raise ImportError(
            "PDFの読み込みにはPyMuPDFが必要です。\npip install pymupdf pymupdf4llm"
        )

    doc = fitz.open(filepath)
    total_pages = len(doc)
    doc.close()

    # ページ上限を適用
    if max_pages and max_pages < total_pages:
        print(
            f"  ページ上限適用: {total_pages}ページ中 先頭{max_pages}ページのみ処理",
            file=sys.stderr,
        )
        total_pages = max_pages

    # 小さいPDFは一括処理
    if total_pages <= PDF_PARALLEL_THRESHOLD:
        return _convert_all(filepath, page_end=total_pages)

    # 大きいPDFはチャンク並列処理
    print(f"  大規模PDF検出（{total_pages}ページ）— 並列処理を使用", file=sys.stderr)
    return _convert_parallel(filepath, total_pages)


def _convert_all(filepath: str, page_end: int | None = None) -> str:
    """pymupdf4llmで全ページ（またはpage_endまで）を一括変換する。"""
    try:
        import pymupdf4llm
        if page_end is not None:
            pages = list(range(0, page_end))
            return pymupdf4llm.to_markdown(filepath, pages=pages)
        return pymupdf4llm.to_markdown(filepath)
    except (ImportError, TypeError):
        return _convert_fitz_fallback(filepath, 0, page_end)


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
    with ThreadPoolExecutor(max_workers=PDF_WORKERS) as executor:
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

