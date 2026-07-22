"""PureICT — Scanner des sessions asiatiques et FVGs.

Dependances :
  - PureICT.models, PureICT.config
  - MetaTrader5, src.mt5_connector, src.time_utils
"""

import fnmatch
import logging
import os
import sys
import time
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

# Chemin projet
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    import MetaTrader5 as mt5
except ImportError:
    print("\n  !! MetaTrader5 n'est pas installe.")
    print("     Installe-le avec : pip install MetaTrader5")
    print("     Puis verifie que MT5 est lance et connecte.\n")
    sys.exit(1)

from src.mt5_connector import MT5Connector
from src.time_utils import now_datetime

from .models import AsianLevels, PreviousAsianLevels, FvgInfo
from .config import (
    DEFAULT_START_HOUR, DEFAULT_END_HOUR, DEFAULT_TIMEZONE,
    TIMEFRAMES, DEFAULT_TF, LOOKBACK_BARS,
    FVG_TIMEFRAMES, FVG_LOOKBACK, DEFAULT_FVG_MIN_PCT,
    calc_max_lots,
    paris_date_str, _tz_offset,
    _session_true_utc_start, _session_true_utc_end,
    format_epoch,
)

logger = logging.getLogger("PureICT.Scanner")


# ===============================================================================
# HELPERS MT5 / BOUGIES
# ===============================================================================

def bars_to_dicts(rates_raw) -> List[dict]:
    """Convertit le ndarray MT5 en liste de dicts simples."""
    out: List[dict] = []
    for r in rates_raw:
        out.append({
            "time":  int(r[0]),
            "open":  float(r[1]),
            "high":  float(r[2]),
            "low":   float(r[3]),
            "close": float(r[4]),
        })
    return out


def sweep_high(bar: dict, level: float) -> bool:
    """ICT sweep AH : meche au-dessus + close en-dessous (BSL)."""
    return bar["high"] > level and bar["close"] < level


def sweep_low(bar: dict, level: float) -> bool:
    """ICT sweep AL : meche en-dessous + close au-dessus (SSL)."""
    return bar["low"] < level and bar["close"] > level


# ===============================================================================
# FVG DETECTION
# ===============================================================================

def find_fvg_at(bars: List[dict], idx: int, direction: str, fvg_min_pct: float) -> Optional[dict]:
    """Verifie si un FVG existe a l'index idx (3e bougie du pattern)."""
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
    gap_pct = gap_size / gap_bottom * 100.0
    if gap_pct < fvg_min_pct:
        return None

    return {
        "type": "bullish" if direction == "bull" else "bearish",
        "zone_top": gap_top,
        "zone_bottom": gap_bottom,
        "gap_size": gap_size,
        "gap_pct": gap_pct,
        "c1_time": c1["time"],
        "c3_time": c3["time"],
    }


def _level_distance(fvg_zone_top: float, fvg_zone_bottom: float, level: float) -> float:
    """Distance en %% entre la zone FVG et un niveau (AH/AL)."""
    if fvg_zone_bottom <= level <= fvg_zone_top:
        return 0.0
    dist_to_top = abs(level - fvg_zone_top)
    dist_to_bot = abs(level - fvg_zone_bottom)
    return min(dist_to_top, dist_to_bot) / level * 100.0 if level > 0 else 999.0


