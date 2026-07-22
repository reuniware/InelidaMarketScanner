#!/usr/bin/env python
"""
PureICT / scan_asian_session.py

Scanne TOUS les actifs disponibles dans MetaTrader 5 et calcule les niveaux
de la session asiatique (High/Low/Mid) en fuseau Paris (00:00-08:00).

Inspire du Pine Script "AsiaSessionHighLowMidLines" pour TradingView (
https://www.tradingview.com/script/AsiaSessionHighLowMidLines/ ).

Comportement (identique au Pine Script) :
  +-------------------------- Pendant la session asiatique --------------------------+
  |  * Le AH/AL est DYNAMIQUE : il evolue a chaque bougie   |
  |  * La session precedente est FIGEE (gelee)              |
  +-------------------------------------------------------------------------------+
  +- Apres la session ------------------------------------------------------------+
  |  * Le AH/AL de la session terminee devient FIGE         |
  |  * La session d'hier est la "precedente"                |
  |  * Les sweeps post-session sont detectes                |
  +-------------------------------------------------------------------------------+

Fonctionnalites :
  * Session asiatique configurable (defaut : Paris 00:00-08:00)
  * Session courante (dynamique si en cours, figee si terminee)
  * Session precedente (toujours figee - comme var lines du Pine)
  * Detection des sweeps AH/AL post-session (definition ICT)
  * Scan de TOUS les symboles disponibles chez le broker
  * Affichage tableau + export CSV optionnel
  * Fuseau horaire automatique (ete/hiver)

Usage :
  python PureICT/scan_asian_session.py
  python PureICT/scan_asian_session.py --date 2026-07-21
  python PureICT/scan_asian_session.py --max-symbols 30
  python PureICT/scan_asian_session.py --export niveaux_asian.csv
  python PureICT/scan_asian_session.py --verbose
"""

import argparse
import csv
import fnmatch
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, asdict, fields
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

# Ajouter la racine du projet au path pour importer src.*
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# Forcer l'encodage UTF-8 pour les caracteres unicode (box-drawing, emoji)
# Necessaire sur Windows ou le terminal utilise cp1252 par defaut
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except AttributeError:
    pass  # Python < 3.7 ou environnement sans reconfigure

try:
    import MetaTrader5 as mt5
except ImportError:
    print("\n  !! MetaTrader5 n'est pas installe.")
    print("     Installe-le avec : pip install MetaTrader5")
    print("     Puis verifie que MT5 est lance et connecte.\n")
    sys.exit(1)

from src.mt5_connector import MT5Connector
from src.time_utils import now_datetime
from src.config import _dst_eu_summer, format_epoch as _fmt_epoch_tz

logger = logging.getLogger("PureICT.AsianSession")


# ===============================================================================
# CONFIGURATION
# ===============================================================================

# Session asiatique par defaut : Paris 00:00-08:00
DEFAULT_START_HOUR = 0
DEFAULT_END_HOUR = 8
DEFAULT_TIMEZONE = "PARIS"

# Timeframes disponibles
TIMEFRAMES = {
    "M1":  mt5.TIMEFRAME_M1,
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1":  mt5.TIMEFRAME_H1,
}

# Timeframe par defaut (M15 : bon compromis precision / vitesse)
DEFAULT_TF = "M15"

# Bougies a charger selon le timeframe (couvre ~4 jours)
LOOKBACK_BARS = {
    "M1":  6000,   # ~4 jours en M1
    "M5":  1200,   # ~4 jours en M5
    "M15": 400,    # ~4 jours en M15
    "M30": 200,    # ~4 jours en M30
    "H1":  100,    # ~4 jours en H1
}

# Timeframes pour la detection FVG
FVG_TIMEFRAMES = {
    "M1":  mt5.TIMEFRAME_M1,
    "M3":  mt5.TIMEFRAME_M3,
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
}

# Nombre de barres a charger pour la detection FVG (couvre ~24h pour M1, ~6h pour les autres)
FVG_LOOKBACK = {
    "M1":  1440,  # ~24h en M1 (assez pour capturer les reclaims lointains)
    "M3":  480,   # ~24h en M3
    "M5":  288,   # ~24h en M5
    "M15": 96,    # ~24h en M15
}

# Taille minimum du FVG en %%
DEFAULT_FVG_MIN_PCT = 0.02


# ===============================================================================
# MAX LOTS CALCULATION (inspire du script MQL5 MaxMargin_Limit)
# ===============================================================================

def calc_max_lots(symbol: str, price: float) -> Tuple[Optional[float], Optional[float], str]:
    """Calcule le nombre de lots maximum negociable pour un symbole.

    Logique (inspiree du script MQL5 MaxMargin_Limit) :
      1. Recuperer la marge libre du compte (ACCOUNT_MARGIN_FREE)
      2. Demander au broker la marge requise pour 1 lot standard
         (mt5.order_calc_margin = equivalent de OrderCalcMargin)
      3. max_lots = free_margin / margin_for_1_lot
      4. Arrondir au volume_step inferieur (ne pas depasser la marge)
      5. Plafonner a SYMBOL_VOLUME_MAX

    Args:
        symbol: Symbole MT5 (ex: EURUSD, XAUUSD).
        price: Prix d'entree (ASK pour BUY, BID pour SELL).

    Returns:
        (max_lots, margin_per_lot, currency)
        - max_lots: nombre de lots max (arrondi au step), ou None si erreur
        - margin_per_lot: marge requise pour 1 lot, ou None si erreur
        - currency: devise du compte ("USD", "EUR", etc.)
    """
    try:
        # 1. Marge libre du compte
        acc = mt5.account_info()
        if acc is None:
            return None, None, ""
        free_margin = acc.margin_free
        currency = acc.currency or ""

        if free_margin <= 0:
            return 0.0, None, currency

        # 2. Marge requise pour 1 lot (ORDER_TYPE_BUY est un bon proxy)
        margin_for_1 = mt5.order_calc_margin(
            mt5.ORDER_TYPE_BUY, symbol, 1.0, price
        )
        if margin_for_1 is None or margin_for_1 <= 0:
            return None, None, currency

        # 3. Calcul brut
        max_lots_raw = free_margin / margin_for_1

        # 4. Arrondir au volume_step du symbole (vers le bas pour securite)
        info = mt5.symbol_info(symbol)
        if info is None:
            return None, margin_for_1, currency

        step = info.volume_step or 0.01
        max_lots = (int(max_lots_raw / step)) * step

        # 5. Plafonner a la taille max autorisee par le broker
        limit_max = info.volume_max
        if max_lots > limit_max:
            max_lots = limit_max

        # Securite : pas moins que le volume_min
        if max_lots < info.volume_min:
            max_lots = info.volume_min

        return round(max_lots, 2), round(margin_for_1, 2), currency

    except Exception as e:
        logger.debug("calc_max_lots(%s) a echoue: %s", symbol, e)
        return None, None, ""


# ===============================================================================
# DATACLASSES
# ===============================================================================

