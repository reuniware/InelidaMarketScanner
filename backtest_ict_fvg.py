"""
backtest_ict_fvg.py -- Backtest ICT FVG Strategy on XAUUSD M3 data (v2)
==========================================================================
Strategie ICT (Inner Circle Trader) 5 etapes, IMPLEMENTATION COMPLETE :
  1. DOL : PDH/PDL, Asian H/L, NWOG
  2. Raid oppose avec macros 10/50 ET kill zones (London Open, NY Open, London Close)
     + equal highs/lows sweep detection
  3. Entree : 1er FVG apres displacement OU IFVG sur la jambe de manipulation
  4. Hard SL au-dela de C1 du FVG, breakeven apres TP1
  5. TP 50% mi-chemin Entry-DOL, 50% juste avant le Terminus

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
    "reports", "xauusd_m3_20260101_to_20260627.json",
)

# DOL sources
USE_PDH_PDL = True
USE_ASIAN_HL = True
USE_NWOG = True

# Macro / Kill zone filter (ETAPE 2)
REQUIRE_MACRO = True          # Le raid doit etre sur :10 ou :50 ±2 min
REQUIRE_KILL_ZONE = True      # Le raid doit etre dans une kill zone ICT
MACRO_TOLERANCE_MIN = 5       # ± minutes autour de :10/:50 (fenetre de 10 min)

# Equal highs/lows (ETAPE 2)
REQUIRE_EQUAL_HL = False      # Le raid doit sweeper des equal highs/lows
EQUAL_HL_TOLERANCE_PCT = 0.08  # Tolerance en % du prix pour "equal"
EQUAL_HL_MIN_CLUSTER = 2       # Minimum de niveaux egaux dans le cluster
EQUAL_HL_LOOKBACK_BARS = 96    # Barres M3 de lookback (~5h)

# FVG / IFVG (ETAPE 3)
FVG_MIN_SIZE_PCT = 0.02
MAX_FVG_LOOKFORWARD = 240
MAX_RETRACE_LOOKFORWARD = 120
USE_IFVG = True               # Chercher aussi les IFVGs

# Risk management (ETAPE 4)
BREAKEVEN_AFTER_TP1 = True    # Deplacer SL au breakeven apres TP1

# General
MAX_RAID_LOOKBACK = 480
MIN_DOL_DISTANCE_PCT = 0.15

UTC = timezone.utc

# DST transition 2026: March 8 (2nd Sunday)
DST_START_UTC = datetime(2026, 3, 8, 7, 0, 0, tzinfo=UTC)

# Kill zones in ET hours (Eastern Time)
# London Open:   2:00-5:00 AM ET   -> EST 7:00-10:00 UTC, EDT 6:00-9:00 UTC
# NY Open:       8:30-11:00 AM ET  -> EST 13:30-16:00 UTC, EDT 12:30-15:00 UTC
# London Close: 10:00 AM-12:00 PM ET -> EST 15:00-17:00 UTC, EDT 14:00-16:00 UTC
KILL_ZONES_ET = [
    ("London Open",   2,  0,  5,  0),
    ("NY Open",       8, 30, 11,  0),
    ("London Close", 10,  0, 12,  0),
]


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
# MACRO 10/50 & KILL ZONES (ETAPE 2)
# ==============================================================================

def et_to_utc(ts: float) -> int:
    """Convertit un timestamp UTC en offset ET vers UTC.
    Retourne l'offset a ADDITIONNER pour passer d'ET a UTC.
    EST = +5, EDT = +4."""
    dt = datetime.fromtimestamp(ts, tz=UTC)
    return 4 if dt >= DST_START_UTC else 5


def is_macro_time(ts: float) -> bool:
    """Verifie si le timestamp est dans la fenetre macro :10 ou :50 ± tolerance."""
    dt = datetime.fromtimestamp(ts, tz=UTC)
    m = dt.minute
    for target in (10, 50):
        diff = abs(m - target)
        if diff <= MACRO_TOLERANCE_MIN or 60 - diff <= MACRO_TOLERANCE_MIN:
            return True
    return False


def is_in_kill_zone(ts: float) -> Tuple[bool, str]:
    """Verifie si le timestamp UTC est dans une kill zone ICT (heure ET).

    Retourne (True/False, nom_de_la_zone ou '').
    """
    offset = et_to_utc(ts)
    dt = datetime.fromtimestamp(ts, tz=UTC)

    for zone_name, start_h, start_m, end_h, end_m in KILL_ZONES_ET:
        zone_start_utc_h = start_h + offset
        zone_end_utc_h = end_h + offset
        zone_start_minutes = zone_start_utc_h * 60 + start_m
        zone_end_minutes = zone_end_utc_h * 60 + end_m
        current_minutes = dt.hour * 60 + dt.minute

        if zone_start_minutes <= current_minutes < zone_end_minutes:
            return True, zone_name

    return False, ""


# ==============================================================================
# EQUAL HIGHS / EQUAL LOWS DETECTION (ETAPE 2)
# ==============================================================================

def find_swing_points(bars: List[dict], idx: int, lookback: int) -> Tuple[List[float], List[float]]:
    """Trouve les swing highs et swing lows dans les barres precedant idx.

    Un swing high = barre dont le high est > high des barres adjacentes (±2 barres).
    Retourne (liste_de_swing_highs, liste_de_swing_lows).
    """
    start = max(0, idx - lookback)
    window = bars[start:idx]
    if len(window) < 5:
        return [], []

    swing_highs = []
    swing_lows = []

    for i in range(2, len(window) - 2):
        bar = window[i]
        # Swing high
        if all(bar["high"] >= window[j]["high"] for j in range(i-2, i+3) if j != i):
            swing_highs.append(bar["high"])
        # Swing low
        if all(bar["low"] <= window[j]["low"] for j in range(i-2, i+3) if j != i):
            swing_lows.append(bar["low"])

    return swing_highs, swing_lows


def has_equal_highs_cluster(bars: List[dict], idx: int, raid_level: float) -> bool:
    """Verifie si un cluster d'equal highs existe autour du niveau raide (BSL).

    Un equal high = au moins EQUAL_HL_MIN_CLUSTER swing highs dans
    une tolerance de EQUAL_HL_TOLERANCE_PCT % du prix.
    """
    swing_highs, _ = find_swing_points(bars, idx, EQUAL_HL_LOOKBACK_BARS)
    if len(swing_highs) < EQUAL_HL_MIN_CLUSTER:
        return False

    tolerance = raid_level * EQUAL_HL_TOLERANCE_PCT / 100
    cluster = [h for h in swing_highs if abs(h - raid_level) < tolerance]
    return len(cluster) >= EQUAL_HL_MIN_CLUSTER


def has_equal_lows_cluster(bars: List[dict], idx: int, raid_level: float) -> bool:
    """Verifie si un cluster d'equal lows existe autour du niveau raide (SSL)."""
    _, swing_lows = find_swing_points(bars, idx, EQUAL_HL_LOOKBACK_BARS)
    if len(swing_lows) < EQUAL_HL_MIN_CLUSTER:
        return False

    tolerance = raid_level * EQUAL_HL_TOLERANCE_PCT / 100
    cluster = [l for l in swing_lows if abs(l - raid_level) < tolerance]
    return len(cluster) >= EQUAL_HL_MIN_CLUSTER


