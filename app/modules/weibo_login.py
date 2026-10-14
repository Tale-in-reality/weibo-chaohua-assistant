"""扫码登录微博 —— 自动获取 cookie（并据此查找超话 containerid）。

流程（2026-10-13 实测通）：
  1. GET  login.sina.com.cn/sso/qrcode/image?entry=miniblog&size=180&callback=STK_1
     → {"retcode":20000000,"data":{"qrid":"...","image":"https://v2.qr.weibo.cn/..."}}
     （必须带 callback，否则返回空 body）
  2. GET  login.sina.com.cn/sso/qrcode/check?entry=miniblog&qrid=<qrid>&callback=STK_1
     → retcode 50114001 未使用 / 50114002 已扫描待确认 / 20000000 成功（data.alt）
  3. retcode=20000000 时 data.alt 是**一次性令牌**（形如 ALT-xxxx），不是 URL：
     GET sso/login.php?entry=qrcodesso&returntype=TEXT&crossdomain=1&cdult=3
         &domain=weibo.com&alt=<alt>&savestate=30&callback=STK_1
     → 响应含 crossDomainUrlList，逐个访问才种上 cookie（拿到 SUB）
  4. cookie 写进 settings.weibo_cookie

⚠️ 用小号扫。登录态只在内存里保存一次（单用户单会话），二维码 120 秒过期。
"""
import base64
import difflib
import html
import json
import re
import time

import httpx

from .. import db
from . import pacing

IMG_API = "https://login.sina.com.cn/sso/qrcode/image"
CHECK_API = "https://login.sina.com.cn/sso/qrcode/check"
LOGIN_API = "https://login.sina.com.cn/sso/login.php"
SEARCH_API = "https://m.weibo.cn/api/container/getIndex"

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
_HEADERS = {"User-Agent": _UA, "Referer": "https://weibo.com/",
            "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9"}

SESSION_TTL = 120          # 秒
_CB = "STK_1"              # JSONP 回调名（服务端要求带 callback 才有返回）

# 单会话状态（qrid + 带 cookie jar 的 client）
_SESSION = {"qrid": "", "client": None, "created": 0.0}


def _jsonp(text: str) -> dict:
    """从 `window.STK_x && STK_x({...});` 里抠出 JSON 对象。"""
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j <= i:
        raise ValueError("响应里没有 JSON")
    return json.loads(text[i:j + 1])


MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 "
             "Mobile/15E148 Safari/604.1")


def _mobile_headers(cookie: str) -> dict:
    # 与 fetcher._headers() 保持一致（同一个身份，别一处一套头）
    return {"User-Agent": MOBILE_UA, "Cookie": cookie,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh-Hans;q=0.9",
            "Referer": "https://m.weibo.cn/",
            "X-Requested-With": "XMLHttpRequest"}


def _cookie_str(client: httpx.Client, prefer: str = "weibo.cn") -> str:
    """拼 cookie 头。同名 cookie 优先取域名匹配 prefer 的那个——
    m.weibo.cn 认的是 `.weibo.cn` 域的 SUB，别被 `.weibo.com` 的覆盖掉。"""
    chosen = {}
    for c in client.cookies.jar:
        cur = chosen.get(c.name)
        if cur is None:
            chosen[c.name] = c
        elif prefer in (c.domain or "") and prefer not in (cur.domain or ""):
            chosen[c.name] = c
    return "; ".join(f"{c.name}={c.value}" for c in chosen.values())


def _inventory(client: httpx.Client) -> list:
    """cookie 清单（名@域，不含值）——排障用。"""
    return sorted({f"{c.name}@{c.domain}" for c in client.cookies.jar})


def _has_sub(client: httpx.Client, domain_hint: str) -> bool:
    return any(c.name == "SUB" and domain_hint in (c.domain or "")
               for c in client.cookies.jar)


def _m_weibo_config(cookie: str) -> dict:
    """用 cookie 问 m.weibo.cn/api/config，拿登录态数据（login/uid…）。"""
    pacing.pace()                      # 开机 / 切「推送」页都会走到这里，必须节流
    try:
        r = httpx.get("https://m.weibo.cn/api/config",
                      headers=_mobile_headers(cookie), timeout=15, follow_redirects=True)
        return r.json().get("data") or {}
    except Exception:
        return {}


def _m_weibo_login_ok(cookie: str) -> bool:
    return bool(_m_weibo_config(cookie).get("login"))


