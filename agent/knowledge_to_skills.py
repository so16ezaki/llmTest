"""
knowledge_to_skills.py — ナレッジ取り込みCLI

任意形式のドキュメントをスキルファイル（Markdown）に変換し、
skills/{doc_name}/ に保存する。

大規模PDF対応:
  - PDF構造情報（TOC、フォントサイズ）を活用した高品質セクション分割
  - ファイルハッシュによるキャッシュ（変更なしならスキップ）
  - チェックポイントによる中断再開
  - 並列ファイル書き出し
  - 進捗表示

使用法:
    python knowledge_to_skills.py <input_path> [--llm] [--name <doc_name>] [--no-cache] [--force]

    --llm      : OllamaのLLMで構造化（各セクションに要約を付与）
    --name     : スキル名を手動指定（省略時はファイル名から自動生成）
    --no-cache : キャッシュを無視して再処理
    --force    : チェックポイントを無視して最初から処理
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from config import (
    ENABLE_CACHE,
    KNOWLEDGE_MAX_TOKENS,
    PAGES_PER_SECTION_FALLBACK,
    SECTION_MAX_CHARS,
    SECTION_MIN_CHARS,
    SKILLS_CACHE_FILE,
    SKILLS_DIR,
    SKILLS_INDEX,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="ドキュメントをスキルファイルに変換する")
    parser.add_argument("input_path", help="入力ファイルまたはディレクトリ")
    parser.add_argument("--llm", action="store_true", help="LLMで構造化する")
    parser.add_argument("--name", help="スキル名（省略時はファイル名から自動生成）")
    parser.add_argument("--no-cache", action="store_true", help="キャッシュを無視して再処理")
    parser.add_argument("--force", action="store_true", help="チェックポイントを無視して最初から処理")
    args = parser.parse_args()

    input_path = args.input_path
    if not os.path.exists(input_path):
        print(f"[error] パスが見つかりません: {input_path}", file=sys.stderr)
        sys.exit(1)

    use_cache = ENABLE_CACHE and not args.no_cache

    # ディレクトリの場合は再帰的に処理
    if os.path.isdir(input_path):
        files = _collect_files(input_path)
        total = len(files)
        for i, fpath in enumerate(files):
            print(f"\n[{i+1}/{total}] ", end="")
            _process_file(
                fpath,
                doc_name=None,
                use_llm=args.llm,
                use_cache=use_cache,
                force=args.force,
            )
    else:
        _process_file(
            input_path,
            doc_name=args.name,
            use_llm=args.llm,
            use_cache=use_cache,
            force=args.force,
        )

    print("完了。")


def _collect_files(directory: str) -> list[str]:
    """ディレクトリ配下の対応ファイルを収集する。"""
    supported = {
        ".pdf", ".md", ".txt", ".html", ".htm", ".rst",
        ".docx", ".xlsx", ".xls", ".csv", ".tsv",
        ".py", ".js", ".ts", ".c", ".cpp", ".h", ".java", ".go",
    }
    exclude_dirs = {".vscode", ".venv", "venv", "env", ".git"}
    files = []
    for root, dirs, fnames in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        for fname in sorted(fnames):
            if os.path.splitext(fname)[1].lower() in supported:
                files.append(os.path.join(root, fname))
    return files


# ── キャッシュ管理 ────────────────────────────────────────────────


def _load_cache() -> dict:
    """キャッシュファイルを読み込む。"""
    if os.path.isfile(SKILLS_CACHE_FILE):
        try:
            with open(SKILLS_CACHE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"files": {}}


def _save_cache(cache: dict) -> None:
    """キャッシュファイルを保存する。"""
    with open(SKILLS_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _file_hash(filepath: str) -> str:
    """ファイルのSHA256ハッシュを返す。"""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def _is_cached(filepath: str, cache: dict) -> bool:
    """ファイルがキャッシュ済み（変更なし）か判定する。"""
    abs_path = os.path.abspath(filepath)
    entry = cache.get("files", {}).get(abs_path)
    if not entry:
        return False
    current_hash = _file_hash(filepath)
    return entry.get("hash") == current_hash


def _update_cache_entry(filepath: str, doc_name: str, sections_count: int, cache: dict) -> None:
    """キャッシュにファイルエントリを登録する。"""
    abs_path = os.path.abspath(filepath)
    cache.setdefault("files", {})[abs_path] = {
        "hash": _file_hash(filepath),
        "mtime": os.path.getmtime(filepath),
        "doc_name": doc_name,
        "sections_count": sections_count,
        "processed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


# ── チェックポイント管理 ──────────────────────────────────────────


def _checkpoint_path(doc_name: str) -> str:
    return os.path.join(SKILLS_DIR, doc_name, ".checkpoint.json")


def _load_checkpoint(doc_name: str) -> dict | None:
    path = _checkpoint_path(doc_name)
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _save_checkpoint(doc_name: str, data: dict) -> None:
    path = _checkpoint_path(doc_name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def _remove_checkpoint(doc_name: str) -> None:
    path = _checkpoint_path(doc_name)
    if os.path.isfile(path):
        os.remove(path)


# ── トークン数上限 ────────────────────────────────────────────────


def _apply_token_limit(
    sections: list[dict], max_tokens: int
) -> tuple[list[dict], list[dict]]:
    """
    トークン数上限でセクションを切り分ける。

    累計トークン数がmax_tokensを超えたセクション境界で停止する。
    最低1セクションは処理する。

    Returns: (to_process, remaining)
    """
    if max_tokens <= 0:
        return sections, []

    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
    except ImportError:
        # tiktokenがなければ文字数÷4で概算
        enc = None

    total = 0
    for i, section in enumerate(sections):
        content = section.get("content", "")
        if enc:
            tokens = len(enc.encode(content))
        else:
            tokens = len(content) // 4
        if total + tokens > max_tokens and i > 0:
            return sections[:i], sections[i:]
        total += tokens
    return sections, []


# ── カバレッジ管理 ────────────────────────────────────────────────


def _coverage_path(doc_name: str) -> str:
    return os.path.join(SKILLS_DIR, doc_name, ".coverage.json")


def load_coverage(doc_name: str) -> dict | None:
    """カバレッジ情報を読み込む。tools/knowledge.pyからも使用。"""
    path = _coverage_path(doc_name)
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _save_coverage(doc_name: str, data: dict) -> None:
    path = _coverage_path(doc_name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _merge_page_ranges(existing: list[list[int]], new_range: list[int]) -> list[list[int]]:
    """ページ範囲をマージする。[[1,100],[200,300]] + [101,199] → [[1,300]]"""
    all_ranges = existing + [new_range]
    all_ranges.sort(key=lambda r: r[0])
    merged = [all_ranges[0]]
    for r in all_ranges[1:]:
        if r[0] <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], r[1])
        else:
            merged.append(r)
    return merged


def _compute_unprocessed(processed: list[list[int]], total_pages: int) -> list[list[int]]:
    """処理済み範囲から未処理範囲を算出する。"""
    if not processed:
        return [[1, total_pages]]
    unprocessed = []
    prev_end = 0
    for start, end in sorted(processed, key=lambda r: r[0]):
        if start > prev_end + 1:
            unprocessed.append([prev_end + 1, start - 1])
        prev_end = max(prev_end, end)
    if prev_end < total_pages:
        unprocessed.append([prev_end + 1, total_pages])
    return unprocessed


def _estimate_page_range(
    sections: list[dict],
    total_pages: int,
    toc: list | None = None,
) -> list[int]:
    """セクションリストがカバーするページ範囲を推定する。Returns: [start, end]"""
    if not sections:
        return [1, 1]

    # "Pages X-Y" タイトルから直接パース
    first_title = sections[0].get("title", "")
    last_title = sections[-1].get("title", "")
    start_page = 1
    end_page = total_pages

    page_match = re.match(r"Pages?\s+(\d+)", first_title)
    if page_match:
        start_page = int(page_match.group(1))
    page_match = re.search(r"(\d+)$", last_title) if "Page" in last_title else None
    if page_match:
        end_page = int(page_match.group(1))
    elif toc and len(sections) < len(toc):
        # TOCベースで推定: 処理済みセクション数に対応するTOCエントリのページ番号
        processed_toc = [t for t in toc if t[0] <= 2]  # H1/H2相当のみ
        if len(processed_toc) > len(sections):
            end_page = processed_toc[len(sections)][2] - 1
    else:
        # 比例推定
        total_chars = sum(len(s.get("content", "")) for s in sections)
        # 概算: 5000ページPDFの全体文字数を仮定して比率計算は不正確なのでtotal_pagesをそのまま使う
        pass

    return [max(1, start_page), min(total_pages, end_page)]


# ── メイン処理 ────────────────────────────────────────────────────


def _process_file(
    filepath: str,
    doc_name: str | None = None,
    use_llm: bool = False,
    use_cache: bool = True,
    force: bool = False,
) -> None:
    """1ファイルを処理してスキルファイルを生成する。"""
    start_time = time.time()

    # ドキュメント名
    if not doc_name:
        doc_name = _make_doc_name(filepath)

    # キャッシュチェック
    cache = _load_cache() if use_cache else {"files": {}}
    if use_cache and _is_cached(filepath, cache):
        print(f"スキップ（キャッシュ済み）: {filepath}")
        return

    print(f"処理中: {filepath}")
    is_pdf = filepath.lower().endswith(".pdf")

    # チェックポイントからの再開
    checkpoint = None if force else _load_checkpoint(doc_name)
    if checkpoint and checkpoint.get("status") == "sections_ready":
        print(f"  チェックポイントから再開（{checkpoint.get('sections_count', '?')}セクション）")
        sections = checkpoint["sections"]
    else:
        # Markdown変換
        print("  [1/4] ファイル読み込み・変換...", file=sys.stderr)
        from readers import read_file
        try:
            markdown_content = read_file(filepath)
        except Exception as e:
            print(f"  [error] 読み込み失敗: {e}", file=sys.stderr)
            return

        # 章分割
        print("  [2/4] セクション分割...", file=sys.stderr)
        if is_pdf:
            sections = split_sections_pdf(filepath, markdown_content)
        else:
            sections = split_sections(markdown_content)

        sections = merge_small_sections(sections, min_chars=SECTION_MIN_CHARS)
        sections = split_large_sections(sections, max_chars=SECTION_MAX_CHARS)

        # LLM構造化（オプション）
        if use_llm:
            print("  [3/4] LLM構造化...", file=sys.stderr)
            sections = _llm_structure(sections, doc_name)
        else:
            print("  [3/4] LLM構造化...スキップ", file=sys.stderr)

        # チェックポイント保存
        _save_checkpoint(doc_name, {
            "status": "sections_ready",
            "sections": sections,
            "sections_count": len(sections),
            "filepath": filepath,
        })

    # トークン数上限を適用
    all_sections = sections
    sections, remaining = _apply_token_limit(sections, KNOWLEDGE_MAX_TOKENS)
    is_partial = bool(remaining)
    if is_partial:
        print(
            f"  トークン上限到達: {len(sections)}/{len(all_sections)}セクションを処理"
            f"（残り{len(remaining)}セクション）",
            file=sys.stderr,
        )

    # 保存
    print(f"  [4/4] {len(sections)}セクションを書き出し...", file=sys.stderr)
    skill_dir = os.path.join(SKILLS_DIR, doc_name)
    os.makedirs(skill_dir, exist_ok=True)

    saved_files = _write_sections_parallel(sections, skill_dir)

    # カバレッジ情報を構築・保存
    total_pages = 0
    toc = []
    if is_pdf:
        try:
            from readers.pdf import extract_toc, get_page_count
            total_pages = get_page_count(filepath)
            toc = extract_toc(filepath)
        except Exception:
            pass

    processed_range = _estimate_page_range(sections, total_pages, toc) if total_pages else [0, 0]
    processed_pages = [processed_range] if total_pages else []
    unprocessed = _compute_unprocessed(processed_pages, total_pages) if total_pages else []

    coverage = {
        "source_path": os.path.abspath(filepath),
        "total_pages": total_pages,
        "processed_pages": processed_pages,
        "unprocessed_ranges": unprocessed,
        "processed_sections": len(sections),
        "total_sections": len(all_sections),
        "partial": is_partial,
        "toc": toc,
        "processed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    _save_coverage(doc_name, coverage)

    # プロジェクト概要.md を自動生成
    overview_path = _generate_project_summary(doc_name, sections, filepath, coverage)
    if overview_path:
        # saved_files の先頭に概要ファイルを追加
        saved_files.insert(0, (overview_path, f"{doc_name} — 概要", "ドキュメント構成と統計の概要"))
        print(f"  -> 概要ファイルを生成しました: {overview_path}", file=sys.stderr)

    # index.md を更新
    _update_index(doc_name, saved_files, filepath, sections, coverage=coverage)
    print(f"  -> {SKILLS_INDEX} を更新しました")

    # チェックポイント削除・キャッシュ更新
    _remove_checkpoint(doc_name)
    if use_cache:
        _update_cache_entry(filepath, doc_name, len(sections), cache)
        _save_cache(cache)

    elapsed = time.time() - start_time
    partial_note = "（部分処理）" if is_partial else ""
    print(f"  完了{partial_note}（{len(sections)}セクション, {elapsed:.1f}秒）")


def _write_sections_parallel(sections: list[dict], skill_dir: str) -> list[tuple[str, str, str]]:
    """セクションファイルを並列で書き出す。Returns: [(path, title, summary), ...]"""
    def write_one(args):
        i, section = args
        filename = f"section_{i+1:02d}.md"
        if section.get("title"):
            safe_title = re.sub(r"[^\w\u3000-\u9fff]", "_", section["title"])[:40]
            filename = f"{i+1:02d}_{safe_title}.md"
        fpath = os.path.join(skill_dir, filename)
        content = section.get("content", "")
        if section.get("title") and not content.startswith("#"):
            content = f"# {section['title']}\n\n{content}"
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(content)
        summary = _extract_summary(content)
        return (fpath, section.get("title", filename), summary)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(write_one, enumerate(sections)))

    for fpath, title, _ in results:
        print(f"  -> {fpath}")
    return results


def _extract_summary(content: str) -> str:
    """セクション内容から概要（先頭テキスト100文字）を抽出する。"""
    for line in content.splitlines():
        line = line.strip().lstrip("#").strip()
        if line and not line.startswith("```") and not line.startswith("|"):
            return line[:100]
    return ""


# ── PDF構造ベースのセクション分割 ─────────────────────────────────


def split_sections_pdf(filepath: str, markdown: str) -> list[dict]:
    """
    PDF構造情報を使った高品質セクション分割。

    優先順位:
    1. TOC（目次）があればそれに基づいて分割
    2. フォントサイズベースの見出し検出
    3. ページベース分割（フォールバック）
    """
    try:
        from readers.pdf import extract_toc, detect_headings_by_font
    except ImportError:
        return split_sections(markdown)

    # 1. TOC取得を試行
    toc = extract_toc(filepath)
    if toc and len(toc) >= 3:
        print(f"  TOC検出（{len(toc)}項目）— TOCベースで分割", file=sys.stderr)
        sections = _split_by_toc(markdown, toc)
        if sections:
            return sections

    # 2. フォントサイズベースの見出し検出
    headings = detect_headings_by_font(filepath)
    if headings and len(headings) >= 3:
        print(f"  見出し検出（{len(headings)}件）— フォントサイズベースで分割", file=sys.stderr)
        sections = _split_by_detected_headings(markdown, headings)
        if sections:
            return sections

    # 3. ページベース分割
    print("  TOC/見出し検出なし — ページベースで分割", file=sys.stderr)
    sections = _split_by_pages(markdown, PAGES_PER_SECTION_FALLBACK)
    if sections:
        return sections

    # 最終フォールバック: 従来のH1/H2分割
    return split_sections(markdown)


def _split_by_toc(markdown: str, toc: list[tuple[int, str, int]]) -> list[dict]:
    """
    TOC情報に基づいてMarkdownを分割する。

    pymupdf4llmの出力には '## Page N' や '# Title' が含まれる。
    TOCのタイトルをMarkdown内で検索し、その位置で分割する。
    """
    lines = markdown.splitlines(keepends=True)
    total_len = len(markdown)

    # TOCタイトルの出現位置をMarkdown内で検索
    split_points = []
    for level, title, page_num in toc:
        if level > 2:
            continue  # H1/H2相当のみ使用
        clean_title = title.strip()
        if not clean_title:
            continue
        # Markdown内でこのタイトルを探す
        # 完全一致または部分一致で検索
        pattern = re.compile(
            r"^#{1,3}\s+" + re.escape(clean_title),
            re.MULTILINE,
        )
        match = pattern.search(markdown)
        if match:
            split_points.append({
                "pos": match.start(),
                "title": clean_title,
                "level": level,
            })
            continue

        # パターン一致しない場合、タイトル文字列そのものを検索
        idx = markdown.find(clean_title)
        if idx >= 0:
            # 行頭を見つける
            line_start = markdown.rfind("\n", 0, idx)
            line_start = 0 if line_start < 0 else line_start + 1
            split_points.append({
                "pos": line_start,
                "title": clean_title,
                "level": level,
            })

    if not split_points:
        return []

    # 位置でソート・重複除去
    split_points.sort(key=lambda x: x["pos"])
    deduped = [split_points[0]]
    for sp in split_points[1:]:
        if sp["pos"] - deduped[-1]["pos"] > 100:
            deduped.append(sp)
    split_points = deduped

    # セクション生成
    sections = []
    # 先頭のプリアンブル
    if split_points[0]["pos"] > 100:
        preamble = markdown[:split_points[0]["pos"]].strip()
        if preamble:
            sections.append({"title": "概要", "content": preamble})

    for i, sp in enumerate(split_points):
        start = sp["pos"]
        end = split_points[i + 1]["pos"] if i + 1 < len(split_points) else total_len
        content = markdown[start:end].strip()
        if content:
            sections.append({"title": sp["title"], "content": content})

    return sections


def _split_by_detected_headings(markdown: str, headings: list[dict]) -> list[dict]:
    """
    フォントサイズ解析で検出した見出しでMarkdownを分割する。
    """
    # 見出しテキストの出現位置をMarkdown内で検索
    split_points = []
    for heading in headings:
        if heading["level"] > 2:
            continue
        text = heading["text"].strip()
        if not text or len(text) < 2:
            continue
        idx = markdown.find(text)
        if idx >= 0:
            line_start = markdown.rfind("\n", 0, idx)
            line_start = 0 if line_start < 0 else line_start + 1
            split_points.append({
                "pos": line_start,
                "title": text,
                "level": heading["level"],
            })

    if not split_points:
        return []

    # 位置でソート・重複除去
    split_points.sort(key=lambda x: x["pos"])
    deduped = [split_points[0]]
    for sp in split_points[1:]:
        if sp["pos"] - deduped[-1]["pos"] > 100:
            deduped.append(sp)
    split_points = deduped

    total_len = len(markdown)
    sections = []

    if split_points[0]["pos"] > 100:
        preamble = markdown[:split_points[0]["pos"]].strip()
        if preamble:
            sections.append({"title": "概要", "content": preamble})

    for i, sp in enumerate(split_points):
        start = sp["pos"]
        end = split_points[i + 1]["pos"] if i + 1 < len(split_points) else total_len
        content = markdown[start:end].strip()
        if content:
            sections.append({"title": sp["title"], "content": content})

    return sections


def _split_by_pages(markdown: str, pages_per_section: int) -> list[dict]:
    """
    ページマーカー（## Page N）でMarkdownを分割する。

    pymupdf4llmおよびfitzフォールバックは '## Page N' マーカーを出力する。
    """
    page_pattern = re.compile(r"^##\s+Page\s+(\d+)", re.MULTILINE)
    matches = list(page_pattern.finditer(markdown))

    if not matches:
        return []

    # pages_per_section ページごとにグルーピング
    sections = []
    group_start = 0
    group_start_page = 1

    for i, match in enumerate(matches):
        page_num = int(match.group(1))
        # グループ内のページ数がしきい値に達したら分割
        if i > 0 and (page_num - group_start_page) >= pages_per_section:
            content = markdown[group_start:match.start()].strip()
            if content:
                sections.append({
                    "title": f"Pages {group_start_page}-{page_num - 1}",
                    "content": content,
                })
            group_start = match.start()
            group_start_page = page_num

    # 最後のグループ
    content = markdown[group_start:].strip()
    if content:
        last_page = int(matches[-1].group(1)) if matches else group_start_page
        sections.append({
            "title": f"Pages {group_start_page}-{last_page}",
            "content": content,
        })

    return sections


# ── 従来のMarkdownベースセクション分割 ────────────────────────────


def split_sections(markdown: str) -> list[dict]:
    """
    MarkdownをH1/H2境界で章分割する。

    Returns: [{"title": str, "content": str}]
    """
    pattern = re.compile(r"^(#{1,2})\s+(.+)$", re.MULTILINE)
    matches = list(pattern.finditer(markdown))

    if not matches:
        return [{"title": "", "content": markdown}]

    sections = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        title = match.group(2).strip()
        content = markdown[start:end].strip()
        sections.append({"title": title, "content": content})

    if matches[0].start() > 0:
        preamble = markdown[:matches[0].start()].strip()
        if preamble:
            sections.insert(0, {"title": "概要", "content": preamble})

    return sections


def merge_small_sections(
    sections: list[dict], min_chars: int = SECTION_MIN_CHARS
) -> list[dict]:
    """min_chars未満の小セクションを前のセクションに統合する。"""
    if not sections:
        return sections

    merged = [sections[0]]
    for section in sections[1:]:
        content = section.get("content", "")
        if len(content) < min_chars and merged:
            prev = merged[-1]
            prev["content"] = prev["content"] + "\n\n" + content
        else:
            merged.append(section)
    return merged


def split_large_sections(
    sections: list[dict], max_chars: int = SECTION_MAX_CHARS
) -> list[dict]:
    """max_chars超えの大セクションを分割する。"""
    result = []
    for section in sections:
        content = section.get("content", "")
        if len(content) <= max_chars:
            result.append(section)
            continue
        title = section.get("title", "")
        parts = _split_by_paragraphs(content, max_chars)
        for i, part in enumerate(parts):
            result.append({
                "title": f"{title} (part {i+1})" if title else f"part {i+1}",
                "content": part,
            })
    return result


def _split_by_paragraphs(text: str, max_chars: int) -> list[str]:
    """段落境界でテキストを分割する。"""
    paragraphs = re.split(r"\n\n+", text)
    parts = []
    current = []
    current_len = 0

    for para in paragraphs:
        if current_len + len(para) > max_chars and current:
            parts.append("\n\n".join(current))
            current = [para]
            current_len = len(para)
        else:
            current.append(para)
            current_len += len(para)

    if current:
        parts.append("\n\n".join(current))
    return parts


# ── LLM構造化 ─────────────────────────────────────────────────────


def _llm_structure(sections: list[dict], doc_name: str) -> list[dict]:
    """LLMを使って各セクションを構造化する（要約・タグ付与）。"""
    import dify_client

    structured = []
    for section in sections:
        content = section.get("content", "")
        if len(content) < 100:
            structured.append(section)
            continue

        prompt = (
            f"以下のドキュメントセクションを構造化してください。\n"
            f"- タイトルを改善（簡潔に）\n"
            f"- 先頭に1-2行の概要を追加\n"
            f"- 元の内容は保持\n\n"
            f"ドキュメント名: {doc_name}\n"
            f"セクションタイトル: {section.get('title', '（なし）')}\n\n"
            f"---\n{content[:3000]}\n---\n\n"
            f"改善されたMarkdownを返してください（説明なし）:"
        )
        try:
            messages = [{"role": "user", "content": prompt}]
            response = dify_client.chat(messages)
            if response.content:
                structured.append({
                    "title": section.get("title", ""),
                    "content": response.content,
                })
            else:
                structured.append(section)
        except Exception as e:  # noqa: BLE001
            print(f"  [warning] LLM構造化エラー: {e}", file=sys.stderr)
            structured.append(section)

    return structured


# ── プロジェクト概要生成 ──────────────────────────────────────────


def _generate_project_summary(
    doc_name: str,
    sections: list[dict],
    source_path: str,
    coverage: dict | None = None,
) -> str | None:
    """
    セクション情報からプロジェクト概要.mdを生成して保存する。

    Returns
    -------
    保存先のファイルパス。エラー時はNone。
    """
    from config import PROJECT_SUMMARY_FILENAME

    lines = [
        f"# {doc_name} — 概要\n",
        f"*ソース: {source_path}*\n",
    ]

    # ドキュメント統計
    total_chars = sum(len(s.get("content", "")) for s in sections)
    lines.append("## 統計\n")
    lines.append(f"- セクション数: {len(sections)}")
    lines.append(f"- 合計文字数: {total_chars:,}")
    if coverage:
        total_pages = coverage.get("total_pages", 0)
        if total_pages:
            lines.append(f"- 総ページ数: {total_pages}")
            if coverage.get("partial"):
                pp = coverage.get("processed_pages", [])
                if pp:
                    lines.append(f"- 処理済みページ: {pp[0][0]}-{pp[0][1]}")

    # セクション構成（目次として機能）
    lines.append("\n## 構成\n")
    for i, section in enumerate(sections):
        title = section.get("title", f"セクション{i + 1}")
        char_count = len(section.get("content", ""))
        summary = section.get("summary", "")
        summary_text = f" — {summary}" if summary else ""
        lines.append(f"{i + 1}. **{title}** ({char_count:,}字){summary_text}")

    # TOCがあれば追加
    if coverage and coverage.get("toc"):
        lines.append("\n## 原文目次\n")
        for level, title, page in coverage["toc"][:50]:
            indent = "  " * (level - 1)
            lines.append(f"{indent}- {title} (p.{page})")

    content = "\n".join(lines) + "\n"

    # ファイル保存
    skill_dir = os.path.join(SKILLS_DIR, doc_name)
    os.makedirs(skill_dir, exist_ok=True)
    overview_path = os.path.join(skill_dir, PROJECT_SUMMARY_FILENAME)
    try:
        with open(overview_path, "w", encoding="utf-8") as f:
            f.write(content)
        return overview_path
    except OSError as e:
        print(f"  [warning] 概要ファイル生成エラー: {e}", file=sys.stderr)
        return None


# ── ユーティリティ ────────────────────────────────────────────────


def _make_doc_name(filepath: str) -> str:
    """ファイルパスからドキュメント名を生成する。"""
    base = os.path.splitext(os.path.basename(filepath))[0]
    name = re.sub(r"[^\w\u3000-\u9fff\-]", "_", base)
    return name[:50]


def _update_index(
    doc_name: str,
    saved_files: list[tuple[str, str, str]],
    source_path: str,
    sections: list[dict] | None = None,
    coverage: dict | None = None,
) -> None:
    """
    skills/index.md にスキルエントリを追記/更新する。

    各セクションに概要・文字数情報を付与して品質を向上。
    部分処理の場合はカバレッジ情報と未処理TOCを表示。
    """
    existing = ""
    if os.path.isfile(SKILLS_INDEX):
        with open(SKILLS_INDEX, encoding="utf-8") as f:
            existing = f.read()

    # 既存のdoc_nameセクションを除去
    section_pattern = re.compile(
        rf"^### {re.escape(doc_name)}.*?(?=^###|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    existing = section_pattern.sub("", existing).strip()

    # 新しいエントリを追加（概要・サイズ情報付き）
    entries = [f"\n### {doc_name}\n"]
    entries.append(f"*ソース: {source_path}*\n")

    # 部分処理の場合はカバレッジ情報を表示
    if coverage and coverage.get("partial"):
        total_pages = coverage.get("total_pages", 0)
        processed = coverage.get("processed_pages", [])
        if processed and total_pages:
            p_start, p_end = processed[0]
            pct = (p_end - p_start + 1) * 100 // total_pages
            entries.append(
                f"*[部分処理] ページ {p_start}-{p_end} / {total_pages} 処理済み ({pct}%)。"
                f"未処理部分は read_pdf_pages で読み取り可能。*\n"
            )

    for i, (fpath, title, summary) in enumerate(saved_files):
        rel = os.path.relpath(fpath, SKILLS_DIR)
        char_count = 0
        if sections and i < len(sections):
            char_count = len(sections[i].get("content", ""))
        size_info = f" ({char_count:,}字)" if char_count else ""
        summary_text = f" — {summary}" if summary else ""
        entries.append(f"- [{title or rel}]({rel}){size_info}{summary_text}")

    # 未処理部分のTOCを表示
    if coverage and coverage.get("partial"):
        toc = coverage.get("toc", [])
        unprocessed = coverage.get("unprocessed_ranges", [])
        if toc and unprocessed:
            up_start = unprocessed[0][0]
            toc_entries = [t for t in toc if t[0] <= 2 and t[2] >= up_start]
            if toc_entries:
                entries.append("\n*未処理部分のTOC:*")
                for level, title, page in toc_entries[:30]:
                    indent = "  " if level > 1 else ""
                    entries.append(f"{indent}- {title} (p.{page})")

    new_content = existing + "\n" + "\n".join(entries) + "\n"

    if not new_content.startswith("# スキルインデックス"):
        new_content = "# スキルインデックス\n\n" + new_content.lstrip()

    os.makedirs(os.path.dirname(os.path.abspath(SKILLS_INDEX)), exist_ok=True)
    with open(SKILLS_INDEX, "w", encoding="utf-8") as f:
        f.write(new_content)


if __name__ == "__main__":
    main()
