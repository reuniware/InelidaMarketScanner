"""
backtest_ict_fvg.py -- Backtest ICT FVG Strategy on XAUUSD M3 data
==================================================================
Strategie ICT (Inner Circle Trader) :
  1. Determine un Draw On Liquidity (DOL) -- PDH/PDL, Asian H/L
  2. Attend un raid de LIQUIDITE OPPOSEE (pas du DOL lui-meme !)
     - DOL haussier -> attendre SSL raid d'un SUPPORT
     - DOL baissier -> attendre BSL raid d'une RESISTANCE
  3. Entre sur le 1er FVG dans la direction du DOL, APRES retracement
     dans la zone du FVG (pas d'entree immediate)
  4. Hard SL au-dela de la bougie #1 du FVG
  5. TP 50% a mi-chemin Entry-DOL, 50% juste avant le Terminus

Totalement independant du reste du projet. Lit un fichier JSON M3.
"""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple

# --- Configuration -----------------------------------------------------------
DATA_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "reports", "xauusd_m3_2026_01_01_to_2026_06_26.json",
)

USE_PDH_PDL = True
USE_ASIAN_HL = True

MACRO_START_UTC = 12
MACRO_END_UTC = 16
REQUIRE_MACRO = False

FVG_MIN_SIZE_PCT = 0.02
MAX_FVG_LOOKFORWARD = 240       # candles apres raid pour trouver FVG
MAX_RETRACE_LOOKFORWARD = 120   # candles apres FVG pour retracement dans zone
MAX_RAID_LOOKBACK = 480         # max bars (24h M3) pour chercher un raid

MIN_DOL_DISTANCE_PCT = 0.15     # DOL minimum distance from entry

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


# ==============================================================================
# DOL + OPPOSING LEVELS
# ==============================================================================

def compute_dol_and_opposing(
    day_str: str,
    all_days: Dict[str, List[dict]],
    bars_today: List[dict],
) -> List[dict]:
    """Calcule les paires (DOL, niveau oppose) pour un jour donne.

    Chaque entree = {
        'dol_level', 'dol_label', 'dol_direction',
        'opposing_level', 'opposing_label', 'opposing_raid_type'
    }

    - DOL haussier (bull) = target ABOVE -> opposing = SUPPORT (SSL raid)
    - DOL baissier (bear) = target BELOW -> opposing = RESISTANCE (BSL raid)
    """
    pairs = []

    prev_day = _previous_trading_day(day_str, all_days)
    prev_bars = all_days.get(prev_day) if prev_day else None
    pdh = max(b["high"] for b in prev_bars) if prev_bars else None
    pdl = min(b["low"] for b in prev_bars) if prev_bars else None

    asian_bars = get_day_session(bars_today, 0, 8)
    ah = max(b["high"] for b in asian_bars) if len(asian_bars) >= 2 else None
    al = min(b["low"] for b in asian_bars) if len(asian_bars) >= 2 else None

    if USE_PDH_PDL and pdh is not None and pdl is not None:
        # PDH as DOL (bullish) -> opposing = PDL (SSL raid)
        pairs.append({
            "dol_level": pdh, "dol_label": f"PDH({prev_day})",
            "dol_direction": "bull",
            "opposing_level": pdl, "opposing_label": f"PDL({prev_day})",
            "opposing_raid_type": "ssl",
        })
        # PDL as DOL (bearish) -> opposing = PDH (BSL raid)
        pairs.append({
            "dol_level": pdl, "dol_label": f"PDL({prev_day})",
            "dol_direction": "bear",
            "opposing_level": pdh, "opposing_label": f"PDH({prev_day})",
            "opposing_raid_type": "bsl",
        })

    if USE_ASIAN_HL and ah is not None and al is not None:
        # AH as DOL (bullish) -> opposing = AL (SSL raid)
        pairs.append({
            "dol_level": ah, "dol_label": f"AH({day_str})",
            "dol_direction": "bull",
            "opposing_level": al, "opposing_label": f"AL({day_str})",
            "opposing_raid_type": "ssl",
        })
        # AL as DOL (bearish) -> opposing = AH (BSL raid)
        pairs.append({
            "dol_level": al, "dol_label": f"AL({day_str})",
            "dol_direction": "bear",
            "opposing_level": ah, "opposing_label": f"AH({day_str})",
            "opposing_raid_type": "bsl",
        })

    return pairs


