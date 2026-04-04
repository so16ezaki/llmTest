"""
tool_registry.py — ツール名→関数マッピング + JSON Schema定義

全ツールのOpenAI形式スキーマを一元管理し、
execute_tool(name, args) でディスパッチする。
"""

from __future__ import annotations

import importlib
from typing import Any, Callable


# ── ツールスキーマ定義（OpenAI function calling形式）──────────────

TOOL_DEFINITIONS: list[dict] = [
    # ── ナレッジ検索 ──────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "list_knowledge",
            "description": "利用可能なナレッジファイルの一覧と概要を返す。",
            "parameters": {
                "type": "object",
                "properties": {
                    "scope": {
                        "type": "string",
                        "description": "サブディレクトリ名でフィルタ（省略時は全て）",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "knowledge_search",
            "description": "index.mdの内容から、質問に関連するナレッジを推薦する。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "検索クエリ",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_knowledge",
            "description": "指定ナレッジファイルの全文を返す（オンデマンドロード）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "ナレッジファイルのパス（knowledge/配下の相対パス）",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "keyword_search",
            "description": "全ナレッジファイルをgrep検索。正規表現対応。前後N行の文脈付きで返す。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "検索パターン（正規表現）",
                    },
                    "scope": {
                        "type": "string",
                        "description": "検索対象のサブディレクトリ（省略時は全て）",
                    },
                    "context_lines": {
                        "type": "integer",
                        "description": "前後に含める行数（デフォルト: 3）",
                        "default": 3,
                    },
                    "page": {
                        "type": "integer",
                        "description": "結果ページ番号（1始まり、デフォルト: 1）",
                        "default": 1,
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    # ── ナレッジカバレッジ・PDF直接読み取り ─────────────────────────
    {
        "type": "function",
        "function": {
            "name": "get_knowledge_coverage",
            "description": "ドキュメントの処理カバレッジ情報を返す。"
                           "どのページが処理済みか、未処理部分のTOCを確認できる。",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_name": {
                        "type": "string",
                        "description": "ドキュメント名（省略時は全ドキュメントの概要）",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_pdf_pages",
            "description": "PDFの指定ページ範囲を直接読み取りMarkdownに変換して返す。"
                           "未処理ページの内容を確認するのに使用する。",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_name": {
                        "type": "string",
                        "description": "ドキュメント名（knowledge/配下のディレクトリ名）",
                    },
                    "start_page": {
                        "type": "integer",
                        "description": "開始ページ番号（1始まり）",
                    },
                    "end_page": {
                        "type": "integer",
                        "description": "終了ページ番号（1始まり、この番号を含む）",
                    },
                },
                "required": ["doc_name", "start_page", "end_page"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "convert_pages_to_knowledge",
            "description": "PDFの指定ページ範囲を正式なナレッジファイルに変換して保存する。"
                           "read_pdf_pagesで重要な内容を見つけた場合に使用する。",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_name": {
                        "type": "string",
                        "description": "ドキュメント名（knowledge/配下のディレクトリ名）",
                    },
                    "start_page": {
                        "type": "integer",
                        "description": "開始ページ番号（1始まり）",
                    },
                    "end_page": {
                        "type": "integer",
                        "description": "終了ページ番号（1始まり、この番号を含む）",
                    },
                },
                "required": ["doc_name", "start_page", "end_page"],
            },
        },
    },
    # ── コード解析 ────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "scan_project",
            "description": "ディレクトリのファイル構成を返す。sort_by='mtime'で更新日時順に表示。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "スキャン対象のディレクトリパス",
                    },
                    "sort_by": {
                        "type": "string",
                        "description": "ソート方法: 'name'（ツリー形式）または 'mtime'（更新日時順）",
                        "enum": ["name", "mtime"],
                        "default": "name",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_source",
            "description": "ソースコードを読む。symbol指定時はその関数/クラスのみ返す。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "ファイルパス",
                    },
                    "symbol": {
                        "type": "string",
                        "description": "関数名またはクラス名（省略時はファイル全体）",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep_source",
            "description": "ソースコードをgrep検索する。結果が多い場合はpage引数でページ送り可能。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "検索パターン（正規表現）",
                    },
                    "path": {
                        "type": "string",
                        "description": "検索対象のファイルまたはディレクトリ",
                    },
                    "context_lines": {
                        "type": "integer",
                        "description": "前後に含める行数（デフォルト: 3）",
                        "default": 3,
                    },
                    "page": {
                        "type": "integer",
                        "description": "結果ページ番号（1始まり、デフォルト: 1）",
                        "default": 1,
                    },
                },
                "required": ["pattern", "path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_structure",
            "description": "関数/クラス/変数の一覧と呼び出し関係をJSONで返す。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "解析対象のファイルまたはディレクトリ",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "static_analysis",
            "description": "指定した解析を実行し結果をJSONで返す。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "解析対象のファイルまたはディレクトリ",
                    },
                    "analysis": {
                        "type": "string",
                        "description": "解析種別",
                        "enum": [
                            "call_graph",
                            "dependency_graph",
                            "data_flow",
                            "control_flow",
                            "complexity",
                            "dead_code",
                            "symbol_table",
                            "type_info",
                            "metrics",
                            "issues",
                        ],
                    },
                },
                "required": ["path", "analysis"],
            },
        },
    },
    # ── スケルトン・依存関係 ────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "generate_skeleton",
            "description": "ファイルからシグネチャ+Docstring+インターフェースのみを抽出したスケルトンを返す。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "対象のソースファイルパス",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dependency_map",
            "description": "ファイル/モジュール間の依存関係をMermaid図またはJSONで返す。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "解析対象のファイルまたはディレクトリ",
                    },
                    "format": {
                        "type": "string",
                        "description": "出力形式: 'mermaid'（デフォルト）または 'json'",
                        "enum": ["mermaid", "json"],
                        "default": "mermaid",
                    },
                },
                "required": ["path"],
            },
        },
    },
    # ── 計画・管理 ────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "todo_write",
            "description": "TODOリストの作成・更新。全体を毎回上書きする。",
            "parameters": {
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "description": "TODOアイテムのリスト",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "content": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "done"],
                                },
                                "priority": {
                                    "type": "string",
                                    "enum": ["high", "medium", "low"],
                                },
                            },
                            "required": ["id", "content", "status"],
                        },
                    }
                },
                "required": ["todos"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_write",
            "description": "project_memory.mdにキー付きで学習を保存する。",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "メモリキー（セクション見出し）",
                    },
                    "content": {
                        "type": "string",
                        "description": "保存する内容",
                    },
                },
                "required": ["key", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_read",
            "description": "project_memory.mdから読み出す。",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "読み出すキー（省略時は全て）",
                    }
                },
                "required": [],
            },
        },
    },
    # ── 出力 ──────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "ファイルを書き出す（md, mermaid, json等）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "書き出し先のファイルパス",
                    },
                    "content": {
                        "type": "string",
                        "description": "ファイルの内容",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "完全一致の文字列置換でファイルを編集する。old_stringは一意である必要がある。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "編集対象のファイルパス",
                    },
                    "old_string": {
                        "type": "string",
                        "description": "置換前の文字列（完全一致、一意である必要がある）",
                    },
                    "new_string": {
                        "type": "string",
                        "description": "置換後の文字列",
                    },
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    # ── サブエージェント ──────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "sub_agent",
            "description": "サブエージェントにタスクを委任する。"
                "explorer: ファイル探索・コード調査、"
                "planner: 計画策定・TODO作成、"
                "executor: ファイル書き込み・編集実行",
            "parameters": {
                "type": "object",
                "properties": {
                    "role": {
                        "type": "string",
                        "enum": ["explorer", "planner", "executor"],
                        "description": "サブエージェントの役割",
                    },
                    "task": {
                        "type": "string",
                        "description": "サブエージェントへの指示（調査内容・計画要件・実行内容）",
                    },
                },
                "required": ["role", "task"],
            },
        },
    },
    # ── コンテキスト管理 ──────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "compact_now",
            "description": "手動でコンテキストのコンパクションを発火する。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_status",
            "description": "現在のトークン使用量・残りバジェット・TODOの状態を返す。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]


