'''
Detecteur de sweeps de liquidite (BSL / SSL) inspire ICT.

Charge les bougies OHLC d un symbole, identifie les swing points via Williams
fractals, puis verifie si un swing haut a ete swept (wick au-dessus + close
en-dessous = raid BSL = liquidity prise au-dessus des stops acheteurs) ou si
un swing bas a ete sweep (wick en-dessous + close au-dessus = raid SSL).

Contient aussi la detection du range de session asiatique (UTC 00:00-08:00)
avec detection de ses sweeps post-Asian (London / NY) ET des sweeps des niveaux
d extension Fibonacci ICT (+1.618, +2.0, +2.618, +3.0, +3.618, +4.0 et negatifs).
'''

import logging
import time
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple

import MetaTrader5 as mt5

from .config import SWEEP, DB, ASIAN, ELITE, ELITE_V1
from .mt5_connector import MT5Connector

logger = logging.getLogger("SweepDetector")


def _classify_symbol(sym: str) -> str:
    """Classifie un symbole par type d'instrument pour le filtre ELITE."""
    sym_u = sym.upper()
    if sym in ('XAUUSD', 'XAGUSD', 'XAUAUD', 'XAGAUD'):
        return 'METAL'
    if sym_u.endswith('USD') and sym not in ('XAUUSD', 'XAGUSD'):
        return 'FOREX_USD'
    if 'JPY' in sym_u:
        return 'FOREX_JPY'
    # Paires basees USD mais ne finissant pas par USD: USDCAD, USDCHF, USDNOK...
    if sym_u.startswith('USD'):
        return 'FOREX_USD'
    if any(c in sym for c in ('EUR', 'GBP', 'CAD', 'AUD', 'NZD', 'CHF',
                                'NOK', 'SEK', 'PLN', 'CZK', 'MXN', 'SGD', 'ZAR', 'HUF')):
        return 'FOREX_CROSS'
    if '.cash' in sym or sym in ('DXY.cash', 'GDAXI'):
        return 'INDEX'
    return 'OTHER'


# Helper qui formate un prix selon l instrument (meme logique adaptative que
# _fmt_price dans display.py, duplique ici pour eviter une dependance circulaire).
def _fmt_price_adaptive(p: Optional[float]) -> str:
    """Formatte un prix avec precision adaptative selon sa magnitude.
    >= 1000 : 2 decimales (XAUUSD, BTCUSD)
    >= 10   : 4 decimales (USDJPY)
    <  10   : 5 decimales (forex 5-digit EURUSD/GBPUSD)."""
    if p is None:
        return "-"
    if p >= 1000.0:
        return f"{p:.2f}"
    if p >= 10.0:
        return f"{p:.4f}"
    return f"{p:.5f}"


# Mapping nom lisible -> constante MT5 TIMEFRAME_*
_TIMEFRAME_MAP: Dict[str, int] = {
    "M1":  mt5.TIMEFRAME_M1,
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1":  mt5.TIMEFRAME_H1,
    "H4":  mt5.TIMEFRAME_H4,
    "D1":  mt5.TIMEFRAME_D1,
    "W1":  mt5.TIMEFRAME_W1,
}

# Niveaux d extension Fibonacci - expansion au-dessus / en-dessous de la range Asian.
# 1.0 et -1.0 EXCLUS car ils correspondent a l autre liquidite (AH/AL) deja trackee
# par direction_target. On affiche la prochaine cible non atteinte dans la direction
# du mouvement. Une fois tous les niveaux franchis, on garde le dernier avec un
# suffixe _DONE pour signaler qu on est au-dela de la grille standard.
_FIB_LEVELS_BULL: Tuple[float, ...] = (1.618, 2.0, 2.618, 3.0, 3.618, 4.0)
_FIB_LEVELS_BEAR: Tuple[float, ...] = (-1.618, -2.0, -2.618, -3.0, -3.618, -4.0)


# --- Dataclasses Williams / BSL-SSL ---
@dataclass
class SwingPoint:
    """Un swing haut ou bas detecte via Williams fractals."""
    bar_index: int
    kind: str            # 'high' ou 'low'
    level: float
    time: float          # epoch seconds


@dataclass
class SweepEvent:
    """Un evenement de sweep detecte sur un symbole."""
    symbol: str
    timeframe: str
    kind: str            # 'high_sweep' (BSL) ou 'low_sweep' (SSL)
    sweep_label: str     # 'BSL' ou 'SSL' (vocabulaire ICT)
    level: float         # Prix du swing point swept
    sweep_time: float    # epoch de la bougie qui a swept
    sweep_close: float   # close de la bougie qui a swept
    current_price: float # prix actuel
    current_time: float  # epoch du tick actuel
    distance_pct: float  # |(current - level) / level| * 100
    direction: str       # 'reversal_down' ou 'reversal_up' (implication ICT)


# --- Helpers Williams Fractals ---
def _bars_to_dicts(rates_raw) -> List[dict]:
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


def detect_swing_points(ohlc_bars: List[dict], fractal_n: int) -> List[SwingPoint]:
    """
    Williams fractal standard:
      swing haut = bar[i].high > toutes les highs dans [i-N, i+N] (excluant i)
      swing bas  = bar[i].low  < toutes les lows  dans [i-N, i+N] (excluant i)
    """
    if len(ohlc_bars) < 2 * fractal_n + 1:
        return []

    swings: List[SwingPoint] = []
    highs = [b["high"] for b in ohlc_bars]
    lows = [b["low"] for b in ohlc_bars]
    times = [b["time"] for b in ohlc_bars]

    for i in range(fractal_n, len(ohlc_bars) - fractal_n):
        h = highs[i]
        is_high = all(h > highs[j] for j in range(i - fractal_n, i + fractal_n + 1) if j != i)
        l = lows[i]
        is_low = all(l < lows[j] for j in range(i - fractal_n, i + fractal_n + 1) if j != i)
        if is_high:
            swings.append(SwingPoint(bar_index=i, kind="high", level=h, time=times[i]))
        elif is_low:
            swings.append(SwingPoint(bar_index=i, kind="low", level=l, time=times[i]))
    return swings


def _bar_sweeps_swing(bar: dict, swing: SwingPoint) -> bool:
    """
    True si la bougie a swept le swing selon la definition ICT :
      - swing haut / BSL: high > swing.level ET close < swing.level
      - swing bas  / SSL: low  < swing.level ET close > swing.level
    """
    if swing.kind == "high":
        return bar["high"] > swing.level and bar["close"] < swing.level
    if swing.kind == "low":
        return bar["low"] < swing.level and bar["close"] > swing.level
    return False


