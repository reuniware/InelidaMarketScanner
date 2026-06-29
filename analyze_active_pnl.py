#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Analyse des signaux actifs : profit/perte, distance au TP1/SL."""
import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

JSONL_PATH = "new_analysis_02/live_ict_signals_global.jsonl"

def check_outcome(sig):
    plan = sig.get("trade_plan", {})
    tp1 = plan.get("tp1")
    sl = plan.get("sl")
    if tp1 is None or sl is None:
        return "unknown"
    direction = sig.get("direction", "bull")
    bid = sig.get("current_bid", 0)
    ask = sig.get("current_ask", 0)
    if direction == "bull":
        if ask >= tp1: return "tp1"
        if bid <= sl: return "sl"
    else:
        if bid <= tp1: return "tp1"
        if ask >= sl: return "sl"
    return "active"

def load(path):
    sigs = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line: sigs.append(json.loads(line))
    return sigs

# Dernier signal pour chaque symbole+direction+dol_label (le plus récent)
sigs = load(JSONL_PATH)

# Dédoublonner : garder le dernier signal par clé unique (symbol+direction+dol_label)
seen = {}
for s in sigs:
    key = f"{s['symbol']}|{s['direction']}|{s['dol_label']}"
    seen[key] = s  # dernier ecrase les precedents

uniques = list(seen.values())
total_unique = len(uniques)

# Separer par statut
tp1_sigs = []
sl_sigs = []
active_sigs = []
for s in uniques:
    o = check_outcome(s)
    if o == "tp1": tp1_sigs.append(s)
    elif o == "sl": sl_sigs.append(s)
    else: active_sigs.append(s)

print(f"SIGNAUX UNIQUES (dernier par symbole+direction+DOL) : {total_unique}")
print(f"  TP1: {len(tp1_sigs)}  |  SL: {len(sl_sigs)}  |  Actifs: {len(active_sigs)}")
print()

# --- ANALYSE DES ACTIFS ---
print("=" * 80)
print("  ANALYSE DES TRADES ACTIFS")
print("=" * 80)

# Pour chaque actif, calculer le P&L par rapport a l'entry
def calc_pnl(s):
    """Retourne (pnl_pct, direction_pct, dist_to_tp1_pct, dist_to_sl_pct)"""
    direction = s.get("direction", "bull")
    entry = s.get("entry", 0)
    bid = s.get("current_bid", 0)
    ask = s.get("current_ask", 0)
    plan = s.get("trade_plan", {})
    tp1 = plan.get("tp1", entry)
    sl = plan.get("sl", entry)
    risk = plan.get("risk", 1)
    if risk == 0: risk = 1

    # Prix actuel selon la direction
    if direction == "bull":
        current = bid  # on vend au bid
        pnl_abs = current - entry
        pnl_r = pnl_abs / risk if risk != 0 else 0
        dist_tp1_pct = (tp1 - current) / (tp1 - entry) * 100 if tp1 != entry else 0
        dist_sl_pct = (current - sl) / (entry - sl) * 100 if entry != sl else 0
    else:
        current = ask  # on rachete au ask
        pnl_abs = entry - current
        pnl_r = pnl_abs / risk if risk != 0 else 0
        dist_tp1_pct = (current - tp1) / (entry - tp1) * 100 if entry != tp1 else 0
        dist_sl_pct = (sl - current) / (sl - entry) * 100 if sl != entry else 0

    return pnl_r, dist_tp1_pct, dist_sl_pct

# Stats globales des actifs
en_profit = 0
en_perte = 0
total_pnl_r = 0.0
total_pnl_r_win = 0.0
total_pnl_r_loss = 0.0
compteur_win = 0
compteur_loss = 0

actif_details = []
for s in active_sigs:
    pnl_r, dist_tp1, dist_sl = calc_pnl(s)
    total_pnl_r += pnl_r
    if pnl_r > 0:
        en_profit += 1
        total_pnl_r_win += pnl_r
        compteur_win += 1
    else:
        en_perte += 1
        total_pnl_r_loss += pnl_r
        compteur_loss += 1
    actif_details.append((s, pnl_r, dist_tp1, dist_sl))

print(f"\n  Trades actifs en profit : {en_profit}")
print(f"  Trades actifs en perte  : {en_perte}")
print(f"  Taux trades positifs    : {en_profit/len(active_sigs)*100:.1f}%")
print(f"  P&L total (en R)        : {total_pnl_r:+.2f}R")
print(f"  P&L moyen par trade     : {total_pnl_r/len(active_sigs):+.3f}R")
if compteur_win > 0:
    print(f"  P&L moyen des gagnants  : {total_pnl_r_win/compteur_win:+.3f}R")
if compteur_loss > 0:
    print(f"  P&L moyen des perdants  : {total_pnl_r_loss/compteur_loss:+.3f}R")

