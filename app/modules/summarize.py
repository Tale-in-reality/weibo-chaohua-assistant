"""总结：每条帖子存成一条事件（完整原文）+ 生成一条「速览」事件（推送用）。

设计（2026-10-13 改）：
  - **每条帖子 = 一条事件**（source='post'，status='pending'），description 放完整原文，
    点进去能看到全部内容。这一步**不依赖模型**，所以即使速览生成失败帖子也不丢。
  - **另生成一条速览事件**（source='digest'）：把全部内容压成要点，让用户最短时间了解要事。
    推送的就是这条（见 scheduler._push_tick）。
  - 可选：`ai_terms_enabled=1` 时顺带让模型抽可能的术语，进术语词典待确认。
"""
import re
from datetime import datetime

from .. import db, llm
from ..util import extract_json_array       # noqa: F401  （保留给后续解析用）
from . import terms

DIGEST_SYSTEM = (
    "你是粉丝社群的观察者。用户会给你一批超话帖子原文。\n"
    "请写一段【速览】：用最短的篇幅让读者知道这批帖子里发生了什么、有哪些要点和重要的事。\n"
    "要求：中文；分 3~6 条，每条一行、以「· 」开头；只依据原文，不编造、不评论、不客套。"
)


def _short_title(content: str) -> str:
    t = re.sub(r"\s+", " ", (content or "").strip())
    if not t:
        return "（空帖）"
    return t[:24] + ("…" if len(t) > 24 else "")


def _date_of(posted_at: str) -> str:
    """微博时间 'Tue Oct 13 21:55:56 +0800 2026' → '2026-10-13'；解析不了就留空。"""
    s = (posted_at or "").strip()
    if not s:
        return ""
    for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except Exception:
            continue
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    return m.group(1) if m else ""


def summarize_pending(limit: int = 60) -> dict:
    posts = db.rows("SELECT * FROM posts WHERE processed=0 ORDER BY id DESC LIMIT ?", (limit,))
    if not posts:
        return {"posts": 0, "digest_id": None, "terms": 0, "message": "没有未处理的帖子"}

    # 1) 每条帖子 → 一条事件（完整原文，不依赖模型）
    for p in posts:
        title = _short_title(p["content"])
        if p.get("author"):
            title = f"{p['author']}：{title}"
        db.run(
            "INSERT INTO events(title, event_date, description, related_terms, people, "
            "source, status, created_at) VALUES(?,?,?,'','','post','pending',?)",
            (title, _date_of(p.get("posted_at", "")), p["content"], db.now()),
        )

    # 2) 一条速览事件（推送用）
    digest_id, digest_text = None, ""
    body = "\n".join(f"- {p['content']}" for p in posts)
    try:
        digest_text = llm.generate(
            f"以下是 {len(posts)} 条超话帖子原文：\n{body}\n\n请写速览。",
            system=DIGEST_SYSTEM, temperature=0.3, max_tokens=800,
        ).strip()
    except Exception as e:
        db.log_run("summarize", "error", f"速览生成失败：{e}")
    if digest_text:
        digest_id = db.run(
            "INSERT INTO events(title, event_date, description, related_terms, people, "
            "source, status, created_at) VALUES(?,'',?,'','','digest','pending',?)",
            (f"📋 超话速览 · {db.now()[11:16]}", digest_text, db.now()),
        )

    # 3) 可选：AI 抽术语
    term_n = 0
    if db.get_setting("ai_terms_enabled", "0") == "1":
        try:
            term_n = terms.extract_terms_from_posts(posts)
        except Exception as e:
            db.log_run("terms", "error", f"抽术语失败：{e}")

    # 4) 标记已处理
    with db.tx() as conn:
        conn.executemany("UPDATE posts SET processed=1 WHERE id=?", [(p["id"],) for p in posts])

    msg = (f"处理 {len(posts)} 帖 → 事件 {len(posts)} 条"
           + (" + 速览 1 条" if digest_id else "（速览生成失败）")
           + (f"，术语候选 +{term_n}" if term_n else ""))
    db.log_run("summarize", "ok", msg)
    return {"posts": len(posts), "digest_id": digest_id, "terms": term_n, "message": msg}
