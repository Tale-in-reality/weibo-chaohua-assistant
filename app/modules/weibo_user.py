"""从微博抓某个用户在指定超话里发过的帖子 → 存进「文案库」。

比手抄历史文案快得多，用来快速攒够风格样本。

接口（2026-10-13 实测）：
  - 用户搜索：`getIndex?containerid=100103type=3&q=<昵称>` → 卡片里 `screen_name` +
    `profile_url`（`m.weibo.cn/u/<uid>`）
  - 用户时间线：`getIndex?containerid=107603<uid>&page=N`
  - 每条帖子 `topic_id == "1022:<超话containerid>"` —— 用它**精确**筛出「属于某超话」的帖子
  - 长文：`text` 会被截断（带「全文」），需 `statuses/show?id=<mid>` 取全文

⚠️ 同样是自动化访问：低频、软失败、不重试。
"""
import html
import random
import re
import threading
import time
from datetime import datetime, timedelta

import httpx

from .. import db
from . import fetcher, pacing

API = fetcher.API
USER_TIMELINE = "107603{}"          # + uid
USER_SEARCH = "100103type=3&q={}"   # + 关键词

# 把「超话」链接整个去掉（连它显示的文字一起）——那是超话徽章，不是本人写的字。
# ⚠️ 只剥 `/p/index`（超话）；`#话题#` 走的是 `/search?q=%23...` 链接，**必须保留**。
_TOPIC_LINK = re.compile(r"<a[^>]*?/p/index[^>]*?>.*?</a>", re.S)
_TOPIC_LINK_NAMED = re.compile(r"<a[^>]*containerid=(100808[0-9A-Za-z]+)[^>]*>(.*?)</a>", re.S)
_BR = re.compile(r"<br\s*/?>", re.I)
_ANY_TAG = re.compile(r"<[^>]+>")
_UID_IN_URL = re.compile(r"/u/(\d+)")
_FULLTEXT_LINK = re.compile(r"\s*<a[^>]*>\s*全文\s*</a>\s*$")


class EmptyPage(Exception):
    """该页没有内容 —— 时间线到底了（微博用 ok=0 表示），不是错误。"""


def _get(url: str, params: dict) -> dict:
    """带 cookie 的 GET。ok=0 → EmptyPage（翻页到底）；其它异常抛 FetchError。"""
    pacing.pace()                       # 不背靠背连发，间隔带抖动
    try:
        r = httpx.get(url, params=params, headers=fetcher._headers(),
                      timeout=15.0, follow_redirects=True)
    except httpx.TimeoutException:
        raise fetcher.FetchError("网络超时（15s）")
    except httpx.HTTPError as e:
        raise fetcher.FetchError(f"网络错误：{e}")
    if r.status_code in (418, 432, 414):
        raise fetcher.FetchError(f"触发风控（HTTP {r.status_code}）——请暂停后再试")
    if r.status_code != 200:
        raise fetcher.FetchError(f"HTTP {r.status_code}")
    if "json" not in r.headers.get("content-type", "").lower():
        raise fetcher.FetchError("返回非 JSON——cookie 可能失效或触发风控")
    try:
        j = r.json()
    except Exception:
        raise fetcher.FetchError("响应不是合法 JSON")
    if j.get("ok") == 0:
        raise EmptyPage()                      # 没有更多内容了
    if j.get("ok") != 1:
        raise fetcher.FetchError(f"接口返回 ok={j.get('ok')}（cookie 可能失效）")
    return j.get("data") or {}


# ---------- 找用户 ----------

