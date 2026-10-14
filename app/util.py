"""公共小工具。"""
import json
import math
import re
from collections import Counter

_jieba = None


def _get_jieba():
    global _jieba
    if _jieba is None:
        import jieba
        jieba.setLogLevel(60)
        _jieba = jieba
    return _jieba


def tokens(text: str) -> set:
    """分词后的「实义词」集合（去单字、去纯符号），用于重叠打分。

    jieba 不可用时回退到「单字集合」，不会抛异常。
    """
    t = text or ""
    try:
        words = _get_jieba().lcut(t)
    except Exception:
        return set(t)
    return {w for w in words if len(w) >= 2 and not re.fullmatch(r"[\W_]+", w)}


def extract_json_array(text: str):
    """从模型输出里抠出最外层 JSON 数组。解析失败返回 None（调用方自行降级）。"""
    m = re.search(r"\[.*\]", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def extract_json_object(text: str):
    """从模型输出里抠出最外层 JSON 对象。解析失败返回 None。"""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def bm25_rank(query: str, docs: list, k1: float = 1.5, b: float = 0.75) -> list:
    """BM25 检索。docs = [(key, text), ...]；返回 [(key, score)] 降序、只保留 score>0。

    纯 Python、零依赖：比「字符集合重叠」准得多（会考虑词频与文档长度归一化），
    且不需要下载 embedding 模型 —— 对本地优先的场景是性价比最高的检索方式。
    """
    q = tokens(query)
    if not q or not docs:
        return []
    tokenized = [(key, tokens(text)) for key, text in docs]
    n = len(tokenized)
    avgdl = (sum(len(d) for _, d in tokenized) / n) or 1.0

    df = Counter()
    for _, d in tokenized:
        for w in set(d):
            df[w] += 1

    out = []
    for key, d in tokenized:
        tf = Counter(d)
        dl = len(d) or 1
        s = 0.0
        for w in q:
            if w not in tf:
                continue
            idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
            s += idf * (tf[w] * (k1 + 1)) / (tf[w] + k1 * (1 - b + b * dl / avgdl))
        if s > 0:
            out.append((key, s))
    out.sort(key=lambda x: -x[1])
    return out
