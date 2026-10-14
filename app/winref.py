"""运行中的 pywebview 窗口引用 —— 供 API 层「唤起窗口并跳页」。

只有 GUI 模式（双击 run.bat 的 pywebview 窗口）才会设置 WINDOW；
`--server-only`（调试壳）时为 None，此时 /api/navigate 返回 has_window=False，
**不会退回去开网页**。
"""
from . import config

WINDOW = None
QUIT = None        # GUI 模式设成「停托盘 + 关窗口」的可调用对象
BUSY = 0           # 正在跑的长任务计数（>0 时关窗要先问一下，别把等待白费）


def quit_app() -> bool:
    """退出整个程序（× 的选择、托盘「退出」都走这里）。"""
    if QUIT is None:
        return False
    try:
        QUIT()
        return True
    except Exception:
        return False


def minimize() -> bool:
    """最小化到托盘（窗口隐藏，调度器继续跑）。"""
    w = WINDOW
    if w is None:
        return False
    try:
        w.hide()
        return True
    except Exception:
        return False


def focus(page: str = "dashboard", event: str = "") -> bool:
    """把窗口唤到前台并跳到某页（可带事件 id 深链）。成功返回 True。"""
    w = WINDOW
    if w is None:
        return False
    hash_ = f"#{page}" + (f"/{event}" if event else "")
    try:
        w.show()
    except Exception:
        pass
    # 重新载入带 hash 的地址 → 前端启动时解析（最稳）
    # 注意用 config.get_port() 而不是导入时的快照：端口是运行时选定的。
    try:
        w.load_url(f"http://{config.HOST}:{config.get_port()}/{hash_}")
        return True
    except Exception:
        pass
    # 退而求其次：不动页面，只改 hash（触发前端 hashchange）
    try:
        w.evaluate_js(f"location.hash='{hash_}'")
        return True
    except Exception:
        return False
