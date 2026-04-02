"""
sandbox.py — エージェントのファイルアクセス制限

許可ルート配下のパスのみ読み書きを許可する。
GUIで選択されたフォルダ/ファイルをset_allowed_roots()で登録してから使う。

常に許可される内部パス:
  - skills/ ディレクトリ（エージェントのナレッジベース）
  - project_memory.md（永続メモリ）
"""

from __future__ import annotations

import os

# エージェント自身のディレクトリ（sandbox.py の場所）
_AGENT_DIR = os.path.dirname(os.path.abspath(__file__))

# 常に許可する内部パス（絶対パスに解決済み）
_INTERNAL_ROOTS: tuple[str, ...] = (
    os.path.realpath(os.path.join(_AGENT_DIR, "skills")),
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
