"""风格档案 —— 把「文案库」里**全部**文案蒸馏成一份可编辑的「风格说明书」，
每次写文案都注入。

为什么要有它：本地模型权重是冻结的，放多少文案进去它「记住」不了。
所以让模型**读完你全部文案**、把规律写成一份说明书，比每次都只挑几条样本更能
体现「越来越像本人」——而且加文案后点一次重新生成，说明书就跟着更新。

（真·把风格学进权重需要微调，见 docs/finetune.md。）
"""
from .. import db, llm

KEY = "style_profile"

SYSTEM = (
    "你是文体分析师。用户会给你一位博主发过的全部微博文案。\n"
    "请提炼出一份**可执行**的写作风格说明，供另一个模型模仿该博主写新文案。\n"
    "要求：\n"
    "- 中文，分点，每点简短具体。「语言生动」这种空话不要写。\n"
    "- 覆盖这些方面：句子长短与节奏；常用句式 / 开头结尾习惯；标点习惯"
    "（爱不爱用～ ！ ？ 省略号）；表情 / 颜文字习惯；高频词与口头禅；"
    "人称与自称；情绪基调；话题标签用法；典型长度区间；明显不会出现的写法（禁忌）。\n"
    "- 每点尽量附 1~2 个原文里的短例。\n"
    "- 给「规律」，不要把原文照抄一遍。\n"
    "- ⚠️ 只描述**文案本身**的写法。原文里的话题标签（#…#）、@提及、日期\n"
    "  （10.05 / 25.12.23）都已经洗掉了，**不要写进档案、也不要说「爱用话题标签」**——\n"
    "  生成时是不要这些装饰的。\n"
)


def get() -> str:
    return db.get_setting(KEY, "") or ""


def save(text: str):
    db.set_setting(KEY, (text or "").strip())


def all_captions_text() -> str:
    """只取**已确认**的文案 —— 待确认的还没经过你核对，不该进风格档案。

    并且**先洗掉话题 / @提及 / 日期**：那是装饰，不是语气。不洗的话档案里会写
    「爱用 #话题#」「开头带日期」，生成时模型就照着写。
    """
    from .captions import strip_decor        # 延迟导入，避免循环引用
    rows = db.rows("SELECT caption_type, content FROM captions "
                   "WHERE status='confirmed' ORDER BY caption_type, id")
    out = []
    for r in rows:
        c = strip_decor(r["content"])
        if c:
            out.append(f"[{r['caption_type']}] {c}")
    return "\n".join(out)


def count_captions() -> int:
    r = db.one("SELECT COUNT(*) c FROM captions WHERE status='confirmed'")
    return r["c"] if r else 0


def generate(max_chars: int = 7000) -> dict:
    """读全部文案 → 让本地模型写风格说明书 → 存起来。"""
    text = all_captions_text()
    if not text.strip():
        return {"ok": False, "error": "文案库是空的，先录入一些你发过的文案"}
    prompt = (f"以下是这位博主发过的 {count_captions()} 条文案：\n\n"
              f"{text[:max_chars]}\n\n请提炼风格说明书。")
    try:
        out = llm.generate(prompt, system=SYSTEM, temperature=0.3, max_tokens=900)
    except Exception as e:
        return {"ok": False, "error": f"模型调用失败：{e}"}
    out = (out or "").strip()
    if out:
        save(out)
    return {"ok": bool(out), "profile": out, "chars": len(out), "captions": count_captions(),
            "error": "" if out else "模型没有返回内容"}