# ==============================================================================
# NWOG (ETAPE 1)
# ==============================================================================

def compute_nwog(
    day_str: str,
    all_days: Dict[str, List[dict]],
) -> Optional[dict]:
    """Calcule le NWOG (New Week Opening Gap) si le jour est un lundi.

    NWOG = ecart entre le close du vendredi precedent et l'open du lundi.
    Retourne None si pas un lundi ou donnees manquantes.
    """
    dt = datetime.strptime(day_str, "%Y-%m-%d").replace(tzinfo=UTC)
    if dt.weekday() != 0:  # Pas lundi
        return None

    # Trouver le vendredi precedent
    prev_dt = dt
    for _ in range(4):
        prev_dt = prev_dt - timedelta(days=1)
        candidate = prev_dt.strftime("%Y-%m-%d")
        if candidate in all_days and not is_weekend(candidate):
            break
    else:
        return None

    friday_bars = all_days.get(candidate)
    monday_bars = all_days.get(day_str)
    if not friday_bars or not monday_bars:
        return None

    friday_close = friday_bars[-1]["close"]
    monday_open = monday_bars[0]["open"]

    gap_top = max(friday_close, monday_open)
    gap_bottom = min(friday_close, monday_open)

    return {
        "friday_close": friday_close,
        "monday_open": monday_open,
        "gap_top": gap_top,
        "gap_bottom": gap_bottom,
        "gap_size": gap_top - gap_bottom,
        "previous_friday": candidate,
    }


