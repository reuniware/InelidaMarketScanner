#!/usr/bin/env python3
"""
📜 Backtest Historique Diamond — Janvier → Aujourd'hui (Juillet 2026)
=====================================================================

Rejoue l'analyse Diamond Analysis jour par jour sur les données historiques MT5,
backteste l'outcome (TP/SL touché) et génère un CSV labellisé prêt pour le ML.

Usage:
    # Scan Janvier → Juillet sur les 6 symboles majeurs (rapide)
    python backtest_historical_diamond.py --symbols EURUSD GBPUSD USDJPY AUDUSD USDCAD USDCHF --output data/historical_dataset.csv

    # Scan complet 13 symboles (lent ~3h)
    python backtest_historical_diamond.py --output data/historical_dataset_full.csv

    # Test rapide : 1 symbole × 2 jours
    python backtest_historical_diamond.py --symbols EURUSD --start 2026-07-01 --end 2026-07-03 --output data/historical_test.csv
"""

import argparse
import csv
import logging
import os
import sys
import time as _time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Dict, List, Optional, Tuple

import MetaTrader5 as mt5

# Import extract_features pour générer les 100+ features nommées
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.ml_predictor import extract_features

# ─── Configuration ────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("HistoricalBacktest")

UTC = timezone.utc

# Symboles par défaut (les 13 de la watchlist)
DEFAULT_SYMBOLS = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF",
    "EURJPY", "GBPJPY", "XAUUSD",
    "US30.cash", "US100.cash", "US500.cash", "DXY.cash",
]


# ─── Helpers ──────────────────────────────────────────────────────────────

def _pips(sym: str, price: float, level: float) -> float:
    """Calcule la distance en pips entre deux prix."""
    if sym == 'XAUUSD':
        return (price - level) * 10
    elif 'JPY' in sym:
        return (price - level) * 100
    elif 'DXY' in sym or 'USDX' in sym:
        return (price - level) * 100
    else:
        return (price - level) * 10000


def _safe_float(val, default: float = 0.0) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (ValueError, TypeError):
        return default


def _parse_date(s: str) -> datetime:
    """Parse une date au format YYYY-MM-DD en datetime UTC (fin de journée)."""
    dt = datetime.strptime(s, "%Y-%m-%d")
    return dt.replace(hour=23, minute=59, second=59, tzinfo=UTC)


def _is_trading_day(dt: datetime) -> bool:
    """Vérifie si un jour est un jour de trading (lundi → vendredi)."""
    return dt.weekday() < 5


def _business_day_range(start: datetime, end: datetime) -> List[datetime]:
    """Génère la liste des jours ouvrés entre start et end (inclus)."""
    days = []
    current = start.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=UTC)
    end_day = end.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=UTC)
    while current <= end_day:
        if _is_trading_day(current):
            days.append(current)
        current += timedelta(days=1)
    return days


# ─── Historical Diamond Scanner ──────────────────────────────────────────

