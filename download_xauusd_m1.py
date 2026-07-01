"""
Telecharge l'historique complet XAUUSD M3 depuis MT5 (01/01/2026 -> 26/06/2026).
Sauvegarde en JSON pour analyse ulterieure.

M3 (~84 960 bougies sur 177 jours) : ~6 chunks de 30 jours.
"""

import json
import os
import sys
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

UTC = timezone.utc

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

# --- Telechargement (corrige: copy_rates_from_pos au lieu de copy_rates_range) ---
print(f"\n[2/3] Telechargement M3...")

all_bars = []

# 80 000 barres M3 = ~166 jours (~5.5 mois)
# Au-dela de 80k, MT5 retourne None (limite du broker FTMO)
max_bars = 80000
print(f"  Telechargement des {max_bars} dernieres barres...")
rates = mt5.copy_rates_from_pos(SYMBOL, TIMEFRAME, 0, max_bars)

if rates is None or len(rates) == 0:
    print(f"  [ERREUR] Aucune donnee retournee par MT5")
    mt5.shutdown()
    sys.exit(1)

start_ts = int(START_DATE.timestamp())
end_ts = int(END_DATE.timestamp())

for r in rates:
    t = int(r[0])
    if t < start_ts or t >= end_ts:
        continue
    all_bars.append({
        "time": t,
        "open": float(r[1]),
        "high": float(r[2]),
        "low": float(r[3]),
        "close": float(r[4]),
        "tick_volume": int(r[5]),
        "spread": int(r[6]) if len(r) > 6 else 0,
        "real_volume": int(r[7]) if len(r) > 7 else 0,
    })

all_bars.sort(key=lambda b: b["time"])
total_bars = len(all_bars)
print(f"  {total_bars} barres dans la periode")

if all_bars:
    first_dt = datetime.fromtimestamp(all_bars[0]["time"], tz=UTC)
    last_dt = datetime.fromtimestamp(all_bars[-1]["time"], tz=UTC)
    print(f"  Periode : {first_dt.strftime('%Y-%m-%d %H:%M')} → {last_dt.strftime('%Y-%m-%d %H:%M')} UTC")

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
    "downloaded_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
    "bars": all_bars,
}

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False)

file_size_kb = os.path.getsize(OUTPUT_FILE) / 1024

print(f"  Fichier : {OUTPUT_FILE}")
print(f"  Taille  : {file_size_kb:.0f} Ko")
print(f"  Barres  : {total_bars}")

if all_bars:
    first = datetime.fromtimestamp(all_bars[0]["time"], tz=UTC)
    last = datetime.fromtimestamp(all_bars[-1]["time"], tz=UTC)
    print(f"  Periode : {first.strftime('%Y-%m-%d %H:%M')} → {last.strftime('%Y-%m-%d %H:%M')} UTC")
    high = max(b["high"] for b in all_bars)
    low = min(b["low"] for b in all_bars)
    print(f"  Range   : {low:.2f} → {high:.2f} ({high - low:.2f} USD)")

mt5.shutdown()
print("\n[OK] Termine.")