def resolve_user(query: str) -> dict:
    """把「昵称或 uid 或主页链接」解析成 {uid, screen_name} 候选。"""
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "请输入用户昵称或 uid", "candidates": []}

    m = _UID_IN_URL.search(q)                     # 主页链接
    if m:
        return {"ok": True, "candidates": [{"uid": m.group(1), "screen_name": ""}]}
    if q.isdigit():                               # 直接给 uid
        return {"ok": True, "candidates": [{"uid": q, "screen_name": ""}]}

    try:
        data = _get(API, {"containerid": USER_SEARCH.format(q), "page_type": "searchall"})
    except EmptyPage:
        return {"ok": True, "candidates": [], "message": "没搜到该用户"}
    except fetcher.FetchError as e:
        return {"ok": False, "error": str(e), "candidates": []}

    found = {}
    _walk_users(data, found)
    out = [{"uid": u, "screen_name": n} for u, n in found.items()]
    if not out:
        return {"ok": True, "candidates": [], "message": "没搜到用户，试试直接填 uid 或主页链接"}
    return {"ok": True, "candidates": out[:8], "message": f"找到 {len(out)} 个用户"}


def scan_user_topics(user: str, days: int = 180, max_pages: int = 10) -> dict:
    """扫该用户的原创帖，列出 TA 发过哪些超话（containerid + 名字 + 条数），供挑选。

    这样就不用手动去 F12 抄 containerid 了。
    """
    if not fetcher.is_configured():
        return {"ok": False, "error": "请先扫码登录获取 cookie"}
    rc = resolve_user(user)
    if not rc.get("ok") or not rc["candidates"]:
        return {"ok": False, "error": rc.get("error") or rc.get("message") or "找不到用户"}
    uid = rc["candidates"][0]["uid"]
    screen_name = rc["candidates"][0].get("screen_name") or uid

    cutoff = datetime.now() - timedelta(days=max(1, int(days)))
    max_pages = max(1, min(int(max_pages or 10), 50))
    topics, scanned, page = {}, 0, 1
    try:
        while page <= max_pages:
            try:
                data = _get(API, {"containerid": USER_TIMELINE.format(uid), "page": page})
            except EmptyPage:
                break
            cards = [c["mblog"] for c in (data.get("cards") or [])
                     if isinstance(c.get("mblog"), dict)]
            if not cards:
                break
            page_newest = None
            for mb in cards:
                scanned += 1
                dt = fetcher._parse_time((mb.get("created_at") or "").strip())
                if dt is not None and (page_newest is None or dt > page_newest):
                    page_newest = dt
                too_old = dt is not None and dt < cutoff
                if too_old or mb.get("retweeted_status"):
                    continue
                for m in _TOPIC_LINK_NAMED.finditer(mb.get("text") or ""):
                    cid = m.group(1)
                    name = re.sub(r"\s+", "", _ANY_TAG.sub("", m.group(2)))
                    t = topics.setdefault(cid, {"containerid": cid, "name": "", "count": 0})
                    t["count"] += 1
                    if name and not t["name"]:
                        t["name"] = name
            if page_newest is not None and page_newest < cutoff:
                break
            page += 1                             # 页间节奏由 pacing 统一控制
    except fetcher.FetchError as e:
        return {"ok": False, "error": str(e), "uid": uid, "screen_name": screen_name}

    items = sorted(topics.values(), key=lambda x: -x["count"])
    msg = (f"@{screen_name} 扫了 {scanned} 条，发过 {len(items)} 个超话" if items
           else f"@{screen_name} 扫了 {scanned} 条，没发现带超话的原创帖")
    return {"ok": True, "uid": uid, "screen_name": screen_name, "scanned": scanned,
            "topics": items, "message": msg}


def _walk_users(obj, found: dict):
    """递归收集 uid→昵称。`profile_url` 和 `screen_name` 常常不在同一个节点，
    所以同一个 uid 后遇到的非空昵称要覆盖回去。"""
    if isinstance(obj, dict):
        m = _UID_IN_URL.search(str(obj.get("profile_url") or obj.get("scheme") or ""))
        if m:
            uid = m.group(1)
            name = (obj.get("screen_name") or "").strip()
            if uid not in found or (name and not found[uid]):
                found[uid] = name
        for v in obj.values():
            _walk_users(v, found)
    elif isinstance(obj, list):
        for v in obj:
            _walk_users(v, found)


