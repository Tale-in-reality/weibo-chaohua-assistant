"""全局路径与默认配置。"""
import os
import sys
from pathlib import Path

# ── 冻结（PyInstaller）检测 ─────────────────────────────────────────────
# 打包后 __file__ 指向解包出的只读目录，`data/` 必须落到 exe 旁边（可写、便携）。
#   BASE_DIR：可写根目录（冻结时 = exe 所在文件夹；开发时 = 仓库根）
#   RES_DIR ：只读资源根目录（冻结时 = _MEIPASS；开发时 = 仓库根）
FROZEN = bool(getattr(sys, "frozen", False))
if FROZEN:
    BASE_DIR = Path(sys.executable).resolve().parent
    RES_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
else:
    BASE_DIR = RES_DIR = Path(__file__).resolve().parent.parent

APP_DIR = RES_DIR / "app"
WEB_DIR = RES_DIR / "web"
ASSETS_DIR = RES_DIR / "assets"
MODELS_DIR = RES_DIR / "models"
ICON_ICO = ASSETS_DIR / "icon.ico"     # 窗口 / 任务栏 / 托盘 / exe 图标
ICON_PNG = ASSETS_DIR / "icon.png"     # 通知弹窗图标（winotify 只吃 .png）


def _writable_dir(preferred: Path) -> Path:
    """优先用 exe 旁的 data/；装到只读目录（如 Program Files）时回退到 LOCALAPPDATA。

    打包成文件夹版后正常在桌面/下载目录解压，这里是可写的；回退只为极端情况兜底。
    """
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        return preferred
    except Exception:
        alt = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "WeiboChaohuaAssistant"
        alt.mkdir(parents=True, exist_ok=True)
        return alt


DATA_DIR = _writable_dir(BASE_DIR / "data")
DB_PATH = DATA_DIR / "fan.db"

HOST = "127.0.0.1"

# ── 端口：优先用 DEFAULT_PORT，被占则运行时换成空闲口（见 main.pick_port）──
DEFAULT_PORT = 8756
PORT = DEFAULT_PORT                    # 运行时可变；跨进程读 PORT_FILE
PORT_FILE = DATA_DIR / "port"          # toast_click.py（独立进程）靠它拿到当前端口

APP_NAME = "微博超话助手"
VERSION = "0.1.0"


def set_port(port: int) -> int:
    """记录本次实际监听端口，并落盘供跨进程读取。"""
    global PORT
    PORT = int(port)
    try:
        PORT_FILE.write_text(str(PORT), encoding="utf-8")
    except Exception:
        pass
    return PORT


def get_port() -> int:
    """本进程当前端口（注意别 `from .config import PORT` —— 那是值快照，不会跟着变）。"""
    return PORT


def read_port_file() -> int:
    """跨进程读当前端口（toast_click / 单实例唤起用）。读不到回退默认端口。"""
    try:
        return int(PORT_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return DEFAULT_PORT

# 设置项默认值（首次写库时插入，之后以库为准）
DEFAULT_SETTINGS = {
    "ollama_url": "http://127.0.0.1:11434",
    "model": "qwen2.5:7b-instruct",

    "style_samples": "8",         # 每次写文案注入几条风格样本（BM25 挑，同类型加权）

    "push_enabled": "1",          # 是否开启桌面推送
    "push_interval_min": "30",    # 推送刷新间隔（分钟）

    "summarize_enabled": "0",     # 是否开启自动总结
    "summarize_interval_min": "60",  # 总结频率（分钟）

    "autostart": "0",             # 开机自启
    "close_action": "ask",        # 点窗口×时：ask 询问 / minimize 最小化到托盘 / quit 直接退出

    "setup_wizard_done": "0",     # 首启环境向导是否已完成/已跳过（1 后不再自动弹）

    "sms_enabled": "0",           # 短信推送（预留）
    "sms_provider": "",
    "sms_config": "",

    "weibo_cookie": "",               # 超话抓取：登录 cookie（用小号！）
    "weibo_containerid": "",          # 超话 containerid（从超话页 XHR 复制完整值）
    "weibo_container_name": "",       # 该超话的名字（选定后存下，用于界面显示）
    "weibo_fetch_enabled": "0",       # 是否开启自动抓取（默认关，安全）
    "weibo_fetch_interval_min": "60", # 抓取间隔（分钟，可改）
    "weibo_autosummarize": "1",       # 抓完有新帖就自动总结
    "ai_terms_enabled": "0",          # 总结时让 AI 顺带识别可能的术语（进术语词典待确认）
    "weibo_max_pages": "20",          # 每次最多抓几页（安全上限；抓窗口内的帖）
    "weibo_max_fulltext": "40",       # 每次最多取几篇长文的全文（每篇多一次请求）
    "weibo_user_agent": "",           # 留空用内置移动端 UA

    "vision_enabled": "0",        # 识图（照片会上传到中转站，默认关）
    "vision_base_url": "",        # OpenAI 兼容地址，含 /v1
    "vision_api_key": "",         # 中转站密钥
    "vision_model": "",           # 识图模型名（用户自选）
    "vision_prompt": "",          # 留空则用 vision.DEFAULT_PROMPT
    "vision_max_side": "1568",    # 上传前缩放的最长边
}

# 预提示词模板：(名称, 类型, 内容)
DEFAULT_TEMPLATES = [
    (
        "返图文案",
        "返图",
        "为这条微博返图写文案。\n"
        "拍摄对象：{target}\n"
        "图频类型：{media_type}\n"
        "想要的氛围/情绪：{mood}\n"
        "想表达的要点：{points}\n\n"
        "要求：\n"
        "- 站在我（拍摄者/站子）的视角写\n"
        "- 短，一两句为主\n"
        "- 自然带出下方「可联想」里的梗或事件，用对含义，不要硬塞\n"
        "- 模仿「风格样本」的语气，但不要照抄句子\n"
        "- 直接给文案，不要解释；不要 #话题#、不要 @某人、不要日期\n"
        "\n{style}",
    ),
    (
        "控评文案",
        "控评",
        "写一条微博控评文案。\n"
        "对象：{target}\n"
        "要点：{points}\n\n"
        "要求：短、有力、正向，符合粉丝语境，模仿风格样本语气。直接给文案；"
        "不要 #话题#、不要 @某人、不要日期。\n"
        "\n{style}",
    ),
    (
        "安利文案",
        "安利",
        "写一条安利文案。\n"
        "对象：{target}\n"
        "想突出的点：{points}\n"
        "氛围：{mood}\n\n"
        "要求：有感染力，自然带出相关梗/事件（用对含义），模仿风格样本语气。直接给文案；"
        "不要 #话题#、不要 @某人、不要日期。\n"
        "\n{style}",
    ),
    (
        "日常文案",
        "日常",
        "写一条日常发文文案。\n"
        "对象：{target}\n"
        "想说的：{points}\n"
        "情绪：{mood}\n\n"
        "要求：口语、自然，模仿风格样本语气。直接给文案；"
        "不要 #话题#、不要 @某人、不要日期。\n"
        "\n{style}",
    ),
]