# ── ツール定義テキスト（Difyバックエンド用）────────────────────────

def _build_tool_definitions_text() -> str:
    """TOOL_DEFINITIONS から LLM向けテキスト形式のツール説明を生成する。

    Difyバックエンドでは function calling が使えないため、
    ツール定義をテキストとしてシステムプロンプトに含める。
    LLMはXMLタグ形式でツール呼び出しを出力する。
    """
    lines = [
        "## 利用可能なツール\n",
        "ツールを呼び出すには以下のXML形式を使ってください:",
        "```",
        "<tool_call>",
        "  <name>ツール名</name>",
        '  <args>{"引数名": "値"}</args>',
        "</tool_call>",
        "```\n",
        "最終回答時はツール呼び出しなしのテキストのみ返してください。\n",
    ]
    for tool_def in TOOL_DEFINITIONS:
        fn = tool_def["function"]
        lines.append(f"### {fn['name']}")
        lines.append(fn["description"])
        props = fn["parameters"].get("properties", {})
        required = fn["parameters"].get("required", [])
        if props:
            for pname, pinfo in props.items():
                req = "必須" if pname in required else "省略可"
                ptype = pinfo.get("type", "")
                desc = pinfo.get("description", "")
                lines.append(f"- {pname} ({ptype}, {req}): {desc}")
        else:
            lines.append("- 引数なし")
        lines.append("")
    return "\n".join(lines)


