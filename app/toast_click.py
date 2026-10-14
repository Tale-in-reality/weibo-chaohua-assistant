"""桌面弹窗点击的回调入口 —— 把 `chaohua://events/5` 转成本地导航请求。

注册的 `chaohua://` 协议会拉起本逻辑：
  - 开发态：`pythonw toast_click.py "chaohua://events/5"`（见 notify.register_click_protocol）
  - 打包态：`app.exe --toast-click "chaohua://events/5"`（由 main.py 转发到这里）
它让**运行中的 app 窗口**被唤到前台并跳到那条事件；app 没在跑时静默失败——不开网页。

端口是运行时选定的，所以这里读 `data/port`（`config.read_port_file()`），读不到回退默认端口。
"""
import sys

try:                    # 包内导入（main.py --toast-click 走这条）
    from . import config as _config
except Exception:       # 作为独立脚本运行（app/ 在 sys.path 上）
    _config = None


def _port() -> int:
    if _config is not None:
        try:
            return _config.read_port_file()
        except Exception:
            pass
    try:
        from config import read_port_file      # 脚本方式
        return read_port_file()
    except Exception:
        return 8756


def handle(uri: str) -> None:
    """把 chaohua://page/event 转成一次 /api/navigate 调用。失败静默（app 没在跑）。"""
    import urllib.parse
    import urllib.request

    parts = [p for p in (uri or "").split("://", 1)[-1].split("/") if p]
    page = parts[0] if parts else "events"
    event = parts[1] if len(parts) > 1 else ""
    url = (f"http://127.0.0.1:{_port()}/api/navigate?page={urllib.parse.quote(page)}"
           f"&event={urllib.parse.quote(event)}")
    try:
        # 必须带 X-Requested-With（后端防 CSRF 的凭据）
        req = urllib.request.Request(url, headers={"X-Requested-With": "toast"})
        urllib.request.urlopen(req, timeout=5).read()
    except Exception:
        pass          # app 没在跑：什么都不做（不退回去开浏览器）


def main() -> None:
    handle(sys.argv[1] if len(sys.argv) > 1 else "")


if __name__ == "__main__":
    main()
