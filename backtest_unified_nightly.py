#!/usr/bin/env python
"""
Backtest UNIFIÉ — Scan nocturne 21:00 UTC + DÉFAUT + ELITE V1 + ELITE V2
===========================================================================
Simule un scan quotidien à 21:00 UTC (23:00 Paris été, fermeture NY).
Détecte TOUS les setups valides (DÉFAUT — aucun filtre), puis les tagge
selon les critères ELITE V1 et ELITE V2 pour produire des statistiques
séparées.

Scan        : 21:00 UTC (après clôture NY)
Filtres     : DÉFAUT (tous), ELITE V1 (type + RR), ELITE V2 (type seul)
Backtest    : M5 (20000 barres, fallback M15)
P&L         : En R-multiples (GAGNÉ = +RR, PERDU = -1R)

Usage :
    python backtest_unified_nightly.py
    python backtest_unified_nightly.py --start 2026-03-01 --end 2026-06-26
    python backtest_unified_nightly.py --scan-hour 21
"""

import os
import sys
import time
import json
import argparse
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5
from src.config import ELITE, ELITE_V1

UTC = timezone.utc
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_DIR, "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

# ─── Configuration ──────────────────────────────────────────────────────────
SCAN_HOUR_UTC = 21          # 21:00 UTC = 23:00 Paris (été), fin NY
SCAN_MINUTE_UTC = 0
START_DATE = "2026-01-01"
END_DATE = "2026-06-26"

# Critères ELITE V1 (config.py)
V1_TYPES = set(ELITE_V1.allowed_types)    # FOREX_USD, INDEX, METAL, FOREX_CROSS
V1_MIN_RR = ELITE_V1.min_rr               # 0.5

# Critères ELITE V2 (config.py)
V2_TYPES = set(ELITE.allowed_types)        # FOREX_USD, INDEX, METAL

FIB_LEVELS_BULL = (1.618, 2.0, 2.618, 3.0, 3.618, 4.0)
FIB_LEVELS_BEAR = (-1.618, -2.0, -2.618, -3.0, -3.618, -4.0)

# Devises fiat connues
FIAT_CURRENCIES = {
    "EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "JPY",
    "NOK", "SEK", "DKK", "PLN", "CZK", "HUF", "MXN", "SGD",
    "ZAR", "TRY", "CNH", "ILS", "RUB", "INR", "HKD", "RON",
    "BGN", "HRK", "ISK", "KRW", "MYR", "PHP", "THB", "TWD",
    "BRL", "CLP", "COP", "PEN", "ARS", "AED", "SAR", "QAR",
    "KWD", "BHD", "OMR", "JOD", "EGP", "NGN", "KES", "GHS",
    "MAD", "TND", "DZD", "XOF", "XAF", "UGX", "TZS", "RWF",
}


# ─── Helpers ────────────────────────────────────────────────────────────────

def classify_symbol(sym: str) -> str:
    """Classification corrigée : CRYPTO, INDEX, METAL, FOREX_USD,
    FOREX_JPY, FOREX_CROSS, COMMODITY."""
    sym_u = sym.upper()

    if sym_u in ('XAUUSD', 'XAGUSD', 'XAUAUD', 'XAGAUD', 'XAUGBP', 'XAUJPY',
                 'XAGEUR', 'XAGGBP', 'XPTUSD', 'XPDUSD'):
        return 'METAL'

    if '.cash' in sym_u:
        return 'INDEX'
    if sym_u in ('DXY', 'DXY.cash', 'GDAXI', 'GDAXI.cash', 'US30', 'US100',
                 'US500', 'US2000', 'NAS100', 'SPX500', 'JP225', 'UK100',
                 'AUS200', 'HK50', 'FRA40', 'GER40', 'ESTX50', 'STOXX50',
                 'IT40', 'ES35', 'SUI20', 'NLD25', 'NOR25', 'SWE30', 'POL20',
                 'W20'):
        return 'INDEX'

    if any(sym_u.endswith(s) for s in ('.c', '.F')):
        return 'COMMODITY'

    if 'JPY' in sym_u:
        return 'FOREX_JPY'

    if sym_u.endswith('USD'):
        base = sym_u[:-3]
        if base in FIAT_CURRENCIES:
            return 'FOREX_USD'
        return 'CRYPTO'

    if sym_u.startswith('USD'):
        quote = sym_u[3:]
        if quote in FIAT_CURRENCIES:
            return 'FOREX_USD'
        return 'CRYPTO'

    if any(c in sym_u for c in ('EUR', 'GBP', 'CAD', 'AUD', 'NZD', 'CHF',
                                  'NOK', 'SEK', 'PLN', 'CZK', 'MXN', 'SGD',
                                  'ZAR', 'HUF')):
        return 'FOREX_CROSS'

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


