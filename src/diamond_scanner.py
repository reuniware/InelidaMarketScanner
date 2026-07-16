"""
Diamond Analysis Scanner — Module permanent d'analyse multi-TF Ichimoku complete.

Integration systematique de l'Etape 3b : detection des flat lines passees, presentes
et futures sur tous les timeframes (H1, H4, D1, W1, MN).

Etape 5 (W1) et Etape 7 (MN) ajoutees le 14/07/2026 :
- Nuage VISIBLE (shift de 26 periodes, pas la valeur future)
- Tenkan W1/MN historique (memoire institutionnelle)
- Double memoire (Tenkan MN plat = Kijun MN actuel)
- Compression multi-TF (Etape 7b)
- Alignement 5/5 TFs
- Scoring etendu a 12 criteres (incluant W1 et MN)

Usage:
    from diamond_scanner import DiamondScanner
    scanner = DiamondScanner(symbols)
    results = scanner.scan_all()
    for r in results:
        print(f"{r.symbol}: {r.score}/12 {r.bias} ({r.quality}) align={r.alignment}/5")
"""

import logging
import time as _time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import MetaTrader5 as mt5

logger = logging.getLogger("DiamondScanner")

UTC = timezone.utc

# ── Data structures ──────────────────────────────────────────────────

@dataclass
class TenkanFlatMemory:
    """Un niveau Tenkan historique plat agissant comme memoire institutionnelle."""
    level: float
    dist_pips: float
    duration: int          # nombre de barres du plat
    start_dt: datetime
    end_dt: datetime
    direction: str         # "RESISTANCE" ou "SUPPORT"
    source: str = "D1"     # "D1", "W1", "MN"

@dataclass
class DiamondResult:
    """Resultat d'analyse Diamond pour un symbole (19 criteres max + Etape 3b + W1/MN)."""
    symbol: str
    price: float
    score: int
    max_score: int = 12    # 12 si MN dispo, 10 sinon
    bias: str = "FLAT"     # "BULL", "BEAR", "FLAT"
    quality: str = "WAIT"  # "STRONG", "GOOD", "WAIT"
    alignment: int = 0     # 0-5 TFs alignes

    # Kijun values (TOUS les TFs)
    kj_h1: float = 0.0
    kj_h4: float = 0.0
    kj_d1: float = 0.0
    kj_w1: float = 0.0
    kj_mn: float = 0.0
    d_kj4: float = 0.0     # distance prix vs Kijun H4 en pips

    # Tenkan values (TOUS les TFs)
    tk_h1: float = 0.0
    tk_h4: float = 0.0
    tk_d1: float = 0.0
    tk_w1: float = 0.0
    tk_mn: float = 0.0

    # T/K crosses
    tkx_h1: str = "N/A"
    tkx_h4: str = "N/A"
    tkx_d1: str = "N/A"
    tkx_w1: str = "N/A"
    tkx_mn: str = "N/A"

    # Kumo (position: ABOVE/BELOW/INSIDE)
    kumo_h1: str = "N/A"
    kumo_h4: str = "N/A"
    kumo_d1: str = "N/A"
    kumo_w1: str = "N/A"
    kumo_mn: str = "N/A"

    # Nuage visible (top/bottom + couleur)
    cloud_w1_top: float = 0.0
    cloud_w1_bot: float = 0.0
    cloud_w1_color: str = "N/A"
    cloud_mn_top: float = 0.0
    cloud_mn_bot: float = 0.0
    cloud_mn_color: str = "N/A"

    # Flat bars (present)
    flat_h1: int = 0
    flat_h4: int = 0

    # Memory (past) — Etape 3b : Tenkan flat history (TOUS les TFs)
    tenkan_flat_h1: List[TenkanFlatMemory] = field(default_factory=list)
    tenkan_flat_h4: List[TenkanFlatMemory] = field(default_factory=list)
    tenkan_flats: List[TenkanFlatMemory] = field(default_factory=list)       # D1
    tenkan_flat_w1: List[TenkanFlatMemory] = field(default_factory=list)
    tenkan_flat_mn: List[TenkanFlatMemory] = field(default_factory=list)

    # SSB proximity (TOUS les TFs)
    ssb_h1: List[Tuple[float, float]] = field(default_factory=list)
    ssb_h4: List[Tuple[float, float]] = field(default_factory=list)
    ssb_proximity: List[Tuple[float, float]] = field(default_factory=list)   # backward compat (H4)
    ssb_d1: List[Tuple[float, float]] = field(default_factory=list)
    ssb_w1: List[Tuple[float, float]] = field(default_factory=list)
    ssb_mn: List[Tuple[float, float]] = field(default_factory=list)

    # Future Kumo projection (TOUS les TFs — 26 barres forward)
    cloud_fut_h1_top: float = 0.0
    cloud_fut_h1_bot: float = 0.0
    cloud_fut_h1_color: str = "N/A"
    cloud_fut_h1_flat: bool = False
    cloud_fut_h4_top: float = 0.0
    cloud_fut_h4_bot: float = 0.0
    cloud_fut_h4_color: str = "N/A"
    cloud_fut_h4_flat: bool = False
    cloud_fut_d1_top: float = 0.0
    cloud_fut_d1_bot: float = 0.0
    cloud_fut_d1_color: str = "N/A"
    cloud_fut_d1_flat: bool = False
    cloud_fut_w1_top: float = 0.0
    cloud_fut_w1_bot: float = 0.0
    cloud_fut_w1_color: str = "N/A"
    cloud_fut_w1_flat: bool = False
    cloud_fut_mn_top: float = 0.0
    cloud_fut_mn_bot: float = 0.0
    cloud_fut_mn_color: str = "N/A"
    cloud_fut_mn_flat: bool = False

    # Kijun flat history (past — TOUS les TFs)
    kijun_flats_h1: List[TenkanFlatMemory] = field(default_factory=list)
    kijun_flats_h4: List[TenkanFlatMemory] = field(default_factory=list)
    kijun_flats_d1: List[TenkanFlatMemory] = field(default_factory=list)
    kijun_flats_w1: List[TenkanFlatMemory] = field(default_factory=list)
    kijun_flats_mn: List[TenkanFlatMemory] = field(default_factory=list)

    # MN specifics
    months_vs_kj_mn: int = 0     # nb de mois consecutifs au-dessus/en-dessous
    double_memory: bool = False  # Tenkan MN historique == Kijun MN actuel

    # Compression (Etape 7b)
    compression_pips: float = 0.0
    compression_zone: str = ""

    # Distance Kijun D1 (confluence ICT x Ichimoku)
    d_kj_d1: float = 0.0     # distance prix vs Kijun D1 en pips

    # Distance Tenkan H4/D1 (support/resistance barrier)
    d_tk_h4: float = 0.0     # distance prix vs Tenkan H4 en pips
    d_tk_d1: float = 0.0     # distance prix vs Tenkan D1 en pips

    # FVG H1 recent — bearish (gap down, low[i] > high[i+2])
    fvg_h1_bear_top: float = 0.0
    fvg_h1_bear_bot: float = 0.0
    fvg_h1_bear_mitigated: bool = False
    fvg_h1_bear_price_pos: str = "N/A"  # "ABOVE", "BELOW", "INSIDE"
    fvg_h1_bear_date: str = ""          # "15/07 18h" format
    fvg_h1_bear_pip_factor: float = 10000.0

    # FVG H1 recent — bullish (gap up, high[i] < low[i+2])
    fvg_h1_bull_top: float = 0.0
    fvg_h1_bull_bot: float = 0.0
    fvg_h1_bull_mitigated: bool = False
    fvg_h1_bull_price_pos: str = "N/A"  # "ABOVE", "BELOW", "INSIDE"
    fvg_h1_bull_date: str = ""
    fvg_h1_bull_pip_factor: float = 10000.0

    # FVG H4 recent — bearish
    fvg_h4_bear_top: float = 0.0
    fvg_h4_bear_bot: float = 0.0
    fvg_h4_bear_mitigated: bool = False
    fvg_h4_bear_price_pos: str = "N/A"
    fvg_h4_bear_date: str = ""
    fvg_h4_bear_pip_factor: float = 10000.0

    # FVG H4 recent — bullish
    fvg_h4_bull_top: float = 0.0
    fvg_h4_bull_bot: float = 0.0
    fvg_h4_bull_mitigated: bool = False
    fvg_h4_bull_price_pos: str = "N/A"
    fvg_h4_bull_date: str = ""
    fvg_h4_bull_pip_factor: float = 10000.0

    # FVG D1 recent — bearish
    fvg_d1_bear_top: float = 0.0
    fvg_d1_bear_bot: float = 0.0
    fvg_d1_bear_mitigated: bool = False
    fvg_d1_bear_price_pos: str = "N/A"
    fvg_d1_bear_date: str = ""
    fvg_d1_bear_pip_factor: float = 10000.0

    # FVG D1 recent — bullish
    fvg_d1_bull_top: float = 0.0
    fvg_d1_bull_bot: float = 0.0
    fvg_d1_bull_mitigated: bool = False
    fvg_d1_bull_price_pos: str = "N/A"
    fvg_d1_bull_date: str = ""
    fvg_d1_bull_pip_factor: float = 10000.0

    # Trade setup
    sl: float = 0.0
    tp: float = 0.0
    rr: float = 0.0
    tp_label: str = ""      # Source du TP (ex: "Ext +2.618 AH", "Kj D1", "FVG H1 Bear")
    horizon: str = ""       # "Intraday", "Session", "Swing", "Position"

    # Asian Range (ICT extensions pour le TP)
    asian_high: float = 0.0
    asian_low: float = 0.0

    # Asian Range sweep detection (ICT liquidez sweep)
    asian_high_swept: bool = False
    asian_low_swept: bool = False
    asian_high_swept_at: float = 0.0     # epoch UTC
    asian_low_swept_at: float = 0.0      # epoch UTC
    asian_high_swept_session: str = ""   # "Asian", "London", "NY", etc.
    asian_low_swept_session: str = ""

    # London Range (LH/LL sweeps by NY)
    london_high: float = 0.0
    london_low: float = 0.0
    london_high_swept: bool = False
    london_low_swept: bool = False
    london_high_swept_at: float = 0.0
    london_low_swept_at: float = 0.0
    london_high_swept_session: str = ""
    london_low_swept_session: str = ""

    # Metadata
    criteria: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# ── Scanner ───────────────────────────────────────────────────────────

