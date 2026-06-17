@echo off
REM ─── InelidaMarketScan — lancement du mode watch sur Windows ───────────────
setlocal
cd /d "%~dp0"

if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
) else (
    echo [INFO] Pas de .venv detecte, on utilise le Python systeme.
)

python main.py watch %*
endlocal
