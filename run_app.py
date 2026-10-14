"""打包入口（PyInstaller 用）。

开发态仍用 `python -m app.main`；打包时包内的模块是**相对导入**，不能直接拿
`app/main.py` 当脚本喂给 PyInstaller，所以这里用一层极薄的壳把包加载起来。

`app.main.main()` 内部已处理：无控制台（pythonw/打包）下的 stdout/stderr 兜底、
单实例、挑选空闲端口、起 uvicorn、开窗口与托盘。
"""
from app.main import main

if __name__ == "__main__":
    main()
