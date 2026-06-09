@echo off
REM Claude Code Observer - Build Script
REM Builds the observer into a single .exe using PyInstaller

setlocal

echo ========================================
echo  Claude Code Observer - Build
echo ========================================
echo.

REM Check Python
where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python not found. Install Python 3.7+ and add to PATH.
    exit /b 1
)

REM Install dependencies
echo [1/3] Installing dependencies...
pip install pywebview pyinstaller --quiet
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Failed to install dependencies.
    exit /b 1
)

REM Build
echo [2/3] Building executable...
pyinstaller --onefile --windowed --name ClaudeObserver --clean ^
    --hidden-import=webview ^
    --hidden-import=webview.platforms.edgechromium ^
    --hidden-import=webview.platforms.winforms ^
    --hidden-import=webview.platforms.mshtml ^
    observer.py

if %ERRORLEVEL% neq 0 (
    echo [ERROR] Build failed.
    exit /b 1
)

echo [3/3] Done!
echo.
echo Output: dist\ClaudeObserver.exe
echo.
echo Remember to copy the hooks\ folder alongside the exe.
