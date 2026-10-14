"""数据清理 —— 防止日志/帖子表无限增长。

策略（保守，不动你的「内容」数据）：
  - `runs` / `push_log` 只留最近若干条（纯日志）
  - `posts` 里**已处理且超过 N 天**的删掉（其正文已经变成 events 存着了）
  - **events / terms / captions 一律不动** —— 那是你自己攒的内容
"""
from .. import db

RETAIN_RUNS = 500
RETAIN_PUSH = 200
POST_DAYS = 30


def cleanup(retain_runs: int = RETAIN_RUNS, retain_push: int = RETAIN_PUSH,
            post_days: int = POST_DAYS) -> dict:
    """返回各表删除条数。"""
    n = {}
    with db.tx() as conn:
        for table, keep in (("runs", retain_runs), ("push_log", retain_push)):
            before = conn.total_changes
            conn.execute(
                f"DELETE FROM {table} WHERE id NOT IN "
                f"(SELECT id FROM {table} ORDER BY id DESC LIMIT ?)", (int(keep),))
            n[table] = conn.total_changes - before

        before = conn.total_changes
        conn.execute(
            "DELETE FROM posts WHERE processed=1 AND created_at < "
            "datetime('now','localtime',?)", (f"-{int(post_days)} days",))
        n["posts"] = conn.total_changes - before
    return n