def scan_reclaim_fvgs(
    symbol: str,
    asian_high: float,
    asian_low: float,
    end_epoch_utc: float,
    fvg_min_pct: float = DEFAULT_FVG_MIN_PCT,
) -> Tuple[List[FvgInfo], List[FvgInfo]]:
    """Detecte les FVGs formes quand le prix repasse SOUS l'AH ou AU-DESSUS de l'AL.

    Returns:
        (fvg_ah_list, fvg_al_list) — listes de FvgInfo (vides si aucun FVG trouve).
    """
    fvg_ah_list: List[FvgInfo] = []
    fvg_al_list: List[FvgInfo] = []
    ah_tfs_done: set = set()
    al_tfs_done: set = set()

    _broker_offset_sec = _tz_offset("BROKER") * 3600
    tf_names = ["M15", "M5", "M3", "M1"]

    for tf_name in tf_names:
        tf = FVG_TIMEFRAMES.get(tf_name)
        if tf is None:
            continue

        lookback = FVG_LOOKBACK.get(tf_name, 360)
        rates_raw = mt5.copy_rates_from_pos(symbol, tf, 0, lookback)
        if rates_raw is None or len(rates_raw) == 0:
            continue

        bars = bars_to_dicts(rates_raw)
        bars.sort(key=lambda b: b["time"])

        for b in bars:
            b["time_utc"] = b["time"] - _broker_offset_sec

        post_bars = [b for b in bars if b["time_utc"] >= end_epoch_utc]
        if len(post_bars) < 3:
            continue

        price_above_ah = any(b["high"] > asian_high for b in post_bars)
        price_below_al = any(b["low"] < asian_low for b in post_bars)
        last_close = post_bars[-1]["close"]
        back_below_ah = price_above_ah and last_close < asian_high
        back_above_al = price_below_al and last_close > asian_low

        if not back_below_ah and not back_above_al:
            continue

        found_ah_on_tf = False
        found_al_on_tf = False
        for i in range(len(post_bars) - 1, 1, -1):
            if back_below_ah and not found_ah_on_tf and tf_name not in ah_tfs_done:
                fvg = find_fvg_at(post_bars, i, "bear", fvg_min_pct)
                if fvg is not None:
                    dist = _level_distance(fvg["zone_top"], fvg["zone_bottom"], asian_high)
                    if dist < 0.5:
                        fvg_ah_list.append(FvgInfo(
                            timeframe=tf_name, direction="bearish",
                            zone_top=fvg["zone_top"], zone_bottom=fvg["zone_bottom"],
                            gap_pct=fvg["gap_pct"], gap_size=fvg["gap_size"],
                            level_type="AH", level_price=asian_high,
                        ))
                        found_ah_on_tf = True
                        ah_tfs_done.add(tf_name)

            if back_above_al and not found_al_on_tf and tf_name not in al_tfs_done:
                fvg = find_fvg_at(post_bars, i, "bull", fvg_min_pct)
                if fvg is not None:
                    dist = _level_distance(fvg["zone_top"], fvg["zone_bottom"], asian_low)
                    if dist < 0.5:
                        fvg_al_list.append(FvgInfo(
                            timeframe=tf_name, direction="bullish",
                            zone_top=fvg["zone_top"], zone_bottom=fvg["zone_bottom"],
                            gap_pct=fvg["gap_pct"], gap_size=fvg["gap_size"],
                            level_type="AL", level_price=asian_low,
                        ))
                        found_al_on_tf = True
                        al_tfs_done.add(tf_name)

    return fvg_ah_list, fvg_al_list


# ===============================================================================
# SCAN D'UN SYMBOLE
# ===============================================================================

