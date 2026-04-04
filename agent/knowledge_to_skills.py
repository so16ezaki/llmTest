"""
knowledge_to_skills.py — ナレッジ取り込みCLI

任意形式のドキュメントをスキルファイル（Markdown）に変換し、
skills/{doc_name}/ に保存する。

使用法:
    python knowledge_to_skills.py <input_path> [--name <doc_name>]
"""

from __future__ import annotations

import argparse
import os
import re
import sys

from config import SKILLS_DIR, SKILLS_INDEX

# GUI進捗コールバック（GUIから設定される。Noneなら無効）
_on_progress = None


def _emit_progress(event: str, **kwargs) -> None:
    """GUI進捗コールバックを安全に呼び出す。"""
    if _on_progress is not None:
        try:
            _on_progress(event, **kwargs)
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="ドキュメントをスキルファイルに変換する")
    parser.add_argument("input_path", help="入力ファイルまたはディレクトリ")
    parser.add_argument("--name", help="スキル名（省略時はファイル名から自動生成）")
    args = parser.parse_args()

    input_path = args.input_path
    if not os.path.exists(input_path):
        print(f"[error] パスが見つかりません: {input_path}", file=sys.stderr)
        sys.exit(1)

    if os.path.isdir(input_path):
        files = _collect_files(input_path)
        total = len(files)
        for i, fpath in enumerate(files):
            print(f"\n[{i+1}/{total}] ", end="")
            _process_file(fpath, doc_name=None)
    else:
        _process_file(input_path, doc_name=args.name)

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


def _process_file(filepath: str, doc_name: str | None = None) -> None:
    """1ファイルを処理してスキルファイルを生成する。"""
    if not doc_name:
        doc_name = _make_doc_name(filepath)

    print(f"処理中: {filepath}")

    # ファイル読み込み・変換
    print("  [1/2] ファイル読み込み・変換...", file=sys.stderr)
    from readers import read_file
    try:
        markdown_content = read_file(filepath)
    except Exception as e:
        print(f"  [error] 読み込み失敗: {e}", file=sys.stderr)
        return

    # ファイル書き出し
    print("  [2/2] ファイル書き出し...", file=sys.stderr)
    skill_dir = os.path.join(SKILLS_DIR, doc_name)
    os.makedirs(skill_dir, exist_ok=True)
    fpath = os.path.join(skill_dir, f"{doc_name}.md")
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(markdown_content)
    summary = _extract_summary(markdown_content)
    saved_files = [(fpath, doc_name, summary)]

    _update_index(doc_name, saved_files, filepath)
    print(f"  -> {SKILLS_INDEX} を更新しました")
    print("  完了")



def _extract_summary(content: str) -> str:
    """セクション内容から概要（先頭テキスト100文字）を抽出する。"""
    for line in content.splitlines():
        line = line.strip().lstrip("#").strip()
        if line and not line.startswith("```") and not line.startswith("|"):
            return line[:100]
    return ""


def _make_doc_name(filepath: str) -> str:
    """ファイルパスからドキュメント名を生成する。"""
    base = os.path.splitext(os.path.basename(filepath))[0]
    name = re.sub(r"[^\w\u3000-\u9fff\-]", "_", base)
    return name[:50]


def _update_index(
    doc_name: str,
    saved_files: list[tuple[str, str, str]],
    source_path: str,
) -> None:
    """skills/index.md にスキルエントリを追記/更新する。"""
    existing = ""
    if os.path.isfile(SKILLS_INDEX):
        with open(SKILLS_INDEX, encoding="utf-8") as f:
            existing = f.read()

    section_pattern = re.compile(
        rf"^### {re.escape(doc_name)}.*?(?=^###|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    existing = section_pattern.sub("", existing).strip()

    entries = [f"\n### {doc_name}\n"]
    entries.append(f"*ソース: {source_path}*\n")
    for fpath, title, summary in saved_files:
        rel = os.path.relpath(fpath, SKILLS_DIR)
        summary_text = f" — {summary}" if summary else ""
        entries.append(f"- [{title or rel}]({rel}){summary_text}")

    new_content = existing + "\n" + "\n".join(entries) + "\n"
    if not new_content.startswith("# スキルインデックス"):
        new_content = "# スキルインデックス\n\n" + new_content.lstrip()

    os.makedirs(os.path.dirname(os.path.abspath(SKILLS_INDEX)), exist_ok=True)
    with open(SKILLS_INDEX, "w", encoding="utf-8") as f:
        f.write(new_content)


if __name__ == "__main__":
    main()
