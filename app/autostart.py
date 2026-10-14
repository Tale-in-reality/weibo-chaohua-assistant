"""开机自启：Windows 启动文件夹里的快捷方式。"""
import os
import subprocess
from pathlib import Path

from .config import APP_NAME, BASE_DIR

STARTUP_DIR = (Path(os.environ.get("APPDATA", ""))
               / "Microsoft/Windows/Start Menu/Programs/Startup")
LNK_PATH = STARTUP_DIR / f"{APP_NAME}.lnk"


def is_enabled() -> bool:
    return LNK_PATH.exists()


def enable() -> bool:
    try:
        _create_shortcut()
        return True
    except Exception:
        return False


def disable() -> bool:
    try:
        if LNK_PATH.exists():
            LNK_PATH.unlink()
        return True
    except Exception:
        return False


def set_enabled(on: bool) -> bool:
    return enable() if on else disable()


def _create_shortcut():
    """用 PowerShell 的 WScript.Shell 建快捷方式，免装 pywin32。"""
    STARTUP_DIR.mkdir(parents=True, exist_ok=True)
    target = BASE_DIR / "run.bat"
    ps = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{LNK_PATH}'); "
        f"$s.TargetPath = '{target}'; "
        f"$s.WorkingDirectory = '{BASE_DIR}'; "
        "$s.WindowStyle = 1; "   # 正常窗口（run.bat 用 start 拉起后自己退出，不会留控制台）
        "$s.Save()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        check=True, capture_output=True,
    )
