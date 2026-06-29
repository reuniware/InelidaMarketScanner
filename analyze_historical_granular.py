#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Analyse historique granulaire: chaque signal suivi sur tous ses points JSONL."""
import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from collections import defaultdict

JSONL_PATH = "new_analysis_02/live_ict_signals_global.jsonl"

def load(path):
    sigs = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line: sigs.append(json.loads(line))
    return sigs

sigs = load(JSONL_PATH)
print(f"Total lignes JSONL: {len(sigs)}")

# Regrouper par cle unique (symbol+direction+dol_label)
# et garder TOUS les points chronologiques
groups = defaultdict(list)
for s in sigs:
    key = f"{s['symbol']}|{s['direction']}|{s['dol_label']}"
    groups[key].append(s)

print(f"Signaux uniques: {len(groups)}")
print()

def check_outcome_at_price(sig, bid, ask):
    """Verifie si, a un instant T (bid/ask donnes), TP1 ou SL est touche."""
    plan = sig.get("trade_plan", {})
    tp1 = plan.get("tp1")
    sl = plan.get("sl")
    if tp1 is None or sl is None:
        return "unknown"
    direction = sig.get("direction", "bull")
    if direction == "bull":
        if ask >= tp1: return "tp1"
        if bid <= sl: return "sl"
    else:
        if bid <= tp1: return "tp1"
        if ask >= sl: return "sl"
    return "active"

def calc_pnl(sig, bid, ask):
    """Calcule le P&L en R a un instant T."""
    entry = sig.get("entry", 0)
    plan = sig.get("trade_plan", {})
    risk = plan.get("risk", 1)
    if risk == 0: risk = 1
    direction = sig.get("direction", "bull")
    if direction == "bull":
        return (bid - entry) / risk
    else:
        return (entry - ask) / risk

def get_evolution(points):
    """Analyse l'evolution historique complete d'un signal a travers tous ses points."""
    first = points[0]
    last = points[-1]
    entry = first.get("entry", 0)
    plan = first.get("trade_plan", {})
    tp1 = plan.get("tp1")
    sl = plan.get("sl")
    risk = plan.get("risk", 1)
    if risk == 0: risk = 1
    direction = first.get("direction", "bull")

    # Suivi des extremums
    max_pnl = float("-inf")
    min_pnl = float("inf")
    max_bid = float("-inf")
    min_bid = float("inf")
    max_ask = float("-inf")
    min_ask = float("inf")
    ever_hit_tp1 = False
    ever_hit_sl = False
    ts_first = first["ts_utc"][:19]
    ts_last = last["ts_utc"][:19]
    ts_tp1 = None
    ts_sl = None
    n_points = len(points)

    points_data = []
    for s in points:
        bid = s.get("current_bid", 0)
        ask = s.get("current_ask", 0)
        ts = s["ts_utc"][:19]
        pnl = calc_pnl(s, bid, ask)
        outcome = check_outcome_at_price(s, bid, ask)

        if outcome == "tp1" and not ever_hit_tp1:
            ever_hit_tp1 = True
            ts_tp1 = ts
        if outcome == "sl" and not ever_hit_sl:
            ever_hit_sl = True
            ts_sl = ts

        max_pnl = max(max_pnl, pnl)
        min_pnl = min(min_pnl, pnl)
        max_bid = max(max_bid, bid)
        min_bid = min(min_bid, bid)
        max_ask = max(max_ask, ask)
        min_ask = min(min_ask, ask)
        points_data.append((ts, bid, ask, pnl, outcome))

    # MFE (Maximum Favorable Excursion) en R
    if direction == "bull":
        best_price = max_bid
        worst_price = min_bid
    else:
        best_price = min_ask
        worst_price = max_ask

    if direction == "bull":
        mfe = (best_price - entry) / risk
        mae = (entry - worst_price) / risk
    else:
        mfe = (entry - best_price) / risk
        mae = (worst_price - entry) / risk

    # Dernier outcome
    last_outcome = check_outcome_at_price(last, last.get("current_bid", 0), last.get("current_ask", 0))
    last_pnl = calc_pnl(last, last.get("current_bid", 0), last.get("current_ask", 0))

    return {
        "symbol": first["symbol"],
        "direction": direction,
        "dol_label": first["dol_label"],
        "action": first["action"],
        "entry": entry,
        "tp1": tp1,
        "sl": sl,
        "rr1": plan.get("rr1", 0),
        "fvg_pct": first.get("fvg_gap_pct", 0),
        "dol_dist": plan.get("dol_distance_pct", 0),
        "symbol_type": first.get("symbol_type", "?"),
        "raid_type": first.get("raid_type", "?"),
        "n_points": n_points,
        "ts_first": ts_first,
        "ts_last": ts_last,
        "ts_tp1": ts_tp1,
        "ts_sl": ts_sl,
        "ever_tp1": ever_hit_tp1,
        "ever_sl": ever_hit_sl,
        "mfe": mfe,
        "mae": mae,
        "pnl_min": min_pnl,
        "pnl_max": max_pnl,
        "last_outcome": last_outcome,
        "last_pnl": last_pnl,
        "last_bid": last.get("current_bid", 0),
        "last_ask": last.get("current_ask", 0),
    }

