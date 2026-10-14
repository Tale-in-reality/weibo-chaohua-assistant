"""SQLite 建表与数据访问层。"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from .config import DB_PATH, DEFAULT_SETTINGS, DEFAULT_TEMPLATES

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT DEFAULT 'manual',   -- manual / weibo
    mid         TEXT DEFAULT '',         -- 微博帖子 id（抓取去重用；手动帖为空）
    author      TEXT DEFAULT '',
    content     TEXT NOT NULL,
    posted_at   TEXT DEFAULT '',
    processed   INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS captions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    content      TEXT NOT NULL,
    tags         TEXT DEFAULT '',        -- 逗号分隔
    caption_type TEXT DEFAULT '返图',
    used_at      TEXT DEFAULT '',
    source       TEXT DEFAULT 'manual',  -- manual / generated / weibo
    mid          TEXT DEFAULT '',        -- 微博帖子 id（从微博导入时去重用；手动条目为空）
    posted_at    TEXT DEFAULT '',        -- 原帖发布时间（YYYY-MM-DD HH:MM:SS）；手动条目为空
    status       TEXT DEFAULT 'confirmed',  -- confirmed / pending（微博导入的先待确认）
    scope        TEXT DEFAULT 'general',    -- general 普适 / song 绑定某首歌
    song         TEXT DEFAULT '',           -- 歌名（仅 scope='song' 时有值）
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS terms (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    term       TEXT NOT NULL UNIQUE,
    meaning    TEXT DEFAULT '',
    term_type  TEXT DEFAULT '黑话',       -- 绰号/黑话/应援/事件指代
    event_id   INTEGER,
    confidence TEXT DEFAULT 'manual',    -- manual / likely / maybe_fabricated
    source     TEXT DEFAULT 'manual',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS term_candidates (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    phrase            TEXT NOT NULL UNIQUE,
    freq              INTEGER DEFAULT 1,
    sample            TEXT DEFAULT '',
    suggested_meaning TEXT DEFAULT '',
    confidence        TEXT DEFAULT '',   -- likely / maybe_fabricated
    status            TEXT DEFAULT 'pending',  -- pending / done / ignored
    created_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT NOT NULL,
    event_date    TEXT DEFAULT '',
    description   TEXT DEFAULT '',
    related_terms TEXT DEFAULT '',
    people        TEXT DEFAULT '',
    source        TEXT DEFAULT 'manual',    -- manual / summarized
    status        TEXT DEFAULT 'confirmed', -- confirmed / pending
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prompt_templates (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    tpl_type   TEXT DEFAULT '返图',
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS push_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT,
    body       TEXT,
    channel    TEXT DEFAULT 'desktop',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    job        TEXT,
    status     TEXT,
    detail     TEXT,
    created_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect() -> sqlite3.Connection:
    # timeout=30：调度器线程与 API 线程会并发写，给足等锁时间（默认只有 5s）
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    # synchronous 是「每连接」的，必须在这里设（在 WAL 下 NORMAL 安全且更快）
    try:
        conn.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        pass
    return conn


@contextmanager
def tx():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def rows(sql: str, params=()) -> list:
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def one(sql: str, params=()):
    r = rows(sql, params)
    return r[0] if r else None


def run(sql: str, params=()):
    with tx() as conn:
        cur = conn.execute(sql, params)
        return cur.lastrowid


def _migrate(conn):
    """给旧库补列/补索引（CREATE TABLE IF NOT EXISTS 不会改已存在的表）。幂等。"""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(posts)").fetchall()}
    if "mid" not in cols:
        conn.execute("ALTER TABLE posts ADD COLUMN mid TEXT DEFAULT ''")
    # 部分唯一索引：只约束非空 mid，手动帖（mid='')不受影响、可重复
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_posts_mid "
        "ON posts(mid) WHERE mid IS NOT NULL AND mid != ''"
    )
    # captions 同理（从微博导入的文案靠 mid 去重）
    ccols = {r["name"] for r in conn.execute("PRAGMA table_info(captions)").fetchall()}
    if "mid" not in ccols:
        conn.execute("ALTER TABLE captions ADD COLUMN mid TEXT DEFAULT ''")
    if "posted_at" not in ccols:
        conn.execute("ALTER TABLE captions ADD COLUMN posted_at TEXT DEFAULT ''")
    if "status" not in ccols:
        # 默认 confirmed：**已有的行自动算已确认**，不会被当成待确认而消失
        conn.execute("ALTER TABLE captions ADD COLUMN status TEXT DEFAULT 'confirmed'")
    if "scope" not in ccols:
        # 默认 general：已有的行都算普适（要归到某首歌，手动改）
        conn.execute("ALTER TABLE captions ADD COLUMN scope TEXT DEFAULT 'general'")
    if "song" not in ccols:
        conn.execute("ALTER TABLE captions ADD COLUMN song TEXT DEFAULT ''")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_captions_mid "
        "ON captions(mid) WHERE mid IS NOT NULL AND mid != ''"
    )


def init_db():
    with tx() as conn:
        conn.execute("PRAGMA journal_mode=WAL")   # 持久化在库文件里，设一次即可
        conn.executescript(SCHEMA)
        _migrate(conn)
        for k, v in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)", (k, v))
        if conn.execute("SELECT COUNT(*) c FROM prompt_templates").fetchone()["c"] == 0:
            for name, tpl_type, content in DEFAULT_TEMPLATES:
                conn.execute(
                    "INSERT INTO prompt_templates(name, tpl_type, content, created_at) VALUES(?,?,?,?)",
                    (name, tpl_type, content, now()),
                )
        # 老库的模板补上 `{style}`（风格档案占位符）—— 幂等，已经有了就不动
        conn.execute("UPDATE prompt_templates SET content = content || ? "
                     "WHERE content NOT LIKE '%{style}%'", ("\n\n{style}",))


# ---------- 设置 ----------

def get_setting(key: str, default=None):
    r = one("SELECT value FROM settings WHERE key = ?", (key,))
    return r["value"] if r else default


def set_setting(key: str, value):
    with tx() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )


def all_settings() -> dict:
    return {r["key"]: r["value"] for r in rows("SELECT key, value FROM settings")}


def log_run(job: str, status: str, detail: str = ""):
    run("INSERT INTO runs(job, status, detail, created_at) VALUES(?,?,?,?)",
        (job, status, detail[:2000], now()))
