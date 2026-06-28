#!/usr/bin/env python
"""
Backtest ELITE V1+V2 — Scan 23:00 Paris (fermeture NY)
========================================================
Période : 01/01/2026 → 26/06/2026

Simule un scan quotidien à 23:00 heure de Paris (fermeture NY),
avec gestion du changement d'heure été/hiver :
  - Hiver (CET, UTC+1) : 23:00 Paris = 22:00 UTC (01/01 → 28/03/2026)
  - Été   (CEST, UTC+2): 23:00 Paris = 21:00 UTC (29/03 → 26/06/2026)

Filtres appliqués (informatifs, pas bloquants) :
  ELITE V1 : FOREX_USD, INDEX, METAL, FOREX_CROSS | RR >= 0.5
  ELITE V2 : FOREX_USD, INDEX, METAL              | RR >= 0.0

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

# ─── Configuration ──────────────────────────────────────────────────────────
START_DATE = "2026-01-01"
END_DATE = "2026-06-26"

# Heure cible à Paris
PARIS_HOUR = 23
PARIS_MINUTE = 0

# Changement DST Europe 2026 : dimanche 29 mars 2026
DST_SWITCH_DATE = "2026-03-29"

# Filtres ELITE V1 (original)
ELITE_V1_TYPES = {"FOREX_USD", "INDEX", "METAL", "FOREX_CROSS"}
ELITE_V1_MIN_RR = 0.5

# Filtres ELITE V2 (optimisé)
ELITE_V2_TYPES = {"FOREX_USD", "INDEX", "METAL"}
ELITE_V2_MIN_RR = 0.0

FIB_LEVELS_BULL = (1.618, 2.0, 2.618, 3.0, 3.618, 4.0)
FIB_LEVELS_BEAR = (-1.618, -2.0, -2.618, -3.0, -3.618, -4.0)

# ─── Helpers ────────────────────────────────────────────────────────────────

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


def paris_to_utc(date_str: str) -> int:
    """Convertit 23:00 Paris → heure UTC selon DST.
    Avant le 29/03/2026 : CET (UTC+1) → 22:00 UTC
    À partir du 29/03/2026 : CEST (UTC+2) → 21:00 UTC
    """
    dt_date = datetime.strptime(date_str, "%Y-%m-%d")
    dst_switch = datetime.strptime(DST_SWITCH_DATE, "%Y-%m-%d")
    if dt_date < dst_switch:
        utc_h = 22  # Hiver CET
    else:
        utc_h = 21  # Été CEST

    scan_dt = datetime(dt_date.year, dt_date.month, dt_date.day,
                       utc_h, PARIS_MINUTE, 0, tzinfo=UTC)
    return int(scan_dt.timestamp())


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
# ANALYSE D'UN SYMBOLE POUR UN JOUR DONNÉ
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_symbol_for_date(h1_bars: List[dict], symbol: str, date_str: str,
                             scan_epoch: int):
    """Analyse le range asiatique depuis les barres H1.
    Scan en fin de NY → toutes les barres London+NY sont incluses."""
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

    # Sweeps post-Asian jusqu'à l'heure du scan (fin NY)
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

    # Calcul fib_state
    bull_base = asian_high
    bear_base = asian_low
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

    # Range trop serré ?
    midpoint = (asian_high + asian_low) / 2
    range_pct = range_size / midpoint * 100.0 if midpoint > 0 else 0
    if range_pct < 0.05:
        return None

    # Calcul SL et TP
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


# ═══════════════════════════════════════════════════════════════════════════════
# STATS HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def compute_stats(trades: List[dict]) -> dict:
    """Calcule les stats pour une liste de trades."""
    n_g = sum(1 for t in trades if t["outcome"] == "GAGNE")
    n_p = sum(1 for t in trades if t["outcome"] == "PERDU")
    n_o = sum(1 for t in trades if t["outcome"] == "OUVERT")
    n_nd = sum(1 for t in trades if t["outcome"] == "NO_DATA")
    n_clos = n_g + n_p
    wr = (n_g / n_clos * 100) if n_clos > 0 else 0

    # R moyen
    rrs = [t["rr"] for t in trades if t["outcome"] in ("GAGNE", "PERDU")]
    pnls = []
    for t in trades:
        if t["outcome"] == "GAGNE":
            pnls.append(t["rr"])
        elif t["outcome"] == "PERDU":
            pnls.append(-1.0)
    avg_pnl = sum(pnls) / len(pnls) if pnls else 0

    return {
        "total": len(trades), "gagnes": n_g, "perdus": n_p,
        "ouverts": n_o, "no_data": n_nd, "winrate": round(wr, 1),
        "avg_pnl_r": round(avg_pnl, 2),
    }


def monthly_stats(trades: List[dict]) -> dict:
    monthly = defaultdict(lambda: {"gagnes": 0, "perdus": 0, "ouverts": 0, "trades": 0})
    for t in trades:
        m = t["date"][:7]
        monthly[m]["trades"] += 1
        if t["outcome"] == "GAGNE": monthly[m]["gagnes"] += 1
        elif t["outcome"] == "PERDU": monthly[m]["perdus"] += 1
        else: monthly[m]["ouverts"] += 1
    result = {}
    for m, v in sorted(monthly.items()):
        closed = v["gagnes"] + v["perdus"]
        wr = (v["gagnes"] / closed * 100) if closed > 0 else 0
        result[m] = {**v, "winrate": round(wr, 1)}
    return result


def type_stats(trades: List[dict]) -> dict:
    by_type = defaultdict(lambda: {"gagnes": 0, "perdus": 0, "ouverts": 0})
    for t in trades:
        st = t["symbol_type"]
        if t["outcome"] == "GAGNE": by_type[st]["gagnes"] += 1
        elif t["outcome"] == "PERDU": by_type[st]["perdus"] += 1
        else: by_type[st]["ouverts"] += 1
    result = {}
    for t, b in sorted(by_type.items()):
        closed = b["gagnes"] + b["perdus"]
        wr = (b["gagnes"] / closed * 100) if closed > 0 else 0
        result[t] = {
            "trades": b["gagnes"] + b["perdus"] + b["ouverts"],
            "gagnes": b["gagnes"], "perdus": b["perdus"],
            "ouverts": b["ouverts"], "winrate": round(wr, 1),
        }
    return result


def dir_stats(trades: List[dict]) -> dict:
    by_dir = defaultdict(lambda: {"gagnes": 0, "perdus": 0, "ouverts": 0})
    for t in trades:
        d = t["action"]
        if t["outcome"] == "GAGNE": by_dir[d]["gagnes"] += 1
        elif t["outcome"] == "PERDU": by_dir[d]["perdus"] += 1
        else: by_dir[d]["ouverts"] += 1
    result = {}
    for d, b in sorted(by_dir.items()):
        closed = b["gagnes"] + b["perdus"]
        wr = (b["gagnes"] / closed * 100) if closed > 0 else 0
        result[d] = {
            "trades": b["gagnes"] + b["perdus"] + b["ouverts"],
            "gagnes": b["gagnes"], "perdus": b["perdus"],
            "ouverts": b["ouverts"], "winrate": round(wr, 1),
        }
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print()
    print("=" * 90)
    print("  BACKTEST ELITE V1+V2 — SCAN 23:00 PARIS (FERMETURE NY)")
    print(f"  Période   : {START_DATE} → {END_DATE}")
    print(f"  Scan      : 23:00 heure de Paris (22:00 UTC hiver / 21:00 UTC été)")
    print(f"  ELITE V1  : types {sorted(ELITE_V1_TYPES)} | RR >= {ELITE_V1_MIN_RR}")
    print(f"  ELITE V2  : types {sorted(ELITE_V2_TYPES)} | RR >= {ELITE_V2_MIN_RR}")
    print(f"  Backtest  : M5 (20000 barres, fallback M15)")
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
    start_dt = datetime(2026, 1, 1, tzinfo=UTC)
    end_dt = datetime(2026, 6, 26, tzinfo=UTC)
    trading_days = []
    current = start_dt
    while current <= end_dt:
        if current.weekday() < 5:
            trading_days.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    print(f"  {len(trading_days)} jours de trading (lun-ven).")
    print()

    # ── Cache H1 par symbole ───────────────────────────────────────────
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

    # ── Scan quotidien + backtest ──────────────────────────────────────
    print("[5/6] Scan quotidien à 23:00 Paris + backtest M5...")
    print()

    all_trades = []     # tous les trades (sans filtre)
    elite_v1_trades = []  # trades passant le filtre ELITE V1
    elite_v2_trades = []  # trades passant le filtre ELITE V2
    daily_stats = {}
    total_setups = 0

    for day_idx, date_str in enumerate(trading_days):
        scan_epoch = paris_to_utc(date_str)

        # Afficher l'heure UTC pour ce jour
        utc_h = datetime.fromtimestamp(scan_epoch, UTC).hour
        utc_label = f"{utc_h:02d}:00 UTC"

        day_all = []
        day_v1 = []
        day_v2 = []

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

                day_all.append(result)
                all_trades.append(result)

                # Filtre ELITE V1
                if (result["symbol_type"] in ELITE_V1_TYPES
                        and result["rr"] >= ELITE_V1_MIN_RR):
                    day_v1.append(result)
                    # Marquer comme elite v1 mais ne pas dupliquer dans elite_v1_trades
                    result["is_elite_v1"] = True
                else:
                    result["is_elite_v1"] = False

                # Filtre ELITE V2
                if (result["symbol_type"] in ELITE_V2_TYPES
                        and result["rr"] >= ELITE_V2_MIN_RR):
                    day_v2.append(result)
                    result["is_elite_v2"] = True
                else:
                    result["is_elite_v2"] = False

            except Exception:
                continue

        # Ajouter aux listes globales (chaque trade peut être dans les deux filtres)
        elite_v1_trades.extend(day_v1)
        elite_v2_trades.extend(day_v2)

        # Stats quotidiennes
        if day_all:
            n_g = sum(1 for t in day_all if t["outcome"] == "GAGNE")
            n_p = sum(1 for t in day_all if t["outcome"] == "PERDU")
            n_o = sum(1 for t in day_all if t["outcome"] == "OUVERT")
            n_clos = n_g + n_p
            wr_all = (n_g / n_clos * 100) if n_clos > 0 else 0

            n_g1 = sum(1 for t in day_v1 if t["outcome"] == "GAGNE")
            n_p1 = sum(1 for t in day_v1 if t["outcome"] == "PERDU")
            n_clos1 = n_g1 + n_p1
            wr_v1 = (n_g1 / n_clos1 * 100) if n_clos1 > 0 else 0

            n_g2 = sum(1 for t in day_v2 if t["outcome"] == "GAGNE")
            n_p2 = sum(1 for t in day_v2 if t["outcome"] == "PERDU")
            n_clos2 = n_g2 + n_p2
            wr_v2 = (n_g2 / n_clos2 * 100) if n_clos2 > 0 else 0

            daily_stats[date_str] = {
                "utc_hour": utc_h,
                "all": {"trades": len(day_all), "wr": round(wr_all, 1)},
                "v1": {"trades": len(day_v1), "wr": round(wr_v1, 1)},
                "v2": {"trades": len(day_v2), "wr": round(wr_v2, 1)},
            }

            print(f"  {date_str} ({utc_label}) : "
                  f"{len(day_all):3d} setups | "
                  f"V1: {len(day_v1):2d} (WR {wr_v1:.0f}%) | "
                  f"V2: {len(day_v2):2d} (WR {wr_v2:.0f}%)")
        else:
            daily_stats[date_str] = {
                "utc_hour": utc_h,
                "all": {"trades": 0, "wr": 0},
                "v1": {"trades": 0, "wr": 0},
                "v2": {"trades": 0, "wr": 0},
            }

        total_setups += len(day_all)

        if day_idx % 10 == 9:
            time.sleep(0.2)

    # ── Statistiques globales ───────────────────────────────────────────
    print()
    print("[6/6] Calcul des statistiques...")
    print()

    stats_all = compute_stats(all_trades)
    stats_v1 = compute_stats(elite_v1_trades)
    stats_v2 = compute_stats(elite_v2_trades)

    monthly_all = monthly_stats(all_trades)
    monthly_v1 = monthly_stats(elite_v1_trades)
    monthly_v2 = monthly_stats(elite_v2_trades)

    type_all = type_stats(all_trades)
    type_v1 = type_stats(elite_v1_trades)
    type_v2 = type_stats(elite_v2_trades)

    dir_all = dir_stats(all_trades)
    dir_v1 = dir_stats(elite_v1_trades)
    dir_v2 = dir_stats(elite_v2_trades)

    # ── Rapport console ─────────────────────────────────────────────────
    print("=" * 90)
    print("  RAPPORT FINAL — BACKTEST ELITE V1+V2 @ 23:00 PARIS (NY CLOSE)")
    print("=" * 90)
    print()
    print(f"  Période          : {START_DATE} → {END_DATE}")
    print(f"  Heure scan       : 23:00 Paris (22:00 UTC hiver / 21:00 UTC été)")
    print(f"  Jours de trading : {len(trading_days)}")
    print(f"  Symboles scannés : {len(symbols_ok)} (avec données H1)")
    print(f"  Total setups     : {total_setups}")
    print()

    def print_filter_stats(label, stats):
        print(f"  {'─' * 70}")
        print(f"  {label}")
        print(f"  {'─' * 70}")
        print(f"  Total trades       : {stats['total']}")
        print(f"  [GAGNÉS]           : {stats['gagnes']}")
        print(f"  [PERDUS]           : {stats['perdus']}")
        print(f"  [OUVERTS]          : {stats['ouverts']}")
        print(f"  [NO DATA]          : {stats['no_data']}")
        print(f"  [WINRATE CLOS]     : {stats['winrate']}% ({stats['gagnes']}/{stats['gagnes']+stats['perdus']})")
        print(f"  [P&L MOYEN]        : {stats['avg_pnl_r']}R/trade")
        print()

    print_filter_stats("TOUS LES TRADES (sans filtre)", stats_all)
    print_filter_stats(f"ELITE V1 (types={sorted(ELITE_V1_TYPES)}, RR>={ELITE_V1_MIN_RR})", stats_v1)
    print_filter_stats(f"ELITE V2 (types={sorted(ELITE_V2_TYPES)}, RR>={ELITE_V2_MIN_RR})", stats_v2)

    # Tableau comparatif
    print(f"  {'─' * 70}")
    print(f"  COMPARAISON V1 vs V2")
    print(f"  {'─' * 70}")
    print(f"  {'Filtre':<20} {'Trades':>7} {'Clos':>6} {'WR':>8} {'P&L/R':>8}")
    print(f"  {'─' * 50}")
    print(f"  {'AUCUN':<20} {stats_all['total']:>7} "
          f"{stats_all['gagnes']+stats_all['perdus']:>6} "
          f"{stats_all['winrate']:>7.1f}% {stats_all['avg_pnl_r']:>7.2f}")
    print(f"  {'ELITE V1':<20} {stats_v1['total']:>7} "
          f"{stats_v1['gagnes']+stats_v1['perdus']:>6} "
          f"{stats_v1['winrate']:>7.1f}% {stats_v1['avg_pnl_r']:>7.2f}")
    print(f"  {'ELITE V2':<20} {stats_v2['total']:>7} "
          f"{stats_v2['gagnes']+stats_v2['perdus']:>6} "
          f"{stats_v2['winrate']:>7.1f}% {stats_v2['avg_pnl_r']:>7.2f}")
    print()

    # Winrate mensuel
    print(f"  {'─' * 70}")
    print(f"  WINRATE MENSUEL — ELITE V2")
    print(f"  {'─' * 70}")
    print(f"  {'Mois':<10} {'Trades':>7} {'Gagnés':>7} {'Perdus':>7} {'Ouverts':>8} {'Winrate':>8}")
    for month in sorted(monthly_v2.keys()):
        m = monthly_v2[month]
        print(f"  {month:<10} {m['trades']:>7} {m['gagnes']:>7} {m['perdus']:>7} "
              f"{m['ouverts']:>8} {m['winrate']:>7.1f}%")
    print()

    # Winrate par type (ELITE V2)
    print(f"  {'─' * 70}")
    print(f"  WINRATE PAR TYPE — ELITE V2")
    print(f"  {'─' * 70}")
    for st in sorted(type_v2.keys()):
        t = type_v2[st]
        print(f"  {st:<20} {t['trades']:>4} trades | "
              f"{t['gagnes']:>3}G/{t['perdus']:>3}P | WR {t['winrate']:>5.1f}%")
    print()

    # ── Sauvegarde JSON ────────────────────────────────────────────────
    output = {
        "meta": {
            "description": "Backtest ELITE V1+V2 — scan 23:00 Paris (fermeture NY)",
            "scan_paris_hour": PARIS_HOUR,
            "scan_paris_minute": PARIS_MINUTE,
            "utc_winter": 22,
            "utc_summer": 21,
            "dst_switch": DST_SWITCH_DATE,
            "start_date": START_DATE,
            "end_date": END_DATE,
            "trading_days": len(trading_days),
            "symbols_with_data": len(symbols_ok),
            "elite_v1_types": sorted(ELITE_V1_TYPES),
            "elite_v1_min_rr": ELITE_V1_MIN_RR,
            "elite_v2_types": sorted(ELITE_V2_TYPES),
            "elite_v2_min_rr": ELITE_V2_MIN_RR,
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
        },
        "summary": {
            "all": stats_all,
            "elite_v1": stats_v1,
            "elite_v2": stats_v2,
        },
        "monthly": {
            "all": monthly_all,
            "elite_v1": monthly_v1,
            "elite_v2": monthly_v2,
        },
        "by_type": {
            "all": type_all,
            "elite_v1": type_v1,
            "elite_v2": type_v2,
        },
        "by_direction": {
            "all": dir_all,
            "elite_v1": dir_v1,
            "elite_v2": dir_v2,
        },
        "all_trades": all_trades,
        "daily_stats": {d: s for d, s in sorted(daily_stats.items())},
    }

    json_path = os.path.join(
        REPORTS_DIR,
        f"elite_ny_close_backtest_{START_DATE}_to_{END_DATE}.json"
    )
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
