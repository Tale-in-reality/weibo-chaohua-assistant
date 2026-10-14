"""FastAPI 路由。"""
import base64
from datetime import date

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import autostart, db, llm, scheduler, winref
from .config import APP_NAME, VERSION, WEB_DIR
from .notify import last_error, notify
from .modules import (captions, events, fetcher, housekeeping, setup, style,
                      summarize, terms, vision, weibo_login, weibo_user)

app = FastAPI(title=APP_NAME, version=VERSION)


@app.middleware("http")
async def _no_cache(request, call_next):
    """本地应用：禁掉浏览器缓存，改了前端立刻生效（否则 app.js 缓存会跑旧代码）。"""
    resp = await call_next(request)
    resp.headers["Cache-Control"] = "no-store"
    return resp


# 改动类请求（以及会改变界面状态的 /api/navigate）必须带这个自定义头。
# 浏览器里第三方网页发「简单请求」时**无法**自定义头（会被 CORS 预检拦住），
# 因此这一条就能挡掉「恶意网页偷调本机 API」的 CSRF。
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_GUARDED_GET = {"/api/navigate"}


@app.middleware("http")
async def _csrf_guard(request, call_next):
    path = request.url.path
    if path.startswith("/api/"):
        needs = (request.method not in _SAFE_METHODS) or (path in _GUARDED_GET)
        if needs and not request.headers.get("x-requested-with"):
            return JSONResponse(
                {"detail": "缺少 X-Requested-With 请求头（本地 API 防 CSRF）"},
                status_code=403,
            )
    return await call_next(request)


# ==================== 请求模型 ====================

class CaptionGenReq(BaseModel):
    template_id: int | None = None
    template_content: str | None = None
    target: str = ""
    media_type: str = "图"
    mood: str = ""
    points: str = ""
    caption_type: str = "返图"
    temperature: float = 0.9
    max_tokens: int | None = None      # 文案长度（旧：token 数）
    max_chars: int | None = None       # 文案长度（新：大约多少个字，前端推子用它）
    ref_song: str = ""                 # 参考某首歌的文案（只作参考注入）
    image_description: str = ""
    image_exif: str = ""


class CaptionReq(BaseModel):
    content: str
    tags: str = ""
    caption_type: str = "返图"
    source: str = "manual"


class BulkCaptionReq(BaseModel):
    text: str
    caption_type: str = "返图"


class TemplateReq(BaseModel):
    name: str
    tpl_type: str = "返图"
    content: str


class TermReq(BaseModel):
    term: str
    meaning: str
    term_type: str = "黑话"
    event_id: int | None = None
    confidence: str = "manual"


class PromoteReq(BaseModel):
    cand_id: int
    term: str
    meaning: str
    term_type: str = "黑话"
    confidence: str = "manual"


class SuggestReq(BaseModel):
    phrase: str
    sample: str = ""


class EventReq(BaseModel):
    title: str
    event_date: str = ""
    description: str = ""
    related_terms: str = ""
    people: str = ""
    status: str = "confirmed"


class EventPatch(BaseModel):
    title: str | None = None
    event_date: str | None = None
    description: str | None = None
    related_terms: str | None = None
    people: str | None = None
    status: str | None = None


class IngestReq(BaseModel):
    text: str
    author: str = ""
    posted_at: str = ""


class VisionModelsReq(BaseModel):
    base_url: str | None = None
    api_key: str | None = None


class VisionDescribeReq(BaseModel):
    image_base64: str
    mime: str = "image/png"
    hint: str = ""


# ==================== 状态 ====================

@app.get("/api/health")
def health():
    return llm.health()


