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

# Nombre de barres a charger pour la detection FVG (couvre ~6h post-session)
FVG_LOOKBACK = 360

# Taille minimum du FVG en %%
DEFAULT_FVG_MIN_PCT = 0.02


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
    fvg_ah: Optional[dict] = None   # FVG baissier pres AH (price a depasse AH puis est revenu dessous)
    fvg_al: Optional[dict] = None   # FVG haussier pres AL (price a depasse AL puis est revenu dessus)
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


def _session_epochs(
    session_date: str,
    start_hour: int = DEFAULT_START_HOUR,
    end_hour: int = DEFAULT_END_HOUR,
    tz_mode: str = DEFAULT_TIMEZONE,
) -> Tuple[float, float]:
    """Retourne (start_epoch, end_epoch) compatibles avec les timestamps MT5.

    !! CRITIQUE : les timestamps de `copy_rates_from_pos` sont en heure SERVEUR
    (broker) traites comme si c'etait UTC. Ex: barre a 01:00 broker (UTC+3) ->
    epoch equivalent a "01:00 UTC" (PAS "22:00 UTC veille").

    Convertit les heures du fuseau utilisateur (tz_mode) en heures BROKER,
    puis construit les epochs en traitant ces heures comme UTC.

    Args:
        session_date: Date de la session au format YYYY-MM-DD.
        start_hour: Heure de debut (fuseau tz_mode).
        end_hour: Heure de fin (fuseau tz_mode).
        tz_mode: Fuseau de la session (PARIS, BROKER, UTC).

    Returns:
        (start_epoch, end_epoch) - timestamps compatibles MT5.
    """
    dt = datetime.strptime(session_date, "%Y-%m-%d")
    # MT5 stocke les heures en heure SERVEUR (BROKER). Convertir du fuseau
    # utilisateur vers le fuseau BROKER. Ex: PARIS 0->8 = BROKER 1->9.
    broker_off = _tz_offset("BROKER")
    user_off = _tz_offset(tz_mode)
    hour_shift = broker_off - user_off  # 0 pour BROKER, 1 pour PARIS, 3 pour UTC

    # Utiliser timedelta (pas replace) pour gerer le rollover >23h ou <0h
    base = dt.replace(hour=0, minute=0, second=0)
    start_dt = base + timedelta(hours=start_hour + hour_shift)
    end_dt = base + timedelta(hours=end_hour + hour_shift)
    start_epoch = start_dt.replace(tzinfo=timezone.utc).timestamp()
    end_epoch = end_dt.replace(tzinfo=timezone.utc).timestamp()
    return (start_epoch, end_epoch)


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