# Traiter tous les signaux
results = []
for key, points in groups.items():
    points_sorted = sorted(points, key=lambda x: x["ts_utc"])
    ev = get_evolution(points_sorted)
    results.append(ev)

# =====================================================================
# RAPPORT GLOBAL
# =====================================================================
print("=" * 90)
print("  ANALYSE HISTORIQUE COMPLETE (TOUS LES POINTS JSONL)")
print("=" * 90)

# Stats finales vs historiques
final_tp1 = sum(1 for r in results if r["last_outcome"] == "tp1")
final_sl = sum(1 for r in results if r["last_outcome"] == "sl")
final_active = sum(1 for r in results if r["last_outcome"] == "active")

ever_tp1 = sum(1 for r in results if r["ever_tp1"])
ever_sl = sum(1 for r in results if r["ever_sl"])
ever_resolved = sum(1 for r in results if r["ever_tp1"] or r["ever_sl"])
ever_both = sum(1 for r in results if r["ever_tp1"] and r["ever_sl"])
never_resolved = sum(1 for r in results if not r["ever_tp1"] and not r["ever_sl"])

print(f"\n  --- ETAT FINAL (dernier point) ---")
print(f"  TP1 au dernier scan  : {final_tp1:>3}")
print(f"  SL au dernier scan   : {final_sl:>3}")
print(f"  Encore actifs        : {final_active:>3}")
print(f"  Total                : {len(results):>3}")

print(f"\n  --- ETAT HISTORIQUE (sur TOUS les points) ---")
print(f"  Ont TOUCHE TP1 a un moment : {ever_tp1:>3}")
print(f"  Ont TOUCHE SL a un moment  : {ever_sl:>3}")
print(f"  Ont touche TP1 ET SL       : {ever_both:>3}")
print(f"  Jamais resolves            : {never_resolved:>3}")

if ever_resolved > 0:
    hist_win_rate = ever_tp1 / ever_resolved * 100
    print(f"  TAUX HISTORIQUE (TP1/resolus) : {hist_win_rate:.1f}% ({ever_tp1}/{ever_resolved})")

# Signaux actifs en dernier point mais qui ont deja touche TP1 puis recule
tp1_then_back = sum(1 for r in results if r["ever_tp1"] and r["last_outcome"] == "active")
sl_then_recovered = sum(1 for r in results if r["ever_sl"] and r["last_outcome"] == "active")
tp1_then_sl = sum(1 for r in results if r["ever_tp1"] and r["ever_sl"])

print(f"\n  --- DETAILS CACHES ---")
print(f"  Signaux ayant touche TP1 PUIS recule (maintenant actifs): {tp1_then_back}")
print(f"  Signaux ayant touche SL PUIS recule (maintenant actifs) : {sl_then_recovered}")
print(f"  Signaux ayant touche TP1 PUIS SL (les deux!)            : {tp1_then_sl}")

