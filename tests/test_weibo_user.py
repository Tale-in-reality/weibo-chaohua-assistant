"""从微博导入文案：纯函数测试（不联网）。"""
from app.modules import weibo_user as W


def test_clean_caption_removes_topic_link_entirely():
    """超话链接要连它显示的文字一起去掉 —— 那不是本人写的字。"""
    raw = ('今天好累 <a href="https://m.weibo.cn/p/index?containerid=100808abc&amp;x=1">'
           '某超话</a> 但还是很开心')
    assert W._clean_caption(raw) == "今天好累 但还是很开心"


def test_clean_caption_strips_trailing_fulltext_link():
    raw = '一段很长的正文……<a href="https://m.weibo.cn/statuses/show?id=1">全文</a>'
    assert W._clean_caption(raw) == "一段很长的正文……"


def test_clean_caption_preserves_line_breaks():
    """换行是本人的排版习惯，必须保住（微博用 <br /> 分行）。"""
    assert W._clean_caption("第一行<br />第二行<br /><br />第四行") == "第一行\n第二行\n\n第四行"
    assert W._clean_caption("A<br/>&nbsp;&nbsp;B　C") == "A\nB C"      # 全角空格也折叠


def test_clean_caption_keeps_hashtag_but_drops_super_topic_badge():
    """`#话题#`（search 链接）要保留；超话徽章（/p/index 链接）要连文字一起去掉。"""
    raw = ('<a href="https://m.weibo.cn/search?q=%23X%23">#声生不息#</a> 好看 '
           '<a href="https://m.weibo.cn/p/index?containerid=100808abc">二手</a>')
    assert W._clean_caption(raw) == "#声生不息# 好看"


def test_clean_caption_unescapes_entities():
    assert W._clean_caption("&lt;3 哈哈哈") == "<3 哈哈哈"


def test_resolve_user_accepts_plain_uid():
    r = W.resolve_user("1234567890")
    assert r["ok"] and r["candidates"][0]["uid"] == "1234567890"


def test_resolve_user_accepts_profile_url():
    for url in ("https://m.weibo.cn/u/1234567890?launchid=x",
                "https://weibo.com/u/1234567890"):
        r = W.resolve_user(url)
        assert r["ok"] and r["candidates"][0]["uid"] == "1234567890"


def test_resolve_user_rejects_empty():
    r = W.resolve_user("   ")
    assert r["ok"] is False and "请输入" in r["error"]


def test_list_captions_newest_first_by_posted_at():
    """文案列表按**原帖时间**排，不是按插入顺序。

    导入是按时间线「新→旧」逐页插的，最后插入的反而是最旧的；
    所以不能按 id 排，否则最旧的在最上面。
    """
    from app import db
    from app.modules import captions as C

    with db.tx() as conn:
        conn.execute("DELETE FROM captions")
    # 模拟导入：先插新的、再插旧的（id 递增，但时间递减）
    db.run("INSERT INTO captions(content,caption_type,source,mid,posted_at,created_at) "
           "VALUES('新的','返图','weibo','m1','2026-10-12 12:00:00',?)", (db.now(),))
    db.run("INSERT INTO captions(content,caption_type,source,mid,posted_at,created_at) "
           "VALUES('旧的','返图','weibo','m2','2026-01-01 00:00:00',?)", (db.now(),))

    got = [c["content"] for c in C.list_captions()]
    assert got[0] == "新的", "最新的应在最上面"
    assert got[1] == "旧的"


def test_list_captions_falls_back_to_created_at_for_manual_entries():
    """手动录入没有 posted_at → 用录入时间排，不能因此漏掉或跑到最后。"""
    from app import db
    from app.modules import captions as C

    with db.tx() as conn:
        conn.execute("DELETE FROM captions")
    db.run("INSERT INTO captions(content,caption_type,source,created_at) "
           "VALUES('手动条','返图','manual',?)", (db.now(),))
    db.run("INSERT INTO captions(content,caption_type,source,mid,posted_at,created_at) "
           "VALUES('导入的旧帖','返图','weibo','m3','2020-01-01 00:00:00',?)", (db.now(),))

    got = [c["content"] for c in C.list_captions()]
    assert "手动条" in got and got[0] == "手动条"      # 刚录的排在最前


def test_captions_split_by_status():
    """导入的先落 pending；手动录入默认 confirmed。列表按 status 分。"""
    from app import db
    from app.modules import captions as C

    with db.tx() as conn:
        conn.execute("DELETE FROM captions")
    db.run("INSERT INTO captions(content,caption_type,source,mid,status,created_at) "
           "VALUES('待确认的','返图','weibo','m1','pending',?)", (db.now(),))
    db.run("INSERT INTO captions(content,caption_type,source,created_at) "
           "VALUES('手动的','返图','manual',?)", (db.now(),))   # 不写 status → 用默认值

    assert [c["content"] for c in C.list_captions("pending")] == ["待确认的"]
    assert [c["content"] for c in C.list_captions("confirmed")] == ["手动的"]
    assert len(C.list_captions()) == 2                      # 不传 = 全部
    cnt = C.count_captions()
    assert cnt["pending"] == 1 and cnt["confirmed"] == 1 and cnt["total"] == 2