# Distribution du P&L
print(f"\n  Distribution du P&L (en R) :")
ranges = [(-100, -5), (-5, -2), (-2, -1), (-1, -0.5), (-0.5, -0.1), (-0.1, 0),
          (0, 0.1), (0.1, 0.5), (0.5, 1), (1, 2), (2, 5), (5, 100)]
for lo, hi in ranges:
    count = sum(1 for _, p, _, _ in actif_details if lo <= p < hi)
    if count > 0:
        bar = "#" * count
        print(f"    [{lo:>5.1f} - {hi:>5.1f}[ : {count:>3} {bar}")

# Top 5 meilleurs et pires actifs
actif_details.sort(key=lambda x: x[1], reverse=True)

print(f"\n  TOP 5 MEILLEURS P&L :")
print(f"  {'Symbol':<12} {'Dir':<6} {'Entry':>10} {'Current':>10} {'P&L(R)':>8} {'DistTP1%':>10} {'DistSL%':>10}")
print(f"  {'-'*66}")
for s, pnl_r, dtp, dsl in actif_details[:5]:
    cur = s.get("current_bid", 0) if s["direction"] == "bull" else s.get("current_ask", 0)
    print(f"  {s['symbol']:<12} {s['direction']:<6} {s['entry']:>10.4f} {cur:>10.4f} {pnl_r:>+8.2f}R {dtp:>9.1f}% {dsl:>9.1f}%")

print(f"\n  TOP 5 PIRE P&L :")
print(f"  {'Symbol':<12} {'Dir':<6} {'Entry':>10} {'Current':>10} {'P&L(R)':>8} {'DistTP1%':>10} {'DistSL%':>10}")
print(f"  {'-'*66}")
for s, pnl_r, dtp, dsl in actif_details[-5:]:
    cur = s.get("current_bid", 0) if s["direction"] == "bull" else s.get("current_ask", 0)
    print(f"  {s['symbol']:<12} {s['direction']:<6} {s['entry']:>10.4f} {cur:>10.4f} {pnl_r:>+8.2f}R {dtp:>9.1f}% {dsl:>9.1f}%")

# Proche de TP1 vs proche de SL
proche_tp1 = sum(1 for _, _, dtp, dsl in actif_details if dtp <= 20 and dtp >= 0)
proche_sl = sum(1 for _, _, dtp, dsl in actif_details if dsl <= 20 and dsl >= 0)
print(f"\n  Proches du TP1 (<=20% distance restante): {proche_tp1}")
print(f"  Proches du SL  (<=20% distance restante): {proche_sl}")

# Par symbole: P&L par actif
print(f"\n{'='*80}")
print(f"  DETAIL PAR SYMBOLE (actifs avec P&L)")
print(f"{'='*80}")
sym_pnl = {}
for s, pnl_r, _, _ in actif_details:
    sym = s["symbol"]
    if sym not in sym_pnl:
        sym_pnl[sym] = {"n":0, "sum":0.0, "pos":0, "neg":0}
    sym_pnl[sym]["n"] += 1
    sym_pnl[sym]["sum"] += pnl_r
    if pnl_r > 0: sym_pnl[sym]["pos"] += 1
    else: sym_pnl[sym]["neg"] += 1

print(f"  {'Symbol':<12} {'N':>3} {'Positifs':>8} {'Negatifs':>8} {'P&L Total':>10} {'P&L Moyen':>10}")
print(f"  {'-'*51}")
for sym, d in sorted(sym_pnl.items(), key=lambda x: x[1]["sum"], reverse=True):
    print(f"  {sym:<12} {d['n']:>3} {d['pos']:>8} {d['neg']:>8} {d['sum']:>+9.2f}R {d['sum']/d['n']:>+9.3f}R")

# --- ANNEXE : dernier signaux TP1 et SL ---
if tp1_sigs:
    print(f"\n{'='*80}")
    print(f"  DERNIER SIGNAL TP1")
    print(f"{'='*80}")
    s = tp1_sigs[-1]  # dernier
    plan = s.get("trade_plan", {})
    print(f"  {s['symbol']} | {s['action']} | Entry={s['entry']:.4f} | "
          f"TP1={plan.get('tp1',0):.4f} | RR1={plan.get('rr1',0):.2f}R | "
          f"Bid={s['current_bid']:.4f} Ask={s['current_ask']:.4f}")

if sl_sigs:
    print(f"\n{'='*80}")
    print(f"  DERNIER SIGNAL SL")
    print(f"{'='*80}")
    s = sl_sigs[-1]  # dernier
    plan = s.get("trade_plan", {})
    print(f"  {s['symbol']} | {s['action']} | Entry={s['entry']:.4f} | "
          f"SL={plan.get('sl',0):.4f} | RR1={plan.get('rr1',0):.2f}R | "
          f"Bid={s['current_bid']:.4f} Ask={s['current_ask']:.4f}")