@app.get("/api/dashboard")
def dashboard():
    today = date.today().strftime("%Y-%m-%d")
    def count(sql, params=()):
        r = db.one(sql, params)
        return r["c"] if r else 0
    return {
        "model": llm.health(),
        "counts": {
            "captions": count("SELECT COUNT(*) c FROM captions"),
            "terms": count("SELECT COUNT(*) c FROM terms"),
            "events": count("SELECT COUNT(*) c FROM events"),
            "events_today": count("SELECT COUNT(*) c FROM events WHERE created_at LIKE ?", (today + "%",)),
            "pending_events": count("SELECT COUNT(*) c FROM events WHERE status='pending'"),
            "candidates": count("SELECT COUNT(*) c FROM term_candidates WHERE status='pending'"),
            "pending_posts": fetcher.count_pending(),
        },
        "next_runs": scheduler.next_runs(),
        "autostart": autostart.is_enabled(),
        "last_fetch": (db.one("SELECT created_at FROM runs WHERE job='fetch' AND status='ok' "
                              "ORDER BY id DESC LIMIT 1") or {}).get("created_at", ""),
        "settings": db.all_settings(),
    }


@app.get("/api/export")
def export_data():
    """导出可备份的**内容**数据。**不含 settings**（里面存着 cookie 与 API key）。"""
    return {
        "app": APP_NAME,
        "version": VERSION,
        "exported_at": db.now(),
        "captions": db.rows("SELECT content, tags, caption_type, source, created_at FROM captions"),
        "terms": db.rows("SELECT term, meaning, term_type, confidence, source, created_at FROM terms"),
        "events": db.rows("SELECT title, event_date, description, related_terms, people, "
                          "source, status, created_at FROM events"),
        "templates": db.rows("SELECT name, tpl_type, content FROM prompt_templates"),
        "term_candidates": db.rows("SELECT phrase, freq, sample, suggested_meaning, "
                                   "confidence, status FROM term_candidates"),
    }


@app.get("/api/runs")
def runs():
    return db.rows("SELECT * FROM runs ORDER BY id DESC LIMIT 50")


# ==================== 写文案 ====================

@app.post("/api/caption/generate")
def caption_generate(req: CaptionGenReq):
    content = req.template_content
    if req.template_id is not None:
        tpl = db.one("SELECT * FROM prompt_templates WHERE id=?", (req.template_id,))
        if tpl:
            content = tpl["content"]
    if not content:
        content = ("为这条微博返图写文案。\n对象：{target}\n图频类型：{media_type}\n"
                   "氛围：{mood}\n要点：{points}")
    fields = {
        "target": req.target, "media_type": req.media_type,
        "mood": req.mood, "points": req.points,
        "caption_type": req.caption_type,
        "max_chars": req.max_chars,
        "ref_song": req.ref_song,
        "image_description": req.image_description,
        "image_exif": req.image_exif,
    }
    winref.BUSY += 1                  # 长任务期间关窗要先问一声（别把等待白费）
    try:
        return captions.generate(content, fields, req.temperature, req.max_tokens)
    except Exception as e:
        raise HTTPException(500, f"生成失败：{e}")
    finally:
        winref.BUSY -= 1


@app.get("/api/captions")
def captions_list(status: str = "", scope: str = ""):
    return captions.list_captions(status, scope)


@app.get("/api/captions/songs")
def captions_songs():
    """已确认的歌曲文案里出现过的歌名（用于「已确认」页按歌分组）。"""
    return captions.list_songs()


class CaptionScopeReq(BaseModel):
    scope: str = "general"      # general / song
    song: str = ""


@app.patch("/api/captions/{cid}")
def captions_set_scope(cid: int, req: CaptionScopeReq):
    """把一条文案归到「普适」或某首歌（手动标）。"""
    captions.set_scope(cid, req.scope, req.song)
    return {"ok": True}


@app.get("/api/captions/counts")
def captions_counts():
    """文案库两个页签的数量。给切页用。"""
    return captions.count_captions()


@app.post("/api/captions/confirm_all")
def captions_confirm_all():
    """一键确认全部待确认文案。"""
    with db.tx() as conn:
        before = conn.total_changes
        conn.execute("UPDATE captions SET status='confirmed' WHERE status='pending'")
        n = conn.total_changes - before
    return {"ok": True, "n": n}


@app.post("/api/captions/{cid}/confirm")
def captions_confirm(cid: int):
    """单条确认。"""
    db.run("UPDATE captions SET status='confirmed' WHERE id=?", (cid,))
    return {"ok": True}


@app.post("/api/captions")
def captions_add(req: CaptionReq):
    return {"id": captions.add_caption(req.content, req.tags, req.caption_type, req.source)}