# MFE/MAE analysis
print(f"\n{'='*90}")
print("  MFE / MAE ANALYSIS (Maximum Favorable/Adverse Excursion)")
print("=" * 90)

# MFE moyen sur les signaux jamais resolus
never = [r for r in results if not r["ever_tp1"] and not r["ever_sl"]]
if never:
    avg_mfe = sum(r["mfe"] for r in never) / len(never)
    avg_mae = sum(r["mae"] for r in never) / len(never)
    max_mfe = max(r["mfe"] for r in never)
    max_mae = max(r["mae"] for r in never)
    print(f"\n  Signaux jamais resolves: {len(never)}")
    print(f"  MFE moyen: {avg_mfe:+.3f}R (meilleur point atteint)")
    print(f"  MAE moyen: {avg_mae:+.3f}R (pire point atteint)")
    print(f"  MFE max  : {max_mfe:+.3f}R")
    print(f"  MAE max  : {max_mae:+.3f}R")

# Top signaux par MFE (meilleur potentiel inexploite)
print(f"\n  TOP 10 SIGNAUX PAR MFE (jamais resolves, meilleur potentiel) :")
never_sorted = sorted(never, key=lambda x: x["mfe"], reverse=True)
print(f"  {'Symbol':<12} {'Dir':<5} {'Entry':>10} {'MFE(R)':>8} {'P&L final':>10} {'Points':>6}")
print(f"  {'-'*51}")
for r in never_sorted[:10]:
    print(f"  {r['symbol']:<12} {r['direction']:<5} {r['entry']:>10.4f} {r['mfe']:>+8.2f}R {r['last_pnl']:>+10.3f}R {r['n_points']:>6}")

# Top signaux par MAE (pire derivee)
print(f"\n  TOP 10 SIGNAUX PAR MAE (jamais resolves, pire derivee) :")
never_sorted_mae = sorted(never, key=lambda x: x["mae"], reverse=True)
print(f"  {'Symbol':<12} {'Dir':<5} {'Entry':>10} {'MAE(R)':>8} {'P&L final':>10} {'Points':>6}")
print(f"  {'-'*51}")
for r in never_sorted_mae[:10]:
    print(f"  {r['symbol']:<12} {r['direction']:<5} {r['entry']:>10.4f} {r['mae']:>+8.2f}R {r['last_pnl']:>+10.3f}R {r['n_points']:>6}")

# Signaux qui ont touche TP1 mais pas SL, puis recule
tp1_ever = [r for r in results if r["ever_tp1"] and not r["ever_sl"]]
if tp1_ever:
    print(f"\n  SIGNAUX AYANT TOUCHE TP1 (sans toucher SL) : {len(tp1_ever)}")
    print(f"  {'Symbol':<12} {'Dir':<5} {'RR1':>6} {'Entry':>10} {'TP1':>10} {'TP1 Time':>12} {'Final':>8}")
    print(f"  {'-'*63}")
    for r in sorted(tp1_ever, key=lambda x: x["ts_tp1"]):
        fin = "TP1" if r["last_outcome"]=="tp1" else ("SL" if r["last_outcome"]=="sl" else "ACTIF")
        print(f"  {r['symbol']:<12} {r['direction']:<5} {r['rr1']:>6.1f}R {r['entry']:>10.4f} {r['tp1']:>10.4f} {r['ts_tp1'][11:19]:>12} {fin:>8}")

# Signaux qui ont touche SL seulement
sl_ever = [r for r in results if not r["ever_tp1"] and r["ever_sl"]]
if sl_ever:
    print(f"\n  SIGNAUX AYANT TOUCHE SL (sans toucher TP1) : {len(sl_ever)}")
    print(f"  {'Symbol':<12} {'Dir':<5} {'RR1':>6} {'Entry':>10} {'SL':>10} {'SL Time':>12} {'MFE(R)':>8}")
    print(f"  {'-'*63}")
    for r in sorted(sl_ever, key=lambda x: x["ts_sl"]):
        print(f"  {r['symbol']:<12} {r['direction']:<5} {r['rr1']:>6.1f}R {r['entry']:>10.4f} {r['sl']:>10.4f} {r['ts_sl'][11:19]:>12} {r['mfe']:>+8.2f}R")

