"""超话抓取 —— 走 m.weibo.cn 的 containerid 接口。

要点（2026-10-13 实测）：
- 帖子列表必须用 **`<cid>_-_sort_time`**（「最新」）才严格按时间倒序；裸 cid 是混合排序（含置顶/推荐）。
- 翻页用 `page=1,2,3...`（`cardlistInfo` 为空、没有 since_id）。
- 抓取窗口 = **距上次成功抓取的时间**（至少一个抓取间隔），把窗口内的帖子全抓下来。
- **水贴过滤**：只发几个字/表情、没有实义内容的帖子直接忽略，不入库。
- **不设页数上限**（与「文案库导入」一致）：一直翻到窗口起点或时间线到底；每翻
  `BATCH_PAGES` 页按 `weibo_fetch_cooldown` 休息一下（0=不额外休息），随时可停。
  只留 `SAFETY_MAX_PAGES` 作内部死循环兜底，不给用户当旋钮。
  风控靠「每请求 1~2.5 秒 pacing + 批间休息 + 抓取间隔抖动」控节奏，不靠砍页数。

⚠️ 风控：用小号、低频、遇 418/432 软失败不重试。
"""
import html
import random
import re
import threading
import time
from datetime import datetime, timedelta

import httpx

from .. import db
from . import pacing

API = "https://m.weibo.cn/api/container/getIndex"
DEFAULT_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
              "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 "
              "Mobile/15E148 Safari/604.1")

_TAG_RE = re.compile(r"<[^>]+>")
_MEANINGFUL_RE = re.compile(r"[一-龥A-Za-z0-9]")
MIN_MEANINGFUL = 6          # 实义字符少于这个数 → 判为水贴
RUN_RE = re.compile(r"(.)\1{2,}")   # 3 个以上连续相同字（啊啊啊啊）
REPEAT_RATIO = 0.6          # 单个 2~3 字片段占比超过这个 → 判为水贴（加油加油加油加油）
# 长文在时间线里被截断，末尾挂一个链接，文字是「全文」/「展开」/「更多」
_TRUNC_LINK = re.compile(r"<a[^>]*>\s*(?:全文|展开|更多)\s*</a>\s*$")
_TRUNC_BARE = re.compile(r"\s*(?:全文|展开|更多)\s*$")
SHOW_API = "https://m.weibo.cn/statuses/show"

_REL_SEC = re.compile(r"(\d+)\s*秒前")
_REL_MIN = re.compile(r"(\d+)\s*分钟前")
_REL_HOUR = re.compile(r"(\d+)\s*小时前")
_TODAY = re.compile(r"今天\s*(\d{1,2}):(\d{2})")
_YESTERDAY = re.compile(r"昨天\s*(\d{1,2}):(\d{2})")


class FetchError(Exception):
    """抓取失败，带中文原因（登录失效 / 触发风控 / 接口变更 / 网络超时）。"""


# ---------- 设置（每次调用懒读） ----------

def _cookie() -> str:
    return db.get_setting("weibo_cookie", "") or ""


def _containerid() -> str:
    return db.get_setting("weibo_containerid", "") or ""


def _int_setting(key: str, default: int) -> int:
    try:
        return max(1, int(db.get_setting(key, str(default)) or default))
    except (TypeError, ValueError):
        return default


def is_configured() -> bool:
    return bool(_cookie()) and bool(_containerid())


# ---------- 抓取进度（供前端轮询，自动/手动共用一份） ----------
# 一次只允许一个抓取在跑（调度线程与手动按钮共用同一份状态，避免并发翻页）。

JOB = {
    "running": False, "done": False, "ok": None,
    "phase": "",              # fetch | summarize | done
    "trigger": "",            # auto（定时/开机补抓） | manual（点按钮）
    "page": 1, "fetched": 0, "added": 0, "noise": 0, "real": 0,
    "batch": 0, "cooldown": 0,        # 第几批 / 本批休息剩余秒数
    "window_min": 0, "start_date": "", "reached_date": "", "cutoff_date": "",
    "progress": 0.0, "message": "", "error": "", "started": 0.0,
}
_LOCK = threading.Lock()
_STOP = threading.Event()


