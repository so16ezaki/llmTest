"""
tool_parser.py — LLM出力からツール呼び出しをパースする

OllamaはOpenAI互換のfunction callingに対応しているため、
通常はdify_client.pyが直接OpenAI形式のtool_callsを返す。

このモジュールはフォールバックとして、
モデルがXMLタグ形式でツール呼び出しを出力した場合のパーサーを提供する。

XMLフォールバック形式（モデルがtool callingに未対応の場合）:
  <tool_call>
    <name>tool_name</name>
    <args>{"key": "value"}</args>
  </tool_call>
"""

from __future__ import annotations

import json
import re


_TOOL_CALL_PATTERN = re.compile(
    r"<tool_call>\s*<name>(.*?)</name>\s*<args>(.*?)</args>\s*</tool_call>",
    re.DOTALL,
)


def parse_xml_tool_calls(text: str) -> list[dict]:
    """
    テキスト中のXMLタグ形式ツール呼び出しをパースする。

    Returns
    -------
    list of {"id": str, "name": str, "args": dict}
    """
    calls = []
    for i, match in enumerate(_TOOL_CALL_PATTERN.finditer(text)):
        name = match.group(1).strip()
        raw_args = match.group(2).strip()
        try:
            args = json.loads(raw_args)
        except json.JSONDecodeError:
            args = {"raw": raw_args}
        calls.append({"id": f"xml_call_{i}", "name": name, "args": args})
    return calls


def strip_tool_calls(text: str) -> str:
    """テキストからXMLツール呼び出しタグを取り除いた本文を返す。"""
    return _TOOL_CALL_PATTERN.sub("", text).strip()
