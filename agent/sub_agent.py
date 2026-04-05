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
from config import LLM_BACKEND, PIPELINE_VERIFY_RETRIES, SUB_AGENT_MAX_TURNS
from tool_registry import TOOL_DEFINITIONS, execute_tool


# ── サブエージェント定義 ──────────────────────────────────────

AGENT_ROLES: dict[str, dict] = {
    "explorer": {
        "system_prompt": (
            "【絶対パス必須】すべてのツールには絶対パスを使用してください。"
            " '.' や相対パスは使用禁止です。スコープに含まれるパスをそのまま使用してください。\n\n"
            "【スコープ指定がある場合】\n"
            "複数のスコープが渡された場合、親子関係にあるパスは最も深い（具体的な）パスのみを\n"
            "scan_project してください。親ディレクトリのスキャンは不要です。\n"
            "[RW] マークが付いたスコープが主たる作業対象です。そこから調査を開始してください。\n\n"
            "【最重要】スコープがプログラムコードのプロジェクトと分かった場合は、"
            "他の調査より先に以下を実行してください（省略禁止）。\n"
            "1. scan_project(path=<スコープパス>, analyze=False) — ファイル構成のみ取得する。"
            "これが最初の必須ステップです。\n"
            "2. タスクの目的に応じて、必要な静的解析のみ個別に実行してください（全量実行は不要）。\n"
            "   - バグ・品質調査: static_analysis(analysis='issues') + 'complexity'\n"
            "   - モジュール依存調査: static_analysis(analysis='dependency_graph')\n"
            "   - 全解析が本当に必要な場合のみ: static_analysis(analysis='all')\n"
            "   ※ analyze=True は static_analysis('all') を自動実行するため、原則使用しないこと。\n"
            "【ライフサイクル・フロー調査の場合は以下の2つを必ず両方実行すること（片方だけでは不十分）】\n"
            "   a. static_analysis(path=<スコープパス>, analysis='call_graph') — 関数呼び出し全体像\n"
            "   b. static_analysis(path=<メインエントリポイントのファイルパス>, analysis='control_flow')"
            " — ループ・分岐・終了条件の詳細\n"
            "3. 必要に応じて generate_skeleton <個別ファイルパス> — 特定ファイルの深堀り時のみ"
            "（ディレクトリ不可。必ずファイルパスを指定）\n"
            "read_source でファイルを丸読みする前に必ずこの手順で絞り込むこと。\n\n"
            "あなたは探索専門のサブエージェントです。\n"
            "メインエージェントからの指示に従い、ファイル構成・コード構造・"
            "ナレッジの調査を行い、結果を簡潔にレポートしてください。\n"
            "ファイルの書き込みや編集は行わないでください。\n"
            "調査結果は構造化して返してください（箇条書き・見出し付き）。\n\n"
            "【調査完了後】コードプロジェクトを調査した場合は、調査結果をメインエージェントに"
            "返す前に memory_write(key='project_summary') で以下を保存してください:\n"
            "  - プロジェクト概要・ファイル構成の役割\n"
            "  - 主要な発見（バグ・複雑度の高い箇所・依存関係等）\n"
            "  - 次に調査・対応すべき項目\n"
            "これにより次のセッションで同じ調査を繰り返さずに済みます。"
        ),
        "allowed_tools": {
            "scan_project", "read_source", "grep_source", "extract_structure",
            "generate_skeleton", "dependency_map",
            "list_skills", "skill_search", "read_skill", "keyword_search",
            "get_knowledge_coverage", "read_pdf_pages", "static_analysis",
            "memory_write",
        },
        "max_turns": SUB_AGENT_MAX_TURNS,
    },
    "planner": {
        "system_prompt": (
            "あなたは計画策定専門のサブエージェントです。\n"
            "メインエージェントから渡された調査結果をもとに、\n"
            "タスクの分解・優先順位付け・TODO作成を行ってください。\n\n"
            "【最重要】元のタスク目的を必ず最優先にしてください。\n"
            "探索中に別の問題（バグ・品質課題等）が見つかっても、それらはTODOに含めないでください。\n"
            "TODOはユーザーが依頼したタスクの実行ステップのみを記述してください。\n\n"
            "【必須アクション】\n"
            "必ず最初に todo_write を呼び出してTODOリストを作成してください。\n"
            "todo_write なしでタスクを終了することは禁止です。\n\n"
            "【TODOの粒度】\n"
            "- 各タスクは1ステップで実行可能な単位に分解してください\n"
            "- ファイルの作成/編集はファイルパスを明示してください\n"
            "- 依存関係がある場合は priority で順序を制御してください\n\n"
            "【重要な発見の保存】\n"
            "設計方針・制約・注意点など、次のセッションでも重要な情報は\n"
            "memory_write で保存してください。"
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
            "edit_file を使う際は、十分な文脈を含めて一意にマッチさせてください。\n"
            "各タスクを完了したら、必ず todo_write でそのアイテムのステータスを"
            " 'in_progress' または 'done' に更新してください。\n\n"
            "【エラー処理】\n"
            "write_file または edit_file のレスポンスが '[sandbox]' で始まる場合、"
            "ファイルの作成・編集はサンドボックスによりブロックされています。\n"
            "この場合はタスクを完了にせず、'[sandbox] パーミッションエラー: スコープが読み取り専用です'"
            " と報告して終了してください。絶対にリトライしないでください。"
        ),
        "allowed_tools": {
            "write_file", "edit_file", "read_source", "convert_pages_to_skill",
            "todo_write",
        },
        "max_turns": SUB_AGENT_MAX_TURNS,
    },
    "verifier": {
        "system_prompt": (
            "あなたは検証専門のサブエージェントです。\n"
            "executor が実行したタスクの結果を確認し、完了レポートを返してください。\n\n"
            "【確認項目】\n"
            "1. 期待したファイルが正しいパスに存在するか（read_source で内容も確認）\n"
            "2. ファイルの内容が元のタスクを満たしているか\n"
            "3. TODOリストの全アイテムが 'done' になっているか\n\n"
            "問題がある場合は具体的に何が不足しているかを報告してください。\n"
            "問題がない場合は '✓ 検証完了' と報告してください。"
        ),
        "allowed_tools": {
            "scan_project", "read_source", "grep_source", "static_analysis",
            "memory_read", "get_status",
        },
        "max_turns": 5,
    },
    "reporter": {
        "system_prompt": (
            "あなたはレポート生成専門のサブエージェントです。\n"
            "渡された探索結果をもとに、ユーザーが要求した図・レポート・分析を Markdown 形式で生成してください。\n\n"
            "【出力形式の選択】\n"
            "- ライフサイクル・フロー図: Mermaid graph TD または sequenceDiagram\n"
            "- 依存関係図: Mermaid graph\n"
            "- 品質・複雑度レポート: Markdown テーブル + 箇条書き\n"
            "- コード構造一覧: 箇条書き + ファイル:行番号\n\n"
            "【重要】ツールを呼ばずに、受け取った情報から直接出力を生成してください。\n"
            "情報が不足している場合は具体的に何が不足しているかを明記してください。\n"
            "出力は完結した Markdown であること。見出し・コードブロックを適切に使うこと。"
        ),
        "allowed_tools": set(),
        "max_turns": 2,
    },
}


