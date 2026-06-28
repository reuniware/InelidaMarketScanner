"""
backtest_ict_universal.py — Backtest ICT FVG v1 Universel (tout symbole)
========================================================================
Strategie ICT FVG (version simple, sans filtres stricts) applicable a
n'importe quel symbole.

Usage:
    python backtest_ict_universal.py XAUUSD
    python backtest_ict_universal.py EURUSD
    python backtest_ict_universal.py EURUSD --capital 5000
    python backtest_ict_universal.py XAUUSD --fvg-min 0.03 --dol-min 0.20

Lit automatiquement reports/{symbol}_m3_*.json (le plus recent).
"""

import json
import os
import sys
import argparse
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple

UTC = timezone.utc
REPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")

# --- Parametres par defaut (surchargeables en CLI) ---
FVG_MIN_SIZE_PCT = 0.02
MAX_FVG_LOOKFORWARD = 240
MAX_RETRACE_LOOKFORWARD = 120
MAX_RAID_LOOKBACK = 480
MIN_DOL_DISTANCE_PCT = 0.15
INITIAL_CAPITAL = 2000.0


# ==============================================================================
# DATA LOADING
# ==============================================================================

def find_data_file(symbol: str) -> str:
    """Trouve le fichier de donnees le plus recent pour un symbole donne."""
    prefix = f"{symbol.lower()}_m3_"
    candidates = []
    for f in os.listdir(REPORTS_DIR):
        if f.startswith(prefix) and f.endswith(".json"):
            candidates.append(os.path.join(REPORTS_DIR, f))
    if not candidates:
        raise FileNotFoundError(
            f"Aucun fichier de donnees trouve pour {symbol} dans {REPORTS_DIR}\n"
            f"  Lance d'abord: python download_historical.py {symbol}")
    candidates.sort(key=os.path.getmtime, reverse=True)
    return candidates[0]


