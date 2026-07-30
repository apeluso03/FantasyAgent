@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pyinstaller.exe" (
    echo Build tools not installed. Run: .venv\Scripts\python -m pip install -e ".[build]"
    pause
    exit /b 1
)
".venv\Scripts\pyinstaller.exe" FantasyAgent.spec

rem PyInstaller deletes and recreates dist\FantasyAgent\ on every build, which
rem wipes any .env / cached data left there from a previous run -- restore
rem them from the project root so the exe works immediately after a rebuild.
if exist ".env" (
    copy /y ".env" "dist\FantasyAgent\.env" >nul
    echo Copied .env into dist\FantasyAgent\
)
if exist "data\fantasy_agent.db" (
    if not exist "dist\FantasyAgent\data" mkdir "dist\FantasyAgent\data"
    copy /y "data\fantasy_agent.db" "dist\FantasyAgent\data\fantasy_agent.db" >nul
    echo Copied cached league data into dist\FantasyAgent\data\
)

echo.
echo Build complete: dist\FantasyAgent\FantasyAgent.exe
pause
