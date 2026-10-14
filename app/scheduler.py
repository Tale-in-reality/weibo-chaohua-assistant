"""APScheduler 定时任务：抓取 + 推送 + 自动总结。频率读自 settings。"""
import random
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from . import db
from .modules import fetcher, housekeeping, summarize
from .notify import last_error, notify

_scheduler = None

PUSH_JOB = "push_tick"
SUM_JOB = "summarize_tick"
FETCH_JOB = "fetch_tick"
FETCH_STARTUP_JOB = "fetch_startup"     # 开机补抓（一次性）
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


def run_fetch(trigger: str = "manual") -> dict:
    """抓一次，必要时链式总结，有新速览就顺手推一次。不抛异常。

    trigger: manual（点按钮）/ auto（定时 / 开机补抓）——只影响进度显示。
    """
    res = fetcher.fetch_new(trigger=trigger, keep_open=True)
    terms_n, events_n, digest_id = 0, 0, None
    # 有新增帖，或还有以前没处理完的帖 → 都值得总结一次
    if (res.get("ok") and db.get_setting("weibo_autosummarize", "1") == "1"
            and (res.get("added") or fetcher.count_pending())):
        fetcher.set_phase("summarize", "抓取完成，正在总结为事件与速览…")
        try:
            sr = summarize.summarize_pending()   # 内部自带 log_run
            terms_n = sr.get("terms", 0)
            events_n = sr.get("posts", 0)
            digest_id = sr.get("digest_id")
        except Exception as e:
            db.log_run("summarize", "error", str(e))
            res["summarize_error"] = str(e)
        finally:
            fetcher.finalize()
    else:
        fetcher.finalize()
    res["created"] = terms_n      # 前端显示「AI 识别术语 N 个」
    res["summarized"] = events_n  # 本次总结了几条帖
    res["digest_id"] = digest_id

    # 刚生成了新速览 → 立刻推一次，不等下一个推送间隔（用户点「抓取」就想马上有反馈）
    if res.get("ok") and db.get_setting("push_enabled", "1") == "1":
        try:
            _push_tick()
        except Exception as e:
            db.log_run("push", "error", str(e))
    return res


def _fetch_tick():
    """定时抓取：开关开且已配置才有动作。失败弹窗告知（不假装成功）。"""
    if db.get_setting("weibo_fetch_enabled", "0") != "1":
        return
    if not fetcher.is_configured():
        return
    res = run_fetch(trigger="auto")
    if not res.get("ok") and res.get("error") != "已经在抓取中，等它跑完（或点「停止抓取」）":
        notify("超话抓取失败", res.get("error", "未知原因"))


def _minutes_since(sql: str) -> float | None:
    """某条查询命中的最近时间距现在多少分钟。查不到 / 解析不了 → None。"""
    row = db.one(sql)
    if not row or not row["created_at"]:
        return None
    try:
        dt = datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None
    return (datetime.now() - dt).total_seconds() / 60


def fetch_due() -> bool:
    """现在「该抓了吗」—— 开机补抓与「一键开启」都用它把门。

    为什么要这道门：用户反复开关 app 时，每次启动都补抓会让同一段时间的帖子被
    重复拉取（mid 去重只防重复入库，**防不住重复请求**）→ 平白增加风控风险。
    所以只在真的「欠着一次抓取」时才补：
      · 距上次**成功**抓取 ≥ 抓取间隔（没到点就交给定时任务）
      · 且最近 3 分钟内**没试过**（含失败，避免失败后连打）
    """
    interval = _int_setting("weibo_fetch_interval_min", 60)
    since_ok = _minutes_since(
        "SELECT created_at FROM runs WHERE job='fetch' AND status='ok' "
        "ORDER BY id DESC LIMIT 1")
    if since_ok is not None and since_ok < interval:
        return False
    since_any = _minutes_since(
        "SELECT created_at FROM runs WHERE job='fetch' ORDER BY id DESC LIMIT 1")
    if since_any is not None and since_any < 3:
        return False
    return True


def schedule_startup_catchup(delay_seconds: int | None = None) -> bool:
    """开机补抓（一次性）：打开 app 后按「距上次成功抓取的空档」补一次。

    没有它的话，`interval` 任务要等满一个抓取间隔才第一次跑 —— 刚打开时
    「什么都没发生」，看起来就像定时坏了。窗口本身由 fetcher._window_minutes()
    按上次成功抓取的时间放大，所以中间漏掉的帖子会被一起抓回来。

    ⚠️ 每次启动都补抓会让同一段时间的帖子被重复请求（去重只在入库层），
    所以先用 `fetch_due()` 把门；延时也带随机抖动（默认 8~20s），
    不形成「启动后固定第 8 秒发请求」的节律。
    """
    if not _scheduler:
        return False
    if db.get_setting("weibo_fetch_enabled", "0") != "1":
        return False
    if not fetcher.is_configured():
        return False
    if not fetch_due():
        return False
    if delay_seconds is None:
        delay_seconds = random.randint(8, 20)
    try:
        _scheduler.add_job(_fetch_tick, "date",
                           run_date=datetime.now() + timedelta(seconds=max(0, delay_seconds)),
                           id=FETCH_STARTUP_JOB, replace_existing=True)
        return True
    except Exception:
        return False


def _push_tick():
    """只推「速览」事件（source='digest'）——每条帖子事件不推，免得刷屏。

    水位线用**已推送过的最大速览 id**（存 settings），而不是 push_log 的时间：
    push_log 也会被「测试推送」「抓取失败」写入，拿它当分界会让一次失败/一次测试
    把接下来的速览推送**静默吞掉**。用 id 就与这些无关。
    """
    if db.get_setting("push_enabled", "1") != "1":
        return
    try:
        mark = int(db.get_setting("last_pushed_digest_id", "0") or 0)
    except (TypeError, ValueError):
        mark = 0
    rows = db.rows("SELECT * FROM events WHERE source='digest' AND id > ? ORDER BY id DESC",
                   (mark,))
    if not rows:
        return
    e = rows[0]                                   # 推最新一条速览
    body = (e["description"] or "")[:200]
    if len(rows) > 1:
        body += f"\n（另有 {len(rows) - 1} 条速览未读）"
    # 点击弹窗 → chaohua:// 协议 → 唤起 app 窗口并跳到这条速览（不开浏览器）
    launch = f"chaohua://events/{e['id']}"
    ok = notify(e["title"] or "超话速览", body, launch=launch)
    db.set_setting("last_pushed_digest_id", str(max(r["id"] for r in rows)))
    db.log_run("push", "ok" if ok else "error",
               f"推送速览 #{e['id']}（点击查看）" if ok
               else f"推送速览 #{e['id']} 失败：{last_error()}")


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
    schedule_startup_catchup()      # 打开就补抓（延时带抖动），别等满一个间隔
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
        return run_fetch(trigger="manual")
    return {"ok": False, "message": "未知任务"}
