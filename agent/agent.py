"""
agent.py — メインエージェントループ

while(tool_call) パターンの実装。
ツール呼び出しがなくなった時点で自然終了する。
"""

from __future__ import annotations

import json
import sys

import compactor
import dify_client
from config import LLM_BACKEND, MAX_TURNS, TOOL_RESULT_MAX_TOKENS
from system_prompt import build_system_prompt
from tool_registry import TOOL_DEFINITIONS, execute_tool

# ── ツール結果リマインダー ────────────────────────────────────────
# ツール結果に付与する固定テキスト。システムプロンプトより遵守率が高い。
TOOL_REMINDERS: dict[str, str] = {
    "read_skill":
        "\n[reminder] 情報が不十分ならkeyword_searchで詳細を探してください。",
    "keyword_search":
        "\n[reminder] 文脈が必要ならread_skillで全文を読んでください。",
    "todo_write":
        "\n[reminder] TODOリストの次のタスクに進んでください。",
    "scan_project":
        "\n[reminder] 重要なファイルをread_sourceやextract_structureで詳しく調べてください。",
    "extract_structure":
        "\n[reminder] 特定のシンボルを深堀りするにはread_sourceを使ってください。"
        " 静的解析が必要ならstatic_analysisも利用できます。",
    "static_analysis":
        "\n[reminder] 解析結果を解釈し、問題があればread_sourceで該当箇所を確認してください。",
    "list_skills":
        "\n[reminder] 関連するスキルはskill_searchで絞り込み、read_skillで詳細を読んでください。",
    "read_pdf_pages":
        "\n[reminder] 重要な内容を見つけた場合はconvert_pages_to_skillで"
        "スキルファイルに変換すると、今後の検索で見つかりやすくなります。",
    "get_knowledge_coverage":
        "\n[reminder] 未処理ページの内容を確認するにはread_pdf_pagesを使ってください。",
    "convert_pages_to_skill":
        "\n[reminder] 変換が完了しました。keyword_searchやskill_searchで検索可能になりました。",
    "sub_agent":
        "\n[reminder] サブエージェントの結果を評価し、"
        " 不十分な場合は追加の指示で再度委任してください。",
    "read_source":
        "\n[reminder] このファイルの依存関係にも注目してください。"
        " 必要なら関連ファイルもread_sourceで確認してください。",
    "write_file":
        "\n[reminder] ファイルを書き出しました。"
        " 内容に不足がないかread_sourceで確認してください。",
    "edit_file":
        "\n[reminder] 編集が完了しました。"
        " read_sourceで変更結果を確認してください。",
    "generate_skeleton":
        "\n[reminder] スケルトンから全体構造を把握したら、"
        " 重要な関数はread_sourceで実装を確認してください。",
    "dependency_map":
        "\n[reminder] 依存関係を把握したら、"
        " 重要なモジュールをread_sourceやextract_structureで詳しく調べてください。",
}


def _pre_compact_result(result: str) -> str:
    """ツール結果が長すぎる場合、先頭+末尾に切り詰める。"""
    tokens = compactor.count_tokens(result)
    if tokens > TOOL_RESULT_MAX_TOKENS:
        return compactor.truncate_to_tokens(result, TOOL_RESULT_MAX_TOKENS)
    return result


def _format_tool_call(name: str, args: dict) -> str:
    """ツール呼び出しを人間が読みやすい形式にフォーマットする。"""
    import os
    if name == "read_source":
        path = args.get("path", "")
        symbol = args.get("symbol")
        label = os.path.basename(path)
        if symbol:
            return f"[read] {label}::{symbol}"
        return f"[read] {label}"
    if name == "read_skill":
        return f"[read_skill] {args.get('path', '')}"
    if name == "scan_project":
        return f"[scan] {args.get('path', '')}"
    if name == "grep_source":
        return f"[grep] {args.get('pattern', '')}  in {args.get('path', '')}"
    if name == "keyword_search":
        return f"[keyword_search] {args.get('pattern', '')}"
    if name == "static_analysis":
        return f"[static_analysis:{args.get('analysis', '')}] {os.path.basename(args.get('path', ''))}"
    if name == "extract_structure":
        return f"[extract_structure] {os.path.basename(args.get('path', ''))}"
    if name == "write_file":
        return f"[write] {args.get('path', '')}"
    if name == "todo_write":
        count = len(args.get("todos", []))
        return f"[todo_write] {count} items"
    if name == "memory_write":
        return f"[memory_write] key={args.get('key', '')}"
    if name == "read_pdf_pages":
        return f"[read_pdf] {args.get('doc_name', '')} p.{args.get('start_page', '')}-{args.get('end_page', '')}"
    if name == "get_knowledge_coverage":
        return f"[coverage] {args.get('doc_name', 'all')}"
    if name == "convert_pages_to_skill":
        return f"[convert] {args.get('doc_name', '')} p.{args.get('start_page', '')}-{args.get('end_page', '')}"
    # デフォルト: ツール名と引数を短縮表示
    args_str = json.dumps(args, ensure_ascii=False)[:60]
    return f"[tool] {name}({args_str})"


