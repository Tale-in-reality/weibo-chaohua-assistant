"""生成应用图标（粉色品牌）。

跑一次即可：`python tools/make_icon.py`
产出 `assets/icon.ico`（多尺寸）与 `assets/icon.png`（通知弹窗用）。

设计：粉色渐变圆盘 + 白色「镜头」环与中心点 —— 呼应产品的摄影返图定位，
且与托盘图标同源（同一张图，各处一致）。改品牌色/造型改这里，别手改产物。
"""
from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "assets"

SS = 4                      # 超采样倍数（先在放大画布上画，再缩小 → 边缘平滑）
BASE = 256                  # 主尺寸
SIZES = [16, 24, 32, 48, 64, 128, 256]

PINK_TOP = (255, 128, 170)  # 品牌粉（浅）
PINK_BOT = (255, 61, 115)   # 品牌粉（深）—— 中间值即现有 (255, 92, 138)
WHITE = (255, 255, 255, 255)


def _render(size: int = BASE, ss: int = SS) -> Image.Image:
    """在 size*ss 的画布上矢量作画，再缩小到 size，得到抗锯齿结果。"""
    s = size * ss

    # 1) 竖向渐变底
    grad = Image.new("RGBA", (s, s))
    d = ImageDraw.Draw(grad)
    for y in range(s):
        t = y / (s - 1)
        col = tuple(round(a + (b - a) * t) for a, b in zip(PINK_TOP, PINK_BOT))
        d.line([(0, y), (s, y)], fill=col + (255,))

    # 2) 圆盘遮罩（留一点内边距，缩小后更透气）
    inset = round(s * 0.03)
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).ellipse([inset, inset, s - 1 - inset, s - 1 - inset], fill=255)

    disc = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    disc.paste(grad, (0, 0), mask)

    # 3) 白色「镜头」：外环 + 中心点
    dd = ImageDraw.Draw(disc)
    c = s / 2
    r1, w, r3 = s * 0.30, max(1, round(s * 0.085)), s * 0.115

    def ring(rad, width):
        dd.ellipse([c - rad, c - rad, c + rad, c + rad], outline=WHITE, width=width)

    ring(r1, w)
    dd.ellipse([c - r3, c - r3, c + r3, c + r3], fill=WHITE)

    return disc.resize((size, size), Image.LANCZOS)


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    base = _render(BASE)

    ico = ASSETS / "icon.ico"
    base.save(ico, format="ICO", sizes=[(n, n) for n in SIZES])

    png = ASSETS / "icon.png"
    _render(512).save(png, format="PNG")   # 通知用，稍大更清晰

    print(f"已生成：{ico}")
    print(f"已生成：{png}")


if __name__ == "__main__":
    main()
