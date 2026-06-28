"""
Analyse comparative des trades gagnants vs perdants du backtest ICT FVG.
"""

import json
import os
from datetime import datetime, timezone
from collections import Counter

UTC = timezone.utc
RESULTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "reports", "backtest_ict_fvg_results.json")

with open(RESULTS_FILE, "r", encoding="utf-8") as f:
    stats = json.load(f)

trades = stats["trades"]
wins = [t for t in trades if t["status"] in ("WIN_FULL", "WIN_PARTIAL")]
losses = [t for t in trades if t["status"] == "LOSS"]

print("=" * 80)
print(f"  ANALYSE WINNERS ({len(wins)}) vs LOSERS ({len(losses)})")
print("=" * 80)

# ── 1. PAR HEURE DE RAID ──────────────────────────────────────────────
print("\n--- 1. HEURE UTC DU RAID ---")
print(f"{'Heure':<10} {'Wins':>6} {'Losses':>6} {'WR%':>8} {'Total':>6}")
print("-" * 40)

hours = {}
for t in trades:
    h = datetime.fromtimestamp(t["raid_time"], tz=UTC).hour
    hours.setdefault(h, {"w": 0, "l": 0})
    cat = "w" if t["status"].startswith("WIN") else "l"
    hours[h][cat] += 1

for h in sorted(hours):
    d = hours[h]
    wr = d["w"] / (d["w"] + d["l"]) * 100 if (d["w"] + d["l"]) > 0 else 0
    bar = "#" * int(wr / 5)
    print(f"  {h:02d}:00    {d['w']:>4}   {d['l']:>4}   {wr:>5.0f}%   {d['w']+d['l']:>4}  {bar}")

# ── 2. PAR TYPE DE DOL ────────────────────────────────────────────────
print("\n--- 2. TYPE DE DRAW ON LIQUIDITY ---")
print(f"{'DOL Type':<22} {'Wins':>5} {'Losses':>6} {'WR%':>7}")

dol_types = {}
for t in trades:
    label = t["dol_label"]
    # Normaliser
    if "PDH" in label:
        key = "PDH"
    elif "PDL" in label:
        key = "PDL"
    elif "AH" in label:
        key = "Asian High"
    elif "AL" in label:
        key = "Asian Low"
    else:
        key = label[:20]
    dol_types.setdefault(key, {"w": 0, "l": 0})
    cat = "w" if t["status"].startswith("WIN") else "l"
    dol_types[key][cat] += 1

for k in sorted(dol_types, key=lambda x: -(dol_types[x]["w"] + dol_types[x]["l"])):
    d = dol_types[k]
    wr = d["w"] / (d["w"] + d["l"]) * 100 if (d["w"] + d["l"]) > 0 else 0
    print(f"  {k:<22} {d['w']:>4}  {d['l']:>4}  {wr:>5.0f}%")

# ── 3. PAR TAILLE DE FVG (gap_pct) ────────────────────────────────────
print("\n--- 3. TAILLE DU FVG (gap %) ---")
buckets = [(0, 0.05), (0.05, 0.10), (0.10, 0.15), (0.15, 0.20),
           (0.20, 0.30), (0.30, 0.50), (0.50, 1.0), (1.0, 999)]
print(f"{'FVG %':<16} {'Wins':>5} {'Losses':>6} {'WR%':>7} {'Avg PnL':>8}")

for lo, hi in buckets:
    bucket = [t for t in trades if lo <= t.get("fvg_gap_pct", 0) < hi]
    if not bucket:
        continue
    w = sum(1 for t in bucket if t["status"].startswith("WIN"))
    l = sum(1 for t in bucket if t["status"] == "LOSS")
    wr = w / (w + l) * 100 if (w + l) > 0 else 0
    avg_pnl = sum(t["pnl_r"] for t in bucket) / len(bucket)
    label = f"{lo:.2f}-{hi:.2f}%"
    print(f"  {label:<16} {w:>4}  {l:>4}  {wr:>5.0f}%  {avg_pnl:>+7.2f}R")

