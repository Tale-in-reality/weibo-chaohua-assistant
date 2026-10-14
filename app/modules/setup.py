"""首启环境检测与一键安装：Ollama 运行时 / 模型权重 / WebView2。

打包成 exe 后，Python 依赖都在包里，用户零安装 —— **但本地模型运行时（Ollama）和
模型权重（GB 级）没法塞进 exe**。所以首次打开时检测缺件，由前端向导调这里的接口
一键下载安装；进度写模块级全局，前端轮询 `status()`。

不阻塞主流程：所有安装/下载都跑在后台线程，失败也只回报中文原因，不影响 app 使用
（写文案之外的页面照常）。
"""
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import httpx

from .. import db
from ..config import DATA_DIR

OLLAMA_DEFAULT_URL = "http://127.0.0.1:11434"
OLLAMA_DOWNLOAD = "https://ollama.com/download/OllamaSetup.exe"
# 官方源在国内可能很慢/不可达；给一个 GitHub 加速镜像备选（若失效可不选）。
OLLAMA_MIRRORS = [
    ("官方（ollama.com）", OLLAMA_DOWNLOAD),
    ("镜像加速（gh-proxy）", "https://gh-proxy.com/https://github.com/ollama/ollama/releases/latest/download/OllamaSetup.exe"),
]
DEFAULT_MODEL = "qwen2.5:7b-instruct"
ALT_MODELS = ["qwen2.5:3b", "qwen2.5:1.5b"]

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# ── 进度状态（单任务）────────────────────────────────────────────
_STATE = {
    "task": None,       # None | "install_ollama" | "pull_model"
    "phase": "",        # 人话的阶段名
    "percent": 0.0,
    "message": "",
    "done": False,
    "error": "",
    "cancel": False,
}
_LOCK = threading.Lock()
_PROC = {"p": None}     # 正在跑的 ollama pull 进程，便于取消


def _set(**kw):
    with _LOCK:
        _STATE.update(kw)


def _reset(task):
    with _LOCK:
        _STATE.update(task=task, phase="", percent=0.0, message="",
                      done=False, error="", cancel=False)
    _PROC["p"] = None


def _busy() -> bool:
    with _LOCK:
        return _STATE["task"] is not None and not _STATE["done"]


# ── 检测 ────────────────────────────────────────────────────────

def _ollama_url() -> str:
    return (db.get_setting("ollama_url", OLLAMA_DEFAULT_URL) or OLLAMA_DEFAULT_URL).rstrip("/")


def _want_model() -> str:
    return (db.get_setting("model", DEFAULT_MODEL) or DEFAULT_MODEL).strip()


def ollama_exe() -> str:
    """找到 ollama 可执行文件（PATH → LOCALAPPDATA 安装目录 → Program Files）。找不到返回空。"""
    p = shutil.which("ollama")
    if p:
        return p
    for cand in (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Ollama" / "ollama.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Ollama" / "ollama.exe",
    ):
        try:
            if cand.exists():
                return str(cand)
        except Exception:
            pass
    return ""


def _ollama_running() -> tuple:
    """(是否在跑, 已装模型名列表)。"""
    try:
        r = httpx.get(_ollama_url() + "/api/tags", timeout=2)
        r.raise_for_status()
        models = [m.get("name", "") for m in (r.json().get("models") or []) if isinstance(m, dict)]
        return True, [m for m in models if m]
    except Exception:
        return False, []


def _has_model(models: list, want: str) -> bool:
    want = (want or "").strip().lower()
    if not want:
        return False
    wb = want.split(":")[0]
    return any(m.lower() == want or m.lower().split(":")[0] == wb for m in models)


_WEBVIEW2_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def webview2_present() -> bool:
    """WebView2 运行时是否已装（Win10/11 一般随 Edge 预装）。"""
    try:
        import winreg
        key = rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{_WEBVIEW2_GUID}"
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(root, key) as k:
                    winreg.QueryValueEx(k, "pv")
                    return True
            except OSError:
                pass
    except Exception:
        pass
    for base_var in ("ProgramFiles(x86)", "ProgramFiles"):
        base = os.environ.get(base_var, "")
        if base:
            try:
                if any((Path(base) / "Microsoft" / "EdgeWebView" / "Application").glob("*")):
                    return True
            except Exception:
                pass
    return False


def check() -> dict:
    """一眼看清环境缺什么。前端据此决定是否弹首启向导。"""
    inst = bool(ollama_exe())
    running, models = _ollama_running()
    want = _want_model()
    present = _has_model(models, want)
    return {
        "ollama_installed": inst,
        "ollama_running": running,
        "ollama_url": _ollama_url(),
        "models": models,
        "model": want,
        "model_present": present,
        "webview2": webview2_present(),
        "needs_setup": not (running and present),
        "default_model": DEFAULT_MODEL,
        "alt_models": ALT_MODELS,
        "ollama_mirrors": [m[0] for m in OLLAMA_MIRRORS],
        "wizard_done": db.get_setting("setup_wizard_done", "0") == "1",
    }


