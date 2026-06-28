#!/usr/bin/env python
"""
Backtest DEFAUT — Historique complet 01/01/2026 -> 26/06/2026
========================================================================
Simule un scan quotidien a 21:00 UTC (23:00 Paris ete, 22:00 Paris hiver),
apres fermeture NY. AUCUN filtre ELITE — toutes les setups valides
du detecteur de sweeps ICT sont backtestees.

Scan : 21:00 UTC (apres cloture NY)
Filtre : AUCUN (ni type, ni RR, ni spread)
Backtest : M5 (20000 barres, fallback M15)
"""

import os
import sys
import time
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

UTC = timezone.utc
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_DIR, "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

# --- Configuration DEFAUT --------------------------------------------------
SCAN_HOUR_UTC = 21       # 21:00 UTC = fin session NY
SCAN_MINUTE_UTC = 0
START_DATE = "2026-01-01"
END_DATE = "2026-06-26"

FIB_LEVELS_BULL = (1.618, 2.0, 2.618, 3.0, 3.618, 4.0)
FIB_LEVELS_BEAR = (-1.618, -2.0, -2.618, -3.0, -3.618, -4.0)

# --- Helpers ----------------------------------------------------------------

def classify_symbol(sym: str) -> str:
    sym_u = sym.upper()
    if sym_u in ('XAUUSD', 'XAGUSD', 'XAUAUD', 'XAGAUD'):
        return 'METAL'
    if sym_u.endswith('USD'):
        return 'FOREX_USD'
    if 'JPY' in sym_u:
        return 'FOREX_JPY'
    if sym_u.startswith('USD'):
        return 'FOREX_USD'
    if any(c in sym_u for c in ('EUR', 'GBP', 'CAD', 'AUD', 'NZD', 'CHF',
                                  'NOK', 'SEK', 'PLN', 'CZK', 'MXN', 'SGD', 'ZAR', 'HUF')):
        return 'FOREX_CROSS'
    if '.cash' in sym_u or sym_u in ('DXY.cash', 'GDAXI'):
        return 'INDEX'
    return 'OTHER'


def bars_to_dicts(rates_raw) -> List[dict]:
    out = []
    for r in rates_raw:
        out.append({
            "time": int(r[0]), "open": float(r[1]),
            "high": float(r[2]), "low": float(r[3]),
            "close": float(r[4]),
        })
    return out


def utc_hour(epoch: int) -> int:
    return (epoch % 86400) // 3600


