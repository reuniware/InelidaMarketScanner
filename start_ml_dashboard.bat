@echo off
cd /d "%~dp0"

echo ==============================================
echo  InelidaMarketScan - ML Dashboard Launcher
echo ==============================================
echo.

REM ─── Cleanup: kill old processes + clear caches ──────────────────────────
python -c "
import subprocess, time, os, shutil

# 1) Kill ALL processes listening on port 8501 (Streamlit default)
print('  Killing old Streamlit processes...')
result = subprocess.run(['netstat', '-ano'], capture_output=True, timeout=10)
output = result.stdout.decode('utf-8', errors='replace')
for line in output.splitlines():
    if ':8501' in line and 'LISTENING' in line:
        parts = line.strip().split()
        if len(parts) >= 5:
            pid = parts[-1]
            try:
                subprocess.run(['taskkill.exe', '/f', '/pid', pid], capture_output=True, timeout=5)
                print('    Killed PID:', pid)
            except Exception as e:
                print('    Failed to kill PID', pid, ':', e)

# Fallback: streamlit.exe
subprocess.run(['taskkill', '/F', '/IM', 'streamlit.exe'], capture_output=True, timeout=5)

# 2) Clean ALL Python caches project-wide
print('  Cleaning Python caches...')
for root, dirs, files in os.walk('.'):
    if '.git' in root or '.venv' in root:
        continue
    for d in dirs[:]:
        if d == '__pycache__':
            shutil.rmtree(os.path.join(root, d), ignore_errors=True)
            print('    Cleaned:', os.path.join(root, d))
    for f in files:
        if f.endswith('.pyc'):
            try:
                os.remove(os.path.join(root, f))
            except:
                pass

# 3) Clear Streamlit user cache
print('  Clearing Streamlit cache...')
streamlit_cache = os.path.join(os.path.expanduser('~'), '.streamlit')
if os.path.isdir(streamlit_cache):
    for item in os.listdir(streamlit_cache):
        item_path = os.path.join(streamlit_cache, item)
        if os.path.isfile(item_path):
            try:
                os.remove(item_path)
            except:
                pass

print('  Cleanup done.')
time.sleep(1)
"

echo.
echo Starting ML Dashboard on http://localhost:8501
echo.

REM ─── Start fresh Streamlit with -B to avoid bytecode cache ───────────────
set PYTHONDONTWRITEBYTECODE=1
python -B -m streamlit run app_ml.py --server.headless true --browser.gatherUsageStats false

pause
