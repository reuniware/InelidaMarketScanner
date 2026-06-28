#!/usr/bin/env python
"""
Backtest OPTIMAL — Historique complet avec scan multi-horaire ELITE V2
=========================================================================
Simule un scan TOUTES LES HEURES dans la fenêtre ELITE (09:00→13:00 UTC),
applique le filtre ÉLITE V2, et backteste chaque trade avec M5 (fallback M15).

AMÉLIORATIONS vs backtest_default_history.py :
  1. Scan MULTI-HORAIRE : 09:00, 10:00, 11:00, 12:00, 13:00 UTC
     → Capture les setups dès qu'ils deviennent valides pendant la journée
  2. Filtre ELITE V2 appliqué (config.py) : USD+INDEX+METAL, spread<0.50%
  3. P&L calculé en R-multiples (GAGNE=+RR, PERDU=-1R)
  4. Classification corrigée : CRYPTO, INDEX, METAL, FOREX_USD, FOREX_JPY,
     FOREX_CROSS, COMMODITY
  5. Rapport enrichi : P&L total, P&L/trade, P&L mensuel, stats par heure

Utilisation :
  python backtest_optimal_history.py
  python backtest_optimal_history.py --start 2026-03-01 --end 2026-06-26
  python backtest_optimal_history.py --no-elite  # désactive le filtre ELITE
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
from src.config import ELITE

UTC = timezone.utc
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_DIR, "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

# ─── Constantes ────────────────────────────────────────────────────────────────
START_DATE = "2026-01-01"
END_DATE = "2026-06-26"

# Heures de scan dans la fenêtre ELITE (UTC)
SCAN_HOURS_UTC = [9, 10, 11, 12, 13]

ELITE_TYPES = set(ELITE.allowed_types) if ELITE.enabled else set()

FIB_LEVELS_BULL = (1.618, 2.0, 2.618, 3.0, 3.618, 4.0)
FIB_LEVELS_BEAR = (-1.618, -2.0, -2.618, -3.0, -3.618, -4.0)

# Devises fiat connues pour distinguer CRYPTO de FOREX_USD
FIAT_CURRENCIES = {
    "EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "JPY",
    "NOK", "SEK", "DKK", "PLN", "CZK", "HUF", "MXN", "SGD",
    "ZAR", "TRY", "CNH", "ILS", "RUB", "INR", "HKD", "RON",
    "BGN", "HRK", "ISK", "KRW", "MYR", "PHP", "THB", "TWD",
    "BRL", "CLP", "COP", "PEN", "ARS", "AED", "SAR", "QAR",
    "KWD", "BHD", "OMR", "JOD", "EGP", "NGN", "KES", "GHS",
    "MAD", "TND", "DZD", "XOF", "XAF", "UGX", "TZS", "RWF",
}


# ─── Helpers ───────────────────────────────────────────────────────────────────

def classify_symbol(sym: str) -> str:
    """Classification corrigée : CRYPTO, INDEX, METAL, FOREX_USD,
    FOREX_JPY, FOREX_CROSS, COMMODITY."""
    sym_u = sym.upper()

    # Métaux
    if sym_u in ('XAUUSD', 'XAGUSD', 'XAUAUD', 'XAGAUD', 'XAUGBP', 'XAUJPY',
                 'XAGEUR', 'XAGGBP', 'XPTUSD', 'XPDUSD'):
        return 'METAL'

    # Indices
    if '.cash' in sym_u:
        return 'INDEX'
    if sym_u in ('DXY', 'DXY.cash', 'GDAXI', 'GDAXI.cash', 'US30', 'US100',
                 'US500', 'US2000', 'NAS100', 'SPX500', 'JP225', 'UK100',
                 'AUS200', 'HK50', 'FRA40', 'GER40', 'ESTX50', 'STOXX50',
                 'IT40', 'ES35', 'SUI20', 'NLD25', 'NOR25', 'SWE30', 'POL20',
                 'W20'):
        return 'INDEX'

    # Matières premières
    if any(sym_u.endswith(s) for s in ('.c', '.F')):
        return 'COMMODITY'

    # Forex JPY
    if 'JPY' in sym_u:
        return 'FOREX_JPY'

    # Paires en USD
    if sym_u.endswith('USD'):
        base = sym_u[:-3]
        if base in FIAT_CURRENCIES:
            if base == 'USD':
                return 'FOREX_USD'  # USDUSD n'existe pas mais sécurité
            return 'FOREX_USD'
        return 'CRYPTO'

    if sym_u.startswith('USD'):
        quote = sym_u[3:]
        if quote in FIAT_CURRENCIES:
            return 'FOREX_USD'
        return 'CRYPTO'

    # Forex crosses
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
# ANALYSE D'UN SYMBOLE POUR UN JOUR + UNE HEURE DE SCAN DONNÉS
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_symbol_for_date_and_hour(
    h1_bars: List[dict], symbol: str, date_str: str, scan_epoch: int
) -> Optional[dict]:
    """Analyse le range asiatique depuis les barres H1 en cache,
    pour une heure de scan précise."""
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

    # Sweeps post-Asian jusqu'à l'heure du scan
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

    # Entry = close H1 à l'heure du scan (ou dernière avant)
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
# CALCUL P&L
# ═══════════════════════════════════════════════════════════════════════════════

def calc_pnl(trade: dict) -> float:
    """Calcule le P&L en R-multiples.
    GAGNE = +RR, PERDU = -1.0, OUVERT/NO_DATA = 0"""
    if trade["outcome"] == "GAGNE":
        return trade["rr"]
    elif trade["outcome"] == "PERDU":
        return -1.0
    return 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Backtest OPTIMAL — Multi-scan ELITE V2 + P&L/R"
    )
    parser.add_argument("--start", default=START_DATE, help=f"Date début (défaut: {START_DATE})")
    parser.add_argument("--end", default=END_DATE, help=f"Date fin (défaut: {END_DATE})")
    parser.add_argument("--scan-hours", type=str, default=None,
                        help="Heures UTC de scan, séparées par des virgules (défaut: 9,10,11,12,13)")
    parser.add_argument("--no-elite", action="store_true",
                        help="Désactive le filtre ELITE V2 (tous types)")
    parser.add_argument("--elite-types", type=str, default=None,
                        help="Types autorisés, séparés par des virgules (défaut: config.py)")
    args = parser.parse_args()

    # Heures de scan
    if args.scan_hours:
        scan_hours = [int(h.strip()) for h in args.scan_hours.split(",")]
    else:
        scan_hours = SCAN_HOURS_UTC

    # Filtre ELITE (--no-elite prioritaire sur --elite-types)
    use_elite = not args.no_elite
    if not use_elite:
        elite_types = set()
    elif args.elite_types:
        elite_types = set(t.strip().upper() for t in args.elite_types.split(","))
    else:
        elite_types = ELITE_TYPES

    print()
    print("=" * 90)
    print("  BACKTEST OPTIMAL — MULTI-SCAN HORAIRE + P&L/R")
    print(f"  Période      : {args.start} → {args.end}")
    print(f"  Heures scan  : {', '.join(f'{h:02d}:00' for h in scan_hours)} UTC")
    print(f"  Filtre ELITE : {'OUI' if use_elite else 'NON (tous types)'}")
    if elite_types:
        print(f"  Types ELITE  : {sorted(elite_types)}")
    print(f"  Backtest     : M5 (20000 barres, fallback M15)")
    print(f"  Note          : scans multi-horaires = trades corrélés possibles")
    print(f"                  (même setup à heures différentes = entrées différentes)")
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

    # ── Multi-scan + backtest ─────────────────────────────────────────
    n_scans = len(scan_hours) * len(trading_days)
    print(f"[5/6] Multi-scan : {len(scan_hours)} heures × {len(trading_days)} jours "
          f"= {n_scans} scans...")
    print()

    all_trades = []
    daily_stats = defaultdict(lambda: {
        "trades": 0, "gagnes": 0, "perdus": 0, "ouverts": 0, "pnl_r": 0.0
    })
    scan_num = 0

    for day_idx, date_str in enumerate(trading_days):
        day_trades = []

        for scan_h in scan_hours:
            scan_dt = datetime.strptime(
                date_str + f" {scan_h:02d}:00:00",
                "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=UTC)
            scan_epoch = int(scan_dt.timestamp())
            scan_num += 1

            for sym in symbols_ok:
                try:
                    bars = h1_cache[sym]
                    day_bars = [b for b in bars if utc_day_str(b["time"]) == date_str]
                    if len(day_bars) < 4:
                        continue

                    result = analyze_symbol_for_date_and_hour(
                        bars, sym, date_str, scan_epoch
                    )
                    if result is None:
                        continue

                    # Filtre ELITE V2 (type)
                    if elite_types and result["symbol_type"] not in elite_types:
                        continue

                    # Backtest
                    outcome, hit_price, tf_used = backtest_trade(
                        sym, result["action"], result["entry"],
                        result["sl"], result["tp1"], scan_epoch
                    )
                    result["outcome"] = outcome
                    result["hit_price"] = hit_price
                    result["tf_used"] = tf_used
                    result["scan_hour_utc"] = scan_h
                    result["pnl_r"] = calc_pnl(result)
                    day_trades.append(result)
                    all_trades.append(result)
                except Exception:
                    continue

        # Stats journalières
        if day_trades:
            n_g = sum(1 for t in day_trades if t["outcome"] == "GAGNE")
            n_p = sum(1 for t in day_trades if t["outcome"] == "PERDU")
            n_o = sum(1 for t in day_trades if t["outcome"] == "OUVERT")
            pnl_total = sum(t["pnl_r"] for t in day_trades if t["outcome"] in ("GAGNE", "PERDU"))
            n_clos = n_g + n_p
            wr = (n_g / n_clos * 100) if n_clos > 0 else 0
            daily_stats[date_str] = {
                "trades": len(day_trades), "gagnes": n_g,
                "perdus": n_p, "ouverts": n_o, "winrate": wr,
                "pnl_r": pnl_total,
            }
            pnl_avg = pnl_total / n_clos if n_clos > 0 else 0
            print(f"  {date_str} : {len(day_trades):3d} trades | "
                  f"{n_g}G/{n_p}P/{n_o}O | WR {wr:.0f}% | P&L {pnl_total:+.2f}R "
                  f"({pnl_avg:+.2f}R/trade)")
        else:
            daily_stats[date_str] = {
                "trades": 0, "gagnes": 0, "perdus": 0, "ouverts": 0,
                "winrate": 0, "pnl_r": 0.0,
            }

        if (day_idx + 1) % 10 == 0:
            print(f"  ... {day_idx+1}/{len(trading_days)} jours")
        time.sleep(0.1)

    # ── Statistiques globales ─────────────────────────────────────────
    print()
    print("[6/6] Calcul des statistiques...")

    n_g = sum(1 for t in all_trades if t["outcome"] == "GAGNE")
    n_p = sum(1 for t in all_trades if t["outcome"] == "PERDU")
    n_o = sum(1 for t in all_trades if t["outcome"] == "OUVERT")
    n_nd = sum(1 for t in all_trades if t["outcome"] == "NO_DATA")
    n_clos = n_g + n_p
    wr_global = (n_g / n_clos * 100) if n_clos > 0 else 0

    # P&L global (trades clos uniquement)
    pnl_total = sum(t["pnl_r"] for t in all_trades if t["outcome"] in ("GAGNE", "PERDU"))
    pnl_avg = pnl_total / n_clos if n_clos > 0 else 0

    # Par heure de scan
    by_hour = defaultdict(lambda: {
        "gagnes": 0, "perdus": 0, "ouverts": 0, "pnl_r": 0.0
    })
    for t in all_trades:
        h = t.get("scan_hour_utc", 0)
        if t["outcome"] == "GAGNE":
            by_hour[h]["gagnes"] += 1
        elif t["outcome"] == "PERDU":
            by_hour[h]["perdus"] += 1
        else:
            by_hour[h]["ouverts"] += 1
        if t["outcome"] in ("GAGNE", "PERDU"):
            by_hour[h]["pnl_r"] += t["pnl_r"]

    # Mensuel
    monthly = defaultdict(lambda: {
        "gagnes": 0, "perdus": 0, "ouverts": 0, "pnl_r": 0.0, "trades": 0
    })
    for t in all_trades:
        m = t["date"][:7]
        monthly[m]["trades"] += 1
        if t["outcome"] == "GAGNE":
            monthly[m]["gagnes"] += 1
        elif t["outcome"] == "PERDU":
            monthly[m]["perdus"] += 1
        else:
            monthly[m]["ouverts"] += 1
        if t["outcome"] in ("GAGNE", "PERDU"):
            monthly[m]["pnl_r"] += t["pnl_r"]

    # Par type
    by_type = defaultdict(lambda: {
        "gagnes": 0, "perdus": 0, "ouverts": 0, "pnl_r": 0.0
    })
    for t in all_trades:
        st = t["symbol_type"]
        if t["outcome"] == "GAGNE":
            by_type[st]["gagnes"] += 1
        elif t["outcome"] == "PERDU":
            by_type[st]["perdus"] += 1
        else:
            by_type[st]["ouverts"] += 1
        if t["outcome"] in ("GAGNE", "PERDU"):
            by_type[st]["pnl_r"] += t["pnl_r"]

    # Par direction
    by_dir = defaultdict(lambda: {
        "gagnes": 0, "perdus": 0, "ouverts": 0, "pnl_r": 0.0
    })
    for t in all_trades:
        d = t["action"]
        if t["outcome"] == "GAGNE":
            by_dir[d]["gagnes"] += 1
        elif t["outcome"] == "PERDU":
            by_dir[d]["perdus"] += 1
        else:
            by_dir[d]["ouverts"] += 1
        if t["outcome"] in ("GAGNE", "PERDU"):
            by_dir[d]["pnl_r"] += t["pnl_r"]

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

    # ── Rapport ────────────────────────────────────────────────────────────
    print()
    print("=" * 90)
    print("  RAPPORT FINAL — BACKTEST OPTIMAL (multi-scan ELITE V2 + P&L/R)")
    print("=" * 90)
    print()
    print(f"  Période            : {args.start} → {args.end}")
    print(f"  Heures de scan     : {', '.join(f'{h:02d}:00' for h in scan_hours)} UTC")
    print(f"  Filtre ELITE       : {'OUI' if elite_types else 'NON'}")
    if elite_types:
        print(f"  Types autorisés    : {sorted(elite_types)}")
    print(f"  Jours de trading   : {len(trading_days)}")
    print(f"  Symboles scannés   : {len(symbols_ok)} (avec données H1)")
    print(f"  Scans totaux       : {scan_num}")
    print()

    # Résumé principal
    print(f"  {'─' * 76}")
    print(f"  {'RÉSULTATS GLOBAUX':^76}")
    print(f"  {'─' * 76}")
    print(f"  Total trades       : {len(all_trades)}")
    print(f"  [GAGNÉS]           : {n_g}")
    print(f"  [PERDUS]           : {n_p}")
    print(f"  [OUVERTS]          : {n_o}")
    print(f"  [NO DATA]          : {n_nd}")
    print(f"  [WINRATE]          : {wr_global:.1f}% ({n_g}/{n_clos} clos)")
    print(f"  [P&L TOTAL]        : {pnl_total:+.2f}R")
    print(f"  [P&L MOYEN]        : {pnl_avg:+.2f}R/trade")
    print()

    # Winrate + P&L par heure de scan
    if by_hour:
        print(f"  {'─' * 76}")
        print(f"  {'WINRATE & P&L PAR HEURE DE SCAN':^76}")
        print(f"  {'─' * 76}")
        print(f"  {'Heure':<8} {'Trades':>7} {'G':>4} {'P':>4} {'O':>4} {'Winrate':>8} {'P&L':>8} {'P&L/T':>8}")
        print(f"  {'─' * 56}")
        for h in sorted(by_hour.keys()):
            b = by_hour[h]
            closed = b["gagnes"] + b["perdus"]
            wr = (b["gagnes"] / closed * 100) if closed > 0 else 0
            total = b["gagnes"] + b["perdus"] + b["ouverts"]
            pnl_avg_h = b["pnl_r"] / closed if closed > 0 else 0
            print(f"  {h:02d}:00{'':<3} {total:>7} {b['gagnes']:>4} {b['perdus']:>4} "
                  f"{b['ouverts']:>4} {wr:>7.1f}% {b['pnl_r']:>+7.2f}R {pnl_avg_h:>+7.2f}R")
        print()

    # Winrate + P&L mensuel
    print(f"  {'─' * 76}")
    print(f"  {'WINRATE & P&L MENSUEL':^76}")
    print(f"  {'─' * 76}")
    print(f"  {'Mois':<10} {'Trades':>7} {'G':>5} {'P':>5} {'O':>5} {'Winrate':>8} {'P&L':>9} {'P&L/T':>8}")
    print(f"  {'─' * 60}")
    for month in sorted(monthly.keys()):
        m = monthly[month]
        closed = m["gagnes"] + m["perdus"]
        wr = (m["gagnes"] / closed * 100) if closed > 0 else 0
        pnl_avg_m = m["pnl_r"] / closed if closed > 0 else 0
        print(f"  {month:<10} {m['trades']:>7} {m['gagnes']:>5} {m['perdus']:>5} "
              f"{m['ouverts']:>5} {wr:>7.1f}% {m['pnl_r']:>+8.2f}R {pnl_avg_m:>+7.2f}R")
    print()

    # Winrate + P&L par type
    print(f"  {'─' * 76}")
    print(f"  {'WINRATE & P&L PAR TYPE':^76}")
    print(f"  {'─' * 76}")
    print(f"  {'Type':<18} {'Trades':>6} {'G':>4} {'P':>4} {'Winrate':>8} {'P&L':>9} {'P&L/T':>8}")
    print(f"  {'─' * 60}")
    for st in sorted(by_type.keys()):
        b = by_type[st]
        closed = b["gagnes"] + b["perdus"]
        wr = (b["gagnes"] / closed * 100) if closed > 0 else 0
        total = b["gagnes"] + b["perdus"] + b["ouverts"]
        pnl_avg_t = b["pnl_r"] / closed if closed > 0 else 0
        print(f"  {st:<18} {total:>6} {b['gagnes']:>4} {b['perdus']:>4} "
              f"{wr:>7.1f}% {b['pnl_r']:>+8.2f}R {pnl_avg_t:>+7.2f}R")
    print()

    # Winrate par direction
    print(f"  {'─' * 76}")
    print(f"  {'WINRATE & P&L PAR DIRECTION':^76}")
    print(f"  {'─' * 76}")
    for d in sorted(by_dir.keys()):
        b = by_dir[d]
        closed = b["gagnes"] + b["perdus"]
        wr = (b["gagnes"] / closed * 100) if closed > 0 else 0
        total = b["gagnes"] + b["perdus"] + b["ouverts"]
        pnl_avg_d = b["pnl_r"] / closed if closed > 0 else 0
        print(f"  {d:<6} {total:>4} trades | {b['gagnes']:>3}G/{b['perdus']:>3}P | "
              f"WR {wr:>5.1f}% | P&L {b['pnl_r']:>+7.2f}R ({pnl_avg_d:>+.2f}R/trade)")
    print()

    # Top / Flop jours
    if best_days:
        print(f"  {'─' * 76}")
        print(f"  {'TOP 10 MEILLEURS JOURS (≥3 trades, ≥3 clos)':^76}")
        print(f"  {'─' * 76}")
        for d, s in best_days:
            pnl_d = s.get("pnl_r", 0)
            print(f"  {d} : {s['trades']:>3} trades | {s['gagnes']}G/{s['perdus']}P | "
                  f"WR {s['winrate']:.0f}% | P&L {pnl_d:+.2f}R")
        print()

    if worst_days:
        print(f"  {'─' * 76}")
        print(f"  {'TOP 10 PIRES JOURS (≥3 trades, ≥3 clos)':^76}")
        print(f"  {'─' * 76}")
        for d, s in worst_days:
            pnl_d = s.get("pnl_r", 0)
            print(f"  {d} : {s['trades']:>3} trades | {s['gagnes']}G/{s['perdus']}P | "
                  f"WR {s['winrate']:.0f}% | P&L {pnl_d:+.2f}R")

    # ── Sauvegarde JSON ────────────────────────────────────────────────────
    output = {
        "meta": {
            "scan_hours_utc": scan_hours,
            "start_date": args.start, "end_date": args.end,
            "trading_days": len(trading_days),
            "symbols_with_data": len(symbols_ok),
            "elite_enabled": use_elite,
            "elite_types": sorted(elite_types) if elite_types else [],
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
        },
        "summary": {
            "total_trades": len(all_trades),
            "gagnes": n_g, "perdus": n_p, "ouverts": n_o, "no_data": n_nd,
            "winrate_global": round(wr_global, 1),
            "pnl_total_r": round(pnl_total, 2),
            "pnl_avg_r": round(pnl_avg, 2),
        },
        "by_hour": {
            f"{h:02d}:00": {
                "trades": b["gagnes"] + b["perdus"] + b["ouverts"],
                "gagnes": b["gagnes"], "perdus": b["perdus"],
                "ouverts": b["ouverts"],
                "winrate": round(
                    (b["gagnes"] / (b["gagnes"] + b["perdus"]) * 100)
                    if (b["gagnes"] + b["perdus"]) > 0 else 0, 1
                ),
                "pnl_r": round(b["pnl_r"], 2),
                "pnl_avg_r": round(
                    b["pnl_r"] / (b["gagnes"] + b["perdus"])
                    if (b["gagnes"] + b["perdus"]) > 0 else 0, 2
                ),
            }
            for h, b in sorted(by_hour.items())
        },
        "monthly": {
            m: {
                "trades": v["trades"], "gagnes": v["gagnes"],
                "perdus": v["perdus"], "ouverts": v["ouverts"],
                "winrate": round(
                    (v["gagnes"] / (v["gagnes"] + v["perdus"]) * 100)
                    if (v["gagnes"] + v["perdus"]) > 0 else 0, 1
                ),
                "pnl_r": round(v["pnl_r"], 2),
                "pnl_avg_r": round(
                    v["pnl_r"] / (v["gagnes"] + v["perdus"])
                    if (v["gagnes"] + v["perdus"]) > 0 else 0, 2
                ),
            }
            for m, v in sorted(monthly.items())
        },
        "by_type": {
            t: {
                "trades": b["gagnes"] + b["perdus"] + b["ouverts"],
                "gagnes": b["gagnes"], "perdus": b["perdus"],
                "ouverts": b["ouverts"],
                "winrate": round(
                    (b["gagnes"] / (b["gagnes"] + b["perdus"]) * 100)
                    if (b["gagnes"] + b["perdus"]) > 0 else 0, 1
                ),
                "pnl_r": round(b["pnl_r"], 2),
                "pnl_avg_r": round(
                    b["pnl_r"] / (b["gagnes"] + b["perdus"])
                    if (b["gagnes"] + b["perdus"]) > 0 else 0, 2
                ),
            }
            for t, b in sorted(by_type.items())
        },
        "by_direction": {
            d: {
                "trades": b["gagnes"] + b["perdus"] + b["ouverts"],
                "gagnes": b["gagnes"], "perdus": b["perdus"],
                "ouverts": b["ouverts"],
                "winrate": round(
                    (b["gagnes"] / (b["gagnes"] + b["perdus"]) * 100)
                    if (b["gagnes"] + b["perdus"]) > 0 else 0, 1
                ),
                "pnl_r": round(b["pnl_r"], 2),
                "pnl_avg_r": round(
                    b["pnl_r"] / (b["gagnes"] + b["perdus"])
                    if (b["gagnes"] + b["perdus"]) > 0 else 0, 2
                ),
            }
            for d, b in sorted(by_dir.items())
        },
        "best_days": [
            {"date": d, "trades": s["trades"], "gagnes": s["gagnes"],
             "perdus": s["perdus"], "winrate": round(s["winrate"], 1),
             "pnl_r": round(s.get("pnl_r", 0), 2)}
            for d, s in best_days
        ],
        "worst_days": [
            {"date": d, "trades": s["trades"], "gagnes": s["gagnes"],
             "perdus": s["perdus"], "winrate": round(s["winrate"], 1),
             "pnl_r": round(s.get("pnl_r", 0), 2)}
            for d, s in worst_days
        ],
        "all_trades": all_trades,
        "daily_stats": {
            d: {
                "trades": s["trades"], "gagnes": s["gagnes"],
                "perdus": s["perdus"], "ouverts": s["ouverts"],
                "winrate": round(s["winrate"], 1),
                "pnl_r": round(s["pnl_r"], 2),
            }
            for d, s in sorted(daily_stats.items())
        },
    }

    json_path = os.path.join(
        REPORTS_DIR,
        f"optimal_backtest_{args.start}_to_{args.end}.json"
    )
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print()
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