@dataclass
class AsianLevels:
    """Niveaux de la session asiatique pour un symbole (comme le Pine Script).

    Champs ajoutes vs Pine Script original :
      - open_first_bar / close_last_bar : prix d'ouverture/fermeture de la session
      - high_at_epoch / low_at_epoch    : timestamp exact du AH et du AL
      - ah_swept / al_swept             : sweep ICT post-session
      - fib_up_*/fib_dn_*               : extensions Fibonacci (1.618-5.618)
      - ote_bear/bull_high/low          : zone OTE retracement 0.618-0.382
      - in_ote_bear / in_ote_bull       : prix dans la zone OTE ?
    """
    symbol: str
    session_date: str               # Date Paris de la session (YYYY-MM-DD)
    session_label: str              # "Current" / "Completed"
    is_live: bool                   # True si session en cours (AH/AL evolutifs)
    open_first_bar: float           # Prix d'ouverture de la 1ere bougie Asian
    close_last_bar: float           # Prix de fermeture de la derniere bougie
    asian_high: float               # Plus haut de la session (refHigh)
    asian_low: float                # Plus bas de la session (refLow)
    high_at_epoch: float            # Timestamp UTC de la bougie du AH
    low_at_epoch: float             # Timestamp UTC de la bougie du AL
    midpoint: float                 # (AH + AL) / 2  (midline)
    range_pips: float               # AH - AL
    range_pct: float                # (AH - AL) / Mid * 100
    bars_in_session: int            # Nombre de barres utilisees
    ah_swept: bool                  # Asian High sweepe ? (meche + rejet)
    al_swept: bool                  # Asian Low sweepe ?
    ah_swept_at: Optional[str]      # Heure UTC du sweep AH (HH:MM:SS)
    al_swept_at: Optional[str]      # Heure UTC du sweep AL
    current_price: float            # Prix actuel bid
    # FVG detection (AH/AL reclaim)
    fvg_ah: Optional[list] = None  # Liste des FVGs baissiers pres AH (price a depasse AH puis est revenu dessous)
    fvg_al: Optional[list] = None  # Liste des FVGs haussiers pres AL (price a depasse AL puis est revenu dessus)
    # Max lots calcules depuis la marge libre du compte
    max_lots: Optional[float] = None  # Nombre de lots max (base sur marge libre)
    account_currency: str = ""        # Devise du compte (ex: USD, EUR)
    margin_per_lot: Optional[float] = None  # Marge requise pour 1 lot standard
    # Extensions Fibonacci (calculees depuis le midpoint)
    fib_up_1618: float = 0.0        # Mid + dist*1.618
    fib_up_2618: float = 0.0        # Mid + dist*2.618
    fib_up_3618: float = 0.0        # Mid + dist*3.618
    fib_up_4618: float = 0.0        # Mid + dist*4.618
    fib_up_5618: float = 0.0        # Mid + dist*5.618
    fib_dn_1618: float = 0.0        # Mid - dist*1.618
    fib_dn_2618: float = 0.0        # Mid - dist*2.618
    fib_dn_3618: float = 0.0        # Mid - dist*3.618
    fib_dn_4618: float = 0.0        # Mid - dist*4.618
    fib_dn_5618: float = 0.0        # Mid - dist*5.618
    # OTE (Optimal Trade Entry) — retracement 0.618-0.382 du range
    ote_bear_high: float = 0.0      # AH - 0.382*range (haut zone OTE bearish)
    ote_bear_low: float = 0.0       # AH - 0.618*range (bas zone OTE bearish)
    ote_bull_high: float = 0.0      # AL + 0.618*range (haut zone OTE bullish)
    ote_bull_low: float = 0.0       # AL + 0.382*range (bas zone OTE bullish)
    in_ote_bear: bool = False       # Prix dans la zone OTE bearish ?
    in_ote_bull: bool = False       # Prix dans la zone OTE bullish ?


@dataclass
class PreviousAsianLevels:
    """Session asiatique PRECEDENTE (figee, comme les lignes var du Pine Script)."""
    symbol: str
    session_date: str
    asian_high: float
    asian_low: float
    midpoint: float
    range_pips: float
    range_pct: float
    bars_in_session: int


@dataclass
class FvgInfo:
    """Fair Value Gap detecte pres de l'AH ou de l'AL (reclaim ICT).

    Quand le prix DEPASSE l'AH (peu importe la duree) puis REVIENT
    en dessous, un FVG baissier peut se former. Quand le prix DEPASSE
    l'AL puis REVIENT au-dessus, un FVG haussier peut se former.

    !!! Il n'est pas necessaire que ce soit un sweep rapide !
    Le prix peut etre reste des heures au-dessus/sous.
    """
    timeframe: str          # M1/M3/M5/M15
    direction: str          # "bearish" (pres AH) ou "bullish" (pres AL)
    zone_top: float         # Haut de la zone FVG
    zone_bottom: float      # Bas de la zone FVG
    gap_pct: float          # Taille du gap en %%
    gap_size: float         # Taille du gap en pips/points
    level_type: str         # "AH" ou "AL"
    level_price: float      # Valeur du niveau concerne


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
    """Retourne le decalage UTC pour un fuseau.

    Modes supportes : PARIS (ete=+2, hiver=+1), BROKER (ete=+3, hiver=+2), UTC (0).
    """
    m = mode.upper()
    dst = _dst_eu_summer()
    if m == "UTC":
        return 0
    if m == "BROKER":
        return 3 if dst else 2
    # PARIS ou defaut
    return 2 if dst else 1


def _session_true_utc_end(
    session_date: str,
    end_hour: int = DEFAULT_END_HOUR,
    tz_mode: str = DEFAULT_TIMEZONE,
) -> datetime:
    """Retourne la VRAIE fin de session en UTC (pour is_live et affichage).

    Contrairement a _session_epochs (compatibilite MT5), cette fonction fait
    une vraie conversion de fuseau horaire.
    """
    offset = _tz_offset(tz_mode)
    local_tz = timezone(timedelta(hours=offset))
    local_dt = datetime.strptime(session_date, "%Y-%m-%d").replace(tzinfo=local_tz)
    return local_dt.replace(hour=end_hour, minute=0, second=0).astimezone(timezone.utc)


def _session_true_utc_start(
    session_date: str,
    start_hour: int = DEFAULT_START_HOUR,
    tz_mode: str = DEFAULT_TIMEZONE,
) -> datetime:
    """Retourne la VRAIE date/heure de debut de session en UTC.

    Calque exact de _session_true_utc_end mais pour le debut.
    """
    offset = _tz_offset(tz_mode)
    local_tz = timezone(timedelta(hours=offset))
    local_dt = datetime.strptime(session_date, "%Y-%m-%d").replace(tzinfo=local_tz)
    return local_dt.replace(hour=start_hour, minute=0, second=0).astimezone(timezone.utc)


def is_in_asian_session(
    start_hour: int = DEFAULT_START_HOUR,
    end_hour: int = DEFAULT_END_HOUR,
    tz_mode: str = DEFAULT_TIMEZONE,
) -> bool:
    """Verifie si maintenant est dans la fenetre de session asiatique.

    Utilise la comparaison timestamp (comme MQL5) pour gerer les sessions overnight.
    """
    offset = _tz_offset(tz_mode)
    local_now = now_datetime() + timedelta(hours=offset)
    session_start_today = local_now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    session_end_today = local_now.replace(hour=end_hour, minute=0, second=0, microsecond=0)
    if start_hour < end_hour:
        # Session normale (ex: 0->8)
        return session_start_today <= local_now < session_end_today
    else:
        # Session overnight (ex: 22->6) : apres start OU avant end
        return local_now >= session_start_today or local_now < session_end_today


def _smart_session_date(
    end_hour: int = DEFAULT_END_HOUR,
    tz_mode: str = DEFAULT_TIMEZONE,
) -> str:
    """Selection intelligente de la session (logique MQL5 - comparaison timestamp).

    +- Regle (identique a l'indicateur MT5) ----------------------------------------+
    | Si on est AVANT la fin de session aujourd'hui               |
    | (now < session_end_today) -> session d'HIER (figee).        |
    | Si on est APRES -> session d'AUJOURD'HUI (terminee).        |
    +------------------------------------------------------------------------------+

    Exemple avec Paris 00:00-08:00 :
      - A 03:00 Paris -> session d'hier (celle d'aujourd'hui est en cours)
      - A 11:00 Paris -> session d'aujourd'hui (terminee a 08:00)

    Args:
        end_hour: Heure de fin de session (fuseau tz_mode).
        tz_mode: PARIS, BROKER ou UTC.

    Returns:
        Date de la session au format YYYY-MM-DD (fuseau tz_mode).

    Note:
        Comme l'indicateur MQL5 original, cette fonction suppose que
        start_hour < end_hour (session dans la meme journee civile).
        Les sessions overnight (ex: 22->6) ne sont pas supportees ici.
    """
    offset = _tz_offset(tz_mode)
    local_now = now_datetime() + timedelta(hours=offset)
    # Construire le timestamp de fin de session aujourd'hui (comparaison MQL5)
    session_end_today = local_now.replace(hour=end_hour, minute=0, second=0, microsecond=0)
    if local_now < session_end_today:
        # Encore avant la fin de session -> montrer celle d'hier
        local_now -= timedelta(days=1)
    return local_now.strftime("%Y-%m-%d")