# --- Detection sur un symbole (BSL/SSL) ---
def detect_sweeps_for_symbol(
    symbol: str,
    timeframe: Optional[str] = None,
    fractal_n: Optional[int] = None,
    lookback: Optional[int] = None,
    sensitivity: Optional[int] = None,
    _mt5c: Optional[MT5Connector] = None,
) -> List[SweepEvent]:
    """
    Charge les bougies d un symbole, detecte swing points et ramene les sweeps
    detectes dans les sensitivity dernieres bougies.
    """
    tf_name = timeframe or SWEEP.timeframe
    f_n = fractal_n if fractal_n is not None else SWEEP.fractal_n
    lb = lookback if lookback is not None else SWEEP.lookback
    sens = sensitivity if sensitivity is not None else SWEEP.sensitivity
    tf = _TIMEFRAME_MAP.get(tf_name.upper())
    if tf is None:
        logger.warning("Timeframe inconnu pour sweeps: %s", tf_name)
        return []

    mt5c = _mt5c if _mt5c is not None else MT5Connector()
    if not mt5c.ensure_connected():
        return []
    mt5c.select_symbol(symbol)

    total_bars = max(lb + sens + 2 * f_n + 5, 60)
    rates_raw = mt5.copy_rates_from_pos(symbol, tf, 0, total_bars)
    if rates_raw is None or len(rates_raw) == 0:
        logger.debug("Pas de bougies %s %s", symbol, tf_name)
        return []

    bars = _bars_to_dicts(rates_raw)
    if len(bars) < lb + sens + 2 * f_n:
        return []

    swings = detect_swing_points(bars, f_n)

    current_tick = mt5.symbol_info_tick(symbol)
    current_price = float(current_tick.bid) if current_tick else bars[-1]["close"]
    current_time = float(current_tick.time) if current_tick else time.time()

    recent_window = bars[-sens:]
    events: List[SweepEvent] = []

    for sw in swings:
        age = (len(bars) - 1) - sw.bar_index
        if age > lb or age < 1:
            continue
        for bar in recent_window:
            if _bar_sweeps_swing(bar, sw):
                if sw.kind == "high":
                    label = "BSL"
                    direction = "reversal_down"
                else:
                    label = "SSL"
                    direction = "reversal_up"
                distance_pct = abs((current_price - sw.level) / sw.level * 100.0)
                if distance_pct < SWEEP.min_distance_pct:
                    break
                events.append(SweepEvent(
                    symbol=symbol,
                    timeframe=tf_name,
                    kind=f"{sw.kind}_sweep",
                    sweep_label=label,
                    level=sw.level,
                    sweep_time=bar["time"],
                    sweep_close=bar["close"],
                    current_price=current_price,
                    current_time=current_time,
                    distance_pct=distance_pct,
                    direction=direction,
                ))
                break

    return events


def scan_market_watch_for_sweeps(
    timeframe: Optional[str] = None,
    fractal_n: Optional[int] = None,
    lookback: Optional[int] = None,
    sensitivity: Optional[int] = None,
    max_symbols: Optional[int] = None,
    symbols_override: Optional[List[str]] = None,
    save_to_db: bool = False,
) -> Tuple[List[SweepEvent], List[str]]:
    """Scanne tous les Market Watch symbols pour BSL/SSL sweeps.

    Args:
        symbols_override: Si fourni, utilise cette liste au lieu de Market Watch.
        save_to_db: Si True, sauvegarde les événements dans la base SQLite.
    """
    tf_name = timeframe or SWEEP.timeframe
    f_n = fractal_n if fractal_n is not None else SWEEP.fractal_n
    lb = lookback if lookback is not None else SWEEP.lookback
    sens = sensitivity if sensitivity is not None else SWEEP.sensitivity
    cap = max_symbols if max_symbols is not None else SWEEP.max_symbols

    mt5c = MT5Connector()
    if not mt5c.ensure_connected():
        return [], []

    if symbols_override is not None:
        symbols = list(symbols_override)
    else:
        symbols = mt5c.list_market_watch_symbols()
        if cap and len(symbols) > cap:
            logger.info(
                "Market Watch contient %d symboles ; limite appliquee = %d (utilise --all pour tout scanner).",
                len(symbols), cap,
            )
            symbols = symbols[:cap]

    all_events: List[SweepEvent] = []
    for sym in symbols:
        try:
            evs = detect_sweeps_for_symbol(sym, tf_name, f_n, lb, sens, _mt5c=mt5c)
            if evs:
                logger.info("[SWEEP] %s: %d evenement(s).", sym, len(evs))
                all_events.extend(evs)
        except Exception as e:
            logger.debug("Sweep scan failed pour %s: %s", sym, e)
        finally:
            try:
                mt5.symbol_select(sym, False)
            except Exception:
                pass

    # Sauvegarde automatique en DB (import lazy pour eviter l'import circulaire)
    if save_to_db and all_events and DB.auto_save_sweeps:
        from .database import get_db
        db = get_db()
        db.save_sweep_events_bulk(all_events)

    return all_events, symbols


def sort_events(events: List[SweepEvent], by_distance: bool = True) -> List[SweepEvent]:
    """Tri stable : symbole -> distance."""
    if by_distance:
        return sorted(events, key=lambda e: (e.symbol, e.distance_pct))
    return sorted(events, key=lambda e: (e.symbol, e.sweep_time))


def events_to_dicts(events: List[SweepEvent]) -> List[dict]:
    return [asdict(e) for e in events]


# --- Level Sweep Result (generic for daily / weekly / asian) ---
@dataclass
class LevelSweepResult:
    """Resultat de sweep d'un niveau (quotidien, hebdomadaire, etc.)."""
    symbol: str
    level_type: str            # "daily" / "weekly"
    level_date: str            # date du niveau (YYYY-MM-DD ou YYYY-WW)
    level_high: float          # PDH / PWH
    level_low: float           # PDL / PWL
    high_swept: bool
    low_swept: bool
    high_swept_at: Optional[float]
    high_swept_close: Optional[float]
    low_swept_at: Optional[float]
    low_swept_close: Optional[float]
    high_breached: bool        # mèche a traversé le haut (sans condition de close)
    low_breached: bool         # mèche a traversé le bas (sans condition de close)
    current_price: float
    current_time: float
    direction_target: str      # "AH" / "AL" / "BOTH" / "-"
    direction_target_label: str # "→ AH" / "→ AL" / "↔ Both" / "−" / "·"
    bars_checked: int


# --- Daily / Weekly level detection ---
def _check_level_sweeps(level_high: float, level_low: float,
                        bars: List[dict],
                        max_bars: int = 48) -> Tuple[bool, bool, Optional[float], Optional[float], Optional[float], Optional[float], bool, bool]:
    """Scanne les bougies pour des sweeps du niveau high/low.
    Retourne (high_swept, low_swept, high_at, high_close, low_at, low_close,
              high_breached, low_breached).
    - swept : mèche traverse + close rejette (ICT classique)
    - breached : mèche traverse (peu importe le close)"""
    high_swept = False
    low_swept = False
    high_breached = False
    low_breached = False
    high_at: Optional[float] = None
    high_close: Optional[float] = None
    low_at: Optional[float] = None
    low_close: Optional[float] = None

    for b in bars[:max_bars]:
        if not high_swept and _bar_sweeps_Asian_high(b, level_high):
            high_swept = True
            high_at = b["time"]
            high_close = b["close"]
        if not low_swept and _bar_sweeps_Asian_low(b, level_low):
            low_swept = True
            low_at = b["time"]
            low_close = b["close"]
        if not high_breached and _bar_breaches_high(b, level_high):
            high_breached = True
        if not low_breached and _bar_breaches_low(b, level_low):
            low_breached = True
        if high_swept and low_swept and high_breached and low_breached:
            break

    return high_swept, low_swept, high_at, high_close, low_at, low_close, high_breached, low_breached