def _screen_name(cookie: str, uid: str) -> str:
    """拿登录账号的昵称（比 uid 直观）。"""
    if not uid:
        return ""
    pacing.pace()
    try:
        r = httpx.get(SEARCH_API, params={"type": "uid", "value": uid},
                      headers=_mobile_headers(cookie), timeout=15, follow_redirects=True)
        info = (r.json().get("data") or {}).get("userInfo") or {}
        return str(info.get("screen_name") or "")
    except Exception:
        return ""


# 登录态结果缓存：前端在「开机」和「切到推送页」时都会问一次，
# 不缓存就变成「反复开 app 反复打微博」——这是风控隐患。缓存按 cookie 值区分，
# cookie 一变（重新登录 / 清除）缓存自动失效。
_STATUS_CACHE = {"key": None, "at": 0.0, "val": None}
STATUS_TTL = 600        # 10 分钟


def login_status(force: bool = False) -> dict:
    """当前保存的 cookie 还有没有效。给前端显示「登录态」用。

    结果缓存 10 分钟（force=True 可强制刷新，给「刷新登录态」按钮用）。
    """
    cookie = db.get_setting("weibo_cookie", "")
    c = _STATUS_CACHE
    now = time.monotonic()
    if (not force and c["val"] is not None and c["key"] == cookie
            and (now - c["at"]) < STATUS_TTL):
        return c["val"]

    if not cookie:
        out = {"ok": True, "has_cookie": False, "valid": False,
               "message": "未登录，请扫码"}
    else:
        cfg = _m_weibo_config(cookie)
        valid = bool(cfg.get("login"))
        uid = str(cfg.get("uid") or "")
        out = {"ok": True, "has_cookie": True, "valid": valid, "uid": uid,
               "screen_name": _screen_name(cookie, uid) if valid else "",
               "message": "登录态：有效" if valid else "登录态：已过期，请重新扫码"}

    _STATUS_CACHE.update(key=cookie, at=now, val=out)
    return out


def resolve_chaohua(containerid: str) -> dict:
    """用 containerid 反查超话名字，并缓存进 settings（供界面显眼显示）。"""
    cid = (containerid or "").strip()
    if not cid:
        return {"ok": False, "name": "", "error": "containerid 为空"}
    cookie = db.get_setting("weibo_cookie", "")
    pacing.pace()                      # 开机时前端会调它反查超话名，必须节流
    try:
        r = httpx.get(SEARCH_API, params={"containerid": cid},
                      headers=_mobile_headers(cookie), timeout=15, follow_redirects=True)
        info = (r.json().get("data") or {}).get("pageInfo") or {}
        name = str(info.get("page_title") or info.get("title_top") or info.get("nick") or "")
    except Exception as e:
        return {"ok": False, "name": "", "error": f"解析失败：{e}"}
    if name:
        db.set_setting("weibo_container_name", name)
    return {"ok": bool(name), "name": name,
            "error": "" if name else "没能解析出超话名（containerid 可能不对）"}


# ---------- 扫码登录 ----------

def start() -> dict:
    """生成二维码。返回 {ok, image(dataURL), qrid?, error?}。"""
    client = httpx.Client(headers=_HEADERS, timeout=15, follow_redirects=True)
    try:
        r = client.get(IMG_API, params={"entry": "miniblog", "size": 180, "callback": _CB})
        j = _jsonp(r.text)
        if j.get("retcode") != 20000000:
            return {"ok": False, "error": f"取二维码失败（retcode={j.get('retcode')}）"}
        data = j.get("data") or {}
        qrid, image_url = data.get("qrid"), data.get("image")
        if not qrid or not image_url:
            return {"ok": False, "error": "取二维码失败：返回缺 qrid/image"}

        img = client.get(image_url)
        if img.status_code != 200 or not img.content:
            return {"ok": False, "error": f"下载二维码失败（HTTP {img.status_code}）"}
        mime = img.headers.get("content-type", "image/jpeg").split(";")[0]
        data_url = f"data:{mime};base64,{base64.b64encode(img.content).decode()}"

        _SESSION.update(qrid=qrid, client=client, created=time.monotonic())
        return {"ok": True, "image": data_url, "qrid": qrid}
    except Exception as e:
        return {"ok": False, "error": f"取二维码失败：{e}"}


