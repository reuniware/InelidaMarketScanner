@echo off
REM scheduled_scan_diamond.bat — Lancement automatique du scan Diamond + Asian + Discord
REM Usage: double-cliquer ou planifier dans le Task Scheduler Windows
REM
REM Pre-requis:
REM   - MetaTrader 5 ouvert et connecte
REM   - Fichier .env avec DISCORD_WEBHOOK_URL (optionnel, pour notifications Discord)
REM   - Python 3.10+ avec dependances installees (MetaTrader5)

cd /d "%~dp0"

echo.
echo ============================================
echo   InelidaMarketScan — Scheduled Diamond Scan
echo   %DATE% %TIME%
echo ============================================
echo.

REM Lancement du scan (avec envoi Discord si webhook configure)
python scheduled_scan_diamond.py %*

echo.
echo Scan termine.
exit /b %ERRORLEVEL%
