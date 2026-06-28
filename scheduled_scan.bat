@echo off
REM ─── InelidaMarketScanner — Scan automatise planifie ─────────────────────────
REM Appele par le Planificateur de taches Windows (schtasks).
REM Lit le webhook Discord depuis le fichier .env (DISCORD_WEBHOOK_URL).
REM ─────────────────────────────────────────────────────────────────────────────

setlocal enabledelayedexpansion
cd /d "%~dp0"

REM ─── Session label ──────────────────────────────────────────────────────────
set SESSION=%1
if "%SESSION%"=="" set SESSION=auto

echo [%DATE% %TIME%] Demarrage scan %SESSION% >> logs\task_scheduler.log

REM ─── Detection du Python ────────────────────────────────────────────────────
if exist .venv\Scripts\python.exe (
    set PYTHON=.venv\Scripts\python.exe
) else (
    set PYTHON=python
)

REM ─── Extraction du webhook depuis .env ──────────────────────────────────────
if exist .env (
    for /f "tokens=1,* delims==" %%a in ('findstr /b "DISCORD_WEBHOOK_URL" .env') do set WEBHOOK=%%b
)

REM ─── Execution du pipeline complet ──────────────────────────────────────────
if not "!WEBHOOK!"=="" (
    %PYTHON% auto_scan_and_post.py --webhook "!WEBHOOK!" >> logs\task_scheduler.log 2>&1
) else (
    echo [WARN] DISCORD_WEBHOOK_URL non defini dans .env — scan sans Discord >> logs\task_scheduler.log
    %PYTHON% auto_scan_and_post.py >> logs\task_scheduler.log 2>&1
)

echo [%DATE% %TIME%] Termine %SESSION% >> logs\task_scheduler.log
endlocal
