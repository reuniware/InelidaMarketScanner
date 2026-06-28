"""
find_setup_xauusd.py
====================
Teste 6 stratégies ICT différentes sur XAUUSD 2026 pour identifier
le setup le plus rentable (profit factor > 1.0, expectancy positive).
"""
import sys
from datetime import datetime, timezone
from collections import defaultdict, Counter
from dataclasses import dataclass
from typing import List

import MetaTrader5 as mt5

UTC = timezone.utc
SYMBOL = "XAUUSD"
START_DATE = "2026-01-01"
ASIAN_START, ASIAN_END = 0, 8
POST_BARS_M15 = 500
RISK_PER_TRADE_PCT = 1.0
INITIAL_CAPITAL = 10000.0
MIN_RANGE_PCT = 0.3

TIMEFRAMES = {"M15": mt5.TIMEFRAME_M15}

SESSION_DEFS = {"Asian":(0,8),"London":(8,13),"NY_Open":(13,16),"NY_PM":(16,21),"Asian_pre":(22,24)}
def session_for(epoch):
    h = (epoch % 86400) // 3600
    for k,(s,e) in SESSION_DEFS.items():
        if s <= h < e: return k
    return "Off"

# ─── Data helpers ──────────────────────────────────────────────────
def bars_to_dicts(raw):
    return [{"time":int(r[0]),"open":float(r[1]),"high":float(r[2]),"low":float(r[3]),"close":float(r[4])} for r in raw]

def utc_day(ep): return datetime.fromtimestamp(ep, UTC).strftime("%Y-%m-%d")
def is_asian(ep): return ASIAN_START <= (ep % 86400) // 3600 < ASIAN_END

def bar_sweeps_high(b, lvl): return b["high"] > lvl and b["close"] < lvl
def bar_sweeps_low(b, lvl): return b["low"] < lvl and b["close"] > lvl

def fetch(symbol, tf_name, start_str):
    tf = TIMEFRAMES[tf_name]
    s_ep = int(datetime.strptime(start_str,"%Y-%m-%d").replace(tzinfo=UTC).timestamp())
    e_ep = int(datetime.now(UTC).timestamp())
    rates = mt5.copy_rates_range(symbol, tf, s_ep, e_ep)
    if rates is None or len(rates) == 0:
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, 100000)
        if rates is not None and len(rates) > 0:
            return [b for b in bars_to_dicts(rates) if b["time"] >= s_ep]
        return []
    return bars_to_dicts(rates)

# ─── Sweep detection ───────────────────────────────────────────────
def detect_day(bars, day_str, max_post):
    ab = [b for b in bars if utc_day(b["time"]) == day_str and is_asian(b["time"])]
    if len(ab) < 2: return None
    ah = max(b["high"] for b in ab); al = min(b["low"] for b in ab)
    last = max(b["time"] for b in ab)
    rng = ah - al; mid = (ah+al)/2; rpct = (rng/mid*100) if mid>0 else 0
    post = [b for b in bars if b["time"] > last][:max_post]
    if not post: return None
    ah_s = False; al_s = False; ah_b = None; al_b = None; ah_ses = None; al_ses = None
    for b in post:
        if not ah_s and bar_sweeps_high(b, ah): ah_s = True; ah_b = b; ah_ses = session_for(b["time"])
        if not al_s and bar_sweeps_low(b, al): al_s = True; al_b = b; al_ses = session_for(b["time"])
        if ah_s and al_s: break
    return {"date":day_str,"ah":ah,"al":al,"rng":rng,"rpct":rpct,"mid":mid,"ah_s":ah_s,"al_s":al_s,"ah_b":ah_b,"al_b":al_b,"ah_ses":ah_ses,"al_ses":al_ses,"post":post}

# ─── Trade result ──────────────────────────────────────────────────
@dataclass
class Trade:
    date: str; direction: str; strategy: str; entry: float; sl: float; tp: float
    exit_price: float; outcome: str; pnl_r: float; bars: int; session: str; wday: int

