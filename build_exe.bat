@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pyinstaller.exe" (
    echo Build tools not installed. Run: .venv\Scripts\python -m pip install -e ".[build]"
    pause
    exit /b 1
)
".venv\Scripts\pyinstaller.exe" FantasyAgent.spec
echo.
echo Build complete: dist\FantasyAgent\FantasyAgent.exe
pause
