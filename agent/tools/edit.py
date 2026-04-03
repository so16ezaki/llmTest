"""
tools/edit.py — 完全一致文字列置換による安全なファイル編集

LLMに正規表現を書かせず、old_string の完全一致で検索・置換する。
マッチが0件または2件以上の場合はエラーを返し、意図しない編集を防ぐ。
"""

from __future__ import annotations

import os


def edit_file(path: str, old_string: str, new_string: str) -> str:
    """
    ファイル内の old_string を new_string に完全一致置換する。

    Parameters
    ----------
    path:
        編集対象のファイルパス
    old_string:
        置換前の文字列（完全一致、一意である必要がある）
    new_string:
        置換後の文字列
    """
    if not os.path.isfile(path):
        return f"[error] ファイルが見つかりません: {path}"

    if old_string == new_string:
        return "[error] old_string と new_string が同一です。変更はありません。"

    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except OSError as e:
        return f"[error] 読み込みエラー: {e}"

    count = content.count(old_string)

    if count == 0:
        return (
            "[error] 指定された文字列が見つかりません。"
            "read_source で現在の内容を確認してください。"
        )

    if count > 1:
        return (
            f"[error] {count}箇所でマッチしました。"
            "より長い文脈を含めて一意にしてください。"
        )

    new_content = content.replace(old_string, new_string, 1)

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
    except OSError as e:
        return f"[error] 書き込みエラー: {e}"

    # 変更行数を計算
    old_lines = old_string.count("\n") + 1
    new_lines = new_string.count("\n") + 1
    return (
        f"編集完了: {path}\n"
        f"  置換: {old_lines}行 → {new_lines}行"
    )