def passes_elite_v1(trade: dict) -> bool:
    """Vérifie si un trade passe le filtre ELITE V1.
    Critères : type ∈ V1_TYPES  ET  RR >= 0.5.
    (Pas de filtre temps car scan à 21:00 = hors fenêtre ELITE ;
     pas de filtre spread car données historiques indisponibles.)"""
    if trade["symbol_type"] not in V1_TYPES:
        return False
    if trade.get("rr", 0) < V1_MIN_RR:
        return False
    return True


def passes_elite_v2(trade: dict) -> bool:
    """Vérifie si un trade passe le filtre ELITE V2.
    Critère : type ∈ V2_TYPES.
    (Pas de filtre RR car ELITE V2 n'en a pas ;
     pas de filtre temps/spread pour les mêmes raisons que V1.)"""
    return trade["symbol_type"] in V2_TYPES


def calc_pnl(trade: dict) -> float:
    """Calcule le P&L en R-multiples. GAGNÉ = +RR, PERDU = -1.0, sinon 0."""
    if trade["outcome"] == "GAGNE":
        return trade["rr"]
    elif trade["outcome"] == "PERDU":
        return -1.0
    return 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# BACKTEST D'UN TRADE
# ═══════════════════════════════════════════════════════════════════════════════

def backtest_trade(symbol: str, direction: str, entry: float, sl: float,
                   tp: float, scan_epoch: int) -> Tuple[str, float, str]:
    """Backteste un trade sur M5 (fallback M15) à partir de scan_epoch."""
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


# ═══════════════════════════════════════════════════════════════════════════════
# ANALYSE D'UN SYMBOLE POUR UN JOUR DONNÉ
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_symbol_for_date(h1_bars: List[dict], symbol: str, date_str: str,
                             scan_epoch: int) -> Optional[dict]:
    """Analyse le range asiatique depuis les barres H1 en cache.
    Scan à 21:00 UTC → barres London + NY incluses."""
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

    # Sweeps post-Asian jusqu'à 21:00 UTC
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

    # Entry = close H1 à 21:00 UTC (ou dernière avant)
    entry_bars = [b for b in h1_bars if b["time"] <= scan_epoch and utc_day_str(b["time"]) == date_str]
    if not entry_bars:
        entry_bars = [b for b in h1_bars if b["time"] <= scan_epoch]
    if not entry_bars:
        return None
    entry_price = entry_bars[-1]["close"]

    # Direction ICT
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

    # Fib state
    if trade_action == "BUY":
        for n in FIB_LEVELS_BULL:
            if entry_price < asian_high + n * range_size:
                fib_state_val = f"+{n}"
                break
    else:
        for n in FIB_LEVELS_BEAR:
            if entry_price > asian_low + n * range_size:
                fib_state_val = f"{n}"
                break

    # Range minimum
    midpoint = (asian_high + asian_low) / 2
    range_pct = range_size / midpoint * 100.0 if midpoint > 0 else 0
    if range_pct < 0.05:
        return None

    # SL et TP
    if trade_action == "BUY":
        trade_sl = asian_low - 0.10 * range_size
        try: fib_num = float(fib_state_val[1:])
        except: fib_num = 1.618
        idx = next((i for i, n in enumerate(FIB_LEVELS_BULL) if n >= fib_num - 0.001), 0)
        tp_candidates = FIB_LEVELS_BULL[idx:idx + 3]
        trade_tp1 = asian_high + tp_candidates[0] * range_size if len(tp_candidates) >= 1 else None
        if trade_tp1 is not None and trade_tp1 <= entry_price:
            if len(tp_candidates) >= 2:
                trade_tp1 = asian_high + tp_candidates[1] * range_size
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
        trade_tp1 = asian_low + tp_candidates[0] * range_size if len(tp_candidates) >= 1 else None
        if trade_tp1 is not None and trade_tp1 >= entry_price:
            if len(tp_candidates) >= 2:
                trade_tp1 = asian_low + tp_candidates[1] * range_size
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