def status() -> dict:
    with _LOCK:
        return dict(_STATE)


def cancel() -> dict:
    _set(cancel=True, message="正在取消…")
    p = _PROC.get("p")
    if p is not None:
        try:
            p.terminate()
        except Exception:
            pass
    return {"ok": True}


# ── 下载 / 安装 Ollama ──────────────────────────────────────────

def _download(url: str, dst: Path):
    tmp = dst.with_suffix(dst.suffix + ".part")
    with httpx.stream("GET", url, follow_redirects=True,
                      timeout=httpx.Timeout(30.0, read=120.0)) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0)
        got = 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_bytes(1024 * 256):
                if _STATE["cancel"]:
                    break
                f.write(chunk)
                got += len(chunk)
                mb = got // 1048576
                msg = f"{mb} MB / {total // 1048576} MB" if total else f"{mb} MB"
                _set(percent=round(got * 100 / total, 1) if total else 0, message=msg)
    tmp.replace(dst)


def install_ollama(mirror: str = "") -> dict:
    if _busy():
        return {"ok": False, "error": "已有任务在跑，请稍候"}
    url = OLLAMA_DOWNLOAD
    for name, u in OLLAMA_MIRRORS:
        if mirror and mirror.strip() == name:
            url = u
            break
    threading.Thread(target=_install_ollama_worker, args=(url,), daemon=True).start()
    return {"ok": True, "started": True}


def _install_ollama_worker(url: str):
    _reset("install_ollama")
    try:
        dst = DATA_DIR / "OllamaSetup.exe"
        _set(phase="下载 Ollama 安装包", percent=0, message=url)
        _download(url, dst)
        if _STATE["cancel"]:
            _set(done=True, phase="已取消")
            return

        _set(phase="安装 Ollama", percent=100, message="静默安装中，如有 UAC 弹窗请点『是』")
        # Ollama 的 Windows 安装包是 Inno Setup，支持 /SILENT /NORESTART。
        subprocess.run([str(dst), "/SILENT", "/NORESTART"], check=False)
        if _STATE["cancel"]:
            _set(done=True, phase="已取消")
            return

        _set(phase="等待 Ollama 就绪", percent=100, message="服务启动中，首次可能要几十秒…")
        for _ in range(120):        # 最多等 2 分钟
            if _STATE["cancel"]:
                _set(done=True, phase="已取消")
                return
            if _ollama_running()[0]:
                _set(done=True, phase="完成", message="Ollama 已就绪")
                return
            time.sleep(1)
        _set(done=True, phase="完成",
             message="安装包已下载并运行，但服务还没起来。若没自动装好，"
                     "请手动双击运行：" + str(dst))
    except Exception as e:
        _set(done=True, error=f"安装 Ollama 失败：{e}", phase="出错")


# ── 拉取模型 ────────────────────────────────────────────────────

_PCT = re.compile(r"(\d{1,3})%")


def pull_model(name: str = "") -> dict:
    name = (name or _want_model()).strip()
    if not name:
        return {"ok": False, "error": "没填模型名"}
    if _busy():
        return {"ok": False, "error": "已有任务在跑，请稍候"}
    threading.Thread(target=_pull_worker, args=(name,), daemon=True).start()
    return {"ok": True, "started": True, "model": name}


def _pull_worker(name: str):
    _reset("pull_model")
    exe = ollama_exe() or "ollama"
    _set(phase=f"拉取模型 {name}", percent=0, message="连接中…")
    try:
        proc = subprocess.Popen(
            [exe, "pull", name], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=_NO_WINDOW,
        )
    except FileNotFoundError:
        _set(done=True, error="找不到 ollama 命令 —— 请先安装 Ollama 并重启本程序",
             phase="出错")
        return
    except Exception as e:
        _set(done=True, error=f"启动 ollama pull 失败：{e}", phase="出错")
        return

    _PROC["p"] = proc
    try:
        for line in proc.stdout:               # type: ignore[union-attr]
            if _STATE["cancel"]:
                proc.terminate()
                _set(done=True, phase="已取消")
                return
            line = line.strip()
            if not line:
                continue
            m = _PCT.search(line)
            if m:
                _set(percent=min(100.0, float(m.group(1))))
            _set(message=line[-140:])
        proc.wait()
        if proc.returncode == 0:
            db.set_setting("model", name)      # 拉成功就把设置里的模型对上
            _set(done=True, phase="完成", percent=100, message=f"{name} 已就绪")
        else:
            _set(done=True, error=f"ollama pull 退出码 {proc.returncode}",
                 phase="出错")
    except Exception as e:
        _set(done=True, error=f"拉取中断：{e}", phase="出错")
    finally:
        _PROC["p"] = None