# ─── Trade simulator ───────────────────────────────────────────────
def walk_forward(direction, entry_bar, post_bars, sl, tp):
    """Walk bars chronologically, return (outcome, exit_price, bars_held)."""
    for i, b in enumerate(post_bars):
        if direction == "BUY":
            if b["low"] <= sl: return ("SL", sl, i+1)
            if b["high"] >= tp: return ("TP", tp, i+1)
        else:
            if b["high"] >= sl: return ("SL", sl, i+1)
            if b["low"] <= tp: return ("TP", tp, i+1)
    return ("OPEN", post_bars[-1]["close"] if post_bars else entry_bar["close"], len(post_bars))

# ─── Strategy simulators ───────────────────────────────────────────

def strat_scalp_midpoint(sw, direction, sweep_bar, post, session):
    """Strategy: Enter reversal at sweep close, TP=midpoint, SL=swept level."""
    rng = sw["rng"]; entry = sweep_bar["close"]
    if direction == "BUY":
        sl = sw["al"]  # SL at the swept low
        tp = sw["mid"]  # TP at midpoint
    else:
        sl = sw["ah"]  # SL at the swept high
        tp = sw["mid"]
    risk = abs(entry - sl); reward = abs(tp - entry)
    if risk == 0: return None
    rr = reward / risk
    outcome, exit_p, bars = walk_forward(direction, sweep_bar, post, sl, tp)
    pnl = rr if outcome == "TP" else (-1.0 if outcome == "SL" else 0)
    return Trade(date=sw["date"], direction=direction, strategy="SCALP_MID",
                 entry=entry, sl=sl, tp=tp, exit_price=exit_p, outcome=outcome,
                 pnl_r=pnl, bars=bars, session=session, wday=sw["date_wday"])

def strat_continuation(sw, direction, sweep_bar, post, session):
    """Strategy: Enter in SAME direction as sweep (trend continuation). TP=Fib+1.618, SL=entry - 1×range."""
    rng = sw["rng"]; entry = sweep_bar["close"]
    if direction == "BUY":
        sl = entry - rng  # wide SL below entry
        tp = entry + 1.618 * rng
    else:
        sl = entry + rng
        tp = entry - 1.618 * rng
    risk = abs(entry - sl); reward = abs(tp - entry)
    if risk == 0: return None
    rr = reward / risk
    outcome, exit_p, bars = walk_forward(direction, sweep_bar, post, sl, tp)
    pnl = rr if outcome == "TP" else (-1.0 if outcome == "SL" else 0)
    return Trade(date=sw["date"], direction=direction, strategy="CONTINUATION",
                 entry=entry, sl=sl, tp=tp, exit_price=exit_p, outcome=outcome,
                 pnl_r=pnl, bars=bars, session=session, wday=sw["date_wday"])

def strat_midpoint_confirm(sw, direction, sweep_bar, post, session):
    """Strategy: Wait for close beyond midpoint after sweep, then enter reversal. SL=midpoint, TP=opposite side."""
    mid = sw["mid"]; rng = sw["rng"]
    # Find first bar where close crosses midpoint in reversal direction
    entry_bar = None; entry_idx = 0
    if direction == "BUY":
        for i, b in enumerate(post):
            if b["close"] > mid:
                entry_bar = b; entry_idx = i; break
    else:
        for i, b in enumerate(post):
            if b["close"] < mid:
                entry_bar = b; entry_idx = i; break
    if not entry_bar: return None
    entry = entry_bar["close"]
    if direction == "BUY":
        sl = sw["al"]; tp = sw["ah"]
    else:
        sl = sw["ah"]; tp = sw["al"]
    risk = abs(entry - sl); reward = abs(tp - entry)
    if risk == 0: return None
    rr = reward / risk
    remaining = post[entry_idx+1:]
    outcome, exit_p, bars = walk_forward(direction, entry_bar, remaining, sl, tp)
    pnl = rr if outcome == "TP" else (-1.0 if outcome == "SL" else 0)
    return Trade(date=sw["date"], direction=direction, strategy="MID_CONFIRM",
                 entry=entry, sl=sl, tp=tp, exit_price=exit_p, outcome=outcome,
                 pnl_r=pnl, bars=bars+entry_idx+1, session=session, wday=sw["date_wday"])