def agent_loop(
    user_input: str,
    verbose: bool = True,
    extra_context: str = "",
) -> str:
    """
    エージェントのメインループ。

    Parameters
    ----------
    user_input:
        ユーザーの入力テキスト
    verbose:
        Trueの場合、各ターンの状況を標準エラー出力に出力する
    extra_context:
        セッション限りの追加コンテキスト。
        システムプロンプトの末尾に注入され、skills/には保存されない。
    """
    # 初期メッセージ構築
    system_prompt = build_system_prompt()
    if extra_context:
        system_prompt = system_prompt + "\n\n" + extra_context
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input},
    ]

    # context.py にメッセージリストの参照を登録（compact_now/get_status用）
    from tools.context import set_context_ref
    set_context_ref(messages, system_prompt)

    # Dify バックエンドの会話ID管理
    conversation_id = ""

    for turn in range(1, MAX_TURNS + 1):
        if verbose:
            ratio = compactor.usage_ratio(messages)
            print(f"[turn {turn}] context: {ratio:.1%}", file=sys.stderr)

        # コンパクション判定
        if compactor.needs_compaction(messages):
            if verbose:
                print("[compaction] triggered", file=sys.stderr)
            messages = compactor.compact(messages, system_prompt)
            # Dify: コンパクション後は新しい会話を開始
            conversation_id = ""

        # LLM呼び出し
        try:
            response = dify_client.chat(
                messages,
                tools=TOOL_DEFINITIONS,
                conversation_id=conversation_id,
            )
        except RuntimeError as e:
            return f"[エラー] LLM呼び出し失敗: {e}"

        # Dify: conversation_id を更新
        if response.conversation_id:
            conversation_id = response.conversation_id

        # ツール呼び出しなし → 最終回答
        if not response.has_tool_calls:
            return response.answer

        # assistantメッセージを追加
        assistant_msg: dict = {"role": "assistant", "content": response.content or ""}
        if LLM_BACKEND == "ollama" and response.tool_calls:
            # Ollama: OpenAI形式の tool_calls を保持
            assistant_msg["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc["args"], ensure_ascii=False),
                    },
                }
                for tc in response.tool_calls
            ]
        messages.append(assistant_msg)

        # ツール実行
        for call in response.tool_calls:
            tool_name = call["name"]
            tool_args = call["args"]
            tool_id = call.get("id", "call_0")

            if verbose:
                print(f"  {_format_tool_call(tool_name, tool_args)}", file=sys.stderr)

            result = execute_tool(tool_name, tool_args)
            result = _pre_compact_result(result)
            reminder = TOOL_REMINDERS.get(tool_name, "")

            if LLM_BACKEND == "ollama":
                # Ollama: OpenAI形式の tool 結果
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "content": result + reminder,
                })
            else:
                # Dify: テキスト形式の tool 結果（name付きで _build_query が整形）
                messages.append({
                    "role": "tool",
                    "name": tool_name,
                    "content": result + reminder,
                })

    return f"[エラー] MAX_TURNS ({MAX_TURNS}) に達しました。タスクが完了しませんでした。"


def main() -> None:
    """CLIエントリーポイント。"""
    import argparse
    import io

    # Windows環境でUTF-8出力を強制
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="ナレッジエージェント")
    parser.add_argument("query", nargs="?", help="質問・指示テキスト")
    parser.add_argument("--quiet", "-q", action="store_true", help="ターン情報を非表示")
    args = parser.parse_args()

    if args.query:
        query = args.query
    else:
        print("質問・指示を入力してください（Ctrl+D で終了）:")
        try:
            query = sys.stdin.read().strip()
        except KeyboardInterrupt:
            return

    if not query:
        print("入力がありません。")
        return

    answer = agent_loop(query, verbose=not args.quiet)
    print("\n" + answer)


if __name__ == "__main__":
    main()
