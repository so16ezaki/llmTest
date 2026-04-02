"""readers/csv.py — CSV/Excel → Markdownテーブル変換（pandas使用）"""

from __future__ import annotations

import os


def read(filepath: str) -> str:
    """CSV/Excel ファイルをMarkdownテーブル形式に変換して返す。"""
    try:
        import pandas as pd
    except ImportError:
        raise ImportError("CSV/Excelの読み込みにはpandasが必要です。\npip install pandas openpyxl")

    ext = os.path.splitext(filepath)[1].lower()
    try:
        if ext in (".xlsx", ".xls", ".xlsm"):
            # 全シートを変換
            xl = pd.ExcelFile(filepath)
            parts = []
            for sheet_name in xl.sheet_names:
                df = xl.parse(sheet_name)
                parts.append(f"## シート: {sheet_name}\n\n{_df_to_md(df)}")
            return "\n\n".join(parts)
        else:
            # CSV/TSV
            sep = "\t" if ext == ".tsv" else ","
            df = pd.read_csv(filepath, sep=sep, encoding="utf-8-sig")
            return _df_to_md(df)
    except Exception as e:
        raise RuntimeError(f"ファイル読み込みエラー: {e}") from e


def _df_to_md(df) -> str:
    """DataFrameをMarkdownテーブルに変換する。"""
    import pandas as pd
    # NaN を空文字に変換
    df = df.fillna("")
    # 最大100行で切り詰め
    if len(df) > 100:
        df = df.head(100)
        truncated = True
    else:
        truncated = False

    lines = []
    # ヘッダー
    headers = [str(c) for c in df.columns]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    # データ行
    for _, row in df.iterrows():
        cells = [str(v).replace("|", "\\|") for v in row]
        lines.append("| " + " | ".join(cells) + " |")

    if truncated:
        lines.append(f"\n*（先頭100行を表示。全{len(df)}行）*")

    return "\n".join(lines)