def fetch_status() -> dict:
    with _LOCK:
        return dict(JOB)


def is_running() -> bool:
    with _LOCK:
        return bool(JOB["running"])


def stop_fetch() -> dict:
    """请求停止当前抓取（跑完当前这一页就收尾，已入库的保留）。"""
    with _LOCK:
        if not JOB["running"]:
            return {"ok": False, "error": "当前没有在跑的抓取"}
    _STOP.set()
    return {"ok": True, "message": "已请求停止，正在收尾（已经入库的会保留）"}


def _set(**kw):
    with _LOCK:
        JOB.update(kw)


def set_phase(phase: str, message: str = ""):
    """抓取完切到「总结中」阶段时用（保持 running，让前端进度条不断档）。"""
    _set(running=True, done=False, phase=phase, message=message)


def finalize():
    _set(running=False, done=True, phase="done")


def _pdate(dt) -> str:
    return dt.strftime("%Y-%m-%d %H:%M") if dt else ""


def _progress(start_pos, reached, cutoff) -> float:
    """从「最新那条帖」往「窗口起点」走了多少（0~1）。"""
    if start_pos is None or reached is None:
        return 0.0
    total = (start_pos - cutoff).total_seconds()
    if total <= 0:
        return 1.0
    return max(0.0, min(1.0, (start_pos - reached).total_seconds() / total))


# 抓取**不设页数上限**（和「文案库导入」一致）：一直翻到窗口起点或时间线到底。
# 这个常量只是防跑飞的死循环保险，不给用户当旋钮 —— 正常靠「翻到窗口起点」结束。
SAFETY_MAX_PAGES = 2000
BATCH_PAGES = 20            # 每翻多少页歇一下（与文案库导入一致）


def _cooldown_setting() -> int:
    """每 BATCH_PAGES 页休息几秒。允许 0（=不额外休息，只靠 pacing 控节奏）。"""
    try:
        return max(0, int(db.get_setting("weibo_fetch_cooldown", "10") or 10))
    except (TypeError, ValueError):
        return 10


def _sleep_or_stop(seconds: float) -> bool:
    """可被「停止抓取」打断的睡眠。返回 True 表示期间收到了停止请求。"""
    end = time.monotonic() + max(0.0, seconds)
    while time.monotonic() < end:
        if _STOP.is_set():
            return True
        time.sleep(0.3)
    return _STOP.is_set()


def _sorted_cid() -> str:
    """「最新」排序的 containerid：去掉已有后缀，拼上 `_-_sort_time`。"""
    base = re.split(r"_-_", _containerid().strip())[0]
    return base + "_-_sort_time"


def _headers() -> dict:
    """请求头。

    原则：**和自称的身份保持一致**（UA 说是 iPhone Safari，那就把 Safari 会带的头带齐），
    这是「写正确」而不是「伪装」——少发头反而不一致。
    ⚠️ 不做指纹工程（TLS 冒用 / 头顺序随机化 / 设备伪造那一类）：那是规避检测，
       而且解决不了频次限制，该限还是限。
    Accept-Encoding 交给 httpx 自己设（它会带 gzip/br 并负责解压，手写反而弄坏）。
    """
    ua = (db.get_setting("weibo_user_agent", "") or "").strip() or DEFAULT_UA
    return {
        "User-Agent": ua,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh-Hans;q=0.9",
        "Referer": "https://m.weibo.cn/",
        "X-Requested-With": "XMLHttpRequest",
        "Cookie": _cookie(),
    }


# ---------- HTTP ----------

