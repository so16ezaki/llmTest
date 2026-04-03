"""
tools/knowledge.py — ナレッジカバレッジ・PDF直接読み取りツール群

部分処理されたドキュメントのカバレッジ確認、未処理ページの直接読み取り、
読み取ったページの正式スキル化を行う。

ツール:
  - get_knowledge_coverage: ドキュメントの処理カバレッジ情報を返す
  - read_pdf_pages: PDFの指定ページ範囲を直接読み取りMarkdownに変換
  - convert_pages_to_skill: 指定ページ範囲をスキルファイルに変換
"""

from __future__ import annotations

import json
import os
import re

from config import PDF_RAW_READ_MAX_PAGES, SKILLS_DIR, SKILLS_INDEX


# ── get_knowledge_coverage ────────────────────────────────────────


def get_knowledge_coverage(doc_name: str | None = None) -> str:
    """
    ドキュメントの処理カバレッジ情報を返す。

    Parameters
    ----------
    doc_name:
        ドキュメント名（省略時は全ドキュメントの概要）
    """
    if doc_name:
        return _coverage_detail(doc_name)
    return _coverage_summary()


def _coverage_summary() -> str:
    """全ドキュメントのカバレッジ概要を返す。"""
    if not os.path.isdir(SKILLS_DIR):
        return "スキルディレクトリが見つかりません。"

    lines = ["## ナレッジカバレッジ概要\n"]
    lines.append("| ドキュメント | 状態 | 処理済み | 全体 | カバレッジ |")
    lines.append("|---|---|---|---|---|")

    found = False
    for entry in sorted(os.scandir(SKILLS_DIR), key=lambda e: e.name):
        if not entry.is_dir():
            continue
        cov = _load_coverage_file(entry.name)
        if cov is None:
            # カバレッジファイルなし = 完全処理済み（旧形式）
            md_count = len([f for f in os.listdir(entry.path)
                           if f.endswith(".md") and f != "index.md"])
            if md_count > 0:
                lines.append(f"| {entry.name} | 完了 | {md_count}ファイル | — | 100% |")
                found = True
            continue

        found = True
        total = cov.get("total_pages", 0)
        partial = cov.get("partial", False)
        if partial and total:
            processed = cov.get("processed_pages", [])
            if processed:
                p_start, p_end = processed[0]
                p_count = p_end - p_start + 1
                pct = p_count * 100 // total
                lines.append(
                    f"| {entry.name} | **部分処理** | p.{p_start}-{p_end} "
                    f"| {total}p | {pct}% |"
                )
            else:
                lines.append(f"| {entry.name} | **部分処理** | — | {total}p | ?% |")
        else:
            sections = cov.get("processed_sections", "?")
            lines.append(f"| {entry.name} | 完了 | {sections}セクション | {total}p | 100% |")

    if not found:
        return "ナレッジが登録されていません。"
    return "\n".join(lines)


def _coverage_detail(doc_name: str) -> str:
    """指定ドキュメントのカバレッジ詳細を返す。"""
    cov = _load_coverage_file(doc_name)
    if cov is None:
        # カバレッジファイルがない場合
        doc_dir = os.path.join(SKILLS_DIR, doc_name)
        if os.path.isdir(doc_dir):
            return f"「{doc_name}」はカバレッジ情報がありません（旧形式で完全処理済みの可能性）。"
        return f"[error] ドキュメント「{doc_name}」が見つかりません。"

    lines = [f"## {doc_name} カバレッジ詳細\n"]
    lines.append(f"- ソース: {cov.get('source_path', '不明')}")
    lines.append(f"- 全ページ数: {cov.get('total_pages', '不明')}")
    lines.append(f"- 処理済みセクション: {cov.get('processed_sections', '?')}"
                 f" / {cov.get('total_sections', '?')}")
    lines.append(f"- 部分処理: {'はい' if cov.get('partial') else 'いいえ'}")
    lines.append(f"- 処理日時: {cov.get('processed_at', '不明')}")

    processed = cov.get("processed_pages", [])
    if processed:
        ranges_str = ", ".join(f"p.{r[0]}-{r[1]}" for r in processed)
        lines.append(f"- 処理済み範囲: {ranges_str}")

    unprocessed = cov.get("unprocessed_ranges", [])
    if unprocessed:
        ranges_str = ", ".join(f"p.{r[0]}-{r[1]}" for r in unprocessed)
        lines.append(f"- **未処理範囲: {ranges_str}**")

    # 未処理部分のTOC
    toc = cov.get("toc", [])
    if toc and unprocessed:
        up_start = unprocessed[0][0]
        unprocessed_toc = [t for t in toc if t[0] <= 2 and t[2] >= up_start]
        if unprocessed_toc:
            lines.append("\n### 未処理部分のTOC\n")
            lines.append("read_pdf_pages で以下のページ範囲を読み取れます:\n")
            for level, title, page in unprocessed_toc[:50]:
                indent = "  " if level > 1 else ""
                lines.append(f"{indent}- {title} (p.{page})")

    return "\n".join(lines)