@app.post("/api/captions/bulk")
def captions_bulk(req: BulkCaptionReq):
    return {"added": captions.bulk_add_captions(req.text, req.caption_type)}


@app.delete("/api/captions/{cid}")
def captions_delete(cid: int):
    captions.delete_caption(cid)
    return {"ok": True}


# ==================== 风格档案 ====================

@app.get("/api/style")
def style_get():
    """当前风格说明书 + 文案库规模。"""
    return {"profile": style.get(), "captions": style.count_captions()}


@app.post("/api/style/generate")
def style_generate():
    """读全部文案 → 让模型写风格说明书并保存。**可能较慢**（要过一遍全部文案）。"""
    winref.BUSY += 1
    try:
        return style.generate()
    finally:
        winref.BUSY -= 1


class StyleSave(BaseModel):
    profile: str = ""


@app.post("/api/style")
def style_save(req: StyleSave):
    style.save(req.profile)
    return {"ok": True, "chars": len(style.get())}


@app.get("/api/style/captions_text")
def style_captions_text():
    """把全部文案拼成纯文本 —— 方便复制到云端强模型，再把结果粘回来。"""
    return {"text": style.all_captions_text(), "count": style.count_captions()}


# ==================== 提示词模板 ====================

@app.get("/api/templates")
def templates_list():
    return captions.list_templates()


@app.post("/api/templates")
def templates_add(req: TemplateReq):
    return {"id": captions.add_template(req.name, req.tpl_type, req.content)}


@app.put("/api/templates/{tid}")
def templates_update(tid: int, req: TemplateReq):
    captions.update_template(tid, req.name, req.tpl_type, req.content)
    return {"ok": True}


@app.delete("/api/templates/{tid}")
def templates_delete(tid: int):
    captions.delete_template(tid)
    return {"ok": True}


# ==================== 术语词典 ====================

@app.get("/api/terms")
def terms_list():
    return terms.list_terms()


@app.post("/api/terms")
def terms_add(req: TermReq):
    terms.upsert_term(req.term, req.meaning, req.term_type, req.event_id, req.confidence)
    return {"ok": True}


@app.delete("/api/terms/{tid}")
def terms_delete(tid: int):
    terms.delete_term(tid)
    return {"ok": True}


class TermPatch(BaseModel):
    meaning: str | None = None
    term_type: str | None = None
    confidence: str | None = None


@app.patch("/api/terms/{tid}")
def terms_update(tid: int, req: TermPatch):
    """就地改词条（词典页）。"""
    terms.update_term(tid, **{k: v for k, v in req.model_dump().items() if v is not None})
    return {"ok": True}


@app.post("/api/terms/delete_all")
def terms_delete_all():
    """一键清空**全部词条**（危险操作，前端有确认）。"""
    with db.tx() as conn:
        before = conn.total_changes
        conn.execute("DELETE FROM terms")
        n = conn.total_changes - before
    return {"ok": True, "n": n}


@app.post("/api/candidates/delete_all")
def candidates_delete_all(status: str = "pending"):
    """一键删除候选。status=pending 只删未确认；status=all 全删。"""
    with db.tx() as conn:
        before = conn.total_changes
        if status == "all":
            conn.execute("DELETE FROM term_candidates")
        else:
            conn.execute("DELETE FROM term_candidates WHERE status='pending'")
        n = conn.total_changes - before
    return {"ok": True, "n": n}


@app.post("/api/captions/delete_all")
def captions_delete_all(status: str = "pending"):
    """一键删除文案。
    status=pending 只删待确认（默认，安全）；confirmed 只删已确认；all 全删。"""
    with db.tx() as conn:
        before = conn.total_changes
        if status == "all":
            conn.execute("DELETE FROM captions")
        elif status == "confirmed":
            conn.execute("DELETE FROM captions WHERE status='confirmed'")
        else:
            conn.execute("DELETE FROM captions WHERE status='pending'")
        n = conn.total_changes - before
    return {"ok": True, "n": n}


