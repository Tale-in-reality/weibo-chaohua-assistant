"""事件库 CRUD。"""
from .. import db

# 「速览」始终置顶（新→旧），其余按时间排。(source='digest') 在 SQLite 里得 1/0
_ORDER = "ORDER BY (source='digest') DESC, event_date DESC, id DESC"


def list_events(status: str | None = None, source: str | None = None,
                q: str = "", limit: int = 100, offset: int = 0) -> dict:
    """分页 + 筛选。返回 {items, total, limit, offset}。

    现在「每帖一条事件」，条数会很快上千，所以**必须**分页——不能一次全返回。
    """
    where, params = [], []
    if status:
        where.append("status=?")
        params.append(status)
    if source:
        where.append("source=?")
        params.append(source)
    q = (q or "").strip()
    if q:
        where.append("(title LIKE ? OR description LIKE ? OR people LIKE ? OR related_terms LIKE ?)")
        params += [f"%{q}%"] * 4
    w = ("WHERE " + " AND ".join(where)) if where else ""

    total = db.one(f"SELECT COUNT(*) c FROM events {w}", params)["c"]
    limit = max(1, min(int(limit or 100), 500))
    offset = max(0, int(offset or 0))
    items = db.rows(f"SELECT * FROM events {w} {_ORDER} LIMIT ? OFFSET ?",
                    params + [limit, offset])
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def count_events(status: str | None = None) -> int:
    if status:
        return db.one("SELECT COUNT(*) c FROM events WHERE status=?", (status,))["c"]
    return db.one("SELECT COUNT(*) c FROM events")["c"]


def add_event(title: str, event_date: str = "", description: str = "",
              related_terms: str = "", people: str = "",
              source: str = "manual", status: str = "confirmed") -> int:
    return db.run(
        "INSERT INTO events(title, event_date, description, related_terms, people, source, status, created_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (title, event_date, description, related_terms, people, source, status, db.now()),
    )


def update_event(eid: int, **fields):
    allowed = ["title", "event_date", "description", "related_terms", "people", "status"]
    sets, params = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            params.append(v)
    if not sets:
        return
    params.append(eid)
    db.run(f"UPDATE events SET {', '.join(sets)} WHERE id=?", params)


def delete_event(eid: int):
    db.run("DELETE FROM events WHERE id=?", (eid,))