def poll() -> dict:
    """轮询扫码状态。返回 {ok, status: waiting|scanned|ok|expired|error, ...}。"""
    qrid, client = _SESSION.get("qrid"), _SESSION.get("client")
    if not qrid or client is None:
        return {"ok": False, "status": "idle", "error": "还没有开始扫码，请先点「扫码登录」"}
    if time.monotonic() - _SESSION.get("created", 0) > SESSION_TTL:
        _clear()
        return {"ok": False, "status": "expired", "error": "二维码已过期，请重新扫码"}
    try:
        r = client.get(CHECK_API, params={"entry": "miniblog", "qrid": qrid, "callback": _CB})
        j = _jsonp(r.text)
    except Exception as e:
        return {"ok": False, "status": "error", "error": f"轮询失败：{e}"}

    ret = j.get("retcode")
    if ret == 50114001:
        return {"ok": True, "status": "waiting", "message": "等待扫码…"}
    if ret == 50114002:
        return {"ok": True, "status": "scanned", "message": "已扫码，请在手机上确认"}
    if ret in (50114004, 50114015):
        _clear()
        return {"ok": False, "status": "expired", "error": "二维码已失效/取消，请重新扫码"}

    if ret == 20000000:
        alt = str((j.get("data") or {}).get("alt") or "").strip()
        if not alt:
            return {"ok": False, "status": "error", "error": "登录成功但未拿到 alt 令牌"}
        try:
            cookie = _exchange_cookie(client, alt)
        except Exception as e:
            return {"ok": False, "status": "error", "error": f"换取 cookie 失败：{e}"}
        inv = _inventory(client)
        if "SUB=" not in cookie:
            return {"ok": False, "status": "error", "cookies": inv,
                    "error": "登录完成但没拿到 SUB（可能被风控拦截），请重试"}
        db.set_setting("weibo_cookie", cookie)
        # 当场验证 m.weibo.cn 是否认可（否则等去搜索才发现 login:false 更绕）
        try:
            pacing.pace()
            httpx.get("https://m.weibo.cn/", headers=_mobile_headers(cookie), timeout=15)
        except Exception:
            pass
        verified = _m_weibo_login_ok(cookie)
        _clear()
        return {"ok": True, "status": "ok", "verified": verified, "cookies": inv,
                "cookie_len": len(cookie),
                "message": "登录成功，cookie 已保存" if verified
                           else "登录完成，但 m.weibo.cn 未认可该 cookie（可能需重试或换入口）"}

    return {"ok": False, "status": "error",
            "error": f"未知状态（retcode={ret} {j.get('msg', '')}）"}


def _exchange_cookie(client: httpx.Client, alt: str) -> str:
    """用 alt 令牌换 cookie：请求 login.php，再逐个访问 crossDomainUrlList 种 cookie。

    关键：m.weibo.cn 认的是 **`.weibo.cn` 域的 SUB**，所以要优先拿 weibo.cn 的跳转链。
    entry/domain 换着试，直到手里出现 `.weibo.cn` 的 SUB。
    """
    attempts = [("qrcodesso", "weibo.cn"), ("qrcodesso", "weibo.com"),
                ("miniblog", "weibo.cn"), ("miniblog", "weibo.com")]
    first_text, tried = "", []
    for entry, domain in attempts:
        try:
            r = client.get(LOGIN_API, params={
                "entry": entry, "returntype": "TEXT", "crossdomain": "1",
                "cdult": "3", "domain": domain, "alt": alt,
                "savestate": "30", "callback": _CB,
            })
        except Exception as e:
            tried.append(f"{entry}/{domain}:ERR {e}")
            continue
        urls = _extract_urls(r.text)
        if not first_text:
            first_text = r.text                      # alt 一次性，第一次响应才有内容
        tried.append(f"{entry}/{domain}:len={len(r.text)},urls={len(urls)}")
        for u in urls[:10]:
            for candidate in (u, u + ("&" if "?" in u else "?") + "action=login"):
                try:
                    client.get(candidate)
                except Exception:
                    continue
        if _has_sub(client, "weibo.cn") or _has_sub(client, "weibo.com"):
            break
    # 诊断写进 runs 表：扫一次我读库即可，免得来回复制
    db.log_run("login", "debug",
               "tried=" + " | ".join(tried) +
               " || inventory=" + json.dumps(_inventory(client)) +
               " || resp1=" + (first_text or "")[:800])
    return _cookie_str(client, prefer="weibo.cn")


def _extract_urls(text: str) -> list:
    """从响应文本里抠出所有 http(s) 链接。
    ⚠️ 必须先还原 `\\/`、`\\u0026` 转义再正则——响应里 URL 形如 `https:\\/\\/...`，
    若先匹配（要求字面 `https://`）会一条都抠不出来。"""
    t = html.unescape(text or "").replace("\\/", "/").replace("\\u0026", "&")
    out = []
    for u in re.findall(r'https?://[^\s"\'\\,\}\]]+', t):
        u = u.rstrip(";)")
        if u not in out:
            out.append(u)
    return out