# ── read_pdf_pages ────────────────────────────────────────────────


def read_pdf_pages(
    doc_name: str,
    start_page: int,
    end_page: int,
) -> str:
    """
    PDFの指定ページ範囲を直接読み取り、Markdownに変換して返す。

    Parameters
    ----------
    doc_name:
        ドキュメント名（skills/配下のディレクトリ名）
    start_page:
        開始ページ番号（1始まり）
    end_page:
        終了ページ番号（1始まり、この番号を含む）
    """
    # カバレッジからソースパスを取得
    cov = _load_coverage_file(doc_name)
    if cov is None:
        return f"[error] 「{doc_name}」のカバレッジ情報が見つかりません。"

    source_path = cov.get("source_path", "")
    if not source_path or not os.path.isfile(source_path):
        return f"[error] ソースPDFが見つかりません: {source_path}"

    # ページ範囲の検証
    total_pages = cov.get("total_pages", 0)
    if total_pages:
        start_page = max(1, start_page)
        end_page = min(total_pages, end_page)

    page_count = end_page - start_page + 1
    if page_count <= 0:
        return f"[error] 無効なページ範囲: {start_page}-{end_page}"

    if page_count > PDF_RAW_READ_MAX_PAGES:
        return (
            f"[error] ページ範囲が大きすぎます（{page_count}ページ）。"
            f"1回の読み取りは最大{PDF_RAW_READ_MAX_PAGES}ページです。"
            f"範囲を絞って再度お試しください。"
        )

    # PDF→Markdown変換
    md = _convert_pdf_range(source_path, start_page, end_page)
    header = (
        f"# {doc_name} — ページ {start_page}-{end_page}\n"
        f"*ソース: {source_path}*\n\n"
    )
    return header + md


def _convert_pdf_range(filepath: str, start_page: int, end_page: int) -> str:
    """PDFの指定ページ範囲をMarkdownに変換する。"""
    # pymupdf4llm の pages パラメータを使用（0-based index）
    try:
        import pymupdf4llm
        pages = list(range(start_page - 1, end_page))
        return pymupdf4llm.to_markdown(filepath, pages=pages)
    except (ImportError, TypeError):
        pass

    # フォールバック: fitz直接テキスト抽出
    try:
        import fitz
        doc = fitz.open(filepath)
        result = []
        for i in range(start_page - 1, min(end_page, len(doc))):
            page = doc[i]
            text = page.get_text()
            if text.strip():
                result.append(f"## Page {i + 1}\n\n{text}")
        doc.close()
        return "\n\n".join(result)
    except ImportError:
        return "[error] PDFの読み込みにはPyMuPDFが必要です。pip install pymupdf"


# ── convert_pages_to_skill ────────────────────────────────────────