# ---------- 清洗正文 ----------

def _clean_caption(text: str) -> str:
    """微博正文 HTML → 纯文本。

    **保留换行**（那是本人的排版习惯，也是风格的一部分）：
    微博用 `<br />` 分行，所以先把 br 换成 \\n 再剥标签，最后只折叠空格、不动换行。
    `#话题#` 走的是 search 链接、不在 _TOPIC_LINK 里，因此会原样保留。
    """
    t = _FULLTEXT_LINK.sub("", text or "")      # 去掉尾部的「全文」链接
    t = _TOPIC_LINK.sub("", t)                  # 去掉超话徽章（连同它的显示文字）
    t = _BR.sub("\n", t)                        # 换行：先于剥标签，且要保住
    t = _ANY_TAG.sub("", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t 　]+", " ", t)   # 折叠空格（含全角空格），换行不动
    t = re.sub(r" *\n *", "\n", t)              # 行首行尾的空格去掉
    t = re.sub(r"\n{3,}", "\n\n", t)            # 最多留一个空行
    return t.strip()


def _full_text(mid: str) -> str:
    """长文取全文。实现统一放在 fetcher.full_text（超话抓取也用同一个）。"""
    return fetcher.full_text(mid)


# ---------- 主入口 ----------

def _flush(rows: list, caption_type: str) -> tuple:
    """写库（按 mid 去重）。rows = [(mid, content, posted_at)]。返回 (added, skipped)。"""
    if not rows:
        return 0, 0
    with db.tx() as conn:
        before = conn.total_changes
        conn.executemany(
            # 导入的先落「待确认」，你在文案库页一条条确认后才算入库
            "INSERT OR IGNORE INTO captions"
            "(content, tags, caption_type, source, mid, posted_at, status, created_at) "
            "VALUES(?,'',?,'weibo',?,?,'pending',?)",
            [(c, caption_type, mid, posted, db.now()) for mid, c, posted in rows],
        )
        added = conn.total_changes - before
    return added, len(rows) - added


def _scan_page(uid, page, want_topic, since, until, max_fulltext):
    """读一页 → (rows, page_newest, empty, stats)。

    since / until 是用户选的日期范围（含）：太旧的跳过、太新的也跳过。
    rows = [(mid, content, posted_at)]；posted_at 用**原帖时间**（列表要按它排，
    不能靠插入顺序 —— 导入是按时间线新→旧插的，最后插入的反而是最旧的）。
    """
    try:
        data = _get(API, {"containerid": USER_TIMELINE.format(uid), "page": page})
    except EmptyPage:
        return [], None, True, {}
    cards = [c["mblog"] for c in (data.get("cards") or [])
             if isinstance(c.get("mblog"), dict)]
    if not cards:
        return [], None, True, {}

    rows, page_newest = [], None
    noise = longn = matched = 0
    for mb in cards:
        raw_time = (mb.get("created_at") or "").strip()
        dt = fetcher._parse_time(raw_time)
        if dt is not None and (page_newest is None or dt > page_newest):
            page_newest = dt
        if until is not None and dt is not None and dt > until:
            continue                          # 比截止日期还新，跳过
        if dt is not None and dt < since:
            continue                          # 太旧，跳过（但**不能据此就停**）
        # 只保留「属于目标超话」的：topic_id 形如 1022:<超话containerid>
        if want_topic and want_topic not in str(mb.get("topic_id") or ""):
            continue
        if mb.get("retweeted_status"):
            continue                          # 转发不是本人原创
        matched += 1

        text = mb.get("text") or ""
        mid = str(mb.get("mid") or mb.get("id") or "")
        if mb.get("isLongText") and longn < max_fulltext and mid:
            full = _full_text(mid)            # 长文取全文，别停在「全文」
            if full:
                text = full
                longn += 1
        content = _clean_caption(text)
        if not content or fetcher._is_noise(content):
            noise += 1
            continue
        rows.append((mid, content, dt.strftime("%Y-%m-%d %H:%M:%S") if dt else ""))

    return rows, page_newest, False, {"scanned": len(cards), "matched": matched,
                                      "noise": noise, "long": longn}