def _clear():
    _SESSION.update(qrid="", client=None, created=0.0)


# ---------- 查找超话 containerid ----------

_TOPIC_CID_RE = re.compile(r"containerid=(100808[0-9A-Za-z]+)")
_PAGEID_RE = re.compile(r"pageid=(100808[0-9A-Za-z]+)")
# 搜超话：type=1 综合含 toolbar 超话入口，type=2/11 里超话以 topic 卡出现 —— 合并取并集
_SEARCH_TYPES = (1, 2, 11)


def find_containerid(keyword: str) -> dict:
    """按关键词搜超话，返回按相似度排序的候选 [{containerid, title, score}]。"""
    keyword = (keyword or "").strip()
    if not keyword:
        return {"ok": False, "error": "请输入超话名称/关键词"}
    cookie = db.get_setting("weibo_cookie", "")
    if not cookie:
        return {"ok": False, "error": "请先扫码登录获取 cookie"}

    headers = dict(_HEADERS)
    headers.update({"Cookie": cookie, "Referer": "https://m.weibo.cn/",
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json, text/plain, */*"})
    topics, ok_any = [], False
    for ty in _SEARCH_TYPES:
        pacing.pace()          # 三种搜索类型是背靠背连发，这里拉开间隔
        try:
            r = httpx.get(SEARCH_API,
                          params={"containerid": f"100103type={ty}&q={keyword}",
                                  "page_type": "searchall"},
                          headers=headers, timeout=15, follow_redirects=True)
            j = r.json()
        except Exception:
            continue
        if j.get("ok") == 1:
            ok_any = True
            _collect_topics(j, topics)
    if not ok_any:
        return {"ok": False, "error": "搜索失败—— cookie 可能失效或需验证"}
    if not topics:
        return {"ok": True, "candidates": [],
                "message": "没找到超话，换个更精确的名称试试"}

    ranked = _rank(keyword, topics)
    cands = ranked[:30]                                     # 全部按相似度排序，前端滚动看更多
    return {"ok": True, "candidates": cands,
            "message": f"共 {len(topics)} 个，按相似度排序（列表内滚动看更多）"}


def _add_topic(out: list, cid: str, title):
    if not cid:
        return
    t = re.sub(r"^【超话】", "", str(title or "")).strip()
    for i, (c, old) in enumerate(out):
        if c == cid:
            if t and not old:            # 补上更好的标题
                out[i] = (cid, t)
            return
    out.append((cid, t))


def _collect_topics(obj, out: list):
    """递归收集 (containerid, 标题)。覆盖搜索里超话出现的几种形式。"""
    if isinstance(obj, dict):
        pu = obj.get("page_url")
        if obj.get("type") == "topic" and isinstance(pu, str):
            m = _TOPIC_CID_RE.search(pu)
            if m:
                _add_topic(out, m.group(1), obj.get("page_title"))
        if obj.get("bd_object_type") == "super_topic":          # darwin_tags
            mu = str(obj.get("mapi_url") or "")
            m = _PAGEID_RE.search(mu) or _TOPIC_CID_RE.search(mu)
            if m:
                _add_topic(out, m.group(1), obj.get("display_name"))
        s = obj.get("scheme")
        if isinstance(s, str) and "containerid=100808" in s:    # toolbar/按钮入口
            m = _TOPIC_CID_RE.search(s)
            if m:
                _add_topic(out, m.group(1), obj.get("page_title") or obj.get("title"))
        # 注：不再从帖子 topic_id 捞（拿不到标题 → 没法模糊匹配，纯噪音）
        for v in obj.values():
            _collect_topics(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _collect_topics(v, out)


def _rank(keyword: str, topics: list) -> list:
    """按包含关系 + difflib 相似度排序。返回 [{containerid, title, score}]。"""
    kw = keyword.strip()
    out = []
    for cid, title in topics:
        t = title or ""
        if kw and t and (kw in t or t in kw):
            s = 0.9 + 0.1 * min(len(kw), len(t)) / max(len(t), len(kw), 1)
        else:
            s = difflib.SequenceMatcher(None, kw, t).ratio() if t else 0.0
        out.append({"containerid": cid, "title": t, "score": round(s, 3)})
    out.sort(key=lambda x: -x["score"])
    return out

