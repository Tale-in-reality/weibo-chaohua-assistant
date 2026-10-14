"""程序入口：uvicorn 服务 + pystray 托盘 + pywebview 窗口。

关键：关窗 = 最小化到托盘，调度器继续跑，
这样「开机自启 → 定时总结/推送」才成立。
"""
import argparse
import os
import threading
import time

import httpx
import uvicorn

from . import db, notify, scheduler, winref
from .api import app as fastapi_app
from .config import APP_NAME, DATA_DIR, HOST, PORT


def _log(msg: str):
    """写一行普通日志。pythonw 没有控制台 —— 这是排查退出原因的唯一线索。"""
    try:
        import time
        line = "[" + time.strftime("%Y-%m-%d %H:%M:%S") + "] " + str(msg) + "\n"
        with (DATA_DIR / "app.log").open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def _log_crash(where: str = ""):
    """pythonw 没有控制台，出错写到 data/app.log，方便排查。

    **追加**而不是覆盖：以前覆盖写，后面的小错误会把真正的死因盖掉。
    """
    try:
        import time
        import traceback
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with (DATA_DIR / "app.log").open("a", encoding="utf-8") as f:
            f.write(f"\n=== [{stamp}] {where} ===\n{traceback.format_exc()}")
    except Exception:
        pass


def _run_server():
    try:
        config = uvicorn.Config(fastapi_app, host=HOST, port=PORT, log_level="warning")
        uvicorn.Server(config).run()
    except Exception:
        # 端口被占（最常见）或其它原因 → 后端起不来。窗口仍会打开，
        # 但所有接口都会 "failed to fetch"，所以这里必须留下线索。
        _log_crash(f"uvicorn 服务线程（后端未启动，多为端口 {PORT} 被占）")
        raise


_MUTEX = None            # 持有引用，别让句柄被回收


def _acquire_single_instance() -> bool:
    """Windows 命名互斥体做单实例保护。已有实例在跑 → 返回 False。

    用互斥体而不是锁文件：进程崩溃时**系统会自动释放**，不会留下假锁。
    非 Windows / 调用失败时一律返回 True（不阻止启动）。
    """
    global _MUTEX
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.restype = wintypes.HANDLE
        k32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        _MUTEX = k32.CreateMutexW(None, False, "weibo_chaohua_assistant_singleton")
        if not _MUTEX:
            return True
        return ctypes.get_last_error() != 183      # ERROR_ALREADY_EXISTS
    except Exception:
        return True


def _focus_existing() -> bool:
    """把已经在跑的那个窗口唤到前台（它自己会 show + 跳页）。

    返回 True 只在「真的把窗口叫出来了」时为真 —— 后端在跑但**没有窗口**
    （僵尸实例）时返回 False，好让调用方给出正确的提示。
    """
    try:
        r = httpx.get(f"http://{HOST}:{PORT}/api/navigate", params={"page": "dashboard"},
                      headers={"X-Requested-With": "single-instance"}, timeout=3)
        return bool(r.status_code == 200 and (r.json() or {}).get("ok"))
    except Exception:
        return False


def _no_window_watchdog(seconds: int = 60):
    """GUI 模式的安全网：这么久还没窗口就自己退出。

    没有它的话，「后端起得来但窗口没建出来」的进程会一直抱着单实例锁，
    之后每次双击都只弹「已经在运行」，而用户根本找不到那个窗口 ——
    看起来就是「app 打不开了」。宁可自己退出，也不能占着锁不放。
    """
    def _run():
        time.sleep(seconds)
        if winref.WINDOW is None:
            _log_crash(f"GUI 模式启动 {seconds} 秒后仍没有窗口 —— 自行退出以释放单实例锁")
            import os
            os._exit(1)
    threading.Thread(target=_run, daemon=True).start()


