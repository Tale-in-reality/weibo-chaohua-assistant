"""写文案 + 文案库 + 提示词模板。

核心：风格样本只教"怎么写"，梗义来自术语库，事件来自事件库——
所有检索到的知识都注入 prompt（没微调，模型不会"记住"）。
"""
import re

from .. import db, llm
from ..util import bm25_rank
from . import style

# 装饰性内容：`#话题#`、`@某人`、日期（10.05 / 25.12.23 / 2026-10-05）
# 用户明确要求：生成结果里**不要**这些，只出具体文案；喂给模型学风格的样本也要先洗掉，
# 否则模型会把「每条都挂个话题」「开头写日期」也当成风格学过去。
_DEC_TOPIC = re.compile(r"#[^#\n]{1,40}#")
_DEC_AT = re.compile(r"@[^\s@#]{1,30}")
_DEC_DATE = re.compile(r"(?<!\d)(?:\d{1,4}[./-]){1,2}\d{1,4}(?!\d)")


def strip_decor(s: str) -> str:
    """洗掉话题 / @提及 / 日期，只留文案本身。"""
    t = _DEC_TOPIC.sub("", s or "")
    t = _DEC_AT.sub("", t)
    t = _DEC_DATE.sub("", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


class _Safe(dict):
    def __missing__(self, key):
        return ""


SYSTEM = (
    "你是帮粉丝写微博文案的助手，熟悉粉圈语境，能自然使用圈内梗和绰号。\n"
    "铁律：\n"
    "0. 严格遵守「我的风格」块里总结的语气规律（句式 / 标点 / 高频词 / 长度 / 禁忌）。\n"
    "0b. 只输出**具体文案本身**。不要写 #话题#（#…#）、不要 @某人、不要写日期"
    "（如 10.05 / 25.12.23 / 2026-10-05）、不要写「xx演唱会」这类时间地点标记"
    "—— 这些用户会自己加。\n"
    "1. 只用下方「术语释义」里明确给出的梗，绝不自行发挥或编造梗的含义。\n"
    "2. 标注为「可能编造」的术语一律不要使用。\n"
    "3. 模仿「风格样本」的语气，但不要照抄句子。\n"
    "4. 只输出文案本身，不要解释、不要加引号。\n"
    "5. 「照片信息」只用来补充画面细节（姿态/光线/服装/构图等），不得编造画面里没有的内容，"
    "也不要猜测人物真实身份；识图可能有误，明显不合理时以常识为准。"
)


# ---------- 检索（BM25，见 util.bm25_rank） ----------

def _sample_limit() -> int:
    try:
        return max(1, min(int(db.get_setting("style_samples", "8") or 8), 40))
    except (TypeError, ValueError):
        return 8


def _relevant_terms(query: str, limit: int = 8) -> list:
    items = db.rows("SELECT * FROM terms WHERE meaning != ''")
    if not items:
        return []
    docs = [(i, f"{t['term']} {t['meaning']}") for i, t in enumerate(items)]
    scored = []
    for i, s in bm25_rank(query, docs):
        t = items[i]
        if t["term"] and t["term"] in (query or ""):
            s += 50                      # 词本身出现在 query 里 → 直接拉满
        scored.append((s, t))
    scored.sort(key=lambda x: -x[0])
    return [t for _, t in scored[:limit]]


def _relevant_events(query: str, limit: int = 4) -> list:
    # 只喂「已确认」的事件给模型：待确认的多是机器猜的，别让它污染文案。
    # 加 LIMIT 防止事件表涨到上千条后每次生成都全表扫。
    items = db.rows("SELECT * FROM events WHERE status='confirmed' ORDER BY id DESC LIMIT 500")
    if not items:
        return []
    docs = [(i, f"{e['title']} {e['description']} {e['people']} {e['related_terms']}")
            for i, e in enumerate(items)]
    scored = []
    for i, s in bm25_rank(query, docs):
        e = items[i]
        if e["title"] and e["title"] in (query or ""):
            s += 50
        scored.append((s, e))
    scored.sort(key=lambda x: -x[0])
    return [e for _, e in scored[:limit]]


def _style_samples(query: str, caption_type: str, limit: int | None = None) -> list:
    """挑风格样本。同类型的加权；不足时用同类型的补齐。"""
    limit = limit or _sample_limit()
    # 只取「已确认 + 普适」：绑定某首歌的文案不该当通用风格学
    items = db.rows("SELECT * FROM captions WHERE status='confirmed' AND scope='general'")
    if not items:
        return []
    docs = [(i, c["content"]) for i, c in enumerate(items)]
    scored = []
    for i, s in bm25_rank(query, docs):
        c = items[i]
        if caption_type and c["caption_type"] == caption_type:
            s *= 1.6
        scored.append((s, c))
    scored.sort(key=lambda x: -x[0])
    picks = [c for _, c in scored[:limit]]

    # 不足就补齐 —— **必须有这个兜底**：查询词太短时 bm25 可能一条都不命中，
    # 那样模型会一条风格样本都拿不到、直接丢掉语气。
    # 补齐顺序：同类型的优先，再按新旧。
    if len(picks) < limit:
        seen = {c["id"] for c in picks}
        rest = [c for c in items if c["id"] not in seen]
        rest.sort(key=lambda c: (c["caption_type"] != caption_type, -c["id"]))
        picks.extend(rest[:limit - len(picks)])
    return picks


def build_prompt(template_content: str, fields: dict):
    prof = style.get()

    # 模板可以显式写 `{style}` 来引用风格档案（在「写文案」页有按钮插入）。
    # 写了就按它放的位置展开、不再自动附一份（免得重复）。
    fmt = dict(fields)
    fmt["style"] = prof
    parts = [template_content.format_map(_Safe(fmt))]

    # 长度：按「大约多少字」来要求，比单纯卡 max_tokens 靠谱
    max_chars = fields.get("max_chars")
    if max_chars:
        parts.append(f"【长度要求】正文控制在 {int(max_chars)} 字左右（不含话题标签）。")

    # 照片信息（识图结果 + EXIF）：插在模板之后、知识块之前，读起来是"拍摄对象"的一部分
    desc = str(fields.get("image_description") or "").strip()
    exif = str(fields.get("image_exif") or "").strip()
    if desc or exif:
        body = (f"拍摄参数：{exif}\n" if exif else "") + desc
        parts.append("【照片信息（识图结果，供参考）】\n" + body)

    # 风格档案（读完全部文案蒸馏出的「规律」）—— 权重冻结下最接近「学进模型」的东西。
    # 模板里已经用 `{style}` 显式引用了就不再自动附一份。
    if prof and "{style}" not in (template_content or ""):
        parts.append("【我的风格（务必遵守，这是本人文案的规律）】\n" + prof)

    # 检索 query：显式的字段 + 画面描述（EXIF 是数字噪声，不参与）
    query = " ".join(str(fields.get(k, "")) for k in
                     ("target", "media_type", "mood", "points", "caption_type"))
    if desc:
        query += " " + desc

    terms = _relevant_terms(query)
    if terms:
        lines = []
        for t in terms:
            tag = ""
            if t["confidence"] == "maybe_fabricated":
                tag = "（可能编造，勿使用）"
            elif t["confidence"] == "likely":
                tag = "（较可信）"
            lines.append(f"- {t['term']}：{t['meaning']}{tag}")
        parts.append("【可联想的梗/术语】\n" + "\n".join(lines))

    events = _relevant_events(query)
    if events:
        lines = []
        for e in events:
            when = f"（{e['event_date']}）" if e["event_date"] else ""
            lines.append(f"- {e['title']}{when}：{e['description']}")
        parts.append("【可联想的事件】\n" + "\n".join(lines))

    # 「参考某首歌的文案」：**只作参考注入**，不进风格样本池、也不要求模型产出一条新的
    ref_song = str(fields.get("ref_song") or "").strip()
    ref_count = 0
    if ref_song:
        refs = db.rows(
            "SELECT content FROM captions WHERE status='confirmed' AND scope='song' AND song=? "
            "ORDER BY COALESCE(NULLIF(posted_at, ''), created_at) DESC LIMIT 6", (ref_song,))
        if refs:
            ref_count = len(refs)
            lines = [f"- {r['content']}" for r in refs]
            parts.append(
                f"【参考：与《{ref_song}》相关的文案（**只作参考** —— 帮你理解这首歌的语境与"
                f"粉丝怎么写它；不要照抄、也不要把它当成通用语气）】\n" + "\n".join(lines))

    samples = _style_samples(query, fields.get("caption_type", ""))
    if samples:
        # 样本先洗掉话题/@/日期 —— 只让它学语气，别把装饰也学过去
        lines = [f"{i + 1}. {strip_decor(c['content'])}" for i, c in enumerate(samples)]
        parts.append("【风格样本（我以前的文案，模仿语气，勿照抄）】\n" + "\n".join(lines))

    used = {
        "terms": [t["term"] for t in terms],
        "events": [e["title"] for e in events],
        "samples": len(samples),
        "image": bool(desc),
        "exif": bool(exif),
        "ref_song": ref_song if ref_count else "",
        "ref_count": ref_count,
    }
    return "\n\n".join(parts), used


def generate(template_content: str, fields: dict, temperature: float = 0.9,
             max_tokens: int | None = None) -> dict:
    # 长度：优先按「字数」算 token（中文约 1 字 ≈ 1 token，给 1.8 倍余量 + 30 兜底），
    # 并把这个字数写进 prompt 让模型自己控制（比单纯卡 token 上限靠谱）。
    max_chars = fields.get("max_chars")
    if max_chars:
        try:
            n = max(10, min(int(max_chars), 500))
            fields = dict(fields, max_chars=n)
            max_tokens = int(n * 1.8) + 30
        except (TypeError, ValueError):
            pass
    prompt, used = build_prompt(template_content, fields)
    mt = 400 if not max_tokens else max(60, min(int(max_tokens), 2000))
    text = llm.generate(prompt, system=SYSTEM, temperature=temperature, max_tokens=mt)
    return {"text": text.strip(), "used": used, "prompt": prompt}


# ---------- 文案库 ----------

def list_captions(status: str = "", scope: str = "") -> list:
    """**最新的在最上面**。status / scope 为空则不过滤。

    不能按 id 排：导入是按时间线「新→旧」逐页插的，最后插入的反而最旧。
    所以按帖子本身的时间排（导入的用原帖时间，手动录入的用录入时间）。
    """
    where, params = [], []
    if status in ("pending", "confirmed"):
        where.append("status=?")
        params.append(status)
    if scope in ("general", "song"):
        where.append("scope=?")
        params.append(scope)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    return db.rows(
        f"SELECT * FROM captions {w} "
        "ORDER BY COALESCE(NULLIF(posted_at, ''), created_at) DESC, id DESC", params)


def list_songs() -> list:
    """已确认的「歌曲文案」里出现过的歌名 + 各自条数（按条数降序）。

    用于「已确认」页把歌曲文案按歌分组。
    """
    return db.rows(
        "SELECT song, COUNT(*) c FROM captions "
        "WHERE status='confirmed' AND scope='song' AND song != '' "
        "GROUP BY song ORDER BY c DESC, song")


def set_scope(cid: int, scope: str, song: str = ""):
    """把一条文案归到「普适」或某首歌。"""
    scope = "song" if scope == "song" else "general"
    db.run("UPDATE captions SET scope=?, song=? WHERE id=?",
           (scope, (song or "").strip() if scope == "song" else "", cid))


def count_captions(status: str = "") -> dict:
    rows = db.rows("SELECT status, scope, COUNT(*) c FROM captions GROUP BY status, scope")
    out = {"pending": 0, "confirmed": 0, "general": 0, "song": 0}
    for r in rows:
        if r["status"] in out:
            out[r["status"]] += r["c"]
        if r["status"] == "confirmed" and r["scope"] in ("general", "song"):
            out[r["scope"]] += r["c"]
    out["total"] = out["pending"] + out["confirmed"]
    return out


def add_caption(content: str, tags: str = "", caption_type: str = "返图",
                source: str = "manual") -> int:
    return db.run(
        "INSERT INTO captions(content, tags, caption_type, source, created_at) VALUES(?,?,?,?,?)",
        (content.strip(), tags, caption_type, source, db.now()),
    )


def bulk_add_captions(text: str, caption_type: str = "返图") -> int:
    n = 0
    for line in text.splitlines():
        line = line.strip()
        if line:
            add_caption(line, "", caption_type)
            n += 1
    return n


def delete_caption(cid: int):
    db.run("DELETE FROM captions WHERE id=?", (cid,))


# ---------- 提示词模板 ----------

def list_templates() -> list:
    return db.rows("SELECT * FROM prompt_templates ORDER BY id")


def add_template(name: str, tpl_type: str, content: str) -> int:
    return db.run(
        "INSERT INTO prompt_templates(name, tpl_type, content, created_at) VALUES(?,?,?,?)",
        (name, tpl_type, content, db.now()),
    )


def update_template(tid: int, name: str, tpl_type: str, content: str):
    db.run("UPDATE prompt_templates SET name=?, tpl_type=?, content=? WHERE id=?",
           (name, tpl_type, content, tid))


def delete_template(tid: int):
    db.run("DELETE FROM prompt_templates WHERE id=?", (tid,))