def _get_index(page: int = 1, since_id: str = "", cid: str = "") -> dict:
    """取一页。任何异常都转成 FetchError（中文原因）。cid 空则用设置里的（自动加 _sort_time）。"""
    params = {"containerid": cid or _sorted_cid(), "page": page}
    if since_id:
        params["since_id"] = since_id
    pacing.pace()                       # 不背靠背连发，间隔带抖动
    try:
        r = httpx.get(API, params=params, headers=_headers(),
                      timeout=15.0, follow_redirects=True)
    except httpx.TimeoutException:
        raise FetchError("网络超时（15s）")
    except httpx.HTTPError as e:
        raise FetchError(f"网络错误：{e}")

    # 微博的风控/验证状态码：418 已被限制、432 需要验证、414 同样
    if r.status_code in (418, 432, 414):
        raise FetchError(
            f"触发风控（HTTP {r.status_code}）—— 多半是 cookie 缺失/失效，或频率过高。"
            "请确认已填小号 cookie，并暂停一段时间再试")
    if r.status_code in (401, 403):
        raise FetchError(f"被拒绝（HTTP {r.status_code}）——cookie 可能已失效")
    if r.status_code != 200:
        raise FetchError(f"HTTP {r.status_code}")

    if "json" not in r.headers.get("content-type", "").lower():
        raise FetchError("返回非 JSON——多半是登录失效或触发风控页")
    try:
        data = r.json()
    except Exception:
        raise FetchError("响应不是合法 JSON——接口可能已变更")
    if data.get("ok") != 1:
        raise FetchError(f"接口返回 ok={data.get('ok')}——cookie 失效或 containerid 有误")
    return data.get("data") or {}


# ---------- 解析 ----------

def _clean(text: str) -> str:
    """正文 HTML → 纯文本。顺手把长文被截断时挂的「全文/展开/更多」标记去掉，
    否则它会留在事件正文结尾。"""
    t = _TRUNC_LINK.sub("", text or "")
    t = _TRUNC_BARE.sub("", html.unescape(_TAG_RE.sub("", t)))
    return t.strip()


def full_text(mid: str) -> str:
    """取长文全文。失败返回空串（调用方回退到截断文本）。"""
    from . import pacing
    pacing.pace()
    try:
        r = httpx.get(SHOW_API, params={"id": mid}, headers=_headers(),
                      timeout=15.0, follow_redirects=True)
        j = r.json()
        if j.get("ok") == 1:
            return ((j.get("data") or {}).get("text") or "")
    except Exception:
        pass
    return ""


def _parse_time(s: str):
    """微博时间 → 本地 naive datetime。解析不了返回 None（不会因此丢帖）。"""
    s = (s or "").strip()
    if not s:
        return None
    if s in ("刚刚", "现在"):
        return datetime.now()
    m = _REL_SEC.search(s)
    if m:
        return datetime.now() - timedelta(seconds=int(m.group(1)))
    m = _REL_MIN.search(s)
    if m:
        return datetime.now() - timedelta(minutes=int(m.group(1)))
    m = _REL_HOUR.search(s)
    if m:
        return datetime.now() - timedelta(hours=int(m.group(1)))
    for pat, days in ((_TODAY, 0), (_YESTERDAY, 1)):
        m = pat.search(s)
        if m:
            d = datetime.now() - timedelta(days=days)
            return d.replace(hour=int(m.group(1)), minute=int(m.group(2)),
                             second=0, microsecond=0)
    try:                                    # Tue Oct 13 23:28:11 +0800 2026
        return datetime.strptime(s, "%a %b %d %H:%M:%S %z %Y").astimezone().replace(tzinfo=None)
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    return None


def _repeat_ratio(t: str) -> float:
    """最频繁的 2 字 / 3 字片段覆盖了文本多大比例。

    「加油加油加油加油天天开心」→ 0.67，「好棒好棒好棒好棒好棒」→ 1.0，
    正常文案如「今天路透拍到哥哥穿白色羽绒服」→ 0.06。
    """
    if len(t) < 4:
        return 0.0
    best = 0.0
    for n in (2, 3):
        segs = [t[i:i + n] for i in range(0, len(t) - n + 1, n)]
        if len(segs) < 2:
            continue
        cnt = {}
        for s in segs:
            cnt[s] = cnt.get(s, 0) + 1
        top = max(cnt.values())
        best = max(best, (top * n) / len(t))
    return best


