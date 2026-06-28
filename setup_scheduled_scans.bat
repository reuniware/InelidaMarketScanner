@echo off
REM ─── InelidaMarketScanner — Installation des scans automatises ──────────────
REM Cree 5 taches planifiees dans le Task Scheduler Windows.
REM Les heures sont en heure de Paris (CEST = UTC+2).
REM ────────────────────────────────────────────────────────────────────────────

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ==============================================
echo  Installation des scans automatises
echo ==============================================
echo.

REM ─── Verifier que scheduled_scan.bat existe ─────────────────────────────────
if not exist "scheduled_scan.bat" (
    echo [ERREUR] scheduled_scan.bat introuvable.
    pause
    exit /b 1
)

REM ─── Verifier que session_analysis.bat existe ──────────────────────────────
if not exist "session_analysis.bat" (
    echo [ERREUR] session_analysis.bat introuvable.
    pause
    exit /b 1
)

REM ─── Verifier que le repertoire logs existe ─────────────────────────────────
if not exist "logs" mkdir logs

REM ─── Chemins absolus vers les scripts ───────────────────────────────────────
for %%I in (scheduled_scan.bat) do set SCRIPT=%%~fI
for %%I in (session_analysis.bat) do set EOD_SCRIPT=%%~fI

echo Chemin scheduled_scan.bat  : %SCRIPT%
echo Chemin session_analysis.bat: %EOD_SCRIPT%
echo.
echo Les taches seront creees aux heures suivantes (Paris) :
echo  08:30 - Asian close / pre-London
echo  10:30 - London Open
echo  15:30 - NY Open
echo  18:30 - NY afternoon
echo  23:30 - End of day (scan + Discord)
echo  01:00 - EOD ICT/SMC complete analysis (23:00 UTC)
echo.

REM ─── Supprimer les anciennes taches si elles existent ──────────────────────
for %%S in (
    "InelidaScan-0830"
    "InelidaScan-1030"
    "InelidaScan-1530"
    "InelidaScan-1830"
    "InelidaScan-2330"
    "InelidaEODAnalysis"
) do (
    schtasks /query /tn %%~S >nul 2>&1
    if !errorlevel! equ 0 (
        schtasks /delete /tn %%~S /f >nul 2>&1
        echo  [SUPPRIME] %%~S
    )
)

echo.

REM ─── Creation des taches ────────────────────────────────────────────────────
REM Les heures sont en heure locale (Paris)
REM On utilise ONTASK pour ne pas ralentir l'ordi

set TASK_USER=%USERDOMAIN%\%USERNAME%

echo Creation des taches...

schtasks /create /tn "InelidaScan-0830" /tr "'%SCRIPT%' asian-close" /sc daily /st 08:30 /ru "%TASK_USER%" /f /it >nul 2>&1
if !errorlevel! equ 0 ( echo  [OK] InelidaScan-0830 - Asian close ) else ( echo  [FAIL] InelidaScan-0830 )

schtasks /create /tn "InelidaScan-1030" /tr "'%SCRIPT%' london-open" /sc daily /st 10:30 /ru "%TASK_USER%" /f /it >nul 2>&1
if !errorlevel! equ 0 ( echo  [OK] InelidaScan-1030 - London Open ) else ( echo  [FAIL] InelidaScan-1030 )

schtasks /create /tn "InelidaScan-1530" /tr "'%SCRIPT%' ny-open" /sc daily /st 15:30 /ru "%TASK_USER%" /f /it >nul 2>&1
if !errorlevel! equ 0 ( echo  [OK] InelidaScan-1530 - NY Open ) else ( echo  [FAIL] InelidaScan-1530 )

schtasks /create /tn "InelidaScan-1830" /tr "'%SCRIPT%' ny-afternoon" /sc daily /st 18:30 /ru "%TASK_USER%" /f /it >nul 2>&1
if !errorlevel! equ 0 ( echo  [OK] InelidaScan-1830 - NY afternoon ) else ( echo  [FAIL] InelidaScan-1830 )

schtasks /create /tn "InelidaScan-2330" /tr "'%SCRIPT%' eod" /sc daily /st 23:30 /ru "%TASK_USER%" /f /it >nul 2>&1
if !errorlevel! equ 0 ( echo  [OK] InelidaScan-2330 - End of day ) else ( echo  [FAIL] InelidaScan-2330 )

schtasks /create /tn "InelidaEODAnalysis" /tr "'%EOD_SCRIPT%'" /sc daily /st 01:00 /ru "%TASK_USER%" /f /it >nul 2>&1
if !errorlevel! equ 0 ( echo  [OK] InelidaEODAnalysis - EOD ICT/SMC complete (23:00 UTC) ) else ( echo  [FAIL] InelidaEODAnalysis )

echo.
echo ==============================================
echo  Verification des taches installees :
echo ==============================================
echo.
schtasks /query /tn "InelidaScan-*" /v /fo list 2>&1 | findstr /i "Tache\|Horaire\|Prochaine\|Script"

echo.
echo ==============================================
echo  Pour desactiver une tache :
echo    schtasks /change /tn InelidaScan-1030 /disable
echo.
echo  Pour supprimer toutes les taches :
echo    schtasks /delete /tn InelidaScan-0830 /f
echo    ...
echo ==============================================
echo.

REM ─── Configurer le webhook dans .env si non present ────────────────────────
findstr /b "DISCORD_WEBHOOK_URL" .env >nul 2>&1
if !errorlevel! neq 0 (
    echo.
    echo ==============================================
    echo  ATTENTION : DISCORD_WEBHOOK_URL non trouve
    echo  dans .env !
    echo.
    echo  Ajoute cette ligne dans .env :
    echo    DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
    echo ==============================================
)

pause
