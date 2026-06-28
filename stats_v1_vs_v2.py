"""
stats_v1_vs_v2.py
=================
Analyse complete : stats V1 vs V2 + etat des trades ouverts + P&L total
simule avec 0.01 lot, incluant les trades clos ET ouverts.
"""

import json, os, sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RESULTS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "reports", "backtest_all_results.json"
)

# ==================== Critères ====================
# V1 (original) : 09:00-10:30, RR>=0.5, spread<0.10, USD+INDEX+METAL+CROSS
# V2 (optimise)  : 09:00-13:00, RR>=0.0, spread<0.50, USD+INDEX+METAL

V1_TYPES = {"FOREX_USD", "INDEX", "METAL", "FOREX_CROSS"}
V2_TYPES = {"FOREX_USD", "INDEX", "METAL"}

def passes_filter(t, start_h, start_m, end_h, end_m, min_rr, max_spread, allowed_types):
    hour = t.get("scan_hour")
    if hour is not None:
        in_window = (
            (hour > start_h or (hour == start_h))
            and (hour < end_h or (hour == end_h))
        )
        if not in_window:
            return False
    sym_type = t.get("sym_type", "")
    if sym_type not in allowed_types:
        return False
    rr = t.get("rr", 0) or 0
    if rr < min_rr:
        return False
    spread = t.get("spread_pct")
    if spread is not None and spread >= max_spread:
        return False
    return True

def passes_v1(t):
    return passes_filter(t, 9, 0, 10, 30, 0.5, 0.10, V1_TYPES)

def passes_v2(t):
    return passes_filter(t, 9, 0, 13, 0, 0.0, 0.50, V2_TYPES)