def format_epoch(epoch: float) -> str:
    """Formate un epoch UTC en HH:MM:SS."""
    return time.strftime("%H:%M:%S", time.gmtime(epoch))


def fmt_price(p: float) -> str:
    """Formatte un prix avec precision adaptative selon sa magnitude."""
    if p is None:
        return "-"
    if p >= 1000.0:
        return f"{p:.2f}"
    if p >= 10.0:
        return f"{p:.4f}"
    return f"{p:.5f}"


def _fmt_fvg_compact(fvg_entries: Optional[list]) -> str:
    """Formate un ou plusieurs FVGs en affichage compact pour le tableau live.

    - 1 FVG : "bear-M5" ou "bull-M15" (prefixe direction + timeframe)
    - 2+ FVGs : "M15+M5" (timeframes concatenes, direction implicite = colonne)
    - None / [] : ""

    Ex: "bear-M5" pour 1 bearish M5, "M15+M5" pour 2 bearish sur M15 et M5.
    """
    if not fvg_entries:
        return ""
    # Determiner la direction depuis le premier element
    d0 = fvg_entries[0]
    direction = d0.get("direction", "?") if isinstance(d0, dict) else getattr(d0, "direction", "?")
    prefix = "bear" if direction == "bearish" else "bull"

    # Collecter les timeframes dans l'ordre du scan (M15->M5->M3->M1)
    seen_tfs = []
    for d in fvg_entries:
        tf = d.get("timeframe", "?") if isinstance(d, dict) else getattr(d, "timeframe", "?")
        if tf not in seen_tfs:
            seen_tfs.append(tf)
    tfs_str = "+".join(seen_tfs)
    # Toujours inclure le prefixe pour uniformite : bear-M15, bear-M15+M5+M3+M1, etc.
    return f"{prefix}-{tfs_str}"


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
# FVG DETECTION (AH/AL RECLAIM)
# ===============================================================================