# ═══════════════════════════════════════════════════════════════════════════════
# STATS HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def compute_stats(trades: List[dict], label: str) -> dict:
    """Calcule les statistiques pour un sous-ensemble de trades."""
    n_g = sum(1 for t in trades if t["outcome"] == "GAGNE")
    n_p = sum(1 for t in trades if t["outcome"] == "PERDU")
    n_o = sum(1 for t in trades if t["outcome"] == "OUVERT")
    n_nd = sum(1 for t in trades if t["outcome"] == "NO_DATA")
    n_clos = n_g + n_p
    wr = (n_g / n_clos * 100) if n_clos > 0 else 0

    pnl_total = sum(calc_pnl(t) for t in trades if t["outcome"] in ("GAGNE", "PERDU"))
    pnl_avg = pnl_total / n_clos if n_clos > 0 else 0

    # Par type
    by_type = defaultdict(lambda: {"gagnes": 0, "perdus": 0, "ouverts": 0, "pnl_r": 0.0})
    for t in trades:
        st = t["symbol_type"]
        if t["outcome"] == "GAGNE":
            by_type[st]["gagnes"] += 1
            by_type[st]["pnl_r"] += calc_pnl(t)
        elif t["outcome"] == "PERDU":
            by_type[st]["perdus"] += 1
            by_type[st]["pnl_r"] += calc_pnl(t)
        else:
            by_type[st]["ouverts"] += 1

    # Par direction
    by_dir = defaultdict(lambda: {"gagnes": 0, "perdus": 0, "ouverts": 0, "pnl_r": 0.0})
    for t in trades:
        d = t["action"]
        if t["outcome"] == "GAGNE":
            by_dir[d]["gagnes"] += 1
            by_dir[d]["pnl_r"] += calc_pnl(t)
        elif t["outcome"] == "PERDU":
            by_dir[d]["perdus"] += 1
            by_dir[d]["pnl_r"] += calc_pnl(t)
        else:
            by_dir[d]["ouverts"] += 1

    # Mensuel
    monthly = defaultdict(lambda: {"gagnes": 0, "perdus": 0, "ouverts": 0, "trades": 0, "pnl_r": 0.0})
    for t in trades:
        m = t["date"][:7]
        monthly[m]["trades"] += 1
        if t["outcome"] == "GAGNE":
            monthly[m]["gagnes"] += 1
            monthly[m]["pnl_r"] += calc_pnl(t)
        elif t["outcome"] == "PERDU":
            monthly[m]["perdus"] += 1
            monthly[m]["pnl_r"] += calc_pnl(t)
        else:
            monthly[m]["ouverts"] += 1

    return {
        "label": label,
        "total": len(trades),
        "gagnes": n_g, "perdus": n_p, "ouverts": n_o, "no_data": n_nd,
        "winrate": round(wr, 1),
        "pnl_total_r": round(pnl_total, 2),
        "pnl_avg_r": round(pnl_avg, 2),
        "by_type": dict(by_type),
        "by_dir": dict(by_dir),
        "monthly": dict(monthly),
    }


