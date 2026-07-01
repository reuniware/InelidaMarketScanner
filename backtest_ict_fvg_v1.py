"""
backtest_ict_fvg_v1.py — Version 1 (SIMPLE, sans filtres ICT stricts)
======================================================================
Strategie ICT FVG en 5 etapes, version LEGERE :
  1. DOL : PDH/PDL, Asian H/L
  2. Raid oppose (sans validation macro/kill zone/equal HL)
  3. Entree : 1er FVG apres displacement, retracement dans la zone
  4. Hard SL au-dela de la bougie #1 du FVG
  5. TP 50% mi-chemin Entry-DOL, 50% juste avant le Terminus

C'est la version qui a produit 214 trades, 17.8% WR, +105.08R total.
Sauvegarde dans reports/backtest_ict_fvg_v1_results.json
"""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple

DATA_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "reports", "xauusd_m3_20260101_to_20260627.json",
)

USE_PDH_PDL = True
USE_ASIAN_HL = True
FVG_MIN_SIZE_PCT = 0.02
MAX_FVG_LOOKFORWARD = 240
MAX_RETRACE_LOOKFORWARD = 120
MAX_RAID_LOOKBACK = 480
MIN_DOL_DISTANCE_PCT = 0.15

UTC = timezone.utc


# ==============================================================================
# DATA LOADING
# ==============================================================================