def load_bars(path: str) -> List[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    bars = data["bars"]
    for b in bars:
        b.setdefault("tick_volume", 0)
        b.setdefault("spread", 0)
    return bars


def group_bars_by_day(bars: List[dict]) -> Dict[str, List[dict]]:
    days = defaultdict(list)
    for b in bars:
        dt = datetime.fromtimestamp(b["time"], tz=UTC)
        day_key = dt.strftime("%Y-%m-%d")
        days[day_key].append(b)
    return dict(days)


def get_day_session(bars: List[dict], start_h: int, end_h: int) -> List[dict]:
    return [b for b in bars
            if start_h <= datetime.fromtimestamp(b["time"], tz=UTC).hour < end_h]


def is_weekend(day_str: str) -> bool:
    return datetime.strptime(day_str, "%Y-%m-%d").replace(tzinfo=UTC).weekday() >= 5


def _previous_trading_day(day_str: str, all_days: Dict) -> Optional[str]:
    dt = datetime.strptime(day_str, "%Y-%m-%d").replace(tzinfo=UTC)
    for _ in range(5):
        dt = dt - timedelta(days=1)
        candidate = dt.strftime("%Y-%m-%d")
        if candidate in all_days and not is_weekend(candidate):
            return candidate
    return None


# ==============================================================================
# DOL (ETAPE 1)
# ==============================================================================

def compute_dol_pairs(day_str: str, all_days: Dict, bars_today: List[dict]) -> List[dict]:
    pairs = []
    prev_day = _previous_trading_day(day_str, all_days)
    prev_bars = all_days.get(prev_day) if prev_day else None
    pdh = max(b["high"] for b in prev_bars) if prev_bars else None
    pdl = min(b["low"] for b in prev_bars) if prev_bars else None

    asian_bars = get_day_session(bars_today, 0, 8)
    ah = max(b["high"] for b in asian_bars) if len(asian_bars) >= 2 else None
    al = min(b["low"] for b in asian_bars) if len(asian_bars) >= 2 else None

    if pdh is not None and pdl is not None:
        pairs.append({"dol": pdh, "label": f"PDH({prev_day})", "dir": "bull",
                       "opposing": pdl, "opp_label": f"PDL({prev_day})", "raid_type": "ssl"})
        pairs.append({"dol": pdl, "label": f"PDL({prev_day})", "dir": "bear",
                       "opposing": pdh, "opp_label": f"PDH({prev_day})", "raid_type": "bsl"})

    if ah is not None and al is not None:
        pairs.append({"dol": ah, "label": f"AH({day_str})", "dir": "bull",
                       "opposing": al, "opp_label": f"AL({day_str})", "raid_type": "ssl"})
        pairs.append({"dol": al, "label": f"AL({day_str})", "dir": "bear",
                       "opposing": ah, "opp_label": f"AH({day_str})", "raid_type": "bsl"})

    return pairs


# ==============================================================================
# RAID DETECTION (ETAPE 2)
# ==============================================================================

def is_ssl_raid(bar: dict, level: float) -> bool:
    return bar["low"] < level and bar["close"] > level


def is_bsl_raid(bar: dict, level: float) -> bool:
    return bar["high"] > level and bar["close"] < level


def find_raid(bars: List[dict], ref_idx: int, level: float, raid_type: str) -> Optional[Tuple[int, dict]]:
    search_start = max(0, ref_idx - MAX_RAID_LOOKBACK)
    check_fn = is_ssl_raid if raid_type == "ssl" else is_bsl_raid
    for i in range(ref_idx - 1, search_start - 1, -1):
        if check_fn(bars[i], level):
            return (i, bars[i])
    return None


# ==============================================================================
# FVG DETECTION (ETAPE 3)
# ==============================================================================

def find_fvg_at(bars: List[dict], idx: int, direction: str) -> Optional[dict]:
    if idx < 2:
        return None
    c1 = bars[idx - 2]
    c3 = bars[idx]

    if direction == "bull":
        if c1["high"] >= c3["low"]:
            return None
        gap_top, gap_bottom = c3["low"], c1["high"]
    else:
        if c1["low"] <= c3["high"]:
            return None
        gap_top, gap_bottom = c1["low"], c3["high"]

    gap_size = gap_top - gap_bottom
    if gap_bottom <= 0 or gap_size <= 0:
        return None
    gap_pct = gap_size / gap_bottom * 100
    if gap_pct < FVG_MIN_SIZE_PCT:
        return None

    return {"type": "bullish" if direction == "bull" else "bearish",
            "zone_top": gap_top, "zone_bottom": gap_bottom,
            "c1": c1, "c3": c3, "gap_size": gap_size, "gap_pct": gap_pct}


def scan_first_fvg(bars: List[dict], start_idx: int, direction: str) -> Optional[Tuple[int, dict]]:
    end_idx = min(start_idx + MAX_FVG_LOOKFORWARD + 1, len(bars))
    for i in range(start_idx + 3, end_idx):
        fvg = find_fvg_at(bars, i, direction)
        if fvg is not None:
            return (i, fvg)
    return None


def wait_retrace(bars: List[dict], fvg_idx: int, fvg: dict) -> Optional[Tuple[int, float]]:
    entry_target = (fvg["zone_top"] + fvg["zone_bottom"]) / 2
    end_idx = min(fvg_idx + MAX_RETRACE_LOOKFORWARD + 1, len(bars))
    for i in range(fvg_idx + 1, end_idx):
        bar = bars[i]
        if bar["low"] <= entry_target <= bar["high"]:
            return (i, entry_target)
    return None


# ==============================================================================
# TRADE SIMULATION (ETAPE 4 & 5)
# ==============================================================================

def simulate(bars: List[dict], entry_idx: int, entry: float, sl: float,
             tp1: float, tp2: float, direction: str) -> dict:
    result = {"entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2,
              "dir": direction, "status": "OPEN", "pnl_r": 0.0,
              "tp1_hit": False, "tp2_hit": False, "sl_hit": False, "exit_time": None}

    risk = abs(entry - sl)
    if risk == 0:
        result["status"] = "INVALID"
        return result

    for i in range(entry_idx + 1, len(bars)):
        bar = bars[i]
        if direction == "bull":
            if bar["low"] <= sl:
                result.update(status="LOSS", sl_hit=True, exit_time=bar["time"], pnl_r=-1.0)
                break
            if not result["tp1_hit"] and bar["high"] >= tp1:
                result["tp1_hit"] = True; result["exit_time"] = bar["time"]
            if result["tp1_hit"] and bar["high"] >= tp2:
                r1 = (tp1 - entry) / risk; r2 = (tp2 - entry) / risk
                result.update(status="WIN_FULL", tp2_hit=True, exit_time=bar["time"],
                              pnl_r=0.5 * r1 + 0.5 * r2)
                break
        else:
            if bar["high"] >= sl:
                result.update(status="LOSS", sl_hit=True, exit_time=bar["time"], pnl_r=-1.0)
                break
            if not result["tp1_hit"] and bar["low"] <= tp1:
                result["tp1_hit"] = True; result["exit_time"] = bar["time"]
            if result["tp1_hit"] and bar["low"] <= tp2:
                r1 = (entry - tp1) / risk; r2 = (entry - tp2) / risk
                result.update(status="WIN_FULL", tp2_hit=True, exit_time=bar["time"],
                              pnl_r=0.5 * r1 + 0.5 * r2)
                break

    if result["tp1_hit"] and not result["tp2_hit"] and not result["sl_hit"]:
        result["status"] = "WIN_PARTIAL"
        result["pnl_r"] = 0.5 * (tp1 - entry) / risk if direction == "bull" else 0.5 * (entry - tp1) / risk
    return result


# ==============================================================================
# BACKTEST ENGINE
# ==============================================================================

def run_backtest(bars: List[dict]) -> dict:
    days = group_bars_by_day(bars)
    trading_days = sorted(d for d in days if not is_weekend(d))
    trades = []
    counters = {"raids": 0, "fvg": 0, "retrace": 0, "no_fvg": 0, "no_retrace": 0}

    for day_str in trading_days:
        day_bars = days[day_str]
        if len(day_bars) < 20:
            continue

        pairs = compute_dol_pairs(day_str, days, day_bars)
        day_start_ts = day_bars[0]["time"]
        day_start_idx = next((i for i, b in enumerate(bars) if b["time"] >= day_start_ts), 0)
        day_end_idx = next((i for i, b in enumerate(bars) if b["time"] > day_bars[-1]["time"]), len(bars))

        for p in pairs:
            raid = find_raid(bars, day_end_idx, p["opposing"], p["raid_type"])
            if raid is None:
                continue
            counters["raids"] += 1
            raid_idx, raid_bar = raid

            if "AH(" in p["label"] or "AL(" in p["label"]:
                if datetime.fromtimestamp(raid_bar["time"], tz=UTC).hour < 8:
                    continue

            fvg_res = scan_first_fvg(bars, raid_idx, p["dir"])
            if fvg_res is None:
                counters["no_fvg"] += 1
                continue
            counters["fvg"] += 1
            fvg_idx, fvg = fvg_res

            ret = wait_retrace(bars, fvg_idx, fvg)
            if ret is None:
                counters["no_retrace"] += 1
                continue
            counters["retrace"] += 1
            entry_idx, entry = ret

            if p["dir"] == "bull":
                if p["dol"] <= entry:
                    continue
                if (p["dol"] - entry) / entry * 100 < MIN_DOL_DISTANCE_PCT:
                    continue
                sl = fvg["c1"]["low"] - fvg["gap_size"] * 0.2
                if sl >= entry:
                    continue
                tp1 = entry + (p["dol"] - entry) * 0.5
                tp2 = p["dol"] - fvg["gap_size"]
            else:
                if p["dol"] >= entry:
                    continue
                if (entry - p["dol"]) / entry * 100 < MIN_DOL_DISTANCE_PCT:
                    continue
                sl = fvg["c1"]["high"] + fvg["gap_size"] * 0.2
                if sl <= entry:
                    continue
                tp1 = entry - (entry - p["dol"]) * 0.5
                tp2 = p["dol"] + fvg["gap_size"]

            result = simulate(bars, entry_idx, entry, sl, tp1, tp2, p["dir"])
            trades.append({
                "day": day_str, "dol_label": p["label"], "dol_level": p["dol"],
                "dol_direction": p["dir"], "opposing_label": p["opp_label"],
                "opposing_level": p["opposing"], "raid_time": raid_bar["time"],
                "fvg_time": bars[fvg_idx]["time"], "fvg_type": fvg["type"],
                "fvg_gap_pct": fvg["gap_pct"], "entry_price": entry,
                "sl_price": sl, "tp1_price": tp1, "tp2_price": tp2, **result,
            })

    return _stats(trades, counters)


def _stats(trades, counters):
    n = len(trades)
    wins = [t for t in trades if t["status"].startswith("WIN")]
    losses = [t for t in trades if t["status"] == "LOSS"]
    closed = len(wins) + len(losses)
    wr = (len(wins) / closed * 100) if closed > 0 else 0
    avg_r = (sum(t["pnl_r"] for t in trades if t["status"] != "OPEN") / closed) if closed > 0 else 0
    total_r = sum(t["pnl_r"] for t in trades if t["status"] != "OPEN")

    bull = [t for t in trades if t["dol_direction"] == "bull"]
    bear = [t for t in trades if t["dol_direction"] == "bear"]
    bull_closed = [t for t in bull if t["status"] != "OPEN"]
    bear_closed = [t for t in bear if t["status"] != "OPEN"]

    return {
        "total_trades": n, "wins": len(wins), "losses": len(losses),
        "full_wins": len([t for t in wins if t["status"] == "WIN_FULL"]),
        "partial_wins": len([t for t in wins if t["status"] == "WIN_PARTIAL"]),
        "winrate_pct": wr, "avg_r_per_trade": avg_r, "total_r": total_r,
        "bull_trades": len(bull),
        "bull_wr": (len([t for t in bull_closed if t["status"].startswith("WIN")]) / len(bull_closed) * 100) if bull_closed else 0,
        "bear_trades": len(bear),
        "bear_wr": (len([t for t in bear_closed if t["status"].startswith("WIN")]) / len(bear_closed) * 100) if bear_closed else 0,
        "raids": counters["raids"], "fvg": counters["fvg"], "retrace": counters["retrace"],
        "no_fvg": counters["no_fvg"], "no_retrace": counters["no_retrace"],
        "trades": trades,
    }


# ==============================================================================
# DISPLAY
# ==============================================================================

def display(stats: dict, symbol: str, capital: float) -> None:
    print()
    print("=" * 72)
    print(f"  BACKTEST ICT FVG (v1) — {symbol}")
    print("=" * 72)
    print(f"  Raids detectes   : {stats['raids']}")
    print(f"  FVGs trouves     : {stats['fvg']}")
    print(f"  Retracements     : {stats['retrace']}")
    print(f"  Sans FVG         : {stats['no_fvg']}")
    print(f"  Sans retrace     : {stats['no_retrace']}")
    print(f"  Trades executes  : {stats['total_trades']}")
    print()
    print(f"  -- PERFORMANCE --")
    print(f"  GAGNES : {stats['wins']} "
          f"({stats['full_wins']} full, {stats['partial_wins']} partial)")
    print(f"  PERDUS : {stats['losses']}")
    print(f"  WR     : {stats['winrate_pct']:.1f}% "
          f"({stats['wins']}/{stats['wins']+stats['losses']})")
    print(f"  AVG R  : {stats['avg_r_per_trade']:+.2f}R")
    print(f"  TOTAL R: {stats['total_r']:+.2f}R")
    print()
    print(f"  BUY  : {stats['bull_trades']} trades, WR={stats['bull_wr']:.1f}%")
    print(f"  SELL : {stats['bear_trades']} trades, WR={stats['bear_wr']:.1f}%")

    # Capital
    cap = capital
    for t in stats["trades"]:
        cap *= (1 + 0.01 * t["pnl_r"])
    print()
    print(f"  -- PROJECTION CAPITAL ({capital:.0f} EUR, 1%/trade) --")
    print(f"  Final : {cap:,.2f} EUR ({(cap/capital - 1)*100:+.1f}%)")


# ==============================================================================
# MAIN
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Backtest ICT FVG universel (v1 simple) sur donnees M3")
    parser.add_argument("symbol", help="Symbole (ex: XAUUSD, EURUSD)")
    parser.add_argument("--capital", type=float, default=INITIAL_CAPITAL,
                        help=f"Capital initial en EUR (defaut: {INITIAL_CAPITAL})")
    parser.add_argument("--fvg-min", type=float, default=FVG_MIN_SIZE_PCT,
                        help=f"Taille minimum FVG en %% (defaut: {FVG_MIN_SIZE_PCT})")
    parser.add_argument("--dol-min", type=float, default=MIN_DOL_DISTANCE_PCT,
                        help=f"Distance minimum Entry->DOL en %% (defaut: {MIN_DOL_DISTANCE_PCT})")

    args = parser.parse_args()

    # Surcharger les constantes du module
    mod = sys.modules[__name__]
    mod.FVG_MIN_SIZE_PCT = args.fvg_min
    mod.MIN_DOL_DISTANCE_PCT = args.dol_min

    try:
        data_file = find_data_file(args.symbol)
    except FileNotFoundError as e:
        print(e)
        return 1

    print(f"Data   : {data_file}")
    print(f"Config : FVG_min={FVG_MIN_SIZE_PCT}%, DOL_min={MIN_DOL_DISTANCE_PCT}%")
    print(f"Capital: {args.capital:.0f} EUR")

    bars = load_bars(data_file)
    meta = json.load(open(data_file, "r", encoding="utf-8"))
    print(f"Bars   : {len(bars)} ({meta.get('timeframe','?')})")

    stats = run_backtest(bars)
    display(stats, args.symbol, args.capital)

    # Sauvegarde
    out = os.path.join(REPORTS_DIR, f"backtest_ict_{args.symbol.lower()}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nResultats : {out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
