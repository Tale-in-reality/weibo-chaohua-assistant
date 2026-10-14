"""APScheduler 定时任务：抓取 + 推送 + 自动总结。频率读自 settings。"""
from apscheduler.schedulers.background import BackgroundScheduler

from . import db
from .modules import fetcher, housekeeping, summarize
from .notify import notify

_scheduler = None

PUSH_JOB = "push_tick"
SUM_JOB = "summarize_tick"
FETCH_JOB = "fetch_tick"
CLEAN_JOB = "cleanup_tick"


def _cleanup_tick():
    """每天清一次：老 runs / push_log / 已处理的旧帖（不动内容数据）。"""
    try:
        n = housekeeping.cleanup()
        if any(n.values()):
            db.log_run("cleanup", "ok",
                       f"清理 runs={n['runs']} push_log={n['push_log']} posts={n['posts']}")
    except Exception as e:
        db.log_run("cleanup", "error", str(e))


def run_fetch() -> dict:
    """抓一次，必要时链式总结。手动端点与定时 tick 共用。不抛异常。"""
    res = fetcher.fetch_new()
    terms_n, events_n = 0, 0
    if res.get("ok") and db.get_setting("weibo_autosummarize", "1") == "1":
        # 有新增帖，或还有以前没处理完的帖 → 都值得总结一次
        if res.get("added") or fetcher.count_pending():
            try:
                sr = summarize.summarize_pending()   # 内部自带 log_run
                terms_n = sr.get("terms", 0)
                events_n = sr.get("posts", 0)
            except Exception as e:
                db.log_run("summarize", "error", str(e))
                res["summarize_error"] = str(e)
    res["created"] = terms_n      # 前端显示「AI 识别术语 N 个」
    res["summarized"] = events_n  # 本次总结了几条帖
    return res


def _fetch_tick():
    """定时抓取：开关开且已配置才有动作。失败弹窗告知（不假装成功）。"""
    if db.get_setting("weibo_fetch_enabled", "0") != "1":
        return
    if not fetcher.is_configured():
        return
    res = run_fetch()
    if not res.get("ok"):
        notify("超话抓取失败", res.get("error", "未知原因"))


def _push_tick():
    """只推「速览」事件（source='digest'）——每条帖子事件不推，免得刷屏。
    点击弹窗跳到对应速览：launch 带 hash 的本地页面。"""
    if db.get_setting("push_enabled", "1") != "1":
        return
    last = db.one("SELECT created_at FROM push_log ORDER BY id DESC LIMIT 1")
    if last:
        rows = db.rows("SELECT * FROM events WHERE source='digest' AND created_at > ? "
                       "ORDER BY id DESC", (last["created_at"],))
    else:
        rows = db.rows("SELECT * FROM events WHERE source='digest' ORDER BY id DESC LIMIT 3")
    if not rows:
        return
    e = rows[0]                                   # 推最新一条速览
    body = (e["description"] or "")[:200]
    if len(rows) > 1:
        body += f"\n（另有 {len(rows) - 1} 条速览未读）"
    # 点击弹窗 → chaohua:// 协议 → 唤起 app 窗口并跳到这条速览（不开浏览器）
    launch = f"chaohua://events/{e['id']}"
    notify(e["title"] or "超话速览", body, launch=launch)
    db.log_run("push", "ok", f"推送速览 #{e['id']}（点击查看）")


def _summarize_tick():
    if db.get_setting("summarize_enabled", "0") != "1":
        return
    if fetcher.count_pending() == 0:
        return
    try:
        summarize.summarize_pending()
    except Exception as e:
        db.log_run("summarize", "error", str(e))


def start():
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
        _scheduler.start()
    reload_jobs()
    return _scheduler


def _int_setting(key: str, default: int) -> int:
    try:
        return max(1, int(db.get_setting(key, str(default)) or default))
    except (TypeError, ValueError):
        return default


def reload_jobs():
    if not _scheduler:
        return
    for jid in (PUSH_JOB, SUM_JOB, FETCH_JOB, CLEAN_JOB):
        if _scheduler.get_job(jid):
            _scheduler.remove_job(jid)
    _scheduler.add_job(_push_tick, "interval",
                       minutes=_int_setting("push_interval_min", 30), id=PUSH_JOB)
    _scheduler.add_job(_summarize_tick, "interval",
                       minutes=_int_setting("summarize_interval_min", 60), id=SUM_JOB)
    fetch_min = _int_setting("weibo_fetch_interval_min", 60)
    # jitter ≈ ±20%：避免固定节律，降低被识别为机器的概率
    _scheduler.add_job(_fetch_tick, "interval", minutes=fetch_min,
                       jitter=fetch_min * 12, id=FETCH_JOB)
    _scheduler.add_job(_cleanup_tick, "interval", hours=24, id=CLEAN_JOB)


def next_runs() -> dict:
    out = {"push": "", "summarize": "", "fetch": ""}
    if not _scheduler:
        return out
    for jid, key in ((PUSH_JOB, "push"), (SUM_JOB, "summarize"), (FETCH_JOB, "fetch")):
        job = _scheduler.get_job(jid)
        if job and job.next_run_time:
            out[key] = job.next_run_time.strftime("%Y-%m-%d %H:%M:%S")
    return out


def trigger(job: str) -> dict:
    """手动触发一次（界面按钮 / 验证用）。"""
    if job == "push":
        _push_tick()
        return {"ok": True, "message": "已发送推送"}
    if job == "summarize":
        return summarize.summarize_pending()
    if job == "fetch":
        return run_fetch()
    return {"ok": False, "message": "未知任务"}
