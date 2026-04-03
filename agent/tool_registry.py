"""
tool_registry.py — ツール名→関数マッピング + JSON Schema定義

全ツールのOpenAI形式スキーマを一元管理し、
execute_tool(name, args) でディスパッチする。
"""

from __future__ import annotations

import importlib
from typing import Any


# ── ツールスキーマ定義（OpenAI function calling形式）──────────────

TOOL_DEFINITIONS: list[dict] = [
    # ── ナレッジ検索 ──────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "list_skills",
            "description": "利用可能なスキルファイルの一覧と概要を返す。",
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
            "name": "skill_search",
            "description": "index.mdの内容から、質問に関連するスキルを推薦する。",
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
            "name": "read_skill",
            "description": "指定スキルファイルの全文を返す（オンデマンドロード）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "スキルファイルのパス（skills/配下の相対パス）",
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
            "description": "全スキルファイルをgrep検索。正規表現対応。前後N行の文脈付きで返す。",
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
                        "description": "ドキュメント名（skills/配下のディレクトリ名）",
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
            "name": "convert_pages_to_skill",
            "description": "PDFの指定ページ範囲を正式なスキルファイルに変換して保存する。"
                           "read_pdf_pagesで重要な内容を見つけた場合に使用する。",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_name": {
                        "type": "string",
                        "description": "ドキュメント名（skills/配下のディレクトリ名）",
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
            "description": "ディレクトリのファイル構成を返す。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "スキャン対象のディレクトリパス",
                    }
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
            "description": "ソースコードをgrep検索する。",
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
    "scan_project":      ("path", "読み取り"),
    "read_source":       ("path", "読み取り"),
    "grep_source":       ("path", "読み取り"),
    "extract_structure": ("path", "読み取り"),
    "static_analysis":   ("path", "読み取り"),
    "write_file":        ("path", "書き込み"),
}


def execute_tool(name: str, args: dict[str, Any]) -> str:
    """
    ツール名と引数を受け取り、対応する関数を呼び出して結果を文字列で返す。
    tool_registryはここに全ツールの実装マッピングを持つ。

    ファイルパスを扱うツールはsandboxで許可チェックを行う。
    """
    import sandbox

    # サンドボックスチェック（パスを使うツールのみ）
    if name in _PATH_CHECKED_TOOLS:
        arg_name, operation = _PATH_CHECKED_TOOLS[name]
        path = args.get(arg_name, "")
        if path:
            try:
                sandbox.check(path, operation)
            except sandbox.SandboxViolation as e:
                return str(e)

    # モジュールのレイジーインポートで循環参照を回避
    dispatch: dict[str, tuple[str, str]] = {
        # (module_path, function_name)
        "list_skills":      ("tools.search",          "list_skills"),
        "skill_search":     ("tools.search",          "skill_search"),
        "read_skill":       ("tools.search",          "read_skill"),
        "keyword_search":   ("tools.search",          "keyword_search"),
        "get_knowledge_coverage": ("tools.knowledge", "get_knowledge_coverage"),
        "read_pdf_pages":         ("tools.knowledge", "read_pdf_pages"),
        "convert_pages_to_skill": ("tools.knowledge", "convert_pages_to_skill"),
        "scan_project":     ("tools.code",            "scan_project"),
        "read_source":      ("tools.code",            "read_source"),
        "grep_source":      ("tools.code",            "grep_source"),
        "extract_structure":("tools.code",            "extract_structure"),
        "static_analysis":  ("tools.static_analysis", "static_analysis"),
        "todo_write":       ("tools.planning",        "todo_write"),
        "memory_write":     ("tools.planning",        "memory_write"),
        "memory_read":      ("tools.planning",        "memory_read"),
        "write_file":       ("tools.output",          "write_file"),
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