def utc_day_str(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%d")


def bar_sweeps_high(bar: dict, level: float) -> bool:
    return bar["high"] > level and bar["close"] < level


def bar_sweeps_low(bar: dict, level: float) -> bool:
    return bar["low"] < level and bar["close"] > level


def session_for_hour(h: int) -> str:
    if 0 <= h < 8: return "Asian"
    if 8 <= h < 13: return "London"
    if 13 <= h < 21: return "NY"
    return "Off"


# ===========================================================================
# BACKTEST D'UN TRADE
# ===========================================================================

def backtest_trade(symbol: str, direction: str, entry: float, sl: float,
                   tp: float, scan_epoch: int) -> Tuple[str, float, str]:
    """Backteste un trade sur M5 (fallback M15) a partir de scan_epoch."""
    is_buy = direction == "BUY"

    for tf_name, tf_const, n_bars in [
        ("M5", mt5.TIMEFRAME_M5, 20000),
        ("M15", mt5.TIMEFRAME_M15, 8000),
    ]:
        try:
            rates = mt5.copy_rates_from_pos(symbol, tf_const, 0, n_bars)
            if rates is None or len(rates) == 0:
                continue
            bars = bars_to_dicts(rates)
            post = [b for b in bars if b["time"] > scan_epoch]
            post.sort(key=lambda b: b["time"])
            if not post:
                post = [b for b in bars if b["time"] >= scan_epoch]
                post.sort(key=lambda b: b["time"])
            if not post:
                continue

            for b in post:
                if is_buy:
                    if b["low"] <= sl:
                        return "PERDU", sl, tf_name
                    if b["high"] >= tp:
                        return "GAGNE", tp, tf_name
                else:
                    if b["high"] >= sl:
                        return "PERDU", sl, tf_name
                    if b["low"] <= tp:
                        return "GAGNE", tp, tf_name

            last = post[-1]
            return "OUVERT", last["close"], tf_name
        except Exception:
            continue

    return "NO_DATA", 0.0, "-"


# ===========================================================================
# ANALYSE D'UN SYMBOLE POUR UN JOUR DONNE
# ===========================================================================

def analyze_symbol_for_date(h1_bars: List[dict], symbol: str, date_str: str,
                             scan_epoch: int):
    """Analyse le range asiatique depuis les barres H1 en cache.
    Scan a 21:00 UTC -> beaucoup plus de barres post-Asian (London + NY)."""
    asian_bars = []
    post_bars_all = []
    for b in h1_bars:
        d = utc_day_str(b["time"])
        h = utc_hour(b["time"])
        if d == date_str:
            if 0 <= h < 8:
                asian_bars.append(b)
            elif h >= 8:
                post_bars_all.append(b)

    if len(asian_bars) < 2:
        return None

    asian_high = max(b["high"] for b in asian_bars)
    asian_low = min(b["low"] for b in asian_bars)
    range_size = asian_high - asian_low
    if range_size <= 0:
        return None

    # Sweeps post-Asian jusqu'a 21:00 UTC (London + NY inclus)
    post_bars = [b for b in post_bars_all if b["time"] <= scan_epoch]
    if not post_bars:
        return None

    high_swept = False; low_swept = False
    high_swept_at = None; low_swept_at = None
    high_swept_session = None; low_swept_session = None

    for b in post_bars:
        if not high_swept and bar_sweeps_high(b, asian_high):
            high_swept = True; high_swept_at = b["time"]
            high_swept_session = session_for_hour(utc_hour(b["time"]))
        if not low_swept and bar_sweeps_low(b, asian_low):
            low_swept = True; low_swept_at = b["time"]
            low_swept_session = session_for_hour(utc_hour(b["time"]))
        if high_swept and low_swept:
            break

    # Entry = close H1 a 21:00 UTC (ou derniere avant)
    entry_bars = [b for b in h1_bars if b["time"] <= scan_epoch and utc_day_str(b["time"]) == date_str]
    if not entry_bars:
        entry_bars = [b for b in h1_bars if b["time"] <= scan_epoch]
    if not entry_bars:
        return None
    entry_price = entry_bars[-1]["close"]

    # Direction ICT
    bull_base = asian_high
    bear_base = asian_low
    trade_action = None
    fib_state_val = ""

    if low_swept and entry_price > asian_high:
        trade_action = "BUY"
    elif high_swept and entry_price < asian_low:
        trade_action = "SELL"
    elif high_swept and low_swept:
        if entry_price > asian_high: trade_action = "BUY"
        elif entry_price < asian_low: trade_action = "SELL"
    elif high_swept and entry_price > asian_high:
        trade_action = "BUY"
    elif low_swept and entry_price < asian_low:
        trade_action = "SELL"

    if not trade_action:
        return None

    if trade_action == "BUY":
        for n in FIB_LEVELS_BULL:
            if entry_price < bull_base + n * range_size:
                fib_state_val = f"+{n}"
                break
    else:
        for n in FIB_LEVELS_BEAR:
            if entry_price > bear_base + n * range_size:
                fib_state_val = f"{n}"
                break

    midpoint = (asian_high + asian_low) / 2
    range_pct = range_size / midpoint * 100.0 if midpoint > 0 else 0
    if range_pct < 0.05:
        return None

    if trade_action == "BUY":
        trade_sl = asian_low - 0.10 * range_size
        try: fib_num = float(fib_state_val[1:])
        except: fib_num = 1.618
        idx = next((i for i, n in enumerate(FIB_LEVELS_BULL) if n >= fib_num - 0.001), 0)
        tp_candidates = FIB_LEVELS_BULL[idx:idx + 3]
        trade_tp1 = bull_base + tp_candidates[0] * range_size if len(tp_candidates) >= 1 else None
        if trade_tp1 is not None and trade_tp1 <= entry_price:
            if len(tp_candidates) >= 2:
                trade_tp1 = bull_base + tp_candidates[1] * range_size
            else:
                return None
        risk = entry_price - trade_sl
        trade_rr = (trade_tp1 - entry_price) / risk if risk > 0 and trade_tp1 else None
    else:
        trade_sl = asian_high + 0.10 * range_size
        try: fib_num = float(fib_state_val[1:])
        except: fib_num = 1.618
        idx = next((i for i, n in enumerate(FIB_LEVELS_BEAR) if n <= -fib_num + 0.001), 0)
        tp_candidates = FIB_LEVELS_BEAR[idx:idx + 3]
        trade_tp1 = bear_base + tp_candidates[0] * range_size if len(tp_candidates) >= 1 else None
        if trade_tp1 is not None and trade_tp1 >= entry_price:
            if len(tp_candidates) >= 2:
                trade_tp1 = bear_base + tp_candidates[1] * range_size
            else:
                return None
        risk = trade_sl - entry_price
        trade_rr = (entry_price - trade_tp1) / risk if risk > 0 and trade_tp1 else None

    if trade_tp1 is None or trade_rr is None or trade_rr <= 0:
        return None

    return {
        "symbol": symbol, "date": date_str, "action": trade_action,
        "entry": entry_price, "sl": trade_sl, "tp1": trade_tp1,
        "rr": trade_rr, "asian_high": asian_high, "asian_low": asian_low,
        "range": range_size, "fib_state": fib_state_val,
        "ah_swept": high_swept, "al_swept": low_swept,
        "ah_swept_at": high_swept_at, "al_swept_at": low_swept_at,
        "ah_swept_session": high_swept_session,
        "al_swept_session": low_swept_session,
        "scan_epoch": scan_epoch, "symbol_type": classify_symbol(symbol),
    }


# ===========================================================================
# MAIN
# ===========================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Backtest DEFAUT historique complet")
    parser.add_argument("--start", default=START_DATE, help=f"Date debut (defaut: {START_DATE})")
    parser.add_argument("--end", default=END_DATE, help=f"Date fin (defaut: {END_DATE})")
    parser.add_argument("--scan-hour", type=int, default=SCAN_HOUR_UTC, help=f"Heure UTC du scan (defaut: {SCAN_HOUR_UTC})")
    args = parser.parse_args()
    start_date = args.start
    end_date = args.end
    scan_hour = args.scan_hour

    print()
    print("=" * 90)
    print("  BACKTEST DEFAUT -- HISTORIQUE COMPLET")
    print(f"  Periode : {start_date} -> {end_date}")
    print(f"  Heure scan : {scan_hour:02d}:{SCAN_MINUTE_UTC:02d} UTC (fin NY)")
    print(f"  Filtre : AUCUN (tous types, tous RR)")
    print(f"  Backtest : M5 (20000 barres, fallback M15)")
    print("=" * 90)
    print()

    # --- Connexion MT5 --------------------------------------------------
    print("[1/6] Connexion MT5...")
    if not mt5.initialize():
        print("[ERREUR] Connexion MT5 echouee.")
        return 1
    ti = mt5.terminal_info()
    ai = mt5.account_info()
    if ti: print(f"  Terminal : {ti.name} (build {ti.build})")
    if ai: print(f"  Compte   : {ai.login} @ {ai.server}")
    print()

    # --- Symboles -------------------------------------------------------
    print("[2/6] Recuperation des symboles disponibles...")
    all_syms = mt5.symbols_get()
    if not all_syms:
        print("[ERREUR] Aucun symbole.")
        mt5.shutdown(); return 1
    symbols = sorted({s.name for s in all_syms})
    print(f"  {len(symbols)} symboles disponibles.")
    print()

    # --- Jours de trading ------------------------------------------------
    print("[3/6] Generation des jours de trading...")
    start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=UTC)
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=UTC)
    trading_days = []
    current = start_dt
    while current <= end_dt:
        if current.weekday() < 5:
            trading_days.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    print(f"  {len(trading_days)} jours de trading (lun-ven).")
    print()

    # --- Cache H1 --------------------------------------------------------
    print("[4/6] Chargement du cache H1 pour tous les symboles...")
    h1_cache = {}
    symbols_ok = []
    for i, sym in enumerate(symbols):
        try:
            rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 5000)
            if rates is not None and len(rates) > 0:
                bars = bars_to_dicts(rates)
                bars.sort(key=lambda b: b["time"])
                h1_cache[sym] = bars
                symbols_ok.append(sym)
        except Exception:
            pass
        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{len(symbols)} symboles...")
    print(f"  {len(h1_cache)}/{len(symbols)} symboles avec donnees H1.")
    print()

    # --- Scan quotidien + backtest ---------------------------------------
    print("[5/6] Scan quotidien a 21:00 UTC + backtest M5...")
    print()

    all_trades = []
    daily_stats = {}
    total_setups = 0

    for day_idx, date_str in enumerate(trading_days):
        scan_dt = datetime.strptime(
            date_str + f" {scan_hour:02d}:{SCAN_MINUTE_UTC:02d}:00",
            "%Y-%m-%d %H:%M:%S"
        ).replace(tzinfo=UTC)
        scan_epoch = int(scan_dt.timestamp())

        day_trades = []
        for sym in symbols_ok:
            try:
                bars = h1_cache[sym]
                day_bars = [b for b in bars if utc_day_str(b["time"]) == date_str]
                if len(day_bars) < 4:
                    continue

                result = analyze_symbol_for_date(bars, sym, date_str, scan_epoch)
                if result is None:
                    continue

                # AUCUN filtre ELITE -- toutes les setups valides

                # Backtest
                outcome, hit_price, tf_used = backtest_trade(
                    sym, result["action"], result["entry"],
                    result["sl"], result["tp1"], scan_epoch
                )
                result["outcome"] = outcome
                result["hit_price"] = hit_price
                result["tf_used"] = tf_used
                day_trades.append(result)
                all_trades.append(result)
            except Exception:
                continue

        if day_trades:
            n_gagne = sum(1 for t in day_trades if t["outcome"] == "GAGNE")
            n_perdu = sum(1 for t in day_trades if t["outcome"] == "PERDU")
            n_ouvert = sum(1 for t in day_trades if t["outcome"] == "OUVERT")
            n_clos = n_gagne + n_perdu
            wr = (n_gagne / n_clos * 100) if n_clos > 0 else 0
            daily_stats[date_str] = {
                "trades": len(day_trades), "gagnes": n_gagne,
                "perdus": n_perdu, "ouverts": n_ouvert, "winrate": wr,
            }
            print(f"  {date_str} : {len(day_trades):3d} trades | "
                  f"{n_gagne}G/{n_perdu}P/{n_ouvert}O | WR {wr:.0f}%")
        else:
            daily_stats[date_str] = {
                "trades": 0, "gagnes": 0, "perdus": 0, "ouverts": 0, "winrate": 0,
            }
        total_setups += len(day_trades)

        if day_idx % 10 == 9:
            time.sleep(0.2)

    # --- Statistiques ----------------------------------------------------
    print()
    print("[6/6] Calcul des statistiques...")

    n_g = sum(1 for t in all_trades if t["outcome"] == "GAGNE")
    n_p = sum(1 for t in all_trades if t["outcome"] == "PERDU")
    n_o = sum(1 for t in all_trades if t["outcome"] == "OUVERT")
    n_nd = sum(1 for t in all_trades if t["outcome"] == "NO_DATA")
    n_clos = n_g + n_p
    wr_global = (n_g / n_clos * 100) if n_clos > 0 else 0

    # Mensuel
    monthly = defaultdict(lambda: {"gagnes": 0, "perdus": 0, "ouverts": 0, "trades": 0})
    for t in all_trades:
        m = t["date"][:7]
        monthly[m]["trades"] += 1
        if t["outcome"] == "GAGNE": monthly[m]["gagnes"] += 1
        elif t["outcome"] == "PERDU": monthly[m]["perdus"] += 1
        else: monthly[m]["ouverts"] += 1

    # Par type
    by_type = defaultdict(lambda: {"gagnes": 0, "perdus": 0, "ouverts": 0})
    for t in all_trades:
        st = t["symbol_type"]
        if t["outcome"] == "GAGNE": by_type[st]["gagnes"] += 1
        elif t["outcome"] == "PERDU": by_type[st]["perdus"] += 1
        else: by_type[st]["ouverts"] += 1

    # Par direction
    by_dir = defaultdict(lambda: {"gagnes": 0, "perdus": 0, "ouverts": 0})
    for t in all_trades:
        d = t["action"]
        if t["outcome"] == "GAGNE": by_dir[d]["gagnes"] += 1
        elif t["outcome"] == "PERDU": by_dir[d]["perdus"] += 1
        else: by_dir[d]["ouverts"] += 1

    # Par session du sweep
    by_session = defaultdict(lambda: {"gagnes": 0, "perdus": 0, "ouverts": 0, "trades": 0})
    for t in all_trades:
        sweep_sessions = []
        if t.get("ah_swept_session"):
            sweep_sessions.append(t["ah_swept_session"])
        if t.get("al_swept_session"):
            sweep_sessions.append(t["al_swept_session"])
        sess = "-".join(sorted(set(sweep_sessions))) if sweep_sessions else "???"
        by_session[sess]["trades"] += 1
        if t["outcome"] == "GAGNE": by_session[sess]["gagnes"] += 1
        elif t["outcome"] == "PERDU": by_session[sess]["perdus"] += 1
        else: by_session[sess]["ouverts"] += 1

    # Meilleurs jours
    best_days = sorted(
        [(d, s) for d, s in daily_stats.items()
         if s["trades"] >= 3 and (s["gagnes"] + s["perdus"]) >= 3],
        key=lambda x: x[1]["winrate"], reverse=True
    )[:10]

    worst_days = sorted(
        [(d, s) for d, s in daily_stats.items()
         if s["trades"] >= 3 and (s["gagnes"] + s["perdus"]) >= 3],
        key=lambda x: x[1]["winrate"]
    )[:10]

    busiest = sorted(
        [(d, s) for d, s in daily_stats.items()],
        key=lambda x: x[1]["trades"], reverse=True
    )[:10]

    # --- Rapport ----------------------------------------------------------
    print()
    print("=" * 90)
    print("  RAPPORT FINAL -- BACKTEST DEFAUT (21:00 UTC, fin NY)")
    print("=" * 90)
    print()
    print(f"  Periode            : {start_date} -> {end_date}")
    print(f"  Heure scan         : {scan_hour:02d}:{SCAN_MINUTE_UTC:02d} UTC (fin session NY)")
    print(f"  Filtre             : AUCUN (tous types, tous RR, tous symboles)")
    print(f"  Jours de trading   : {len(trading_days)}")
    print(f"  Symboles scannes   : {len(symbols_ok)} (avec donnees H1)")
    print(f"  Total setups       : {total_setups}")
    print()
    print(f"  {'-' * 70}")
    print(f"  TRADES DEFAUT")
    print(f"  {'-' * 70}")
    print(f"  Total trades       : {len(all_trades)}")
    print(f"  [GAGNES]           : {n_g}")
    print(f"  [PERDUS]           : {n_p}")
    print(f"  [OUVERTS]          : {n_o}")
    print(f"  [NO DATA]          : {n_nd}")
    print(f"  [WINRATE GLOBAL]   : {wr_global:.1f}% ({n_g}/{n_clos} closes)")
    print()

    # Winrate mensuel
    print(f"  {'-' * 70}")
    print(f"  WINRATE MENSUEL")
    print(f"  {'-' * 70}")
    print(f"  {'Mois':<10} {'Trades':>7} {'Gagnes':>7} {'Perdus':>7} {'Ouverts':>8} {'Winrate':>8}")
    print(f"  {'-' * 50}")
    for month in sorted(monthly.keys()):
        m = monthly[month]
        closed = m["gagnes"] + m["perdus"]
        wr = (m["gagnes"] / closed * 100) if closed > 0 else 0
        print(f"  {month:<10} {m['trades']:>7} {m['gagnes']:>7} {m['perdus']:>7} "
              f"{m['ouverts']:>8} {wr:>7.1f}%")
    print()

    # Winrate par type
    print(f"  {'-' * 70}")
    print(f"  WINRATE PAR TYPE D'INSTRUMENT")
    print(f"  {'-' * 70}")
    for st in sorted(by_type.keys()):
        b = by_type[st]
        closed = b["gagnes"] + b["perdus"]
        wr = (b["gagnes"] / closed * 100) if closed > 0 else 0
        total = b["gagnes"] + b["perdus"] + b["ouverts"]
        print(f"  {st:<20} {total:>4} trades | {b['gagnes']:>3}G/{b['perdus']:>3}P | WR {wr:>5.1f}%")
    print()

    # Winrate par direction
    print(f"  {'-' * 70}")
    print(f"  WINRATE PAR DIRECTION")
    print(f"  {'-' * 70}")
    for d in sorted(by_dir.keys()):
        b = by_dir[d]
        closed = b["gagnes"] + b["perdus"]
        wr = (b["gagnes"] / closed * 100) if closed > 0 else 0
        print(f"  {d:<6} {b['gagnes']+b['perdus']+b['ouverts']:>4} trades | "
              f"{b['gagnes']:>3}G/{b['perdus']:>3}P | WR {wr:>5.1f}%")
    print()

    # Winrate par session de sweep
    if by_session:
        print(f"  {'-' * 70}")
        print(f"  WINRATE PAR SESSION DE SWEEP")
        print(f"  {'-' * 70}")
        for sess in sorted(by_session.keys()):
            b = by_session[sess]
            closed = b["gagnes"] + b["perdus"]
            wr = (b["gagnes"] / closed * 100) if closed > 0 else 0
            print(f"  {sess:<15} {b['trades']:>4} trades | {b['gagnes']:>3}G/{b['perdus']:>3}P | WR {wr:>5.1f}%")
        print()

    # Top jours
    if best_days:
        print(f"  {'-' * 70}")
        print(f"  TOP 10 MEILLEURS JOURS (>=3 trades, >=3 clos)")
        print(f"  {'-' * 70}")
        for d, s in best_days:
            print(f"  {d} : {s['trades']:>3} trades | {s['gagnes']}G/{s['perdus']}P | WR {s['winrate']:.0f}%")
        print()

    if worst_days:
        print(f"  {'-' * 70}")
        print(f"  TOP 10 PIRES JOURS (>=3 trades, >=3 clos)")
        print(f"  {'-' * 70}")
        for d, s in worst_days:
            print(f"  {d} : {s['trades']:>3} trades | {s['gagnes']}G/{s['perdus']}P | WR {s['winrate']:.0f}%")
        print()

    print(f"  {'-' * 70}")
    print(f"  TOP 10 JOURS LES PLUS ACTIFS")
    print(f"  {'-' * 70}")
    for d, s in busiest:
        print(f"  {d} : {s['trades']} trades DEFAUT")

    # --- Sauvegarde JSON --------------------------------------------------
    output = {
        "meta": {
            "filter": "DEFAUT",
            "scan_hour_utc": SCAN_HOUR_UTC,
            "scan_minute_utc": SCAN_MINUTE_UTC,
            "start_date": START_DATE, "end_date": END_DATE,
            "trading_days": len(trading_days),
            "symbols_with_data": len(symbols_ok),
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
        },
        "summary": {
            "total_trades": len(all_trades),
            "gagnes": n_g, "perdus": n_p, "ouverts": n_o, "no_data": n_nd,
            "winrate_global": round(wr_global, 1),
        },
        "monthly": {
            m: {
                "trades": v["trades"], "gagnes": v["gagnes"],
                "perdus": v["perdus"], "ouverts": v["ouverts"],
                "winrate": round(
                    (v["gagnes"] / (v["gagnes"] + v["perdus"]) * 100)
                    if (v["gagnes"] + v["perdus"]) > 0 else 0, 1
                ),
            }
            for m, v in sorted(monthly.items())
        },
        "by_type": {
            t: {
                "trades": b["gagnes"] + b["perdus"] + b["ouverts"],
                "gagnes": b["gagnes"], "perdus": b["perdus"], "ouverts": b["ouverts"],
                "winrate": round(
                    (b["gagnes"] / (b["gagnes"] + b["perdus"]) * 100)
                    if (b["gagnes"] + b["perdus"]) > 0 else 0, 1
                ),
            }
            for t, b in sorted(by_type.items())
        },
        "by_direction": {
            d: {
                "trades": b["gagnes"] + b["perdus"] + b["ouverts"],
                "gagnes": b["gagnes"], "perdus": b["perdus"], "ouverts": b["ouverts"],
                "winrate": round(
                    (b["gagnes"] / (b["gagnes"] + b["perdus"]) * 100)
                    if (b["gagnes"] + b["perdus"]) > 0 else 0, 1
                ),
            }
            for d, b in sorted(by_dir.items())
        },
        "best_days": [
            {"date": d, "trades": s["trades"], "gagnes": s["gagnes"],
             "perdus": s["perdus"], "winrate": round(s["winrate"], 1)}
            for d, s in best_days
        ],
        "worst_days": [
            {"date": d, "trades": s["trades"], "gagnes": s["gagnes"],
             "perdus": s["perdus"], "winrate": round(s["winrate"], 1)}
            for d, s in worst_days
        ],
        "all_trades": all_trades,
        "daily_stats": {d: s for d, s in sorted(daily_stats.items())},
    }

    json_path = os.path.join(REPORTS_DIR, f"default_backtest_{start_date}_to_{end_date}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print()
    print(f"  Rapport JSON : {json_path}")
    print(f"  Taille        : {os.path.getsize(json_path) / 1024:.1f} Ko")
    print("=" * 90)

    mt5.shutdown()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[STOP] Interrompu.")
        mt5.shutdown()
        sys.exit(130)
    except Exception as e:
        print(f"\n[ERREUR] {e}")
        import traceback
        traceback.print_exc()
        mt5.shutdown()
        sys.exit(1)