# ---------- 后台续跑导入 ----------
#
# 用户要求：**超过页数上限不要让他手点**，自动休息一会儿再从断点继续，
# 直到把日期范围内的帖子扫完。所以跑在后台线程里，前端轮询进度。

# 内部兜底：正常情况下靠「翻到日期起点」结束；这个只是防跑飞的死循环保险，
# 不给用户当旋钮（用户要的是「一直翻到扫完」，不该被页数卡住）。
SAFETY_MAX_PAGES = 2000

JOB = {
    "running": False, "done": False, "ok": None,
    "uid": "", "screen_name": "", "days": 0,
    "page": 1, "scanned": 0, "added": 0, "skipped": 0, "noise": 0, "long": 0,
    "batch": 0, "cooldown": 0, "message": "", "error": "", "started": 0.0,
    # 进度：从「最新的帖」翻到「目标日期」走完了多少
    "progress": 0.0, "start_date": "", "reached_date": "", "cutoff_date": "",
}
_LOCK = threading.Lock()
_STOP = threading.Event()          # 手动停止


def import_status() -> dict:
    with _LOCK:
        return dict(JOB)


def stop_import() -> dict:
    """请求停止当前导入（跑完当前这一页就收尾，已入库的保留）。"""
    with _LOCK:
        if not JOB["running"]:
            return {"ok": False, "error": "当前没有在跑的导入"}
    _STOP.set()
    return {"ok": True, "message": "已请求停止，正在收尾（已经入库的会保留）"}


def _sleep_or_stop(seconds: float) -> bool:
    """可被停止打断的睡眠。返回 True 表示期间收到了停止请求。"""
    end = time.monotonic() + max(0.0, seconds)
    while time.monotonic() < end:
        if _STOP.is_set():
            return True
        time.sleep(0.3)
    return _STOP.is_set()


def _parse_day(s: str, end_of_day: bool = False):
    """'YYYY-MM-DD' → datetime（本地）。空/非法 → None。

    end_of_day=True 时取当天 23:59:59（截止日期要含当天）。
    """
    s = (s or "").strip()
    if not s:
        return None
    try:
        d = datetime.strptime(s[:10], "%Y-%m-%d")
    except Exception:
        return None
    return d.replace(hour=23, minute=59, second=59) if end_of_day else d


def start_import(user: str, containerid: str = "", date_from: str = "",
                 date_to: str = "", caption_type: str = "返图",
                 batch_pages: int = 20, cooldown: int = 10) -> dict:
    """启动**后台**导入。立刻返回，前端轮询 import_status() 看进度。

    date_from / date_to 是用户选的日期范围（含两端，YYYY-MM-DD）：
    date_from 空 → 不限下限；date_to 空 → 今天为止。
    """
    with _LOCK:
        if JOB["running"]:
            return {"ok": False, "error": "已经有一个导入在跑，等它跑完（或点「停止导入」）"}
    if not fetcher.is_configured():
        return {"ok": False, "error": "请先扫码登录获取 cookie"}

    rc = resolve_user(user)
    if not rc.get("ok"):
        return {"ok": False, "error": rc.get("error", "找不到用户")}
    if not rc["candidates"]:
        return {"ok": False, "error": rc.get("message", "找不到用户")}
    uid = rc["candidates"][0]["uid"]
    screen_name = rc["candidates"][0].get("screen_name") or uid

    want_topic = re.split(r"_-_", (containerid or "").strip())[0]
    since = _parse_day(date_from) or datetime(2009, 1, 1)        # 微博最早也就 2009
    until = _parse_day(date_to, end_of_day=True) or datetime.now()
    if since > until:
        return {"ok": False, "error": "起始日期比截止日期还晚，检查一下"}

    _STOP.clear()
    with _LOCK:
        JOB.update(running=True, done=False, ok=None, uid=uid, screen_name=screen_name,
                   page=1, scanned=0, added=0, skipped=0, noise=0,
                   long=0, batch=0, cooldown=0, error="", started=time.time(),
                   progress=0.0, start_date=until.strftime("%Y-%m-%d"), reached_date="",
                   cutoff_date=since.strftime("%Y-%m-%d"),
                   message=f"已开始后台导入 @{screen_name}（自动翻页、中途会休息）")
    threading.Thread(
        target=_worker,
        # cooldown=0 允许 —— 那就只靠每请求 1~2.5s 的 pacing 控制节奏
        args=(uid, screen_name, want_topic, since, until, caption_type,
              max(1, int(batch_pages)), max(0, int(cooldown))),
        daemon=True,
    ).start()
    return {"ok": True, "uid": uid, "screen_name": screen_name,
            "message": f"已开始后台导入 @{screen_name}"}