def print_stats_section(stats: dict):
    """Affiche une section de statistiques formatée."""
    label = stats["label"]
    print(f"  {'─' * 76}")
    print(f"  {label:^76}")
    print(f"  {'─' * 76}")
    print(f"  Total trades       : {stats['total']}")
    print(f"  [GAGNÉS]           : {stats['gagnes']}")
    print(f"  [PERDUS]           : {stats['perdus']}")
    print(f"  [OUVERTS]          : {stats['ouverts']}")
    if stats['no_data']:
        print(f"  [NO DATA]          : {stats['no_data']}")
    print(f"  [WINRATE]          : {stats['winrate']:.1f}% "
          f"({stats['gagnes']}/{stats['gagnes'] + stats['perdus']} clos)")
    print(f"  [P&L TOTAL]        : {stats['pnl_total_r']:+.2f}R")
    print(f"  [P&L MOYEN]        : {stats['pnl_avg_r']:+.2f}R/trade")
    print()

    # Par type
    by_type = stats.get("by_type", {})
    if by_type:
        print(f"  {'Type':<18} {'Trades':>6} {'G':>4} {'P':>4} {'WR':>7} {'P&L':>9} {'P&L/T':>8}")
        print(f"  {'─' * 60}")
        for st in sorted(by_type.keys()):
            b = by_type[st]
            closed = b["gagnes"] + b["perdus"]
            wr = (b["gagnes"] / closed * 100) if closed > 0 else 0
            total = b["gagnes"] + b["perdus"] + b["ouverts"]
            pnl_avg_t = b["pnl_r"] / closed if closed > 0 else 0
            print(f"  {st:<18} {total:>6} {b['gagnes']:>4} {b['perdus']:>4} "
                  f"{wr:>6.1f}% {b['pnl_r']:>+8.2f}R {pnl_avg_t:>+7.2f}R")
        print()

    # Par direction
    by_dir = stats.get("by_dir", {})
    if by_dir:
        print(f"  {'Direction':<10} {'Trades':>6} {'G':>4} {'P':>4} {'WR':>7} {'P&L':>9} {'P&L/T':>8}")
        print(f"  {'─' * 55}")
        for d in sorted(by_dir.keys()):
            b = by_dir[d]
            closed = b["gagnes"] + b["perdus"]
            wr = (b["gagnes"] / closed * 100) if closed > 0 else 0
            total = b["gagnes"] + b["perdus"] + b["ouverts"]
            pnl_avg_d = b["pnl_r"] / closed if closed > 0 else 0
            print(f"  {d:<10} {total:>6} {b['gagnes']:>4} {b['perdus']:>4} "
                  f"{wr:>6.1f}% {b['pnl_r']:>+8.2f}R {pnl_avg_d:>+7.2f}R")
        print()

    # Mensuel
    monthly = stats.get("monthly", {})
    if monthly:
        print(f"  {'Mois':<10} {'Trades':>7} {'G':>5} {'P':>5} {'WR':>7} {'P&L':>9} {'P&L/T':>8}")
        print(f"  {'─' * 55}")
        for month in sorted(monthly.keys()):
            m = monthly[month]
            closed = m["gagnes"] + m["perdus"]
            wr = (m["gagnes"] / closed * 100) if closed > 0 else 0
            pnl_avg_m = m["pnl_r"] / closed if closed > 0 else 0
            print(f"  {month:<10} {m['trades']:>7} {m['gagnes']:>5} {m['perdus']:>5} "
                  f"{wr:>6.1f}% {m['pnl_r']:>+8.2f}R {pnl_avg_m:>+7.2f}R")
        print()


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Backtest UNIFIÉ — Nocturne 21:00 UTC + DÉFAUT + V1 + V2"
    )
    parser.add_argument("--start", default=START_DATE, help=f"Date début (défaut: {START_DATE})")
    parser.add_argument("--end", default=END_DATE, help=f"Date fin (défaut: {END_DATE})")
    parser.add_argument("--scan-hour", type=int, default=SCAN_HOUR_UTC,
                        help=f"Heure UTC du scan (défaut: {SCAN_HOUR_UTC})")
    args = parser.parse_args()

    scan_hour = args.scan_hour

    print()
    print("=" * 90)
    print("  BACKTEST UNIFIÉ — NOCTURNE 21:00 UTC (23:00 Paris, fin NY)")
    print(f"  Période     : {args.start} → {args.end}")
    print(f"  Heure scan  : {scan_hour:02d}:{SCAN_MINUTE_UTC:02d} UTC")
    print(f"  3 VUES      : DÉFAUT (tous) | ELITE V1 | ELITE V2")
    print(f"  V1 critères : types {sorted(V1_TYPES)}, RR >= {V1_MIN_RR}")
    print(f"  V2 critères : types {sorted(V2_TYPES)} (aucun filtre RR)")
    print(f"  Backtest    : M5 (20000 barres, fallback M15)")
    print(f"  P&L         : R-multiples (GAGNÉ=+RR, PERDU=-1R)")
    print("=" * 90)
    print()

    # ── Connexion MT5 ──────────────────────────────────────────────────
    print("[1/6] Connexion MT5...")
    if not mt5.initialize():
        print("[ERREUR] Connexion MT5 échouée.")
        return 1
    ti = mt5.terminal_info()
    ai = mt5.account_info()
    if ti: print(f"  Terminal : {ti.name} (build {ti.build})")
    if ai: print(f"  Compte   : {ai.login} @ {ai.server}")
    print()

    # ── Symboles ───────────────────────────────────────────────────────
    print("[2/6] Récupération des symboles disponibles...")
    all_syms = mt5.symbols_get()
    if not all_syms:
        print("[ERREUR] Aucun symbole.")
        mt5.shutdown(); return 1
    symbols = sorted({s.name for s in all_syms})
    print(f"  {len(symbols)} symboles disponibles.")
    print()

    # ── Jours de trading ───────────────────────────────────────────────
    print("[3/6] Génération des jours de trading...")
    start_dt = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=UTC)
    end_dt = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=UTC)
    trading_days = []
    current = start_dt
    while current <= end_dt:
        if current.weekday() < 5:
            trading_days.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    print(f"  {len(trading_days)} jours de trading (lun-ven).")
    print()

    # ── Cache H1 ──────────────────────────────────────────────────────
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
    print(f"  {len(h1_cache)}/{len(symbols)} symboles avec données H1.")
    print()

    # ── Scan quotidien + backtest + tagging ───────────────────────────
    print(f"[5/6] Scan quotidien à {scan_hour:02d}:00 UTC + backtest M5...")
    print()

    all_trades = []
    daily_stats_all = {}
    daily_stats_v1 = {}
    daily_stats_v2 = {}

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

                # Backtest
                outcome, hit_price, tf_used = backtest_trade(
                    sym, result["action"], result["entry"],
                    result["sl"], result["tp1"], scan_epoch
                )
                result["outcome"] = outcome
                result["hit_price"] = hit_price
                result["tf_used"] = tf_used

                # Tagging ELITE
                result["is_elite_v1"] = passes_elite_v1(result)
                result["is_elite_v2"] = passes_elite_v2(result)

                day_trades.append(result)
                all_trades.append(result)
            except Exception:
                continue

        if day_trades:
            n_g = sum(1 for t in day_trades if t["outcome"] == "GAGNE")
            n_p = sum(1 for t in day_trades if t["outcome"] == "PERDU")
            n_o = sum(1 for t in day_trades if t["outcome"] == "OUVERT")
            n_clos = n_g + n_p
            wr = (n_g / n_clos * 100) if n_clos > 0 else 0
            daily_stats_all[date_str] = {
                "trades": len(day_trades), "gagnes": n_g,
                "perdus": n_p, "ouverts": n_o, "winrate": wr,
            }

            # V1 subset
            v1_day = [t for t in day_trades if t["is_elite_v1"]]
            if v1_day:
                n_g1 = sum(1 for t in v1_day if t["outcome"] == "GAGNE")
                n_p1 = sum(1 for t in v1_day if t["outcome"] == "PERDU")
                n_o1 = sum(1 for t in v1_day if t["outcome"] == "OUVERT")
                n_clos1 = n_g1 + n_p1
                wr1 = (n_g1 / n_clos1 * 100) if n_clos1 > 0 else 0
                daily_stats_v1[date_str] = {
                    "trades": len(v1_day), "gagnes": n_g1,
                    "perdus": n_p1, "ouverts": n_o1, "winrate": wr1,
                }

            # V2 subset
            v2_day = [t for t in day_trades if t["is_elite_v2"]]
            if v2_day:
                n_g2 = sum(1 for t in v2_day if t["outcome"] == "GAGNE")
                n_p2 = sum(1 for t in v2_day if t["outcome"] == "PERDU")
                n_o2 = sum(1 for t in v2_day if t["outcome"] == "OUVERT")
                n_clos2 = n_g2 + n_p2
                wr2 = (n_g2 / n_clos2 * 100) if n_clos2 > 0 else 0
                daily_stats_v2[date_str] = {
                    "trades": len(v2_day), "gagnes": n_g2,
                    "perdus": n_p2, "ouverts": n_o2, "winrate": wr2,
                }

            v1_n = len(v1_day)
            v2_n = len(v2_day)
            print(f"  {date_str} : {len(day_trades):3d} trades "
                  f"| V1:{v1_n:2d} V2:{v2_n:2d} "
                  f"| {n_g}G/{n_p}P/{n_o}O | WR {wr:.0f}%")
        else:
            daily_stats_all[date_str] = {
                "trades": 0, "gagnes": 0, "perdus": 0, "ouverts": 0, "winrate": 0,
            }

        if (day_idx + 1) % 10 == 0:
            print(f"  ... {day_idx+1}/{len(trading_days)} jours")
        time.sleep(0.1)

    # ── Statistiques ───────────────────────────────────────────────────
    print()
    print("[6/6] Calcul des statistiques triples (DÉFAUT, V1, V2)...")

    # Subsets
    trades_v1 = [t for t in all_trades if t["is_elite_v1"]]
    trades_v2 = [t for t in all_trades if t["is_elite_v2"]]

    stats_default = compute_stats(all_trades, "DÉFAUT — Tous les trades (aucun filtre)")
    stats_v1 = compute_stats(trades_v1, "ELITE V1 — Types USD+INDEX+METAL+CROSS, RR ≥ 0.5")
    stats_v2 = compute_stats(trades_v2, "ELITE V2 — Types USD+INDEX+METAL (aucun filtre RR)")

    # ── Rapport ────────────────────────────────────────────────────────────
    print()
    print("=" * 90)
    print("  RAPPORT FINAL — BACKTEST UNIFIÉ NOCTURNE")
    print("=" * 90)
    print()
    print(f"  Période            : {args.start} → {args.end}")
    print(f"  Heure scan         : {scan_hour:02d}:{SCAN_MINUTE_UTC:02d} UTC (23:00 Paris été)")
    print(f"  Jours de trading   : {len(trading_days)}")
    print(f"  Symboles scannés   : {len(symbols_ok)} (avec données H1)")
    print()

    # ═══ COMPARAISON RAPIDE ═══
    print(f"  {'═' * 76}")
    print(f"  {'COMPARAISON RAPIDE':^76}")
    print(f"  {'═' * 76}")
    print(f"  {'Filtre':<20} {'Trades':>8} {'Clos':>6} {'Winrate':>9} {'P&L Total':>10} {'P&L/Trade':>10}")
    print(f"  {'─' * 66}")
    for s in [stats_default, stats_v1, stats_v2]:
        n_clos = s["gagnes"] + s["perdus"]
        print(f"  {s['label'].split('—')[0].strip():<20} {s['total']:>8} {n_clos:>6} "
              f"{s['winrate']:>8.1f}% {s['pnl_total_r']:>+9.2f}R {s['pnl_avg_r']:>+9.2f}R")
    print()

    # ═══ DÉTAIL PAR FILTRE ═══
    print_stats_section(stats_default)
    print_stats_section(stats_v1)
    print_stats_section(stats_v2)

    # ═══ OVERLAP ═══
    v1_and_v2 = [t for t in all_trades if t["is_elite_v1"] and t["is_elite_v2"]]
    v1_only = [t for t in all_trades if t["is_elite_v1"] and not t["is_elite_v2"]]
    v2_only = [t for t in all_trades if t["is_elite_v2"] and not t["is_elite_v1"]]
    neither = [t for t in all_trades if not t["is_elite_v1"] and not t["is_elite_v2"]]

    print(f"  {'─' * 76}")
    print(f"  {'OVERLAP V1 ∩ V2':^76}")
    print(f"  {'─' * 76}")
    print(f"  V1 ∩ V2 (les deux)   : {len(v1_and_v2)} trades")
    print(f"  V1 seulement          : {len(v1_only)} trades")
    print(f"  V2 seulement          : {len(v2_only)} trades")
    print(f"  Ni V1 ni V2           : {len(neither)} trades")
    print()

    # ── Sauvegarde JSON ────────────────────────────────────────────────
    # Simplifier les stats pour le JSON
    def stats_to_json(s):
        by_type_json = {}
        for t, b in s["by_type"].items():
            closed = b["gagnes"] + b["perdus"]
            by_type_json[t] = {
                "trades": b["gagnes"] + b["perdus"] + b["ouverts"],
                "gagnes": b["gagnes"], "perdus": b["perdus"], "ouverts": b["ouverts"],
                "winrate": round((b["gagnes"] / closed * 100) if closed > 0 else 0, 1),
                "pnl_r": round(b["pnl_r"], 2),
                "pnl_avg_r": round(b["pnl_r"] / closed if closed > 0 else 0, 2),
            }
        by_dir_json = {}
        for d, b in s["by_dir"].items():
            closed = b["gagnes"] + b["perdus"]
            by_dir_json[d] = {
                "trades": b["gagnes"] + b["perdus"] + b["ouverts"],
                "gagnes": b["gagnes"], "perdus": b["perdus"], "ouverts": b["ouverts"],
                "winrate": round((b["gagnes"] / closed * 100) if closed > 0 else 0, 1),
                "pnl_r": round(b["pnl_r"], 2),
                "pnl_avg_r": round(b["pnl_r"] / closed if closed > 0 else 0, 2),
            }
        monthly_json = {}
        for m, v in s["monthly"].items():
            closed = v["gagnes"] + v["perdus"]
            monthly_json[m] = {
                "trades": v["trades"], "gagnes": v["gagnes"],
                "perdus": v["perdus"], "ouverts": v["ouverts"],
                "winrate": round((v["gagnes"] / closed * 100) if closed > 0 else 0, 1),
                "pnl_r": round(v["pnl_r"], 2),
                "pnl_avg_r": round(v["pnl_r"] / closed if closed > 0 else 0, 2),
            }
        return {
            "total_trades": s["total"],
            "gagnes": s["gagnes"], "perdus": s["perdus"],
            "ouverts": s["ouverts"], "no_data": s["no_data"],
            "winrate": s["winrate"],
            "pnl_total_r": s["pnl_total_r"],
            "pnl_avg_r": s["pnl_avg_r"],
            "by_type": by_type_json,
            "by_direction": by_dir_json,
            "monthly": monthly_json,
        }

    output = {
        "meta": {
            "scan_hour_utc": scan_hour,
            "scan_minute_utc": SCAN_MINUTE_UTC,
            "start_date": args.start, "end_date": args.end,
            "trading_days": len(trading_days),
            "symbols_with_data": len(symbols_ok),
            "v1_criteria": {
                "types": sorted(V1_TYPES),
                "min_rr": V1_MIN_RR,
            },
            "v2_criteria": {
                "types": sorted(V2_TYPES),
            },
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
        },
        "comparison": {
            "default": stats_to_json(stats_default),
            "elite_v1": stats_to_json(stats_v1),
            "elite_v2": stats_to_json(stats_v2),
        },
        "overlap": {
            "v1_and_v2": len(v1_and_v2),
            "v1_only": len(v1_only),
            "v2_only": len(v2_only),
            "neither": len(neither),
        },
        "all_trades": all_trades,
        "trades_v1_count": len(trades_v1),
        "trades_v2_count": len(trades_v2),
        "daily_stats": {
            d: s for d, s in sorted(daily_stats_all.items())
        },
        "daily_stats_v1": {
            d: s for d, s in sorted(daily_stats_v1.items())
        },
        "daily_stats_v2": {
            d: s for d, s in sorted(daily_stats_v2.items())
        },
    }

    json_path = os.path.join(
        REPORTS_DIR,
        f"unified_backtest_{args.start}_to_{args.end}.json"
    )
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"  Rapport JSON : {json_path}")
    print(f"  Taille       : {os.path.getsize(json_path) / 1024:.1f} Ko")
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
