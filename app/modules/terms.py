"""术语/梗词典 + 候选抽取（自动识别）+ 校准。

原则：机器只能"提候选"，含义由人校准。自动填释义必须标注可信度，
防止模型用确信语气掩盖不确定。
"""
import re

from .. import db, llm
from ..util import extract_json_array, extract_json_object

STOPWORDS = set(
    "的 了 是 在 我 你 他 她 它 们 和 与 就 都 也 还 很 太 这 那 有 没 不 要 会 能 把 被 给 让 "
    "从 到 对 为 以 之 而 及 或 一个 我们 你们 他们 这个 那个 什么 怎么 这样 那样 因为 所以 "
    "但是 如果 就是 一起 现在 今天 明天 昨天 已经 还是 真的 好像 感觉 喜欢 爱 好看 好好 "
    "希望 大家 谢谢 加油 时候 自己 可以 没有 知道 觉得 有点 一点 一直 终于 然后".split()
)

_jieba = None


def _get_jieba():
    global _jieba
    if _jieba is None:
        import jieba
        jieba.setLogLevel(60)
        _jieba = jieba
    return _jieba


# ---------- 词典 CRUD ----------

def list_terms() -> list:
    return db.rows("SELECT * FROM terms ORDER BY id DESC")


def upsert_term(term: str, meaning: str, term_type: str = "黑话", event_id=None,
                confidence: str = "manual", source: str = "manual"):
    db.run(
        "INSERT INTO terms(term, meaning, term_type, event_id, confidence, source, created_at) "
        "VALUES(?,?,?,?,?,?,?) "
        "ON CONFLICT(term) DO UPDATE SET meaning=excluded.meaning, term_type=excluded.term_type, "
        "event_id=excluded.event_id, confidence=excluded.confidence, source=excluded.source",
        (term.strip(), meaning.strip(), term_type, event_id, confidence, source, db.now()),
    )


def delete_term(term_id: int):
    db.run("DELETE FROM terms WHERE id=?", (term_id,))


def update_term(term_id: int, **fields):
    """就地修改词条（词典页用）。白名单：meaning / term_type / confidence / event_id。"""
    allowed = ["meaning", "term_type", "confidence", "event_id"]
    sets, params = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            params.append(v)
    if not sets:
        return
    params.append(term_id)
    db.run(f"UPDATE terms SET {', '.join(sets)} WHERE id=?", params)


# ---------- 候选 ----------

def list_candidates(status: str = "pending") -> list:
    if status == "all":
        return db.rows("SELECT * FROM term_candidates ORDER BY freq DESC")
    return db.rows("SELECT * FROM term_candidates WHERE status=? ORDER BY freq DESC", (status,))


def _llm_filter(words: list):
    """让模型挑出像圈内黑话的词。失败返回 None（调用方降级）。"""
    prompt = (
        "以下是从一位粉丝的文案里抽出的高频词。请挑出其中像"
        "【粉圈内部黑话 / 艺人绰号 / 特定梗或事件指代】的词"
        "（即普通读者看不懂、需要圈内知识才能理解的词），普通词汇不要。\n"
        '只返回 JSON 字符串数组，例如 ["昵称A","梗B"]。不要解释。\n\n'
        "词语：" + "、".join(words)
    )
    try:
        text = llm.generate(prompt, temperature=0.2, max_tokens=500)
        arr = extract_json_array(text)
        return set(arr) if arr else None
    except Exception:
        return None


def fetch_candidates() -> dict:
    """扫文案库 → 抽高频词 → 模型过滤 → 写入待校准清单。"""
    captions = db.rows("SELECT content FROM captions")
    if not captions:
        return {"added": 0, "message": "文案库是空的，先录入一些历史文案"}

    jieba = _get_jieba()
    freq, ctx = {}, {}
    for c in captions:
        for w in jieba.lcut(c["content"]):
            w = w.strip()
            if len(w) < 2 or w in STOPWORDS or re.fullmatch(r"[\W_]+", w):
                continue
            freq[w] = freq.get(w, 0) + 1
            ctx.setdefault(w, c["content"][:60])

    known = {t["term"] for t in db.rows("SELECT term FROM terms")}
    ranked = [(w, n) for w, n in sorted(freq.items(), key=lambda x: -x[1]) if w not in known][:40]
    if not ranked:
        return {"added": 0, "message": "没有发现新候选词"}

    words = [w for w, _ in ranked]
    suspicious = _llm_filter(words)
    degraded = suspicious is None
    if degraded:
        suspicious = set(words[:15])  # 模型不可用时降级：取高频前 15

    added = 0
    for w, n in ranked:
        if w in suspicious:
            db.run(
                "INSERT INTO term_candidates(phrase, freq, sample, status, created_at) "
                "VALUES(?,?,?,'pending',?) "
                "ON CONFLICT(phrase) DO UPDATE SET freq=excluded.freq, sample=excluded.sample",
                (w, n, ctx.get(w, ""), db.now()),
            )
            added += 1
    msg = f"新增 {added} 个候选词" + ("（模型不可用，已降级为高频词）" if degraded else "")
    return {"added": added, "message": msg, "degraded": degraded}