def convert_pages_to_skill(
    doc_name: str,
    start_page: int,
    end_page: int,
) -> str:
    """
    PDFの指定ページ範囲を正式なスキルファイルに変換する。

    Parameters
    ----------
    doc_name:
        ドキュメント名
    start_page:
        開始ページ番号（1始まり）
    end_page:
        終了ページ番号（1始まり、この番号を含む）
    """
    # カバレッジからソースパスを取得
    cov = _load_coverage_file(doc_name)
    if cov is None:
        return f"[error] 「{doc_name}」のカバレッジ情報が見つかりません。"

    source_path = cov.get("source_path", "")
    if not source_path or not os.path.isfile(source_path):
        return f"[error] ソースPDFが見つかりません: {source_path}"

    total_pages = cov.get("total_pages", 0)
    if total_pages:
        start_page = max(1, start_page)
        end_page = min(total_pages, end_page)

    page_count = end_page - start_page + 1
    if page_count <= 0:
        return f"[error] 無効なページ範囲: {start_page}-{end_page}"

    # PDF→Markdown変換
    md = _convert_pdf_range(source_path, start_page, end_page)

    # セクション分割
    from knowledge_to_skills import (
        merge_small_sections,
        split_large_sections,
        split_sections,
    )
    from config import SECTION_MAX_CHARS, SECTION_MIN_CHARS

    sections = split_sections(md)
    sections = merge_small_sections(sections, min_chars=SECTION_MIN_CHARS)
    sections = split_large_sections(sections, max_chars=SECTION_MAX_CHARS)

    # スキルファイルに保存（既存ファイルと衝突しないファイル名）
    skill_dir = os.path.join(SKILLS_DIR, doc_name)
    os.makedirs(skill_dir, exist_ok=True)

    # 既存ファイル数を取得して連番を決定
    existing_files = [f for f in os.listdir(skill_dir) if f.endswith(".md")]
    next_num = len(existing_files) + 1

    saved_files = []
    for i, section in enumerate(sections):
        num = next_num + i
        title = section.get("title", "")
        if title:
            safe_title = re.sub(r"[^\w\u3000-\u9fff]", "_", title)[:40]
            filename = f"{num:02d}_p{start_page}_{end_page}_{safe_title}.md"
        else:
            filename = f"{num:02d}_p{start_page}_{end_page}.md"
        fpath = os.path.join(skill_dir, filename)

        content = section.get("content", "")
        if title and not content.startswith("#"):
            content = f"# {title}\n\n{content}"
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(content)
        saved_files.append(fpath)

    # カバレッジを更新
    from knowledge_to_skills import _merge_page_ranges, _compute_unprocessed, _save_coverage

    new_range = [start_page, end_page]
    processed = cov.get("processed_pages", [])
    processed = _merge_page_ranges(processed, new_range)
    unprocessed = _compute_unprocessed(processed, total_pages) if total_pages else []

    cov["processed_pages"] = processed
    cov["unprocessed_ranges"] = unprocessed
    cov["processed_sections"] = cov.get("processed_sections", 0) + len(sections)
    cov["partial"] = bool(unprocessed)

    _save_coverage(doc_name, cov)

    # index.md に追記（既存エントリを保持して追加分だけ追記）
    _append_to_index(doc_name, saved_files, start_page, end_page)

    return (
        f"ページ {start_page}-{end_page} をスキル化しました。\n"
        f"  - {len(sections)}セクション生成\n"
        f"  - 保存先: {skill_dir}/\n"
        f"  - カバレッジ更新済み"
    )


def _append_to_index(
    doc_name: str,
    saved_files: list[str],
    start_page: int,
    end_page: int,
) -> None:
    """index.mdの既存doc_nameセクションに追記する。"""
    if not os.path.isfile(SKILLS_INDEX):
        return

    with open(SKILLS_INDEX, encoding="utf-8") as f:
        content = f.read()

    # doc_nameセクションの末尾を見つけて追記
    pattern = re.compile(
        rf"(^### {re.escape(doc_name)}.*?)(?=^###|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(content)
    if not match:
        return

    # 追記エントリ
    new_entries = [f"\n*[追加スキル化] ページ {start_page}-{end_page}:*"]
    for fpath in saved_files:
        rel = os.path.relpath(fpath, SKILLS_DIR)
        name = os.path.basename(fpath)
        new_entries.append(f"- [{name}]({rel})")

    insert_pos = match.end()
    new_content = content[:insert_pos] + "\n".join(new_entries) + "\n" + content[insert_pos:]

    with open(SKILLS_INDEX, "w", encoding="utf-8") as f:
        f.write(new_content)


# ── ユーティリティ ────────────────────────────────────────────────


def _load_coverage_file(doc_name: str) -> dict | None:
    """カバレッジファイルを読み込む。knowledge_to_skills.load_coverageのラッパー。"""
    try:
        from knowledge_to_skills import load_coverage
        return load_coverage(doc_name)
    except ImportError:
        # フォールバック: 直接読み込み
        path = os.path.join(SKILLS_DIR, doc_name, ".coverage.json")
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return None