def find_fvg_at(bars: List[dict], idx: int, direction: str, fvg_min_pct: float) -> Optional[dict]:
    """Verifie si un FVG existe a l'index idx (3e bougie du pattern).

    Definition ICT :
      - Bullish FVG : high[i-2] < low[i]  (gap up, C1 high < C3 low)
      - Bearish FVG : low[i-2] > high[i]  (gap down, C1 low > C3 high)

    Args:
        bars: Liste de dicts avec 'high', 'low', 'time'.
        idx: Index de la 3e bougie (C3 du pattern 3-candles).
        direction: "bull" pour bullish, "bear" pour bearish.
        fvg_min_pct: Taille minimum du gap en %%.

    Returns:
        Dict FVG ou None.
    """
    if idx < 2:
        return None
    c1 = bars[idx - 2]
    c3 = bars[idx]

    if direction == "bull":
        if c1["high"] >= c3["low"]:
            return None  # pas de gap
        gap_top, gap_bottom = c3["low"], c1["high"]
    else:
        if c1["low"] <= c3["high"]:
            return None  # pas de gap
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
    """Distance en %% entre la zone FVG et un niveau (AH/AL).

    Retourne la distance minimum entre le niveau et la zone.
    Si le niveau est dans la zone, distance = 0.
    """
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

    !!! IMPORTANT : il n'est PAS necessaire que le depassement de l'AH/AL
    soit un "sweep" rapide (meche + close). Le prix peut etre reste des
    heures au-dessus de l'AH ou sous l'AL. La seule condition est :
      - Le prix a DEPASSE l'AH a un moment donne (une ou plusieurs barres)
        ET le close actuel est REVENU en dessous de l'AH
        -> on cherche un FVG baissier pres de l'AH
      - Le prix a DEPASSE l'AL a un moment donne
        ET le close actuel est REVENU au-dessus de l'AL
        -> on cherche un FVG haussier pres de l'AL

    Les timeframes scannees : M15 -> M5 -> M3 -> M1 (du plus grand au plus petit).
    Collecte TOUS les FVGs trouves sur tous les timeframes (pas seulement le premier).

    Args:
        symbol: Symbole MT5.
        asian_high: Asian High de la session.
        asian_low: Asian Low de la session.
        end_epoch_utc: Fin de la session asiatique (epoch UTC).
        fvg_min_pct: Taille minimum du FVG en %%.

    Returns:
        (fvg_ah_list, fvg_al_list) - listes de FvgInfo (vides si aucun FVG trouve).
    """
    fvg_ah_list: List[FvgInfo] = []
    fvg_al_list: List[FvgInfo] = []
    # Suivi des timeframes deja traites pour eviter les doublons
    ah_tfs_done: set = set()
    al_tfs_done: set = set()

    # Offset broker en secondes (cacule une fois pour tous les timeframes)
    _broker_offset_sec = _tz_offset("BROKER") * 3600

    # Parcourir les timeframes du plus grand au plus petit
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

        # Convertir les timestamps MT5 (broker) en vrai UTC
        for b in bars:
            b["time_utc"] = b["time"] - _broker_offset_sec

        # Barres post-session (filtre UTC)
        post_bars = [b for b in bars if b["time_utc"] >= end_epoch_utc]
        if len(post_bars) < 3:
            continue

        # Verifier si price a depasse AH ou AL (peu importe depuis combien de temps)
        # any() = True si UNE SEULE barre a depasse le niveau, meme 200 barres plus tot
        price_above_ah = any(b["high"] > asian_high for b in post_bars)
        price_below_al = any(b["low"] < asian_low for b in post_bars)

        # Verifier si le close actuel est revenu de l'autre cote du niveau
        # (peu importe depuis combien de temps le prix etait au-dessus/sous)
        last_close = post_bars[-1]["close"]
        back_below_ah = price_above_ah and last_close < asian_high
        back_above_al = price_below_al and last_close > asian_low

        if not back_below_ah and not back_above_al:
            continue

        # Scanner les barres pour trouver des FVGs
        # On garde au maximum 1 FVG par timeframe (le premier trouve le plus proche du prix)
        found_ah_on_tf = False
        found_al_on_tf = False
        for i in range(len(post_bars) - 1, 1, -1):  # de la fin vers le debut
            if back_below_ah and not found_ah_on_tf and tf_name not in ah_tfs_done:
                fvg = find_fvg_at(post_bars, i, "bear", fvg_min_pct)
                if fvg is not None:
                    dist = _level_distance(fvg["zone_top"], fvg["zone_bottom"], asian_high)
                    if dist < 0.5:  # dans les 0.5% de l'AH
                        fvg_ah_list.append(FvgInfo(
                            timeframe=tf_name,
                            direction="bearish",
                            zone_top=fvg["zone_top"],
                            zone_bottom=fvg["zone_bottom"],
                            gap_pct=fvg["gap_pct"],
                            gap_size=fvg["gap_size"],
                            level_type="AH",
                            level_price=asian_high,
                        ))
                        found_ah_on_tf = True
                        ah_tfs_done.add(tf_name)

            if back_above_al and not found_al_on_tf and tf_name not in al_tfs_done:
                fvg = find_fvg_at(post_bars, i, "bull", fvg_min_pct)
                if fvg is not None:
                    dist = _level_distance(fvg["zone_top"], fvg["zone_bottom"], asian_low)
                    if dist < 0.5:
                        fvg_al_list.append(FvgInfo(
                            timeframe=tf_name,
                            direction="bullish",
                            zone_top=fvg["zone_top"],
                            zone_bottom=fvg["zone_bottom"],
                            gap_pct=fvg["gap_pct"],
                            gap_size=fvg["gap_size"],
                            level_type="AL",
                            level_price=asian_low,
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

    Args:
        symbol: Symbole MT5 (ex: EURUSD, US30.cash, XAUUSD).
        session_date_paris: Date de la session (YYYY-MM-DD, fuseau tz_mode).
        start_hour: Heure debut session (fuseau tz_mode).
        end_hour: Heure fin session (fuseau tz_mode).
        timeframe: M1/M5/M15/M30/H1.
        tz_mode: PARIS, BROKER ou UTC.
        _mt5c: Connecteur MT5 partage.
        fvg_mode: Activer la detection des FVGs pres AH/AL.
        fvg_min_pct: Taille minimum du FVG en %%.

    Returns:
        (AsianLevels, None) si succes, (None, raison_erreur) si echec.
        Les raisons possibles :
          "MT5 non connecte"
          "select_symbol a echoue"
          "Pas de donnees"
          "Aucune barre dans la fenetre session"
    """
    if session_date_paris is None:
        session_date_paris = paris_date_str()

    mt5c = _mt5c if _mt5c is not None else MT5Connector()
    if not mt5c.ensure_connected():
        return None, "MT5 non connecte"
    if not mt5c.select_symbol(symbol):
        return None, "select_symbol a echoue"


    # -- Vraies bornes UTC du debut et fin de session --
    _broker_offset_sec = _tz_offset("BROKER") * 3600
    session_start_utc = _session_true_utc_start(session_date_paris, start_hour, tz_mode)
    session_end_utc = _session_true_utc_end(session_date_paris, end_hour, tz_mode)

    # -- Choix du timeframe --
    tf = TIMEFRAMES.get(timeframe.upper())
    if tf is None:
        logger.error("Timeframe inconnu : %s (disponibles: %s)",
                     timeframe, ', '.join(TIMEFRAMES.keys()))
        return None, "Timeframe invalide"
    lookback = LOOKBACK_BARS.get(timeframe.upper(), 400)

    # -- Bougies --
    rates_raw = mt5.copy_rates_from_pos(symbol, tf, 0, lookback)
    if rates_raw is None or len(rates_raw) == 0:
        return None, "Pas de donnees"

    bars = bars_to_dicts(rates_raw)
    bars.sort(key=lambda b: b["time"])

    # -- Convertir les timestamps MT5 (broker) en vrai UTC --
    for b in bars:
        b["time_utc"] = b["time"] - _broker_offset_sec

    # -- Barres de la session asiatique (filtre UTC) --
    session_start_epoch = session_start_utc.timestamp()
    session_end_epoch = session_end_utc.timestamp()
    session_bars = [b for b in bars if session_start_epoch <= b["time_utc"] < session_end_epoch]
    if not session_bars:
        return None, "Aucune barre dans la fenetre session"

    # Tracker le AH/AL avec leurs timestamps exacts
    asian_high = -float('inf')
    asian_low = float('inf')
    high_at_epoch = 0.0
    low_at_epoch = 0.0

    for b in session_bars:
        if b["high"] > asian_high:
            asian_high = b["high"]
            high_at_epoch = b["time_utc"]  # deja en UTC
        if b["low"] < asian_low:
            asian_low = b["low"]
            low_at_epoch = b["time_utc"]  # deja en UTC

    midpoint = (asian_high + asian_low) / 2.0
    range_pips = asian_high - asian_low
    range_pct = (range_pips / midpoint * 100.0) if midpoint > 0 else 0.0

    # -- Extensions Fibonacci --
    # dist = moitie du range (midpoint -> AH ou AL)
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
        # Session plate (AH==AL) -> toutes les extensions = midpoint
        for lvl in fib_levels:
            key = int(lvl * 1000)
            fib_up_vals[f"fib_up_{key}"] = midpoint
            fib_dn_vals[f"fib_dn_{key}"] = midpoint

    # Ouverture de la 1ere bougie, fermeture de la derniere
    open_first_bar = session_bars[0]["open"]
    close_last_bar = session_bars[-1]["close"]

    # -- Session live ? (comparaison UTC via now_datetime NTP-synced) --
    is_live = now_datetime() < session_end_utc
    if is_live:
        # Si session en cours, le close est le prix actuel
        tick = mt5.symbol_info_tick(symbol)
        close_last_bar = float(tick.bid) if tick else close_last_bar

    # -- Barres post-session pour sweeps (filtre UTC) --
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

    # -- Prix actuel --
    tick = mt5.symbol_info_tick(symbol)
    current_price = float(tick.bid) if tick else (bars[-1]["close"] if bars else 0.0)

    # -- Zone OTE (Optimal Trade Entry) : retracement 0.618-0.382 du range --
    ote_bear_high = 0.0  # zone bearish : AH - 0.382*range
    ote_bear_low  = 0.0  #                   AH - 0.618*range
    ote_bull_high = 0.0  # zone bullish : AL + 0.618*range
    ote_bull_low  = 0.0  #                  AL + 0.382*range
    in_ote_bear = False
    in_ote_bull = False
    if range_pips > 0:
        # Bearish OTE (apres sweep AH) : retracement depuis AH vers AL
        ote_bear_high = asian_high - 0.382 * range_pips  # 38.2% en dessous AH
        ote_bear_low  = asian_high - 0.618 * range_pips  # 61.8% en dessous AH
        # Bullish OTE (apres sweep AL) : retracement depuis AL vers AH
        ote_bull_high = asian_low  + 0.618 * range_pips  # 61.8% au-dessus AL
        ote_bull_low  = asian_low  + 0.382 * range_pips  # 38.2% au-dessus AL
        # Detection temps reel : le prix actuel est-il dans une zone OTE ?
        # (on utilise le current_price deja recupere au-dessus)
        in_ote_bear = ote_bear_low <= current_price <= ote_bear_high
        in_ote_bull = ote_bull_low <= current_price <= ote_bull_high

    # -- Detection FVG pres AH/AL (si active) --
    fvg_ah_list: List[FvgInfo] = []
    fvg_al_list: List[FvgInfo] = []
    if fvg_mode:
        try:
            fvg_ah_list, fvg_al_list = scan_reclaim_fvgs(
                symbol, asian_high, asian_low, session_end_epoch, fvg_min_pct,
            )
        except Exception as e:
            logger.debug("FVG scan failed for %s: %s", symbol, e)

    # -- Calcul du nombre de lots max (marge libre) --
    max_lots_val, margin_per_lot_val, acc_currency = calc_max_lots(symbol, current_price)

    label = "LIVE" if is_live else "OK"

    return AsianLevels(
        symbol=symbol,
        session_date=session_date_paris,
        session_label=label,
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


def scan_previous_session(
    symbol: str,
    session_date_paris: Optional[str] = None,
    start_hour: int = DEFAULT_START_HOUR,
    end_hour: int = DEFAULT_END_HOUR,
    timeframe: str = DEFAULT_TF,
    tz_mode: str = DEFAULT_TIMEZONE,
    _mt5c: Optional[MT5Connector] = None,
) -> Optional[PreviousAsianLevels]:
    """Calcule les niveaux de la session asiatique PRECEDENTE.

    Dans le Pine Script, les lignes var persistent apres la session :
      timeIsAllowed and not timeIsAllowed[1] -> newSession -> figer l'ancienne

    Ici on decale simplement d'un jour vers le passe.

    Args:
        symbol: Symbole MT5.
        session_date_paris: Date de la session courante.
        start_hour: Heure de debut de session (Paris).
        end_hour: Heure de fin de session (Paris).
        _mt5c: Connecteur partage.

    Returns:
        PreviousAsianLevels ou None.
    """
    if session_date_paris is None:
        session_date_paris = paris_date_str()

    # Decaler d'un jour vers le passe
    dt = datetime.strptime(session_date_paris, "%Y-%m-%d") - timedelta(days=1)
    prev_date = dt.strftime("%Y-%m-%d")

    r, err = scan_symbol(symbol, prev_date, start_hour, end_hour, timeframe, tz_mode, _mt5c=_mt5c)
    if r is None:
        return None

    return PreviousAsianLevels(
        symbol=symbol,
        session_date=prev_date,
        asian_high=r.asian_high,
        asian_low=r.asian_low,
        midpoint=r.midpoint,
        range_pips=r.range_pips,
        range_pct=r.range_pct,
        bars_in_session=r.bars_in_session,
    )


# ===============================================================================
# FORCE SELECT (pre-activation massive des symboles)
# ===============================================================================

def _force_select_all(symbols: List[str], batch_size: int = 20) -> Tuple[int, int]:
    """Tente d'activer tous les symboles dans Market Watch AVANT le scan.

    Certains brokers (FTMO, etc.) ne laissent pas `copy_rates_from_pos`
    acceder aux donnees des symboles hors Market Watch. Cette fonction
    pre-active chaque symbole un par un pour contourner cette limitation.

    Args:
        symbols: Liste des symboles a activer.
        batch_size: Nombre d'activations entre chaque progression + pause.

    Returns:
        (ok_count, fail_count) - nombre de symboles actives vs echoues.
    """
    if not symbols:
        print(f"  Pre-activation : aucun symbole a traiter.")
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
                ok_count += 1  # deja visible
                continue
            # Tenter d'activer
            if mt5.symbol_select(sym, True):
                ok_count += 1
            else:
                fail_count += 1
        except Exception:
            fail_count += 1

        # Progression toutes les batch_size activations
        if (i + 1) % batch_size == 0 or i == total - 1:
            print(f"    Progression : {i+1}/{total}  |  OK: {ok_count}  FAIL: {fail_count}")
            # Pause pour ne pas saturer MT5 avec trop de symbol_select() rapides
            if i + 1 < total:
                time.sleep(0.1)

    print(f"  Pre-activation terminee : {ok_count} actifs, {fail_count} echoues")
    return ok_count, fail_count


# ===============================================================================
# SCAN DE TOUS LES SYMBOLES
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

    Collecte aussi la liste des symboles exclus et la raison.

    Args:
        session_date_paris: Date Paris de la session.
        max_symbols: Limite de symboles (None = tous).
        include_previous: Inclure la session precedente.
        market_watch_only: Market Watch uniquement.
        start_hour: Heure debut session.
        end_hour: Heure fin session.
        symbol_filters: Liste de motifs fnmatch (ex: ['EUR*', '*JPY']).
        force_select: Pre-active tous les symboles dans Market Watch avant scan.
        fvg_mode: Activer la detection des FVGs pres AH/AL.
        fvg_min_pct: Taille minimum du FVG en %%.

    Returns:
        (current_results, previous_results, excluded_symbols)
        excluded_symbols = [(symbole, raison), ...] pour ceux qui ont echoue.
    """
    mt5c = MT5Connector()
    if not mt5c.ensure_connected():
        return [], [], []

    # Symboles : Market Watch ou tous
    if market_watch_only:
        all_syms = mt5c.list_market_watch_symbols()
        source = "Market Watch"
    else:
        all_syms = mt5c.list_all_symbols()
        source = "broker complet"

    if not all_syms:
        logger.error("Aucun symbole trouve chez le broker.")
        return [], [], []

    # Appliquer le filtre --symbol (motifs fnmatch)
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

    # Sauvegarder les symboles deja visibles (pour ne pas les deselectionner)
    originally_visible: set = set()

    # Pre-activation massive des symboles (si demande)
    if force_select and not market_watch_only:
        # Capturer les symboles deja visibles avant la pre-activation
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
            # Nettoyer le Market Watch : ne deselectionner QUE les symboles
            # qui n'y etaient PAS avant --force-select
            try:
                if sym not in originally_visible:
                    mt5.symbol_select(sym, False)
            except Exception:
                pass

    return current_results, previous_results, excluded


# ===============================================================================
# AFFICHAGE
# ===============================================================================

def display_results(results: List[AsianLevels],
                    previous: List[PreviousAsianLevels] = None,
                    tz_mode: str = DEFAULT_TIMEZONE,
                    is_previous_session: bool = False,
                    show_ote: bool = False):
    """Affiche un tableau unique des AH/AL avec timestamps 3tz."""
    if not results:
        print("  Aucun resultat a afficher.")
        return

    # Tri alphabetique par symbole
    results.sort(key=lambda r: r.symbol)

    n_total = len(results)
    n_live = sum(1 for r in results if r.is_live)

    # Heure locale dans le fuseau de la session
    offset = _tz_offset(tz_mode)
    local_now = now_datetime() + timedelta(hours=offset)

    # Label clair : session d'aujourd'hui vs session precedente
    if is_previous_session:
        session_kind = "PRECEDENTE (hier, figee)"
    else:
        session_kind = "du jour (terminee)"

    print()
    print(f"  ##### PureICT - Session Asiatique {session_kind} #####")
    print(f"  Date  : {results[0].session_date}")
    print(f"  Heure : {local_now.strftime('%H:%M:%S')} {tz_mode}")
    print(f"  Symboles : {n_total}  |  Session en cours : {n_live}")
    print()

    # Verifier si on a des infos de marge (au moins un symbole avec max_lots)
    _has_margin_info = any(r.max_lots is not None for r in results)

    # -- Tableau unique --
    if _has_margin_info:
        sep = "  " + "-" * 165
        print(sep)
        hdr = (f"  {'Actif':<14} {'Open':>12} {'Close':>12} "
               f"{'AH':>12} {'@UTC':>7} {'@Paris':>9} {'@Bkr':>9} "
               f"{'AL':>12} {'@UTC':>7} {'@Paris':>9} {'@Bkr':>9} "
               f"{'LotsMax':>8} {'Marge/Lot':>10}")
    else:
        sep = "  " + "-" * 135
        print(sep)
        hdr = (f"  {'Actif':<14} {'Open':>12} {'Close':>12} "
               f"{'AH':>12} {'@UTC':>7} {'@Paris':>9} {'@Bkr':>9} "
               f"{'AL':>12} {'@UTC':>7} {'@Paris':>9} {'@Bkr':>9} ")
    print(hdr)
    print(sep)

    for r in results:
        ah_utc = _fmt_epoch_tz(r.high_at_epoch, "%H:%M", "UTC")
        ah_paris = _fmt_epoch_tz(r.high_at_epoch, "%H:%M", "PARIS")
        ah_broker = _fmt_epoch_tz(r.high_at_epoch, "%H:%M", "BROKER")
        al_utc = _fmt_epoch_tz(r.low_at_epoch, "%H:%M", "UTC")
        al_paris = _fmt_epoch_tz(r.low_at_epoch, "%H:%M", "PARIS")
        al_broker = _fmt_epoch_tz(r.low_at_epoch, "%H:%M", "BROKER")

        if _has_margin_info:
            max_str = f"{r.max_lots:.2f}" if r.max_lots is not None else "-"
            margin_str = f"{r.margin_per_lot:.0f}" if r.margin_per_lot is not None else "-"
            print(f"  {r.symbol:<14}"
                  f"{fmt_price(r.open_first_bar):>12} "
                  f"{fmt_price(r.close_last_bar):>12} "
                  f"{fmt_price(r.asian_high):>12} "
                  f"{ah_utc.split()[0]:>7} {ah_paris.split()[0]:>9} {ah_broker.split()[0]:>9} "
                  f"{fmt_price(r.asian_low):>12} "
                  f"{al_utc.split()[0]:>7} {al_paris.split()[0]:>9} {al_broker.split()[0]:>9} "
                  f"{max_str:>8} {margin_str:>10}")
        else:
            print(f"  {r.symbol:<14}"
                  f"{fmt_price(r.open_first_bar):>12} "
                  f"{fmt_price(r.close_last_bar):>12} "
                  f"{fmt_price(r.asian_high):>12} "
                  f"{ah_utc.split()[0]:>7} {ah_paris.split()[0]:>9} {ah_broker.split()[0]:>9} "
                  f"{fmt_price(r.asian_low):>12} "
                  f"{al_utc.split()[0]:>7} {al_paris.split()[0]:>9} {al_broker.split()[0]:>9}")

    print(sep)
    print(f"  TZ: UTC / Paris / Broker  |  Live = session en cours (donnees partielles)")
    if _has_margin_info:
        # Afficher la devise du compte a partir du 1er symbole qui en a
        currency = next((r.account_currency for r in results if r.account_currency), "")
        dev_label = f" {currency}" if currency else ""
        print(f"  LotsMax = lots max negociables (marge libre{dev_label})  |  Marge/Lot = marge requise pour 1 lot{dev_label}")

    # -- Extensions Fibonacci --
    _print_fibonacci(results)

    # -- Zone OTE (Optimal Trade Entry) --
    if show_ote:
        _print_ote(results)

    # -- Session precedente (optionnelle) --
    if previous:
        _print_previous(previous)


def _print_fibonacci(results: List[AsianLevels]):
    """Affiche les extensions Fibonacci (1.618-5.618) pour chaque symbole."""
    if not results:
        return

    fib_levels = [1.618, 2.618, 3.618, 4.618, 5.618]
    fib_up_keys = [f"fib_up_{int(l*1000)}" for l in fib_levels]
    fib_dn_keys = [f"fib_dn_{int(l*1000)}" for l in fib_levels]

    print()
    print(f"  -- Extensions Fibonacci (depuis le midpoint) --")
    sep = "  " + "-" * 140
    print(sep)
    # En-tete : symbole + 5 niveaux UP + 5 niveaux DOWN
    hdr = f"  {'Symbole':<14} {'Mid':>12}"
    for lvl in fib_levels:
        hdr += f" {'\u25b2'+str(lvl):>12}"
    hdr += "  |"
    for lvl in fib_levels:
        hdr += f" {'\u25bc'+str(lvl):>12}"
    print(hdr)
    print(sep)

    for r in results:
        row = f"  {r.symbol:<14} {fmt_price(r.midpoint):>12}"
        for key in fib_up_keys:
            val = getattr(r, key, 0.0)
            row += f" {fmt_price(val):>12}"
        row += "  |"
        for key in fib_dn_keys:
            val = getattr(r, key, 0.0)
            row += f" {fmt_price(val):>12}"
        print(row)

    print(sep)


def _print_ote(results: List[AsianLevels]):
    """Affiche la zone OTE (Optimal Trade Entry 0.618-0.382) pour chaque symbole.

    OTE = Fibonacci retracement zone. Apres un sweep AH, le prix retrace souvent
    dans la zone 0.618-0.382 du range (OTE bearish). Apres un sweep AL, le prix
    retrace dans la zone 0.382-0.618 (OTE bullish). Affiche un indicateur quand
    le prix actuel est DANS la zone.
    """
    if not results:
        return

    # Filtrer les symboles avec un range non nul
    ote_results = [r for r in results if r.range_pips > 0]
    if not ote_results:
        return

    print()
    print(f"  -- OTE (Optimal Trade Entry) : retracement 0.618-0.382 --")
    sep = "  " + "-" * 155
    print(sep)
    hdr = (f"  {'Symbole':<14} {'Range':>10} {'AH':>12} {'AL':>12} "
           f"{'OTE Bear H':>12} {'OTE Bear L':>12} {'BZ':>5} "
           f"{'OTE Bull H':>12} {'OTE Bull L':>12} {'BZ':>5} "
           f"{'Now':>12}")
    print(hdr)
    print(sep)

    for r in ote_results:
        range_str = f"{r.range_pips:.1f}" if r.range_pips < 100 else f"{r.range_pips:.0f}"
        # Indicateur "dans la zone" (BZ = Breath Zone, ou "In Zone")
        bear_zone = "[Z]" if r.in_ote_bear else "   "
        bull_zone = "[Z]" if r.in_ote_bull else "   "
        print(f"  {r.symbol:<14}"
              f"{range_str:>10} "
              f"{fmt_price(r.asian_high):>12} {fmt_price(r.asian_low):>12} "
              f"{fmt_price(r.ote_bear_high):>12} {fmt_price(r.ote_bear_low):>12} {bear_zone:>5} "
              f"{fmt_price(r.ote_bull_high):>12} {fmt_price(r.ote_bull_low):>12} {bull_zone:>5} "
              f"{fmt_price(r.current_price):>12}")

    print(sep)
    print(f"  BZ = Prix dans la zone OTE  |  Bear zone = retracement 38.2%-61.8% depuis AH vers AL")
    print(f"                                   Bull zone = retracement 38.2%-61.8% depuis AL vers AH")


def _print_previous(previous: List[PreviousAsianLevels]):
    """Affiche la session precedente (figee)."""
    if not previous:
        return

    # Trier par range decroissant (les plus interessants d'abord)
    previous.sort(key=lambda p: -p.range_pips)

    print()
    print(f"  -- Session PRECEDENTE ({previous[0].session_date}) - Figee --")
    print(f"  (Equivalent des lignes var du Pine Script)")
    sep = "  " + "-" * 80
    print(sep)
    print(f"  {'Symbole':<14} {'AH':>12} {'AL':>12} {'Mid':>12} {'Range':>8}")
    print(sep)

    for p in previous:
        range_str = f"{p.range_pips:.1f}p" if p.range_pips < 100 else f"{p.range_pips:.0f}pt"
        print(f"  {p.symbol:<14} "
              f"{fmt_price(p.asian_high):>12} {fmt_price(p.asian_low):>12} "
              f"{fmt_price(p.midpoint):>12} {range_str:>8}")

    print(sep)


def display_exclusions(excluded: List[Tuple[str, str]], scanned_count: int):
    """Affiche le tableau des symboles exclus avec la raison."""
    if not excluded:
        return

    # Compter par raison
    by_reason: dict = {}
    for sym, reason in excluded:
        by_reason.setdefault(reason, []).append(sym)

    print()
    print(f"  -- Symboles EXCLUS du scan ({len(excluded)} exclus / {scanned_count} retenus) --")
    sep = "  " + "-" * 80
    print(sep)
    print(f"  {'Symbole':<30} {'Raison':<45}")
    print(sep)

    # Grouper par raison pour le confort de lecture
    for reason in sorted(by_reason.keys()):
        syms = sorted(by_reason[reason])
        for i, sym in enumerate(syms):
            if i == 0:
                print(f"  {sym:<30} {reason:<45}")
            else:
                print(f"  {sym:<30} {'':<45}")
        if len(syms) > 1:
            print(f"  {'':>30} ({len(syms)} symboles)")

    print(sep)
    print(f"  Resume : {len(excluded)} exclus / {scanned_count + len(excluded)} total broker")
    print()


def export_csv(results: List[AsianLevels], filepath: str):
    """Exporte les resultats en CSV."""
    if not results:
        print("  Aucun resultat a exporter.")
        return

    fieldnames = [f.name for f in fields(AsianLevels)]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow(asdict(r))

    print(f"\n  \u2705 {len(results)} lignes exportees -> {os.path.abspath(filepath)}")


def export_json(results: List[AsianLevels], filepath: str):
    """Exporte les resultats en JSON.

    Chaque symbole est un objet. Les grands tableaux sont indentes
    pour rester lisibles dans un editeur.
    """
    if not results:
        print("  Aucun resultat a exporter.")
        return

    data = [asdict(r) for r in results]
    # Convertir les champs Optionnel non serialisables
    for d in data:
        for k, v in d.items():
            if isinstance(v, float) and (v != v):  # NaN -> None
                d[k] = None

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\n  \u2705 {len(results)} symboles exportes -> {os.path.abspath(filepath)}")


# ===============================================================================
# MODE LIVE
# ===============================================================================

def live_monitor(results: List[AsianLevels], tz_mode: str, interval: int, show_ote: bool = False):
    """Mode live : rafraichit les prix en continu et affiche distances AH/AL."""
    if not results:
        return

    mt5c = MT5Connector()
    if not mt5c.ensure_connected():
        print("  !! MT5 non connecte - impossible de passer en mode live.")
        return

    offset = _tz_offset(tz_mode)
    n = len(results)

    print(f"\n  === MODE LIVE (Ctrl+C pour quitter) ===")
    print(f"  Symboles : {n}  |  Rafraichissement : {interval}s")
    print(f"  Niveaux fixes (session terminee) - Prix temps reel\n")

    tick_count = 0
    try:
        while True:
            tick_count += 1
            local_now = now_datetime() + timedelta(hours=offset)

            # Effacer l'ecran (compatible Windows et Unix)
            if tick_count > 1:
                os.system('cls' if os.name == 'nt' else 'clear')

            print(f"  PureICT Live - {local_now.strftime('%H:%M:%S')} {tz_mode}  |  tick #{tick_count}")

            # Verifier si un symbole a des FVGs actifs
            _has_fvg_live = any(r.fvg_ah or r.fvg_al for r in results)
            # Verifier si on a des infos de marge (au moins un symbole avec max_lots)
            _has_margin_live = any(r.max_lots is not None for r in results)
            if _has_fvg_live:
                if _has_margin_live:
                    hdr = f"  {'Symbole':<12} {'Prix':>10} {'AH':>10} {'AL':>10} " \
                          f"{'Dist AH':>9} {'Dist AL':>9} {'vs Mid':>8} " \
                          f"{'FVG AH':>26} {'FVG AL':>26} {'AHS':>5} {'ALS':>5} {'Lots':>7}   {'Pos':<6}"
                    sep_len = 165
                else:
                    hdr = f"  {'Symbole':<12} {'Prix':>10} {'AH':>10} {'AL':>10} " \
                          f"{'Dist AH':>9} {'Dist AL':>9} {'vs Mid':>8} " \
                          f"{'FVG AH':>26} {'FVG AL':>26} {'AHS':>5} {'ALS':>5}   {'Pos':<6}"
                    sep_len = 157
            else:
                if _has_margin_live:
                    hdr = f"  {'Symbole':<12} {'Prix':>10} {'AH':>10} {'AL':>10} " \
                          f"{'Dist AH':>9} {'Dist AL':>9} {'vs Mid':>8} " \
                          f"{'AHS':>5} {'ALS':>5} {'Lots':>7}   {'Pos':<6}"
                    sep_len = 107
                else:
                    hdr = f"  {'Symbole':<12} {'Prix':>10} {'AH':>10} {'AL':>10} " \
                          f"{'Dist AH':>9} {'Dist AL':>9} {'vs Mid':>8} " \
                          f"{'AHS':>5} {'ALS':>5}   {'Pos':<6}"
                    sep_len = 99
            print(hdr)
            print(f"  {'-' * sep_len}")

            for r in results:
                tick = mt5.symbol_info_tick(r.symbol)
                if tick is None:
                    continue
                price = float(tick.bid)

                # Distances
                dist_ah_pct = (price - r.asian_high) / r.asian_high * 100.0 if r.asian_high else 0.0
                dist_al_pct = (price - r.asian_low) / r.asian_low * 100.0 if r.asian_low else 0.0
                vs_mid = (price - r.midpoint) / r.midpoint * 100.0 if r.midpoint else 0.0

                # Direction visuelle (vs_mid utilise >/<, pas de + explicite)
                mid_sign = ">" if vs_mid > 0 else ("<" if vs_mid < 0 else "=")

                # Sweeps individuels AH/AL
                ah_swept_str = "AH" if r.ah_swept else "-"
                al_swept_str = "AL" if r.al_swept else "-"

                # Couleur selon position vs AH/AL
                if price > r.asian_high:
                    marker = "ABOVE "
                elif price < r.asian_low:
                    marker = "BELOW "
                else:
                    marker = "IN    "

                # Indicateur OTE (recalcule en live a partir des niveaux stockes)
                ote_marker = ""
                if show_ote:
                    in_ote_live_bear = r.ote_bear_low <= price <= r.ote_bear_high if r.range_pips > 0 else False
                    in_ote_live_bull = r.ote_bull_low <= price <= r.ote_bull_high if r.range_pips > 0 else False
                    if in_ote_live_bear or in_ote_live_bull:
                        ote_marker = " OTE"

                # FVG affichage compact (liste de FVGs)
                fvg_ah_str = _fmt_fvg_compact(r.fvg_ah)
                fvg_al_str = _fmt_fvg_compact(r.fvg_al)

                # Max lots column (ajoutee dynamiquement si marge disponible)
                lots_col = f" {r.max_lots:.2f}" if _has_margin_live and r.max_lots is not None else ""

                # Dist AH/AL : format +8.2f = signe (+/-) inclus dans la largeur
                # pour que les valeurs positives et negatives soient alignees
                if _has_fvg_live:
                    print(f"  {r.symbol:<12} {fmt_price(price):>10} {fmt_price(r.asian_high):>10} "
                          f"{fmt_price(r.asian_low):>10} "
                          f"{dist_ah_pct:+8.2f}% "
                          f"{dist_al_pct:+8.2f}% "
                          f"{mid_sign}{abs(vs_mid):>6.2f}% "
                          f"{fvg_ah_str:>26} {fvg_al_str:>26} {ah_swept_str:>5} {al_swept_str:>5} {lots_col:>8}   {marker}{ote_marker}")
                else:
                    print(f"  {r.symbol:<12} {fmt_price(price):>10} {fmt_price(r.asian_high):>10} "
                          f"{fmt_price(r.asian_low):>10} "
                          f"{dist_ah_pct:+8.2f}% "
                          f"{dist_al_pct:+8.2f}% "
                          f"{mid_sign}{abs(vs_mid):>6.2f}% "
                          f"{ah_swept_str:>5} {al_swept_str:>5} {lots_col:>8}   {marker}{ote_marker}")

            print(f"  {'-' * sep_len}")
            print(f"  Ctrl+C pour quitter  |  Intervalle: {interval}s")

            time.sleep(interval)
    except KeyboardInterrupt:
        print(f"\n\n  Mode live termine apres {tick_count} tick(s).")


# ===============================================================================
# CLI
# ===============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="PureICT - Scan Session Asiatique (niveaux AH/AL/Mid)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples :
  python PureICT/scan_asian_session.py
  python PureICT/scan_asian_session.py --symbol EURUSD
  python PureICT/scan_asian_session.py --symbol EUR*
  python PureICT/scan_asian_session.py --symbol *JPY
  python PureICT/scan_asian_session.py --symbol EUR* --symbol *JPY
  python PureICT/scan_asian_session.py --symbol EURUSD --market-watch --previous
  python PureICT/scan_asian_session.py --symbol XAU* --date 2026-07-21
  python PureICT/scan_asian_session.py --export asian_levels.csv
  python PureICT/scan_asian_session.py --start-hour 22 --end-hour 6 --timezone UTC
  python PureICT/scan_asian_session.py --verbose
        """,
    )
    parser.add_argument("--date", default=None,
                        help="Date Paris de la session (YYYY-MM-DD). Defaut: aujourd'hui.")
    parser.add_argument("--max-symbols", type=int, default=None,
                        help="Limite du nombre de symboles a scanner.")
    parser.add_argument("--previous", action="store_true",
                        help="Inclure la session precedente (figee, comme les var lines du Pine Script).")
    parser.add_argument("--export", default=None,
                        help="Chemin du fichier CSV d'export.")
    parser.add_argument("--start-hour", type=int, default=DEFAULT_START_HOUR,
                        help=f"Heure de debut de session. Defaut: {DEFAULT_START_HOUR}h.")
    parser.add_argument("--end-hour", type=int, default=DEFAULT_END_HOUR,
                        help=f"Heure de fin de session. Defaut: {DEFAULT_END_HOUR}h.")
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE,
                        help=f"Fuseau de la session. Defaut: {DEFAULT_TIMEZONE}.")
    parser.add_argument("--symbol", "-s", action="append", default=[],
                        help="Filtre par motif (fnmatch). Accepte les wildcards * et ?. "
                             "Peut etre utilise plusieurs fois : --symbol EUR* --symbol *JPY. "
                             "Exemples : EURUSD, EUR*, *JPY, *USD*")
    parser.add_argument("--timeframe", "-tf", default=DEFAULT_TF,
                        choices=list(TIMEFRAMES.keys()),
                        help=f"Timeframe pour les bougies. Defaut: {DEFAULT_TF}."
                             f" M1/M5 = max precision, M15 = compromis, H1 = rapide.")
    parser.add_argument("--market-watch", action="store_true",
                        help="Utiliser uniquement les symboles visibles dans Market Watch (plus rapide).")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Mode verbeux (logs debug).")
    parser.add_argument("--live", "-l", action="store_true",
                        help="Mode live : rafraichit le prix en continu (Ctrl+C pour quitter).")
    parser.add_argument("--interval", "-i", type=int, default=10,
                        help="Intervalle de rafraichissement en secondes (defaut: 10s).")
    parser.add_argument("--force-select", action="store_true",
                        help="Pre-active tous les symboles dans Market Watch avant le scan. "
                             "Tente de contourner la limitation FTMO qui bloque les donnees "
                             "des symboles hors Market Watch.")
    parser.add_argument("--fvg", action="store_true",
                        help="Active la detection des Fair Value Gaps pres de l'AH/AL. "
                             "Detecte quand le prix est revenu sous l'AH ou au-dessus de l'AL "
                             "(peu importe la duree du depassement).")
    parser.add_argument("--fvg-min", type=float, default=DEFAULT_FVG_MIN_PCT,
                        help=f"Taille minimum du FVG en %% (defaut: {DEFAULT_FVG_MIN_PCT}%%).")
    parser.add_argument("--ote", action="store_true",
                        help="Affiche la zone OTE (Optimal Trade Entry) : retracement 0.618-0.382 "
                             "du range asiatique. Le prix dans cette zone est un signal ICT de continuation.")
    parser.add_argument("--swept-only", action="store_true",
                        help="Filtre les resultats pour n'afficher que les symboles ou "
                             "un sweep AH ou AL a ete detecte.")
    parser.add_argument("--json", default=None,
                        help="Exporte les resultats au format JSON (chemin du fichier). "
                             "Compatible avec --export (les deux formats peuvent etre generes simultanement).")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    print()
    print()
    print(f"  ====== PureICT ======")
    print(f"  Asian Session Scan")
    print(f"  =====================")
    print()

    offset = _tz_offset(args.timezone)

    # -- Selection intelligente de la session (logique MQL5) --
    if args.date:
        session_date = args.date
        date_source = "manuelle (--date)"
    else:
        session_date = _smart_session_date(args.end_hour, args.timezone)
        date_source = "auto (MQL5: avant fin session -> hier, apres -> aujourd'hui)"

    print(f"  Fuseau session : {args.timezone} (UTC{'+' if offset > 0 else ''}{offset})")
    print(f"  Creneau        : {args.start_hour:02d}:00 -> {args.end_hour:02d}:00 {args.timezone}")
    print(f"  Date session   : {session_date} ({date_source})")
    print(f"  Timeframe      : {args.timeframe}")
    # -- Intervalle UTC reel pour affichage --
    true_end_utc = _session_true_utc_end(session_date, args.end_hour, args.timezone)
    offset_hours = _tz_offset(args.timezone)
    true_start_utc = true_end_utc - timedelta(hours=(args.end_hour - args.start_hour))
    print(f"  Intervalle UTC : {true_start_utc.strftime('%Y-%m-%d %H:%M')} -> {true_end_utc.strftime('%H:%M')}")
    print(f"  Heure {args.timezone} : {paris_now().strftime('%H:%M:%S')}")
    in_session = is_in_asian_session(args.start_hour, args.end_hour, args.timezone)
    print(f"  {'(Session en cours)' if in_session else '(Session terminee)'}")
    if in_session:
        fin = true_end_utc.strftime('%H:%M')
        print(f"  Fin de session dans ~{(true_end_utc - now_datetime()).total_seconds():.0f}s ({fin} UTC)")
    # Indique clairement si on affiche la session d'hier
    is_previous = in_session and not args.date
    if is_previous:
        today_str_local = (now_datetime() + timedelta(hours=offset)).strftime("%Y-%m-%d")
        print(f"  !! Session d'aujourd'hui ({today_str_local}) encore en cours ->")
        print(f"     affichage de la session precedente ({session_date}) terminee.")
    print()

    current, previous, excluded = scan_all_symbols(
        session_date_paris=session_date,
        max_symbols=args.max_symbols,
        include_previous=args.previous,
        market_watch_only=args.market_watch,
        start_hour=args.start_hour,
        end_hour=args.end_hour,
        symbol_filters=args.symbol if args.symbol else None,
        timeframe=args.timeframe,
        tz_mode=args.timezone,
        force_select=args.force_select,
        fvg_mode=args.fvg,
        fvg_min_pct=args.fvg_min,
    )

    if not current:
        print(f"  Aucune donnee asiatique trouvee.")
        print(f"  Verifie que MT5 est connecte et que les symboles sont disponibles.")
        return 1

    # -- Filtre --swept-only (AH ou AL sweepe) --
    if args.swept_only:
        n_before = len(current)
        current = [r for r in current if r.ah_swept or r.al_swept]
        n_after = len(current)
        n_filtre = n_before - n_after
        if n_filtre > 0:
            print(f"  Filtre --swept-only : {n_after} symbole(s) avec sweep / {n_filtre} exclus")
        elif n_before == 0:
            print(f"  Aucun symbole avec sweep detecte.")
        else:
            print(f"  Filtre --swept-only : tous les {n_after} symboles ont un sweep.")
        if not current:
            print(f"  Aucun resultat apres filtrage --swept-only.")
            return 1

    if args.live:
        if args.export or args.json:
            print(f"  !! --live est incompatible avec --export et --json, les exports sont ignores.\n")
        live_monitor(current, args.timezone, args.interval, show_ote=args.ote)
        return 0

    display_results(current, previous if args.previous else None, args.timezone,
                    is_previous_session=is_previous, show_ote=args.ote)

    # Afficher les exclus si --verbose
    if excluded and args.verbose:
        display_exclusions(excluded, len(current))
    elif excluded and not args.verbose:
        # Petit resume meme sans --verbose
        reasons = {}
        for _, reason in excluded:
            reasons[reason] = reasons.get(reason, 0) + 1
        resume = ", ".join(f"{n}x {r}" for r, n in sorted(reasons.items()))
        print(f"\n  {len(excluded)} symbole(s) exclus ({resume})")
        print(f"  Utilise --verbose (-v) pour voir le detail.")

    if args.export:
        export_csv(current, args.export)
    if args.json:
        export_json(current, args.json)

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
