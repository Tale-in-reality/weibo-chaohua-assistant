@echo off
cd /d "%~dp0"

rem --- launch with pythonw (no console window); Anaconda path first ---
set "PYW=%USERPROFILE%\anaconda3\pythonw.exe"
if exist "%PYW%" goto run

where pythonw >nul 2>nul
if errorlevel 1 goto fail
set "PYW=pythonw"

:run
start "" "%PYW%" -m app.main
exit /b 0

:fail
echo [FAILED] pythonw.exe not found.
echo   Expected: %USERPROFILE%\anaconda3\pythonw.exe
echo   Edit PYW in this file, or install Anaconda.
echo.
echo If the app starts but shows nothing, check data\app.log
pause
exit /b 1