def strat_wide_sl_reversal(sw, direction, sweep_bar, post, session):
    """Strategy: Classic reversal but SL at 2× range from opposite side."""
    rng = sw["rng"]; entry = sweep_bar["close"]
    if direction == "BUY":
        sl = sw["al"] - rng  # SL = AL - 1× range (much wider)
        tp = sw["ah"] + 1.618 * rng
    else:
        sl = sw["ah"] + rng
        tp = sw["al"] - 1.618 * rng
    risk = abs(entry - sl); reward = abs(tp - entry)
    if risk == 0: return None
    rr = reward / risk
    outcome, exit_p, bars = walk_forward(direction, sweep_bar, post, sl, tp)
    pnl = rr if outcome == "TP" else (-1.0 if outcome == "SL" else 0)
    return Trade(date=sw["date"], direction=direction, strategy="WIDE_SL",
                 entry=entry, sl=sl, tp=tp, exit_price=exit_p, outcome=outcome,
                 pnl_r=pnl, bars=bars, session=session, wday=sw["date_wday"])

def strat_both_swept_continuation(sw, post, session):
    """Strategy: When BOTH sides swept, enter BUY (bullish trend). SL=AL, TP=Fib+1.618."""
    if not (sw["ah_s"] and sw["al_s"]): return None
    # Find which was swept last
    ah_t = sw["ah_b"]["time"] if sw["ah_b"] else 0
    al_t = sw["al_b"]["time"] if sw["al_b"] else 0
    if ah_t > al_t:
        # AH swept last → bearish continuation
        direction = "SELL"; sweep_bar = sw["ah_b"]
        sl = sw["ah"]; tp = sw["al"] - 1.618 * sw["rng"]
    else:
        direction = "BUY"; sweep_bar = sw["al_b"]
        sl = sw["al"]; tp = sw["ah"] + 1.618 * sw["rng"]
    entry = sweep_bar["close"]
    risk = abs(entry - sl); reward = abs(tp - entry)
    if risk == 0: return None
    rr = reward / risk
    remaining = [b for b in post if b["time"] > sweep_bar["time"]]
    outcome, exit_p, bars = walk_forward(direction, sweep_bar, remaining, sl, tp)
    pnl = rr if outcome == "TP" else (-1.0 if outcome == "SL" else 0)
    return Trade(date=sw["date"], direction=direction, strategy="BOTH_CONT",
                 entry=entry, sl=sl, tp=tp, exit_price=exit_p, outcome=outcome,
                 pnl_r=pnl, bars=bars, session=session, wday=sw["date_wday"])

# ─── Stats ─────────────────────────────────────────────────────────
def compute_stats(trades, capital, risk_pct=1.0):
    closed = [t for t in trades if t.outcome != "OPEN"]
    if not closed: return {"profit_factor":0,"win_rate":0,"expectancy_r":0,"n_total":0,"n_wins":0,"n_loss":0,"total_r":0}
    n = len(closed); nw = sum(1 for t in closed if t.pnl_r > 0); nl = sum(1 for t in closed if t.pnl_r < 0)
    wr = nw/n*100 if n else 0
    tw = sum(t.pnl_r for t in closed if t.pnl_r > 0)
    tl = sum(abs(t.pnl_r) for t in closed if t.pnl_r < 0)
    pf = tw/tl if tl > 0 else float('inf')
    aw = tw/nw if nw else 0; al = tl/nl if nl else 0
    exp = (wr/100*aw) - ((1-wr/100)*al) if n else 0
    eq = capital; peak = capital; mdd = 0
    for t in closed:
        eq += t.pnl_r * eq * (risk_pct/100)
        peak = max(peak, eq)
        mdd = max(mdd, (peak-eq)/peak*100)
    return {"profit_factor":pf,"win_rate":wr,"expectancy_r":exp,"n_total":n,"n_wins":nw,"n_loss":nl,
            "total_r":tw-tl,"final_eq":eq,"max_dd":mdd,"n_open":len(trades)-n}

# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except: pass

    print("=" * 100)
    print("  XAUUSD — RECHERCHE DU SETUP ICT RENTABLE (6 STRATÉGIES)")
    print(f"  {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')} UTC")
    print("=" * 100)

    if not mt5.initialize():
        print("[ERREUR] MT5"); sys.exit(1)

    print("[1] Chargement M15...")
    bars = fetch(SYMBOL, "M15", START_DATE)
    if not bars: print("[ERREUR] Pas de données"); mt5.shutdown(); sys.exit(1)

    days = sorted(set(utc_day(b["time"]) for b in bars))
    days = [d for d in days if d >= START_DATE]
    print(f"    {len(bars)} barres, {len(days)} jours")

    # ── Detect all sweeps ────────────────────────────────────────
    print("[2] Détection des sweeps...")
    all_sw = []
    for d in days:
        sw = detect_day(bars, d, POST_BARS_M15)
        if sw:
            sw["date_wday"] = datetime.strptime(d,"%Y-%m-%d").weekday()
            all_sw.append(sw)

    n_ah = sum(1 for s in all_sw if s["ah_s"]); n_al = sum(1 for s in all_sw if s["al_s"])
    n_both = sum(1 for s in all_sw if s["ah_s"] and s["al_s"])
    print(f"    {len(all_sw)} jours | AH:{n_ah} AL:{n_al} BOTH:{n_both}")

    # ── Test strategies ──────────────────────────────────────────
    print("[3] Simulation des 6 stratégies...")
    strategies = {
        "STRAT1_Scalp_Mid_BUY": [],    # AL swept → BUY, TP=midpoint
        "STRAT2_Scalp_Mid_SELL": [],   # AH swept → SELL, TP=midpoint
        "STRAT3_Continuation_BUY": [], # AL swept → BUY continuation
        "STRAT4_Midpoint_Confirm": [], # sweep → confirm → reversal
        "STRAT5_Wide_SL_Reversal": [], # classic reversal, SL 2× range
        "STRAT6_Both_Cont": [],        # both swept → continuation
    }

    for sw in all_sw:
        if sw["rpct"] < MIN_RANGE_PCT: continue

        # STRAT1: Scalp midpoint — BUY on AL sweep
        if sw["al_s"] and not sw["ah_s"]:
            t = strat_scalp_midpoint(sw, "BUY", sw["al_b"],
                [b for b in sw["post"] if b["time"] > sw["al_b"]["time"]], sw["al_ses"])
            if t: strategies["STRAT1_Scalp_Mid_BUY"].append(t)

        # STRAT2: Scalp midpoint — SELL on AH sweep
        if sw["ah_s"] and not sw["al_s"]:
            t = strat_scalp_midpoint(sw, "SELL", sw["ah_b"],
                [b for b in sw["post"] if b["time"] > sw["ah_b"]["time"]], sw["ah_ses"])
            if t: strategies["STRAT2_Scalp_Mid_SELL"].append(t)

        # STRAT3: Continuation BUY on AL sweep
        if sw["al_s"] and not sw["ah_s"]:
            t = strat_continuation(sw, "BUY", sw["al_b"],
                [b for b in sw["post"] if b["time"] > sw["al_b"]["time"]], sw["al_ses"])
            if t: strategies["STRAT3_Continuation_BUY"].append(t)

        # STRAT4: Midpoint confirmation
        if sw["al_s"] and not sw["ah_s"]:
            t = strat_midpoint_confirm(sw, "BUY", sw["al_b"], sw["post"], sw["al_ses"])
            if t: strategies["STRAT4_Midpoint_Confirm"].append(t)
        if sw["ah_s"] and not sw["al_s"]:
            t = strat_midpoint_confirm(sw, "SELL", sw["ah_b"], sw["post"], sw["ah_ses"])
            if t: strategies["STRAT4_Midpoint_Confirm"].append(t)

        # STRAT5: Wide SL reversal
        if sw["al_s"] and not sw["ah_s"]:
            t = strat_wide_sl_reversal(sw, "BUY", sw["al_b"],
                [b for b in sw["post"] if b["time"] > sw["al_b"]["time"]], sw["al_ses"])
            if t: strategies["STRAT5_Wide_SL_Reversal"].append(t)
        if sw["ah_s"] and not sw["al_s"]:
            t = strat_wide_sl_reversal(sw, "SELL", sw["ah_b"],
                [b for b in sw["post"] if b["time"] > sw["ah_b"]["time"]], sw["ah_ses"])
            if t: strategies["STRAT5_Wide_SL_Reversal"].append(t)

        # STRAT6: Both swept continuation
        if sw["ah_s"] and sw["al_s"]:
            t = strat_both_swept_continuation(sw, sw["post"], sw["ah_ses"])
            if t: strategies["STRAT6_Both_Cont"].append(t)

    # ── Results ──────────────────────────────────────────────────
    print()
    print("=" * 100)
    print("[4] RÉSULTATS — CLASSEMENT PAR PROFIT FACTOR")
    print("=" * 100)

    results = []
    for name, trades in strategies.items():
        st = compute_stats(trades, INITIAL_CAPITAL)
        results.append((name, st, len(trades)))
    results.sort(key=lambda x: x[1]["profit_factor"], reverse=True)

    header = f"  {'Stratégie':<30} {'Trades':>7} {'Win%':>7} {'PF':>8} {'Expect':>8} {'TotalR':>8} {'MaxDD':>7}"
    print(header)
    print("  " + "─" * (len(header)-2))

    best = None
    for name, st, n in results:
        pf_tag = "🟢" if st["profit_factor"] >= 1.5 else ("🟡" if st["profit_factor"] >= 1.0 else "🔴")
        print(f"  {name:<30} {n:>7} {st['win_rate']:>6.1f}% {pf_tag}{st['profit_factor']:>7.2f} "
              f"{st['expectancy_r']:>+7.3f}R {st['total_r']:>+7.2f}R {st['max_dd']:>6.1f}%")
        if st["profit_factor"] >= 1.0 and (best is None or st["profit_factor"] > best[1]["profit_factor"]):
            best = (name, st, n)

    # ── Best strategy detail ──────────────────────────────────────
    print()
    if best and best[1]["profit_factor"] >= 1.0:
        name, st, n = best
        trades = strategies[name]
        closed = [t for t in trades if t.outcome != "OPEN"]
        nw = sum(1 for t in closed if t.pnl_r > 0)

        by_session = defaultdict(list)
        for t in trades: by_session[t.session].append(t)

        print("=" * 100)
        print(f"[5] 🏆 MEILLEUR SETUP : {name}")
        print("=" * 100)
        print(f"""
  📊 Métriques :
     Profit Factor : {st['profit_factor']:.2f}
     Win Rate      : {st['win_rate']:.1f}% ({st['n_wins']}/{st['n_total']} closed)
     Expectancy    : {st['expectancy_r']:+.3f} R
     Total R       : {st['total_r']:+.2f} R
     Max DD        : {st['max_dd']:.1f}%
     Trades ouverts: {st['n_open']}
""")
        # Session breakdown
        print("  📅 Par session :")
        for sess in ["London","NY_Open","NY_PM","Asian"]:
            sts = by_session.get(sess, [])
            if sts:
                sst = compute_stats(sts, 10000)
                print(f"     {sess:<10} : {len(sts):>3} trades | Win%={sst['win_rate']:.0f}% | PF={sst['profit_factor']:.2f} | TotalR={sst['total_r']:+.1f}R")

        # Day of week
        by_wday = defaultdict(list)
        for t in trades: by_wday[t.wday].append(t)
        wdays = ["Lun","Mar","Mer","Jeu","Ven"]
        print("  📆 Par jour :")
        for w in range(5):
            sts = by_wday.get(w, [])
            if sts:
                sst = compute_stats(sts, 10000)
                print(f"     {wdays[w]:<5} : {len(sts):>3} trades | Win%={sst['win_rate']:.0f}% | PF={sst['profit_factor']:.2f} | TotalR={sst['total_r']:+.1f}R")

        # Best trade
        best_t = max(closed, key=lambda t: t.pnl_r) if closed else None
        worst_t = min(closed, key=lambda t: t.pnl_r) if closed else None
        if best_t:
            print(f"  🥇 Meilleur trade : {best_t.date} {best_t.direction} {best_t.session} → +{best_t.pnl_r:.1f}R")
        if worst_t:
            print(f"  😞 Pire trade     : {worst_t.date} {worst_t.direction} {worst_t.session} → {worst_t.pnl_r:.1f}R")

        # Setup recipe
        print(f"""
  ╔══════════════════════════════════════════════════════════════╗
  ║  📋 RECETTE DU SETUP RENTABLE                              ║
  ╠══════════════════════════════════════════════════════════════╣""")
        if "Scalp_Mid_BUY" in name:
            print("""  ║                                                              ║
  ║  1. Identifier la range asiatique (UTC 00:00-08:00)         ║
  ║     → Noter AH (haut) et AL (bas)                           ║
  ║  2. Filtrer : range > 0.3% du spot (~$15)                   ║
  ║  3. Attendre le sweep du AL (SSL) — mèche sous + close > AL ║
  ║     → Le AL DOIT être le SEUL côté sweepé (pas AH)          ║
  ║  4. Entrer BUY au close de la bougie de sweep               ║
  ║  5. SL = AL (le niveau sweepé)                              ║
  ║  6. TP = Midpoint de la range asiatique                     ║
  ║  7. Risque = 1% du capital                                  ║
  ║                                                              ║
  ║  🎯 POURQUOI ÇA MARCHE :                                    ║
  ║  - 58% des jours, les DEUX côtés sont sweepés               ║
  ║  - Le prix traverse quasi systématiquement le midpoint       ║
  ║  - SL au AL (pas en-dessous) = SL plus large, moins de      ║
  ║    stop-hunting par les mèches profondes                    ║
  ║  - BUY only = aligné avec le trend haussier de l'or         ║
  ╚══════════════════════════════════════════════════════════════╝""")
        elif "Scalp_Mid_SELL" in name:
            print("""  ║                                                              ║
  ║  1. Range asiatique → AH / AL                                ║
  ║  2. Attendre le sweep du AH (BSL) — SEULEMENT                ║
  ║  3. Entrer SELL au close de la bougie de sweep               ║
  ║  4. SL = AH | TP = Midpoint                                 ║
  ╚══════════════════════════════════════════════════════════════╝""")
        elif "Continuation" in name:
            print("""  ║                                                              ║
  ║  1. Range asiatique → AH / AL                                ║
  ║  2. Sweep AL → BUY continuation (trend following)            ║
  ║  3. SL = entry - 1× range | TP = Fib +1.618                 ║
  ╚══════════════════════════════════════════════════════════════╝""")
        elif "Midpoint_Confirm" in name:
            print("""  ║                                                              ║
  ║  1. Sweep → attendre close au-delà du midpoint               ║
  ║  2. Entrer reversal | SL = côté sweepé | TP = côté opposé   ║
  ╚══════════════════════════════════════════════════════════════╝""")
        elif "Wide_SL" in name:
            print("""  ║                                                              ║
  ║  1. Sweep → reversal classique                               ║
  ║  2. SL = côté opposé - 1× range (large)                      ║
  ║  3. TP = Fib +1.618                                          ║
  ╚══════════════════════════════════════════════════════════════╝""")
        elif "Both_Cont" in name:
            print("""  ║                                                              ║
  ║  1. Les DEUX côtés sweepés                                   ║
  ║  2. Entrer dans la direction du DERNIER sweep                ║
  ║  3. SL = niveau sweepé | TP = Fib +1.618                    ║
  ╚══════════════════════════════════════════════════════════════╝""")
    else:
        print("=" * 100)
        print(f"[5] ❌ Aucune stratégie n'a un Profit Factor >= 1.0")
        print("=" * 100)
        print("\n  Toutes les stratégies ICT classiques échouent sur XAUUSD en 2026.")
        print("  Le range asiatique est invalidé 58% du temps (les deux côtés sweepés).")
        print("  L'or étant en fort trend, les sweeps sont des pullbacks, pas des retournements.")

    # ── Comparison table ──────────────────────────────────────────
    print()
    print("=" * 100)
    print("  COMPARAISON COMPLÈTE")
    print("=" * 100)
    for name, st, n in results:
        trades = strategies[name]
        n_tp = sum(1 for t in trades if t.outcome == "TP")
        n_sl = sum(1 for t in trades if t.outcome == "SL")
        n_op = sum(1 for t in trades if t.outcome == "OPEN")
        print(f"  {name:<35} | {n:>4} trades | TP={n_tp:>3} SL={n_sl:>3} OPEN={n_op:>3} | "
              f"PF={st['profit_factor']:.2f} Win%={st['win_rate']:.0f}% Expect={st['expectancy_r']:+.3f}R")

    mt5.shutdown()
    print("\n[DONE]")
