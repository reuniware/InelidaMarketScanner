@echo off
REM ─── InelidaMarketScanner — Analyse ICT/SMC de fin de journee ─────────────────
REM Appele par le Planificateur de taches Windows (schtasks) a 01:00 Paris (23:00 UTC).
REM Lance l'analyse complete des sessions Asian/London/NY de TOUS les symboles MT5
REM et genere un rapport PDF + DOCX dans reports/
REM ─────────────────────────────────────────────────────────────────────────────

setlocal enabledelayedexpansion
cd /d "%~dp0"

if not exist "logs" mkdir logs

echo [%DATE% %TIME%] Demarrage analyse ICT/SMC fin de journee >> logs\task_scheduler.log

REM ─── Detection du Python ────────────────────────────────────────────────────
if exist .venv\Scripts\python.exe (
    set PYTHON=.venv\Scripts\python.exe
) else (
    set PYTHON=python
)

REM ─── Execution de l'analyse complete ─────────────────────────────────────────
REM Options par defaut : --limit 200, toutes les categories (Forex, Indices, Metaux, Crypto, Autre)
%PYTHON% full_session_analysis.py >> logs\task_scheduler.log 2>&1

echo [%DATE% %TIME%] Termine analyse ICT/SMC fin de journee >> logs\task_scheduler.log
endlocal
