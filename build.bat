@echo off
cd /d "%~dp0"

echo === [1/4] 安装依赖（运行 + 打包）===
python -m pip install -r requirements.txt -r requirements-dev.txt || goto :fail

echo.
echo === [2/4] 准备图标 ===
if not exist assets\icon.ico python tools\make_icon.py

echo.
echo === [3/4] 清理旧产物 ===
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo.
echo === [4/4] 打包（文件夹版）===
python -m PyInstaller app.spec --noconfirm || goto :fail

echo.
echo ============================================================
echo  完成： dist\app\app.exe
echo  把整个 dist\app 文件夹拷给别人，双击 app.exe 即用。
echo  （首次打开会检测 Ollama：没装会引导一键下载）
echo ============================================================
pause
exit /b 0

:fail
echo.
echo [FAILED] 打包失败，请看上面的错误信息。
pause
exit /b 1
