"""
tools/output.py — 出力ツール

write_file を実装する。
"""

from __future__ import annotations

import os


def write_file(path: str, content: str) -> str:
    """
    指定パスにファイルを書き出す。

    Parameters
    ----------
    path:
        書き出し先のファイルパス
    content:
        ファイルの内容
    """
    abs_path = os.path.abspath(path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    try:
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
        size = len(content.encode("utf-8"))
        return f"ファイルを書き出しました: {abs_path} ({size:,} bytes)"
    except OSError as e:
        return f"[error] ファイル書き出し失敗: {e}"
