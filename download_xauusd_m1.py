"""
Telecharge l'historique complet XAUUSD M3 depuis MT5 (01/01/2026 -> 26/06/2026).
Sauvegarde en JSON pour analyse ulterieure.

M3 (~84 960 bougies sur 177 jours) : ~6 chunks de 30 jours.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

# Force UTF-8 pour eviter les UnicodeEncodeError sur Windows cp1252
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import MetaTrader5 as mt5

# --- Configuration -----------------------------------------------------------
SYMBOL = "XAUUSD"
TIMEFRAME = mt5.TIMEFRAME_M3  # 3 minutes
START_DATE = datetime(2026, 1, 1, tzinfo=timezone.utc)
END_DATE = datetime(2026, 6, 27, tzinfo=timezone.utc)  # exclusif -> jusqu'au 26 inclus

OUTPUT_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "reports",
    "xauusd_m3_2026_01_01_to_2026_06_26.json",
)

CHUNK_DAYS = 30  # 30 jours M3 = ~14 400 barres

# --- Connexion MT5 -----------------------------------------------------------
print("[1/3] Connexion a MetaTrader 5...")
if not mt5.initialize():
    print(f"[ERREUR] Connexion MT5 : {mt5.last_error()}")
    sys.exit(1)

ti = mt5.terminal_info()
if ti:
    print(f"  Terminal : {ti.name} (build {ti.build})")

ai = mt5.account_info()
if ai:
    print(f"  Compte   : {ai.login} @ {ai.server}")

# Activer le symbole
info = mt5.symbol_info(SYMBOL)
if info is None:
    print(f"[ERREUR] Symbole {SYMBOL} indisponible chez ce broker.")
    mt5.shutdown()
    sys.exit(1)

if not info.visible:
    mt5.symbol_select(SYMBOL, True)

print(f"  Symbole  : {SYMBOL} (digits={info.digits}, spread={info.spread})")

# --- Telechargement par chunks -----------------------------------------------
print(f"\n[2/3] Telechargement M3 par chunks de {CHUNK_DAYS} jours...")

all_bars = []
chunk_start = START_DATE
chunk_num = 0
total_bars = 0

while chunk_start < END_DATE:
    # Calcul de la fin de chunk
    chunk_end_ts = chunk_start.timestamp() + CHUNK_DAYS * 86400
    if chunk_end_ts >= END_DATE.timestamp():
        chunk_end_dt = END_DATE
    else:
        chunk_end_dt = datetime.fromtimestamp(chunk_end_ts, tz=timezone.utc)

    chunk_num += 1
    print(
        f"  Chunk {chunk_num:02d} : "
        f"{chunk_start.strftime('%Y-%m-%d')} --> {chunk_end_dt.strftime('%Y-%m-%d')} ...",
        end=" ", flush=True,
    )

    rates = mt5.copy_rates_range(SYMBOL, TIMEFRAME, chunk_start, chunk_end_dt)

    if rates is None or len(rates) == 0:
        print(f"0 barres (pas de donnees sur cette periode)")
        chunk_start = chunk_end_dt
        continue

    chunk_bars = []
    for r in rates:
        chunk_bars.append({
            "time": int(r[0]),
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
            "tick_volume": int(r[5]),
            "spread": int(r[6]) if len(r) > 6 else 0,
            "real_volume": int(r[7]) if len(r) > 7 else 0,
        })

    all_bars.extend(chunk_bars)
    n = len(chunk_bars)
    total_bars += n
    first_dt = datetime.fromtimestamp(chunk_bars[0]["time"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    last_dt = datetime.fromtimestamp(chunk_bars[-1]["time"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    print(f"{n} barres ({first_dt} --> {last_dt})")

    chunk_start = chunk_end_dt

# --- Sauvegarde --------------------------------------------------------------
print(f"\n[3/3] Sauvegarde de {total_bars} barres...")

os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

data = {
    "symbol": SYMBOL,
    "timeframe": "M3",
    "start_date": START_DATE.strftime("%Y-%m-%d"),
    "end_date": END_DATE.strftime("%Y-%m-%d"),
    "total_bars": total_bars,
    "broker": ai.server if ai else "unknown",
    "downloaded_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    "bars": all_bars,
}

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False)

file_size_kb = os.path.getsize(OUTPUT_FILE) / 1024

print(f"  Fichier : {OUTPUT_FILE}")
print(f"  Taille  : {file_size_kb:.0f} Ko")
print(f"  Barres  : {total_bars}")

if all_bars:
    first = datetime.fromtimestamp(all_bars[0]["time"], tz=timezone.utc)
    last = datetime.fromtimestamp(all_bars[-1]["time"], tz=timezone.utc)
    print(f"  Periode : {first.strftime('%Y-%m-%d %H:%M')} --> {last.strftime('%Y-%m-%d %H:%M')} UTC")
    high = max(b["high"] for b in all_bars)
    low = min(b["low"] for b in all_bars)
    print(f"  Range   : {low:.2f} --> {high:.2f} ({high - low:.2f} USD)")

mt5.shutdown()
print("\n[OK] Termine.")
