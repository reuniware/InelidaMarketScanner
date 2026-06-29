#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Analyse SL 2x avec historique complet JSONL.
Pour chaque signal ayant touche SL, on utilise TOUS les points temporels
pour verifier si avec un SL 2x plus large, le TP1 aurait ete atteint.
"""
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

all_sigs = load(JSONL_PATH)

# Grouper par cle unique (symbol+direction+dol_label) avec TOUS les points chronologiques
groups = defaultdict(list)
for s in all_sigs:
    key = f"{s['symbol']}|{s['direction']}|{s['dol_label']}"
    groups[key].append(s)

# Trier chaque groupe par timestamp
for k in groups:
    groups[k].sort(key=lambda x: x["ts_utc"])

def check_outcome_at(sig, bid, ask):
    plan = sig.get("trade_plan", {})
    tp1 = plan.get("tp1")
    sl = plan.get("sl")
    if tp1 is None or sl is None: return "unknown"
    direction = sig.get("direction", "bull")
    if direction == "bull":
        if ask >= tp1: return "tp1"
        if bid <= sl: return "sl"
    else:
        if bid <= tp1: return "tp1"
        if ask >= sl: return "sl"
    return "active"

def check_tp1_sl_at(sig, bid, ask, sl_wider=None):
    """Verifie TP1 et SL (eventuellement elargi) a un instant T."""
    plan = sig.get("trade_plan", {})
    tp1 = plan.get("tp1")
    sl = plan.get("sl")
    if tp1 is None: return "unknown"
    direction = sig.get("direction", "bull")
    effective_sl = sl_wider if sl_wider is not None else sl
    if direction == "bull":
        if ask >= tp1: return "tp1"
        if effective_sl is not None and bid <= effective_sl: return "sl"
    else:
        if bid <= tp1: return "tp1"
        if effective_sl is not None and ask >= effective_sl: return "sl"
    return "active"

print("=" * 90)
print("  ANALYSE SL 2x AVEC HISTORIQUE COMPLET JSONL")
print("=" * 90)
print(f"\n  Total signaux uniques: {len(groups)}")
print(f"  Total points temporels: {len(all_sigs)}")

# Pour chaque groupe, determiner le dernier outcome
results = []
for key, points in groups.items():
    last = points[-1]
    outcome = check_outcome_at(last, last.get("current_bid", 0), last.get("current_ask", 0))
    
    entry = last.get("entry", 0)
    plan = last.get("trade_plan", {})
    tp1 = plan.get("tp1")
    sl = plan.get("sl")
    risk = plan.get("risk", 1)
    if risk == 0: risk = 1
    direction = last.get("direction", "bull")
    
    # SL 2x plus large
    if direction == "bull":
        sl_wider = entry - risk * 2
    else:
        sl_wider = entry + risk * 2
    
    # Simuler avec SL 2x sur TOUS les points
    ever_tp1_wider = False
    ever_sl_wider = False
    max_pnl = float("-inf")
    min_pnl = float("inf")
    final_outcome_wider = "active"
    ts_tp1_wider = None
    
    for p in points:
        bid = p.get("current_bid", 0)
        ask = p.get("current_ask", 0)
        
        # P&L instantane
        if direction == "bull":
            pnl = (bid - entry) / risk if risk > 0 else 0
        else:
            pnl = (entry - ask) / risk if risk > 0 else 0
        max_pnl = max(max_pnl, pnl)
        min_pnl = min(min_pnl, pnl)
        
        # Outcome avec SL 2x
        o = check_tp1_sl_at(p, bid, ask, sl_wider)
        if o == "tp1":
            ever_tp1_wider = True
            if ts_tp1_wider is None:
                ts_tp1_wider = p["ts_utc"][:19]
            # On continue a verifier si SL est touche apres
        if o == "sl":
            ever_sl_wider = True
            final_outcome_wider = "sl"
        
        if o == "tp1":
            final_outcome_wider = "tp1"
    
    # Si jamais SL 2x touche mais TP1 aussi, c'est tp1 (priorite au TP)
    if ever_tp1_wider and ever_sl_wider:
        # Verifier l'ordre: est-ce que TP1 a ete touche AVANT SL ?
        tp1_ts = None
        sl_ts = None
        for p in points:
            bid = p.get("current_bid", 0)
            ask = p.get("current_ask", 0)
            o = check_tp1_sl_at(p, bid, ask, sl_wider)
            if o == "tp1" and tp1_ts is None:
                tp1_ts = p["ts_utc"]
            if o == "sl" and sl_ts is None:
                sl_ts = p["ts_utc"]
        if tp1_ts and sl_ts:
            if tp1_ts <= sl_ts:
                final_outcome_wider = "tp1"
                ever_sl_wider = False  # TP1 arrive avant SL -> avec BE, le SL n'est plus actif
            else:
                final_outcome_wider = "sl"
                ever_tp1_wider = False
        elif tp1_ts:
            final_outcome_wider = "tp1"
        elif sl_ts:
            final_outcome_wider = "sl"
    
    results.append({
        "key": key,
        "symbol": last["symbol"],
        "direction": direction,
        "entry": entry,
        "sl": sl,
        "sl_wider": sl_wider,
        "tp1": tp1,
        "risk": risk,
        "rr1": plan.get("rr1", 0),
        "rr1_wider": (tp1 - entry) / (risk * 2) if direction == "bull" and risk > 0 else
                     (entry - tp1) / (risk * 2) if risk > 0 else 0,
        "outcome_current": outcome,
        "n_points": len(points),
        "ever_tp1_wider": ever_tp1_wider,
        "ever_sl_wider": ever_sl_wider,
        "final_outcome_wider": final_outcome_wider,
        "max_pnl": max_pnl,
        "min_pnl": min_pnl,
        "ts_tp1_wider": ts_tp1_wider,
    })

# Filtrer les signaux qui ont SL dans l'etat actuel
sl_signals = [r for r in results if r["outcome_current"] == "sl"]
print(f"\n  Signaux avec SL actuel: {len(sl_signals)}")

# Avec SL 2x:
tp1_wider = [r for r in sl_signals if r["ever_tp1_wider"]]
sl_wider = [r for r in sl_signals if not r["ever_tp1_wider"] and r["ever_sl_wider"]]
still_active_wider = [r for r in sl_signals if r["final_outcome_wider"] == "active"]

print(f"  Deviennent TP1 avec SL 2x: {len(tp1_wider)}")
print(f"  Encore SL avec SL 2x     : {len(sl_wider)}")
print(f"  Encore actifs avec SL 2x : {len(still_active_wider)}")

if tp1_wider:
    print(f"\n  --- Signaux qui deviennent TP1 avec SL 2x ---")
    print(f"  {'Symbol':<12} {'Dir':<5} {'Entry':>10} {'RR1':>6} {'RR1_2x':>8} {'Npoints':>8} {'MaxPnL':>8}")
    print(f"  {'-'*57}")
    for r in sorted(tp1_wider, key=lambda x: x["rr1_wider"], reverse=True):
        print(f"  {r['symbol']:<12} {r['direction']:<5} {r['entry']:>10.4f} "
              f"{r['rr1']:>5.1f}R {r['rr1_wider']:>7.1f}R {r['n_points']:>8} {r['max_pnl']:>+7.2f}R")

if still_active_wider:
    print(f"\n  --- Signaux encore ACTIFS avec SL 2x (ni TP1 ni SL) ---")
    print(f"  {'Symbol':<12} {'Dir':<5} {'Entry':>10} {'MaxPnL':>8} {'Npoints':>8}")
    print(f"  {'-'*43}")
    for r in sorted(still_active_wider, key=lambda x: x["max_pnl"], reverse=True):
        print(f"  {r['symbol']:<12} {r['direction']:<5} {r['entry']:>10.4f} "
              f"{r['max_pnl']:>+7.2f}R {r['n_points']:>8}")

# MFE/MAE des signaux SL avec et sans SL 2x
if sl_signals:
    print(f"\n  --- MFE/MAE des {len(sl_signals)} signaux SL (avec SL 2x) ---")
    avg_mfe = sum(r["max_pnl"] for r in sl_signals) / len(sl_signals)
    avg_mae = sum(r["min_pnl"] for r in sl_signals) / len(sl_signals)
    print(f"  MFE moyen: {avg_mfe:+.3f}R (meilleur point avec SL 2x)")
    print(f"  MAE moyen: {avg_mae:+.3f}R (pire point avec SL 2x)")
    n_positive_mfe = sum(1 for r in sl_signals if r["max_pnl"] > 0)
    print(f"  Signaux ayant eu un MFE positif: {n_positive_mfe}/{len(sl_signals)} ({n_positive_mfe/len(sl_signals)*100:.1f}%)")
    n_above_1r = sum(1 for r in sl_signals if r["max_pnl"] >= 1.0)
    print(f"  Signaux ayant atteint >=+1.0R: {n_above_1r}/{len(sl_signals)}")

# Esperance projetee avec SL 2x
print(f"\n  --- Esperance projetee avec SL 2x ---")
total_signals = len(sl_signals)
if total_signals > 0:
    wins = len(tp1_wider)
    losses = len(sl_wider)
    unresolved = len(still_active_wider)
    winrate_proj = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0
    avg_rr_win = sum(r["rr1_wider"] for r in tp1_wider) / len(tp1_wider) if tp1_wider else 0
    exp_proj = (wins / (wins + losses) * avg_rr_win) - (losses / (wins + losses) * 1) if (wins + losses) > 0 else 0
    print(f"  Trades (SL actuels): {total_signals}")
    print(f"  TP1 (projete)      : {wins}")
    print(f"  SL (projete)       : {losses}")
    print(f"  Non resolus        : {unresolved}")
    print(f"  WinRate projete    : {winrate_proj:.1f}%")
    print(f"  RR1 moyen gagnants : {avg_rr_win:.2f}R (avec SL 2x)")
    print(f"  Esperance projetee : {exp_proj:+.3f}R/trade")
    print(f"  Esperance actuelle : -1.000R/trade (tous SL)")
    print(f"  AMELIORATION       : {exp_proj - (-1.0):+.3f}R/trade")

# RR1 vs distance au TP1
print(f"\n  --- Distance au TP1 pour les signaux SL (avec SL 2x, si non TP1) ---")
never_tp1 = [r for r in sl_signals if not r["ever_tp1_wider"]]
if never_tp1:
    print(f"  Ces {len(never_tp1)} signaux n'atteignent PAS TP1 meme avec SL 2x.")
    print(f"  Le probleme n'est pas le SL mais l'ENTREE ou la DIRECTION du trade.")
    for r in sorted(never_tp1, key=lambda x: x["max_pnl"])[:5]:
        print(f"  {r['symbol']:<12} {r['direction']:<5} MaxPnL={r['max_pnl']:+.2f}R "
              f"MinPnL={r['min_pnl']:+.2f}R")

print("\n" + "=" * 90)
print("  CONCLUSION")
print("=" * 90)
if tp1_wider:
    print(f"\n  ✓ {len(tp1_wider)} signaux sur {len(sl_signals)} auraient ete gagnants avec SL 2x")
else:
    print(f"\n  ✗ Aucun signal SL ne deviendrait gagnant avec SL 2x")
if still_active_wider:
    print(f"  ~ {len(still_active_wider)} signaux sont encore actifs avec SL 2x (ni TP1 ni SL atteints)")
print(f"\n  Le vrai probleme semble etre l'entree et la selection des setups,")
print(f"  pas seulement la largeur du stop-loss.")