# ==============================================================================
# DOL + OPPOSING LEVELS (ETAPE 1)
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
        pairs.append({
            "dol_level": pdh, "dol_label": f"PDH({prev_day})",
            "dol_direction": "bull",
            "opposing_level": pdl, "opposing_label": f"PDL({prev_day})",
            "opposing_raid_type": "ssl",
        })
        pairs.append({
            "dol_level": pdl, "dol_label": f"PDL({prev_day})",
            "dol_direction": "bear",
            "opposing_level": pdh, "opposing_label": f"PDH({prev_day})",
            "opposing_raid_type": "bsl",
        })

    if USE_ASIAN_HL and ah is not None and al is not None:
        pairs.append({
            "dol_level": ah, "dol_label": f"AH({day_str})",
            "dol_direction": "bull",
            "opposing_level": al, "opposing_label": f"AL({day_str})",
            "opposing_raid_type": "ssl",
        })
        pairs.append({
            "dol_level": al, "dol_label": f"AL({day_str})",
            "dol_direction": "bear",
            "opposing_level": ah, "opposing_label": f"AH({day_str})",
            "opposing_raid_type": "bsl",
        })

    if USE_NWOG:
        nwog = compute_nwog(day_str, all_days)
        if nwog is not None and nwog["gap_size"] > 0:
            # NWOG top comme DOL haussier -> opposing = NWOG bottom
            pairs.append({
                "dol_level": nwog["gap_top"],
                "dol_label": f"NWOG_top({nwog['previous_friday']})",
                "dol_direction": "bull",
                "opposing_level": nwog["gap_bottom"],
                "opposing_label": f"NWOG_bot({nwog['previous_friday']})",
                "opposing_raid_type": "ssl",
            })
            # NWOG bottom comme DOL baissier -> opposing = NWOG top
            pairs.append({
                "dol_level": nwog["gap_bottom"],
                "dol_label": f"NWOG_bot({nwog['previous_friday']})",
                "dol_direction": "bear",
                "opposing_level": nwog["gap_top"],
                "opposing_label": f"NWOG_top({nwog['previous_friday']})",
                "opposing_raid_type": "bsl",
            })

    return pairs


# ==============================================================================
# RAID DETECTION (ETAPE 2)
# ==============================================================================

def is_ssl_raid(bar: dict, level: float) -> bool:
    return bar["low"] < level and bar["close"] > level


def is_bsl_raid(bar: dict, level: float) -> bool:
    return bar["high"] > level and bar["close"] < level


def find_raid_of_level(
    bars: List[dict],
    ref_idx: int,
    level: float,
    raid_type: str,
    max_lookback: int = MAX_RAID_LOOKBACK,
) -> Optional[Tuple[int, dict]]:
    """Cherche un raid du niveau donne dans les barres precedant ref_idx."""
    search_start = max(0, ref_idx - max_lookback)
    check_fn = is_ssl_raid if raid_type == "ssl" else is_bsl_raid

    for i in range(ref_idx - 1, search_start - 1, -1):
        if check_fn(bars[i], level):
            return (i, bars[i])

    return None