def detect_daily_levels_for_symbol(
    symbol: str,
    scan_tf: str = "H1",
    lookback_days: int = 3,
    _mt5c: Optional[MT5Connector] = None,
) -> Optional[LevelSweepResult]:
    """Détecte PDH/PDL (Previous Day High/Low) + sweeps.

    Charge les D1, prend la veille comme niveau, scanne les bougies H1
    post-ouverture du jour pour détecter les sweeps.
    """
    tf = _TIMEFRAME_MAP.get(scan_tf.upper())
    if tf is None:
        logger.warning("Timeframe inconnu pour daily scan: %s", scan_tf)
        return None

    mt5c = _mt5c if _mt5c is not None else MT5Connector()
    if not mt5c.ensure_connected():
        return None
    mt5c.select_symbol(symbol)

    # Récupérer les D1 pour trouver le PDH/PDL
    d1_rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, lookback_days)
    if d1_rates is None or len(d1_rates) < 2:
        logger.debug("%s: pas assez de barres D1", symbol)
        return None

    d1_bars = _bars_to_dicts(d1_rates)
    d1_bars.sort(key=lambda b: b["time"])
    yesterday = d1_bars[-2]
    today_d1 = d1_bars[-1]

    level_high = yesterday["high"]
    level_low = yesterday["low"]
    yesterday_date = time.strftime("%Y-%m-%d", time.gmtime(yesterday["time"]))

    # Récupérer les bougies du timeframe de scan pour détecter les sweeps
    rates_raw = mt5.copy_rates_from_pos(symbol, tf, 0, 240)
    if rates_raw is None or len(rates_raw) == 0:
        # Fallback: copy_rates_from_pos
        rates_raw = mt5.copy_rates_from_pos(symbol, tf, 0, 48)
        if rates_raw is None or len(rates_raw) == 0:
            logger.debug("%s: pas de barres %s", symbol, scan_tf)
            return None

    scan_bars = _bars_to_dicts(rates_raw)
    scan_bars.sort(key=lambda b: b["time"])

    # Ne garder que les bougies après l'ouverture d'aujourd'hui (D1)
    today_open = today_d1["time"]
    post_bars = [b for b in scan_bars if b["time"] >= today_open]

    if not post_bars:
        # Si aucune bougie aujourd'hui, prendre les dernières bougies
        post_bars = scan_bars[-12:]

    # Détection des sweeps + breaches
    high_swept, low_swept, h_at, h_close, l_at, l_close, high_breached, low_breached = _check_level_sweeps(
        level_high, level_low, post_bars
    )

    # Prix courant
    tick = mt5.symbol_info_tick(symbol)
    current_price = float(tick.bid) if tick else (scan_bars[-1]["close"] if scan_bars else 0.0)
    current_time = float(tick.time) if tick else time.time()

    # Direction target
    midpoint = (level_high + level_low) / 2.0
    target_key = "-"
    target_label = "−"
    if high_swept and low_swept:
        target_key = "BOTH"
        target_label = "↔ Both"
    elif high_swept:
        target_key = "AL"
        if current_price < level_low:
            target_label = "·"  # deja sous le Low, plus une cible valide
        elif current_price < midpoint:
            target_label = "→ AL"
        else:
            target_label = "·"
    elif low_swept:
        target_key = "AH"
        if current_price > level_high:
            target_label = "·"  # deja au-dessus du High, plus une cible valide
        elif current_price > midpoint:
            target_label = "→ AH"
        else:
            target_label = "·"

    return LevelSweepResult(
        symbol=symbol,
        level_type="daily",
        level_date=yesterday_date,
        level_high=level_high,
        level_low=level_low,
        high_swept=high_swept,
        low_swept=low_swept,
        high_swept_at=h_at,
        high_swept_close=h_close,
        low_swept_at=l_at,
        low_swept_close=l_close,
        high_breached=high_breached,
        low_breached=low_breached,
        current_price=current_price,
        current_time=current_time,
        direction_target=target_key,
        direction_target_label=target_label,
        bars_checked=len(post_bars),
    )


def detect_weekly_levels_for_symbol(
    symbol: str,
    scan_tf: str = "D1",
    lookback_weeks: int = 3,
    _mt5c: Optional[MT5Connector] = None,
) -> Optional[LevelSweepResult]:
    """Détecte PWH/PWL (Previous Week High/Low) + sweeps.

    Charge les W1, prend la semaine dernière comme niveau, scanne les bougies D1
    de cette semaine pour détecter les sweeps.
    """
    tf = _TIMEFRAME_MAP.get(scan_tf.upper())
    if tf is None:
        logger.warning("Timeframe inconnu pour weekly scan: %s", scan_tf)
        return None

    mt5c = _mt5c if _mt5c is not None else MT5Connector()
    if not mt5c.ensure_connected():
        return None
    mt5c.select_symbol(symbol)

    # Récupérer les W1
    w1_rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_W1, 0, lookback_weeks)
    if w1_rates is None or len(w1_rates) < 2:
        logger.debug("%s: pas assez de barres W1", symbol)
        return None

    w1_bars = _bars_to_dicts(w1_rates)
    w1_bars.sort(key=lambda b: b["time"])
    last_week = w1_bars[-2]
    this_week = w1_bars[-1]

    level_high = last_week["high"]
    level_low = last_week["low"]
    level_week = time.strftime("%Y-W%W", time.gmtime(last_week["time"]))

    # Récupérer les D1 de cette semaine pour détecter les sweeps
    this_week_start = this_week["time"]
    d1_rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, 14)
    if d1_rates is None or len(d1_rates) == 0:
        d1_rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, 14)
        if d1_rates is None or len(d1_rates) == 0:
            logger.debug("%s: pas de barres D1", symbol)
            return None

    d1_bars = _bars_to_dicts(d1_rates)
    d1_bars.sort(key=lambda b: b["time"])
    post_bars = [b for b in d1_bars if b["time"] >= this_week_start]

    if not post_bars:
        post_bars = d1_bars[-3:]  # fallback

    # Détection des sweeps + breaches
    high_swept, low_swept, h_at, h_close, l_at, l_close, high_breached, low_breached = _check_level_sweeps(
        level_high, level_low, post_bars
    )

    # Prix courant
    tick = mt5.symbol_info_tick(symbol)
    current_price = float(tick.bid) if tick else (d1_bars[-1]["close"] if d1_bars else 0.0)
    current_time = float(tick.time) if tick else time.time()

    # Direction target
    midpoint = (level_high + level_low) / 2.0
    target_key = "-"
    target_label = "−"
    if high_swept and low_swept:
        target_key = "BOTH"
        target_label = "↔ Both"
    elif high_swept:
        target_key = "AL"
        if current_price < level_low:
            target_label = "·"  # deja sous le Low, plus une cible valide
        elif current_price < midpoint:
            target_label = "→ AL"
        else:
            target_label = "·"
    elif low_swept:
        target_key = "AH"
        if current_price > level_high:
            target_label = "·"  # deja au-dessus du High, plus une cible valide
        elif current_price > midpoint:
            target_label = "→ AH"
        else:
            target_label = "·"

    return LevelSweepResult(
        symbol=symbol,
        level_type="weekly",
        level_date=level_week,
        level_high=level_high,
        level_low=level_low,
        high_swept=high_swept,
        low_swept=low_swept,
        high_swept_at=h_at,
        high_swept_close=h_close,
        low_swept_at=l_at,
        low_swept_close=l_close,
        high_breached=high_breached,
        low_breached=low_breached,
        current_price=current_price,
        current_time=current_time,
        direction_target=target_key,
        direction_target_label=target_label,
        bars_checked=len(post_bars),
    )