# ── 4. PAR DIRECTION ──────────────────────────────────────────────────
print("\n--- 4. DIRECTION (BUY vs SELL) ---")
for direction in ("bull", "bear"):
    subset = [t for t in trades if t["direction"] == direction]
    w = sum(1 for t in subset if t["status"].startswith("WIN"))
    l = sum(1 for t in subset if t["status"] == "LOSS")
    wr = w / (w + l) * 100 if (w + l) > 0 else 0
    avg_pnl = sum(t["pnl_r"] for t in subset) / len(subset) if subset else 0
    print(f"  {direction:5} : {len(subset):>3} trades | {w:>3}W / {l:>3}L "
          f"| WR={wr:.0f}% | Avg={avg_pnl:+.2f}R")

# ── 5. DISTANCE AU DOL ────────────────────────────────────────────────
print("\n--- 5. DISTANCE ENTRY -> DOL (% du prix) ---")
for status, trades_subset in [("WIN", wins), ("LOSS", losses)]:
    if not trades_subset:
        continue
    dists = []
    for t in trades_subset:
        dol = t["dol_level"]
        entry = t["entry_price"]
        dist = abs(dol - entry) / entry * 100
        dists.append(dist)
    avg_d = sum(dists) / len(dists)
    print(f"  {status:5} : avg dist = {avg_d:.2f}% (min={min(dists):.2f}, max={max(dists):.2f})")

# ── 6. WINNERS : PROFIL DES MEILLEURS ─────────────────────────────────
print("\n--- 6. TOP 10 WINNERS (meilleur PnL) ---")
sorted_wins = sorted(wins, key=lambda t: t["pnl_r"], reverse=True)
for t in sorted_wins[:10]:
    rd = datetime.fromtimestamp(t["raid_time"], tz=UTC).strftime("%m-%d %H:%M")
    print(f"  +{t['pnl_r']:.2f}R | {t['day']} {rd} UTC | "
          f"{t['direction']:4} | DOL={t['dol_label']:<18} | "
          f"FVG={t['fvg_gap_pct']:.3f}% | Opp={t['opposing_label']}")

# ── 7. CALENDRIER HEBDOMADAIRE ────────────────────────────────────────
print("\n--- 7. WINRATE PAR JOUR DE SEMAINE ---")
days_of_week = ["Lun", "Mar", "Mer", "Jeu", "Ven"]
weekday_stats = {d: {"w": 0, "l": 0} for d in days_of_week}
for t in trades:
    dt = datetime.strptime(t["day"], "%Y-%m-%d")
    dow = dt.weekday()  # 0=Mon
    if dow < 5:
        day_name = days_of_week[dow]
        cat = "w" if t["status"].startswith("WIN") else "l"
        weekday_stats[day_name][cat] += 1

for day in days_of_week:
    d = weekday_stats[day]
    wr = d["w"] / (d["w"] + d["l"]) * 100 if (d["w"] + d["l"]) > 0 else 0
    print(f"  {day:4} : {d['w']:>3}W / {d['l']:>3}L | WR={wr:.0f}% ({d['w']+d['l']} trades)")

# ── 8. DÉLAI RAID -> FVG -> ENTRÉE ───────────────────────────────────
print("\n--- 8. DÉLAIS MOYENS (en barres M3) ---")
for status, trades_subset in [("WIN", wins), ("LOSS", losses)]:
    if not trades_subset:
        continue
    raid_to_fvg = []
    fvg_to_entry = []
    for t in trades_subset:
        rt = t.get("raid_time", 0)
        ft = t.get("fvg_time", 0)
        # On peut estimer le delta via les index de barres
        pass
    # On utilise les epochs pour estimer
    deltas_rf = []
    deltas_fe = []
    for t in trades_subset:
        rt = t.get("raid_time", 0)
        ft = t.get("fvg_time", 0)
        if rt and ft and ft > rt:
            deltas_rf.append((ft - rt) / 180)  # 180 sec = 3 min
    if deltas_rf:
        print(f"  {status:5} : Raid->FVG = {sum(deltas_rf)/len(deltas_rf):.1f} barres M3 "
              f"({sum(deltas_rf)/len(deltas_rf)*3:.0f} min)")

print("\n" + "=" * 80)