def validate_raid(
    bars: List[dict],
    raid_idx: int,
    raid_bar: dict,
    level: float,
    raid_type: str,
) -> Tuple[bool, str]:
    """Valide un raid selon les criteres ICT :
    - Macro 10/50 (si REQUIRE_MACRO)
    - Kill zone (si REQUIRE_KILL_ZONE)
    - Equal highs/lows (si REQUIRE_EQUAL_HL)

    Retourne (est_valide, raison).
    """
    raid_ts = raid_bar["time"]

    if REQUIRE_MACRO and not is_macro_time(raid_ts):
        return False, "hors_macro"

    if REQUIRE_KILL_ZONE:
        in_kz, kz_name = is_in_kill_zone(raid_ts)
        if not in_kz:
            return False, "hors_kill_zone"

    if REQUIRE_EQUAL_HL:
        if raid_type == "bsl":
            if not has_equal_highs_cluster(bars, raid_idx, level):
                return False, "pas_equal_highs"
        else:
            if not has_equal_lows_cluster(bars, raid_idx, level):
                return False, "pas_equal_lows"

    return True, "ok"


# ==============================================================================
# FVG DETECTION (ETAPE 3)
# ==============================================================================

def find_fvg_at(bars: List[dict], idx: int, direction: str) -> Optional[dict]:
    """Verifie si un FVG existe a l'index idx (3e bougie du pattern)."""
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
    """Scanne les barres apres start_idx pour le 1er FVG dans la direction."""
    end_idx = min(start_idx + max_look + 1, len(bars))
    for i in range(start_idx + 3, end_idx):
        fvg = find_fvg_at(bars, i, direction)
        if fvg is not None:
            return (i, fvg)
    return None