def _pdate(dt) -> str:
    return dt.strftime("%Y-%m-%d") if dt else ""


def _progress(start_pos, reached, cutoff) -> float:
    """从「最新的帖」往「目标日期」走了多少（0~1）。"""
    if start_pos is None or reached is None:
        return 0.0
    total = (start_pos - cutoff).total_seconds()
    if total <= 0:
        return 1.0
    return max(0.0, min(1.0, (start_pos - reached).total_seconds() / total))


def _worker(uid, screen_name, want_topic, since, until, caption_type, batch_pages, cooldown):
    max_fulltext = 60
    page, in_batch = 1, 0
    scanned = added = skipped = noise = longn = batches = 0
    start_pos = reached = None            # start_pos = 最新那条帖的时间
    reason = None
    try:
        while page <= SAFETY_MAX_PAGES and reason is None:
            if _STOP.is_set():
                reason = "stopped"
                break

            rows, page_newest, empty, st = _scan_page(
                uid, page, want_topic, since, until, max_fulltext)
            if empty:
                reason = "empty"
                break
            scanned += st.get("scanned", 0)
            noise += st.get("noise", 0)
            longn += st.get("long", 0)
            a, s = _flush(rows, caption_type)
            added += a
            skipped += s

            if page_newest is not None:
                if start_pos is None:
                    start_pos = min(page_newest, until)   # 进度从「范围上界」或最新帖算起
                reached = page_newest
            page += 1
            in_batch += 1
            with _LOCK:
                JOB.update(page=page, scanned=scanned, added=added, skipped=skipped,
                           noise=noise, long=longn,
                           progress=_progress(start_pos, reached, since),
                           start_date=_pdate(start_pos), reached_date=_pdate(reached))

            # 整页最新的都早于起始日期 → 扫完了
            if page_newest is not None and page_newest < since:
                reason = "time"
                break

            if in_batch >= batch_pages:                    # 该歇一下了
                in_batch = 0
                batches += 1
                wait = int(cooldown + random.uniform(0, cooldown * 0.6)) if cooldown > 0 else 0
                if wait > 0:
                    with _LOCK:
                        JOB.update(batch=batches, cooldown=wait,
                                   message=f"已翻到 {_pdate(reached) or '—'}，休息 {wait} 秒后继续…")
                    hit_stop = _sleep_or_stop(wait)          # 休息也能被「停止」打断
                    with _LOCK:
                        JOB["cooldown"] = 0
                    if hit_stop:
                        reason = "stopped"
                        break
                else:
                    with _LOCK:
                        JOB["batch"] = batches
        if reason is None:
            reason = "cap"                                # 撞到内部兜底上限（正常不该发生）
    except fetcher.FetchError as e:
        reason = "error"
        with _LOCK:
            JOB["error"] = str(e)
    except Exception as e:                    # 兜底：后台线程的异常不能吞掉
        reason = "error"
        with _LOCK:
            JOB["error"] = f"{type(e).__name__}: {e}"

    end = f"已翻到 {_pdate(reached)}" if reached else "尚未翻页"
    if reason == "stopped":
        msg = (f"@{screen_name}：已手动停止（{end}）。入库 {added} 条。"
               f"再点「开始导入」会从头翻，重复的自动跳过。")
    elif reason == "error":
        msg = f"@{screen_name}：已入 {added} 条后中断（{JOB.get('error')}）。可稍后重试。"
    elif reason == "cap":
        msg = (f"@{screen_name}：翻了 {page - 1} 页到内部兜底上限就停了，"
               f"日期范围内可能还有没扫到的。入库 {added} 条。")
    else:
        why = "时间线到底" if reason == "empty" else "已到日期范围起点"
        msg = (f"@{screen_name}：翻 {page - 1} 页扫完（{why}，{end}），"
               f"入库 {added} 条（重复跳过 {skipped}），忽略水贴 {noise}"
               + (f"，展开长文 {longn} 篇" if longn else ""))
    with _LOCK:
        JOB.update(running=False, done=True, ok=(reason != "error"), cooldown=0,
                   page=page, scanned=scanned, added=added, skipped=skipped,
                   noise=noise, long=longn, progress=1.0 if reason in ("time", "empty") else JOB["progress"],
                   message=msg)
    db.log_run("import_captions", "ok" if reason != "error" else "error", msg)


