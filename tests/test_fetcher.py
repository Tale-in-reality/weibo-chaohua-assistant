"""抓取模块的纯函数测试（水贴过滤 / 时间解析 / containerid 归一化）。"""
import pytest

from app import db
from app.modules import fetcher as F


def test_sorted_cid_normalizes_suffix():
    db.set_setting("weibo_containerid", "100808abc_-_feed")
    assert F._sorted_cid() == "100808abc_-_sort_time"
    db.set_setting("weibo_containerid", "100808abc")
    assert F._sorted_cid() == "100808abc_-_sort_time"
    db.set_setting("weibo_containerid", "")          # 还原，别影响别的用例


def test_parse_time_absolute():
    dt = F._parse_time("Tue Oct 13 23:28:11 +0800 2026")
    assert dt is not None
    assert (dt.year, dt.month, dt.day) == (2026, 10, 13)


@pytest.mark.parametrize("text", ["刚刚", "5分钟前", "2小时前", "今天 12:30", "昨天 09:05"])
def test_parse_time_relative(text):
    assert F._parse_time(text) is not None


@pytest.mark.parametrize("text", ["", "   ", "看不出时间", "abc"])
def test_parse_time_garbage(text):
    assert F._parse_time(text) is None


@pytest.mark.parametrize("text,expected", [
    # 水贴：几个字 / 纯表情 / 只有转发链
    ("王一博 晚安！", True),
    ("💚💚💚", True),
    ("[doge][doge]", True),
    ("#话题# 王一博 //@某人:转发的一大段内容", True),
    ("//@A:哈哈哈//@B:太可爱了", True),
    # 水贴：**长但全是灌水** —— 只看长度会漏掉这些
    ("加油加油加油加油天天开心", True),
    ("好棒好棒好棒好棒好棒", True),
    ("哈哈哈哈哈哈", True),
    ("太帅了啊啊啊啊啊啊", True),
    ("好帅好帅好帅", True),
    # 真帖：本人有实质内容（转发但带评论 / 普通长文）
    ("真的太好看了！！这段镜头我能看一百遍 //@某人:原图", False),
    ("今天路透拍到哥哥穿白色羽绒服状态超好", False),
    ("25.12.23声生不息中场下班", False),
    ("#声生不息# 25.12.23中场下班", False),
])
def test_is_noise(text, expected):
    assert F._is_noise(text) is expected


def test_repeat_ratio_separates_filler_from_real_text():
    assert F._repeat_ratio("加油加油加油加油") > 0.6
    assert F._repeat_ratio("今天路透拍到哥哥穿白色羽绒服") < 0.3


@pytest.mark.parametrize("raw", [
    '正文很长很长<a href="/status/123">全文</a>',
    '正文很长很长<a href="https://m.weibo.cn/detail/123">展开</a>',
])
def test_clean_strips_truncation_marker(raw):
    """长文被截断时末尾挂的「全文/展开」不能留在正文里。"""
    out = F._clean(raw)
    assert "全文" not in out and "展开" not in out
    assert out.startswith("正文很长很长")


def test_is_noise_strips_repost_chain():
    """核心语义：`//@` 后面的内容不算本人所言。"""
    assert F._is_noise("王一博 //@A:今天天气真不错大家都要开心哦") is True
    assert F._is_noise("今天天气真不错大家都要开心哦 //@A:图") is False
