# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 —— 文件夹版，产物 `dist/app/app.exe`。

构建：  pyinstaller app.spec --noconfirm      （或双击 build.bat）
分发：  把整个 `dist/app` 文件夹拷给别人，双击里面的 `app.exe` 即用（无需装 Python）。

要点：
- 入口用仓库根的 run_app.py（包内是相对导入，不能直接拿 app/main.py 当脚本）。
- web / assets / models 作为数据文件打进包；**data/ 不打**（运行时落在 exe 旁边，便携）。
- webview 必须带 `WebView2Loader.dll` 与 `js/*.js`；uvicorn 需要子模块（靠字符串动态导入）。
- **jieba 只收数据文件**（dict.txt / finalseg），**不要 collect_all**：
  jieba 自带一个可选的 `lac_small` 模块会 `import paddle`，一旦整包收集就会把
  paddle → cv2 → numpy → Intel MKL 整条链拖进来（实测让产物从 ~150MB 涨到 1.8GB）。
- 其余「环境里恰好装着」的重量级包（见 _DROP）一律排除 + 产物过滤，
  保证在别人机器上构建也得到同样精简的结果。
"""
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

datas = [
    ('web', 'web'),
    ('assets', 'assets'),
    ('models', 'models'),
]
binaries = []
hiddenimports = ['jieba']

# jieba：只要数据（分词词典 dict.txt + finalseg 概率表），子模块交给静态分析即可。
# 排掉用不到的数据：lac_small（10MB 模型，且它会 import paddle）、analyse（idf 5.9MB）、
# posseg（.p 5MB）—— `import jieba` 实测不会带出这些子模块。
datas += collect_data_files('jieba', excludes=['lac_small/**', 'analyse/**', 'posseg/**'])

# 这几个包有运行期二进制/数据（dll / js / powershell 脚本），整包收集最稳。
for _pkg in ('webview', 'winotify', 'clr_loader', 'pythonnet'):
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

# 与本体无关、但在开发机上常常装着的重量级包（Anaconda 里尤其多）。
# 已逐个核实：本体只依赖 requirements.txt 里那 9 个包，且这 9 个都不会间接带出下面任何一个。
_DROP = (
    # 科学计算 / 视觉 / 训练框架
    'paddle', 'cv2', 'llvmlite', 'numba', 'datashader', 'skimage', 'sklearn',
    'scipy', 'numpy', 'mkl', 'pandas', 'plotly', 'torch', 'tensorflow',
    'sympy', 'matplotlib', 'cython',
    # 浏览器自动化
    'patchright', 'playwright', 'scrapling',
    # 交互式/IPython 及其依赖链
    'ipython', 'ipykernel', 'jedi', 'parso', 'traitlets', 'tornado', 'zmq',
    'pyzmq', 'jupyter', 'jupyter_client', 'nbformat', 'matplotlib_inline',
    'pexpect', 'prompt_toolkit', 'stack_data', 'asttokens', 'pure_eval',
    'executing', 'ptyprocess',
    # 文档 / 类型检查 / 测试
    'sphinx', 'alabaster', 'numpydoc', 'docutils', 'snowballstemmer',
    'mypy', 'mypy_extensions', 'pytest', '_pytest', 'nose', 'coverage',
    # 网络解析 / 本地化
    'bs4', 'beautifulsoup4', 'lxml', 'babel',
    # GUI（我们只用 pywebview+EdgeChromium 与 win32 托盘）
    'tkinter', 'Tkinter', '_tkinter', 'tcl', 'PyQt5', 'PyQt6',
    'PySide2', 'PySide6', 'wx',
)


def _keep(name: str) -> bool:
    n = name.lower().replace('\\', '/').lstrip('./')
    return not any(n == d or n.startswith(d + '/') or n.startswith(d + '.') for d in _DROP)


a = Analysis(
    ['run_app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=list(_DROP),
    noarchive=False,
)

# jieba 里用不到的 3 块数据：lac_small（10MB 模型，还会 import paddle）、
# analyse（idf 5.9MB）、posseg（.p 5MB）。`import jieba` 实测不会带出这些子模块，
# 而 collect_data_files(excludes=...) 在本机 PyInstaller 版本上不生效 —— 所以在产物层滤。
_DROP_PATHS = _DROP + ('jieba/lac_small', 'jieba/analyse', 'jieba/posseg')


def _keep(name: str) -> bool:
    n = name.lower().replace('\\', '/').lstrip('./')
    return not any(n == d or n.startswith(d + '/') or n.startswith(d + '.') for d in _DROP_PATHS)


# 兜底：排除项若由某个第三方 hook 直接塞进 datas/binaries（excludes 管不到），这里再滤一遍。
a.datas = [x for x in a.datas if _keep(x[0])]
a.binaries = [x for x in a.binaries if _keep(x[0])]

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