def wait_import(timeout: float = 600) -> dict:
    """同步等导入结束（测试用；接口层用轮询，不用这个）。"""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not import_status()["running"]:
            break
        time.sleep(0.5)
    return import_status()


def fetch_user_captions(user: str, containerid: str = "", date_from: str = "",
                        date_to: str = "", max_pages: int = 60,
                        caption_type: str = "返图", max_fulltext: int = 60) -> dict:
    """一次性抓取（同步）。跑后台续跑用 start_import()；这个留给测试/脚本。"""
    if not fetcher.is_configured():
        return {"ok": False, "error": "请先扫码登录获取 cookie"}
    rc = resolve_user(user)
    if not rc.get("ok") or not rc["candidates"]:
        return {"ok": False, "error": rc.get("error") or rc.get("message") or "找不到用户"}
    uid = rc["candidates"][0]["uid"]
    screen_name = rc["candidates"][0].get("screen_name") or uid

    want_topic = re.split(r"_-_", (containerid or "").strip())[0]
    since = _parse_day(date_from) or datetime(2009, 1, 1)
    until = _parse_day(date_to, end_of_day=True) or datetime.now()
    max_pages = max(1, min(int(max_pages or 60), 200))

    scanned = added = skipped = noise = longn = 0
    page = 1
    try:
        while page <= max_pages:
            rows, page_newest, empty, st = _scan_page(
                uid, page, want_topic, since, until, max_fulltext)
            if empty:
                break
            scanned += st.get("scanned", 0)
            noise += st.get("noise", 0)
            longn += st.get("long", 0)
            a, s = _flush(rows, caption_type)
            added += a
            skipped += s
            if page_newest is not None and page_newest < since:
                break
            page += 1
    except fetcher.FetchError as e:
        db.log_run("import_captions", "error", str(e))
        return {"ok": bool(added), "error": str(e), "added": added, "scanned": scanned,
                "uid": uid, "screen_name": screen_name,
                "message": f"@{screen_name}：已入 {added} 条后中断（{e}）"}

    msg = (f"@{screen_name}：翻 {page} 页扫 {scanned} 条 → 入文案库 {added}"
           f"（重复跳过 {skipped}），忽略水贴 {noise}"
           + (f"，展开长文 {longn} 篇" if longn else ""))
    db.log_run("import_captions", "ok", msg)
    return {"ok": True, "uid": uid, "screen_name": screen_name, "scanned": scanned,
            "added": added, "skipped": skipped, "noise": noise, "long": longn,
            "pages": page, "message": msg}