class DiamondScanner:
    """Scanner Diamond Analysis multi-symboles avec Etapes 3b, 5, 7, 7b integrees."""

    def __init__(self, symbols: Optional[List[str]] = None):
        self.symbols: List[str] = list(symbols or [])
        self._initialized = False

    # ── Public API ──

    def initialize(self) -> bool:
        """Initialise MT5 et active tous les symboles."""
        if not mt5.initialize():
            logger.error("MT5 initialization failed")
            return False
        for sym in self.symbols:
            mt5.symbol_select(sym, True)
        self._initialized = True
        return True

    def shutdown(self):
        """Ferme MT5."""
        if self._initialized:
            mt5.shutdown()
            self._initialized = False

    def scan_all(self) -> List[DiamondResult]:
        """Scan complet de tous les symboles avec Etapes 3b, 5, 7, 7b."""
        if not self._initialized:
            self.initialize()

        results = []
        for sym in self.symbols:
            r = self._scan_symbol(sym)
            if r is not None:
                results.append(r)

        results.sort(key=lambda x: (x.quality != "WAIT", x.score), reverse=True)
        return results

    def scan_symbol(self, symbol: str) -> Optional[DiamondResult]:
        """Scan d'un seul symbole."""
        if not self._initialized:
            self.initialize()
        return self._scan_symbol(symbol)

    # ── Helpers ──

    def _pips(self, sym: str, price: float, level: float) -> float:
        if sym == 'XAUUSD': return (price - level) * 10
        elif 'JPY' in sym: return (price - level) * 100
        elif 'DXY' in sym or 'USDX' in sym: return (price - level) * 100
        else: return (price - level) * 10000

    def _pct(self, price: float, level: float) -> float:
        return (price - level) / level * 100.0 if level else 0.0

    def _get_price(self, sym: str) -> Optional[float]:
        mt5.symbol_select(sym, True)
        t = mt5.symbol_info_tick(sym)
        return float(t.bid) if t else None

    def _get_rates(self, sym: str, tf: int, n: int) -> Optional[List[Tuple[int, float, float, float]]]:
        r = mt5.copy_rates_from_pos(sym, tf, 0, n)
        if r is None or len(r) < n:
            return None
        return [(int(x[0]), float(x[2]), float(x[3]), float(x[4])) for x in r]

    def _get_rates_min(self, sym: str, tf: int, min_bars: int, request_bars: int) -> Optional[List[Tuple[int, float, float, float]]]:
        """Fetch bars; return None if < min_bars available even after requesting request_bars."""
        r = mt5.copy_rates_from_pos(sym, tf, 0, request_bars)
        if r is None or len(r) < min_bars:
            return None
        return [(int(x[0]), float(x[2]), float(x[3]), float(x[4])) for x in r]

    @staticmethod
    def _session_for_epoch(epoch: float) -> str:
        """Determine la session ICT pour un epoch UTC.
        
        ICT session windows (UTC):
          - Asian  : 00:00 - 08:00
          - London : 08:00 - 13:00
          - NY Open: 13:00 - 16:00
          - NY     : 16:00 - 21:00
          - Off    : 21:00 - 00:00
        """
        h = (int(epoch) // 3600) % 24
        if 0 <= h < 8:
            return "Asian"
        if 8 <= h < 13:
            return "London"
        if 13 <= h < 16:
            return "NY Open"
        if 16 <= h < 21:
            return "NY"
        return "Off"

    @staticmethod
    def _bar_sweeps_high(b: tuple, level: float) -> bool:
        """Sweep ICT : mèche au-dessus + close en-dessous du niveau."""
        return b[1] > level and b[3] < level

    @staticmethod
    def _bar_sweeps_low(b: tuple, level: float) -> bool:
        """Sweep ICT : mèche en-dessous + close au-dessus du niveau."""
        return b[2] < level and b[3] > level

    def _detect_asian_range(self, sym: str, h1_data: Optional[List] = None) -> Tuple[float, float]:
        """Detecte l'Asian High et Asian Low sur H1 (session 00:00-08:00 UTC).

        🔧 Filtre par session_date pour ne pas inclure les barres asiatiques
        du jour precedent (24 dernieres H1 peuvent deborder sur hier).

        Si h1_data est fourni (deja charge par _scan_symbol), on l'utilise
        pour eviter un second appel a MT5.

        Returns:
            (AH, AL) — les deux a 0.0 si pas assez de barres.
        """
        session_date = _time.strftime("%Y-%m-%d", _time.gmtime())
        if h1_data is None:
            h1_data = self._get_rates(sym, mt5.TIMEFRAME_H1, 32)
        if h1_data is None:
            return (0.0, 0.0)

        ah = None
        al = None
        for bar in h1_data:
            dt = datetime.fromtimestamp(bar[0], UTC)
            bar_date = dt.strftime("%Y-%m-%d")
            if bar_date == session_date and dt.hour >= 0 and dt.hour < 8:
                h, l = bar[1], bar[2]
                if ah is None or h > ah:
                    ah = h
                if al is None or l < al:
                    al = l
        return (ah or 0.0, al or 0.0)

    def _detect_asian_sweeps(self, h1_data: List, asian_high: float, asian_low: float, session_date: str) -> Tuple[bool, bool, float, float, str, str]:
        """Detecte les sweeps AH/AL sur les barres H1 deja chargees.

        Scanne depuis la premiere barre asiatique du jour (00:00 UTC)
        jusqu'a la fin des donnees, pour detecter les sweeps ICT :
        - AH swept : high > AH ET close < AH
        - AL swept : low < AL ET close > AL

        Returns:
            (ah_swept, al_swept, ah_at, al_at, ah_session, al_session)
        """
        ah_swept = False
        al_swept = False
        ah_at = 0.0
        al_at = 0.0
        ah_session = ""
        al_session = ""

        if asian_high <= 0 or asian_low <= 0:
            return (False, False, 0.0, 0.0, "", "")

        for bar in h1_data:
            dt = datetime.fromtimestamp(bar[0], UTC)
            bar_date = dt.strftime("%Y-%m-%d")
            if bar_date != session_date:
                continue
            if not ah_swept and self._bar_sweeps_high(bar, asian_high):
                ah_swept = True
                ah_at = float(bar[0])
                ah_session = self._session_for_epoch(bar[0])
            if not al_swept and self._bar_sweeps_low(bar, asian_low):
                al_swept = True
                al_at = float(bar[0])
                al_session = self._session_for_epoch(bar[0])
            if ah_swept and al_swept:
                break

        return (ah_swept, al_swept, ah_at, al_at, ah_session, al_session)

    # ── London Range (LH/LL) detection ──

    def _detect_london_range(self, h1_data: List) -> Tuple[float, float]:
        """Detecte le London High et London Low sur H1 (session 08:00-13:00 UTC).

        Returns:
            (LH, LL) — les deux a 0.0 si pas assez de barres.
        """
        if not h1_data:
            return (0.0, 0.0)
        session_date = _time.strftime("%Y-%m-%d", _time.gmtime())
        lh = None
        ll = None
        for bar in h1_data:
            dt = datetime.fromtimestamp(bar[0], UTC)
            bar_date = dt.strftime("%Y-%m-%d")
            if bar_date == session_date and 8 <= dt.hour < 13:
                h, l = bar[1], bar[2]
                if lh is None or h > lh:
                    lh = h
                if ll is None or l < ll:
                    ll = l
        return (lh or 0.0, ll or 0.0)

    def _detect_london_sweeps(self, h1_data: List, london_high: float, london_low: float, session_date: str) -> Tuple[bool, bool, float, float, str, str]:
        """Detecte les sweeps LH/LL sur les barres H1 apres 13:00 UTC (NY).

        Scanne les barres NY (>= 13:00 UTC) pour detecter les sweeps ICT :
        - LH swept : high > LH ET close < LH
        - LL swept : low < LL ET close > LL

        Returns:
            (lh_swept, ll_swept, lh_at, ll_at, lh_session, ll_session)
        """
        lh_swept = False
        ll_swept = False
        lh_at = 0.0
        ll_at = 0.0
        lh_session = ""
        ll_session = ""

        if london_high <= 0 or london_low <= 0:
            return (False, False, 0.0, 0.0, "", "")

        for bar in h1_data:
            dt = datetime.fromtimestamp(bar[0], UTC)
            bar_date = dt.strftime("%Y-%m-%d")
            if bar_date != session_date:
                continue
            # Only scan NY session bars (>= 13:00 UTC)
            if dt.hour < 13:
                continue
            if not lh_swept and self._bar_sweeps_high(bar, london_high):
                lh_swept = True
                lh_at = float(bar[0])
                lh_session = self._session_for_epoch(bar[0])
            if not ll_swept and self._bar_sweeps_low(bar, london_low):
                ll_swept = True
                ll_at = float(bar[0])
                ll_session = self._session_for_epoch(bar[0])
            if lh_swept and ll_swept:
                break

        return (lh_swept, ll_swept, lh_at, ll_at, lh_session, ll_session)

    def _kj(self, highs: List[float], lows: List[float]) -> float:
        return (max(highs[-26:]) + min(lows[-26:])) / 2.0

    def _tk(self, highs: List[float], lows: List[float]) -> float:
        return (max(highs[-9:]) + min(lows[-9:])) / 2.0

    def _kumo_pos(self, price: float, highs: List[float], lows: List[float]) -> str:
        n = len(highs)
        if n < 78: return "N/A"
        idx = n - 27
        tk_v = (max(highs[idx-8:idx+1]) + min(lows[idx-8:idx+1])) / 2.0
        kj_v = (max(highs[idx-25:idx+1]) + min(lows[idx-25:idx+1])) / 2.0
        sa_v = (tk_v + kj_v) / 2.0
        sb_v = (max(highs[idx-51:idx+1]) + min(lows[idx-51:idx+1])) / 2.0
        ct, cb = max(sa_v, sb_v), min(sa_v, sb_v)
        return "ABOVE" if price > ct else ("BELOW" if price < cb else "INSIDE")

    def _kumo_visible(self, price: float, highs: List[float], lows: List[float]) -> Tuple[str, float, float, str]:
        """Kumo VISIBLE (shift de 26 periodes, pas la valeur future).
        Returns (position, cloud_top, cloud_bot, color)."""
        n = len(highs)
        if n < 78: return ("N/A", 0.0, 0.0, "N/A")
        idx = n - 27  # -26 bars from end
        if idx < 52: return ("N/A", 0.0, 0.0, "N/A")
        tk_v = (max(highs[idx-8:idx+1]) + min(lows[idx-8:idx+1])) / 2.0
        kj_v = (max(highs[idx-25:idx+1]) + min(lows[idx-25:idx+1])) / 2.0
        sa_v = (tk_v + kj_v) / 2.0
        sb_v = (max(highs[idx-51:idx+1]) + min(lows[idx-51:idx+1])) / 2.0
        ct, cb = max(sa_v, sb_v), min(sa_v, sb_v)
        color = "VERT" if sa_v > sb_v else "ROUGE"
        pos = "ABOVE" if price > ct else ("BELOW" if price < cb else "INSIDE")
        return (pos, ct, cb, color)

    def _flat_bars(self, highs: List[float], lows: List[float], max_bars: int = 100) -> int:
        if len(highs) < 27: return 0
        base = (max(highs[-26:]) + min(lows[-26:])) / 2.0
        vals = [base]
        for i in range(len(highs) - 27, max(len(highs) - max_bars - 26, 25), -1):
            k = (max(highs[i:i+26]) + min(lows[i:i+26])) / 2.0
            vals.append(k)
            if (max(vals) - min(vals)) / base * 100 > 0.05:
                break
        return len(vals) - 1

    # ── Etape 3b : Kumo FUTUR (projection +26 barres) ──

    def _kumo_future(self, highs: List[float], lows: List[float], sym: str = "") -> Tuple[float, float, str, bool]:
        """Calcule le Kumo FUTUR projete 26 barres en avant.
        Returns (cloud_top, cloud_bot, color, is_flat)."""
        n = len(highs)
        if n < 52:
            return (0.0, 0.0, "N/A", False)

        # Tenkan = (highest high + lowest low) / 2 sur 9 periodes
        tk_now = (max(highs[-9:]) + min(lows[-9:])) / 2.0
        # Kijun = idem sur 26 periodes
        kj_now = (max(highs[-26:]) + min(lows[-26:])) / 2.0
        # Senkou A = (Tenkan + Kijun) / 2, projete 26 barres forward
        sa_fut = (tk_now + kj_now) / 2.0
        # Senkou B = (highest high + lowest low) / 2 sur 52 periodes, projete 26 barres forward
        sb_fut = (max(highs[-52:]) + min(lows[-52:])) / 2.0

        ct, cb = max(sa_fut, sb_fut), min(sa_fut, sb_fut)
        color = "VERT" if sa_fut > sb_fut else "ROUGE"

        # Detection Kumo flat: Senkou B inchange depuis 3 barres
        is_flat = False
        if n >= 55:
            sb_prev = (max(highs[-55:-3]) + min(lows[-55:-3])) / 2.0
            # Use instrument-appropriate threshold (same pattern as Tenkan/Kijun detectors)
            thresh = 0.03 if sym == 'XAUUSD' or ('JPY' in sym) else 0.0003
            is_flat = abs(sb_fut - sb_prev) < thresh

        return ct, cb, color, is_flat

    # ── Etape 3b : Kijun flat history (zones d'equilibre historiques) ──

    def _detect_kijun_flat_history(
        self, highs: List[float], lows: List[float],
        timestamps: List[int], sym: str, price: float,
        max_pips: float = 80.0, source_label: str = "D1"
    ) -> List[TenkanFlatMemory]:
        """Detecte les Kijun plats historiques (zones d'equilibre majeures)."""
        n = len(highs)
        if n < 52:
            return []

        thresh = 0.03 if ('JPY' in sym or sym == 'XAUUSD') else 0.0003
        prev_kj = None
        current_flat: List[Tuple[datetime, float]] = []
        all_flats: List[List[Tuple[datetime, float]]] = []

        for i in range(25, n):
            kj = (max(highs[i-25:i+1]) + min(lows[i-25:i+1])) / 2.0
            dt = datetime.fromtimestamp(timestamps[i], UTC)
            if prev_kj is not None:
                if abs(kj - prev_kj) < thresh:
                    current_flat.append((dt, kj))
                else:
                    if len(current_flat) >= 2:
                        all_flats.append(current_flat)
                    current_flat = [(dt, kj)]
            else:
                current_flat = [(dt, kj)]
            prev_kj = kj
        if len(current_flat) >= 2:
            all_flats.append(current_flat)

        relevant: List[TenkanFlatMemory] = []
        for period in all_flats:
            vals = [p[1] for p in period]
            avg = sum(vals) / len(vals)
            dist = self._pips(sym, price, avg)
            if abs(dist) < max_pips and len(period) >= 2:
                relevant.append(TenkanFlatMemory(
                    level=avg, dist_pips=dist, duration=len(period),
                    start_dt=period[0][0], end_dt=period[-1][0],
                    direction="SUPPORT" if dist > 0 else "RESISTANCE",
                    source=source_label,
                ))
        return sorted(relevant, key=lambda x: abs(x.dist_pips))

    # ── Etape 3b : Tenkan flat history (generic TF) ──

    def _detect_tenkan_flat_history(
        self, highs: List[float], lows: List[float],
        timestamps: List[int], sym: str, price: float,
        max_pips: float = 80.0, source_label: str = "D1"
    ) -> List[TenkanFlatMemory]:
        """Detecte les Tenkan plats historiques sur n'importe quel TF."""
        n = len(highs)
        if n < 30: return []

        thresh = 0.03 if ('JPY' in sym or sym == 'XAUUSD') else 0.0003
        prev_tk = None
        current_flat: List[Tuple[datetime, float]] = []
        all_flats: List[List[Tuple[datetime, float]]] = []

        for i in range(8, n):
            t = (max(highs[i-8:i+1]) + min(lows[i-8:i+1])) / 2.0
            dt = datetime.fromtimestamp(timestamps[i], UTC)
            if prev_tk is not None:
                if abs(t - prev_tk) < thresh:
                    current_flat.append((dt, t))
                else:
                    if len(current_flat) >= 2:
                        all_flats.append(current_flat)
                    current_flat = [(dt, t)]
            else:
                current_flat = [(dt, t)]
            prev_tk = t
        if len(current_flat) >= 2:
            all_flats.append(current_flat)

        relevant: List[TenkanFlatMemory] = []
        for period in all_flats:
            vals = [p[1] for p in period]
            avg = sum(vals) / len(vals)
            dist = self._pips(sym, price, avg)
            if abs(dist) < max_pips and len(period) >= 2:
                relevant.append(TenkanFlatMemory(
                    level=avg, dist_pips=dist, duration=len(period),
                    start_dt=period[0][0], end_dt=period[-1][0],
                    direction="SUPPORT" if dist > 0 else "RESISTANCE",
                    source=source_label,
                ))
        return sorted(relevant, key=lambda x: abs(x.dist_pips))

    # ── SSB proximity ──

    def _detect_ssb_near(
        self, highs: List[float], lows: List[float],
        price: float, sym: str, max_pips: float = 5.0, shift: int = 0
    ) -> List[Tuple[float, float]]:
        """Trouve les SSB VISIBLES (décalés) dans les max_pips du prix.

        Args:
            shift: Décalage pour la projection Ichimoku.
                   Le SSB est projeté 26 périodes en avant sur le graphique.
                   Pour W1 et MN, shift=26 car la valeur visible aujourd'hui
                   a été calculée il y a 26 périodes (Piège #2).
                   Pour H1/H4/D1, shift=0 car le décalage est négligeable.
        """
        factor = 10 if sym == 'XAUUSD' else (100 if 'JPY' in sym else 10000)
        results: List[Tuple[float, float]] = []
        seen = set()
        n = len(highs)
        start = 52 + shift
        for i in range(start, n):
            # Visible SSB à la position i = SB calculé il y a 'shift' périodes
            sb_idx_end = i + 1 - shift
            sb_idx_start = i - 51 - shift
            if sb_idx_start < 0 or sb_idx_end > n:
                continue
            sb = (max(highs[sb_idx_start:sb_idx_end]) + min(lows[sb_idx_start:sb_idx_end])) / 2.0
            if sb == 0: continue
            dist = abs(price - sb) * factor
            if dist < max_pips:
                key = round(sb, 5)
                if key not in seen:
                    seen.add(key)
                    results.append((sb, dist))
        return sorted(results, key=lambda x: x[1])

    # ── FVG detection (bearish + bullish gaps) — generic TF ──

    def _detect_fvg(
        self, highs: List[float], lows: List[float],
        timestamps: List[int], price: float, sym: str,
        scan_window: int = 72, use_priority: bool = True, tf_label: str = "H1"
    ) -> Tuple[float, float, bool, str, str, float,
               float, float, bool, str, str, float]:
        """Detecte les FVGs bearish (low[i] > high[i+2]) et bullish (high[i] < low[i+2]).

        Pour H1, utilise un systeme de priorite (18h-20h Paris = 10, hier = 5).
        Pour les autres TFs, prend le plus recent.

        Returns 12 valeurs:
            bear_top, bear_bot, bear_mitigated, bear_pos, bear_date, bear_pip_factor,
            bull_top, bull_bot, bull_mitigated, bull_pos, bull_date, bull_pip_factor
        """
        n = len(highs)
        if n < 6:
            return (0.0, 0.0, False, "N/A", "", 10000.0,
                    0.0, 0.0, False, "N/A", "", 10000.0)

        thresh = 0.03 if ('JPY' in sym or sym == 'XAUUSD') else 0.0005
        tolerance = thresh / 2.0
        pip_factor = 10.0 if sym == 'XAUUSD' else (100.0 if 'JPY' in sym else 10000.0)

        # Date formatter: include hour for H1, just date for H4/D1
        if tf_label == "H1":
            date_fmt = "%d/%m %Hh"
        else:
            date_fmt = "%d/%m"

        best_bear: Optional[Tuple[int, float, float, str, int]] = None
        best_bull: Optional[Tuple[int, float, float, str, int]] = None
        max_idx = min(n, scan_window)

        for i in range(2, max_idx):
            dt_i = datetime.fromtimestamp(timestamps[i], UTC)
            dt_i2 = datetime.fromtimestamp(timestamps[i - 2], UTC)

            if use_priority:
                prev_h = dt_i2.hour
                # Priority: yesterday's 18h-20h Paris (16-18 UTC) gets 10, yesterday gets 5
                priority = 0
                if prev_h == 16 and dt_i.hour == 18:
                    priority = 10
                elif dt_i.day != datetime.now(UTC).day:
                    priority = 5
            else:
                # For H4/D1: just use reverse index as priority (most recent = highest)
                priority = max_idx - i

            # Bearish FVG: low[i-2] > high[i]
            if lows[i - 2] > highs[i] and (lows[i - 2] - highs[i]) > thresh:
                label = dt_i2.strftime(date_fmt)
                if best_bear is None or priority > best_bear[0]:
                    best_bear = (priority, lows[i - 2], highs[i], label, i)

            # Bullish FVG: high[i-2] < low[i]
            if highs[i - 2] < lows[i] and (lows[i] - highs[i - 2]) > thresh:
                label = dt_i2.strftime(date_fmt)
                if best_bull is None or priority > best_bull[0]:
                    best_bull = (priority, lows[i], highs[i - 2], label, i)

        # ── Resolve bearish FVG ──
        bear_top, bear_bot, bear_mitigated, bear_pos, bear_date = 0.0, 0.0, False, "N/A", ""
        if best_bear is not None:
            bear_top, bear_bot = best_bear[1], best_bear[2]
            bear_date = best_bear[3]
            fvg_idx = best_bear[4]
            bear_mitigated = False
            for k in range(fvg_idx + 1, n):
                if highs[k] >= bear_bot - tolerance:
                    bear_mitigated = True
                    break
            if not bear_mitigated and price >= bear_bot - tolerance:
                bear_mitigated = True
            if bear_bot > 0:
                if price > bear_top: bear_pos = "ABOVE"
                elif price < bear_bot: bear_pos = "BELOW"
                else: bear_pos = "INSIDE"

        # ── Resolve bullish FVG ──
        bull_top, bull_bot, bull_mitigated, bull_pos, bull_date = 0.0, 0.0, False, "N/A", ""
        if best_bull is not None:
            bull_top, bull_bot = best_bull[1], best_bull[2]
            bull_date = best_bull[3]
            fvg_idx = best_bull[4]
            bull_mitigated = False
            for k in range(fvg_idx + 1, n):
                if lows[k] <= bull_top + tolerance:
                    bull_mitigated = True
                    break
            if not bull_mitigated and price <= bull_top + tolerance:
                bull_mitigated = True
            if bull_bot > 0:
                if price > bull_top: bull_pos = "ABOVE"
                elif price < bull_bot: bull_pos = "BELOW"
                else: bull_pos = "INSIDE"

        return (bear_top, bear_bot, bear_mitigated, bear_pos, bear_date, pip_factor,
                bull_top, bull_bot, bull_mitigated, bull_pos, bull_date, pip_factor)

    # ── TP calculation based on real levels ──

    def _compute_tp(
        self, sym: str, price: float, sl: float, direction: int,
        kijuns: dict, tenkans: dict, fvgs_bear: list, fvgs_bull: list,
        ssbs: list, clouds: list, asian_high: float = 0.0, asian_low: float = 0.0
    ) -> Tuple[float, float, float, str]:
        """Calcule le TP optimal base sur les vrais niveaux techniques.

        Collecte Kijun, Tenkan, FVG, SSB, nuages, et extensions ICT (base sur AH/AL).
        Filtre par direction.
        Prend le niveau le plus proche qui donne RR >= 1.5.

        ICT Extensions (base sur AH):
          - Ext +1.272/+1.618/+2.0/+2.272/+2.618/+3.0/+3.618
          - Extension BEAR: AH - n × (AH - AL)  (projete vers le bas)
          - Extension BULL: AL + n × (AH - AL)  (projete vers le haut)

        Returns: (tp, risk, rr, tp_label)
        """
        pip_factor = 10.0 if sym == 'XAUUSD' else (100.0 if 'JPY' in sym else 10000.0)
        risk = abs(price - sl) * pip_factor  # in pip units
        min_tp_dist = risk * 1.5 / pip_factor  # minimum distance for RR>=1.5 (in price units)

        candidates: List[Tuple[float, str]] = []  # (level, label)

        # ICT Retracements + Extensions (base sur l'Asian Range)
        if asian_high > 0 and asian_low > 0:
            asi_range = asian_high - asian_low
            if asi_range > 0:
                # Retracements Fibo (targets courts, intra-range)
                for n_str, n in [("0.5", 0.5), ("0.618", 0.618), ("0.786", 0.786)]:
                    # Bear retracement (retour vers le range depuis AH)
                    ret_bear = asian_high - n * asi_range
                    if direction == -1 and ret_bear < price:
                        candidates.append((ret_bear, f"Ret {n_str} AH"))
                    # Bull retracement (retour vers le range depuis AL)
                    ret_bull = asian_low + n * asi_range
                    if direction == 1 and ret_bull > price:
                        candidates.append((ret_bull, f"Ret {n_str} AL"))
                # Extensions ICT (targets longs, au-dela du range)
                for n_str, n in [("+1.272", 1.272), ("+1.618", 1.618), ("+2.0", 2.0),
                                 ("+2.272", 2.272), ("+2.618", 2.618), ("+3.0", 3.0),
                                 ("+3.618", 3.618)]:
                    # Bear extension (base sur AH, projetee vers le bas)
                    ext_bear = asian_high - n * asi_range
                    if direction == -1 and ext_bear < price:
                        candidates.append((ext_bear, f"Ext {n_str} AH"))
                    # Bull extension (base sur AL, projetee vers le haut)
                    ext_bull = asian_low + n * asi_range
                    if direction == 1 and ext_bull > price:
                        candidates.append((ext_bull, f"Ext {n_str} AL"))

        # Kijuns (all TFs)
        for label, kj in [("Kj H1", kijuns.get('h1', 0)), ("Kj H4", kijuns.get('h4', 0)),
                          ("Kj D1", kijuns.get('d1', 0)), ("Kj W1", kijuns.get('w1', 0))]:
            if kj > 0 and ((direction == 1 and kj > price) or (direction == -1 and kj < price)):
                candidates.append((kj, label))

        # Tenkans (all TFs)
        for label, tk in [("Tk H1", tenkans.get('h1', 0)), ("Tk H4", tenkans.get('h4', 0)),
                          ("Tk D1", tenkans.get('d1', 0)), ("Tk W1", tenkans.get('w1', 0))]:
            if tk > 0 and ((direction == 1 and tk > price) or (direction == -1 and tk < price)):
                candidates.append((tk, label))

        # FVG levels (both bear and bull — just the relevant side)
        for fvg_data in fvgs_bear + fvgs_bull:
            if fvg_data[0] > 0 and fvg_data[1] > 0:
                top, bot, label = fvg_data[0], fvg_data[1], fvg_data[2]
                if direction == 1 and top > price:
                    candidates.append((top, f"FVG {label}"))
                elif direction == -1 and bot < price:
                    candidates.append((bot, f"FVG {label}"))

        # SSBs
        for sb_l, sb_d, sb_label in ssbs:
            if (direction == 1 and sb_l > price) or (direction == -1 and sb_l < price):
                candidates.append((sb_l, f"SSB {sb_label}"))

        # Clouds
        for c_top, c_bot, c_label in clouds:
            if c_top > 0:
                if direction == 1 and c_top > price:
                    candidates.append((c_top, f"Nuage {c_label}"))
                elif direction == -1 and c_bot < price:
                    candidates.append((c_bot, f"Nuage {c_label}"))

        if not candidates:
            # Fallback: fixed RR=2.0
            tp = price + (risk * 2.0) / pip_factor * direction
            return tp, risk, 2.0, "RR 2.0 (aucun niveau trouve)"

        # Sort by distance from price (closest first)
        candidates.sort(key=lambda x: abs(x[0] - price))

        # Find first level that meets min RR >= 1.5
        for level, label in candidates:
            dist = abs(level - price) * pip_factor
            rr = dist / risk if risk > 0 else 0
            if rr >= 1.5:
                return level, risk, round(rr, 1), label

        # No level meets RR>=1.5 — take the closest one anyway
        best_level, best_label = candidates[0]
        dist = abs(best_level - price) * pip_factor
        rr = dist / risk if risk > 0 else 0
        return best_level, risk, round(rr, 1), f"{best_label} (RR {rr:.1f})"

    # ── Etape 7b : Compression multi-TF ──

    def _detect_compression(self, r: DiamondResult, sym: str) -> Tuple[float, str]:
        """Detecte une compression entre support MN et resistance W1."""
        supports = []
        resistances = []

        # Support MN: Kijun MN
        if r.kj_mn > 0 and r.price > r.kj_mn:
            supports.append(("Kijun MN", r.kj_mn))
        # Support W1: Kijun W1
        if r.kj_w1 > 0 and r.price > r.kj_w1:
            supports.append(("Kijun W1", r.kj_w1))
        # Resistance W1: cloud top
        if r.cloud_w1_top > 0 and r.price < r.cloud_w1_top:
            resistances.append(("Top nuage W1", r.cloud_w1_top))
        # Resistance MN: Tenkan MN flat
        for f in r.tenkan_flat_mn:
            if f.direction == "RESISTANCE":
                resistances.append((f"Tenkan MN plat", f.level))

        if not supports or not resistances:
            return (0.0, "")

        nearest_support = max(supports, key=lambda x: x[1])
        nearest_resistance = min(resistances, key=lambda x: x[1])
        gap = self._pips(sym, nearest_resistance[1], nearest_support[1])

        if gap < 0:
            return (0.0, "")  # no compression, price outside bounds

        if gap < 100:
            desc = (f"COMPRESSION {gap:.0f}p: {nearest_support[0]} "
                    f"{nearest_support[1]:.5f} ← PRIX → {nearest_resistance[0]} "
                    f"{nearest_resistance[1]:.5f}")
            return (gap, desc)
        return (gap, "")

    # ── Core scan ──

    def _scan_symbol(self, sym: str) -> Optional[DiamondResult]:
        price = self._get_price(sym)
        if price is None: return None

        # ── H1, H4, D1 (requis) ──
        h1 = self._get_rates(sym, mt5.TIMEFRAME_H1, 120)
        h4 = self._get_rates(sym, mt5.TIMEFRAME_H4, 120)
        d1 = self._get_rates(sym, mt5.TIMEFRAME_D1, 200)
        if h1 is None or h4 is None or d1 is None:
            return None

        h1_h, h1_l = [x[1] for x in h1], [x[2] for x in h1]
        h4_h, h4_l = [x[1] for x in h4], [x[2] for x in h4]
        d1_h, d1_l = [x[1] for x in d1], [x[2] for x in d1]
        h1_t = [x[0] for x in h1]
        h4_t = [x[0] for x in h4]
        d1_t = [x[0] for x in d1]

        # ═══ Asian Range + Sweep detection (H1 deja charge) ═══════════════
        session_date = _time.strftime("%Y-%m-%d", _time.gmtime())
        asian_high, asian_low = self._detect_asian_range(sym, h1_data=h1)
        ah_swept, al_swept, ah_at, al_at, ah_sess, al_sess = self._detect_asian_sweeps(
            h1, asian_high, asian_low, session_date
        )

        # ═══ London Range + Sweep detection ══════════════════════════════
        london_high, london_low = self._detect_london_range(h1)
        lh_swept, ll_swept, lh_at, ll_at, lh_sess, ll_sess = self._detect_london_sweeps(
            h1, london_high, london_low, session_date
        )

        # ── Ichimoku H1/H4/D1 ──
        kj1, kj4, kd1 = self._kj(h1_h, h1_l), self._kj(h4_h, h4_l), self._kj(d1_h, d1_l)
        tk1, tk4, td1 = self._tk(h1_h, h1_l), self._tk(h4_h, h4_l), self._tk(d1_h, d1_l)

        kumo1 = self._kumo_pos(price, h1_h, h1_l)
        kumo4 = self._kumo_pos(price, h4_h, h4_l)
        kumod1 = self._kumo_pos(price, d1_h, d1_l)

        tkx1 = "BULL" if tk1 > kj1 else "BEAR"
        tkx4 = "BULL" if tk4 > kj4 else "BEAR"
        tkxd1 = "BULL" if td1 > kd1 else "BEAR"

        flat1 = self._flat_bars(h1_h, h1_l)
        flat4 = self._flat_bars(h4_h, h4_l)

        # ═══ Etape 3b: Tenkan flat history — TOUS les TFs ════════════════════
        tenkan_flat_h1 = self._detect_tenkan_flat_history(h1_h, h1_l, h1_t, sym, price, max_pips=30.0, source_label="H1")
        tenkan_flat_h4 = self._detect_tenkan_flat_history(h4_h, h4_l, h4_t, sym, price, max_pips=50.0, source_label="H4")
        tenkan_flats = self._detect_tenkan_flat_history(d1_h, d1_l, d1_t, sym, price, max_pips=80.0, source_label="D1")

        # ═══ Etape 3b: Kijun flat history — TOUS les TFs ═════════════════════
        kijun_flats_h1 = self._detect_kijun_flat_history(h1_h, h1_l, h1_t, sym, price, max_pips=30.0, source_label="H1")
        kijun_flats_h4 = self._detect_kijun_flat_history(h4_h, h4_l, h4_t, sym, price, max_pips=50.0, source_label="H4")
        kijun_flats_d1 = self._detect_kijun_flat_history(d1_h, d1_l, d1_t, sym, price, max_pips=150.0, source_label="D1")

        # ═══ Etape 3b: Kumo FUTUR — TOUS les TFs (H1/H4/D1) ══════════════════
        cf_h1_top, cf_h1_bot, cf_h1_color, cf_h1_flat = self._kumo_future(h1_h, h1_l, sym)
        cf_h4_top, cf_h4_bot, cf_h4_color, cf_h4_flat = self._kumo_future(h4_h, h4_l, sym)
        cf_d1_top, cf_d1_bot, cf_d1_color, cf_d1_flat = self._kumo_future(d1_h, d1_l, sym)

        # ═══ Etape 3b: SSB proximity — TOUS les TFs ══════════════════════════
        ssb_h1 = self._detect_ssb_near(h1_h, h1_l, price, sym)
        ssb_h4 = self._detect_ssb_near(h4_h, h4_l, price, sym)
        ssb_d1 = self._detect_ssb_near(d1_h, d1_l, price, sym)



        # ═══ Etape 5: W1 Analysis ═══════════════════════════════════════════
        kjw1 = 0.0
        tkw1 = 0.0
        tkxw1 = "N/A"
        kumow1 = "N/A"
        cloud_w1_top = 0.0
        cloud_w1_bot = 0.0
        cloud_w1_color = "N/A"
        tenkan_flat_w1: List[TenkanFlatMemory] = []
        cf_w1_top = cf_w1_bot = 0.0
        cf_w1_color = "N/A"
        cf_w1_flat = False
        kijun_flats_w1: List[TenkanFlatMemory] = []
        ssb_w1: List[Tuple[float, float]] = []
        w1_available = False

        w1 = self._get_rates_min(sym, mt5.TIMEFRAME_W1, 80, 100)
        if w1 is not None:
            w1_h, w1_l = [x[1] for x in w1], [x[2] for x in w1]
            w1_t = [x[0] for x in w1]
            kjw1 = self._kj(w1_h, w1_l)
            tkw1 = self._tk(w1_h, w1_l)
            tkxw1 = "BULL" if tkw1 > kjw1 else "BEAR"
            kumow1, cloud_w1_top, cloud_w1_bot, cloud_w1_color = self._kumo_visible(price, w1_h, w1_l)
            tenkan_flat_w1 = self._detect_tenkan_flat_history(w1_h, w1_l, w1_t, sym, price, max_pips=200.0, source_label="W1")
            cf_w1_top, cf_w1_bot, cf_w1_color, cf_w1_flat = self._kumo_future(w1_h, w1_l, sym)
            kijun_flats_w1 = self._detect_kijun_flat_history(w1_h, w1_l, w1_t, sym, price, max_pips=300.0, source_label="W1")
            ssb_w1 = self._detect_ssb_near(w1_h, w1_l, price, sym, max_pips=15.0, shift=26)
            w1_available = True

        # ═══ Etape 7: MN Analysis ════════════════════════════════════════════
        kjmn = 0.0
        tkxmn = "N/A"
        kumomn = "N/A"
        cloud_mn_top = 0.0
        cloud_mn_bot = 0.0
        cloud_mn_color = "N/A"
        tenkan_flat_mn: List[TenkanFlatMemory] = []
        cf_mn_top = cf_mn_bot = 0.0
        cf_mn_color = "N/A"
        cf_mn_flat = False
        kijun_flats_mn: List[TenkanFlatMemory] = []
        ssb_mn: List[Tuple[float, float]] = []
        months_vs_kj = 0
        double_memory = False
        mn_available = False

        mn = self._get_rates_min(sym, mt5.TIMEFRAME_MN1, 80, 120)
        if mn is not None:
            mn_h, mn_l = [x[1] for x in mn], [x[2] for x in mn]
            mn_c = [x[3] for x in mn]
            mn_t = [x[0] for x in mn]
            kjmn = self._kj(mn_h, mn_l)
            tkmn = self._tk(mn_h, mn_l)
            tkxmn = "BULL" if tkmn > kjmn else "BEAR"
            kumomn, cloud_mn_top, cloud_mn_bot, cloud_mn_color = self._kumo_visible(price, mn_h, mn_l)
            tenkan_flat_mn = self._detect_tenkan_flat_history(mn_h, mn_l, mn_t, sym, price, max_pips=500.0, source_label="MN")
            cf_mn_top, cf_mn_bot, cf_mn_color, cf_mn_flat = self._kumo_future(mn_h, mn_l, sym)
            kijun_flats_mn = self._detect_kijun_flat_history(mn_h, mn_l, mn_t, sym, price, max_pips=600.0, source_label="MN")
            ssb_mn = self._detect_ssb_near(mn_h, mn_l, price, sym, max_pips=30.0, shift=26)
            mn_available = True

            # Months vs Kijun MN
            months_vs_kj = 0
            if kjmn > 0:
                for i in range(len(mn_c) - 1, -1, -1):
                    c = mn_c[i]
                    if c > kjmn:
                        months_vs_kj += 1
                    else:
                        break

            # Double memory: Tenkan MN flat level == current Kijun MN
            for f in tenkan_flat_mn:
                if abs(f.level - kjmn) / kjmn * 100 < 0.05:
                    double_memory = True
                    break

        d_kj4 = self._pips(sym, price, kj4)

        # ═══ Kijun D1 distance ═══════════════════════════════════════════
        d_kj_d1 = self._pips(sym, price, kd1)

        # ═══ FVG detection — H1, H4, D1 ══════════════════════════════════
        fvg_top, fvg_bot, fvg_mitigated, fvg_pos, fvg_date, fvg_pip_factor, \
            fvg_bull_top, fvg_bull_bot, fvg_bull_mitigated, fvg_bull_pos, fvg_bull_date, fvg_bull_pip_factor = self._detect_fvg(
            h1_h, h1_l, h1_t, price, sym, scan_window=72, use_priority=True, tf_label="H1"
        )
        fvg4_top, fvg4_bot, fvg4_mitigated, fvg4_pos, fvg4_date, fvg4_pip_factor, \
            fvg4_bull_top, fvg4_bull_bot, fvg4_bull_mitigated, fvg4_bull_pos, fvg4_bull_date, fvg4_bull_pip_factor = self._detect_fvg(
            h4_h, h4_l, h4_t, price, sym, scan_window=48, use_priority=False, tf_label="H4"
        )
        fvg_d1_top, fvg_d1_bot, fvg_d1_mitigated, fvg_d1_pos, fvg_d1_date, fvg_d1_pip_factor, \
            fvg_d1_bull_top, fvg_d1_bull_bot, fvg_d1_bull_mitigated, fvg_d1_bull_pos, fvg_d1_bull_date, fvg_d1_bull_pip_factor = self._detect_fvg(
            d1_h, d1_l, d1_t, price, sym, scan_window=30, use_priority=False, tf_label="D1"
        )

        # ═══ Bias/Direction (computed BEFORE scoring) ════════════════════
        bias = "FLAT"
        direction = 0
        mn_bullish = mn_available and kjmn > 0 and price > kjmn
        mn_bearish = mn_available and kjmn > 0 and price < kjmn
        if d_kj4 > 5 and kumo4 == "ABOVE":
            if mn_bearish:
                bias = "FLAT"
            else:
                bias, direction = "BULL", 1
        elif d_kj4 < -5 and kumo4 == "BELOW":
            if mn_bullish:
                bias = "FLAT"
            else:
                bias, direction = "BEAR", -1

        # ═══ Scoring (25 criteres max avec TK4/TKd1/Kj4/KjD1 + Asian Sweep) ═══════════
        score = 0
        max_score = 27 if mn_available else 25
        crit: List[str] = []
        warnings: List[str] = []
        alignment = 0

        # H1 (2 criteres)
        if kumo1 == "ABOVE": score += 1; crit.append("H1Ku"); alignment += 1
        if tkx1 == "BULL": score += 1; crit.append("H1TK")
        # H4 (2 criteres)
        if kumo4 == "ABOVE": score += 1; crit.append("H4Ku"); alignment += 1
        if tkx4 == "BULL": score += 1; crit.append("H4TK")
        # D1 (2 criteres)
        if kumod1 == "ABOVE": score += 1; crit.append("D1Ku"); alignment += 1
        if tkxd1 == "BULL": score += 1; crit.append("D1TK")
        # Flat bars (2 criteres)
        if flat4 >= 8: score += 1; crit.append(f"Fl4({flat4}b)")
        if flat1 >= 8: score += 1; crit.append(f"Fl1({flat1}b)")
        # W1 (2 criteres) — Etape 5
        if w1_available:
            if kumow1 == "ABOVE": score += 1; crit.append("W1Ku"); alignment += 1
            if tkxw1 == "BULL": score += 1; crit.append("W1TK")
        # MN (2 criteres) — Etape 7
        if mn_available:
            if kumomn == "ABOVE": score += 1; crit.append("MNKu"); alignment += 1
            if tkxmn == "BULL": score += 1; crit.append("MNTK")
        # Tenkan/Kijun H4/D1 barrier (4 criteres) — S/R proximity
        d_tk_h4 = self._pips(sym, price, tk4)
        d_tk_d1 = self._pips(sym, price, td1)
        tk_h4_thresh = 20.0 if sym == 'XAUUSD' else (5.0 if 'JPY' in sym else 20.0)
        tk_d1_thresh = 40.0 if sym == 'XAUUSD' else (10.0 if 'JPY' in sym else 40.0)
        kj4_score_thresh = 30.0 if sym == 'XAUUSD' else (7.0 if 'JPY' in sym else 30.0)
        kj_d1_thresh = 50.0 if sym == 'XAUUSD' else (12.0 if 'JPY' in sym else 50.0)
        # TK4: Tenkan H4
        if tk4 > 0 and direction != 0 and abs(d_tk_h4) < tk_h4_thresh:
            if (direction == 1 and price > tk4) or (direction == -1 and price < tk4):
                score += 1; crit.append("TK4"); alignment += 1
        # TKd1: Tenkan D1
        if td1 > 0 and direction != 0 and abs(d_tk_d1) < tk_d1_thresh:
            if (direction == 1 and price > td1) or (direction == -1 and price < td1):
                score += 1; crit.append("TKd1"); alignment += 1
        # Kj4: Kijun H4 (reuses d_kj4 computed earlier)
        if kj4 > 0 and direction != 0 and abs(d_kj4) < kj4_score_thresh:
            if (direction == 1 and price > kj4) or (direction == -1 and price < kj4):
                score += 1; crit.append("Kj4"); alignment += 1
        # KjD1: Kijun D1 barrier (proximity-scored)
        if kd1 > 0 and direction != 0 and abs(d_kj_d1) < kj_d1_thresh:
            if (direction == 1 and price > kd1) or (direction == -1 and price < kd1):
                score += 1; crit.append("KjD1"); alignment += 1
        # FVG H1 (2 criteres max) — mitigated FVG acting as S/R
        if fvg_mitigated and fvg_pos in ("BELOW", "ABOVE") and direction != 0:
            if (direction == -1 and fvg_pos == "BELOW") or (direction == 1 and fvg_pos == "ABOVE"):
                score += 1; crit.append("FVG")
        if fvg_bull_mitigated and fvg_bull_pos in ("BELOW", "ABOVE") and direction != 0:
            if (direction == 1 and fvg_bull_pos == "ABOVE") or (direction == -1 and fvg_bull_pos == "BELOW"):
                score += 1; crit.append("FVGb")
        # FVG H4 (2 criteres max)
        if fvg4_mitigated and fvg4_pos in ("BELOW", "ABOVE") and direction != 0:
            if (direction == -1 and fvg4_pos == "BELOW") or (direction == 1 and fvg4_pos == "ABOVE"):
                score += 1; crit.append("FVG4")
        if fvg4_bull_mitigated and fvg4_bull_pos in ("BELOW", "ABOVE") and direction != 0:
            if (direction == 1 and fvg4_bull_pos == "ABOVE") or (direction == -1 and fvg4_bull_pos == "BELOW"):
                score += 1; crit.append("FVGb4")
        # FVG D1 (2 criteres max)
        if fvg_d1_mitigated and fvg_d1_pos in ("BELOW", "ABOVE") and direction != 0:
            if (direction == -1 and fvg_d1_pos == "BELOW") or (direction == 1 and fvg_d1_pos == "ABOVE"):
                score += 1; crit.append("FVGD1")
        if fvg_d1_bull_mitigated and fvg_d1_bull_pos in ("BELOW", "ABOVE") and direction != 0:
            if (direction == 1 and fvg_d1_bull_pos == "ABOVE") or (direction == -1 and fvg_d1_bull_pos == "BELOW"):
                score += 1; crit.append("FVGbD1")
        # Asian Sweep (2 criteres) — liquidez ICT sweep AH/AL
        if ah_swept:
            score += 1; crit.append(f"AH{ah_sess or ''}")
        if al_swept:
            score += 1; crit.append(f"AL\u00e9{al_sess or ''}")
        if ah_swept and al_swept:
            score += 1; crit.append("BOTH")
            alignment += 1
        elif ah_swept or al_swept:
            alignment += 1

        # London Sweep (2 criteres) — LH/LL sweeps par NY
        if lh_swept:
            score += 1; crit.append(f"LH{lh_sess or ''}")
        if ll_swept:
            score += 1; crit.append(f"LL\u00e9{ll_sess or ''}")
        if lh_swept and ll_swept:
            score += 1; crit.append("BOTHL")
            alignment += 1
        elif lh_swept or ll_swept:
            alignment += 1

        # ── Warnings (Etape 3b — TOUS les TFs) ──
        # Tenkan/Kijun barrier warnings (when price near but NOT aligned)
        if direction != 0:
            # Tenkan H4 resistance when BULL (price below TK)
            if direction == 1 and d_tk_h4 < 0 and abs(d_tk_h4) < tk_h4_thresh:
                warnings.append(f"Tenkan H4 RESIST {tk4:.5f} ({d_tk_h4:+.0f}p) — obstacle haussier")
            # Tenkan H4 support when BEAR (price above TK)
            if direction == -1 and d_tk_h4 > 0 and abs(d_tk_h4) < tk_h4_thresh:
                warnings.append(f"Tenkan H4 SUPPORT {tk4:.5f} ({d_tk_h4:+.0f}p) — obstacle baissier")
        # Tenkan D1 (always warn if close)
        if td1 > 0 and abs(d_tk_d1) < tk_d1_thresh:
            role = "RESIST" if price < td1 else "SUPPORT"
            if direction == 0 or (direction == 1 and price < td1) or (direction == -1 and price > td1):
                warnings.append(f"Tenkan D1 {role} {td1:.5f} ({d_tk_d1:+.0f}p)")
        # Kijun H4 always warn if close
        d_kj4_abs = abs(d_kj4)
        kj4_warn_thresh = 30.0 if sym == 'XAUUSD' else (3.0 if 'JPY' in sym else 30.0)
        if d_kj4_abs < kj4_warn_thresh and kj4 > 0:
            role = "RESIST" if price < kj4 else "SUPPORT"
            if direction == 0 or (direction == 1 and price < kj4) or (direction == -1 and price > kj4):
                warnings.append(f"Kijun H4 {role} {kj4:.5f} ({d_kj4:+.0f}p)")

        # FVG warnings (H1 + H4 + D1, bearish + bullish)
        for tf_name, fvg_t, fvg_b, fvg_m, fvg_p, fvg_d, fvg_pf, fvg_bt, fvg_bb, fvg_bm, fvg_bp, fvg_bd, fvg_bpf in [
            ("H1", fvg_top, fvg_bot, fvg_mitigated, fvg_pos, fvg_date, fvg_pip_factor,
             fvg_bull_top, fvg_bull_bot, fvg_bull_mitigated, fvg_bull_pos, fvg_bull_date, fvg_bull_pip_factor),
            ("H4", fvg4_top, fvg4_bot, fvg4_mitigated, fvg4_pos, fvg4_date, fvg4_pip_factor,
             fvg4_bull_top, fvg4_bull_bot, fvg4_bull_mitigated, fvg4_bull_pos, fvg4_bull_date, fvg4_bull_pip_factor),
            ("D1", fvg_d1_top, fvg_d1_bot, fvg_d1_mitigated, fvg_d1_pos, fvg_d1_date, fvg_d1_pip_factor,
             fvg_d1_bull_top, fvg_d1_bull_bot, fvg_d1_bull_mitigated, fvg_d1_bull_pos, fvg_d1_bull_date, fvg_d1_bull_pip_factor),
        ]:
            if fvg_t > 0 and fvg_b > 0:
                gap = abs(fvg_t - fvg_b) * fvg_pf
                mit = "MITIGE" if fvg_m else "NON MITIGE"
                warnings.append(
                    f"FVG {tf_name} BEAR {fvg_d}: {fvg_b:.5f}-{fvg_t:.5f} ({gap:.1f}p) [{mit}] [{fvg_p}]"
                )
            if fvg_bt > 0 and fvg_bb > 0:
                gap = abs(fvg_bt - fvg_bb) * fvg_bpf
                mit = "MITIGE" if fvg_bm else "NON MITIGE"
                warnings.append(
                    f"FVG {tf_name} BULL {fvg_bd}: {fvg_bb:.5f}-{fvg_bt:.5f} ({gap:.1f}p) [{mit}] [{fvg_bp}]"
                )
        # Tenkan flats proches (H1/H4/D1/W1/MN)
        for flats, label, threshold, unit in [
            (tenkan_flat_h1, "TenkanH1", 5, "b"),
            (tenkan_flat_h4, "TenkanH4", 10, "b"),
            (tenkan_flats, "TenkanD1", 10, "j"),
            (tenkan_flat_w1, "TenkanW1", 20, "sem"),
        ]:
            near = [f for f in flats if abs(f.dist_pips) < threshold]
            for nf in near[:2 if label == "TenkanD1" else 1]:
                warnings.append(
                    f"{label} {nf.direction} {nf.level:.5f} "
                    f"({nf.dist_pips:+.0f}p, {nf.duration}{unit})"
                )
        # Tenkan D1 penalty
        if tenkan_flats:
            near_d1 = [f for f in tenkan_flats if abs(f.dist_pips) < 10]
            if near_d1:
                score -= 1

        # Tenkan MN — double memory
        if double_memory:
            warnings.append(f"DOUBLE MEMOIRE: Tenkan MN plat = Kijun MN {kjmn:.5f}")

        # Kijun flat history warnings (H1/H4/D1/W1/MN)
        for flats, label, threshold, unit in [
            (kijun_flats_h1, "KijunH1", 5, "b"),
            (kijun_flats_h4, "KijunH4", 10, "b"),
            (kijun_flats_d1, "KijunD1", 20, "j"),
            (kijun_flats_w1, "KijunW1", 30, "sem"),
            (kijun_flats_mn, "KijunMN", 50, "mois"),
        ]:
            near = [f for f in flats if abs(f.dist_pips) < threshold]
            for nf in near[:1]:
                warnings.append(
                    f"{label} {nf.direction} {nf.level:.5f} "
                    f"({nf.dist_pips:+.0f}p, {nf.duration}{unit})"
                )

        # ── Confluence Kijun H1=H4 ──
        kj_h1h4_dist = self._pips(sym, kj1, kj4)
        if abs(kj_h1h4_dist) < 5.0 and kj1 > 0 and kj4 > 0:
            avg_kj = (kj1 + kj4) / 2.0
            if sym == 'XAUUSD':
                level_label = f"{avg_kj:.2f}"
            elif 'JPY' in sym:
                level_label = f"{avg_kj:.3f}"
            else:
                level_label = f"{avg_kj:.5f}"
            warnings.append(
                f"CONFLUENT KIJUN H1=H4: {level_label} "
                f"({abs(kj_h1h4_dist):.1f}p)"
            )

        # SSB proches (H1/H4/D1/W1/MN)
        for ssb_list, label in [
            (ssb_h1, "SSB H1"), (ssb_h4, "SSB H4"), (ssb_d1, "SSB D1"),
            (ssb_w1, "SSB W1"), (ssb_mn, "SSB MN"),
        ]:
            for sb_l, sb_d in ssb_list[:2 if label == "SSB H4" else 1]:
                warnings.append(f"{label} {sb_l:.5f} ({sb_d:.1f}p)")

        # Kumo futur (H1/H4/D1/W1/MN)
        for cf_color, cf_flat, kumo_current, label in [
            (cf_h1_color, cf_h1_flat, kumo1, "H1"),
            (cf_h4_color, cf_h4_flat, kumo4, "H4"),
            (cf_d1_color, cf_d1_flat, kumod1, "D1"),
            (cf_w1_color, cf_w1_flat, kumow1, "W1"),
            (cf_mn_color, cf_mn_flat, kumomn, "MN"),
        ]:
            if cf_color == "ROUGE" and kumo_current == "ABOVE":
                warnings.append(f"KUMO VIRAGE {label}: Nuage futur ROUGE (devient baissier)")
            if cf_flat and label in ("H4", "D1", "W1", "MN"):
                warnings.append(f"KUMO FLAT {label}: Senkou B projete plat → magnet")

        # ── MN conflict warning (bias already computed above) ──
        if bias == "FLAT":
            if direction == 0 and mn_bullish and d_kj4 < -5 and kumo4 == "BELOW":
                warnings.append(f"CONFLIT MN: Prix SUR Kijun MN {kjmn:.5f}")
            elif direction == 0 and mn_bearish and d_kj4 > 5 and kumo4 == "ABOVE":
                warnings.append(f"CONFLIT MN: Prix SOUS Kijun MN {kjmn:.5f}")

        # ── Quality thresholds ──
        good_threshold = max_score - 4
        strong_threshold = max_score - 2

        if direction != 0:
            sl = kj4
            # Compute TP from real technical levels (Kijun, Tenkan, FVG, SSB, cloud)
            kijun_dict = {'h1': kj1, 'h4': kj4, 'd1': kd1, 'w1': kjw1}
            tenkan_dict = {'h1': tk1, 'h4': tk4, 'd1': td1, 'w1': tkw1 if w1_available else 0.0}
            fvgs_bear = [(fvg_top, fvg_bot, 'H1 Bear'), (fvg4_top, fvg4_bot, 'H4 Bear'),
                         (fvg_d1_top, fvg_d1_bot, 'D1 Bear')]
            fvgs_bull = [(fvg_bull_top, fvg_bull_bot, 'H1 Bull'), (fvg4_bull_top, fvg4_bull_bot, 'H4 Bull'),
                         (fvg_d1_bull_top, fvg_d1_bull_bot, 'D1 Bull')]
            ssb_list = [(sb_l, sb_d, f'H4 #{i}') for i, (sb_l, sb_d) in enumerate(ssb_h4[:3])]
            ssb_list += [(sb_l, sb_d, f'D1 #{i}') for i, (sb_l, sb_d) in enumerate(ssb_d1[:2])]
            clouds = []
            if cloud_w1_top > 0: clouds.append((cloud_w1_top, cloud_w1_bot, 'W1'))
            if cloud_mn_top > 0: clouds.append((cloud_mn_top, cloud_mn_bot, 'MN'))
            # Detecter l'Asian Range pour les extensions ICT
            tp, risk, rr, tp_label = self._compute_tp(
                sym, price, sl, direction, kijun_dict, tenkan_dict,
                fvgs_bear, fvgs_bull, ssb_list, clouds,
                asian_high=asian_high, asian_low=asian_low
            )
            has_warnings = any("TenkanD1" in w for w in warnings)
            if score >= strong_threshold and not has_warnings:
                quality = "STRONG"
            elif score >= good_threshold:
                quality = "GOOD"
            else:
                quality = "WAIT"

            # ── SL proximity safety net ──
            # Degrades quality if price is too close to the stop loss.
            # Prevents the scanner from calling a trade STRONG/GOOD
            # when it's 3 pts away from being stopped out.
            if sl > 0 and tp > 0:
                total_range = abs(tp - sl)
                dist_to_sl = abs(price - sl)
                if total_range > 0:
                    sl_pct = dist_to_sl / total_range * 100
                    if sl_pct < 10:
                        warnings.append(
                            f"SL CRITIQUE: {dist_to_sl:.1f} du SL "
                            f"({sl_pct:.0f}% du range — trade force a WAIT)"
                        )
                        quality = "WAIT"
                    elif sl_pct < 20:
                        warnings.append(
                            f"SL PROCHE: {dist_to_sl:.1f} du SL "
                            f"({sl_pct:.0f}% du range)"
                        )
                        if quality == "STRONG": quality = "GOOD"
        else:
            sl = tp = rr = 0.0
            tp_label = ""
            quality = "WAIT"

        # ── Horizon de trading ──
        # Base sur l'alignement + Kumo (direction-agnostique : ABOVE ou BELOW = signal clair)
        clear_mn = mn_available and kumomn not in ("INSIDE", "N/A")
        clear_w1 = w1_available and kumow1 not in ("INSIDE", "N/A")
        clear_d1 = kumod1 not in ("INSIDE", "N/A")

        horizon = ""  # vide si aucun horizon clair
        if alignment >= 5 and clear_mn:
            horizon = "Position (semaines/mois)"
        elif alignment >= 4 and clear_w1:
            horizon = "Swing long (jours/semaines)"
        elif alignment >= 3 and clear_d1 and flat4 >= 8:
            horizon = "Swing (jours)"
        elif flat4 >= 8 and flat1 >= 8:
            horizon = "Session (heures)"
        elif flat1 >= 8:
            horizon = "Intraday (minutes/heures)"

        # ── Etape 7b: Compression ──
        r = DiamondResult(
            symbol=sym, price=price, score=score, max_score=max_score,
            bias=bias, quality=quality, alignment=alignment,
            kj_h1=kj1, kj_h4=kj4, kj_d1=kd1, kj_w1=kjw1, kj_mn=kjmn, d_kj4=d_kj4,
            tk_h1=tk1, tk_h4=tk4, tk_d1=td1, tk_w1=tkw1 if w1_available else 0.0, tk_mn=tkmn if mn_available else 0.0,
            tkx_h1=tkx1, tkx_h4=tkx4, tkx_d1=tkxd1, tkx_w1=tkxw1, tkx_mn=tkxmn,
            kumo_h1=kumo1, kumo_h4=kumo4, kumo_d1=kumod1, kumo_w1=kumow1, kumo_mn=kumomn,
            cloud_w1_top=cloud_w1_top, cloud_w1_bot=cloud_w1_bot, cloud_w1_color=cloud_w1_color,
            cloud_mn_top=cloud_mn_top, cloud_mn_bot=cloud_mn_bot, cloud_mn_color=cloud_mn_color,
            flat_h1=flat1, flat_h4=flat4,
            tenkan_flat_h1=tenkan_flat_h1, tenkan_flat_h4=tenkan_flat_h4,
            tenkan_flats=tenkan_flats, tenkan_flat_w1=tenkan_flat_w1, tenkan_flat_mn=tenkan_flat_mn,
            ssb_h1=ssb_h1, ssb_h4=ssb_h4, ssb_proximity=ssb_h4,
            ssb_d1=ssb_d1, ssb_w1=ssb_w1, ssb_mn=ssb_mn,
            cloud_fut_h1_top=cf_h1_top, cloud_fut_h1_bot=cf_h1_bot, cloud_fut_h1_color=cf_h1_color, cloud_fut_h1_flat=cf_h1_flat,
            cloud_fut_h4_top=cf_h4_top, cloud_fut_h4_bot=cf_h4_bot, cloud_fut_h4_color=cf_h4_color, cloud_fut_h4_flat=cf_h4_flat,
            cloud_fut_d1_top=cf_d1_top, cloud_fut_d1_bot=cf_d1_bot, cloud_fut_d1_color=cf_d1_color, cloud_fut_d1_flat=cf_d1_flat,
            cloud_fut_w1_top=cf_w1_top, cloud_fut_w1_bot=cf_w1_bot, cloud_fut_w1_color=cf_w1_color, cloud_fut_w1_flat=cf_w1_flat,
            cloud_fut_mn_top=cf_mn_top, cloud_fut_mn_bot=cf_mn_bot, cloud_fut_mn_color=cf_mn_color, cloud_fut_mn_flat=cf_mn_flat,
            kijun_flats_h1=kijun_flats_h1, kijun_flats_h4=kijun_flats_h4, kijun_flats_d1=kijun_flats_d1,
            kijun_flats_w1=kijun_flats_w1, kijun_flats_mn=kijun_flats_mn,
            months_vs_kj_mn=months_vs_kj, double_memory=double_memory,
            d_kj_d1=d_kj_d1,
            d_tk_h4=d_tk_h4, d_tk_d1=d_tk_d1,
            fvg_h1_bear_top=fvg_top, fvg_h1_bear_bot=fvg_bot,
            fvg_h1_bear_mitigated=fvg_mitigated, fvg_h1_bear_price_pos=fvg_pos,
            fvg_h1_bear_date=fvg_date, fvg_h1_bear_pip_factor=fvg_pip_factor,
            fvg_h1_bull_top=fvg_bull_top, fvg_h1_bull_bot=fvg_bull_bot,
            fvg_h1_bull_mitigated=fvg_bull_mitigated, fvg_h1_bull_price_pos=fvg_bull_pos,
            fvg_h1_bull_date=fvg_bull_date, fvg_h1_bull_pip_factor=fvg_bull_pip_factor,
            fvg_h4_bear_top=fvg4_top, fvg_h4_bear_bot=fvg4_bot,
            fvg_h4_bear_mitigated=fvg4_mitigated, fvg_h4_bear_price_pos=fvg4_pos,
            fvg_h4_bear_date=fvg4_date, fvg_h4_bear_pip_factor=fvg4_pip_factor,
            fvg_h4_bull_top=fvg4_bull_top, fvg_h4_bull_bot=fvg4_bull_bot,
            fvg_h4_bull_mitigated=fvg4_bull_mitigated, fvg_h4_bull_price_pos=fvg4_bull_pos,
            fvg_h4_bull_date=fvg4_bull_date, fvg_h4_bull_pip_factor=fvg4_bull_pip_factor,
            fvg_d1_bear_top=fvg_d1_top, fvg_d1_bear_bot=fvg_d1_bot,
            fvg_d1_bear_mitigated=fvg_d1_mitigated, fvg_d1_bear_price_pos=fvg_d1_pos,
            fvg_d1_bear_date=fvg_d1_date, fvg_d1_bear_pip_factor=fvg_d1_pip_factor,
            fvg_d1_bull_top=fvg_d1_bull_top, fvg_d1_bull_bot=fvg_d1_bull_bot,
            fvg_d1_bull_mitigated=fvg_d1_bull_mitigated, fvg_d1_bull_price_pos=fvg_d1_bull_pos,
            fvg_d1_bull_date=fvg_d1_bull_date, fvg_d1_bull_pip_factor=fvg_d1_bull_pip_factor,
            asian_high=asian_high, asian_low=asian_low,
            asian_high_swept=ah_swept, asian_low_swept=al_swept,
            asian_high_swept_at=ah_at, asian_low_swept_at=al_at,
            asian_high_swept_session=ah_sess, asian_low_swept_session=al_sess,
            london_high=london_high, london_low=london_low,
            london_high_swept=lh_swept, london_low_swept=ll_swept,
            london_high_swept_at=lh_at, london_low_swept_at=ll_at,
            london_high_swept_session=lh_sess, london_low_swept_session=ll_sess,
            sl=sl, tp=tp, rr=rr, tp_label=tp_label, horizon=horizon,
            criteria=crit, warnings=warnings,
        )

        compression_pips, compression_zone = self._detect_compression(r, sym)
        r.compression_pips = compression_pips
        r.compression_zone = compression_zone

        return r


# ── DXY helpers ──

def get_dxy_price() -> Optional[float]:
    """Recupere le prix du DXY (essaye plusieurs variantes de symbole)."""
    mt5.initialize()
    for sym in ['DXY.cash', 'DXY', 'USDX']:
        mt5.symbol_select(sym, True)
        t = mt5.symbol_info_tick(sym)
        if t:
            return float(t.bid)
    return None


def get_dxy_kijun_h1() -> Optional[float]:
    """Kijun H1 du DXY."""
    mt5.initialize()
    for sym in ['DXY.cash', 'DXY', 'USDX']:
        mt5.symbol_select(sym, True)
        r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 60)
        if r is not None and len(r) >= 27:
            h = [float(x[2]) for x in r]
            l = [float(x[3]) for x in r]
            return (max(h[-26:]) + min(l[-26:])) / 2.0
    return None
