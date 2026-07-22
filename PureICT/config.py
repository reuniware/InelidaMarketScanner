"""PureICT — Constantes et fonctions utilitaires temps/format.

Dependances :
  - src.time_utils.now_datetime
  - src.config._dst_eu_summer, format_epoch (importe comme _fmt_epoch_tz)
  - MetaTrader5 (pour les constantes TIMEFRAMES)
"""

import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

# Chemin projet pour importer src.*
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Forcer l'encodage UTF-8
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except AttributeError:
    pass

try:
    import MetaTrader5 as mt5
except ImportError:
    print("\n  !! MetaTrader5 n'est pas installe.")
    print("     Installe-le avec : pip install MetaTrader5")
    print("     Puis verifie que MT5 est lance et connecte.\n")
    sys.exit(1)

from src.time_utils import now_datetime
from src.config import _dst_eu_summer

logger = logging.getLogger("PureICT.Config")


# ===============================================================================
# CONSTANTES DE SESSION
# ===============================================================================

DEFAULT_START_HOUR = 0
DEFAULT_END_HOUR = 8
DEFAULT_TIMEZONE = "PARIS"

TIMEFRAMES = {
    "M1":  mt5.TIMEFRAME_M1,
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1":  mt5.TIMEFRAME_H1,
}
DEFAULT_TF = "M15"

LOOKBACK_BARS = {
    "M1":  6000,
    "M5":  1200,
    "M15": 400,
    "M30": 200,
    "H1":  100,
}

FVG_TIMEFRAMES = {
    "M1":  mt5.TIMEFRAME_M1,
    "M3":  mt5.TIMEFRAME_M3,
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
}

FVG_LOOKBACK = {
    "M1":  1440,
    "M3":  480,
    "M5":  288,
    "M15": 96,
}

DEFAULT_FVG_MIN_PCT = 0.02


# ===============================================================================
# MAX LOTS
# ===============================================================================

def calc_max_lots(symbol: str, price: float) -> Tuple[Optional[float], Optional[float], str]:
    """Calcule le nombre de lots maximum negociable pour un symbole (marge libre)."""
    try:
        acc = mt5.account_info()
        if acc is None:
            return None, None, ""
        free_margin = acc.margin_free
        currency = acc.currency or ""

        if free_margin <= 0:
            return 0.0, None, currency

        margin_for_1 = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, symbol, 1.0, price)
        if margin_for_1 is None or margin_for_1 <= 0:
            return None, None, currency

        max_lots_raw = free_margin / margin_for_1
        info = mt5.symbol_info(symbol)
        if info is None:
            return None, margin_for_1, currency

        step = info.volume_step or 0.01
        max_lots = (int(max_lots_raw / step)) * step
        limit_max = info.volume_max
        if max_lots > limit_max:
            max_lots = limit_max
        if max_lots < info.volume_min:
            max_lots = info.volume_min

        return round(max_lots, 2), round(margin_for_1, 2), currency

    except Exception as e:
        logger.debug("calc_max_lots(%s) a echoue: %s", symbol, e)
        return None, None, ""


# ===============================================================================
# HELPERS TEMPS
# ===============================================================================

def paris_offset() -> int:
    """Decalage Paris vs UTC : +2 ete (CEST), +1 hiver (CET)."""
    return 2 if _dst_eu_summer() else 1


def paris_now() -> datetime:
    """Retourne la date/heure actuelle en fuseau Paris (CEST/CET)."""
    return now_datetime() + timedelta(hours=paris_offset())


def paris_date_str(dt: Optional[datetime] = None) -> str:
    """Retourne la date format YYYY-MM-DD en fuseau Paris."""
    return (dt or paris_now()).strftime("%Y-%m-%d")


def _tz_offset(mode: str = DEFAULT_TIMEZONE) -> int:
    """Retourne le decalage UTC pour un fuseau (PARIS/BROKER/UTC)."""
    m = mode.upper()
    dst = _dst_eu_summer()
    if m == "UTC":
        return 0
    if m == "BROKER":
        return 3 if dst else 2
    return 2 if dst else 1


def _session_true_utc_end(
    session_date: str,
    end_hour: int = DEFAULT_END_HOUR,
    tz_mode: str = DEFAULT_TIMEZONE,
) -> datetime:
    """Retourne la VRAIE fin de session en UTC."""
    offset = _tz_offset(tz_mode)
    local_tz = timezone(timedelta(hours=offset))
    local_dt = datetime.strptime(session_date, "%Y-%m-%d").replace(tzinfo=local_tz)
    return local_dt.replace(hour=end_hour, minute=0, second=0).astimezone(timezone.utc)


def _session_true_utc_start(
    session_date: str,
    start_hour: int = DEFAULT_START_HOUR,
    tz_mode: str = DEFAULT_TIMEZONE,
) -> datetime:
    """Retourne la VRAIE date/heure de debut de session en UTC."""
    offset = _tz_offset(tz_mode)
    local_tz = timezone(timedelta(hours=offset))
    local_dt = datetime.strptime(session_date, "%Y-%m-%d").replace(tzinfo=local_tz)
    return local_dt.replace(hour=start_hour, minute=0, second=0).astimezone(timezone.utc)


def is_in_asian_session(
    start_hour: int = DEFAULT_START_HOUR,
    end_hour: int = DEFAULT_END_HOUR,
    tz_mode: str = DEFAULT_TIMEZONE,
) -> bool:
    """Verifie si maintenant est dans la fenetre de session asiatique."""
    offset = _tz_offset(tz_mode)
    local_now = now_datetime() + timedelta(hours=offset)
    session_start_today = local_now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    session_end_today = local_now.replace(hour=end_hour, minute=0, second=0, microsecond=0)
    if start_hour < end_hour:
        return session_start_today <= local_now < session_end_today
    else:
        return local_now >= session_start_today or local_now < session_end_today


def _smart_session_date(
    end_hour: int = DEFAULT_END_HOUR,
    tz_mode: str = DEFAULT_TIMEZONE,
) -> str:
    """Selection intelligente de la session (logique MQL5)."""
    offset = _tz_offset(tz_mode)
    local_now = now_datetime() + timedelta(hours=offset)
    session_end_today = local_now.replace(hour=end_hour, minute=0, second=0, microsecond=0)
    if local_now < session_end_today:
        local_now -= timedelta(days=1)
    return local_now.strftime("%Y-%m-%d")


# ===============================================================================
# FORMATAGE
# ===============================================================================

def format_epoch(epoch: float) -> str:
    """Formate un epoch UTC en HH:MM:SS."""
    return time.strftime("%H:%M:%S", time.gmtime(epoch))


def _fmt_fvg_compact(fvg_entries: Optional[list]) -> str:
    """Formate un ou plusieurs FVGs en affichage compact pour le tableau live.

    Ex: "bear-M5", "bear-M15+M5+M3+M1", ou "" (si aucun FVG).
    """
    if not fvg_entries:
        return ""
    d0 = fvg_entries[0]
    direction = d0.get("direction", "?") if isinstance(d0, dict) else getattr(d0, "direction", "?")
    prefix = "bear" if direction == "bearish" else "bull"

    seen_tfs = []
    for d in fvg_entries:
        tf = d.get("timeframe", "?") if isinstance(d, dict) else getattr(d, "timeframe", "?")
        if tf not in seen_tfs:
            seen_tfs.append(tf)
    tfs_str = "+".join(seen_tfs)
    return f"{prefix}-{tfs_str}"
