"""推送：Windows 桌面弹窗 + 短信（预留）。"""
import os
import shutil

from . import db
from .config import ICON_PNG


def _ensure_powershell_on_path() -> None:
    """winotify 内部用 subprocess 调 'powershell.exe'，靠 PATH 查找。
    若进程从精简 PATH 启动（某些快捷方式/受限环境），会 FileNotFoundError 而静默失败。
    这里把 PowerShell 目录补进 PATH。"""
    ps_dir = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                          "System32", "WindowsPowerShell", "v1.0")
    if not os.path.isdir(ps_dir):
        return
    if ps_dir.lower() not in [p.lower() for p in os.environ.get("PATH", "").split(os.pathsep) if p]:
        os.environ["PATH"] = ps_dir + os.pathsep + os.environ.get("PATH", "")


_ensure_powershell_on_path()

try:
    from winotify import Notification, audio
    _HAS_WINOTIFY = True
except Exception:
    _HAS_WINOTIFY = False

APP_ID = "微博超话助手"
SCHEME = "chaohua"          # 桌面弹窗点击用的自定义协议 → 唤起 app 窗口
_LAST_ERROR = ""


def _click_command() -> str:
    """点击弹窗时系统实际执行的命令。

    - 打包态：`app.exe --toast-click "%1"`（复用同一个 exe，跟主程序同路径，最稳）。
    - 开发态：`pythonw.exe app/toast_click.py "%1"`。
    """
    import sys
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --toast-click "%1"'
    from pathlib import Path
    script = Path(__file__).resolve().parent / "toast_click.py"
    pyw = Path(sys.executable).with_name("pythonw.exe")
    exe = pyw if pyw.exists() else Path(sys.executable)
    return f'"{exe}" "{script}" "%1"'


def register_click_protocol() -> bool:
    """把 chaohua:// 注册成「唤起 app 窗口」的协议（幂等）。
    弹窗 launch 用 chaohua://events/<id>，点击时由系统拉起上面的命令，
    它再调本地 API 让运行中的窗口显示并跳页 —— 全程不开浏览器。"""
    import winreg
    cmd = _click_command()
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              rf"Software\Classes\{SCHEME}") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, f"URL:{APP_ID}")
            winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              rf"Software\Classes\{SCHEME}\shell\open\command") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)
        return True
    except Exception as e:
        global _LAST_ERROR
        _LAST_ERROR = f"协议注册失败：{e}"
        return False


def last_error() -> str:
    """最近一次桌面弹窗失败的原因（成功时为空串）。"""
    return _LAST_ERROR


def notify(title: str, body: str, channel: str = "desktop", launch: str = "") -> bool:
    ok = False
    if channel == "desktop":
        ok = _desktop(title, body, launch)
    elif channel == "sms":
        ok = _sms(title, body)
    db.run(
        "INSERT INTO push_log(title, body, channel, created_at) VALUES(?,?,?,?)",
        (title, body[:500], channel, db.now()),
    )
    return ok


def _desktop(title: str, body: str, launch: str = "") -> bool:
    global _LAST_ERROR
    _LAST_ERROR = ""
    if not _HAS_WINOTIFY:
        _LAST_ERROR = "未安装 winotify"
        return False
    if not shutil.which("powershell.exe"):
        _LAST_ERROR = "找不到 powershell.exe"
        return False
    try:
        # launch：整条通知被点击时打开（这里是带 hash 的本地页面，跳进对应事件）
        # icon：winotify 只认绝对路径的 .png —— 用品牌图标，和窗口/托盘一致。
        icon = str(ICON_PNG) if ICON_PNG.exists() else ""
        toast = Notification(app_id=APP_ID, title=title, msg=body, launch=launch, icon=icon)
        toast.set_audio(audio.Default, loop=False)
        toast.show()
        return True
    except Exception as e:
        _LAST_ERROR = f"{type(e).__name__}: {e}"
        return False


def _sms(title: str, body: str) -> bool:
    """短信推送 —— 预留。需第三方短信网关（阿里云/腾讯云/聚合短信等）。"""
    if db.get_setting("sms_enabled", "0") != "1":
        return False
    # TODO 阶段二：按 sms_provider / sms_config 调用短信网关
    return False