TOOL_DEFINITIONS_TEXT: str = _build_tool_definitions_text()


# ── ツールディスパッチャー ────────────────────────────────────────

# ファイルパスを使うツールと、チェック対象の引数名・操作種別のマッピング
# (引数名, 操作種別)
_PATH_CHECKED_TOOLS: dict[str, tuple[str, str]] = {
    "scan_project":       ("path", "読み取り"),
    "read_source":        ("path", "読み取り"),
    "grep_source":        ("path", "読み取り"),
    "extract_structure":  ("path", "読み取り"),
    "static_analysis":    ("path", "読み取り"),
    "generate_skeleton":  ("path", "読み取り"),
    "dependency_map":     ("path", "読み取り"),
    "write_file":         ("path", "書き込み"),
    "edit_file":          ("path", "書き込み"),
}


# ── 書き込み承認コールバック ──────────────────────────────────────

_approval_callback: Callable[[str, str, dict], bool] | None = None


def set_approval_callback(cb: Callable[[str, str, dict], bool]) -> None:
    """
    GUIから承認コールバックを登録する。

    コールバック引数: (tool_name, operation, args) → bool（Trueで許可）
    """
    global _approval_callback
    _approval_callback = cb


def execute_tool(name: str, args: dict[str, Any]) -> str:
    """
    ツール名と引数を受け取り、対応する関数を呼び出して結果を文字列で返す。
    tool_registryはここに全ツールの実装マッピングを持つ。

    ファイルパスを扱うツールはsandboxで許可チェックを行う。
    書き込み承認が有効な場合、WRITE以上の操作はコールバックで承認を求める。
    """
    import sandbox
    from config import REQUIRE_WRITE_APPROVAL

    # サンドボックスチェック（パスを使うツールのみ）
    if name in _PATH_CHECKED_TOOLS:
        arg_name, operation = _PATH_CHECKED_TOOLS[name]
        path = args.get(arg_name, "")
        if path:
            try:
                sandbox.check(path, operation)
            except sandbox.SandboxViolation as e:
                return str(e)

    # 書き込み承認チェック
    if REQUIRE_WRITE_APPROVAL and _approval_callback:
        perm = sandbox.get_tool_permission(name)
        if perm >= sandbox.PermissionLevel.WRITE:
            if not _approval_callback(name, "書き込み", args):
                return f"[blocked] {name} の実行がユーザーにより拒否されました。"

    # モジュールのレイジーインポートで循環参照を回避
    dispatch: dict[str, tuple[str, str]] = {
        # (module_path, function_name)
        "list_knowledge":   ("tools.search",          "list_knowledge"),
        "knowledge_search": ("tools.search",          "knowledge_search"),
        "read_knowledge":   ("tools.search",          "read_knowledge"),
        "keyword_search":   ("tools.search",          "keyword_search"),
        "get_knowledge_coverage": ("tools.knowledge", "get_knowledge_coverage"),
        "read_pdf_pages":         ("tools.knowledge", "read_pdf_pages"),
        "convert_pages_to_knowledge": ("tools.knowledge", "convert_pages_to_knowledge"),
        "scan_project":     ("tools.code",            "scan_project"),
        "read_source":      ("tools.code",            "read_source"),
        "grep_source":      ("tools.code",            "grep_source"),
        "extract_structure":("tools.code",            "extract_structure"),
        "static_analysis":  ("tools.static_analysis", "static_analysis"),
        "generate_skeleton":("tools.code",            "generate_skeleton"),
        "dependency_map":   ("tools.code",            "dependency_map"),
        "todo_write":       ("tools.planning",        "todo_write"),
        "memory_write":     ("tools.planning",        "memory_write"),
        "memory_read":      ("tools.planning",        "memory_read"),
        "write_file":       ("tools.output",          "write_file"),
        "edit_file":        ("tools.edit",            "edit_file"),
        "sub_agent":        ("sub_agent",             "run_sub_agent"),
        "compact_now":      ("tools.context",         "compact_now"),
        "get_status":       ("tools.context",         "get_status"),
    }

    if name not in dispatch:
        return f"[error] 未知のツール: {name}"

    module_path, func_name = dispatch[name]
    try:
        module = importlib.import_module(module_path)
        func = getattr(module, func_name)
        result = func(**args)
        return str(result) if result is not None else ""
    except Exception as e:  # noqa: BLE001
        return f"[error] {name} 実行エラー: {type(e).__name__}: {e}"
