# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 —— 文件夹版，产物 `dist/app/app.exe`。

构建：  pyinstaller app.spec --noconfirm      （或双击 build.bat）
分发：  把整个 `dist/app` 文件夹拷给别人，双击里面的 `app.exe` 即用（无需装 Python）。

要点：
- 入口用仓库根的 run_app.py（包内是相对导入，不能直接拿 app/main.py 当脚本）。
- web / assets / models 作为数据文件打进包；**data/ 不打**（运行时落在 exe 旁边，便携）。
- webview 必须带 `WebView2Loader.dll` 与 `js/*.js`；jieba 必须带分词词典；
  uvicorn 需要子模块（它靠字符串动态导入）。漏了就运行时报错。
"""
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [
    ('web', 'web'),
    ('assets', 'assets'),
    ('models', 'models'),
]
binaries = []
hiddenimports = []

# 这几个包有运行期数据/二进制（dll / js / 词典 / powershell 脚本），整包收集最稳。
for _pkg in ('webview', 'jieba', 'winotify', 'clr_loader', 'pythonnet'):
    try:
        _d, _b, _h = collect_all(_pkg)
        datas += _d
        binaries += _b
        hiddenimports += _h
    except Exception:
        pass

hiddenimports += collect_submodules('uvicorn')
hiddenimports += [
    'uvicorn.logging', 'uvicorn.loops.auto', 'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan.on',
    'bottle',
]

a = Analysis(
    ['run_app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='app',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                       # 无控制台黑框
    disable_windowed_traceback=False,
    icon='assets/icon.ico',              # 资源管理器 / 任务栏 / 快捷方式图标
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='app',
)