def suggest_meaning(phrase: str, sample: str = "") -> dict:
    """让模型给释义草稿并自评是否认识。返回 {meaning, confidence}。"""
    prompt = (
        f"词语：「{phrase}」\n"
        f"出现语境：{sample}\n\n"
        "请判断这个词语的含义。规则：\n"
        '- 若是全网流行的大众梗/常见词，你有把握，返回 {"known": true, "meaning": "简要释义"}\n'
        '- 若你不确定，或它像是某个圈子的内部用语而你不知道，返回 {"known": false, "meaning": ""}\n'
        "只返回 JSON，不要解释。"
    )
    try:
        text = llm.generate(prompt, temperature=0.2, max_tokens=200)
        data = extract_json_object(text) or {}
    except Exception:
        data = {}
    if data.get("known") and data.get("meaning"):
        return {"meaning": data["meaning"].strip(), "confidence": "likely"}
    return {"meaning": "", "confidence": "maybe_fabricated"}


def extract_terms_from_posts(posts: list) -> int:
    """从**帖子原文**里让模型抽出可能的圈内术语，写进待确认清单。返回写入条数。

    与 fetch_candidates 的区别：那个的数据源是「文案库」，这个的数据源是「超话帖子」。
    会写 suggested_meaning（模型推测的释义），供用户在术语词典页确认时直接采用/修改。
    """
    text = "\n".join("- " + (p["content"] or "") for p in posts)[:6000]
    if not text.strip():
        return 0
    prompt = (
        "以下是微博超话里的一批帖子原文。请找出其中**可能属于粉圈内部黑话 / 艺人绰号 / "
        "特定梗或事件指代**的词（普通读者看不懂、需要圈内知识才能理解的）。\n"
        '只返回 JSON 数组，每个元素形如 {"term":"词","meaning":"你推测的含义"}；'
        "含义没把握就用空字符串。没有则返回 []。不要解释。\n\n"
        "帖子：\n" + text
    )
    try:
        arr = extract_json_array(llm.generate(prompt, temperature=0.2, max_tokens=800))
    except Exception:
        return 0
    if not isinstance(arr, list):
        return 0

    known = {t["term"] for t in db.rows("SELECT term FROM terms")}
    added = 0
    for item in arr[:60]:
        if isinstance(item, dict):
            term = str(item.get("term") or "").strip()
            meaning = str(item.get("meaning") or "").strip()
        elif isinstance(item, str):
            term, meaning = item.strip(), ""
        else:
            continue
        if len(term) < 2 or term in known or re.fullmatch(r"[\W_]+", term):
            continue
        sample = ""
        for p in posts:
            if term in (p["content"] or ""):
                sample = (p["content"] or "")[:60]
                break
        db.run(
            "INSERT INTO term_candidates(phrase, freq, sample, suggested_meaning, status, created_at) "
            "VALUES(?,?,?,?,'pending',?) "
            "ON CONFLICT(phrase) DO UPDATE SET freq=freq+1, sample=excluded.sample, "
            "suggested_meaning=CASE WHEN excluded.suggested_meaning!='' "
            "THEN excluded.suggested_meaning ELSE suggested_meaning END",
            (term, 1, sample, meaning, db.now()),
        )
        added += 1
    return added


def ignore_candidate(cid: int):
    db.run("UPDATE term_candidates SET status='ignored' WHERE id=?", (cid,))


def promote_candidate(cid: int, term: str, meaning: str,
                      term_type: str = "黑话", confidence: str = "manual"):
    upsert_term(term, meaning, term_type, None, confidence, source="candidate")
    db.run("UPDATE term_candidates SET status='done' WHERE id=?", (cid,))