@app.post("/api/terms/extract_from_posts")
def terms_extract_from_posts():
    """手动触发：从最近的超话帖子抽可能的术语。"""
    posts = db.rows("SELECT * FROM posts ORDER BY id DESC LIMIT 60")
    try:
        n = terms.extract_terms_from_posts(posts)
    except Exception as e:
        raise HTTPException(500, f"抽取失败：{e}")
    return {"ok": True, "added": n}


# ==================== 校对台 ====================

@app.get("/api/candidates")
def candidates_list(status: str = "pending"):
    return terms.list_candidates(status)


@app.post("/api/candidates/fetch")
def candidates_fetch():
    try:
        return terms.fetch_candidates()
    except Exception as e:
        raise HTTPException(500, f"抽取失败：{e}")


@app.post("/api/candidates/suggest")
def candidates_suggest(req: SuggestReq):
    try:
        return terms.suggest_meaning(req.phrase, req.sample)
    except Exception as e:
        raise HTTPException(500, f"释义失败：{e}")


@app.post("/api/candidates/promote")
def candidates_promote(req: PromoteReq):
    terms.promote_candidate(req.cand_id, req.term, req.meaning, req.term_type, req.confidence)
    return {"ok": True}


@app.post("/api/candidates/{cid}/ignore")
def candidates_ignore(cid: int):
    terms.ignore_candidate(cid)
    return {"ok": True}


# ==================== 事件库 ====================

@app.get("/api/events")
def events_list(status: str | None = None, source: str | None = None, q: str = "",
                limit: int = 100, offset: int = 0):
    return events.list_events(status, source, q, limit, offset)


@app.post("/api/events")
def events_add(req: EventReq):
    return {"id": events.add_event(req.title, req.event_date, req.description,
                                   req.related_terms, req.people, "manual", req.status)}


@app.patch("/api/events/{eid}")
def events_patch(eid: int, req: EventPatch):
    events.update_event(eid, **{k: v for k, v in req.model_dump().items() if v is not None})
    return {"ok": True}


@app.delete("/api/events/{eid}")
def events_delete(eid: int):
    events.delete_event(eid)
    return {"ok": True}


@app.post("/api/events/confirm_all")
def events_confirm_all():
    """一键确认全部待确认事件。"""
    with db.tx() as conn:
        before = conn.total_changes
        conn.execute("UPDATE events SET status='confirmed' WHERE status='pending'")
        n = conn.total_changes - before
    return {"ok": True, "n": n}


@app.post("/api/events/delete_pending")
def events_delete_pending():
    """一键删除全部待确认事件（已确认与手动录入的不动）。"""
    with db.tx() as conn:
        before = conn.total_changes
        conn.execute("DELETE FROM events WHERE status='pending'")
        n = conn.total_changes - before
    return {"ok": True, "n": n}


@app.post("/api/events/delete_all")
def events_delete_all(status: str = ""):
    """一键删除事件。status=pending/confirmed 只删该状态；留空 = 全删（危险）。"""
    with db.tx() as conn:
        before = conn.total_changes
        if status in ("pending", "confirmed"):
            conn.execute("DELETE FROM events WHERE status=?", (status,))
        else:
            conn.execute("DELETE FROM events")
        n = conn.total_changes - before
    return {"ok": True, "n": n}


# ==================== 帖子 & 总结 ====================

@app.get("/api/posts")
def posts_list():
    return db.rows("SELECT * FROM posts ORDER BY id DESC LIMIT 200")


@app.post("/api/posts/ingest")
def posts_ingest(req: IngestReq):
    return {"added": fetcher.ingest_manual(req.text, req.author, req.posted_at)}


@app.post("/api/summarize")
def do_summarize():
    try:
        return summarize.summarize_pending()
    except Exception as e:
        raise HTTPException(500, f"总结失败：{e}")


@app.post("/api/fetch/run")
def fetch_run():
    """手动抓一次超话（含链式自动总结）。总是 200，真实结果在 ok 字段里。"""
    return scheduler.run_fetch()


# ==================== 扫码登录（自动获取 cookie） ====================

@app.post("/api/weibo/qr/start")
def weibo_qr_start():
    """生成扫码登录二维码。总是 200。"""
    return weibo_login.start()


@app.get("/api/weibo/qr/poll")
def weibo_qr_poll():
    """轮询扫码状态；成功后自动把 cookie 写进 settings。总是 200。"""
    return weibo_login.poll()


