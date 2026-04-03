"""テスト共通設定。"""

import os
import sys

import pytest

# agent/ ディレクトリをパスに追加
AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)

# test_data ディレクトリ
TEST_DATA_DIR = os.path.join(os.path.dirname(AGENT_DIR), "test_data")
C_PROJECT_DIR = os.path.join(TEST_DATA_DIR, "c_project")


@pytest.fixture
def c_project_dir():
    """test_data/c_project ディレクトリのパスを返す。"""
    if not os.path.exists(C_PROJECT_DIR):
        pytest.skip("test_data/c_project not available")
    return C_PROJECT_DIR


@pytest.fixture
def agent_dir():
    return AGENT_DIR