def load_bars(path: str) -> List[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    bars = data["bars"]
    for b in bars:
        b.setdefault("tick_volume", 0)
        b.setdefault("spread", 0)
    print(f"Charge : {len(bars)} barres {data.get('timeframe','?')} "
          f"({data.get('start_date','?')} -> {data.get('end_date','?')})")
    return bars


def group_bars_by_day(bars: List[dict]) -> Dict[str, List[dict]]:
    days = defaultdict(list)
    for b in bars:
        dt = datetime.fromtimestamp(b["time"], tz=UTC)
        day_key = dt.strftime("%Y-%m-%d")
        days[day_key].append(b)
    return dict(days)


def get_day_session(bars: List[dict], start_h: int, end_h: int) -> List[dict]:
    return [
        b for b in bars
        if start_h <= datetime.fromtimestamp(b["time"], tz=UTC).hour < end_h
    ]


def is_weekend(day_str: str) -> bool:
    dt = datetime.strptime(day_str, "%Y-%m-%d").replace(tzinfo=UTC)
    return dt.weekday() >= 5


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

def compute_dol_and_opposing(
    day_str: str, all_days: Dict[str, List[dict]], bars_today: List[dict],
) -> List[dict]:
    pairs = []

    prev_day = _previous_trading_day(day_str, all_days)
    prev_bars = all_days.get(prev_day) if prev_day else None
    pdh = max(b["high"] for b in prev_bars) if prev_bars else None
    pdl = min(b["low"] for b in prev_bars) if prev_bars else None

    asian_bars = get_day_session(bars_today, 0, 8)
    ah = max(b["high"] for b in asian_bars) if len(asian_bars) >= 2 else None
    al = min(b["low"] for b in asian_bars) if len(asian_bars) >= 2 else None

    if USE_PDH_PDL and pdh is not None and pdl is not None:
        pairs.append({"dol_level": pdh, "dol_label": f"PDH({prev_day})",
                       "dol_direction": "bull",
                       "opposing_level": pdl, "opposing_label": f"PDL({prev_day})",
                       "opposing_raid_type": "ssl"})
        pairs.append({"dol_level": pdl, "dol_label": f"PDL({prev_day})",
                       "dol_direction": "bear",
                       "opposing_level": pdh, "opposing_label": f"PDH({prev_day})",
                       "opposing_raid_type": "bsl"})

    if USE_ASIAN_HL and ah is not None and al is not None:
        pairs.append({"dol_level": ah, "dol_label": f"AH({day_str})",
                       "dol_direction": "bull",
                       "opposing_level": al, "opposing_label": f"AL({day_str})",
                       "opposing_raid_type": "ssl"})
        pairs.append({"dol_level": al, "dol_label": f"AL({day_str})",
                       "dol_direction": "bear",
                       "opposing_level": ah, "opposing_label": f"AH({day_str})",
                       "opposing_raid_type": "bsl"})

    return pairs


# ==============================================================================
# RAID DETECTION (ETAPE 2)
# ==============================================================================

def is_ssl_raid(bar: dict, level: float) -> bool:
    return bar["low"] < level and bar["close"] > level


def is_bsl_raid(bar: dict, level: float) -> bool:
    return bar["high"] > level and bar["close"] < level


def find_raid_of_level(
    bars: List[dict], ref_idx: int, level: float, raid_type: str,
    max_lookback: int = MAX_RAID_LOOKBACK,
) -> Optional[Tuple[int, dict]]:
    search_start = max(0, ref_idx - max_lookback)
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
        gap_top = c3["low"]
        gap_bottom = c1["high"]
    else:
        if c1["low"] <= c3["high"]:
            return None
        gap_top = c1["low"]
        gap_bottom = c3["high"]

    gap_size = gap_top - gap_bottom
    if gap_bottom <= 0 or gap_size <= 0:
        return None
    gap_pct = gap_size / gap_bottom * 100
    if gap_pct < FVG_MIN_SIZE_PCT:
        return None

    return {
        "type": "bullish" if direction == "bull" else "bearish",
        "zone_top": gap_top, "zone_bottom": gap_bottom,
        "c1_bar": c1, "c3_bar": c3,
        "gap_size": gap_size, "gap_pct": gap_pct,
    }


def scan_first_fvg_after(
    bars: List[dict], start_idx: int, direction: str,
    max_look: int = MAX_FVG_LOOKFORWARD,
) -> Optional[Tuple[int, dict]]:
    end_idx = min(start_idx + max_look + 1, len(bars))
    for i in range(start_idx + 3, end_idx):
        fvg = find_fvg_at(bars, i, direction)
        if fvg is not None:
            return (i, fvg)
    return None


def wait_for_fvg_retrace(
    bars: List[dict], fvg_idx: int, fvg: dict, direction: str,
    max_look: int = MAX_RETRACE_LOOKFORWARD,
) -> Optional[Tuple[int, float]]:
    zone_top = fvg["zone_top"]
    zone_bottom = fvg["zone_bottom"]
    entry_target = (zone_top + zone_bottom) / 2
    end_idx = min(fvg_idx + max_look + 1, len(bars))
    for i in range(fvg_idx + 1, end_idx):
        bar = bars[i]
        if bar["low"] <= entry_target <= bar["high"]:
            return (i, entry_target)
    return None


# ==============================================================================
# TRADE SIMULATION (ETAPE 4 & 5)
# ==============================================================================

def simulate_trade(
    bars: List[dict], entry_idx: int, entry_price: float,
    sl_price: float, tp1_price: float, tp2_price: float, direction: str,
) -> dict:
    result = {
        "entry_price": entry_price, "sl_price": sl_price,
        "tp1_price": tp1_price, "tp2_price": tp2_price,
        "direction": direction, "status": "OPEN", "pnl_r": 0.0,
        "tp1_hit": False, "tp2_hit": False, "sl_hit": False,
        "exit_time": None,
    }

    risk = abs(entry_price - sl_price)
    if risk == 0:
        result["status"] = "INVALID"
        return result

    for i in range(entry_idx + 1, len(bars)):
        bar = bars[i]

        if direction == "bull":
            if bar["low"] <= sl_price:
                result.update(status="LOSS", sl_hit=True, exit_time=bar["time"], pnl_r=-1.0)
                break
            if not result["tp1_hit"] and bar["high"] >= tp1_price:
                result["tp1_hit"] = True
                result["exit_time"] = bar["time"]
            if result["tp1_hit"] and bar["high"] >= tp2_price:
                r1 = (tp1_price - entry_price) / risk
                r2 = (tp2_price - entry_price) / risk
                result.update(status="WIN_FULL", tp2_hit=True, exit_time=bar["time"],
                              pnl_r=0.5 * r1 + 0.5 * r2)
                break
        else:
            if bar["high"] >= sl_price:
                result.update(status="LOSS", sl_hit=True, exit_time=bar["time"], pnl_r=-1.0)
                break
            if not result["tp1_hit"] and bar["low"] <= tp1_price:
                result["tp1_hit"] = True
                result["exit_time"] = bar["time"]
            if result["tp1_hit"] and bar["low"] <= tp2_price:
                r1 = (entry_price - tp1_price) / risk
                r2 = (entry_price - tp2_price) / risk
                result.update(status="WIN_FULL", tp2_hit=True, exit_time=bar["time"],
                              pnl_r=0.5 * r1 + 0.5 * r2)
                break

    if result["tp1_hit"] and not result["tp2_hit"] and not result["sl_hit"]:
        result["status"] = "WIN_PARTIAL"
        if direction == "bull":
            result["pnl_r"] = 0.5 * (tp1_price - entry_price) / risk
        else:
            result["pnl_r"] = 0.5 * (entry_price - tp1_price) / risk

    return result


# ==============================================================================
# MAIN BACKTEST
# ==============================================================================

def run_backtest(bars: List[dict]) -> dict:
    days = group_bars_by_day(bars)
    trading_days = sorted(d for d in days if not is_weekend(d))
    print(f"Jours de trading : {len(trading_days)}")

    trades = []
    raids_found = 0
    fvgs_found = 0
    retraces_found = 0
    no_fvg = 0
    no_retrace = 0

    for day_str in trading_days:
        day_bars = days[day_str]
        if len(day_bars) < 20:
            continue

        pairs = compute_dol_and_opposing(day_str, days, day_bars)
        if not pairs:
            continue

        day_start_ts = day_bars[0]["time"]
        day_start_idx = next(
            (i for i, b in enumerate(bars) if b["time"] >= day_start_ts), 0)
        day_end_idx = next(
            (i for i, b in enumerate(bars) if b["time"] > day_bars[-1]["time"]),
            len(bars))

        for pair in pairs:
            dol_level = pair["dol_level"]
            opposing_level = pair["opposing_level"]
            opposing_type = pair["opposing_raid_type"]
            is_asian_dol = "AH(" in pair["dol_label"] or "AL(" in pair["dol_label"]

            raid = find_raid_of_level(bars, day_end_idx, opposing_level, opposing_type)
            if raid is None:
                continue

            raids_found += 1
            raid_idx, raid_bar = raid

            if is_asian_dol:
                raid_hour = datetime.fromtimestamp(raid_bar["time"], tz=UTC).hour
                if raid_hour < 8:
                    continue

            fvg_result = scan_first_fvg_after(bars, raid_idx, pair["dol_direction"])
            if fvg_result is None:
                no_fvg += 1
                continue

            fvgs_found += 1
            fvg_idx, fvg = fvg_result

            retrace = wait_for_fvg_retrace(bars, fvg_idx, fvg, pair["dol_direction"])
            if retrace is None:
                no_retrace += 1
                continue

            retraces_found += 1
            entry_idx, entry_price = retrace

            if pair["dol_direction"] == "bull":
                if dol_level <= entry_price:
                    continue
                if (dol_level - entry_price) / entry_price * 100 < MIN_DOL_DISTANCE_PCT:
                    continue
            else:
                if dol_level >= entry_price:
                    continue
                if (entry_price - dol_level) / entry_price * 100 < MIN_DOL_DISTANCE_PCT:
                    continue

            gap_size = fvg["gap_size"]
            if pair["dol_direction"] == "bull":
                sl_price = fvg["c1_bar"]["low"] - gap_size * 0.2
                if sl_price >= entry_price:
                    continue
                tp1_price = entry_price + (dol_level - entry_price) * 0.5
                tp2_price = dol_level - gap_size
            else:
                sl_price = fvg["c1_bar"]["high"] + gap_size * 0.2
                if sl_price <= entry_price:
                    continue
                tp1_price = entry_price - (entry_price - dol_level) * 0.5
                tp2_price = dol_level + gap_size

            result = simulate_trade(
                bars, entry_idx, entry_price, sl_price, tp1_price, tp2_price,
                pair["dol_direction"],
            )

            trades.append({
                "day": day_str,
                "dol_label": pair["dol_label"],
                "dol_level": dol_level,
                "dol_direction": pair["dol_direction"],
                "opposing_label": pair["opposing_label"],
                "opposing_level": opposing_level,
                "raid_time": raid_bar["time"],
                "fvg_time": bars[fvg_idx]["time"] if fvg_idx < len(bars) else 0,
                "fvg_type": fvg["type"],
                "fvg_gap_pct": fvg["gap_pct"],
                "entry_price": entry_price,
                "sl_price": sl_price,
                "tp1_price": tp1_price,
                "tp2_price": tp2_price,
                **result,
            })

    return _compute_stats(trades, raids_found, fvgs_found, retraces_found, no_fvg, no_retrace)


def _compute_stats(trades, raids_found, fvgs_found, retraces_found, no_fvg, no_retrace):
    n = len(trades)
    wins = [t for t in trades if t["status"] in ("WIN_FULL", "WIN_PARTIAL")]
    losses = [t for t in trades if t["status"] == "LOSS"]
    opens = [t for t in trades if t["status"] == "OPEN"]
    full_wins = [t for t in trades if t["status"] == "WIN_FULL"]
    partial_wins = [t for t in trades if t["status"] == "WIN_PARTIAL"]

    n_wins = len(wins)
    n_losses = len(losses)
    n_closed = n_wins + n_losses
    winrate = (n_wins / n_closed * 100) if n_closed > 0 else 0
    avg_r = (sum(t["pnl_r"] for t in trades if t["status"] != "OPEN") / n_closed
             if n_closed > 0 else 0)
    total_r = sum(t["pnl_r"] for t in trades if t["status"] != "OPEN")

    bull = [t for t in trades if t["direction"] == "bull"]
    bear = [t for t in trades if t["direction"] == "bear"]
    bull_closed = [t for t in bull if t["status"] != "OPEN"]
    bear_closed = [t for t in bear if t["status"] != "OPEN"]
    bull_wr = (len([t for t in bull_closed if t["status"].startswith("WIN")])
               / len(bull_closed) * 100) if bull_closed else 0
    bear_wr = (len([t for t in bear_closed if t["status"].startswith("WIN")])
               / len(bear_closed) * 100) if bear_closed else 0

    return {
        "total_trades": n, "wins": n_wins, "losses": n_losses,
        "open": len(opens), "full_wins": len(full_wins),
        "partial_wins": len(partial_wins),
        "winrate_pct": winrate, "avg_r_per_trade": avg_r, "total_r": total_r,
        "bull_trades": len(bull), "bull_winrate_pct": bull_wr,
        "bear_trades": len(bear), "bear_winrate_pct": bear_wr,
        "raids_found": raids_found, "fvgs_found": fvgs_found,
        "retraces_found": retraces_found,
        "no_fvg": no_fvg, "no_retrace": no_retrace,
        "trades": trades,
    }


def display_results(stats: dict) -> None:
    print()
    print("=" * 72)
    print("  BACKTEST ICT FVG v1 (SANS FILTRES) — RESULTS")
    print("=" * 72)
    print(f"  Raids detectes     : {stats['raids_found']}")
    print(f"  FVGs trouves       : {stats['fvgs_found']}")
    print(f"  Retracements FVG   : {stats['retraces_found']}")
    print(f"  Sans FVG           : {stats['no_fvg']}")
    print(f"  Sans retracement   : {stats['no_retrace']}")
    print(f"  Trades executes    : {stats['total_trades']}")
    print()
    print(f"  -- PERFORMANCE --")
    print(f"  GAGNES   : {stats['wins']} "
          f"({stats['full_wins']} full, {stats['partial_wins']} partial)")
    print(f"  PERDUS   : {stats['losses']}")
    print(f"  OUVERTS  : {stats['open']}")
    closed = stats['wins'] + stats['losses']
    print(f"  WINRATE  : {stats['winrate_pct']:.1f}% "
          f"({stats['wins']}/{closed} closed)")
    print(f"  AVG R    : {stats['avg_r_per_trade']:+.2f}R")
    print(f"  TOTAL R  : {stats['total_r']:+.2f}R")
    print()
    print(f"  -- PAR DIRECTION --")
    print(f"  BUY  : {stats['bull_trades']} trades, "
          f"WR={stats['bull_winrate_pct']:.1f}%")
    print(f"  SELL : {stats['bear_trades']} trades, "
          f"WR={stats['bear_winrate_pct']:.1f}%")


def main():
    if not os.path.exists(DATA_FILE):
        print(f"[ERREUR] Fichier introuvable : {DATA_FILE}")
        return 1

    print(f"Data : {DATA_FILE}")
    print(f"Config: PDH/PDL={'ON' if USE_PDH_PDL else 'OFF'} "
          f"Asian={'ON' if USE_ASIAN_HL else 'OFF'} "
          f"FVG_min={FVG_MIN_SIZE_PCT}%")

    bars = load_bars(DATA_FILE)
    stats = run_backtest(bars)
    display_results(stats)

    # Sauvegarde dans un fichier SEPARE
    trades_file = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "reports", "backtest_ict_fvg_v1_results.json",
    )
    with open(trades_file, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2, default=str)
    print(f"Resultats sauvegardes : {trades_file}")

    # Calcul du capital final avec 2000 EUR
    capital = 2000.0
    for t in stats["trades"]:
        capital *= (1 + 0.01 * t["pnl_r"])
    print()
    print(f"  -- PROJECTION CAPITAL (1% risque/trade) --")
    print(f"  Capital initial : 2000.00 EUR")
    print(f"  Capital final   : {capital:.2f} EUR")
    print(f"  Gain            : {capital - 2000:+.2f} EUR ({(capital/2000 - 1)*100:+.1f}%)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
