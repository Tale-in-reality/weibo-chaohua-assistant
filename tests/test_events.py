"""事件库：分页 / 筛选 / 速览置顶。"""
from app import db
from app.modules import events


def _seed():
    with db.tx() as conn:
        conn.execute("DELETE FROM events")
    events.add_event("手动事件A", "2026-10-10", "x", status="confirmed")
    events.add_event("手动事件B", "2026-10-12", "y", status="confirmed")
    db.run("INSERT INTO events(title,event_date,description,source,status,created_at) "
           "VALUES('超话速览·旧','','s1','digest','pending',?)", (db.now(),))
    db.run("INSERT INTO events(title,event_date,description,source,status,created_at) "
           "VALUES('超话速览·新','','s2','digest','pending',?)", (db.now(),))


def test_digest_first_then_by_date():
    _seed()
    r = events.list_events(limit=10)
    titles = [e["title"] for e in r["items"]]
    assert titles[0] == "超话速览·新" and titles[1] == "超话速览·旧"   # 速览置顶（新→旧）
    assert titles[2:] == ["手动事件B", "手动事件A"]                    # 其余按日期倒序


def test_filter_by_status_and_source():
    _seed()
    assert events.list_events(status="pending")["total"] == 2
    assert events.list_events(source="digest")["total"] == 2
    assert events.list_events(status="confirmed")["total"] == 2


def test_search():
    _seed()
    assert events.list_events(q="速览")["total"] == 2
    assert events.list_events(q="不存在的东西")["total"] == 0


def test_pagination_and_clamp():
    _seed()
    page = events.list_events(limit=2, offset=0)
    assert len(page["items"]) == 2 and page["total"] == 4
    page2 = events.list_events(limit=2, offset=2)
    assert len(page2["items"]) == 2
    assert {e["id"] for e in page["items"]}.isdisjoint({e["id"] for e in page2["items"]})
    assert events.list_events(limit=99999)["limit"] == 500      # 上限被夹住