@app.get("/api/weibo/login_status")
def weibo_login_status():
    """当前保存的 cookie 是否仍有效（登录态 + 昵称）。总是 200。"""
    return weibo_login.login_status()


class UserQueryReq(BaseModel):
    query: str = ""


@app.post("/api/weibo/resolve_user")
def weibo_resolve_user(req: UserQueryReq):
    """把「昵称 / uid / 主页链接」解析成候选用户。总是 200。"""
    return weibo_user.resolve_user(req.query)


class ScanTopicsReq(BaseModel):
    user: str = ""
    days: int = 180
    max_pages: int = 10


@app.post("/api/weibo/scan_user_topics")
def weibo_scan_user_topics(req: ScanTopicsReq):
    """扫该用户发过哪些超话 → 供前端下拉挑选（省得手动抄 containerid）。总是 200。"""
    return weibo_user.scan_user_topics(req.user, req.days, req.max_pages)


class ImportCaptionsReq(BaseModel):
    user: str = ""
    containerid: str = ""      # 留空 = 不限超话（抓该用户全部原创）
    date_from: str = ""        # 起始日期 YYYY-MM-DD（含）；留空 = 不限
    date_to: str = ""          # 截止日期 YYYY-MM-DD（含）；留空 = 今天
    cooldown: int = 10            # 每批之间的休息秒数（0 = 不额外休息）
    caption_type: str = "返图"


@app.post("/api/weibo/import_captions")
def weibo_import_captions(req: ImportCaptionsReq):
    """启动**后台**导入：自动翻页、每 20 页休息一会儿再继续，
    直到扫完「天数」范围内的所有帖。立刻返回，前端轮询下面那个 status。总是 200。"""
    return weibo_user.start_import(req.user, req.containerid,
                                   req.date_from, req.date_to,
                                   req.caption_type, cooldown=req.cooldown)


@app.get("/api/weibo/import_status")
def weibo_import_status():
    """后台导入的进度（含 progress / 已翻到的日期 / 目标日期）。总是 200。"""
    return weibo_user.import_status()


@app.post("/api/weibo/import_stop")
def weibo_import_stop():
    """手动停止后台导入（已入库的保留）。总是 200。"""
    return weibo_user.stop_import()


class ResolveChaoReq(BaseModel):
    containerid: str = ""


@app.post("/api/weibo/resolve_chaohua")
def weibo_resolve_chaohua(req: ResolveChaoReq):
    """用 containerid 反查超话名（并缓存）。总是 200。"""
    return weibo_login.resolve_chaohua(req.containerid)


class FindCidReq(BaseModel):
    keyword: str = ""


@app.post("/api/weibo/find_containerid")
def weibo_find_containerid(req: FindCidReq):
    """按关键词搜超话，返回 containerid 候选。总是 200。"""
    return weibo_login.find_containerid(req.keyword)


# ==================== 推送 ====================

@app.post("/api/push/test")
def push_test():
    ok = notify("超话助手 · 测试", "这是一条测试推送，看到就说明弹窗正常。")
    return {"ok": ok, "error": "" if ok else last_error()}


@app.get("/api/navigate")
def navigate(page: str = "dashboard", event: str = ""):
    """把运行中的 app 窗口唤到前台并跳页（桌面弹窗点击走这里）。
    GUI 模式才有窗口；--server-only 时 has_window=False，不开网页。"""
    return {"ok": winref.focus(page, event), "has_window": winref.WINDOW is not None}


@app.post("/api/maintenance/cleanup")
def maintenance_cleanup():
    """清理无限增长的日志/旧帖（不动事件、术语、文案）。"""
    return {"ok": True, "deleted": housekeeping.cleanup()}


@app.post("/api/quit")
def quit_app():
    """直接退出整个程序。"""
    return {"ok": winref.quit_app()}


class CloseChoice(BaseModel):
    action: str = "minimize"        # minimize | quit
    remember: bool = False          # 记住 → 写进设置，以后 × 不再问


