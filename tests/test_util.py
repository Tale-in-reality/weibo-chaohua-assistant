"""公共工具：JSON 抠取 + 分词。"""
from app.util import extract_json_array, extract_json_object, tokens


def test_extract_json_array_plain():
    assert extract_json_array('[{"a": 1}, {"b": 2}]') == [{"a": 1}, {"b": 2}]


def test_extract_json_array_wrapped_in_prose():
    text = '好的，结果是：[{"term":"面包","meaning":"昵称"}] 就这样。'
    assert extract_json_array(text) == [{"term": "面包", "meaning": "昵称"}]


def test_extract_json_array_bad_input():
    assert extract_json_array("完全不是 JSON") is None
    assert extract_json_array("") is None
    assert extract_json_array("[不是合法 json]") is None


def test_extract_json_object():
    assert extract_json_object('{"known": true, "meaning": "x"}') == {"known": True, "meaning": "x"}
    assert extract_json_object("no json here") is None


def test_tokens_filters_single_chars_and_punct():
    got = tokens("今天，路透拍到哥哥！")
    assert "路透" in got
    assert "，" not in got
    assert "，" not in got
    # 单字不该进集合
    assert all(len(w) >= 2 for w in got)