def scan_market_watch_levels(
    level_type: str = "daily",
    scan_tf: str = "H1",
    max_symbols: Optional[int] = None,
    symbols_override: Optional[List[str]] = None,
) -> Tuple[List[LevelSweepResult], List[str]]:
    """Scanne tous les symboles du Market Watch pour les niveaux daily ou weekly."""
    cap = max_symbols if max_symbols is not None else SWEEP.max_symbols

    mt5c = MT5Connector()
    if not mt5c.ensure_connected():
        return [], []

    if symbols_override is not None:
        symbols = list(symbols_override)
    else:
        symbols = mt5c.list_market_watch_symbols()
        if cap and len(symbols) > cap:
            symbols = symbols[:cap]

    results: List[LevelSweepResult] = []
    for sym in symbols:
        try:
            if level_type == "daily":
                r = detect_daily_levels_for_symbol(sym, scan_tf, _mt5c=mt5c)
            else:
                r = detect_weekly_levels_for_symbol(sym, scan_tf, _mt5c=mt5c)
            if r is not None:
                results.append(r)
        except Exception as e:
            logger.debug("%s scan failed pour %s: %s", level_type, sym, e)
        finally:
            try:
                mt5.symbol_select(sym, False)
            except Exception:
                pass

    return results, symbols


# --- Asian Session Range + Sweep detection ---
@dataclass
class AsianRangeResult:
    """Resultat du scan du range asiatique + detection de sweeps post-Asian,
    sweeps d extension Fibonacci, et direction cible."""
    symbol: str
    timeframe: str
    session_date: str
    asian_high: float
    asian_low: float
    asian_high_swept: bool
    asian_low_swept: bool
    asian_high_breached: bool   # mèche a traversé le AH (sweep ou non)
    asian_low_breached: bool    # mèche a traversé le AL (sweep ou non)
    high_swept_at: Optional[float]
    high_swept_close: Optional[float]
    high_swept_session: Optional[str]
    high_swept_session_label: Optional[str]
    low_swept_at: Optional[float]
    low_swept_close: Optional[float]
    low_swept_session: Optional[str]
    low_swept_session_label: Optional[str]
    current_price: float
    current_time: float
    distance_high_pct: float
    distance_low_pct: float
    bars_checked: int
    direction_target: str            # "AH" / "AL" / "BOTH" / "-"
    direction_target_label: str      # "→ AH" / "→ AL" / "↔ Both" / "−" / "·"
    fib_plus_1618: float             # bull_base + 1.618 * range
    fib_minus_1618: float            # bear_base - 1.618 * range
    fib_state: str                   # "" / "+1.618" / "-1.618" / "+1.618_DONE" / "-1.618_DONE"
    fib_label: str                   # "→ +1.618" / "+1.618 ✓" / "→ -1.618" / "-1.618 ✓" / ""
    bull_fib_swept: bool
    bull_fib_swept_label: Optional[str]      # "+1.618" / "+2.0" / ... (deepest swept)
    bull_fib_swept_at: Optional[float]
    bull_fib_swept_close: Optional[float]
    bull_fib_swept_session: Optional[str]
    bull_fib_swept_session_label: Optional[str]
    bear_fib_swept: bool
    bear_fib_swept_label: Optional[str]      # "-1.618" / "-2.0" / ... (deepest swept)
    bear_fib_swept_at: Optional[float]
    bear_fib_swept_close: Optional[float]
    bear_fib_swept_session: Optional[str]
    bear_fib_swept_session_label: Optional[str]
    # Trade idea (ICT model: SL = 0.10*range past the opposite side,
    # TP ladder = +-1.618 / +-2.618 / +-4.0 fib extensions).
    trade_action: str            # "BUY" / "SELL" / "-"
    trade_status: str            # "Active" / "Wait pullback" / "Targets hit" / "Range too tight" / "-"
    trade_entry: Optional[float]
    trade_sl: Optional[float]
    trade_tp1: Optional[float]
    trade_tp2: Optional[float]
    trade_tp3: Optional[float]
    trade_rr1: Optional[float]   # risk:reward to TP1
    trade_rr2: Optional[float]   # risk:reward to TP2
    trade_plan_label: str        # "BUY 1.34356" / "SELL 1.34250" / "-"
    spread_pct: float = 0.0       # spread actuel en % du prix bid
    symbol_type: str = ""         # classification (FOREX_USD, METAL, INDEX, ...)
    is_elite: bool = False        # True si le trade passe le filtre ELITE v2
    elite_reason: str = ""        # raison si rejeté (hors fenêtre, mauvais type, RR trop bas, spread)
    is_elite_v1: bool = False      # True si le trade passe le filtre ELITE v1
    elite_v1_reason: str = ""      # raison si rejeté du filtre v1


