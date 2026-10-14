"""检索：BM25 排序 + 风格档案注入。"""
from app import db
from app.modules import captions as C
from app.modules import style
from app.util import bm25_rank

DOCS = [
    (1, "今天的路透照片里哥哥穿了白色羽绒服状态很好"),
    (2, "工作室发声明回应机场事件"),
    (3, "新歌预告放出来了前奏好听"),
]


def test_bm25_picks_the_relevant_doc():
    r = bm25_rank("路透 羽绒服", DOCS)
    assert r and r[0][0] == 1


def test_bm25_scores_are_descending():
    r = bm25_rank("路透 羽绒服 哥哥", DOCS)
    scores = [s for _, s in r]
    assert scores == sorted(scores, reverse=True)


def test_bm25_degenerate_inputs():
    assert bm25_rank("", DOCS) == []
    assert bm25_rank("路透", []) == []
    assert bm25_rank("完全无关的词汇", DOCS) == []      # 无词重叠 → 无命中


def test_sample_limit_reads_setting():
    db.set_setting("style_samples", "3")
    assert C._sample_limit() == 3
    db.set_setting("style_samples", "99999")
    assert C._sample_limit() == 40                     # 上限夹住
    db.set_setting("style_samples", "abc")
    assert C._sample_limit() == 8                      # 非法值回默认
    db.set_setting("style_samples", "8")


def test_style_profile_is_injected_only_when_set():
    style.save("")
    assert "我的风格" not in C.build_prompt("写 {target}", {"target": "x"})[0]

    style.save("  爱用省略号和哈哈哈哈  ")
    assert style.get() == "爱用省略号和哈哈哈哈"          # 存的时候 strip
    assert "我的风格" in C.build_prompt("写 {target}", {"target": "x"})[0]

    style.save("")                                     # 收尾，别影响其他用例


def test_all_captions_text_and_count():
    with db.tx() as conn:
        conn.execute("DELETE FROM captions")
    assert style.all_captions_text() == ""
    assert style.count_captions() == 0
    C.add_caption("测试文案一", caption_type="返图")
    assert style.count_captions() == 1
    assert "测试文案一" in style.all_captions_text()
    with db.tx() as conn:
        conn.execute("DELETE FROM captions")