def _is_noise(content: str) -> bool:
    """水贴判定：只算**本人自己写的话**，然后看「实义内容」够不够。

    三条规则（只看长度会漏掉「加油加油加油加油天天开心」这种）：
      1. `//@某人:...` 是**转发的别人的内容**，整段剥掉；
         再剥 `#话题#` / `@` / 链接 / `[表情]`
      2. 3 个以上连续相同字压成 1 个（「啊啊啊啊啊」→「啊」）
      3. 实义字符 < 6 → 水贴；或**单个片段重复占比 > 60%** → 水贴
    """
    t = content or ""
    t = re.sub(r"//@[^\s]*.*$", "", t, flags=re.S)   # //@转发链（含其后全部内容）
    t = re.sub(r"#.*?#", "", t)                      # #话题#
    t = re.sub(r"@[^\s@]+", "", t)                   # @某人
    t = re.sub(r"https?://\S+", "", t)               # 链接
    t = re.sub(r"\[[^\]]{1,6}\]", "", t)             # [表情]
    core = "".join(_MEANINGFUL_RE.findall(t))
    if not core:
        return True
    core = RUN_RE.sub(r"\1", core)                   # 压掉连续重复字
    if len(core) < MIN_MEANINGFUL:
        return True
    return _repeat_ratio(core) > REPEAT_RATIO


def _parse_cards(data: dict) -> list:
    """从 data.cards 里挑出带 mblog 的正文卡。返回 [{mid, author, content, posted_at, dt}]。"""
    out = []
    for card in data.get("cards") or []:
        mb = card.get("mblog")
        if not isinstance(mb, dict):
            continue
        mid = str(mb.get("mid") or mb.get("id") or "").strip()
        raw = mb.get("text") or ""
        content = _clean(raw)
        if not mid or not content:
            continue
        posted_at = (mb.get("created_at") or "").strip()
        out.append({
            "mid": mid,
            "author": ((mb.get("user") or {}).get("screen_name") or "").strip(),
            "content": content,
            "posted_at": posted_at,
            "dt": _parse_time(posted_at),
            # 长文被截断了：要么标了 isLongText，要么末尾挂着「全文/展开/更多」链接
            "long": bool(mb.get("isLongText")) or bool(_TRUNC_LINK.search(raw)),
        })
    return out


# ---------- 入库 ----------

def _exists(mid: str) -> bool:
    return db.one("SELECT 1 FROM posts WHERE mid = ? LIMIT 1", (mid,)) is not None


def _insert(items: list) -> int:
    if not items:
        return 0
    rows = [("weibo", it["mid"], it["author"], it["content"], it["posted_at"], 0, db.now())
            for it in items]
    with db.tx() as conn:
        before = conn.total_changes
        conn.executemany(
            "INSERT OR IGNORE INTO posts"
            "(source, mid, author, content, posted_at, processed, created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            rows,
        )
        return conn.total_changes - before


# ---------- 抓取窗口 ----------

def _window_days() -> int:
    """抓取窗口上限（天）。0 = 不限。"""
    try:
        return max(0, int(db.get_setting("weibo_fetch_window_days", "7") or 7))
    except (TypeError, ValueError):
        return 7


def _window_minutes() -> int:
    """抓取窗口（分钟）：至少一个抓取间隔；距上次成功抓取更久则放大，免得停机期间漏帖。

    上限由设置 `weibo_fetch_window_days` 决定（默认 7 天，**0 = 不限** ——
    那种情况下真正的兜底是 SAFETY_MAX_PAGES，跑完会如实告知被兜底截断）。
    """
    win = _int_setting("weibo_fetch_interval_min", 60)
    last = db.one("SELECT created_at FROM runs WHERE job='fetch' AND status='ok' "
                  "ORDER BY id DESC LIMIT 1")
    if last:
        try:
            gap = (datetime.now() - datetime.strptime(
                last["created_at"], "%Y-%m-%d %H:%M:%S")).total_seconds() / 60
            win = max(win, int(gap) + 2)
        except Exception:
            pass
    days = _window_days()
    if days > 0:
        win = min(win, days * 24 * 60)
    return win