def _fmt_fvg_compact(fvg_dict: dict) -> str:
    """Formate un FVG en affichage compact pour le tableau live.

    Ex: "B-M5" pour bearish M5, "B-M1" pour bullish M1.
    """
    direction = fvg_dict.get("direction", "?")
    tf = fvg_dict.get("timeframe", "?")
    prefix = "B" if direction == "bearish" else "b"  # B=bear, b=bull
    return f"{prefix}-{tf}"


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
    end_epoch: float,
    fvg_min_pct: float = DEFAULT_FVG_MIN_PCT,
) -> Tuple[Optional[FvgInfo], Optional[FvgInfo]]:
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
    On garde le premier FVG trouve sur le plus grand timeframe.

    Args:
        symbol: Symbole MT5.
        asian_high: Asian High de la session.
        asian_low: Asian Low de la session.
        end_epoch: Fin de la session asiatique (epoch MT5).
        fvg_min_pct: Taille minimum du FVG en %%.

    Returns:
        (fvg_ah, fvg_al) - FVGInfo ou None pour chaque niveau.
    """
    fvg_ah_result: Optional[FvgInfo] = None
    fvg_al_result: Optional[FvgInfo] = None

    # Parcourir les timeframes du plus grand au plus petit
    tf_names = ["M15", "M5", "M3", "M1"]
    for tf_name in tf_names:
        tf = FVG_TIMEFRAMES.get(tf_name)
        if tf is None:
            continue

        rates_raw = mt5.copy_rates_from_pos(symbol, tf, 0, FVG_LOOKBACK)
        if rates_raw is None or len(rates_raw) == 0:
            continue

        bars = bars_to_dicts(rates_raw)
        bars.sort(key=lambda b: b["time"])

        # Barres post-session
        post_bars = [b for b in bars if b["time"] >= end_epoch]
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
        for i in range(len(post_bars) - 1, 1, -1):  # de la fin vers le debut
            if fvg_ah_result is None and back_below_ah:
                fvg = find_fvg_at(post_bars, i, "bear", fvg_min_pct)
                if fvg is not None:
                    # Verifier que le FVG est pres de l'AH
                    dist = _level_distance(fvg["zone_top"], fvg["zone_bottom"], asian_high)
                    if dist < 0.5:  # dans les 0.5% de l'AH
                        fvg_ah_result = FvgInfo(
                            timeframe=tf_name,
                            direction="bearish",
                            zone_top=fvg["zone_top"],
                            zone_bottom=fvg["zone_bottom"],
                            gap_pct=fvg["gap_pct"],
                            gap_size=fvg["gap_size"],
                            level_type="AH",
                            level_price=asian_high,
                        )

            if fvg_al_result is None and back_above_al:
                fvg = find_fvg_at(post_bars, i, "bull", fvg_min_pct)
                if fvg is not None:
                    dist = _level_distance(fvg["zone_top"], fvg["zone_bottom"], asian_low)
                    if dist < 0.5:
                        fvg_al_result = FvgInfo(
                            timeframe=tf_name,
                            direction="bullish",
                            zone_top=fvg["zone_top"],
                            zone_bottom=fvg["zone_bottom"],
                            gap_pct=fvg["gap_pct"],
                            gap_size=fvg["gap_size"],
                            level_type="AL",
                            level_price=asian_low,
                        )

            if fvg_ah_result is not None and fvg_al_result is not None:
                break

    return fvg_ah_result, fvg_al_result


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


    # -- Epochs compatibles MT5 (heure broker traitee comme UTC) --
    start_epoch, end_epoch = _session_epochs(session_date_paris, start_hour, end_hour,
                                               tz_mode)

    # Offset BROKER pour convertir epochs MT5 -> vrai UTC (affichage)
    _broker_offset_sec = _tz_offset("BROKER") * 3600

    # Vraie fin de session UTC (pour is_live)
    true_end_utc = _session_true_utc_end(session_date_paris, end_hour, tz_mode)

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

    # -- Barres de la session asiatique --
    session_bars = [b for b in bars if start_epoch <= b["time"] < end_epoch]
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
            high_at_epoch = float(b["time"]) - _broker_offset_sec  # MT5->UTC
        if b["low"] < asian_low:
            asian_low = b["low"]
            low_at_epoch = float(b["time"]) - _broker_offset_sec  # MT5->UTC

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

    # -- Session live ? --
    is_live = time.time() < true_end_utc.timestamp()
    if is_live:
        # Si session en cours, le close est le prix actuel
        tick = mt5.symbol_info_tick(symbol)
        close_last_bar = float(tick.bid) if tick else close_last_bar

    # -- Barres post-session pour sweeps --
    true_end_epoch = true_end_utc.timestamp()
    today_date_utc = time.strftime("%Y-%m-%d", time.gmtime(true_end_epoch))
    post_bars = [
        b for b in bars
        if b["time"] >= end_epoch
        and time.strftime("%Y-%m-%d", time.gmtime(b["time"] - _broker_offset_sec)) == today_date_utc
    ]

    ah_swept = False
    al_swept = False
    ah_swept_at: Optional[str] = None
    al_swept_at: Optional[str] = None

    for b in post_bars:
        if not ah_swept and sweep_high(b, asian_high):
            ah_swept = True
            ah_swept_at = format_epoch(b["time"] - _broker_offset_sec)
        if not al_swept and sweep_low(b, asian_low):
            al_swept = True
            al_swept_at = format_epoch(b["time"] - _broker_offset_sec)
        if ah_swept and al_swept:
            break

    # -- Prix actuel --
    tick = mt5.symbol_info_tick(symbol)
    current_price = float(tick.bid) if tick else (bars[-1]["close"] if bars else 0.0)

    # -- Detection FVG pres AH/AL (si active) --
    fvg_ah_result: Optional[FvgInfo] = None
    fvg_al_result: Optional[FvgInfo] = None
    if fvg_mode:
        try:
            fvg_ah_result, fvg_al_result = scan_reclaim_fvgs(
                symbol, asian_high, asian_low, end_epoch, fvg_min_pct,
            )
        except Exception as e:
            logger.debug("FVG scan failed for %s: %s", symbol, e)

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
        fvg_ah=asdict(fvg_ah_result) if fvg_ah_result else None,
        fvg_al=asdict(fvg_al_result) if fvg_al_result else None,
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
                    is_previous_session: bool = False):
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

    # -- Tableau unique --
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

        print(f"  {r.symbol:<14}"
              f"{fmt_price(r.open_first_bar):>12} "
              f"{fmt_price(r.close_last_bar):>12} "
              f"{fmt_price(r.asian_high):>12} "
              f"{ah_utc.split()[0]:>7} {ah_paris.split()[0]:>9} {ah_broker.split()[0]:>9} "
              f"{fmt_price(r.asian_low):>12} "
              f"{al_utc.split()[0]:>7} {al_paris.split()[0]:>9} {al_broker.split()[0]:>9}")

    print(sep)
    print(f"  TZ: UTC / Paris / Broker  |  Live = session en cours (donnees partielles)")

    # -- Extensions Fibonacci --
    _print_fibonacci(results)

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


# ===============================================================================
# MODE LIVE
# ===============================================================================

def live_monitor(results: List[AsianLevels], tz_mode: str, interval: int):
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
            if _has_fvg_live:
                hdr = (f"  {'Symbole':<12} {'Prix':>10} {'AH':>10} {'AL':>10} "
                       f"{'Dist AH':>9} {'Dist AL':>9} {'vs Mid':>8} {'FVG AH':>8} {'FVG AL':>8}")
                sep_len = 98
            else:
                hdr = (f"  {'Symbole':<12} {'Prix':>10} {'AH':>10} {'AL':>10} "
                       f"{'Dist AH':>9} {'Dist AL':>9} {'vs Mid':>8} {'Sweeps':>8}")
                sep_len = 85
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

                # Direction visuelle
                ah_sign = "+" if dist_ah_pct > 0 else ""
                al_sign = "+" if dist_al_pct > 0 else ""
                mid_sign = ">" if vs_mid > 0 else ("<" if vs_mid < 0 else "=")

                # Sweeps
                sweep_str = ""
                if r.ah_swept:
                    sweep_str += "AH"
                if r.al_swept:
                    sweep_str += "AL" if not sweep_str else ",AL"
                if not sweep_str:
                    sweep_str = "-"

                # Couleur selon position vs AH/AL
                if price > r.asian_high:
                    marker = " ABOVE"
                elif price < r.asian_low:
                    marker = " BELOW"
                else:
                    marker = "  IN  "

                # FVG affichage compact
                fvg_ah_str = _fmt_fvg_compact(r.fvg_ah) if r.fvg_ah else ""
                fvg_al_str = _fmt_fvg_compact(r.fvg_al) if r.fvg_al else ""

                if _has_fvg_live:
                    print(f"  {r.symbol:<12} {fmt_price(price):>10} {fmt_price(r.asian_high):>10} "
                          f"{fmt_price(r.asian_low):>10} "
                          f"{ah_sign}{dist_ah_pct:>7.2f}% "
                          f"{al_sign}{dist_al_pct:>7.2f}% "
                          f"{mid_sign}{abs(vs_mid):>6.2f}% "
                          f"{fvg_ah_str:>8} {fvg_al_str:>8}{marker}")
                else:
                    print(f"  {r.symbol:<12} {fmt_price(price):>10} {fmt_price(r.asian_high):>10} "
                          f"{fmt_price(r.asian_low):>10} "
                          f"{ah_sign}{dist_ah_pct:>7.2f}% "
                          f"{al_sign}{dist_al_pct:>7.2f}% "
                          f"{mid_sign}{abs(vs_mid):>6.2f}% "
                          f"{sweep_str:>8}{marker}")

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
        print(f"  Fin de session dans ~{true_end_utc.timestamp() - time.time():.0f}s ({fin} UTC)")
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

    if args.live:
        if args.export:
            print(f"  !! --live et --export sont incompatibles, l'export est ignore.\n")
        live_monitor(current, args.timezone, args.interval)
        return 0

    display_results(current, previous if args.previous else None, args.timezone,
                    is_previous_session=is_previous)

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

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