def scan_symbol(
    symbol: str,
    session_date_paris: Optional[str] = None,
    start_hour: int = DEFAULT_START_HOUR,
    end_hour: int = DEFAULT_END_HOUR,
    timeframe: str = DEFAULT_TF,
    tz_mode: str = DEFAULT_TIMEZONE,
    _mt5c: Optional[MT5Connector] = None,
    fvg_mode: bool = False,
    fvg_min_pct: float = DEFAULT_FVG_MIN_PCT,
) -> Tuple[Optional[AsianLevels], Optional[str]]:
    """Calcule les niveaux asiatiques pour un symbole.

    Returns:
        (AsianLevels, None) si succes, (None, raison_erreur) si echec.
    """
    if session_date_paris is None:
        session_date_paris = paris_date_str()

    mt5c = _mt5c if _mt5c is not None else MT5Connector()
    if not mt5c.ensure_connected():
        return None, "MT5 non connecte"
    if not mt5c.select_symbol(symbol):
        return None, "select_symbol a echoue"

    _broker_offset_sec = _tz_offset("BROKER") * 3600
    session_start_utc = _session_true_utc_start(session_date_paris, start_hour, tz_mode)
    session_end_utc = _session_true_utc_end(session_date_paris, end_hour, tz_mode)

    tf = TIMEFRAMES.get(timeframe.upper())
    if tf is None:
        logger.error("Timeframe inconnu : %s", timeframe)
        return None, "Timeframe invalide"
    lookback = LOOKBACK_BARS.get(timeframe.upper(), 400)

    rates_raw = mt5.copy_rates_from_pos(symbol, tf, 0, lookback)
    if rates_raw is None or len(rates_raw) == 0:
        return None, "Pas de donnees"

    bars = bars_to_dicts(rates_raw)
    bars.sort(key=lambda b: b["time"])

    for b in bars:
        b["time_utc"] = b["time"] - _broker_offset_sec

    session_start_epoch = session_start_utc.timestamp()
    session_end_epoch = session_end_utc.timestamp()
    session_bars = [b for b in bars if session_start_epoch <= b["time_utc"] < session_end_epoch]
    if not session_bars:
        return None, "Aucune barre dans la fenetre session"

    asian_high = -float('inf')
    asian_low = float('inf')
    high_at_epoch = 0.0
    low_at_epoch = 0.0

    for b in session_bars:
        if b["high"] > asian_high:
            asian_high = b["high"]
            high_at_epoch = b["time_utc"]
        if b["low"] < asian_low:
            asian_low = b["low"]
            low_at_epoch = b["time_utc"]

    midpoint = (asian_high + asian_low) / 2.0
    range_pips = asian_high - asian_low
    range_pct = (range_pips / midpoint * 100.0) if midpoint > 0 else 0.0

    # Fibonacci
    fib_levels = [1.618, 2.618, 3.618, 4.618, 5.618]
    fib_up_vals: dict = {}
    fib_dn_vals: dict = {}
    if range_pips > 0:
        dist = range_pips / 2.0
        for lvl in fib_levels:
            key = int(lvl * 1000)
            fib_up_vals[f"fib_up_{key}"] = round(midpoint + dist * lvl, 5)
            fib_dn_vals[f"fib_dn_{key}"] = round(midpoint - dist * lvl, 5)
    else:
        for lvl in fib_levels:
            key = int(lvl * 1000)
            fib_up_vals[f"fib_up_{key}"] = midpoint
            fib_dn_vals[f"fib_dn_{key}"] = midpoint

    open_first_bar = session_bars[0]["open"]
    close_last_bar = session_bars[-1]["close"]

    is_live = now_datetime() < session_end_utc
    if is_live:
        tick = mt5.symbol_info_tick(symbol)
        close_last_bar = float(tick.bid) if tick else close_last_bar

    # Sweeps
    today_date_utc = session_end_utc.strftime("%Y-%m-%d")
    post_bars = [
        b for b in bars
        if b["time_utc"] >= session_end_epoch
        and time.strftime("%Y-%m-%d", time.gmtime(b["time_utc"])) == today_date_utc
    ]
    ah_swept = False
    al_swept = False
    ah_swept_at: Optional[str] = None
    al_swept_at: Optional[str] = None

    for b in post_bars:
        if not ah_swept and sweep_high(b, asian_high):
            ah_swept = True
            ah_swept_at = format_epoch(b["time_utc"])
        if not al_swept and sweep_low(b, asian_low):
            al_swept = True
            al_swept_at = format_epoch(b["time_utc"])
        if ah_swept and al_swept:
            break

    # Prix actuel
    tick = mt5.symbol_info_tick(symbol)
    current_price = float(tick.bid) if tick else (bars[-1]["close"] if bars else 0.0)

    # OTE
    ote_bear_high = 0.0
    ote_bear_low = 0.0
    ote_bull_high = 0.0
    ote_bull_low = 0.0
    in_ote_bear = False
    in_ote_bull = False
    if range_pips > 0:
        ote_bear_high = asian_high - 0.382 * range_pips
        ote_bear_low = asian_high - 0.618 * range_pips
        ote_bull_high = asian_low + 0.618 * range_pips
        ote_bull_low = asian_low + 0.382 * range_pips
        in_ote_bear = ote_bear_low <= current_price <= ote_bear_high
        in_ote_bull = ote_bull_low <= current_price <= ote_bull_high

    # FVG
    fvg_ah_list: List[FvgInfo] = []
    fvg_al_list: List[FvgInfo] = []
    if fvg_mode:
        try:
            fvg_ah_list, fvg_al_list = scan_reclaim_fvgs(
                symbol, asian_high, asian_low, session_end_epoch, fvg_min_pct,
            )
        except Exception as e:
            logger.debug("FVG scan failed for %s: %s", symbol, e)

    max_lots_val, margin_per_lot_val, acc_currency = calc_max_lots(symbol, current_price)

    return AsianLevels(
        symbol=symbol,
        session_date=session_date_paris,
        session_label="LIVE" if is_live else "OK",
        is_live=is_live,
        open_first_bar=open_first_bar,
        close_last_bar=close_last_bar,
        asian_high=asian_high,
        asian_low=asian_low,
        high_at_epoch=high_at_epoch,
        low_at_epoch=low_at_epoch,
        midpoint=midpoint,
        range_pips=range_pips,
        range_pct=round(range_pct, 4),
        bars_in_session=len(session_bars),
        ah_swept=ah_swept,
        al_swept=al_swept,
        ah_swept_at=ah_swept_at,
        al_swept_at=al_swept_at,
        current_price=current_price,
        fvg_ah=[asdict(f) for f in fvg_ah_list] if fvg_ah_list else None,
        fvg_al=[asdict(f) for f in fvg_al_list] if fvg_al_list else None,
        max_lots=max_lots_val,
        account_currency=acc_currency,
        margin_per_lot=margin_per_lot_val,
        ote_bear_high=round(ote_bear_high, 5),
        ote_bear_low=round(ote_bear_low, 5),
        ote_bull_high=round(ote_bull_high, 5),
        ote_bull_low=round(ote_bull_low, 5),
        in_ote_bear=in_ote_bear,
        in_ote_bull=in_ote_bull,
        **fib_up_vals,
        **fib_dn_vals,
    ), None