@app.post("/api/window/close")
def window_close(req: CloseChoice):
    """× 弹框里选完后的落地：可选记住偏好，然后执行。"""
    act = "quit" if req.action == "quit" else "minimize"
    if req.remember:
        db.set_setting("close_action", act)
    if act == "quit":
        winref.quit_app()
    else:
        winref.minimize()
    return {"ok": True, "action": act, "remembered": req.remember}


@app.get("/api/push/log")
def push_log():
    return db.rows("SELECT * FROM push_log ORDER BY id DESC LIMIT 50")


@app.post("/api/jobs/{job}/run")
def job_run(job: str):
    return scheduler.trigger(job)


# ==================== 识图（云端 VLM） ====================

@app.post("/api/vision/models")
def vision_models(req: VisionModelsReq):
    """拉取中转站模型列表供用户选择。POST 以便直接测试刚输入的地址/密钥。"""
    if req.base_url:
        db.set_setting("vision_base_url", req.base_url.strip())
    if req.api_key:
        db.set_setting("vision_api_key", req.api_key.strip())
    models = vision.list_models()
    return {
        "ok": bool(models),
        "models": models,
        "error": "" if models else "连不上中转站或未返回模型列表（检查地址是否含 /v1、密钥是否正确）",
    }


@app.post("/api/vision/describe")
def vision_describe(req: VisionDescribeReq):
    if len(req.image_base64) > 20_000_000:
        raise HTTPException(413, "图片过大")
    try:
        raw = base64.b64decode(req.image_base64, validate=False)
    except Exception as e:
        raise HTTPException(400, f"图片解码失败：{e}")
    winref.BUSY += 1
    try:
        exif = vision.exif_summary(raw)          # 从原图读 EXIF（describe 会重编码剥离）
        desc = vision.describe(raw, req.mime, req.hint)
        return {"description": desc, "exif": exif,
                "model": db.get_setting("vision_model", "")}
    except Exception as e:
        raise HTTPException(500, f"识图失败：{e}")
    finally:
        winref.BUSY -= 1


# ==================== 首启环境向导（Ollama / 模型 / WebView2） ====================

@app.get("/api/setup/check")
def setup_check():
    """检测本机环境缺什么（Ollama 是否装/在跑、模型是否就绪、WebView2 是否存在）。"""
    return setup.check()


@app.get("/api/setup/status")
def setup_status():
    """当前安装/下载任务的进度（前端每秒轮询）。"""
    return setup.status()


@app.post("/api/setup/install_ollama")
def setup_install_ollama(payload: dict = Body(default={})):
    """一键下载并静默安装 Ollama（后台线程；进度看 /api/setup/status）。"""
    return setup.install_ollama((payload or {}).get("mirror", ""))


@app.post("/api/setup/pull_model")
def setup_pull_model(payload: dict = Body(default={})):
    """一键拉取模型权重（后台线程；进度看 /api/setup/status）。"""
    return setup.pull_model((payload or {}).get("model", ""))


@app.post("/api/setup/cancel")
def setup_cancel():
    return setup.cancel()


@app.post("/api/setup/done")
def setup_done(payload: dict = Body(default={})):
    """记下向导已完成/已跳过，之后不再自动弹。"""
    db.set_setting("setup_wizard_done", "1" if (payload or {}).get("done", True) else "0")
    return {"ok": True}


# ==================== 设置 ====================

@app.get("/api/settings")
def settings_get():
    return db.all_settings()


@app.post("/api/settings")
def settings_set(payload: dict = Body(...)):
    for k, v in payload.items():
        db.set_setting(k, v)
    if "autostart" in payload:
        autostart.set_enabled(str(payload["autostart"]) == "1")
    if ("push_interval_min" in payload or "summarize_interval_min" in payload
            or "weibo_fetch_interval_min" in payload):
        scheduler.reload_jobs()
    return {"ok": True, "settings": db.all_settings()}


@app.post("/api/autostart")
def autostart_toggle(payload: dict = Body(...)):
    on = bool(payload.get("enabled"))
    ok = autostart.set_enabled(on)
    db.set_setting("autostart", "1" if on else "0")
    return {"ok": ok, "enabled": autostart.is_enabled()}


# ==================== 静态资源（放最后，避免遮蔽 API） ====================

@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