def _message(text: str):
    """没有控制台也能弹的原生提示框（pythonw 下可用）。"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, APP_NAME, 0x40)
    except Exception:
        try:
            print(text)
        except Exception:
            pass


def _ensure_std_streams():
    """pythonw（无控制台）下 sys.stdout/stderr 是 None。
    uvicorn 构造日志格式器时会调 sys.stdout.isatty() → 崩 → 服务起不来。
    这里兜底成空设备。**必须在 uvicorn.Config 之前调用**。"""
    import os
    import sys
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def _wait_server(timeout: int = 20) -> bool:
    for _ in range(timeout * 10):
        try:
            httpx.get(f"http://{HOST}:{PORT}/api/health", timeout=1)
            return True
        except Exception:
            time.sleep(0.1)
    return False


def _icon_image():
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), fill=(255, 92, 138, 255))
    d.ellipse((20, 20, 44, 44), fill=(255, 255, 255, 255))
    return img


def _run_gui():
    import pystray
    import webview

    window = webview.create_window(
        APP_NAME, f"http://{HOST}:{PORT}",
        width=1200, height=820, min_size=(960, 640),
    )
    _log("窗口已创建")
    winref.WINDOW = window          # 供 /api/navigate 唤起窗口 + 跳页
    notify.register_click_protocol()   # 弹窗点击 → chaohua:// → 唤起本窗口

    def on_closing():
        """点 × 的行为，按设置 close_action 决定：ask 询问 / minimize / quit。

        例外：**正在跑长任务**（写文案 / 识图 / 生成风格档案）时，不管设置成什么
        都先问一下 —— 否则用户以为卡死了顺手一关，等了半天的结果就没了。
        """
        act = db.get_setting("close_action", "ask")
        _log(f"on_closing 触发：close_action={act} busy={winref.BUSY}")
        if winref.BUSY:
            act = "ask"
        if act == "minimize":
            window.hide()
            return False                      # 取消关闭 → 藏在托盘
        if act == "quit":
            return True                       # 允许关闭 → webview 结束 → 进程退出
        # ask：取消关闭，让页面弹「最小化 / 直接退出」选择框
        def _ask():
            try:
                window.evaluate_js("showCloseDialog()")
            except Exception:
                _log_crash("弹出关闭选择框（evaluate_js）")
        threading.Thread(target=_ask, daemon=True).start()
        return False

    window.events.closing += on_closing

    def quit_app(icon=None, item=None):
        _log("quit_app 被调用（托盘退出 / API 退出）")
        try:
            icon.stop()
        except Exception:
            pass
        try:
            window.destroy()
        except Exception:
            pass
        # 兜底：万一 destroy 没让 webview.start() 返回，2 秒后强制退出进程
        def _force():
            time.sleep(2)
            import os
            os._exit(0)
        threading.Thread(target=_force, daemon=True).start()

    winref.QUIT = quit_app          # 界面「退出程序」按钮 → /api/quit → 这里

    menu = pystray.Menu(
        pystray.MenuItem("显示窗口", lambda icon, item: window.show(), default=True),
        pystray.MenuItem("立即推送", lambda icon, item: scheduler.trigger("push")),
        pystray.MenuItem("退出", quit_app),
    )
    icon = pystray.Icon("weibochassistant", _icon_image(), APP_NAME, menu)
    threading.Thread(target=icon.run, daemon=True).start()

    webview.start()  # 阻塞直到窗口销毁
    _log("webview.start() 返回了 —— 窗口已销毁，即将退出进程")
    try:
        icon.stop()
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--server-only", action="store_true",
                        help="只启动本地服务，不开窗口（调试用）")
    args = parser.parse_args()

    _log(f"启动：server_only={args.server_only} pid={os.getpid()}")
    _ensure_std_streams()      # pythonw 无控制台：先补上 stdout/stderr，否则 uvicorn 崩

    # 单实例保护：第二个实例会因端口被占而后端起不来（窗口却照开，全是 failed to fetch），
    # 所以这里直接拦住，并把已有窗口唤到前台。
    if not _acquire_single_instance():
        if _focus_existing():
            # 已经把已有窗口叫到前台了 —— 静默退出，不弹框（弹了还得点确定，更烦）
            if args.server_only:
                print("[已经在运行] 已把已有窗口切到前台")
            return
        # 叫不出窗口：多半是「没有窗口的僵尸实例」占着锁。
        # 它会在启动 60 秒后自行退出（见 _no_window_watchdog），所以等一下再试就行。
        msg = ("检测到上一次的进程还占着（但它没有窗口）。\n\n"
               "它会在 60 秒内自行退出 —— 请稍等片刻再双击一次。\n\n"
               "如果急着用：打开任务管理器，结束 pythonw.exe，然后再启动。")
        if args.server_only:
            print("[被占用] " + msg.replace("\n\n", " "))
        else:
            _message(msg)
        return

    _log("已取得单实例锁")
    db.init_db()
    scheduler.start()

    threading.Thread(target=_run_server, daemon=True).start()
    if not _wait_server():
        # 后端没起来（最典型是端口被别的程序占）——别开一个空窗口
        _log_crash(f"后端 20 秒内未就绪（端口 {PORT} 可能被占）")
        if args.server_only:
            print(f"[启动失败] 后端未就绪，端口 {PORT} 可能被占。详见 data/app.log")
            return
        _message(f"后端启动失败。\n\n常见原因：端口 {PORT} 被别的程序占用。\n"
                 f"详情见 data\\app.log")
        return

    _log("后端已就绪")
    if args.server_only:
        print(f"{APP_NAME} 服务已启动： http://{HOST}:{PORT}")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            return
    else:
        _no_window_watchdog()      # 起不来窗口就自我了断，别占着单实例锁
        _run_gui()


if __name__ == "__main__":
    try:
        main()
        _log("main() 正常返回 —— 进程即将结束")
    except Exception:
        _log_crash()          # pythonw 无控制台：错误落到 data/app.log
        raise
