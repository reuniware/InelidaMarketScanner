"""
analyze_open_elite.py
=====================
Analyse les trades ELITE v2 marques comme "OUVERT" dans le backtest
et determine s'ils etaient en direction favorable (positifs) ou non (negatifs)
au moment du dernier bar M1 disponible.
"""

import json, os, sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RESULTS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "reports", "backtest_all_results.json"
)

ELITE_ALLOWED_TYPES = {"FOREX_USD", "INDEX", "METAL"}

def passes_v2(t):
    hour = t.get("scan_hour")
    if hour is not None and not (hour >= 9 and hour < 13):
        return False
    if t.get("sym_type", "") not in ELITE_ALLOWED_TYPES:
        return False
    spread = t.get("spread_pct")
    if spread is not None and spread >= 0.50:
        return False
    return True

with open(RESULTS_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

all_trades = data["all_trades"]
v2_trades = [t for t in all_trades if passes_v2(t)]

print("=" * 100)
print("  ANALYSE DES TRADES ELITE v2 'OUVERTS'")
print("=" * 100)
print()

# Classer par outcome
by_outcome = Counter(t["outcome"] for t in v2_trades)
print(f"  Total trades ELITE v2: {len(v2_trades)}")
print(f"  GAGNE: {by_outcome.get('GAGNE', 0)}")
print(f"  PERDU: {by_outcome.get('PERDU', 0)}")
print(f"  OUVERT: {by_outcome.get('OUVERT', 0)}")
print(f"  INDETERMINE: {by_outcome.get('INDETERMINE', 0)}")
print()

open_trades = [t for t in v2_trades if t["outcome"] == "OUVERT"]

if not open_trades:
    print("  Aucun trade OUVERT trouve.")
    sys.exit(0)

print(f"  DETAIL DES {len(open_trades)} TRADES OUVERTS")
print(f"  {'=' * 70}")
print()

# Pour chaque trade ouvert, on regarde le dernier bar connu
# Si last_bar_close est renseigne, on peut voir si le prix va vers TP ou SL
positive = 0
negative = 0
neutral = 0
no_data = 0

for i, t in enumerate(open_trades):
    sym = t["symbol"]
    action = t["action"]
    entry = t["entry"]
    sl = t["sl"]
    tp = t["tp"] if t.get("tp") else "N/A"
    last_close = t.get("last_bar_close")
    last_time = t.get("last_bar_time")
    pnl_r = t.get("pnl_pct", 0)
    
    # Determiner si le trade est en positif ou negatif
    # Si last_bar_close existe, on compare avec l'entry
    if last_close is not None and entry is not None:
        if action == "BUY":
            dist_tp = tp - entry if isinstance(tp, (int, float)) else 0
            dist_sl = entry - sl
            current_dist = last_close - entry
            pct_to_tp = (current_dist / dist_tp * 100) if dist_tp > 0 else 0
            pct_to_sl = (current_dist / dist_sl * 100) if dist_sl > 0 else 0
        else:  # SELL
            dist_tp = entry - tp if isinstance(tp, (int, float)) else 0
            dist_sl = sl - entry
            current_dist = entry - last_close
            pct_to_tp = (current_dist / dist_tp * 100) if dist_tp > 0 else 0
            pct_to_sl = (current_dist / dist_sl * 100) if dist_sl > 0 else 0
        
        status = "✅ VERS TP" if pct_to_tp > 50 else ("⚠️ VERS SL" if pct_to_sl > 50 else "➡️ NEUTRE")
        
        if pct_to_tp > 50:
            positive += 1
        elif pct_to_sl > 50:
            negative += 1
        else:
            neutral += 1
        
        tp_str = f"{tp:.4f}" if isinstance(tp, (int, float)) else str(tp)
        print(f"  {i+1:>2d}. {sym:<16s} {action:>4s} | Entry:{entry:<12.4f} SL:{sl:<12.4f} TP:{tp_str:<12s} | "
              f"Dernier: {last_close:.4f} | {status}  ({pct_to_tp:.0f}%->TP / {pct_to_sl:.0f}%->SL)")
    else:
        no_data += 1
        print(f"  {i+1:>2d}. {sym:<16s} {action:>4s} | Entry:{entry:<12.4f} SL:{sl:<12.4f}  | "
              f"Pas de data M1 disponible")

print()
print(f"  SYNTHESE:")
print(f"  {'=' * 50}")
total_with_data = positive + negative + neutral
if total_with_data > 0:
    print(f"  ✅ En direction du TP (positif):     {positive:>3d} / {total_with_data:>3d}  ({positive/total_with_data*100:.0f}%)")
    print(f"  ⚠️  En direction du SL (negatif):    {negative:>3d} / {total_with_data:>3d}  ({negative/total_with_data*100:.0f}%)")
    print(f"  ➡️  Neutre (entre SL et TP):         {neutral:>3d} / {total_with_data:>3d}  ({neutral/total_with_data*100:.0f}%)")
if no_data > 0:
    print(f"  ❓ Pas de donnees M1:                {no_data:>3d} / {by_outcome.get('OUVERT', 0):>3d}")
print()

# Ajouter une analyse du P&L potentiel des trades ouverts
# Si on les fermait au dernier prix connu
print(f"  P&L POTENTIEL SI FERMETURE AU DERNIER PRIX:")
print(f"  {'=' * 50}")
# Recalculer en utilisant pnl_pct (en R) et les donnees MT5
# On va charger les donnees de calc_elite_pnl si disponibles
pnl_potential = sum(t.get("pnl_pct", 0) for t in open_trades if t.get("pnl_pct") is not None)
print(f"  Somme des P&L (en R) des trades ouverts: {pnl_potential:+.3f}R")
print(f"  (Positif = en faveur du trade au dernier check)")
