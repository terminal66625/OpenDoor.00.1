@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem 优先使用随文件夹携带的便携主程序（搬到别的电脑也能用）
if exist "%~dp0大肥鱼.exe" (
    start "" "%~dp0大肥鱼.exe"
    exit /b
)

rem 没有主程序则用本机 Python 源码运行
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "%~dp0run.py"
) else (
    start "" python "%~dp0run.py"
)
