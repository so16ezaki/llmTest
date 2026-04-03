"""
readers/ — ドキュメントリーダーパッケージ

get_reader(filepath) でファイル拡張子に対応するリーダーを返す。
"""

from __future__ import annotations

import os


def get_reader(filepath: str):
    """ファイル拡張子からリーダーモジュールを選択して返す。"""
    ext = os.path.splitext(filepath)[1].lower()

    if ext == ".pdf":
        from readers import pdf
        return pdf
    elif ext == ".rst":
        from readers import rst
        return rst
    elif ext in (".md", ".txt"):
        from readers import markdown
        return markdown
    elif ext in (".html", ".htm"):
        from readers import html
        return html
    elif ext in (".docx",):
        from readers import docx
        return docx
    elif ext in (".csv", ".tsv", ".xlsx", ".xls", ".xlsm"):
        from readers import csv
        return csv
    else:
        # ソースコードや未知の形式はcodeリーダーで処理
        from readers import code
        return code


def read_file(filepath: str) -> str:
    """ファイルを適切なリーダーで読み込み、Markdownとして返す。"""
    reader = get_reader(filepath)
    return reader.read(filepath)