def find_ifvg(
    bars: List[dict],
    start_idx: int,
    end_idx: int,
    dol_direction: str,
) -> Optional[Tuple[int, dict]]:
    """Cherche un IFVG : FVG forme dans la direction OPPOSEE au DOL
    (sur la jambe de manipulation), qui a ete traverse par le prix
    (donc "inverse"), et dont le prix est revenu dans la zone APRES l'inversion.

    Retourne (index_entree, infos_fvg) ou None.
    """
    opposite_dir = "bear" if dol_direction == "bull" else "bull"

    # Scanner les barres entre start_idx et end_idx pour un FVG oppose
    for i in range(start_idx + 3, end_idx):
        fvg = find_fvg_at(bars, i, opposite_dir)
        if fvg is None:
            continue

        zone_top = fvg["zone_top"]
        zone_bottom = fvg["zone_bottom"]

        # Chercher si le prix a casse la zone FVG dans la direction du DOL
        # (une meche suffit pour l'inversion en ICT)
        inverted = False
        inv_bar_idx = None
        for j in range(i + 1, end_idx):
            if dol_direction == "bull":
                if bars[j]["high"] > zone_top:
                    inverted = True
                    inv_bar_idx = j
                    break
            else:
                if bars[j]["low"] < zone_bottom:
                    inverted = True
                    inv_bar_idx = j
                    break

        if not inverted:
            continue

        # Chercher retrace DANS la zone APRES l'inversion
        for j in range(inv_bar_idx + 1, end_idx):
            bar = bars[j]
            if bar["low"] <= zone_top and bar["high"] >= zone_bottom:
                # Prix dans la zone IFVG -> entree au midpoint
                entry_price = (zone_top + zone_bottom) / 2
                if bar["low"] <= entry_price <= bar["high"]:
                    return (j, {
                        "type": f"ifvg_{opposite_dir}",
                        "zone_top": zone_top,
                        "zone_bottom": zone_bottom,
                        "c1_bar": fvg["c1_bar"],
                        "c3_bar": fvg["c3_bar"],
                        "gap_size": fvg["gap_size"],
                        "gap_pct": fvg["gap_pct"],
                        "is_ifvg": True,
                    })

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
    """Attend que le prix retrace dans la zone FVG pour entrer au midpoint."""
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
    bars: List[dict],
    entry_idx: int,
    entry_price: float,
    sl_price: float,
    tp1_price: float,
    tp2_price: float,
    direction: str,
) -> dict:
    """Simule un trade en forward-test avec breakeven optionnel apres TP1."""
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
        "breakeven_activated": False,
        "exit_time": None,
    }

    risk = abs(entry_price - sl_price)
    if risk == 0:
        result["status"] = "INVALID"
        return result

    current_sl = sl_price

    for i in range(entry_idx + 1, len(bars)):
        bar = bars[i]

        if direction == "bull":
            # Verifier SL
            if bar["low"] <= current_sl:
                result.update(status="LOSS", sl_hit=True,
                              exit_time=bar["time"], pnl_r=-1.0)
                break
            # TP1
            if not result["tp1_hit"] and bar["high"] >= tp1_price:
                result["tp1_hit"] = True
                result["exit_time"] = bar["time"]
                if BREAKEVEN_AFTER_TP1:
                    current_sl = entry_price
                    result["breakeven_activated"] = True
            # TP2
            if result["tp1_hit"] and bar["high"] >= tp2_price:
                r1 = (tp1_price - entry_price) / risk
                r2 = (tp2_price - entry_price) / risk
                result.update(status="WIN_FULL", tp2_hit=True,
                              exit_time=bar["time"], pnl_r=0.5 * r1 + 0.5 * r2)
                break
        else:
            if bar["high"] >= current_sl:
                result.update(status="LOSS", sl_hit=True,
                              exit_time=bar["time"], pnl_r=-1.0)
                break
            if not result["tp1_hit"] and bar["low"] <= tp1_price:
                result["tp1_hit"] = True
                result["exit_time"] = bar["time"]
                if BREAKEVEN_AFTER_TP1:
                    current_sl = entry_price
                    result["breakeven_activated"] = True
            if result["tp1_hit"] and bar["low"] <= tp2_price:
                r1 = (entry_price - tp1_price) / risk
                r2 = (entry_price - tp2_price) / risk
                result.update(status="WIN_FULL", tp2_hit=True,
                              exit_time=bar["time"], pnl_r=0.5 * r1 + 0.5 * r2)
                break

    # Si le trade est toujours ouvert en fin de donnees
    if result["status"] == "OPEN":
        if result["tp1_hit"] and not result["sl_hit"]:
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
    stats_counters = {
        "raids_found": 0, "fvgs_found": 0, "ifvgs_found": 0,
        "retraces_found": 0, "no_fvg": 0, "no_retrace": 0,
        "raid_rejected_macro": 0, "raid_rejected_kz": 0,
        "raid_rejected_eh": 0,
    }

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

            # Chercher un raid du NIVEAU OPPOSE
            raid = find_raid_of_level(
                bars, day_end_idx, opposing_level, opposing_type)
            if raid is None:
                continue

            raid_idx, raid_bar = raid
            stats_counters["raids_found"] += 1

            # Filtrer trades Asian declenches avant 08:00 UTC
            if is_asian_dol:
                raid_hour = datetime.fromtimestamp(raid_bar["time"], tz=UTC).hour
                if raid_hour < 8:
                    continue

            # Valider le raid (macro, kill zone, equal highs/lows)
            valid, reject_reason = validate_raid(
                bars, raid_idx, raid_bar, opposing_level, opposing_type)
            if not valid:
                if reject_reason == "hors_macro":
                    stats_counters["raid_rejected_macro"] += 1
                elif reject_reason == "hors_kill_zone":
                    stats_counters["raid_rejected_kz"] += 1
                elif reject_reason.startswith("pas_equal"):
                    stats_counters["raid_rejected_eh"] += 1
                continue

            # Chercher le 1er FVG APRES le raid, vers le DOL
            fvg_result = scan_first_fvg_after(
                bars, raid_idx, pair["dol_direction"])
            if fvg_result is None:
                stats_counters["no_fvg"] += 1
                continue

            fvg_idx, fvg = fvg_result
            stats_counters["fvgs_found"] += 1

            # Option A : FVG standard avec retracement
            retrace = wait_for_fvg_retrace(
                bars, fvg_idx, fvg, pair["dol_direction"])
            if retrace is not None:
                entry_idx, entry_price = retrace
                entry_type = "fvg"
                entry_fvg = fvg
            elif USE_IFVG:
                # Option B : IFVG (alternative)
                ifvg_result = find_ifvg(
                    bars, raid_idx, day_end_idx, pair["dol_direction"])
                if ifvg_result is not None:
                    entry_idx, entry_fvg = ifvg_result
                    entry_price = (entry_fvg["zone_top"] + entry_fvg["zone_bottom"]) / 2
                    entry_type = "ifvg"
                    stats_counters["ifvgs_found"] += 1
                else:
                    stats_counters["no_retrace"] += 1
                    continue
            else:
                stats_counters["no_retrace"] += 1
                continue

            stats_counters["retraces_found"] += 1

            # Verifier distance DOL suffisante
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
            c1 = entry_fvg["c1_bar"]
            gap_size = entry_fvg["gap_size"]

            if pair["dol_direction"] == "bull":
                sl_price = c1["low"] - gap_size * 0.2
                if sl_price >= entry_price:
                    continue
                tp1_price = entry_price + (dol_level - entry_price) * 0.5
                tp2_price = dol_level - gap_size
            else:
                sl_price = c1["high"] + gap_size * 0.2
                if sl_price <= entry_price:
                    continue
                tp1_price = entry_price - (entry_price - dol_level) * 0.5
                tp2_price = dol_level + gap_size

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
                "fvg_type": entry_fvg.get("type", fvg.get("type", "?")),
                "fvg_gap_pct": entry_fvg.get("gap_pct", 0),
                "entry_type": entry_type,
                "entry_price": entry_price,
                "sl_price": sl_price,
                "tp1_price": tp1_price,
                "tp2_price": tp2_price,
                **result,
            })

    return _compute_stats(trades, stats_counters)


