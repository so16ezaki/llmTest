"""readers/pdf.py — PDF → Markdown変換（pymupdf4llm使用）"""

from __future__ import annotations


def read(filepath: str) -> str:
    """PDFをMarkdown形式に変換して返す。"""
    try:
        import pymupdf4llm
        return pymupdf4llm.to_markdown(filepath)
    except ImportError:
        # フォールバック: PyMuPDF（fitz）で直接テキスト抽出
        try:
            import fitz  # type: ignore
            doc = fitz.open(filepath)
            pages = []
            for i, page in enumerate(doc):
                text = page.get_text()
                if text.strip():
                    pages.append(f"## Page {i + 1}\n\n{text}")
            return "\n\n".join(pages)
        except ImportError:
            raise ImportError(
                "PDFの読み込みにはpymupdf4llmまたはPyMuPDFが必要です。\n"
                "pip install pymupdf4llm"
            )
