"""桌面弹窗点击的回调入口 —— 独立进程运行，只依赖标准库。

注册的 `chaohua://` 协议会以 `pythonw toast_click.py "chaohua://events/5"` 拉起本脚本；
它把 URI 转成本地 API 调用，让**运行中的 app 窗口**被唤到前台并跳到那条事件。

见 notify.register_click_protocol()（注册协议）。app 没在跑时静默失败——不开网页。
"""
import sys
import urllib.parse
import urllib.request

try:
    from config import HOST, PORT          # app/ 在 sys.path 上时可用
    HP = f"{HOST}:{PORT}"
except Exception:
    HP = "127.0.0.1:8756"


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    # chaohua://events/5  →  page=events, event=5
    parts = [p for p in arg.split("://", 1)[-1].split("/") if p]
    page = parts[0] if parts else "events"
    event = parts[1] if len(parts) > 1 else ""
    url = (f"http://{HP}/api/navigate?page={urllib.parse.quote(page)}"
           f"&event={urllib.parse.quote(event)}")
    try:
        # 必须带 X-Requested-With（后端防 CSRF 的凭据）
        req = urllib.request.Request(url, headers={"X-Requested-With": "toast"})
        urllib.request.urlopen(req, timeout=5).read()
    except Exception:
        pass          # app 没在跑：什么都不做（不退回去开浏览器）


if __name__ == "__main__":
    main()