class HistoricalDiamondScanner:
    """Réimplémentation légère de l'analyse Diamond pour un jour historique.

    Se concentre sur les critères essentiels qui peuvent être calculés
    à partir des données MT5 historiques :
      - Kijun / Tenkan (H1, H4, D1, W1)
      - T/K crosses
      - Kumo positions
      - Bias directionnel
    """

    def __init__(self, symbols: List[str], scan_date: datetime):
        self.symbols = symbols
        self.scan_date = scan_date  # datetime avec tzinfo=UTC

    # ── Data fetching ──

    # Multiplicateurs de sécurité pour copy_rates_range
    # On demande 3× le nombre de barres nécessaires pour être sûr d'avoir assez d'historique
    _TF_LOOKBACK_MULT = {
        mt5.TIMEFRAME_M1: 60 * 3,      # 3 heures pour 60 barres M1
        mt5.TIMEFRAME_M5: 300 * 3,      # 15 min × 3
        mt5.TIMEFRAME_M15: 900 * 3,     # 45 min × 3
        mt5.TIMEFRAME_M30: 1800 * 3,    # 1h30 × 3
        mt5.TIMEFRAME_H1: 3600 * 3,     # 3h × le nb de barres
        mt5.TIMEFRAME_H4: 14400 * 3,    # 12h × le nb de barres
        mt5.TIMEFRAME_D1: 86400 * 3,    # 3 jours × le nb de barres
        mt5.TIMEFRAME_W1: 604800 * 3,   # 3 semaines × le nb de barres
        mt5.TIMEFRAME_MN1: 2592000 * 3, # 3 mois × le nb de barres (approx)
    }

    def _fetch_rates(self, sym: str, tf: int, n: int) -> Optional[List[Tuple[int, float, float, float]]]:
        """Fetch N barres OHLC terminant à scan_date.

        Utilise copy_rates_range avec une borne de fin explicite (scan_date)
        pour éviter le data leakage. Ne JAMAIS utiliser copy_rates_from()
        qui retourne les barres vers le futur.
        """
        lookback_sec = self._TF_LOOKBACK_MULT.get(tf, 3600 * 3) * n
        from_dt = self.scan_date - timedelta(seconds=lookback_sec)
        r = mt5.copy_rates_range(sym, tf, from_dt, self.scan_date)
        if r is None or len(r) < n:
            return None
        # Prendre les N dernières barres (les plus proches de scan_date)
        return [(int(x[0]), float(x[2]), float(x[3]), float(x[4])) for x in r[-n:]]

    # ── Ichimoku calculations ──

    @staticmethod
    def _kj(highs: List[float], lows: List[float]) -> float:
        if len(highs) < 26:
            return 0.0
        return (max(highs[-26:]) + min(lows[-26:])) / 2.0

    @staticmethod
    def _tk(highs: List[float], lows: List[float]) -> float:
        if len(highs) < 9:
            return 0.0
        return (max(highs[-9:]) + min(lows[-9:])) / 2.0

    @staticmethod
    def _tkx(tk: float, kj: float) -> str:
        if tk == 0 or kj == 0:
            return "N/A"
        return "BULL" if tk > kj else ("BEAR" if tk < kj else "N/A")

    def _kumo_pos(self, price: float, highs: List[float], lows: List[float]) -> str:
        n = len(highs)
        if n < 78:
            return "N/A"
        idx = n - 27
        if idx < 52:
            return "N/A"
        tk_v = (max(highs[idx - 8:idx + 1]) + min(lows[idx - 8:idx + 1])) / 2.0
        kj_v = (max(highs[idx - 25:idx + 1]) + min(lows[idx - 25:idx + 1])) / 2.0
        sa_v = (tk_v + kj_v) / 2.0
        sb_v = (max(highs[idx - 51:idx + 1]) + min(lows[idx - 51:idx + 1])) / 2.0
        ct, cb = max(sa_v, sb_v), min(sa_v, sb_v)
        return "ABOVE" if price > ct else ("BELOW" if price < cb else "INSIDE")

    # ── Bias determination ──

    def _determine_bias(self, price: float,
                        kj_h1: float, kj_h4: float, kj_d1: float,
                        tkx_h1: str, tkx_h4: str, tkx_d1: str,
                        kumo_h1: str, kumo_h4: str, kumo_d1: str) -> Tuple[str, int]:
        """Détermine le biais directionnel basé sur l'Ichimoku multi-TF.

        Returns:
            (bias, alignment) — bias: "BULL", "BEAR", "FLAT"
        """
        bull_score = 0
        bear_score = 0

        # Price vs Kijun
        if kj_h1 > 0:
            if price > kj_h1:
                bull_score += 1
            else:
                bear_score += 1
        if kj_h4 > 0:
            if price > kj_h4:
                bull_score += 1
            else:
                bear_score += 1
        if kj_d1 > 0:
            if price > kj_d1:
                bull_score += 1
            else:
                bear_score += 1

        # T/K crosses
        if tkx_h1 == "BULL":
            bull_score += 1
        elif tkx_h1 == "BEAR":
            bear_score += 1
        if tkx_h4 == "BULL":
            bull_score += 1
        elif tkx_h4 == "BEAR":
            bear_score += 1
        if tkx_d1 == "BULL":
            bull_score += 1
        elif tkx_d1 == "BEAR":
            bear_score += 1

        # Kumo positions
        if kumo_h1 == "ABOVE":
            bull_score += 1
        elif kumo_h1 == "BELOW":
            bear_score += 1
        if kumo_h4 == "ABOVE":
            bull_score += 1
        elif kumo_h4 == "BELOW":
            bear_score += 1
        if kumo_d1 == "ABOVE":
            bull_score += 1
        elif kumo_d1 == "BELOW":
            bear_score += 1

        if bull_score > bear_score + 2:
            return ("BULL", bull_score)
        elif bear_score > bull_score + 2:
            return ("BEAR", bear_score)
        else:
            return ("FLAT", 0)

    # ── SL/TP calculation ──

    def _calculate_sl_tp(self, sym: str, price: float, bias: str,
                         kj_h1: float, kj_h4: float, kj_d1: float) -> Tuple[float, float, float]:
        """Calcule SL et TP basés sur les Kijun (simple).

        Returns:
            (sl, tp, rr)
        """
        if bias == "FLAT":
            return (0.0, 0.0, 0.0)

        d_kj4 = _pips(sym, price, kj_h4) if kj_h4 > 0 else 0

        if bias == "BULL":
            # SL sous le Kijun H4 le plus proche
            candidates = [k for k in [kj_h1, kj_h4, kj_d1] if k > 0 and k < price]
            sl = max(candidates) if candidates else (price - 0.005 if 'JPY' in sym else price * 0.995)
            # TP = SL + 2 × distance
            risk = abs(_pips(sym, price, sl))
            pip_f = 10 if sym == 'XAUUSD' else (100 if 'JPY' in sym else 10000)
            tp = price + (risk * 2.0) / pip_f
        else:  # BEAR
            candidates = [k for k in [kj_h1, kj_h4, kj_d1] if k > 0 and k > price]
            sl = min(candidates) if candidates else (price + 0.005 if 'JPY' in sym else price * 1.005)
            risk = abs(_pips(sym, price, sl))
            pip_f = 10 if sym == 'XAUUSD' else (100 if 'JPY' in sym else 10000)
            tp = price - (risk * 2.0) / pip_f

        # RR
        dist_sl = abs(_pips(sym, price, sl))
        dist_tp = abs(_pips(sym, price, tp))
        rr = round(dist_tp / max(dist_sl, 0.01), 2) if dist_sl > 0 else 0.0

        return (round(sl, 5), round(tp, 5), rr)

    # ── Backtest outcome ──

    # ── FVG detection (lightweight, adapted from diamond_scanner.py) ──

    @staticmethod
    def _detect_fvg_historical(
        highs: List[float], lows: List[float],
        price: float, scan_window: int
    ) -> Tuple[float, float, float, float, float, float]:
        """Detecte FVG bearish + bullish sur des donnees historiques.

        Bearish FVG: low[i-2] > high[i]  (gap down)
        Bullish FVG: high[i-2] < low[i]  (gap up)

        Prend le plus recent (index le plus eleve).

        Returns:
            bear_top, bear_bot, bear_mitigated_pct,
            bull_top, bull_bot, bull_mitigated_pct
        """
        n = len(highs)
        if n < 6:
            return (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

        max_idx = min(n, scan_window)
        best_bear_idx = -1
        best_bull_idx = -1
        bear_top = bear_bot = 0.0
        bull_top = bull_bot = 0.0

        for i in range(2, max_idx):
            # Bearish FVG: low[i-2] > high[i]
            if lows[i - 2] > highs[i]:
                if i > best_bear_idx:
                    best_bear_idx = i
                    bear_top = lows[i - 2]
                    bear_bot = highs[i]

            # Bullish FVG: high[i-2] < low[i]
            if highs[i - 2] < lows[i]:
                if i > best_bull_idx:
                    best_bull_idx = i
                    bull_top = lows[i]
                    bull_bot = highs[i - 2]

        # ── Mitigation % ──
        bear_mit = 0.0
        if best_bear_idx >= 0 and bear_top > bear_bot:
            gap = bear_top - bear_bot
            deepest = 0.0
            for k in range(best_bear_idx + 1, n):
                if highs[k] >= bear_bot:
                    entry = min(highs[k], bear_top)
                    if entry > deepest:
                        deepest = entry
            if price >= bear_bot:
                entry = min(price, bear_top)
                if entry > deepest:
                    deepest = entry
            if deepest > 0:
                bear_mit = (deepest - bear_bot) / gap * 100.0
                bear_mit = min(100.0, max(0.0, bear_mit))

        bull_mit = 0.0
        if best_bull_idx >= 0 and bull_top > bull_bot:
            gap = bull_top - bull_bot
            deepest = bull_top
            for k in range(best_bull_idx + 1, n):
                if lows[k] <= bull_top:
                    entry = max(lows[k], bull_bot)
                    if entry < deepest:
                        deepest = entry
            if price <= bull_top:
                entry = max(price, bull_bot)
                if entry < deepest:
                    deepest = entry
            bull_mit = (bull_top - deepest) / gap * 100.0
            bull_mit = min(100.0, max(0.0, bull_mit))

        return (bear_top, bear_bot, bear_mit, bull_top, bull_bot, bull_mit)

    # ── Order Block detection (lightweight, adapted from diamond_scanner.py) ──

    @staticmethod
    def _detect_ob_historical(
        highs: List[float], lows: List[float], closes: List[float],
        price: float, scan_window: int = 80, min_dist_pct: float = 0.005
    ) -> Tuple[float, float]:
        """Detecte Order Blocks bear + bull sur des donnees historiques.

        v2 (18/07/2026):
          - ATR x 2.0 (was 1.2) -> seuls les vrais mouvements d'impulsion
          - Mitigation detection: OB must be UNMITIGATED (price hasn't touched it)
          - Distance filter: TF-aware (0.2% H1, 0.5% H4, 1.0% D1)

        Bearish OB: candle BEFORE a bearish impulse (close drops > 2.0x ATR),
                    price must be BELOW the OB level (unmitigated resistance).
        Bullish OB: candle BEFORE a bullish impulse (close rises > 2.0x ATR),
                    price must be ABOVE the OB level (unmitigated support).

        Returns:
            bear_level, bull_level (closest unmitigated OB, or 0.0 if none)
        """
        n = len(highs)
        if n < 10:
            return (0.0, 0.0)

        max_idx = min(n, scan_window)

        # ATR(14)
        ranges = [highs[i] - lows[i] for i in range(max_idx)]
        atr14 = sum(ranges[-14:]) / 14 if len(ranges) >= 14 else (sum(ranges) / max(len(ranges), 1))
        impulse_thresh = atr14 * 2.0  # v2: was 1.2 -> now 2.0 for real impulses only

        if atr14 <= 0:
            return (0.0, 0.0)

        min_dist_pct = 0.005  # 0.5% minimum distance from price

        bear_level = 0.0
        bull_level = 0.0
        best_bear_dist = float('inf')
        best_bull_dist = float('inf')

        for i in range(2, max_idx):
            # Bearish impulse: close drops > 2.0x ATR
            if closes[i] < closes[i - 1] - impulse_thresh:
                level = highs[i - 1]
                # Only UNMITIGATED: price must be BELOW the OB
                if price >= level:
                    continue
                # Distance filter: > 0.5% from price
                dist_pct = abs(price - level) / level
                if dist_pct < min_dist_pct:
                    continue
                dist = abs(price - level)
                if dist < best_bear_dist:
                    bear_level = level
                    best_bear_dist = dist

            # Bullish impulse: close rises > 2.0x ATR
            if closes[i] > closes[i - 1] + impulse_thresh:
                level = lows[i - 1]
                # Only UNMITIGATED: price must be ABOVE the OB
                if price <= level:
                    continue
                # Distance filter: > 0.5% from price
                dist_pct = abs(price - level) / level
                if dist_pct < min_dist_pct:
                    continue
                dist = abs(price - level)
                if dist < best_bull_dist:
                    bull_level = level
                    best_bull_dist = dist

        return (bear_level, bull_level)

    # ── Market Structure detection (lightweight, adapted from diamond_scanner.py) ──

    @staticmethod
    def _detect_mss_historical(
        highs: List[float], lows: List[float],
        price: float, scan_window: int = 60
    ) -> Tuple[str, str, str]:
        """Analyse Market Structure (BOS, MSS, regime) sur donnees historiques.

        Returns:
            (regime, bos, shift)
            regime: "BULL", "BEAR", "RANGE", "N/A"
            bos: "BULL", "BEAR", "N/A"
            shift: "BULL", "BEAR", "N/A"
        """
        n = len(highs)
        if n < 10:
            return ("N/A", "N/A", "N/A")

        max_idx = min(n, scan_window)

        # Swing detection (5-bar fractals)
        swing_highs: List[Tuple[int, float]] = []
        swing_lows: List[Tuple[int, float]] = []

        for i in range(2, max_idx - 2):
            if (highs[i] > highs[i-2] and highs[i] > highs[i-1] and
                highs[i] >= highs[i+1] and highs[i] >= highs[i+2]):
                swing_highs.append((i, highs[i]))
            if (lows[i] < lows[i-2] and lows[i] < lows[i-1] and
                lows[i] <= lows[i+1] and lows[i] <= lows[i+2]):
                swing_lows.append((i, lows[i]))

        if not swing_highs or not swing_lows:
            return ("RANGE", "N/A", "N/A")

        # Regime: analyser les 3 derniers swings
        last_3_sh = swing_highs[-3:] if len(swing_highs) >= 3 else swing_highs
        last_3_sl = swing_lows[-3:] if len(swing_lows) >= 3 else swing_lows

        higher_highs = len(last_3_sh) >= 2 and last_3_sh[-1][1] > last_3_sh[-2][1]
        lower_highs = len(last_3_sh) >= 2 and last_3_sh[-1][1] < last_3_sh[-2][1]
        higher_lows = len(last_3_sl) >= 2 and last_3_sl[-1][1] > last_3_sl[-2][1]
        lower_lows = len(last_3_sl) >= 2 and last_3_sl[-1][1] < last_3_sl[-2][1]

        if higher_highs and higher_lows:
            regime = "BULL"
        elif lower_highs and lower_lows:
            regime = "BEAR"
        else:
            regime = "RANGE"

        # BOS
        bos = "N/A"
        last_sh = swing_highs[-1][1] if swing_highs else None
        last_sl = swing_lows[-1][1] if swing_lows else None
        if last_sh and price > last_sh:
            bos = "BULL"
        elif last_sl and price < last_sl:
            bos = "BEAR"

        # MSS (shift)
        shift = "N/A"
        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            prev_sh = swing_highs[-2][1]
            prev_sl = swing_lows[-2][1]
            # Bullish MSS: higher low in a downtrend
            if last_sl and prev_sl and last_sl > prev_sl and regime != "BULL":
                shift = "BULL"
            # Bearish MSS: lower high in an uptrend
            if last_sh and prev_sh and last_sh < prev_sh and regime != "BEAR":
                shift = "BEAR"

        return (regime, bos, shift)

    def _backtest_outcome(self, sym: str, scan_dt: datetime,
                          price: float, sl: float, tp: float, bias: str,
                          max_lookback_hours: int = 120) -> int:
        """Backteste le trade sur les M1 après scan_dt.

        Returns:
            1.0 = TP touché avant SL
            0.0 = SL touché avant TP
            -1.0 = Ni TP ni SL dans le lookback
        """
        if bias == "FLAT" or sl == 0 or tp == 0:
            return -1

        # Début = scan_dt + 1 minute
        from_dt = scan_dt + timedelta(minutes=1)
        to_dt = scan_dt + timedelta(hours=max_lookback_hours)

        # Si to_dt est dans le futur, limiter à maintenant
        now = datetime.now(UTC).replace(tzinfo=UTC)
        if to_dt > now:
            to_dt = now

        if from_dt >= to_dt:
            return -1

        # Fetch M1 bars
        rates = mt5.copy_rates_range(sym, mt5.TIMEFRAME_M1, from_dt, to_dt)
        if rates is None or len(rates) < 2:
            # Fallback M5
            rates = mt5.copy_rates_range(sym, mt5.TIMEFRAME_M5, from_dt, to_dt)
            if rates is None or len(rates) < 2:
                return -1

        # Vérifier TP/SL barre par barre
        tp_hit_bar = None
        sl_hit_bar = None

        if bias == "BULL":
            # SL en dessous, TP au-dessus
            for i, bar in enumerate(rates):
                bar_high = float(bar[2])
                bar_low = float(bar[3])
                if bar_high >= tp:
                    tp_hit_bar = i
                    break
                if bar_low <= sl:
                    sl_hit_bar = i
                    break
        else:  # BEAR
            for i, bar in enumerate(rates):
                bar_high = float(bar[2])
                bar_low = float(bar[3])
                if bar_low <= tp:
                    tp_hit_bar = i
                    break
                if bar_high >= sl:
                    sl_hit_bar = i
                    break

        if tp_hit_bar is not None:
            return 1
        elif sl_hit_bar is not None:
            return 0
        else:
            return -1

    # ── Scan one symbol on one date ──

    def scan_symbol(self, sym: str) -> Optional[Dict[str, float]]:
        """Analyse un symbole à la date scan_date et retourne les features + outcome.

        Returns:
            Dict avec toutes les features + outcome, ou None si données insuffisantes.
        """
        mt5.symbol_select(sym, True)

        # Fetch data for each timeframe (en commençant par H1 pour extraire le prix)
        h1 = self._fetch_rates(sym, mt5.TIMEFRAME_H1, 80)
        h4 = self._fetch_rates(sym, mt5.TIMEFRAME_H4, 60)
        d1 = self._fetch_rates(sym, mt5.TIMEFRAME_D1, 60)
        w1 = self._fetch_rates(sym, mt5.TIMEFRAME_W1, 40)
        mn = self._fetch_rates(sym, mt5.TIMEFRAME_MN1, 20)

        # Prix = close de la dernière barre H1 avant scan_date
        # (Évite copy_rates_from qui va vers le futur = data leakage)
        if h1 is None:
            logger.debug(f"  {sym}: pas de données H1 pour {self.scan_date.date()}")
            return None
        price = h1[-1][3]  # close de la dernière barre H1 avant scan_date

        if not h1 or not h4 or not d1:
            logger.debug(f"  {sym}: données insuffisantes pour {self.scan_date.date()}")
            return None

        # Extract OHLC
        h1_h = [x[1] for x in h1]
        h1_l = [x[2] for x in h1]
        h4_h = [x[1] for x in h4]
        h4_l = [x[2] for x in h4]
        d1_h = [x[1] for x in d1]
        d1_l = [x[2] for x in d1]

        # ── Ichimoku levels ──
        kj_h1 = self._kj(h1_h, h1_l)
        kj_h4 = self._kj(h4_h, h4_l)
        kj_d1 = self._kj(d1_h, d1_l)
        tk_h1 = self._tk(h1_h, h1_l)
        tk_h4 = self._tk(h4_h, h4_l)
        tk_d1 = self._tk(d1_h, d1_l)

        # W1/MN if available
        kj_w1 = self._kj([x[1] for x in w1], [x[2] for x in w1]) if w1 else 0.0
        kj_mn = self._kj([x[1] for x in mn], [x[2] for x in mn]) if mn else 0.0
        tk_w1 = self._tk([x[1] for x in w1], [x[2] for x in w1]) if w1 else 0.0
        tk_mn = self._tk([x[1] for x in mn], [x[2] for x in mn]) if mn else 0.0

        # T/K crosses
        tkx_h1 = self._tkx(tk_h1, kj_h1)
        tkx_h4 = self._tkx(tk_h4, kj_h4)
        tkx_d1 = self._tkx(tk_d1, kj_d1)

        # Kumo positions
        kumo_h1 = self._kumo_pos(price, h1_h, h1_l)
        kumo_h4 = self._kumo_pos(price, h4_h, h4_l)
        kumo_d1 = self._kumo_pos(price, d1_h, d1_l)

        # Bias
        bias, alignment = self._determine_bias(
            price, kj_h1, kj_h4, kj_d1,
            tkx_h1, tkx_h4, tkx_d1,
            kumo_h1, kumo_h4, kumo_d1,
        )

        # SL / TP / RR
        sl, tp, rr = self._calculate_sl_tp(sym, price, bias, kj_h1, kj_h4, kj_d1)

        # Backtest outcome
        outcome = self._backtest_outcome(sym, self.scan_date, price, sl, tp, bias)

        # ── ICT Detection: FVG (H1/H4/D1) ──
        h1_closes = [x[3] for x in h1]
        h4_closes = [x[3] for x in h4]
        d1_closes = [x[3] for x in d1]

        fvg_h1 = self._detect_fvg_historical(h1_h, h1_l, price, scan_window=72)
        fvg_h4 = self._detect_fvg_historical(h4_h, h4_l, price, scan_window=48)
        fvg_d1 = self._detect_fvg_historical(d1_h, d1_l, price, scan_window=30)

        # ── ICT Detection: Order Blocks (H1/H4/D1) — TF-aware distance thresholds ──
        ob_h1_bear, ob_h1_bull = self._detect_ob_historical(h1_h, h1_l, h1_closes, price, min_dist_pct=0.002)
        ob_h4_bear, ob_h4_bull = self._detect_ob_historical(h4_h, h4_l, h4_closes, price, min_dist_pct=0.005)
        ob_d1_bear, ob_d1_bull = self._detect_ob_historical(d1_h, d1_l, d1_closes, price, min_dist_pct=0.01)

        # ── ICT Detection: Market Structure (H1/H4/D1) ──
        mss_h1 = self._detect_mss_historical(h1_h, h1_l, price)
        mss_h4 = self._detect_mss_historical(h4_h, h4_l, price)
        mss_d1 = self._detect_mss_historical(d1_h, d1_l, price)

        # ── Build DiamondResult-like object + extract_features ──
        max_score = 109
        score_pct = alignment / 9.0 if bias != "FLAT" else 0.0
        score = int(score_pct * max_score)

        # Distances aux Kijun/Tenkan en pips
        d_kj_h1 = _pips(sym, price, kj_h1) if kj_h1 > 0 else 0.0
        d_kj_h4 = _pips(sym, price, kj_h4) if kj_h4 > 0 else 0.0
        d_kj_d1 = _pips(sym, price, kj_d1) if kj_d1 > 0 else 0.0
        d_tk_h1 = _pips(sym, price, tk_h1) if tk_h1 > 0 else 0.0
        d_tk_h4 = _pips(sym, price, tk_h4) if tk_h4 > 0 else 0.0
        d_tk_d1 = _pips(sym, price, tk_d1) if tk_d1 > 0 else 0.0

        # Pseudo-result object avec tous les attributs que extract_features() lit
        # Valeurs par défaut 0.0/False/"N/A" pour ce qu'on ne peut pas calculer historiquement
        result = SimpleNamespace(
            symbol=sym, price=price, score=score, max_score=max_score,
            bias=bias, alignment=float(alignment),
            sl=sl, tp=tp, rr=rr,
            # ── Kijun (TOUS les TFs) ──
            kj_h1=kj_h1, kj_h4=kj_h4, kj_d1=kj_d1, kj_w1=kj_w1, kj_mn=kj_mn,
            kj_m30=0.0, kj_m15=0.0, kj_m5=0.0,
            d_kj_h1=d_kj_h1, d_kj_h4=d_kj_h4, d_kj_d1=d_kj_d1,
            d_kj_m30=0.0, d_kj_m15=0.0, d_kj_m5=0.0,
            # ── Tenkan (TOUS les TFs) ──
            tk_h1=tk_h1, tk_h4=tk_h4, tk_d1=tk_d1, tk_w1=tk_w1, tk_mn=tk_mn,
            tk_m30=0.0, tk_m15=0.0, tk_m5=0.0,
            d_tk_h1=d_tk_h1, d_tk_h4=d_tk_h4, d_tk_d1=d_tk_d1,
            d_tk_m30=0.0, d_tk_m15=0.0, d_tk_m5=0.0,
            # ── T/K crosses ──
            tkx_h1=tkx_h1, tkx_h4=tkx_h4, tkx_d1=tkx_d1,
            tkx_w1=self._tkx(tk_w1, kj_w1), tkx_mn=self._tkx(tk_mn, kj_mn),
            # ── Kumo ──
            kumo_h1=kumo_h1, kumo_h4=kumo_h4, kumo_d1=kumo_d1,
            kumo_w1="N/A", kumo_mn="N/A",
            # ── M5/M15/M30 crosses (pas calculables historiquement) ──
            kj_m30_cross_bear=False, kj_m30_cross_bull=False,
            kj_m15_cross_bear=False, kj_m15_cross_bull=False,
            kj_m5_cross_bear=False, kj_m5_cross_bull=False,
            tk_m30_cross_bear=False, tk_m30_cross_bull=False,
            tk_m15_cross_bear=False, tk_m15_cross_bull=False,
            tk_m5_cross_bear=False, tk_m5_cross_bull=False,
            # ── Flat bars ──
            flat_h1=0, flat_h4=0,
            # ── FVG (calculés historiquement) ──
            fvg_h1_bear_top=fvg_h1[0], fvg_h1_bear_bot=fvg_h1[1],
            fvg_h1_bear_mitigated_pct=fvg_h1[2],
            fvg_h1_bull_top=fvg_h1[3], fvg_h1_bull_bot=fvg_h1[4],
            fvg_h1_bull_mitigated_pct=fvg_h1[5],
            fvg_h4_bear_top=fvg_h4[0], fvg_h4_bear_bot=fvg_h4[1],
            fvg_h4_bear_mitigated_pct=fvg_h4[2],
            fvg_h4_bull_top=fvg_h4[3], fvg_h4_bull_bot=fvg_h4[4],
            fvg_h4_bull_mitigated_pct=fvg_h4[5],
            fvg_d1_bear_top=fvg_d1[0], fvg_d1_bear_bot=fvg_d1[1],
            fvg_d1_bear_mitigated_pct=fvg_d1[2],
            fvg_d1_bull_top=fvg_d1[3], fvg_d1_bull_bot=fvg_d1[4],
            fvg_d1_bull_mitigated_pct=fvg_d1[5],
            # M5/M15/M30 FVG restent a 0 (pas de donnees intraday)
            **{f"fvg_{tf}_{side}_top": 0.0 for tf in ["m30","m15","m5"] for side in ["bear","bull"]},
            **{f"fvg_{tf}_{side}_mitigated_pct": 100.0 for tf in ["m30","m15","m5"] for side in ["bear","bull"]},
            # ── OB (calculés historiquement) ──
            ob_h1_bear_level=ob_h1_bear, ob_h1_bull_level=ob_h1_bull,
            ob_h4_bear_level=ob_h4_bear, ob_h4_bull_level=ob_h4_bull,
            ob_d1_bear_level=ob_d1_bear, ob_d1_bull_level=ob_d1_bull,
            # ── Sweeps ──
            asian_high_swept=False, asian_low_swept=False,
            london_high_swept=False, london_low_swept=False,
            # ── Volume ──
            vol_hvn_h1=0.0, vol_lvn_h1=0.0,
            vol_hvn_h4=0.0, vol_lvn_h4=0.0,
            vol_hvn_d1=0.0, vol_lvn_d1=0.0,
            # ── MSS (calculés historiquement) ──
            mss_h1_regime=mss_h1[0], mss_h4_regime=mss_h4[0], mss_d1_regime=mss_d1[0],
            # ── Compression ──
            compression_pips=0.0,
        )

        # Extraire les 100+ features nommées via le vrai extract_features()
        feats = extract_features(result, scan_time=self.scan_date)

        # Ajouter la colonne outcome (cible ML)
        feats["outcome"] = float(outcome)

        return feats


def _features_to_row(feats: Dict[str, float], sym_str: str) -> Dict[str, float]:
    """Nettoie les features pour le CSV (supprime les métadonnées string)."""
    return {k: v for k, v in feats.items() if not k.startswith("_")}


def _sort_features(feats_list: List[Dict[str, float]]) -> List[str]:
    """Ordonne les colonnes : features d'abord, outcome en dernier."""
    if not feats_list:
        return ["outcome"]
    keys = list(feats_list[0].keys())
    # Mettre outcome en dernier
    if "outcome" in keys:
        keys.remove("outcome")
        keys.append("outcome")
    return keys


# ─── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="📜 Backtest Historique Diamond — Génération du dataset ML",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  # Test rapide (1 symbole, 2 jours)
  %(prog)s --symbols EURUSD --start 2026-07-01 --end 2026-07-03

  # Scan complet depuis janvier
  %(prog)s --output data/historical_dataset.csv

  # Scan 6 majeurs depuis mars
  %(prog)s --symbols EURUSD GBPUSD USDJPY AUDUSD USDCAD USDCHF --start 2026-03-01
        """,
    )
    parser.add_argument("--symbols", "-s", nargs="+", default=None,
                        help="Symboles à scanner (défaut: tous)")
    parser.add_argument("--start", default="2026-01-01",
                        help="Date de début (YYYY-MM-DD, défaut: 2026-01-01)")
    parser.add_argument("--end", default=None,
                        help="Date de fin (YYYY-MM-DD, défaut: aujourd'hui)")
    parser.add_argument("--output", "-o", default="data/historical_dataset.csv",
                        help="Fichier CSV de sortie (défaut: data/historical_dataset.csv)")
    parser.add_argument("--lookback", type=int, default=120,
                        help="Heures de lookback pour le backtest (défaut: 120 = 5 jours)")
    parser.add_argument("--max-days", type=int, default=0,
                        help="Nombre max de jours à scanner (0 = tous)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Logs détaillés")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # ── Résolution des paramètres ──
    symbols = args.symbols or DEFAULT_SYMBOLS
    start_dt = _parse_date(args.start)
    end_dt = _parse_date(args.end) if args.end else datetime.now(UTC).replace(hour=23, minute=59, second=59, tzinfo=UTC)

    # Limiter end_dt à hier (ne pas backtester aujourd'hui, pas de données futures)
    yesterday = (datetime.now(UTC) - timedelta(days=1)).replace(hour=23, minute=59, second=59, tzinfo=UTC)
    if end_dt > yesterday:
        end_dt = yesterday
        logger.info(f"📅 Fin limitée à hier : {end_dt.date()}")

    # Jours ouvrés
    days = _business_day_range(start_dt, end_dt)
    if args.max_days > 0:
        days = days[:args.max_days]

    logger.info(f"{'='*60}")
    logger.info(f"  📜 Backtest Historique Diamond")
    logger.info(f"{'='*60}")
    logger.info(f"  Période : {start_dt.date()} → {end_dt.date()}  ({len(days)} jours ouvrés)")
    logger.info(f"  Symboles: {len(symbols)}  ({', '.join(symbols)})")
    logger.info(f"  Lookback : {args.lookback}h")
    logger.info(f"  Sortie   : {args.output}")
    logger.info(f"{'='*60}")

    # ── Connexion MT5 ──
    logger.info("🔌 Connexion MT5...")
    if not mt5.initialize():
        logger.error("❌ Échec connexion MT5")
        return 1
    logger.info("✅ MT5 connecté")

    # Activer les symboles
    for sym in symbols:
        mt5.symbol_select(sym, True)

    # ── Boucle principale ──
    all_rows: List[Dict[str, float]] = []
    total_scans = len(days) * len(symbols)
    scanned = 0
    skipped = 0
    total_outcome_known = 0
    total_wins = 0
    total_losses = 0

    start_wall = _time.time()

    try:
        for day_idx, day in enumerate(days):
            day_ts = day.strftime("%Y-%m-%d")
            scanner = HistoricalDiamondScanner(symbols, day.replace(hour=23, minute=59, second=59, tzinfo=UTC))

            for sym_idx, sym in enumerate(symbols):
                scanned += 1
                progress = scanned / total_scans * 100
                elapsed = _time.time() - start_wall
                rate = scanned / max(elapsed, 1)

                if scanned % 10 == 0 or scanned == 1:
                    eta_min = (total_scans - scanned) / max(rate, 0.1) / 60
                    logger.info(
                        f"  [{scanned}/{total_scans} {progress:.0f}%] "
                        f"{day_ts} {sym:12s} "
                        f"| {rate:.1f} scans/s | ETA {eta_min:.0f}min"
                    )

                feats = scanner.scan_symbol(sym)
                if feats is None:
                    skipped += 1
                    continue

                # Outcome stats
                outcome = feats.get("outcome", -1)
                if outcome >= 0:
                    total_outcome_known += 1
                    if outcome == 1:
                        total_wins += 1
                    else:
                        total_losses += 1

                row = _features_to_row(feats, sym)
                all_rows.append(row)

                # Sauvegarde périodique (tous les 100 trades)
                if len(all_rows) % 100 == 0:
                    _write_csv(args.output, all_rows)
                    wr = total_wins / max(total_outcome_known, 1) * 100
                    logger.info(f"  💾 Checkpoint: {len(all_rows)} trades, "
                                f"{total_wins}W/{total_losses}L ({wr:.0f}%)")

    except KeyboardInterrupt:
        logger.warning("\n⏹️  Interruption utilisateur — sauvegarde partielle...")
    finally:
        mt5.shutdown()

    # ── Sauvegarde finale ──
    if all_rows:
        _write_csv(args.output, all_rows)
    else:
        logger.warning("⚠️  Aucune donnée générée.")

    # ── Rapport ──
    elapsed = _time.time() - start_wall
    win_rate = total_wins / max(total_outcome_known, 1) * 100

    logger.info(f"\n{'='*60}")
    logger.info(f"  📊 RAPPORT FINAL")
    logger.info(f"{'='*60}")
    logger.info(f"  Période    : {start_dt.date()} → {end_dt.date()} ({len(days)} jours)")
    logger.info(f"  Symboles   : {len(symbols)}")
    logger.info(f"  Scans      : {scanned}")
    logger.info(f"  Trades     : {len(all_rows)}")
    logger.info(f"  Ignorés    : {skipped}")
    logger.info(f"  Outcomes   : {total_outcome_known} connus "
                f"({total_wins}W / {total_losses}L)")
    logger.info(f"  Win rate   : {win_rate:.1f}%")
    logger.info(f"  Temps      : {elapsed/60:.1f}min ({scanned/max(elapsed,1):.1f} scans/s)")
    logger.info(f"  CSV        : {args.output}")
    logger.info(f"{'='*60}")

    return 0


def _write_csv(path: str, rows: List[Dict[str, float]]):
    """Écrit les données dans un CSV."""
    if not rows:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fieldnames = _sort_features(rows)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    logger.info(f"  💾 {len(rows)} trades → {path}")


if __name__ == "__main__":
    sys.exit(main())