def _previous_trading_day(day_str: str, all_days: Dict) -> Optional[str]:
    dt = datetime.strptime(day_str, "%Y-%m-%d").replace(tzinfo=UTC)
    for _ in range(5):
        dt = dt - timedelta(days=1)
        candidate = dt.strftime("%Y-%m-%d")
        if candidate in all_days and not is_weekend(candidate):
            return candidate
    return None


# ==============================================================================
# RAID DETECTION (opposing liquidity)
# ==============================================================================

def is_ssl_raid(bar: dict, level: float) -> bool:
    """SSL raid: prix passe SOUS le niveau + close rejette AU-DESSUS."""
    return bar["low"] < level and bar["close"] > level


def is_bsl_raid(bar: dict, level: float) -> bool:
    """BSL raid: prix passe AU-DESSUS du niveau + close rejette EN-DESSOUS."""
    return bar["high"] > level and bar["close"] < level


def find_raid_of_level(
    bars: List[dict],
    ref_idx: int,
    level: float,
    raid_type: str,
    max_lookback: int = MAX_RAID_LOOKBACK,
) -> Optional[Tuple[int, dict]]:
    """Cherche un raid du niveau donne dans les barres precedant ref_idx.

    raid_type = 'ssl' -> SSL raid (bar.low < level AND bar.close > level)
    raid_type = 'bsl' -> BSL raid (bar.high > level AND bar.close < level)

    Retourne (index_global, bar_du_raid) ou None.
    """
    search_start = max(0, ref_idx - max_lookback)
    check_fn = is_ssl_raid if raid_type == "ssl" else is_bsl_raid

    for i in range(ref_idx - 1, search_start - 1, -1):
        if check_fn(bars[i], level):
            return (i, bars[i])

    return None


# ==============================================================================
# FVG DETECTION
# ==============================================================================

def find_fvg_at(
    bars: List[dict],
    idx: int,
    direction: str,
) -> Optional[dict]:
    """Verifie si un FVG existe a l'index idx (3e bougie du pattern).

    direction = 'bull' -> C[idx-2].high < C[idx].low
    direction = 'bear' -> C[idx-2].low > C[idx].high
    """
    if idx < 2:
        return None
    c1 = bars[idx - 2]
    c2 = bars[idx - 1]
    c3 = bars[idx]

    gap_top = 0.0
    gap_bottom = 0.0

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
    if gap_bottom <= 0:
        return None
    gap_pct = gap_size / gap_bottom * 100
    if gap_pct < FVG_MIN_SIZE_PCT:
        return None

    return {
        "type": "bullish" if direction == "bull" else "bearish",
        "zone_top": gap_top,
        "zone_bottom": gap_bottom,
        "c1_bar": c1,
        "c3_bar": c3,
        "gap_size": gap_size,
        "gap_pct": gap_pct,
    }


def scan_first_fvg_after(
    bars: List[dict],
    start_idx: int,
    direction: str,
    max_look: int = MAX_FVG_LOOKFORWARD,
) -> Optional[Tuple[int, dict]]:
    """Scanne les barres apres start_idx pour le 1er FVG dans la direction.

    Retourne (index_du_FVG, infos_FVG) ou None.
    """
    end_idx = min(start_idx + max_look + 1, len(bars))
    for i in range(start_idx + 3, end_idx):
        fvg = find_fvg_at(bars, i, direction)
        if fvg is not None:
            return (i, fvg)
    return None


