"""
sub_agent.py — サブエージェント実行エンジン

メインエージェントが sub_agent ツールで委任したタスクを、
役割ごとに制限されたツールセットとシステムプロンプトで実行する。

サブエージェントの種類:
  - explorer: ファイル探索・コード構造調査（読み取り専用）
  - planner:  計画策定・TODO作成・メモリ管理
  - executor: ファイル書き込み・編集実行
"""

from __future__ import annotations

import json
import sys

import dify_client
from agent import TOOL_REMINDERS, _format_call_log, _pre_compact_result
from config import LLM_BACKEND, SUB_AGENT_MAX_TURNS
from tool_registry import TOOL_DEFINITIONS, execute_tool


# ── サブエージェント定義 ──────────────────────────────────────

AGENT_ROLES: dict[str, dict] = {
    "explorer": {
        "system_prompt": (
            "【スコープ指定がある場合】\n"
            "複数のスコープが渡された場合、親子関係にあるパスは最も深い（具体的な）パスのみを\n"
            "scan_project してください。親ディレクトリのスキャンは不要です。\n"
            "[RW] マークが付いたスコープが主たる作業対象です。そこから調査を開始してください。\n\n"
            "【最重要】スコープがプログラムコードのプロジェクトと分かった場合は、"
            "他の調査より先に以下を実行してください。\n"
            "1. generate_skeleton — シグネチャ・Docstringのみ抽出し、全体構造を把握する\n"
            "2. static_analysis — コードを評価・計算する"
            "（analysis='complexity' で複雑度、'issues' で潜在バグ、"
            "'metrics' で統計、'dead_code' で未使用コードを検出できます）\n"
            "read_source でファイルを丸読みする前に必ずこの順で絞り込むこと。\n\n"
            "あなたは探索専門のサブエージェントです。\n"
            "メインエージェントからの指示に従い、ファイル構成・コード構造・"
            "ナレッジの調査を行い、結果を簡潔にレポートしてください。\n"
            "ファイルの書き込みや編集は行わないでください。\n"
            "調査結果は構造化して返してください（箇条書き・見出し付き）。"
        ),
        "allowed_tools": {
            "scan_project", "read_source", "grep_source", "extract_structure",
            "generate_skeleton", "dependency_map",
            "list_skills", "skill_search", "read_skill", "keyword_search",
            "get_knowledge_coverage", "read_pdf_pages", "static_analysis",
        },
        "max_turns": SUB_AGENT_MAX_TURNS,
    },
    "planner": {
        "system_prompt": (
            "あなたは計画策定専門のサブエージェントです。\n"
            "メインエージェントからの調査結果を受け取り、\n"
            "タスクの分解・優先順位付け・TODO作成を行ってください。\n"
            "重要な発見は memory_write で保存してください。\n"
            "計画は具体的で実行可能なステップに分解してください。"
        ),
        "allowed_tools": {
            "todo_write", "memory_write", "memory_read", "get_status",
        },
        "max_turns": 5,
    },
    "executor": {
        "system_prompt": (
            "あなたは実行専門のサブエージェントです。\n"
            "メインエージェントの計画に従い、ファイルの作成・編集を行ってください。\n"
            "編集前に必ず read_source で現在の内容を確認してください。\n"
            "edit_file を使う際は、十分な文脈を含めて一意にマッチさせてください。"
        ),
        "allowed_tools": {
            "write_file", "edit_file", "read_source", "convert_pages_to_skill",
        },
        "max_turns": SUB_AGENT_MAX_TURNS,
    },
}


# ── サブエージェント実行 ──────────────────────────────────────

def run_sub_agent(role: str, task: str) -> str:
    """
    サブエージェントを実行し、結果を返す。

    Parameters
    ----------
    role:
        サブエージェントの役割（explorer / planner / executor）
    task:
        サブエージェントへの指示
    """
    if role not in AGENT_ROLES:
        available = ", ".join(AGENT_ROLES.keys())
        return f"[error] 未知のサブエージェント役割: {role}（利用可能: {available}）"

    config = AGENT_ROLES[role]
    allowed = config["allowed_tools"]
    max_turns = config["max_turns"]

    # ツール定義をフィルタリング
    tools = [
        t for t in TOOL_DEFINITIONS
        if t["function"]["name"] in allowed
    ]

    messages: list[dict] = [
        {"role": "system", "content": config["system_prompt"]},
        {"role": "user", "content": task},
    ]

    # Dify バックエンドの会話ID管理
    conversation_id = ""

    for turn in range(1, max_turns + 1):
        print(
            f"  [sub_agent:{role}] turn {turn}/{max_turns}",
            file=sys.stderr,
        )

        try:
            response = dify_client.chat(
                messages,
                tools=tools,
                conversation_id=conversation_id,
            )
        except RuntimeError as e:
            return f"[error] サブエージェント LLM呼び出し失敗: {e}"

        if response.conversation_id:
            conversation_id = response.conversation_id

        # ツール呼び出しなし → 最終回答
        if not response.has_tool_calls:
            return response.answer

        # assistant メッセージを追加
        assistant_msg: dict = {"role": "assistant", "content": response.content or ""}
        if LLM_BACKEND == "ollama" and response.tool_calls:
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

            # ツール制限チェック
            if tool_name not in allowed:
                result = f"[blocked] {tool_name} はこの役割（{role}）では使用できません。"
            else:
                result = execute_tool(tool_name, tool_args)
                result = _pre_compact_result(result)

            reminder = TOOL_REMINDERS.get(tool_name, "")

            print(_format_call_log(tool_name, tool_args, result, indent="    "), file=sys.stderr)

            if LLM_BACKEND == "ollama":
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "content": result + reminder,
                })
            else:
                messages.append({
                    "role": "tool",
                    "name": tool_name,
                    "content": result + reminder,
                })

    return (
        f"[warning] サブエージェント（{role}）がターン上限（{max_turns}）に達しました。"
        "最新の応答を確認してください。"
    )
