"""
knowledge_to_skills.py — ナレッジ取り込みCLI

任意形式のドキュメントをスキルファイル（Markdown）に変換し、
skills/{doc_name}/ に保存する。

使用法:
    python knowledge_to_skills.py <input_path> [--llm] [--name <doc_name>]

    --llm   : OllamaのLLMで構造化（各セクションに要約を付与）
    --name  : スキル名を手動指定（省略時はファイル名から自動生成）
"""

from __future__ import annotations

import argparse
import os
import re
import sys

from config import SECTION_MAX_CHARS, SECTION_MIN_CHARS, SKILLS_DIR, SKILLS_INDEX


def main() -> None:
    parser = argparse.ArgumentParser(description="ドキュメントをスキルファイルに変換する")
    parser.add_argument("input_path", help="入力ファイルまたはディレクトリ")
    parser.add_argument("--llm", action="store_true", help="LLMで構造化する")
    parser.add_argument("--name", help="スキル名（省略時はファイル名から自動生成）")
    args = parser.parse_args()

    input_path = args.input_path
    if not os.path.exists(input_path):
        print(f"[error] パスが見つかりません: {input_path}", file=sys.stderr)
        sys.exit(1)

    # ディレクトリの場合は再帰的に処理
    if os.path.isdir(input_path):
        files = _collect_files(input_path)
        for fpath in files:
            _process_file(fpath, doc_name=None, use_llm=args.llm)
    else:
        _process_file(input_path, doc_name=args.name, use_llm=args.llm)

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
        # 除外ディレクトリを再帰対象から外す
        dirs[:] = [d for d in dirs if d not in exclude_dirs]

        for fname in sorted(fnames):
            if os.path.splitext(fname)[1].lower() in supported:
                files.append(os.path.join(root, fname))
    return files


def _process_file(
    filepath: str,
    doc_name: str | None = None,
    use_llm: bool = False,
) -> None:
    """1ファイルを処理してスキルファイルを生成する。"""
    print(f"処理中: {filepath}")

    # Markdown変換
    from readers import read_file
    try:
        markdown_content = read_file(filepath)
    except Exception as e:
        print(f"  [error] 読み込み失敗: {e}", file=sys.stderr)
        return

    # ドキュメント名
    if not doc_name:
        doc_name = _make_doc_name(filepath)

    # 章分割
    sections = split_sections(markdown_content)
    sections = merge_small_sections(sections, min_chars=SECTION_MIN_CHARS)
    sections = split_large_sections(sections, max_chars=SECTION_MAX_CHARS)

    # LLM構造化（オプション）
    if use_llm:
        sections = _llm_structure(sections, doc_name)

    # 保存
    skill_dir = os.path.join(SKILLS_DIR, doc_name)
    os.makedirs(skill_dir, exist_ok=True)

    saved_files = []
    for i, section in enumerate(sections):
        filename = f"section_{i+1:02d}.md"
        if section.get("title"):
            safe_title = re.sub(r"[^\w\u3000-\u9fff]", "_", section["title"])[:40]
            filename = f"{i+1:02d}_{safe_title}.md"
        fpath = os.path.join(skill_dir, filename)
        with open(fpath, "w", encoding="utf-8") as f:
            content = section.get("content", "")
            if section.get("title") and not content.startswith("#"):
                content = f"# {section['title']}\n\n{content}"
            f.write(content)
        saved_files.append((fpath, section.get("title", filename)))
        print(f"  -> {fpath}")

    # index.md を更新
    _update_index(doc_name, saved_files, filepath)
    print(f"  -> {SKILLS_INDEX} を更新しました")


def _make_doc_name(filepath: str) -> str:
    """ファイルパスからドキュメント名を生成する。"""
    base = os.path.splitext(os.path.basename(filepath))[0]
    # 英数字・日本語・ハイフン・アンダースコアのみ残す
    name = re.sub(r"[^\w\u3000-\u9fff\-]", "_", base)
    return name[:50]


def split_sections(markdown: str) -> list[dict]:
    """
    MarkdownをH1/H2境界で章分割する。

    Returns: [{"title": str, "content": str}]
    """
    # H1/H2 の区切りを検出
    pattern = re.compile(r"^(#{1,2})\s+(.+)$", re.MULTILINE)
    matches = list(pattern.finditer(markdown))

    if not matches:
        # 見出しがない場合は全体を1セクションとして返す
        return [{"title": "", "content": markdown}]

    sections = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        title = match.group(2).strip()
        content = markdown[start:end].strip()
        sections.append({"title": title, "content": content})

    # 先頭の見出し前にコンテンツがある場合
    if matches[0].start() > 0:
        preamble = markdown[:matches[0].start()].strip()
        if preamble:
            sections.insert(0, {"title": "概要", "content": preamble})

    return sections


def merge_small_sections(
    sections: list[dict], min_chars: int = SECTION_MIN_CHARS
) -> list[dict]:
    """
    min_chars未満の小セクションを前のセクションに統合する。
    """
    if not sections:
        return sections

    merged = [sections[0]]
    for section in sections[1:]:
        content = section.get("content", "")
        if len(content) < min_chars and merged:
            # 前のセクションに追記
            prev = merged[-1]
            prev["content"] = prev["content"] + "\n\n" + content
        else:
            merged.append(section)
    return merged


def split_large_sections(
    sections: list[dict], max_chars: int = SECTION_MAX_CHARS
) -> list[dict]:
    """
    max_chars超えの大セクションを分割する。
    """
    result = []
    for section in sections:
        content = section.get("content", "")
        if len(content) <= max_chars:
            result.append(section)
            continue

        # 段落境界で分割
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


def _llm_structure(sections: list[dict], doc_name: str) -> list[dict]:
    """
    Ollama LLMを使って各セクションを構造化する（要約・タグ付与）。
    """
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


def _update_index(
    doc_name: str,
    saved_files: list[tuple[str, str]],
    source_path: str,
) -> None:
    """skills/index.md にスキルエントリを追記/更新する。"""
    # 既存のindex.mdを読み込む
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

    # 新しいエントリを追加
    entries = [f"\n### {doc_name}\n"]
    entries.append(f"*ソース: {source_path}*\n")
    for fpath, title in saved_files:
        rel = os.path.relpath(fpath, SKILLS_DIR)
        entries.append(f"- [{title or rel}]({rel})")

    new_content = existing + "\n" + "\n".join(entries) + "\n"

    # index.mdのヘッダーがなければ追加
    if not new_content.startswith("# スキルインデックス"):
        new_content = "# スキルインデックス\n\n" + new_content.lstrip()

    os.makedirs(os.path.dirname(os.path.abspath(SKILLS_INDEX)), exist_ok=True)
    with open(SKILLS_INDEX, "w", encoding="utf-8") as f:
        f.write(new_content)


if __name__ == "__main__":
    main()
