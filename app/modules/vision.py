"""云端视觉模型（OpenAI 兼容中转站）——识图写文案的 Stage 1。

设计：「看图描述」比「创作文案」简单，交给云端 VLM；写文案仍用本地 7B。
照片会离开本机，故默认关闭；地址 / 密钥 / 模型全部由用户在设置页填写。
"""
import base64
import io

import httpx
from PIL import ExifTags, Image

from .. import db


# ---------- 设置（每次调用懒读，与 llm.py 一致） ----------

def _base() -> str:
    return db.get_setting("vision_base_url", "").rstrip("/")


def _key() -> str:
    return db.get_setting("vision_api_key", "")


def _model() -> str:
    return db.get_setting("vision_model", "")


def _enabled() -> bool:
    return db.get_setting("vision_enabled", "0") == "1"


def _max_side() -> int:
    try:
        return int(db.get_setting("vision_max_side", "1568") or 1568)
    except Exception:
        return 1568


def _headers() -> dict:
    return {"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"}


def configured() -> bool:
    return bool(_base() and _key() and _model())


DEFAULT_PROMPT = (
    "你在为一位粉丝站子的摄影师描述照片，用于帮他写微博返图文案。请客观、具体、用短句。\n"
    "按下面的方面逐行输出，每行以「方面：」开头：\n"
    "人物姿态 / 表情 / 视线 / 服装造型 / 光线 / 背景 / 构图 / 色调 / 情绪\n"
    "要求：\n"
    "- 只描述画面里真实可见的东西，不要猜测人物身份、姓名或真实关系。\n"
    "- 不要评价美丑，不要写文案，不要输出标题或多余解释。\n"
    "- 每行不超过 20 字；看不清的方面写「不确定」。"
)


# ---------- 中转站调用 ----------

def list_models() -> list:
    """拉取中转站模型列表（供设置页下拉）。软失败返回 []。"""
    try:
        r = httpx.get(_base() + "/models", headers=_headers(), timeout=10)
        r.raise_for_status()
        j = r.json()
        data = j.get("data") or j.get("models") or []
        out = []
        for m in data:
            mid = m.get("id") or m.get("name") if isinstance(m, dict) else str(m)
            if mid:
                out.append(mid)
        return out
    except Exception:
        return []


def prepare(image_bytes: bytes, mime: str):
    """缩放 + 重编码为 JPEG：控制体积、省 token，并顺带剥离 EXIF。失败则原样返回。"""
    try:
        im = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        max_side = _max_side()
        if max(im.size) > max_side:
            im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        return image_bytes, mime or "image/png"


def describe(image_bytes: bytes, mime: str = "image/png", hint: str = "") -> str:
    """调用云端 VLM 描述照片。失败时抛异常（由 API 层转成中文错误）。"""
    if not _enabled():
        raise RuntimeError("识图未开启（请在设置页打开「开启识图」）")
    if not configured():
        raise RuntimeError("未配置识图中转站（请在设置页填写地址 / 密钥 / 模型）")
    data, mime = prepare(image_bytes, mime)
    b64 = base64.b64encode(data).decode()
    prompt = db.get_setting("vision_prompt", "") or DEFAULT_PROMPT
    if hint:
        prompt = prompt + "\n补充提示：" + hint
    payload = {
        "model": _model(),
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
        ]}],
        "max_tokens": 500,
        "temperature": 0.4,
    }
    r = httpx.post(_base() + "/chat/completions", headers=_headers(), json=payload, timeout=120)
    r.raise_for_status()
    j = r.json()
    return (j.get("choices", [{}])[0].get("message", {}).get("content", "") or "").strip()


# ---------- EXIF ----------

# 用整数 tag 而非 ExifTags.Base 名称，跨 Pillow 版本更稳
_MAKE, _MODEL_T, _LENS = 0x010F, 0x0110, 0xA434
_FNUM, _EXPO, _ISO = 0x829D, 0x829A, 0x8827
_FOCAL, _FOCAL35 = 0x920A, 0xA405


def _fmt_exposure(v) -> str:
    try:
        v = float(v)
    except Exception:
        return ""
    if 0 < v < 1:
        return f"1/{round(1 / v)}s"
    return f"{v:g}s"


def exif_summary(image_bytes: bytes) -> str:
    """把常见拍摄参数压成一行中文，如 `Canon EOS R6 · 50mm · f/1.8 · 1/500s · ISO 400`。
    无 EXIF（截图 / 转发图）返回空串。注意：必须在重编码前读原图。"""
    try:
        exif = Image.open(io.BytesIO(image_bytes)).getexif()
        if not exif:
            return ""
        try:
            ifd = exif.get_ifd(ExifTags.IFD.Exif) or {}
        except Exception:
            ifd = {}

        cam = " ".join(x for x in [str(exif.get(_MAKE) or "").strip(),
                                   str(exif.get(_MODEL_T) or "").strip()] if x).strip()
        lens = ifd.get(_LENS)
        focal, focal35 = ifd.get(_FOCAL), ifd.get(_FOCAL35)
        fnum, expo, iso = ifd.get(_FNUM), ifd.get(_EXPO), ifd.get(_ISO)

        parts = []
        if cam:
            parts.append(cam)
        if lens:
            parts.append(str(lens).strip())
        if focal:
            try:
                parts.append(f"{float(focal):g}mm")
            except Exception:
                pass
        elif focal35:
            try:
                parts.append(f"等效{int(focal35)}mm")
            except Exception:
                pass
        if fnum:
            try:
                parts.append(f"f/{float(fnum):g}")
            except Exception:
                pass
        e = _fmt_exposure(expo)
        if e:
            parts.append(e)
        if iso:
            try:
                parts.append(f"ISO {int(iso)}")
            except Exception:
                pass
        return " · ".join(parts)
    except Exception:
        return ""