# ==================== Chargement ====================
with open(RESULTS_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

all_trades = data["all_trades"]
print("=" * 120)
print("  STATISTIQUES COMPLETES ELITE V1 vs V2")
print("=" * 120)
print()

# ==================== 1. Stats V1 vs V2 ====================
print("─" * 80)
print("  1. REPARTITION V1 vs V2 SUR LES 438 TRADES")
print("─" * 80)
print()

cats = {"V1 uniquement": 0, "V2 uniquement": 0, "Les deux": 0, "Aucun": 0}
cat_trades = {"V1 uniquement": [], "V2 uniquement": [], "Les deux": [], "Aucun": []}

for t in all_trades:
    v1 = passes_v1(t)
    v2 = passes_v2(t)
    if v1 and v2:
        cats["Les deux"] += 1
        cat_trades["Les deux"].append(t)
    elif v1:
        cats["V1 uniquement"] += 1
        cat_trades["V1 uniquement"].append(t)
    elif v2:
        cats["V2 uniquement"] += 1
        cat_trades["V2 uniquement"].append(t)
    else:
        cats["Aucun"] += 1
        cat_trades["Aucun"].append(t)

print(f"  {'Categorie':<25s} {'Nb trades':>10s} {'% des 438':>10s} {'WR clos':>10s}")
print(f"  {'-'*55}")
for cat in ["Les deux", "V1 uniquement", "V2 uniquement", "Aucun"]:
    n = cats[cat]
    pct = n / 438 * 100
    closed = [t for t in cat_trades[cat] if t["outcome"] in ("GAGNE", "PERDU")]
    won = sum(1 for t in closed if t["outcome"] == "GAGNE")
    wr = f"{won/len(closed)*100:.1f}%" if closed else "N/A"
    print(f"  {cat:<25s} {n:>10d} {pct:>9.1f}% {wr:>10s}")
print()

# Winrates par outcome
for cat in ["Les deux", "V1 uniquement", "V2 uniquement", "Aucun"]:
    trades = cat_trades[cat]
    by_outcome = Counter(t["outcome"] for t in trades)
    g = by_outcome.get("GAGNE", 0)
    p = by_outcome.get("PERDU", 0)
    o = by_outcome.get("OUVERT", 0)
    i = by_outcome.get("INDETERMINE", 0)
    c = g + p
    wr = g / c * 100 if c > 0 else 0
    print(f"  {cat:<25s} Total:{len(trades):>3d}  G:{g:>3d}  P:{p:>3d}  O:{o:>3d}  I:{i:>2d}  "
          f"WR:{wr:>5.1f}%  (clos:{c})")

print()

# ==================== 2. Details V2 trades ====================
v2_trades = [t for t in all_trades if passes_v2(t)]
print("─" * 80)
print(f"  2. DETAIL DES {len(v2_trades)} TRADES ELITE V2")
print("─" * 80)
print()

by_outcome_v2 = Counter(t["outcome"] for t in v2_trades)
closed_v2 = [t for t in v2_trades if t["outcome"] in ("GAGNE", "PERDU")]
won_v2 = [t for t in closed_v2 if t["outcome"] == "GAGNE"]
lost_v2 = [t for t in closed_v2 if t["outcome"] == "PERDU"]
open_v2 = [t for t in v2_trades if t["outcome"] == "OUVERT"]

print(f"  Total V2: {len(v2_trades)}")
print(f"  GAGNE: {len(won_v2)}  PERDU: {len(lost_v2)}  OUVERT: {len(open_v2)}")
if closed_v2:
    print(f"  Winrate (clos): {len(won_v2)/len(closed_v2)*100:.1f}% ({len(won_v2)}/{len(closed_v2)})")
print()

# ==================== 3. Etat des trades ouverts ====================
print("─" * 80)
print(f"  3. ETAT DES {len(open_v2)} TRADES OUVERTS")
print("─" * 80)
print()

if open_v2:
    # Analyser la direction de chaque trade ouvert
    toward_tp = 0
    toward_sl = 0
    neutral = 0
    no_data = 0
    total_pnl_r = 0.0
    
    for t in open_v2:
        pnl = t.get("pnl_pct", 0) or 0
        total_pnl_r += pnl
        
        last_close = t.get("last_bar_close")
        entry = t.get("entry")
        sl = t.get("sl")
        tp = t.get("tp")
        action = t.get("action")
        
        if last_close is not None and entry is not None and sl is not None:
            if action == "BUY":
                dist_sl = entry - sl
                current_dist = last_close - entry
                pct_to_sl = abs(current_dist) / dist_sl * 100 if dist_sl > 0 else 0
                if current_dist < 0:  # vers SL
                    toward_sl += 1
                else:
                    toward_tp += 1 if isinstance(tp, (int,float)) and tp > entry and current_dist / (tp-entry)*100 > 50 else 0
                    toward_tp += 0  # simplified
            elif action == "SELL":
                dist_sl = sl - entry
                current_dist = entry - last_close
                pct_to_sl = abs(current_dist) / dist_sl * 100 if dist_sl > 0 else 0
                if current_dist < 0:  # vers SL
                    toward_sl += 1
                else:
                    toward_tp += 0
        
        # Re-classification simplifiee basee sur pnl_pct
        # Si pnl_pct < 0 => en drawdown
        pass
    
    # Utilisons plutot pnl_pct comme indicateur
    pos_open = sum(1 for t in open_v2 if (t.get("pnl_pct") or 0) > 0)
    neg_open = sum(1 for t in open_v2 if (t.get("pnl_pct") or 0) < 0)
    zero_open = sum(1 for t in open_v2 if (t.get("pnl_pct") or 0) == 0)
    
    print(f"  Signe du P&L au dernier check M1 :")
    print(f"    Positifs (vers TP):  {pos_open:>3d} / {len(open_v2):>3d}")
    print(f"    Negatifs (vers SL):  {neg_open:>3d} / {len(open_v2):>3d}")
    print(f"    Neutres:             {zero_open:>3d} / {len(open_v2):>3d}")
    print()
    
    # Top 3 plus positifs et plus negatifs
    sorted_open = sorted(open_v2, key=lambda t: t.get("pnl_pct", 0) or 0)
    print(f"  TOP 3 PIRE trades ouverts (P&L le plus negatif) :")
    for t in sorted_open[:3]:
        print(f"    {t['symbol']:<16s} {t['action']:>4s} Entry={t['entry']:<10.4f} "
              f"P&L={t.get('pnl_pct',0):+.3f}R")
    
    print(f"  TOP 3 MEILLEUR trades ouverts (P&L le plus positif) :")
    for t in reversed(sorted_open[-3:]):
        if t.get("pnl_pct", 0) > 0:
            print(f"    {t['symbol']:<16s} {t['action']:>4s} Entry={t['entry']:<10.4f} "
                  f"P&L={t.get('pnl_pct',0):+.3f}R")
    print()
    
    print(f"  P&L total des trades ouverts: {total_pnl_r:+.3f}R")
    print(f"  (negatif = drawdown collectif au dernier check)")
print()

# ==================== 4. P&L total avec MT5 ====================
print("─" * 80)
print("  4. CALCUL P&L TOTAL (CLOS + OUVERTS) VIA MT5")
print("─" * 80)
print()

import MetaTrader5 as mt5

if not mt5.initialize():
    print("  [ERREUR] Connexion MT5 impossible")
    sys.exit(1)

# Taux EURUSD
tick = mt5.symbol_info_tick("EURUSD")
eurusd = tick.bid if tick else 1.14
print(f"  EUR/USD: {eurusd:.5f}")
print()

LOTS = 0.01
total_pnl_eur = 0.0
total_risk_eur = 0.0
n_ok = 0
n_err = 0

# Stats detailles
closed_pnl_eur = 0.0
open_pnl_eur = 0.0
closed_risk_eur = 0.0
open_risk_eur = 0.0
n_closed_ok = 0
n_open_ok = 0

print(f"  {'#':>3s} {'Symbole':<16s} {'Outcome':<12s} {'P&L(R)':>8s} {'P&L(EUR)':>10s} {'Risk(EUR)':>10s}")
print(f"  {'-'*65}")

for i, t in enumerate(v2_trades):
    sym = t["symbol"]
    action = t["action"]
    entry = t["entry"]
    sl = t["sl"]
    pnl_r = t.get("pnl_pct", 0) or 0
    outcome = t["outcome"]
    
    if outcome == "INDETERMINE":
        continue
    
    try:
        info = mt5.symbol_info(sym)
        if info is None:
            n_err += 1
            continue
        
        contract = info.trade_contract_size
        currency_profit = info.currency_profit
        
        sl_dist = abs(entry - sl)
        if sl_dist == 0:
            n_err += 1
            continue
        
        # Risk en devise de cotation
        risk_quote = LOTS * contract * sl_dist
        
        # Conversion EUR
        if currency_profit == "EUR":
            risk_eur = risk_quote
            pnl_eur = risk_quote * pnl_r
        elif currency_profit == "USD":
            risk_eur = risk_quote / eurusd
            pnl_eur = risk_quote * pnl_r / eurusd
        elif currency_profit == "JPY":
            tj = mt5.symbol_info_tick("USDJPY")
            usdjpy = tj.bid if tj else 114.0
            risk_eur = risk_quote / usdjpy / eurusd
            pnl_eur = risk_quote * pnl_r / usdjpy / eurusd
        else:
            risk_eur = risk_quote
            pnl_eur = risk_quote * pnl_r
        
        total_pnl_eur += pnl_eur
        total_risk_eur += risk_eur
        n_ok += 1
        
        if outcome in ("GAGNE", "PERDU"):
            closed_pnl_eur += pnl_eur
            closed_risk_eur += risk_eur
            n_closed_ok += 1
        elif outcome == "OUVERT":
            open_pnl_eur += pnl_eur
            open_risk_eur += risk_eur
            n_open_ok += 1
        
        print(f"  {n_ok:>3d} {sym:<16s} {outcome:<12s} {pnl_r:>+7.3f}R {pnl_eur:>+9.2f}e {risk_eur:>9.2f}e")
        
    except Exception as e:
        n_err += 1
        continue

mt5.shutdown()

print(f"  {'-'*65}")
print()

print(f"  Trades calcules avec succes: {n_ok}")
print(f"  Trades ignores (erreur): {n_err}")
print()

print("=" * 80)
print("  SYNTHESE GLOBALE")
print("=" * 80)
print()

print(f"  {'Trades ELITE V2':<35s} {n_ok:>8d}")
print(f"  {'  Dont GAGNE':<35s} {len(won_v2):>8d}")
print(f"  {'  Dont PERDU':<35s} {len(lost_v2):>8d}")
print(f"  {'  Dont OUVERT':<35s} {len(open_v2):>8d}")
if closed_v2:
    print(f"  {'WR (clos)':<35s} {len(won_v2)/len(closed_v2)*100:>7.1f}%")
print()

print(f"  {'P&L TRADES CLOS':-^60s}")
print(f"  {'P&L clos (EUR)':<35s} {closed_pnl_eur:>+9.2f}")
print(f"  {'Risque clos (EUR)':<35s} {closed_risk_eur:>9.2f}")
print(f"  {'Return on Risk (clos)':<35s} {closed_pnl_eur/closed_risk_eur*100 if closed_risk_eur else 0:>+7.1f}%")
print(f"  {'Moyen / trade clos':<35s} {closed_pnl_eur/n_closed_ok if n_closed_ok else 0:>+9.3f}")
print()

print(f"  {'P&L TRADES OUVERTS':-^60s}")
print(f"  {'P&L ouverts (EUR)':<35s} {open_pnl_eur:>+9.2f}")
print(f"  {'Risque ouverts (EUR)':<35s} {open_risk_eur:>9.2f}")
print(f"  {'Moyen / trade ouvert':<35s} {open_pnl_eur/n_open_ok if n_open_ok else 0:>+9.3f}")
print()

print(f"  {'P&L TOTAL (clos + ouverts)':-^60s}")
total = closed_pnl_eur + open_pnl_eur
print(f"  {'P&L total (EUR)':<35s} {total:>+9.2f}")
print(f"  {'Risque total engage (EUR)':<35s} {total_risk_eur:>9.2f}")
if total_risk_eur > 0:
    print(f"  {'Return on Risk total':<35s} {total/total_risk_eur*100:>+7.1f}%")
print()

# Estimation du compte final
capital_init = 10000.0  # hypothese compte demo FTMO
capital_final = capital_init + total
print(f"  {'COMPTE SIMULE (10000 EUR initial)':-^60s}")
print(f"  {'Capital initial':<35s} {capital_init:>9.2f} EUR")
print(f"  {'P&L total':<35s} {total:>+9.2f} EUR")
print(f"  {'Capital final (estime)':<35s} {capital_final:>9.2f} EUR")
print(f"  {'Rendement total':<35s} {total/capital_init*100:>+7.1f}%")
print()

# Estimation par jour
n_days = len(set(t.get("report","") for t in all_trades))
print(f"  {'ESTIMATION TEMPORELLE':-^60s}")
print(f"  {'Nombre de jours':<35s} {n_days:>8d}")
print(f"  {'P&L / jour':<35s} {total/n_days:>+9.3f} EUR" if n_days else "")
print(f"  {'P&L / mois estime (21j)':<35s} {total/n_days*21:>+9.2f} EUR" if n_days else "")
print()

# Scenarios
print(f"  {'SCENARIOS POUR LES TRADES OUVERTS':-^60s}")
print()
for pct_loss in [0.0, 0.25, 0.50, 0.75, 1.0]:
    # On suppose que X% des trades ouverts finissent perdants (en moyenne -1R)
    # et que le reste finit gagnants (en moyenne +0.35R)
    n_open_real = n_open_ok
    n_lost_est = int(n_open_real * pct_loss)
    n_won_est = n_open_real - n_lost_est
    pnl_open_est = n_won_est * 0.35 * (total_risk_eur / n_ok) - n_lost_est * 1.0 * (total_risk_eur / n_ok)
    total_est = closed_pnl_eur + pnl_open_est
    capital_est = capital_init + total_est
    wr_closed = len(won_v2) / len(closed_v2) * 100 if closed_v2 else 0
    total_closed = len(closed_v2)
    total_est_wr = (len(won_v2) + n_won_est) / (total_closed + n_open_real) * 100
    
    print(f"  Scenario {pct_loss*100:3.0f}% perte sur ouverts:")
    print(f"    {n_lost_est:>3d} perdus / {n_won_est:>3d} gagnes sur {n_open_real} ouverts")
    print(f"    WR estime: {total_est_wr:.1f}%")
    print(f"    P&L total estime: {total_est:>+8.2f} EUR")
    print(f"    Capital final: {capital_est:>8.2f} EUR")
    print()