# ==============================================================================
# FVG RETRACEMENT (entry trigger)
# ==============================================================================

def wait_for_fvg_retrace(
    bars: List[dict],
    fvg_idx: int,
    fvg: dict,
    direction: str,
    max_look: int = MAX_RETRACE_LOOKFORWARD,
) -> Optional[Tuple[int, float]]:
    """Attend que le prix retrace dans la zone FVG pour entrer.

    Retourne (index_d_entree, prix_entree) ou None si pas de retracement.
    Le prix_entree est le midpoint de la zone FVG.
    On exige que le prix ait EFFECTIVEMENT touche le midpoint.
    """
    zone_top = fvg["zone_top"]
    zone_bottom = fvg["zone_bottom"]
    entry_target = (zone_top + zone_bottom) / 2
    end_idx = min(fvg_idx + max_look + 1, len(bars))

    for i in range(fvg_idx + 1, end_idx):
        bar = bars[i]
        # Verifier que le midpoint est dans le range de la barre
        if bar["low"] <= entry_target <= bar["high"]:
            return (i, entry_target)

    return None


# ==============================================================================
# TRADE SIMULATION
# ==============================================================================

def simulate_trade(
    bars: List[dict],
    entry_idx: int,
    entry_price: float,
    sl_price: float,
    tp1_price: float,
    tp2_price: float,
    direction: str,
) -> dict:
    """Simule un trade en forward-test.

    Retourne dict avec status, pnl_r, etc.
    """
    result = {
        "entry_price": entry_price,
        "sl_price": sl_price,
        "tp1_price": tp1_price,
        "tp2_price": tp2_price,
        "direction": direction,
        "status": "OPEN",
        "pnl_r": 0.0,
        "tp1_hit": False,
        "tp2_hit": False,
        "sl_hit": False,
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
                result.update(status="LOSS", sl_hit=True,
                              exit_time=bar["time"], pnl_r=-1.0)
                break
            if not result["tp1_hit"] and bar["high"] >= tp1_price:
                result["tp1_hit"] = True
                result["exit_time"] = bar["time"]
            if result["tp1_hit"] and bar["high"] >= tp2_price:
                r1 = (tp1_price - entry_price) / risk
                r2 = (tp2_price - entry_price) / risk
                result.update(status="WIN_FULL", tp2_hit=True,
                              exit_time=bar["time"], pnl_r=0.5 * r1 + 0.5 * r2)
                break
        else:
            if bar["high"] >= sl_price:
                result.update(status="LOSS", sl_hit=True,
                              exit_time=bar["time"], pnl_r=-1.0)
                break
            if not result["tp1_hit"] and bar["low"] <= tp1_price:
                result["tp1_hit"] = True
                result["exit_time"] = bar["time"]
            if result["tp1_hit"] and bar["low"] <= tp2_price:
                r1 = (entry_price - tp1_price) / risk
                r2 = (entry_price - tp2_price) / risk
                result.update(status="WIN_FULL", tp2_hit=True,
                              exit_time=bar["time"], pnl_r=0.5 * r1 + 0.5 * r2)
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

            # Filtrer : pour les DOL derives de l'Asian, ne trader qu'apres 08:00 UTC
            is_asian_dol = "AH(" in pair["dol_label"] or "AL(" in pair["dol_label"]

            # Chercher un raid du NIVEAU OPPOSE (pas du DOL !)
            raid = find_raid_of_level(
                bars, day_end_idx, opposing_level, opposing_type)
            if raid is None:
                continue

            raids_found += 1
            raid_idx, raid_bar = raid

            # Filtrer trades Asian declenches avant 08:00 UTC
            if is_asian_dol:
                raid_hour = datetime.fromtimestamp(raid_bar["time"], tz=UTC).hour
                if raid_hour < 8:
                    continue

            # Verifier timing macro
            if REQUIRE_MACRO:
                raid_hour = datetime.fromtimestamp(raid_bar["time"], tz=UTC).hour
                if not (MACRO_START_UTC <= raid_hour < MACRO_END_UTC):
                    continue

            # Chercher le 1er FVG APRES le raid, vers le DOL
            fvg_result = scan_first_fvg_after(
                bars, raid_idx, pair["dol_direction"])
            if fvg_result is None:
                no_fvg += 1
                continue

            fvgs_found += 1
            fvg_idx, fvg = fvg_result

            # Attendre que le prix retrace DANS la zone FVG
            retrace = wait_for_fvg_retrace(
                bars, fvg_idx, fvg, pair["dol_direction"])
            if retrace is None:
                no_retrace += 1
                continue

            retraces_found += 1
            entry_idx, entry_price = retrace

            # Verifier distance DOL suffisante (avec le prix d'entree reel)
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

            # Calculer SL et TPs
            if pair["dol_direction"] == "bull":
                sl_price = fvg["c1_bar"]["low"] - fvg["gap_size"] * 0.2
                if sl_price >= entry_price:
                    continue  # SL invalide
                tp1_price = entry_price + (dol_level - entry_price) * 0.5
                tp2_price = dol_level - fvg["gap_size"]
            else:
                sl_price = fvg["c1_bar"]["high"] + fvg["gap_size"] * 0.2
                if sl_price <= entry_price:
                    continue  # SL invalide
                tp1_price = entry_price - (entry_price - dol_level) * 0.5
                tp2_price = dol_level + fvg["gap_size"]

            # Simuler le trade
            result = simulate_trade(
                bars, entry_idx, entry_price,
                sl_price, tp1_price, tp2_price,
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

    return _compute_stats(trades, raids_found, fvgs_found,
                          retraces_found, no_fvg, no_retrace)


def _compute_stats(trades, raids_found, fvgs_found,
                   retraces_found, no_fvg, no_retrace):
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


# ==============================================================================
# DISPLAY
# ==============================================================================

def display_results(stats: dict) -> None:
    print()
    print("=" * 72)
    print("  BACKTEST ICT FVG STRATEGY -- RESULTS")
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

    if stats["trades"]:
        print()
        print(f"  -- DERNIERS TRADES --")
        for t in stats["trades"][-10:]:
            icons = {"WIN_FULL": "WIN ", "WIN_PARTIAL": "WIN*",
                     "LOSS": "LOSS", "OPEN": "OPEN"}
            icon = icons.get(t["status"], t["status"])
            raid_dt = datetime.fromtimestamp(
                t["raid_time"], tz=UTC).strftime("%m-%d %H:%M")
            print(
                f"  {icon:5} {t['day']} {t['dol_direction']:4} "
                f"DOL={t['dol_label']:<20} "
                f"Opp={t['opposing_label']:<15} "
                f"Raid@{raid_dt} "
                f"RR={t['pnl_r']:+.2f}R"
            )

    print()
    print("=" * 72)


# ==============================================================================
# MAIN
# ==============================================================================

def main():
    if not os.path.exists(DATA_FILE):
        print(f"[ERREUR] Fichier introuvable : {DATA_FILE}")
        return 1

    print(f"Data : {DATA_FILE}")
    print(f"Config: PDH/PDL={'ON' if USE_PDH_PDL else 'OFF'} "
          f"Asian={'ON' if USE_ASIAN_HL else 'OFF'} "
          f"Macro={'ON' if REQUIRE_MACRO else 'OFF'} "
          f"FVG_min={FVG_MIN_SIZE_PCT}%")

    bars = load_bars(DATA_FILE)
    stats = run_backtest(bars)
    display_results(stats)

    trades_file = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "reports", "backtest_ict_fvg_results.json",
    )
    with open(trades_file, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2, default=str)
    print(f"Resultats sauvegardes : {trades_file}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