def _compute_stats(trades, counters):
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
        "raids_found": counters["raids_found"],
        "fvgs_found": counters["fvgs_found"],
        "ifvgs_found": counters["ifvgs_found"],
        "retraces_found": counters["retraces_found"],
        "no_fvg": counters["no_fvg"],
        "no_retrace": counters["no_retrace"],
        "raid_rejected_macro": counters["raid_rejected_macro"],
        "raid_rejected_kz": counters["raid_rejected_kz"],
        "raid_rejected_eh": counters["raid_rejected_eh"],
        "trades": trades,
    }


# ==============================================================================
# DISPLAY
# ==============================================================================

def display_results(stats: dict) -> None:
    print()
    print("=" * 72)
    print("  BACKTEST ICT FVG STRATEGY (v2 - COMPLETE) -- RESULTS")
    print("=" * 72)
    print(f"  Raids detectes          : {stats['raids_found']}")
    print(f"    Rejetes (macro)       : {stats.get('raid_rejected_macro', 0)}")
    print(f"    Rejetes (kill zone)   : {stats.get('raid_rejected_kz', 0)}")
    print(f"    Rejetes (equal H/L)   : {stats.get('raid_rejected_eh', 0)}")
    print(f"  FVGs trouves            : {stats['fvgs_found']}")
    print(f"  IFVGs trouves           : {stats.get('ifvgs_found', 0)}")
    print(f"  Retracements FVG/IFVG   : {stats['retraces_found']}")
    print(f"  Sans FVG                : {stats['no_fvg']}")
    print(f"  Sans retracement        : {stats['no_retrace']}")
    print(f"  Trades executes         : {stats['total_trades']}")
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
            entry_t = t.get("entry_type", "fvg")
            be = " [BE]" if t.get("breakeven_activated") else ""
            print(
                f"  {icon:5} {t['day']} {t['dol_direction']:4} "
                f"DOL={t['dol_label']:<22} "
                f"Raid@{raid_dt} "
                f"{entry_t}{be} "
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
          f"NWOG={'ON' if USE_NWOG else 'OFF'} "
          f"Macro={'ON' if REQUIRE_MACRO else 'OFF'} "
          f"KillZone={'ON' if REQUIRE_KILL_ZONE else 'OFF'} "
          f"EqualHL={'ON' if REQUIRE_EQUAL_HL else 'OFF'} "
          f"IFVG={'ON' if USE_IFVG else 'OFF'} "
          f"BE={'ON' if BREAKEVEN_AFTER_TP1 else 'OFF'} "
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