# ---------- 主入口 ----------

def fetch_new(cookie: str = "", containerid: str = "",
              trigger: str = "manual", keep_open: bool = False) -> dict:
    """抓「最新」里、窗口内的帖子入库。返回 dict，**不抛异常**。

    **不设页数上限**（与「文案库导入」同一逻辑）：一直翻到窗口起点（碰到早于窗口的
    帖子）或时间线到底为止；每翻 BATCH_PAGES 页按设置休息一下，休息也能被「停止」打断。
    只留内部兜底 SAFETY_MAX_PAGES 防死循环，不给用户当旋钮。

    成功：{ok, fetched, added, skipped, noise, pages, stopped, window_min, message}
    失败：{ok:False, error, ...}   （软失败，绝不重试）

    trigger: manual（点按钮）/ auto（定时或开机补抓）——只用于进度显示。
    全程把进度写进模块级 JOB，供前端轮询；**一次只允许一个抓取在跑**。
    """
    if cookie:
        db.set_setting("weibo_cookie", cookie)
    if containerid:
        db.set_setting("weibo_containerid", containerid)
    if not is_configured():
        return {"ok": False, "error": "未配置 cookie 或 containerid"}

    with _LOCK:
        if JOB["running"]:
            return {"ok": False, "error": "已经在抓取中，等它跑完（或点「停止抓取」）"}
        JOB.update(running=True, done=False, ok=None, phase="fetch", trigger=trigger,
                   page=1, fetched=0, added=0, noise=0, real=0, progress=0.0,
                   message="开始抓取…", error="", started=time.time(),
                   start_date="", reached_date="", cutoff_date="", batch=0, cooldown=0)
    _STOP.clear()

    window_min = _window_minutes()
    now = datetime.now()
    cutoff = now - timedelta(minutes=window_min)
    cooldown = _cooldown_setting()
    _set(window_min=window_min, start_date=_pdate(now), cutoff_date=_pdate(cutoff),
         message=f"窗口 {window_min} 分钟：从最新往前翻，直到翻到窗口起点…")

    max_fulltext = _int_setting("weibo_max_fulltext", 40)   # 每次最多取几篇长文全文
    fetched = added = noise = real_seen = longtxt = 0
    stopped = None              # window | empty | stopped | cap
    page = 1                    # 正在翻的页码
    in_batch = 0
    batches = 0
    start_pos = reached = None  # 窗口内「最新那条」与「当前翻到最旧那条」的时间
    try:
        try:
            while page <= SAFETY_MAX_PAGES and stopped is None:
                if _STOP.is_set():
                    stopped = "stopped"
                    break
                data = _get_index(page)
                items = _parse_cards(data)
                if not items:
                    stopped = "empty"         # 时间线到底
                    break
                fetched += len(items)

                reached_old = False
                fresh = []
                for it in items:
                    if it["dt"] is not None:
                        if start_pos is None or it["dt"] > start_pos:
                            start_pos = it["dt"]
                        if reached is None or it["dt"] < reached:
                            reached = it["dt"]
                    if it["dt"] is not None and it["dt"] < cutoff:
                        reached_old = True    # 「最新」严格倒序：碰到旧帖就到头了
                        continue
                    if it.get("long") and longtxt < max_fulltext:
                        full = full_text(it["mid"])   # 长文取全文，别让正文停在「全文」
                        if full:
                            it["content"] = _clean(full)
                            longtxt += 1
                    if _is_noise(it["content"]):  # 水贴：只几个字 / 无意义转发 → 丢
                        noise += 1
                        continue
                    real_seen += 1
                    fresh.append(it)
                added += _insert(fresh)           # mid 唯一 → 自动去重

                _set(page=page, fetched=fetched, added=added, noise=noise, real=real_seen,
                     reached_date=_pdate(reached),
                     progress=_progress(start_pos, reached, cutoff),
                     message=(f"翻到第 {page} 页 · 已到 {_pdate(reached) or '—'}"
                              f"（目标 {_pdate(cutoff)}）· 新增 {added}"))
                page += 1
                in_batch += 1

                if reached_old:
                    stopped = "window"        # 已够到窗口起点 → 抓完
                    break

                if in_batch >= BATCH_PAGES:   # 该歇一下了（与文案库导入一致）
                    in_batch = 0
                    batches += 1
                    wait = int(cooldown + random.uniform(0, cooldown * 0.6)) if cooldown > 0 else 0
                    if wait > 0:
                        _set(batch=batches, cooldown=wait,
                             message=(f"已翻 {page - 1} 页到 {_pdate(reached) or '—'}，"
                                      f"休息 {wait} 秒后继续…"))
                        hit = _sleep_or_stop(wait)      # 休息也能被「停止」打断
                        _set(cooldown=0)
                        if hit:
                            stopped = "stopped"
                            break
                    else:
                        _set(batch=batches)
            if stopped is None:
                stopped = "cap"               # 撞到内部兜底（正常不该发生）
        except FetchError as e:
            if added:
                db.log_run("fetch", "partial", f"部分成功（已入 {added} 帖）后失败：{e}")
            _set(ok=False, error=str(e), message=f"失败：{e}")
            return {"ok": False, "error": str(e), "fetched": fetched, "added": added}

        pages_done = page - 1
        skipped = max(fetched - added - noise, 0)
        end = f"已到 {_pdate(reached)}" if reached else "尚未翻页"
        if stopped == "stopped":
            msg = (f"已手动停止（{end}）：翻 {pages_done} 页，新增 {added} 条。"
                   f"再点「抓取」会从最新重翻，重复的自动跳过。")
        elif stopped == "cap":
            msg = (f"翻了 {pages_done} 页到内部兜底上限就停了，窗口内可能还有没抓到的。"
                   f"新增 {added} 条。")
        else:
            why = "时间线到底" if stopped == "empty" else "已到窗口起点"
            msg = (f"翻 {pages_done} 页扫完（{why}，{end}）：窗口 {window_min} 分钟取 "
                   f"{fetched} 条 → 真帖 {real_seen}，新增 {added}（去重跳过 {skipped}），"
                   f"忽略水贴 {noise}"
                   + (f"，展开长文 {longtxt} 篇" if longtxt else ""))
        db.log_run("fetch", "partial" if stopped == "cap" else "ok", msg)
        kw = dict(ok=True, page=pages_done, fetched=fetched, added=added, noise=noise,
                  real=real_seen, batches=batches, message=msg)
        if stopped in ("window", "empty"):
            kw["progress"] = 1.0              # 跑完了，进度条拉满
        _set(**kw)
        return {"ok": True, "fetched": fetched, "added": added, "skipped": skipped,
                "noise": noise, "real": real_seen, "pages": pages_done, "stopped": stopped,
                "window_min": window_min, "batches": batches, "message": msg}
    finally:
        # keep_open=True：调用方（run_fetch）后面还要接「总结」阶段，别在这里收尾，
        # 否则前端会先看到 done 而停掉轮询，错过总结进度。
        if not keep_open:
            finalize()


# ---------- 手动粘贴（保留） ----------

def ingest_manual(text: str, author: str = "", posted_at: str = "") -> int:
    """手动粘贴的帖子入库。每行算一条（不过滤水贴——用户自己贴的）。"""
    n = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        db.run(
            "INSERT INTO posts(source, author, content, posted_at, processed, created_at) "
            "VALUES('manual',?,?,?,0,?)",
            (author, line, posted_at, db.now()),
        )
        n += 1
    return n


def count_pending() -> int:
    r = db.one("SELECT COUNT(*) c FROM posts WHERE processed=0")
    return r["c"] if r else 0