def _session_for_epoch(epoch: float) -> Tuple[str, str]:
    """Determine (cle, label-court) ICT pour un epoch UTC."""
    h = (int(epoch) // 3600) % 24
    if 0 <= h < 8:
        return ("Asian", "Asian")
    if 7 <= h < 13:
        return ("London", "London")
    if 13 <= h < 16:
        return ("NY_Open", "NY Open")
    if 13 <= h < 21:
        return ("New_York", "NY")
    if h >= 22:
        return ("Asian_pre", "Asian pre")
    return ("Off_hours", "Off")


def _bar_sweeps_Asian_high(b: dict, h: float) -> bool:
    """Sweep classique ICT : mèche traverse + close rejette de l'autre côté."""
    return b["high"] > h and b["close"] < h


def _bar_sweeps_Asian_low(b: dict, low: float) -> bool:
    """Sweep classique ICT : mèche traverse + close rejette de l'autre côté."""
    return b["low"] < low and b["close"] > low


def _bar_breaches_high(b: dict, level: float) -> bool:
    """Breach : la mèche traverse le niveau haut, peu importe le close (pas de rejet)."""
    return b["high"] > level


def _bar_breaches_low(b: dict, level: float) -> bool:
    """Breach : la mèche traverse le niveau bas, peu importe le close (pas de rejet)."""
    return b["low"] < level


def detect_asian_range_for_symbol(
    symbol: str,
    timeframe: Optional[str] = None,
    session_date: Optional[str] = None,
    start_utc: int = 0,
    end_utc: int = 8,
    max_bars_after: int = 240,
    _mt5c: Optional[MT5Connector] = None,
) -> Optional[AsianRangeResult]:
    """Calcule le range asiatique du jour (UTC) + detecte sweeps post-Asian
    (Asian High/Low + niveaux d extension Fibonacci).

    Args:
        _mt5c: Connecteur MT5 optionnel. Si fourni, il est reutilise tel quel
               (pas de select_symbol, pas de nouvel ensure_connected). Utile
               pour les batch scans (--all) ou on ne veut pas saturer le
               Market Watch avec 167 select_symbol().
    """
    tf_name = (timeframe or "H1").upper()
    tf = _TIMEFRAME_MAP.get(tf_name)
    if tf is None:
        logger.warning("Timeframe inconnu pour Asian scan: %s", tf_name)
        return None

    if session_date is None:
        session_date = time.strftime("%Y-%m-%d", time.gmtime())

    # Reutiliser le connecteur fourni ou en creer un nouveau
    mt5c = _mt5c if _mt5c is not None else MT5Connector()
    if not mt5c.ensure_connected():
        return None
    # select_symbol EST necessaire pour que MT5 charge/cache les donnees.
    # En mode batch, on nettoie le Market Watch apres pour eviter la saturation.
    mt5c.select_symbol(symbol)

    lookback_bars = max(240, 24 * 14)
    rates_raw = mt5.copy_rates_from_pos(symbol, tf, 0, lookback_bars)
    if rates_raw is None or len(rates_raw) == 0:
        logger.debug("%s: aucune barre %s", symbol, tf_name)
        return None

    bars = _bars_to_dicts(rates_raw)
    bars.sort(key=lambda b: b["time"])

    asian_bars: List[dict] = []
    for b in bars:
        d = time.strftime("%Y-%m-%d", time.gmtime(b["time"]))
        if d != session_date:
            continue
        h_utc = (b["time"] % 86400) // 3600
        if start_utc <= h_utc < end_utc:
            asian_bars.append(b)

    if not asian_bars:
        logger.debug("%s: pas de barres Asian pour %s", symbol, session_date)
        return None

    asian_high = max(b["high"] for b in asian_bars)
    asian_low = min(b["low"] for b in asian_bars)
    last_asian_time = max(b["time"] for b in asian_bars)

    # 🔧 CORRECTION BUG: scanner TOUTES les barres du jour (y compris intra-asian)
    # pour les sweeps, pas seulement les barres apres la session asiatique.
    # Avant: seules les barres > last_asian_time (08:00 UTC) etaient scannees.
    # Un sweep intra-session a 07:45 UTC (9h45 Paris) etait ignore.
    # Maintenant: on scanne depuis la premiere barre asiatique du jour.
    first_asian_time = min(b["time"] for b in asian_bars)
    all_day_bars = [b for b in bars if b["time"] >= first_asian_time]
    all_day_bars = all_day_bars[:max_bars_after]

    high_swept = False
    low_swept = False
    high_breached = False
    low_breached = False
    high_swept_at: Optional[float] = None
    high_swept_close: Optional[float] = None
    high_swept_session: Optional[str] = None
    high_swept_label: Optional[str] = None
    low_swept_at: Optional[float] = None
    low_swept_close: Optional[float] = None
    low_swept_session: Optional[str] = None
    low_swept_label: Optional[str] = None

    for b in all_day_bars:
        if not high_swept and _bar_sweeps_Asian_high(b, asian_high):
            high_swept = True
            high_swept_at = b["time"]
            high_swept_close = b["close"]
            high_swept_session, high_swept_label = _session_for_epoch(b["time"])
        if not low_swept and _bar_sweeps_Asian_low(b, asian_low):
            low_swept = True
            low_swept_at = b["time"]
            low_swept_close = b["close"]
            low_swept_session, low_swept_label = _session_for_epoch(b["time"])
        if not high_breached and _bar_breaches_high(b, asian_high):
            high_breached = True
        if not low_breached and _bar_breaches_low(b, asian_low):
            low_breached = True
        if high_swept and low_swept and high_breached and low_breached:
            break

    # --- Fibonacci level sweep detection ---
    # Pour chaque niveau ICT (+1.618, +2.0, ... +4.0 et negatifs), on cherche le
    # PREMIER bar (intra-asian inclus) qui le sweep, puis on garde le PLUS PROFOND.
    # Sweep = wick + rejet (meme definition ICT que les sweeps Asian High/Low).
    range_size = asian_high - asian_low
    # Base Fibonacci configurable : "AH" = extensions depuis le haut (ICT agressif),
    # "AL" = extensions depuis le swing low (fib standard). Defaut = "AH" (prouve 74% WR).
    _fib_base = getattr(ASIAN, 'fib_base', 'AH')
    if _fib_base not in ("AH", "AL"):
        raise ValueError(
            f"ASIAN.fib_base must be 'AH' or 'AL', got {_fib_base!r}"
        )
    bull_base = asian_low if _fib_base == 'AL' else asian_high
    bear_base = asian_high if _fib_base == 'AL' else asian_low
    bull_fib_swept = False
    bull_fib_swept_lbl: Optional[str] = None
    bull_fib_swept_at_v: Optional[float] = None
    bull_fib_swept_close_v: Optional[float] = None
    bull_fib_session_key: Optional[str] = None
    bull_fib_session_lbl_str: Optional[str] = None
    bear_fib_swept = False
    bear_fib_swept_lbl: Optional[str] = None
    bear_fib_swept_at_v: Optional[float] = None
    bear_fib_swept_close_v: Optional[float] = None
    bear_fib_session_key: Optional[str] = None
    bear_fib_session_lbl_str: Optional[str] = None

    if range_size > 0:
        bull_hits = []
        for n in _FIB_LEVELS_BULL:
            lvl = bull_base + n * range_size
            for b in all_day_bars:
                if b["high"] > lvl and b["close"] < lvl:
                    bull_hits.append((n, b["time"], b["close"]))
                    break
        if bull_hits:
            n_max, t_at, c_close = bull_hits[-1]   # deepest (last in ascending list)
            bull_fib_swept = True
            bull_fib_swept_lbl = f"+{n_max}"
            bull_fib_swept_at_v = t_at
            bull_fib_swept_close_v = c_close
            bull_fib_session_key, bull_fib_session_lbl_str = _session_for_epoch(t_at)

        bear_hits = []
        for n in _FIB_LEVELS_BEAR:
            lvl = bear_base + n * range_size   # n est negatif -> lvl < bear_base
            for b in all_day_bars:
                if b["low"] < lvl and b["close"] > lvl:
                    bear_hits.append((n, b["time"], b["close"]))
                    break
        if bear_hits:
            n_min, t_at, c_close = bear_hits[-1]   # deepest (last = most negative)
            bear_fib_swept = True
            bear_fib_swept_lbl = f"{n_min}"
            bear_fib_swept_at_v = t_at
            bear_fib_swept_close_v = c_close
            bear_fib_session_key, bear_fib_session_lbl_str = _session_for_epoch(t_at)

    tick = mt5.symbol_info_tick(symbol)
    spread_pct = 0.0
    if tick:
        current_price = float(tick.bid)
        current_time = float(tick.time)
        if tick.bid > 0 and tick.ask > 0:
            spread_pct = (tick.ask - tick.bid) / tick.bid * 100.0
    else:
        current_price = bars[-1]["close"] if bars else 0.0
        current_time = time.time()

    distance_high_pct = (
        abs((current_price - asian_high) / asian_high * 100.0) if asian_high else 0.0
    )
    distance_low_pct = (
        abs((current_price - asian_low) / asian_low * 100.0) if asian_low else 0.0
    )

    # Direction "vers l autre liquidite" (logique ICT)
    midpoint_value = (asian_high + asian_low) / 2.0
    target_key = "-"
    target_label = "−"
    if high_swept and low_swept:
        target_key = "BOTH"
        target_label = "↔ Both"
    elif high_swept:
        target_key = "AL"
        if current_price < asian_low:
            target_label = "·"  # deja sous le AL, plus une cible valide
        elif current_price < midpoint_value:
            target_label = "→ AL"
        else:
            target_label = "·"
    elif low_swept:
        target_key = "AH"
        if current_price > asian_high:
            target_label = "·"  # deja au-dessus du AH, plus une cible valide
        elif current_price > midpoint_value:
            target_label = "→ AH"
        else:
            target_label = "·"

    # Fib expansion multi-niveaux (prochaine cible non atteinte dans la direction du mouvement)
    fib_plus_1618 = bull_base + 1.618 * range_size
    fib_minus_1618 = bear_base - 1.618 * range_size
    fib_state_val = ""
    fib_label_val = ""

    def _next_bull(price: float, al: float, rs: float) -> Tuple[str, str]:
        for n in _FIB_LEVELS_BULL:
            lvl = al + n * rs
            if price < lvl:
                return f"+{n}", f"→ +{n}"
        last = _FIB_LEVELS_BULL[-1]
        return f"+{last}_DONE", f"+{last}"

    def _next_bear(price: float, ah: float, rs: float) -> Tuple[str, str]:
        for n in _FIB_LEVELS_BEAR:
            lvl = ah + n * rs   # n negatif -> lvl < ah
            if price > lvl:
                return f"{n}", f"→ {n}"
        last = _FIB_LEVELS_BEAR[-1]
        return f"{last}_DONE", f"{last}"

    # --- Priorite 1 : sweep + traverse vers l'autre liquidite (classique) ---
    if low_swept and current_price > asian_high:
        # SSL sweep → prix traverse vers le haut → BUY classique
        fib_state_val, fib_label_val = _next_bull(current_price, bull_base, range_size)
    elif high_swept and current_price < asian_low:
        # BSL sweep → prix traverse vers le bas → SELL classique
        fib_state_val, fib_label_val = _next_bear(current_price, bear_base, range_size)
    # --- Priorite 2 : double sweep → vers la liquidite non testee ---
    elif high_swept and low_swept:
        if current_price > asian_high:
            fib_state_val, fib_label_val = _next_bull(current_price, bull_base, range_size)
        elif current_price < asian_low:
            fib_state_val, fib_label_val = _next_bear(current_price, bear_base, range_size)
    # --- Priorité 3 : fakeout / continuation (sweep + prix meme cote) ---
    elif high_swept and current_price > asian_high:
        # BSL swept → prix continue de monter (fakeout baissier → bullish)
        fib_state_val, fib_label_val = _next_bull(current_price, bull_base, range_size)
    elif low_swept and current_price < asian_low:
        # SSL swept → prix continue de descendre (fakeout haussier → bearish)
        fib_state_val, fib_label_val = _next_bear(current_price, bear_base, range_size)

    # --- Trade idea generation (ICT model) ---
    # SL = 0.10*range past the opposite side (full setup invalidation wick + buffer).
    #
    # TP : on utilise le PROCHAIN niveau fib non atteint (celui de fib_state_val)
    # et pas 1.618 hardcode.  Explication du bug corrige : quand le prix a deja
    # depasse AH, il peut etre au-dessus de +1.618.  Hardcoder TP1 a 1.618
    # donne un TP en-dessous du prix d'entree pour un BUY -> TP = perte.
    #
    # fib_state_val est le resultat de _next_bull / _next_bear qui renvoie le
    # premier niveau fib au-dessus du prix (bull) ou en-dessous (bear).
    # Exemples : "+1.618" "+2.0" "-2.618"  (jamais _DONE ici car filtre avant).
    # Entry = current_price (market entry).
    is_bull_trade = bool(fib_state_val and fib_state_val.startswith("+"))
    is_bear_trade = bool(fib_state_val and fib_state_val.startswith("-"))
    is_done_trade = "_DONE" in fib_state_val
    trade_action = "-"
    trade_status_v = "Wait breakout"
    trade_entry_v: Optional[float] = None
    trade_sl_v: Optional[float] = None
    trade_tp1_v: Optional[float] = None
    trade_tp2_v: Optional[float] = None
    trade_tp3_v: Optional[float] = None
    trade_rr1_v: Optional[float] = None
    trade_rr2_v: Optional[float] = None
    trade_plan_label_v = "-"
    if midpoint_value > 0 and range_size > 0:
        range_pct = range_size / midpoint_value * 100.0
        if range_pct < 0.05:
            trade_status_v = "Range too tight"
        elif is_done_trade:
            trade_status_v = "Targets hit"
        elif is_bull_trade:
            trade_action = "BUY"
            trade_entry_v = current_price
            trade_sl_v = asian_low - 0.10 * range_size
            # ---- TP derives de fib_state_val (prochain niveau au-dessus du prix) ----
            try:
                fib_num = float(fib_state_val[1:])  # "+2.0" -> 2.0
            except (ValueError, AttributeError):
                fib_num = 1.618
            # Index du premier niveau >= fib_num dans la liste bull
            idx = next((i for i, n in enumerate(_FIB_LEVELS_BULL)
                        if n >= fib_num - 0.001), 0)
            tp_candidates = _FIB_LEVELS_BULL[idx:idx + 3]
            if len(tp_candidates) >= 1:
                trade_tp1_v = bull_base + tp_candidates[0] * range_size
            if len(tp_candidates) >= 2:
                trade_tp2_v = bull_base + tp_candidates[1] * range_size
            if len(tp_candidates) >= 3:
                trade_tp3_v = bull_base + tp_candidates[2] * range_size
            # Securite : si TP1 est en-dessous (ou egal) a l'entry, on skip au suivant
            if trade_tp1_v is not None and trade_tp1_v <= trade_entry_v:
                if len(tp_candidates) >= 2:
                    trade_tp1_v = asian_low + tp_candidates[1] * range_size
                    trade_tp2_v = (asian_low + tp_candidates[2] * range_size
                                   if len(tp_candidates) >= 3 else None)
                    trade_tp3_v = None
                else:
                    trade_tp1_v = None
                    trade_status_v = "No valid TP"
            # ---- RR ----
            risk = trade_entry_v - trade_sl_v
            if risk > 0 and trade_tp1_v is not None and trade_tp1_v > trade_entry_v:
                trade_rr1_v = (trade_tp1_v - trade_entry_v) / risk
                if trade_tp2_v is not None and trade_tp2_v > trade_entry_v:
                    trade_rr2_v = (trade_tp2_v - trade_entry_v) / risk
            trade_status_v = "Active"
            trade_plan_label_v = f"BUY {_fmt_price_adaptive(trade_entry_v)}"
        elif is_bear_trade:
            trade_action = "SELL"
            trade_entry_v = current_price
            trade_sl_v = asian_high + 0.10 * range_size
            # ---- TP derives de fib_state_val (prochain niveau en-dessous du prix) ----
            try:
                fib_num = float(fib_state_val[1:])  # "-2.0" -> 2.0
            except (ValueError, AttributeError):
                fib_num = 1.618
            # Index du premier niveau <= -fib_num dans la liste bear
            # (_FIB_LEVELS_BEAR contient des valeurs negatives: -1.618, -2.0, ...)
            idx = next((i for i, n in enumerate(_FIB_LEVELS_BEAR)
                        if n <= -fib_num + 0.001), 0)
            tp_candidates = _FIB_LEVELS_BEAR[idx:idx + 3]
            if len(tp_candidates) >= 1:
                trade_tp1_v = bear_base + tp_candidates[0] * range_size
            if len(tp_candidates) >= 2:
                trade_tp2_v = bear_base + tp_candidates[1] * range_size
            if len(tp_candidates) >= 3:
                trade_tp3_v = bear_base + tp_candidates[2] * range_size
            # Securite : si TP1 est au-dessus (ou egal) a l'entry, on skip au suivant
            if trade_tp1_v is not None and trade_tp1_v >= trade_entry_v:
                if len(tp_candidates) >= 2:
                    trade_tp1_v = asian_high + tp_candidates[1] * range_size
                    trade_tp2_v = (asian_high + tp_candidates[2] * range_size
                                   if len(tp_candidates) >= 3 else None)
                    trade_tp3_v = None
                else:
                    trade_tp1_v = None
                    trade_status_v = "No valid TP"
            # ---- RR ----
            risk = trade_sl_v - trade_entry_v
            if risk > 0 and trade_tp1_v is not None and trade_tp1_v < trade_entry_v:
                trade_rr1_v = (trade_entry_v - trade_tp1_v) / risk
                if trade_tp2_v is not None and trade_tp2_v < trade_entry_v:
                    trade_rr2_v = (trade_entry_v - trade_tp2_v) / risk
            trade_status_v = "Active"
            trade_plan_label_v = f"SELL {_fmt_price_adaptive(trade_entry_v)}"

    # --- Filtre ELITE (v2) ---
    sym_type = _classify_symbol(symbol)
    is_elite = False
    elite_reason = ""
    if ELITE.enabled and trade_action != "-":
        now = time.gmtime()
        now_hour = now.tm_hour
        now_min = now.tm_min
        in_window = (
            (now_hour > ELITE.start_hour_utc or (now_hour == ELITE.start_hour_utc and now_min >= ELITE.start_minute_utc))
            and (now_hour < ELITE.end_hour_utc or (now_hour == ELITE.end_hour_utc and now_min <= ELITE.end_minute_utc))
        )
        if not in_window:
            elite_reason = "hors fenetre"
        elif sym_type not in ELITE.allowed_types:
            elite_reason = f"type {sym_type} non ELITE"
        elif (trade_rr1_v or 0) < ELITE.min_rr:
            elite_reason = f"RR {trade_rr1_v or 0:.2f} < {ELITE.min_rr}"
        elif spread_pct > ELITE.max_spread_pct:
            elite_reason = f"spread {spread_pct:.3f}% > {ELITE.max_spread_pct}%"
        else:
            is_elite = True

    # --- Filtre ELITE V1 (original) ---
    is_elite_v1 = False
    elite_v1_reason = ""
    if ELITE_V1.enabled and trade_action != "-":
        now = time.gmtime()
        now_hour = now.tm_hour
        now_min = now.tm_min
        in_window_v1 = (
            (now_hour > ELITE_V1.start_hour_utc or (now_hour == ELITE_V1.start_hour_utc and now_min >= ELITE_V1.start_minute_utc))
            and (now_hour < ELITE_V1.end_hour_utc or (now_hour == ELITE_V1.end_hour_utc and now_min <= ELITE_V1.end_minute_utc))
        )
        if not in_window_v1:
            elite_v1_reason = "hors fenetre v1"
        elif sym_type not in ELITE_V1.allowed_types:
            elite_v1_reason = f"type {sym_type} non ELITE v1"
        elif (trade_rr1_v or 0) < ELITE_V1.min_rr:
            elite_v1_reason = f"RR {trade_rr1_v or 0:.2f} < {ELITE_V1.min_rr}"
        elif spread_pct > ELITE_V1.max_spread_pct:
            elite_v1_reason = f"spread {spread_pct:.3f}% > {ELITE_V1.max_spread_pct}%"
        else:
            is_elite_v1 = True

    return AsianRangeResult(
        symbol=symbol,
        timeframe=tf_name,
        session_date=session_date,
        asian_high=asian_high,
        asian_low=asian_low,
        asian_high_swept=high_swept,
        asian_low_swept=low_swept,
        asian_high_breached=high_breached,
        asian_low_breached=low_breached,
        high_swept_at=high_swept_at,
        high_swept_close=high_swept_close,
        high_swept_session=high_swept_session,
        high_swept_session_label=high_swept_label,
        low_swept_at=low_swept_at,
        low_swept_close=low_swept_close,
        low_swept_session=low_swept_session,
        low_swept_session_label=low_swept_label,
        current_price=current_price,
        current_time=current_time,
        distance_high_pct=distance_high_pct,
        distance_low_pct=distance_low_pct,
        bars_checked=len(post_bars),
        direction_target=target_key,
        direction_target_label=target_label,
        fib_plus_1618=fib_plus_1618,
        fib_minus_1618=fib_minus_1618,
        fib_state=fib_state_val,
        fib_label=fib_label_val,
        bull_fib_swept=bull_fib_swept,
        bull_fib_swept_label=bull_fib_swept_lbl,
        bull_fib_swept_at=bull_fib_swept_at_v,
        bull_fib_swept_close=bull_fib_swept_close_v,
        bull_fib_swept_session=bull_fib_session_key,
        bull_fib_swept_session_label=bull_fib_session_lbl_str,
        bear_fib_swept=bear_fib_swept,
        bear_fib_swept_label=bear_fib_swept_lbl,
        bear_fib_swept_at=bear_fib_swept_at_v,
        bear_fib_swept_close=bear_fib_swept_close_v,
        bear_fib_swept_session=bear_fib_session_key,
        bear_fib_swept_session_label=bear_fib_session_lbl_str,
        trade_action=trade_action,
        trade_status=trade_status_v,
        trade_entry=trade_entry_v,
        trade_sl=trade_sl_v,
        trade_tp1=trade_tp1_v,
        trade_tp2=trade_tp2_v,
        trade_tp3=trade_tp3_v,
        trade_rr1=trade_rr1_v,
        trade_rr2=trade_rr2_v,
        trade_plan_label=trade_plan_label_v,
        spread_pct=spread_pct,
        symbol_type=sym_type,
        is_elite=is_elite,
        elite_reason=elite_reason,
        is_elite_v1=is_elite_v1,
        elite_v1_reason=elite_v1_reason,
    )


def scan_market_watch_asian_ranges(
    timeframe: Optional[str] = None,
    session_date: Optional[str] = None,
    max_symbols: Optional[int] = None,
    symbols_override: Optional[List[str]] = None,
    save_to_db: bool = False,
) -> Tuple[List[AsianRangeResult], List[str]]:
    """Scan tous les symboles visibles du Market Watch pour leur range asiatique.

    Args:
        symbols_override: Si fourni, utilise cette liste au lieu de Market Watch.
        save_to_db: Si True, sauvegarde les résultats dans la base SQLite.
    """
    tf_name = (timeframe or "H1").upper()
    cap = max_symbols if max_symbols is not None else SWEEP.max_symbols

    mt5c = MT5Connector()
    if not mt5c.ensure_connected():
        return [], []

    if symbols_override is not None:
        symbols = list(symbols_override)
    else:
        symbols = mt5c.list_market_watch_symbols()
        if cap and len(symbols) > cap:
            logger.info(
                "Market Watch contient %d symboles ; limite appliquee = %d (utilise --all).",
                len(symbols), cap,
            )
            symbols = symbols[:cap]

    results: List[AsianRangeResult] = []
    for sym in symbols:
        try:
            r = detect_asian_range_for_symbol(sym, tf_name, session_date,
                                               _mt5c=mt5c)
            if r is not None:
                results.append(r)
        except Exception as e:
            logger.debug("Asian scan failed pour %s: %s", sym, e)
        finally:
            # Nettoyer le Market Watch pour ne pas saturer avec 167 symboles
            # en mode --scan-all. Safe a appeler meme si le symbole n'etait
            # pas dans le Market Watch.
            try:
                mt5.symbol_select(sym, False)
            except Exception:
                pass

    # Sauvegarde automatique en DB (import lazy pour eviter l'import circulaire)
    if save_to_db and results and DB.auto_save_asian:
        from .database import get_db
        db = get_db()
        db.save_asian_results_bulk(results)

    return results, symbols


def asians_to_dicts(results: List[AsianRangeResult]) -> List[dict]:
    out: List[dict] = []
    for r in results:
        out.append({
            "symbol": r.symbol,
            "timeframe": r.timeframe,
            "session_date": r.session_date,
            "asian_high": r.asian_high,
            "asian_low": r.asian_low,
            "asian_high_swept": r.asian_high_swept,
            "asian_low_swept": r.asian_low_swept,
            "asian_high_breached": r.asian_high_breached,
            "asian_low_breached": r.asian_low_breached,
            "high_swept_at": r.high_swept_at,
            "high_swept_close": r.high_swept_close,
            "high_swept_session": r.high_swept_session,
            "high_swept_session_label": r.high_swept_session_label,
            "low_swept_at": r.low_swept_at,
            "low_swept_close": r.low_swept_close,
            "low_swept_session": r.low_swept_session,
            "low_swept_session_label": r.low_swept_session_label,
            "current_price": r.current_price,
            "current_time": r.current_time,
            "distance_high_pct": r.distance_high_pct,
            "distance_low_pct": r.distance_low_pct,
            "bars_checked": r.bars_checked,
            "direction_target": r.direction_target,
            "direction_target_label": r.direction_target_label,
            "fib_plus_1618": r.fib_plus_1618,
            "fib_minus_1618": r.fib_minus_1618,
            "fib_state": r.fib_state,
            "fib_label": r.fib_label,
            "bull_fib_swept": r.bull_fib_swept,
            "bull_fib_swept_label": r.bull_fib_swept_label,
            "bull_fib_swept_at": r.bull_fib_swept_at,
            "bull_fib_swept_close": r.bull_fib_swept_close,
            "bull_fib_swept_session": r.bull_fib_swept_session,
            "bull_fib_swept_session_label": r.bull_fib_swept_session_label,
            "bear_fib_swept": r.bear_fib_swept,
            "bear_fib_swept_label": r.bear_fib_swept_label,
            "bear_fib_swept_at": r.bear_fib_swept_at,
            "bear_fib_swept_close": r.bear_fib_swept_close,
            "bear_fib_swept_session": r.bear_fib_swept_session,
            "bear_fib_swept_session_label": r.bear_fib_swept_session_label,
            "high_swept_at_utc": (
                time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(r.high_swept_at))
                if r.high_swept_at else None
            ),
            "low_swept_at_utc": (
                time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(r.low_swept_at))
                if r.low_swept_at else None
            ),
            "bull_fib_swept_at_utc": (
                time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(r.bull_fib_swept_at))
                if r.bull_fib_swept_at else None
            ),
            "bear_fib_swept_at_utc": (
                time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(r.bear_fib_swept_at))
                if r.bear_fib_swept_at else None
            ),
            "trade_action": r.trade_action,
            "trade_status": r.trade_status,
            "trade_entry": r.trade_entry,
            "trade_sl": r.trade_sl,
            "trade_tp1": r.trade_tp1,
            "trade_tp2": r.trade_tp2,
            "trade_tp3": r.trade_tp3,
            "trade_rr1": r.trade_rr1,
            "trade_rr2": r.trade_rr2,
            "trade_plan_label": r.trade_plan_label,
            "spread_pct": r.spread_pct,
            "symbol_type": r.symbol_type,
            "is_elite": r.is_elite,
            "elite_reason": r.elite_reason,
            "is_elite_v1": r.is_elite_v1,
            "elite_v1_reason": r.elite_v1_reason,
        })
    return out