# ===============================================================================
# SCAN SESSION PRECEDENTE
# ===============================================================================

def scan_previous_session(
    symbol: str,
    session_date_paris: Optional[str] = None,
    start_hour: int = DEFAULT_START_HOUR,
    end_hour: int = DEFAULT_END_HOUR,
    timeframe: str = DEFAULT_TF,
    tz_mode: str = DEFAULT_TIMEZONE,
    _mt5c: Optional[MT5Connector] = None,
) -> Optional[PreviousAsianLevels]:
    """Calcule les niveaux de la session asiatique PRECEDENTE (J-1)."""
    if session_date_paris is None:
        session_date_paris = paris_date_str()

    dt = datetime.strptime(session_date_paris, "%Y-%m-%d") - timedelta(days=1)
    prev_date = dt.strftime("%Y-%m-%d")

    r, err = scan_symbol(symbol, prev_date, start_hour, end_hour, timeframe, tz_mode, _mt5c=_mt5c)
    if r is None:
        return None
    return PreviousAsianLevels(
        symbol=symbol, session_date=prev_date,
        asian_high=r.asian_high, asian_low=r.asian_low,
        midpoint=r.midpoint, range_pips=r.range_pips,
        range_pct=r.range_pct, bars_in_session=r.bars_in_session,
    )


# ===============================================================================
# FORCE SELECT
# ===============================================================================

def _force_select_all(symbols: List[str], batch_size: int = 20) -> Tuple[int, int]:
    """Pre-active tous les symboles dans Market Watch avant le scan."""
    if not symbols:
        print("  Pre-activation : aucun symbole a traiter.")
        return 0, 0
    total = len(symbols)
    ok_count = 0
    fail_count = 0
    print(f"  Pre-activation de {total} symboles dans Market Watch...")
    for i, sym in enumerate(symbols):
        try:
            info = mt5.symbol_info(sym)
            if info is None:
                fail_count += 1
                continue
            if info.visible:
                ok_count += 1
                continue
            if mt5.symbol_select(sym, True):
                ok_count += 1
            else:
                fail_count += 1
        except Exception:
            fail_count += 1
        if (i + 1) % batch_size == 0 or i == total - 1:
            print(f"    Progression : {i+1}/{total}  |  OK: {ok_count}  FAIL: {fail_count}")
            if i + 1 < total:
                time.sleep(0.1)
    print(f"  Pre-activation terminee : {ok_count} actifs, {fail_count} echoues")
    return ok_count, fail_count


