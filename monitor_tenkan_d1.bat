@echo off
cd /d "%~dp0"
echo.
echo ============================================================
echo   Monitor Tenkan D1 - GBPUSD
echo   Surveillance en continu - Ctrl+C pour quitter
echo ============================================================
echo.
python monitor_tenkan_d1.py
pause
