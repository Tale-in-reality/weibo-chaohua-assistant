"""测试夹具：把数据库指到临时目录，绝不碰真实 data/fan.db。"""
import sys
from pathlib import Path

import pytest

# 让 `import app` 能找到项目根
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db as dbmod   # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _temp_db(tmp_path_factory):
    """整个测试会话用同一个临时库（connect() 读的是 db.DB_PATH 这个模块属性）。"""
    d = tmp_path_factory.mktemp("data")
    dbmod.DB_PATH = d / "test.db"
    dbmod.init_db()
    yield