# ── パイプライン実行 ──────────────────────────────────────────
# explorer→planner→executor→verifier の順序をPythonで強制する。
# LLMにフロー制御を任せない。

def run_pipeline(task: str, scope_path: str = "", scope_mode: str = "R") -> str:
    """
    explorer → planner → [executor → verifier] のパイプラインを実行する。

    Parameters
    ----------
    task:
        ユーザーの元の要求
    scope_path:
        スコープのパス（例: C:/Users/foo/project）
    scope_mode:
        "R" = 読み取り専用（executor を実行しない）
        "RW" = 読み書き可（executor → verifier まで実行する）
    """
    results: dict[str, str] = {}

    # Phase 1: Explorer
    explorer_task = task
    if scope_path:
        explorer_task = f"{task}\n\nスコープ: {scope_path}"
    print("[pipeline] Phase 1: explorer", file=sys.stderr)
    results["explorer"] = run_sub_agent("explorer", explorer_task)

    # Phase 2: Reporter（R スコープ）/ Planner（RW スコープ）
    if scope_mode == "R":
        reporter_task = (
            f"元のタスク: {task}\n\n"
            f"探索結果:\n{results['explorer']}\n\n"
            "上記の探索結果をもとに、元のタスクが求める図・レポートを生成してください。"
        )
        print("[pipeline] Phase 2: reporter", file=sys.stderr)
        results["reporter"] = run_sub_agent("reporter", reporter_task)

    # Phase 3 & 4: Planner → Executor → Verifier（RW スコープのみ、失敗時リトライあり）
    if scope_mode == "RW":
        planner_task = (
            f"元のタスク（最優先）: {task}\n\n"
            f"探索結果:\n{results['explorer']}\n\n"
            "上記の元のタスクを実現するためのTODOのみを作成してください。"
            "探索で発見した副次的な問題はTODOに含めないでください。"
        )
        print("[pipeline] Phase 3: planner", file=sys.stderr)
        results["planner"] = run_sub_agent("planner", planner_task)
        executor_task = (
            f"元のタスク: {task}\n\n"
            f"実行計画:\n{results['planner']}\n\n"
            "上記の計画に従いファイルを作成・編集してください。"
            "各タスク完了後に todo_write でステータスを更新してください。"
        )

        for attempt in range(1, PIPELINE_VERIFY_RETRIES + 1):
            print(f"[pipeline] Phase 4: executor (attempt {attempt}/{PIPELINE_VERIFY_RETRIES})", file=sys.stderr)
            executor_result = run_sub_agent("executor", executor_task)
            results["executor"] = executor_result

            verifier_task = (
                f"元のタスク: {task}\n\n"
                f"実行結果:\n{executor_result}\n\n"
                "実行が正しく完了しているか確認してください。"
            )
            print(f"[pipeline] Phase 5: verifier (attempt {attempt}/{PIPELINE_VERIFY_RETRIES})", file=sys.stderr)
            verifier_result = run_sub_agent("verifier", verifier_task)
            results["verifier"] = verifier_result

            if "✓ 検証完了" in verifier_result:
                break

            if attempt < PIPELINE_VERIFY_RETRIES:
                print("[pipeline] verifier が失敗を報告。executor をリトライします。", file=sys.stderr)
                executor_task = (
                    f"元のタスク: {task}\n\n"
                    f"前回の実行結果:\n{executor_result}\n\n"
                    f"検証フィードバック（要修正）:\n{verifier_result}\n\n"
                    "上記のフィードバックを踏まえて修正・再実行してください。"
                    "各タスク完了後に todo_write でステータスを更新してください。"
                )

    sections = "\n\n---\n\n".join(
        f"## [{phase}]\n{result}" for phase, result in results.items()
    )
    return sections


# ── サブエージェント実行 ──────────────────────────────────────

def run_sub_agent(role: str, task: str, scope_path: str = "", scope_mode: str = "R") -> str:
    """
    サブエージェントを実行し、結果を返す。

    Parameters
    ----------
    role:
        サブエージェントの役割（pipeline / explorer / planner / executor / verifier）
        pipeline を指定すると explorer→planner→[executor→verifier] を自動実行する。
    task:
        サブエージェントへの指示
    scope_path:
        pipeline ロール専用。スコープのパス。
    scope_mode:
        pipeline ロール専用。"R" または "RW"。
    """
    if role == "pipeline":
        return run_pipeline(task, scope_path=scope_path, scope_mode=scope_mode)

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