# Bilan P&L final (sur le dernier point)
total_pnl = sum(r["last_pnl"] for r in results)
pnl_winners = sum(r["last_pnl"] for r in results if r["last_outcome"] == "tp1")
pnl_losers = sum(r["last_pnl"] for r in results if r["last_outcome"] == "sl")
pnl_active = sum(r["last_pnl"] for r in results if r["last_outcome"] == "active")

print(f"\n{'='*90}")
print("  BILAN P&L (sur le dernier point de chaque signal)")
print("=" * 90)
print(f"  P&L total (tous signaux) : {total_pnl:+.2f}R")
print(f"  P&L des TP1              : {pnl_winners:+.2f}R")
print(f"  P&L des SL               : {pnl_losers:+.2f}R")
print(f"  P&L des actifs           : {pnl_active:+.2f}R")
print(f"  P&L moyen par signal     : {total_pnl/len(results):+.3f}R")

# Esperance reelle
rr_tp1 = [r["rr1"] for r in results if r["last_outcome"] == "tp1"]
print(f"\n  Esperance reelle (sur etat final):")
print(f"  Win rate: {final_tp1}/{final_tp1+final_sl} = {final_tp1/(final_tp1+final_sl)*100:.1f}%")
if rr_tp1:
    avg_rr_win = sum(rr_tp1) / len(rr_tp1)
    exp_reelle = (final_tp1/(final_tp1+final_sl) * avg_rr_win) - (final_sl/(final_tp1+final_sl) * 1)
    print(f"  RR1 moyen gagnants: {avg_rr_win:.2f}R")
    print(f"  Esperance reelle: {exp_reelle:+.3f}R par trade")

print(f"\n  Esperance MAX (si tous les TP1 touches historiquement etaient conserves):")
print(f"  Win rate max: {ever_tp1}/{ever_resolved} = {ever_tp1/ever_resolved*100:.1f}%")
rr_ever = [r["rr1"] for r in results if r["ever_tp1"]]
if rr_ever:
    avg_rr_ever = sum(rr_ever) / len(rr_ever)
    exp_max = (ever_tp1/ever_resolved * avg_rr_ever) - (ever_sl/ever_resolved * 1)
    print(f"  RR1 moyen ayant touche TP1: {avg_rr_ever:.2f}R")
    print(f"  Esperance maximale: {exp_max:+.3f}R par trade")

# Resume final
print(f"\n{'='*90}")
print("  SYNTHESE")
print("=" * 90)
print(f"  Signaux uniques analyses       : {len(results)}")
print(f"  Total points temporels         : {len(sigs)}")
print(f"  Points en moyenne par signal   : {len(sigs)/len(results):.1f}")
print(f"")
print(f"  ETAT FINAL (dernier instantane):")
print(f"    TP1 -> {final_tp1:>3}  |  SL -> {final_sl:>3}  |  Actif -> {final_active:>3}")
print(f"    Win rate: {final_tp1}/{final_tp1+final_sl} = {final_tp1/(final_tp1+final_sl)*100:.1f}%")
print(f"")
print(f"  ETAT HISTORIQUE (sur TOUS les points):")
print(f"    Ont touche TP1 (au moins 1x): {ever_tp1:>3}")
print(f"    Ont touche SL (au moins 1x) : {ever_sl:>3}")
print(f"    Jamais resolves              : {never_resolved:>3}")
print(f"    Win rate historique: {ever_tp1}/{ever_resolved} = {ever_tp1/ever_resolved*100:.1f}%")
print(f"")
print(f"  ESPERANCE:")
print(f"    Reelle (sur etat final) : {exp_reelle:+.3f}R/trade" if 'exp_reelle' in dir() else "")
print(f"    Maximale (historique)   : {exp_max:+.3f}R/trade" if 'exp_max' in dir() else "")
print(f"")
print(f"  SIGNaux ayant RECULE APRES TP1: {tp1_then_back}")
print(f"  => Ces trades etaient gagnants mais le suivi n'a pas ete maintenu.")
