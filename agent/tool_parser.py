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


# ── Ollama向けサニタイズ ─────────────────────────────────────

_THINK_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL)


def strip_think_tags(text: str) -> str:
    """qwen3等の ``<think>`` タグを除去する。"""
    return _THINK_PATTERN.sub("", text).strip()


def _find_json_objects(text: str) -> list[tuple[int, int, object]]:
    """テキスト中の有効なJSONオブジェクト/配列を検出する。

    Returns
    -------
    list of (start_index, end_index, parsed_object)
    """
    decoder = json.JSONDecoder()
    results: list[tuple[int, int, object]] = []
    i = 0
    while i < len(text):
        if text[i] in ("{", "["):
            try:
                obj, end_offset = decoder.raw_decode(text, i)
                results.append((i, i + end_offset, obj))
                i = i + end_offset
            except json.JSONDecodeError:
                i += 1
        else:
            i += 1
    return results


def _is_tool_call_json(obj: object, known_tool_names: set[str]) -> bool:
    """パース済みJSONがツール呼び出し構造に一致するか判定する。"""
    if isinstance(obj, dict):
        # {"name": "tool_name", "arguments"|"args": ...}
        name = obj.get("name")
        if isinstance(name, str) and name in known_tool_names:
            if "arguments" in obj or "args" in obj or "parameters" in obj:
                return True
        # {"function": {"name": ..., "arguments": ...}}
        fn = obj.get("function")
        if isinstance(fn, dict) and fn.get("name") in known_tool_names:
            return True
        # {"function": "tool_name", "arguments": {...}}
        if isinstance(fn, str) and fn in known_tool_names:
            return True
        # {"tool_calls": [...]}
        if "tool_calls" in obj and isinstance(obj["tool_calls"], list):
            return True
    elif isinstance(obj, list) and obj:
        # 配列内の全要素がツール呼び出し風か
        return all(
            isinstance(item, dict)
            and (
                "function" in item
                or (isinstance(item.get("name"), str) and item["name"] in known_tool_names)
            )
            for item in obj
        )
    return False


def _parse_tool_call_from_json(
    obj: object, idx: int, known_tool_names: set[str],
) -> list[dict]:
    """JSONオブジェクトからツール呼び出しリストを生成する。"""
    calls: list[dict] = []

    def _extract_one(d: dict, call_idx: int) -> dict | None:
        fn = d.get("function")
        if isinstance(fn, dict):
            name = fn.get("name", "")
            args = fn.get("arguments") or fn.get("args") or {}
        elif isinstance(fn, str):
            # {"function": "tool_name", "arguments": {...}} 形式
            name = fn
            args = d.get("arguments") or d.get("args") or d.get("parameters") or {}
        else:
            name = d.get("name", "")
            args = d.get("arguments") or d.get("args") or d.get("parameters") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"raw": args}
        if name in known_tool_names:
            return {"id": f"json_call_{idx}_{call_idx}", "name": name, "args": args}
        return None

    if isinstance(obj, dict):
        if "tool_calls" in obj and isinstance(obj["tool_calls"], list):
            for ci, tc in enumerate(obj["tool_calls"]):
                if isinstance(tc, dict):
                    c = _extract_one(tc, ci)
                    if c:
                        calls.append(c)
        else:
            c = _extract_one(obj, 0)
            if c:
                calls.append(c)
    elif isinstance(obj, list):
        for ci, item in enumerate(obj):
            if isinstance(item, dict):
                c = _extract_one(item, ci)
                if c:
                    calls.append(c)
    return calls


def extract_json_tool_calls(
    text: str, known_tool_names: set[str],
) -> tuple[list[dict], str]:
    """テキスト中のJSON形式ツール呼び出しを抽出し、除去したテキストを返す。

    Returns
    -------
    (tool_calls, cleaned_text)
    """
    found = _find_json_objects(text)
    if not found:
        return [], text

    tool_calls: list[dict] = []
    # 後ろから除去してインデックスを壊さない
    removals: list[tuple[int, int]] = []
    for start, end, obj in found:
        if _is_tool_call_json(obj, known_tool_names):
            removals.append((start, end))
            tool_calls.extend(
                _parse_tool_call_from_json(obj, len(tool_calls), known_tool_names)
            )

    # テキストからツール呼び出しJSONを除去
    cleaned = text
    for start, end in reversed(removals):
        cleaned = cleaned[:start] + cleaned[end:]

    # 複数空行を1つに圧縮
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return tool_calls, cleaned


def sanitize_content(
    text: str,
    has_tool_calls: bool,
    known_tool_names: set[str] | None = None,
) -> tuple[str, list[dict]]:
    """Ollamaレスポンスのcontentをサニタイズする。

    Parameters
    ----------
    text : str
        LLMレスポンスのcontentフィールド
    has_tool_calls : bool
        APIレスポンスにtool_callsが既に存在するか
    known_tool_names : set[str] | None
        既知のツール名セット（Noneの場合はJSON抽出をスキップ）

    Returns
    -------
    (cleaned_content, fallback_tool_calls)
        fallback_tool_callsはhas_tool_calls=Falseの場合のみ値を持つ
    """
    if not text:
        return "", []

    # 1. <think> タグ除去
    text = strip_think_tags(text)

    # 2. XML形式ツール呼び出し除去
    xml_calls = parse_xml_tool_calls(text)
    if xml_calls:
        text = strip_tool_calls(text)

    # 3. JSON形式ツール呼び出し除去
    fallback_calls: list[dict] = []
    if known_tool_names:
        json_calls, text = extract_json_tool_calls(text, known_tool_names)
        if not has_tool_calls:
            # APIにtool_callsがなければフォールバックとして使う
            fallback_calls = xml_calls + json_calls
        # has_tool_calls=Trueの場合、JSONは除去するだけ（APIのtool_callsを優先）

    return text, fallback_calls