def test_pending_captions_not_used_as_style_samples():
    """没确认的文案不该参与生成（那就是「确认后入库」的意义）。"""
    from app import db
    from app.modules import captions as C

    with db.tx() as conn:
        conn.execute("DELETE FROM captions")
    db.run("INSERT INTO captions(content,caption_type,source,mid,status,created_at) "
           "VALUES('还没确认的','返图','weibo','m9','pending',?)", (db.now(),))
    assert C._style_samples("随便", "返图", limit=10) == []

    db.run("INSERT INTO captions(content,caption_type,source,created_at) "
           "VALUES('已确认的','返图','manual',?)", (db.now(),))
    got = C._style_samples("随便", "返图", limit=10)
    assert [c["content"] for c in got] == ["已确认的"]


def test_song_captions_excluded_from_style_pool():
    """绑定某首歌的文案不进风格样本池 —— 那才是不污染通用语气的关键。"""
    from app import db
    from app.modules import captions as C

    with db.tx() as conn:
        conn.execute("DELETE FROM captions")
    db.run("INSERT INTO captions(content,caption_type,source,created_at) "
           "VALUES('普适文案','返图','manual',?)", (db.now(),))
    db.run("INSERT INTO captions(content,caption_type,source,scope,song,created_at) "
           "VALUES('唱到副歌哭了','返图','manual','song','背影',?)", (db.now(),))

    assert [c["content"] for c in C.list_captions("confirmed", "general")] == ["普适文案"]
    assert [c["content"] for c in C.list_captions("confirmed", "song")] == ["唱到副歌哭了"]
    assert [s["song"] for s in C.list_songs()] == ["背影"]

    got = C._style_samples("随便", "返图", limit=10)
    assert [c["content"] for c in got] == ["普适文案"], "歌曲文案不该当风格样本"

    cnt = C.count_captions()
    assert cnt["confirmed"] == 2 and cnt["general"] == 1 and cnt["song"] == 1


def test_ref_song_injected_as_reference_only():
    """选了某首歌 → 注入「参考」块；但风格样本里仍然没有它。"""
    from app import db
    from app.modules import captions as C

    with db.tx() as conn:
        conn.execute("DELETE FROM captions")
    db.run("INSERT INTO captions(content,caption_type,source,created_at) "
           "VALUES('普适文案','返图','manual',?)", (db.now(),))
    db.run("INSERT INTO captions(content,caption_type,source,scope,song,created_at) "
           "VALUES('唱到副歌哭了','返图','manual','song','背影',?)", (db.now(),))

    p_no, used_no = C.build_prompt("写 {target}", {"target": "x"})
    assert "参考：与《背影》" not in p_no
    assert used_no["ref_song"] == ""

    p_yes, used_yes = C.build_prompt("写 {target}", {"target": "x", "ref_song": "背影"})
    assert "参考：与《背影》" in p_yes and "唱到副歌哭了" in p_yes
    assert used_yes["ref_song"] == "背影" and used_yes["ref_count"] == 1
    # 参考块里不该混进普适文案之外的东西，风格样本仍只有普适那条
    assert used_yes["samples"] == 1


def test_strip_decor_removes_topic_at_date():
    """话题 / @提及 / 日期是「装饰」，不该进风格，生成时也不要。"""
    from app.modules.captions import strip_decor
    assert strip_decor("#黄霄雲# 25.12.23声生不息中场下班 @黄龄") == "声生不息中场下班"
    assert strip_decor("拍到了！\n#王一博#\n10.05 太帅") == "拍到了！\n\n太帅"
    assert strip_decor("普通文案，没有装饰") == "普通文案，没有装饰"
    assert strip_decor("2026-10-05 场馆") == "场馆"


def test_style_placeholder_expands_and_no_duplicate():
    """模板里写 {style} 就按那个位置展开；没写就自动附在最后。两者都只出现一次。"""
    from app import db
    from app.modules import captions as C

    db.set_setting("style_profile", "【风格】爱用省略号…")
    try:
        p1, _ = C.build_prompt("写 {target} {style}", {"target": "x"})
        assert "【风格】" in p1 and p1.count("【风格】") == 1

        p2, _ = C.build_prompt("写 {target}", {"target": "x"})
        assert p2.count("【风格】") == 1
    finally:
        db.set_setting("style_profile", "")


def test_style_profile_input_is_sanitized():
    """**生成档案时**喂进去的文案要洗掉话题/@/日期 ——
    否则档案里会写「爱用话题标签」，生成时模型就照着挂话题。
    （注意：已有的旧档案不会自动变干净，必须重新生成一次。）"""
    from app import db
    from app.modules import style as S

    with db.tx() as conn:
        conn.execute("DELETE FROM captions")
    db.run("INSERT INTO captions(content,caption_type,source,created_at) "
           "VALUES('#话题# 25.12.23 拍得真好 @某人','返图','manual',?)", (db.now(),))

    text = S.all_captions_text()
    assert "话题" not in text and "25.12.23" not in text and "@某人" not in text
    assert "拍得真好" in text


def test_length_hint_and_no_decor_rule_in_system():
    from app.modules import captions as C
    p, _ = C.build_prompt("写 {target}", {"target": "x", "max_chars": 80})
    assert "【长度要求】正文控制在 80 字左右" in p
    assert "不要写 #话题#" in C.SYSTEM
