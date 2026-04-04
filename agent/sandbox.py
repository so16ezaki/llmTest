"""
sandbox.py — エージェントのファイルアクセス制限

許可ルート配下のパスのみ読み書きを許可する。
GUIで選択されたフォルダ/ファイルをset_allowed_roots()で登録してから使う。

常に許可される内部パス:
  - knowledge/ ディレクトリ（エージェントのナレッジベース）
  - project_memory.md（永続メモリ）
"""

from __future__ import annotations

import os
from enum import IntEnum


# ── 権限レベル ─────────────────────────────────────────────

class PermissionLevel(IntEnum):
    """操作種別ごとの権限レベル。"""
    READ = 1       # ファイル読み取り（常に許可）
    WRITE = 2      # ファイル書き込み（許可ルート内のみ）
    EXECUTE = 3    # 外部コマンド実行（ユーザー承認必要）


# 各ツールの権限レベルマッピング
TOOL_PERMISSIONS: dict[str, PermissionLevel] = {
    "scan_project": PermissionLevel.READ,
    "read_source": PermissionLevel.READ,
    "grep_source": PermissionLevel.READ,
    "list_knowledge": PermissionLevel.READ,
    "knowledge_search": PermissionLevel.READ,
    "read_knowledge": PermissionLevel.READ,
    "keyword_search": PermissionLevel.READ,
    "extract_structure": PermissionLevel.READ,
    "static_analysis": PermissionLevel.READ,
    "generate_skeleton": PermissionLevel.READ,
    "dependency_map": PermissionLevel.READ,
    "get_knowledge_coverage": PermissionLevel.READ,
    "read_pdf_pages": PermissionLevel.READ,
    "get_status": PermissionLevel.READ,
    "memory_read": PermissionLevel.READ,
    "compact_now": PermissionLevel.READ,
    "sub_agent": PermissionLevel.READ,
    "write_file": PermissionLevel.WRITE,
    "edit_file": PermissionLevel.WRITE,
    "todo_write": PermissionLevel.WRITE,
    "memory_write": PermissionLevel.WRITE,
    "convert_pages_to_knowledge": PermissionLevel.WRITE,
}


def get_tool_permission(tool_name: str) -> PermissionLevel:
    """ツールの権限レベルを返す。未登録ツールはREADを返す。"""
    return TOOL_PERMISSIONS.get(tool_name, PermissionLevel.READ)


# エージェント自身のディレクトリ（sandbox.py の場所）
_AGENT_DIR = os.path.dirname(os.path.abspath(__file__))

# 常に許可する内部パス（絶対パスに解決済み）
_INTERNAL_ROOTS: tuple[str, ...] = (
    os.path.realpath(os.path.join(_AGENT_DIR, "knowledge")),
    os.path.realpath(os.path.join(_AGENT_DIR, "project_memory.md")),
)

# ユーザーが選択した許可ルート（絶対パス・realpath解決済み）
_allowed_roots: list[str] = []


def set_allowed_roots(paths: list[str]) -> None:
    """許可ルートを設定する。既存の設定は上書きされる。"""
    global _allowed_roots
    _allowed_roots = [os.path.realpath(p) for p in paths if p]


def clear() -> None:
    """許可ルートをリセットする（内部パスは引き続き有効）。"""
    global _allowed_roots
    _allowed_roots = []


def get_allowed_roots() -> list[str]:
    """現在の許可ルート一覧を返す（内部パス含む）。"""
    return list(_INTERNAL_ROOTS) + list(_allowed_roots)


def is_allowed(path: str) -> bool:
    """
    パスがアクセス許可範囲内かどうかを返す。

    - 相対パスは _AGENT_DIR 基準で解決する
    - シンボリックリンクは realpath で解決してチェックする
    - ディレクトリトラバーサル（../）も realpath で無効化
    """
    # 絶対パスに解決
    if not os.path.isabs(path):
        path = os.path.join(_AGENT_DIR, path)
    real = os.path.realpath(path)

    # 内部パスチェック
    for root in _INTERNAL_ROOTS:
        if real == root or real.startswith(root + os.sep):
            return True

    # ユーザー許可ルートチェック
    for root in _allowed_roots:
        if real == root or real.startswith(root + os.sep):
            return True

    return False


def check(path: str, operation: str = "アクセス") -> None:
    """
    パスが許可範囲外なら SandboxViolation を送出する。

    Parameters
    ----------
    path:
        チェック対象のパス
    operation:
        エラーメッセージに使う操作名（"読み取り" / "書き込み" 等）
    """
    if not is_allowed(path):
        roots = get_allowed_roots()
        roots_str = "\n  ".join(roots) if roots else "（未設定）"
        raise SandboxViolation(
            f"[sandbox] {operation}が拒否されました: {path}\n"
            f"許可されているパス:\n  {roots_str}"
        )


class SandboxViolation(PermissionError):
    """サンドボックス違反を示す例外。"""