# ===============================================================================
# SCAN TOUS LES SYMBOLES
# ===============================================================================

def scan_all_symbols(
    session_date_paris: Optional[str] = None,
    max_symbols: Optional[int] = None,
    include_previous: bool = False,
    market_watch_only: bool = False,
    start_hour: int = DEFAULT_START_HOUR,
    end_hour: int = DEFAULT_END_HOUR,
    symbol_filters: Optional[List[str]] = None,
    timeframe: str = DEFAULT_TF,
    tz_mode: str = DEFAULT_TIMEZONE,
    force_select: bool = False,
    fvg_mode: bool = False,
    fvg_min_pct: float = DEFAULT_FVG_MIN_PCT,
) -> Tuple[List[AsianLevels], List[PreviousAsianLevels], List[Tuple[str, str]]]:
    """Scanne TOUS les symboles disponibles chez le broker, avec filtre optionnel.

    Returns:
        (current_results, previous_results, excluded_symbols)
        excluded_symbols = [(symbole, raison), ...] pour ceux qui ont echoue.
    """
    mt5c = MT5Connector()
    if not mt5c.ensure_connected():
        return [], [], []

    if market_watch_only:
        all_syms = mt5c.list_market_watch_symbols()
        source = "Market Watch"
    else:
        all_syms = mt5c.list_all_symbols()
        source = "broker complet"

    if not all_syms:
        logger.error("Aucun symbole trouve chez le broker.")
        return [], [], []

    if symbol_filters:
        matched = set()
        for pattern in symbol_filters:
            p_upper = pattern.upper()
            for s in all_syms:
                if fnmatch.fnmatch(s.upper(), p_upper):
                    matched.add(s)
        all_syms = sorted(matched)
        source += f" (filtre: {', '.join(symbol_filters)})"
        if not all_syms:
            logger.error("Aucun symbole ne correspond aux filtres : %s", symbol_filters)
            return [], [], []

    if max_symbols and len(all_syms) > max_symbols:
        all_syms = all_syms[:max_symbols]

    originally_visible: set = set()

    if force_select and not market_watch_only:
        for s in all_syms:
            info = mt5.symbol_info(s)
            if info and info.visible:
                originally_visible.add(s)
        ok, fail = _force_select_all(all_syms)
        print(f"    OK: {ok}  |  FAIL: {fail}  |  Deja visibles: {len(originally_visible)}")
        print()

    if session_date_paris is None:
        session_date_paris = paris_date_str()

    current_results: List[AsianLevels] = []
    previous_results: List[PreviousAsianLevels] = []
    excluded: List[Tuple[str, str]] = []
    total = len(all_syms)

    print(f"  Scan de {total} symboles ({source})...")
    print(f"  (Timeframe {timeframe} - les symboles sans donnees seront ignores)")

    for i, sym in enumerate(all_syms):
        if (i + 1) % 50 == 0:
            print(f"    Progression : {i+1}/{total}")

        try:
            r, err = scan_symbol(sym, session_date_paris, start_hour, end_hour,
                                  timeframe, tz_mode, _mt5c=mt5c,
                                  fvg_mode=fvg_mode, fvg_min_pct=fvg_min_pct)
            if r is not None:
                current_results.append(r)
            else:
                excluded.append((sym, err or "Erreur inconnue"))

            if include_previous:
                p = scan_previous_session(sym, session_date_paris,
                                           start_hour, end_hour,
                                           timeframe, tz_mode, _mt5c=mt5c)
                if p is not None:
                    previous_results.append(p)
        except Exception as e:
            excluded.append((sym, f"Exception: {e}"))
        finally:
            try:
                if sym not in originally_visible:
                    mt5.symbol_select(sym, False)
            except Exception:
                pass

    return current_results, previous_results, excluded
