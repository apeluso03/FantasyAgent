@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Virtual environment not found at .venv\ -- run setup first (see README.md).
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m fantasy_agent.gui_user
