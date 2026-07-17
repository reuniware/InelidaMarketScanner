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
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

import MetaTrader5 as mt5

from src.config import tz_offset as _tz_off, tz_label as _tz_lbl, DEFAULT_TZ_MODE
from src.news_calendar import get_news_risk

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
    kj_m30: float = 0.0    # Kijun M30 (cross detection)
    kj_h4: float = 0.0
    kj_d1: float = 0.0
    kj_w1: float = 0.0
    kj_mn: float = 0.0
    d_kj4: float = 0.0     # distance prix vs Kijun H4 en pips

    # M30 Kijun/Tenkan cross detection
    kj_m30_cross_bear: bool = False
    kj_m30_cross_bull: bool = False
    d_kj_m30: float = 0.0
    tk_m30: float = 0.0
    tk_m30_cross_bear: bool = False
    tk_m30_cross_bull: bool = False
    d_tk_m30: float = 0.0

    # M15 Kijun/Tenkan cross detection
    kj_m15: float = 0.0
    kj_m15_cross_bear: bool = False
    kj_m15_cross_bull: bool = False
    d_kj_m15: float = 0.0
    tk_m15: float = 0.0
    tk_m15_cross_bear: bool = False
    tk_m15_cross_bull: bool = False
    d_tk_m15: float = 0.0

    # M5 Kijun/Tenkan cross detection
    kj_m5: float = 0.0
    kj_m5_cross_bear: bool = False
    kj_m5_cross_bull: bool = False
    d_kj_m5: float = 0.0
    tk_m5: float = 0.0
    tk_m5_cross_bear: bool = False
    tk_m5_cross_bull: bool = False
    d_tk_m5: float = 0.0

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

    # ── ML prediction ──
    ml_win_pct: Optional[float] = None  # probabilité de trade gagnant (0.0 → 1.0), None si modèle non chargé

    # Distance Kijun D1 (confluence ICT x Ichimoku)
    d_kj_d1: float = 0.0     # distance prix vs Kijun D1 en pips

    # Distance Tenkan H4/D1 (support/resistance barrier)
    d_tk_h4: float = 0.0     # distance prix vs Tenkan H4 en pips
    d_tk_d1: float = 0.0     # distance prix vs Tenkan D1 en pips

    # FVG H1 recent — bearish (gap down, low[i] > high[i+2])
    fvg_h1_bear_top: float = 0.0
    fvg_h1_bear_bot: float = 0.0
    fvg_h1_bear_mitigated_pct: float = 0.0
    fvg_h1_bear_price_pos: str = "N/A"  # "ABOVE", "BELOW", "INSIDE"
    fvg_h1_bear_date: str = ""          # "15/07 18h" format
    fvg_h1_bear_pip_factor: float = 10000.0

    # FVG H1 recent — bullish (gap up, high[i] < low[i+2])
    fvg_h1_bull_top: float = 0.0
    fvg_h1_bull_bot: float = 0.0
    fvg_h1_bull_mitigated_pct: float = 0.0
    fvg_h1_bull_price_pos: str = "N/A"  # "ABOVE", "BELOW", "INSIDE"
    fvg_h1_bull_date: str = ""
    fvg_h1_bull_pip_factor: float = 10000.0

    # FVG H4 recent — bearish
    fvg_h4_bear_top: float = 0.0
    fvg_h4_bear_bot: float = 0.0
    fvg_h4_bear_mitigated_pct: float = 0.0
    fvg_h4_bear_price_pos: str = "N/A"
    fvg_h4_bear_date: str = ""
    fvg_h4_bear_pip_factor: float = 10000.0

    # FVG H4 recent — bullish
    fvg_h4_bull_top: float = 0.0
    fvg_h4_bull_bot: float = 0.0
    fvg_h4_bull_mitigated_pct: float = 0.0
    fvg_h4_bull_price_pos: str = "N/A"
    fvg_h4_bull_date: str = ""
    fvg_h4_bull_pip_factor: float = 10000.0

    # FVG D1 recent — bearish
    fvg_d1_bear_top: float = 0.0
    fvg_d1_bear_bot: float = 0.0
    fvg_d1_bear_mitigated_pct: float = 0.0
    fvg_d1_bear_price_pos: str = "N/A"
    fvg_d1_bear_date: str = ""
    fvg_d1_bear_pip_factor: float = 10000.0

    # FVG D1 recent — bullish
    fvg_d1_bull_top: float = 0.0
    fvg_d1_bull_bot: float = 0.0
    fvg_d1_bull_mitigated_pct: float = 0.0
    fvg_d1_bull_price_pos: str = "N/A"
    fvg_d1_bull_date: str = ""
    fvg_d1_bull_pip_factor: float = 10000.0

    # Order Blocks (OB) ICT — H1
    ob_h1_bear_level: float = 0.0
    ob_h1_bear_pos: str = "N/A"     # "ABOVE", "BELOW", "AT"
    ob_h1_bear_mitigated: bool = False
    ob_h1_bull_level: float = 0.0
    ob_h1_bull_pos: str = "N/A"     # "ABOVE", "BELOW", "AT"
    ob_h1_bull_mitigated: bool = False

    # Order Blocks (OB) ICT — H4
    ob_h4_bear_level: float = 0.0
    ob_h4_bear_pos: str = "N/A"
    ob_h4_bear_mitigated: bool = False
    ob_h4_bull_level: float = 0.0
    ob_h4_bull_pos: str = "N/A"
    ob_h4_bull_mitigated: bool = False

    # Order Blocks (OB) ICT — D1
    ob_d1_bear_level: float = 0.0
    ob_d1_bear_pos: str = "N/A"
    ob_d1_bear_mitigated: bool = False
    ob_d1_bull_level: float = 0.0
    ob_d1_bull_pos: str = "N/A"
    ob_d1_bull_mitigated: bool = False

    # Market Structure (MSS/BOS) ICT — H1
    mss_h1_regime: str = "N/A"       # "BULL", "BEAR", "RANGE"
    mss_h1_bos: str = "N/A"          # "BULL", "BEAR", "N/A"
    mss_h1_shift: str = "N/A"        # "BULL", "BEAR", "N/A"

    # Market Structure (MSS/BOS) ICT — H4
    mss_h4_regime: str = "N/A"
    mss_h4_bos: str = "N/A"
    mss_h4_shift: str = "N/A"

    # Market Structure (MSS/BOS) ICT — D1
    mss_d1_regime: str = "N/A"
    mss_d1_bos: str = "N/A"
    mss_d1_shift: str = "N/A"

    # Volume analysis (HVN/LVN + spike)
    vol_avg_h1: float = 0.0       # volume moyen H1
    vol_spike_h1: bool = False    # volume spike sur la derniere barre H1
    vol_hvn_h1: float = 0.0       # plus proche niveau HVN H1
    vol_lvn_h1: float = 0.0       # plus proche niveau LVN H1
    vol_avg_h4: float = 0.0
    vol_spike_h4: bool = False
    vol_hvn_h4: float = 0.0
    vol_lvn_h4: float = 0.0
    vol_avg_d1: float = 0.0
    vol_spike_d1: bool = False
    vol_hvn_d1: float = 0.0
    vol_lvn_d1: float = 0.0

    # Breaker Blocks (OB inverse) — H1/H4/D1
    brk_h1_bear_level: float = 0.0   # Ancien Bull OB cassé → résistance
    brk_h1_bull_level: float = 0.0   # Ancien Bear OB cassé → support
    brk_h4_bear_level: float = 0.0
    brk_h4_bull_level: float = 0.0
    brk_d1_bear_level: float = 0.0
    brk_d1_bull_level: float = 0.0

    # ── FVG M5/M15/M30 ──
    fvg_m5_bear_top: float = 0.0
    fvg_m5_bear_bot: float = 0.0
    fvg_m5_bear_mitigated_pct: float = 0.0
    fvg_m5_bear_price_pos: str = "N/A"
    fvg_m5_bear_date: str = ""
    fvg_m5_bull_top: float = 0.0
    fvg_m5_bull_bot: float = 0.0
    fvg_m5_bull_mitigated_pct: float = 0.0
    fvg_m5_bull_price_pos: str = "N/A"
    fvg_m5_bull_date: str = ""
    fvg_m5_pip_factor: float = 10000.0
    fvg_m15_bear_top: float = 0.0
    fvg_m15_bear_bot: float = 0.0
    fvg_m15_bear_mitigated_pct: float = 0.0
    fvg_m15_bear_price_pos: str = "N/A"
    fvg_m15_bear_date: str = ""
    fvg_m15_bull_top: float = 0.0
    fvg_m15_bull_bot: float = 0.0
    fvg_m15_bull_mitigated_pct: float = 0.0
    fvg_m15_bull_price_pos: str = "N/A"
    fvg_m15_bull_date: str = ""
    fvg_m15_pip_factor: float = 10000.0
    fvg_m30_bear_top: float = 0.0
    fvg_m30_bear_bot: float = 0.0
    fvg_m30_bear_mitigated_pct: float = 0.0
    fvg_m30_bear_price_pos: str = "N/A"
    fvg_m30_bear_date: str = ""
    fvg_m30_bull_top: float = 0.0
    fvg_m30_bull_bot: float = 0.0
    fvg_m30_bull_mitigated_pct: float = 0.0
    fvg_m30_bull_price_pos: str = "N/A"
    fvg_m30_bull_date: str = ""
    fvg_m30_pip_factor: float = 10000.0

    # ── OB M5/M15/M30 ──
    ob_m5_bear_level: float = 0.0
    ob_m5_bear_pos: str = "N/A"
    ob_m5_bear_mitigated: bool = False
    ob_m5_bull_level: float = 0.0
    ob_m5_bull_pos: str = "N/A"
    ob_m5_bull_mitigated: bool = False
    ob_m15_bear_level: float = 0.0
    ob_m15_bear_pos: str = "N/A"
    ob_m15_bear_mitigated: bool = False
    ob_m15_bull_level: float = 0.0
    ob_m15_bull_pos: str = "N/A"
    ob_m15_bull_mitigated: bool = False
    ob_m30_bear_level: float = 0.0
    ob_m30_bear_pos: str = "N/A"
    ob_m30_bear_mitigated: bool = False
    ob_m30_bull_level: float = 0.0
    ob_m30_bull_pos: str = "N/A"
    ob_m30_bull_mitigated: bool = False

    # ── MSS M5/M15/M30 ──
    mss_m5_regime: str = "N/A"
    mss_m5_bos: str = "N/A"
    mss_m5_shift: str = "N/A"
    mss_m15_regime: str = "N/A"
    mss_m15_bos: str = "N/A"
    mss_m15_shift: str = "N/A"
    mss_m30_regime: str = "N/A"
    mss_m30_bos: str = "N/A"
    mss_m30_shift: str = "N/A"

    # ── Volume M5/M15/M30 ──
    vol_avg_m5: float = 0.0
    vol_spike_m5: bool = False
    vol_hvn_m5: float = 0.0
    vol_lvn_m5: float = 0.0
    vol_avg_m15: float = 0.0
    vol_spike_m15: bool = False
    vol_hvn_m15: float = 0.0
    vol_lvn_m15: float = 0.0
    vol_avg_m30: float = 0.0
    vol_spike_m30: bool = False
    vol_hvn_m30: float = 0.0
    vol_lvn_m30: float = 0.0

    # ── BRK M5/M15/M30 ──
    brk_m5_bear_level: float = 0.0
    brk_m5_bull_level: float = 0.0
    brk_m15_bear_level: float = 0.0
    brk_m15_bull_level: float = 0.0
    brk_m30_bear_level: float = 0.0
    brk_m30_bull_level: float = 0.0

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

    # Reversal Pipeline (sweep → retournement → confirmation)
    bars_since_sweep: int = -1       # barres H1 depuis le dernier sweep
    reversal_h1: str = "N/A"         # "SWEEP_ONLY", "REVERSAL", "CONFIRMED", "FAILED"
    reversal_h4: str = "N/A"         # idem sur H4
    fvg_post_sweep: float = 0.0      # niveau du FVG créé APRÈS le sweep (dans la direction du reversal)
    fvg_post_sweep_dir: str = ""     # "BULL" ou "BEAR"
    retest_sweep_level: bool = False # prix a retesté le niveau sweepé
    retest_sweep_pips: float = 0.0   # distance du retest en pips
    cho_post_sweep: bool = False     # Change of Character (CHoCH) après le sweep
    reversal_chaine: str = ""        # chaîne complète : "AH sweep → FVG bear H1 → CHoCH → CONFIRMED"

    # Metadata
    criteria: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# ── Scanner ───────────────────────────────────────────────────────────

class DiamondScanner:
    """Scanner Diamond Analysis multi-symboles avec Etapes 3b, 5, 7, 7b integrees."""

    def __init__(self, symbols: Optional[List[str]] = None, tz_mode: str = ""):
        self.symbols: List[str] = list(symbols or [])
        self.tz_mode: str = (tz_mode or DEFAULT_TZ_MODE).upper()
        self._initialized = False
        self._ml_predictor = None  # lazy-load (type: Optional[MLPredictor])

    # ── Public API ──

    def initialize(self) -> bool:
        """Initialise MT5 et active tous les symboles."""
        if not mt5.initialize():
            logger.error("MT5 initialization failed")
            return False
        # Tenter de charger le modèle ML (non-bloquant, lazy import)
        if self._ml_predictor is None:
            try:
                from src.ml_predictor import MLPredictor
                self._ml_predictor = MLPredictor()
                self._ml_predictor.load()
            except ImportError as e:
                logger.info("ML non disponible (dépendances manquantes: %s)", e)
                self._ml_predictor = None
        return True

    @property
    def ml_available(self) -> bool:
        return self._ml_predictor is not None and self._ml_predictor.is_loaded
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

    def _get_rates_with_volume(self, sym: str, tf: int, n: int) -> Optional[List[Tuple[int, float, float, float, int]]]:
        """Fetch OHLC + tick_volume. Retourne (time, high, low, close, tick_volume)."""
        r = mt5.copy_rates_from_pos(sym, tf, 0, n)
        if r is None or len(r) < n:
            return None
        return [(int(x[0]), float(x[2]), float(x[3]), float(x[4]), int(x[5])) for x in r]

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
    ) -> Tuple[float, float, float, str, str, float,
               float, float, float, str, str, float]:
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

        pip_factor = 10.0 if sym == 'XAUUSD' else (100.0 if 'JPY' in sym else 10000.0)

        # Date formatter: include hour for intraday TFs, date only for higher
        if tf_label in ("M5", "M15", "M30"):
            date_fmt = "%d/%m %H:%M"
        elif tf_label == "H1":
            date_fmt = "%d/%m %Hh"
        else:
            date_fmt = "%d/%m"
        # Timezone offset + label (configurable: FTMO, PARIS, UTC)
        _off = _tz_off(self.tz_mode)
        _lbl = _tz_lbl(self.tz_mode)
        _tz_tag = f" {_lbl}"

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
                # For non-H1 TFs: use index as priority (higher i = more recent = higher priority)
                priority = i

            # Bearish FVG: low[i-2] > high[i]
            if lows[i - 2] > highs[i]:
                dt_local = dt_i2 + timedelta(hours=_off)
                label = f"{dt_local.strftime(date_fmt)}{_tz_tag}"
                if best_bear is None or priority > best_bear[0]:
                    best_bear = (priority, lows[i - 2], highs[i], label, i)

            # Bullish FVG: high[i-2] < low[i]
            if highs[i - 2] < lows[i]:
                dt_local = dt_i2 + timedelta(hours=_off)
                label = f"{dt_local.strftime(date_fmt)}{_tz_tag}"
                if best_bull is None or priority > best_bull[0]:
                    best_bull = (priority, lows[i], highs[i - 2], label, i)

        # ── Resolve bearish FVG (mitigation %) ──
        bear_top, bear_bot, bear_mitigated_pct, bear_pos, bear_date = 0.0, 0.0, 0.0, "N/A", ""
        if best_bear is not None:
            bear_top, bear_bot = best_bear[1], best_bear[2]
            bear_date = best_bear[3]
            fvg_idx = best_bear[4]
            gap = bear_top - bear_bot
            if gap > 0:
                # Trouver le niveau le plus profond dans le gap
                deepest = 0.0
                for k in range(fvg_idx + 1, n):
                    if highs[k] >= bear_bot:
                        entry = min(highs[k], bear_top)  # cap au top du gap
                        if entry > deepest:
                            deepest = entry
                if price >= bear_bot:
                    entry = min(price, bear_top)
                    if entry > deepest:
                        deepest = entry
                if deepest > 0:
                    bear_mitigated_pct = (deepest - bear_bot) / gap * 100.0
                    bear_mitigated_pct = min(100.0, max(0.0, bear_mitigated_pct))
            if bear_bot > 0:
                if price > bear_top: bear_pos = "ABOVE"
                elif price < bear_bot: bear_pos = "BELOW"
                else: bear_pos = "INSIDE"

        # ── Resolve bullish FVG (mitigation %) ──
        bull_top, bull_bot, bull_mitigated_pct, bull_pos, bull_date = 0.0, 0.0, 0.0, "N/A", ""
        if best_bull is not None:
            bull_top, bull_bot = best_bull[1], best_bull[2]
            bull_date = best_bull[3]
            fvg_idx = best_bull[4]
            gap = bull_top - bull_bot
            if gap > 0:
                # Trouver le niveau le plus profond dans le gap (par le haut)
                deepest = bull_top  # start from top
                for k in range(fvg_idx + 1, n):
                    if lows[k] <= bull_top:
                        entry = max(lows[k], bull_bot)  # cap au bottom du gap
                        if entry < deepest:
                            deepest = entry
                if price <= bull_top:
                    entry = max(price, bull_bot)
                    if entry < deepest:
                        deepest = entry
                bull_mitigated_pct = (bull_top - deepest) / gap * 100.0
                bull_mitigated_pct = min(100.0, max(0.0, bull_mitigated_pct))
            if bull_bot > 0:
                if price > bull_top: bull_pos = "ABOVE"
                elif price < bull_bot: bull_pos = "BELOW"
                else: bull_pos = "INSIDE"

        return (bear_top, bear_bot, bear_mitigated_pct, bear_pos, bear_date, pip_factor,
                bull_top, bull_bot, bull_mitigated_pct, bull_pos, bull_date, pip_factor)

    # ── Order Blocks (OB) ICT detection — generic TF ──

    def _detect_order_blocks(
        self, highs: List[float], lows: List[float], closes: List[float],
        timestamps: List[int], price: float, sym: str,
        tf_label: str = "H1", scan_window: int = 80
    ) -> Tuple[float, str, bool, float, str, bool]:
        """Detecte les Order Blocks (OB) ICT : bearish et bullish.

        Bearish OB : dernière bougie avant une impulsion baissière.
          - Niveau OB = high de la bougie précédant l'impulsion.
          - Actif (BELOW) = prix sous l'OB → résistance potentielle.
          - Mitigé (ABOVE/AT) = prix a touché l'OB → résistance affaiblie.

        Bullish OB : dernière bougie avant une impulsion haussière.
          - Niveau OB = low de la bougie précédant l'impulsion.
          - Actif (ABOVE) = prix au-dessus de l'OB → support potentiel.
          - Mitigé (BELOW/AT) = prix a touché l'OB → support affaibli.

        Détection d'impulsion : close[i] - close[i-1] > 1.2 × ATR(14).
        Prend le niveau OB le PLUS PROCHE du prix (le plus récent pertinent).

        Returns:
            (bear_level, bear_pos, bear_mitigated,
             bull_level, bull_pos, bull_mitigated)
        """
        n = len(highs)
        if n < 10:
            return (0.0, "N/A", False, 0.0, "N/A", False)

        max_idx = min(n, scan_window)

        # ── ATR(14) pour seuil d'impulsion ──
        ranges = [highs[i] - lows[i] for i in range(max_idx)]
        atr_14 = sum(ranges[-14:]) / 14 if len(ranges) >= 14 else (sum(ranges) / len(ranges) if ranges else 0.0001)
        impulse_thresh = atr_14 * 1.2  # 1.2× ATR

        if atr_14 == 0:
            return (0.0, "N/A", False, 0.0, "N/A", False)

        bear_level = 0.0
        bull_level = 0.0
        best_bear_dist = float('inf')
        best_bull_dist = float('inf')

        # ── Scan des barres de gauche à droite ──
        for i in range(2, max_idx):
            # Bearish impulse : close baisse fortement
            if closes[i] < closes[i - 1] - impulse_thresh:
                j = i - 1  # Bougie avant l'impulsion = OB
                if j >= 0:
                    level = highs[j]
                    dist = abs(price - level)
                    if bear_level == 0 or dist < best_bear_dist:
                        bear_level = level
                        best_bear_dist = dist

            # Bullish impulse : close monte fortement
            if closes[i] > closes[i - 1] + impulse_thresh:
                j = i - 1
                if j >= 0:
                    level = lows[j]
                    dist = abs(price - level)
                    if bull_level == 0 or dist < best_bull_dist:
                        bull_level = level
                        best_bull_dist = dist

        # ── Position et mitigation ──
        pip_thresh = 3.0  # 3 pips de tolérance pour "AT"

        bear_pos = "N/A"
        bear_mitigated = False
        if bear_level > 0:
            d = self._pips(sym, price, bear_level)
            if abs(d) < pip_thresh:
                bear_pos = "AT"
                bear_mitigated = True
            elif price > bear_level:
                bear_pos = "ABOVE"
                bear_mitigated = True  # Prix a dépassé l'OB → mitigé
            else:
                bear_pos = "BELOW"
                # Non mitigé : OB intacte, résistance active

        bull_pos = "N/A"
        bull_mitigated = False
        if bull_level > 0:
            d = self._pips(sym, price, bull_level)
            if abs(d) < pip_thresh:
                bull_pos = "AT"
                bull_mitigated = True
            elif price < bull_level:
                bull_pos = "BELOW"
                bull_mitigated = True  # Prix en dessous → mitigé
            else:
                bull_pos = "ABOVE"
                # Non mitigé : OB intacte, support active

        return (bear_level, bear_pos, bear_mitigated,
                bull_level, bull_pos, bull_mitigated)

    # ── Market Structure (MSS/BOS) detection — generic TF ──

    def _detect_market_structure(
        self, highs: List[float], lows: List[float],
        closes: List[float], price: float, sym: str,
        tf_label: str = "H1", scan_window: int = 60
    ) -> Tuple[str, str, str]:
        """Analyse la structure du marché : BOS, MSS, régime.

        Concepts ICT :
          - Swing High : pic local avec 2 barres plus basses de chaque côté.
          - Swing Low : creux local avec 2 barres plus hautes de chaque côté.
          - BOS (Break of Structure) : prix casse un swing high (bull) ou
            swing low (bear) → confirmation de tendance.
          - MSS (Market Structure Shift) : la structure de swings change
            (ex: lower lows → higher low) → signal de retournement.
          - Régime : "BULL" (HH/HL), "BEAR" (LH/LL), "RANGE" (sideways).

        Returns:
            (regime, bos, shift)
              regime : "BULL", "BEAR", "RANGE", "N/A"
              bos    : "BULL", "BEAR", "N/A"
              shift  : "BULL", "BEAR", "N/A"
        """
        n = len(highs)
        if n < 10:
            return ("N/A", "N/A", "N/A")

        max_idx = min(n, scan_window)

        # ── Swing detection (5-bar fractals) ──
        swing_highs: List[Tuple[int, float]] = []  # (index, level)
        swing_lows: List[Tuple[int, float]] = []

        for i in range(2, max_idx - 2):
            # Swing High: high[i] > high[i-2], high[i] > high[i-1],
            #             high[i] >= high[i+1], high[i] >= high[i+2]
            if (highs[i] > highs[i-2] and highs[i] > highs[i-1] and
                highs[i] >= highs[i+1] and highs[i] >= highs[i+2]):
                swing_highs.append((i, highs[i]))
            # Swing Low: low[i] < low[i-2], low[i] < low[i-1],
            #            low[i] <= low[i+1], low[i] <= low[i+2]
            if (lows[i] < lows[i-2] and lows[i] < lows[i-1] and
                lows[i] <= lows[i+1] and lows[i] <= lows[i+2]):
                swing_lows.append((i, lows[i]))

        if not swing_highs or not swing_lows:
            return ("RANGE", "N/A", "N/A")

        # ── Régime : analyser les 3 derniers swings ──
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

        # ── BOS : prix a-t-il cassé le dernier swing ? ──
        bos = "N/A"
        last_sh = swing_highs[-1][1] if swing_highs else None
        last_sl = swing_lows[-1][1] if swing_lows else None

        if last_sh and price > last_sh:
            bos = "BULL"
        elif last_sl and price < last_sl:
            bos = "BEAR"

        # ── MSS : la structure récente change-t-elle ? ──
        shift = "N/A"
        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            prev_sh = swing_highs[-2][1]
            prev_sl = swing_lows[-2][1]

            # Bullish MSS : tendance baissière → prix fait un higher low
            # (la structure s'inverse)
            if (regime == "BEAR" or regime == "RANGE"):
                if higher_lows and len(swing_lows) >= 2:
                    if swing_lows[-1][1] > swing_lows[-2][1]:
                        shift = "BULL"

            # Bearish MSS : tendance haussière → prix fait un lower high
            if (regime == "BULL" or regime == "RANGE"):
                if lower_highs and len(swing_highs) >= 2:
                    if swing_highs[-1][1] < swing_highs[-2][1]:
                        shift = "BEAR"

        return (regime, bos, shift)

    # ── Volume analysis (HVN/LVN + spike) — generic TF ──

    def _detect_volume_analysis(
        self, highs: List[float], lows: List[float], closes: List[float],
        volumes: List[int], price: float, sym: str,
        tf_label: str = "H1", scan_window: int = 60
    ) -> Tuple[float, bool, float, float]:
        """Analyse le tick volume : moyenne, spike, HVN, LVN.

        Concepts :
          - Volume moyen : moyenne des tick_volumes sur la fenetre.
          - Volume spike : volume de la derniere barre > 2x la moyenne.
          - HVN (High Volume Node) : niveau de prix avec volume > 1.5x moyenne.
            Zone de support/resistance forte.
          - LVN (Low Volume Node) : niveau de prix avec volume < 0.5x moyenne.
            Zone de faible interet — le prix la traverse rapidement.

        Algorithme HVN/LVN :
          - Divise l'amplitude de prix (min_low à max_high) en 20 zones.
          - Pour chaque barre, ajoute son volume à la zone correspondant à son close.
          - Calcule le volume moyen par zone.
          - HVN = zone la plus proche du prix avec volume > 1.5x moyenne.
          - LVN = zone la plus proche du prix avec volume < 0.5x moyenne.

        Returns:
            (avg_volume, spike, hvn_level, lvn_level)
        """
        n = len(volumes)
        if n < 5 or not any(volumes):
            return (0.0, False, 0.0, 0.0)

        max_idx = min(n, scan_window)
        vols = volumes[-max_idx:]
        hs = highs[-max_idx:]
        ls = lows[-max_idx:]
        cs = closes[-max_idx:]

        avg_vol = sum(vols) / len(vols) if vols else 0
        spike = vols[-1] > avg_vol * 2.0 if len(vols) >= 1 else False

        if avg_vol == 0:
            return (float(avg_vol), spike, 0.0, 0.0)

        # ── HVN/LVN via price zones ──
        min_p = min(ls)
        max_p = max(hs)
        if max_p <= min_p:
            return (float(avg_vol), spike, 0.0, 0.0)

        n_zones = 20
        zone_size = (max_p - min_p) / n_zones
        zone_vols = [0.0] * n_zones
        zone_counts = [0] * n_zones

        for i in range(max_idx):
            cz = cs[i]
            v = vols[i]
            zi = min(n_zones - 1, int((cz - min_p) / zone_size)) if zone_size > 0 else 0
            zone_vols[zi] += v
            zone_counts[zi] += 1

        # Volume moyen par zone (zones non vides uniquement)
        non_zero_zones = [v for v in zone_vols if v > 0]
        zone_avg = sum(non_zero_zones) / len(non_zero_zones) if non_zero_zones else avg_vol

        # Trouver la zone HVN la plus proche du prix
        price_zone = min(n_zones - 1, int((price - min_p) / zone_size)) if zone_size > 0 else 0
        hvn_level = 0.0
        lvn_level = 0.0
        best_hvn_dist = float('inf')
        best_lvn_dist = float('inf')

        for zi in range(n_zones):
            z_vol = zone_vols[zi]
            if z_vol == 0:
                continue
            z_price = min_p + (zi + 0.5) * zone_size
            z_dist = abs(zi - price_zone)

            if z_vol > zone_avg * 1.5 and z_dist < best_hvn_dist:
                hvn_level = z_price
                best_hvn_dist = z_dist
            if z_vol < zone_avg * 0.5 and z_dist < best_lvn_dist:
                lvn_level = z_price
                best_lvn_dist = z_dist

        return (float(avg_vol), spike, hvn_level, lvn_level)

    # ── Reversal Pipeline (sweep → retournement → confirmation) ──

    def _detect_reversal_pipeline(
        self, symbol: str, price: float,
        h1_data: list, asian_high: float, asian_low: float,
        ah_swept: bool, al_swept: bool, ah_at: float, al_at: float,
        lh_swept: bool, ll_swept: bool, lh_at: float, ll_at: float,
        london_high: float, london_low: float,
        session_date: str,
        h1_h: list, h1_l: list, h1_c: list, h1_t: list,
        h4_h: list, h4_l: list, h4_c: list, h4_t: list,
        mss_h1_regime_detected: str, mss_h1_shift_detected: str,
        mss_h4_regime_detected: str, mss_h4_shift_detected: str,
        fvg_top: float, fvg_bot: float, fvg_date: str,
        fvg_bull_top: float, fvg_bull_bot: float, fvg_bull_date: str,
        fvg4_top: float, fvg4_bot: float, fvg4_date: str,
        fvg4_bull_top: float, fvg4_bull_bot: float, fvg4_bull_date: str,
    ) -> Tuple[int, str, str, float, str, bool, float, bool, str]:
        """Analyse le pipeline sweep → retournement → confirmation.

        Étape 1 : Compter les barres H1 depuis le dernier sweep
        Étape 2 : Vérifier si un FVG a été créé APRÈS le sweep
        Étape 3 : Vérifier si un CHoCH (MSS shift) a eu lieu après le sweep
        Étape 4 : Vérifier si le prix a retesté le niveau sweepé
        Étape 5 : Déterminer le statut : SWEEP_ONLY / REVERSAL / CONFIRMED / FAILED
        Étape 6 : Construire la chaîne de confirmation

        Returns:
            (bars_since_sweep, reversal_h1, reversal_h4,
             fvg_post_sweep, fvg_post_sweep_dir,
             retest_sweep_level, retest_sweep_pips,
             cho_post_sweep, reversal_chaine)
        """
        bars_since_sweep = -1
        reversal_h1 = "N/A"
        reversal_h4 = "N/A"
        fvg_post_sweep = 0.0
        fvg_post_sweep_dir = ""
        retest_sweep_level = False
        retest_sweep_pips = 0.0
        cho_post_sweep = False
        reversal_chaine = ""

        # ── Déterminer le dernier sweep (timestamps) ──
        sweep_timestamps = []
        if ah_swept and ah_at > 0:
            sweep_timestamps.append((ah_at, "AH"))
        if al_swept and al_at > 0:
            sweep_timestamps.append((al_at, "AL"))
        if lh_swept and lh_at > 0:
            sweep_timestamps.append((lh_at, "LH"))
        if ll_swept and ll_at > 0:
            sweep_timestamps.append((ll_at, "LL"))

        if not sweep_timestamps or not h1_data:
            return (bars_since_sweep, reversal_h1, reversal_h4,
                    fvg_post_sweep, fvg_post_sweep_dir,
                    retest_sweep_level, retest_sweep_pips,
                    cho_post_sweep, reversal_chaine)

        # Trier par timestamp (le plus récent en dernier)
        sweep_timestamps.sort(key=lambda x: x[0])
        last_sweep_ts = sweep_timestamps[-1][0]
        last_sweep_label = sweep_timestamps[-1][1]

        # ── Étape 1 : Compter les barres H1 depuis le dernier sweep ──
        bars_since_sweep = 0
        now_ts = _time.time()
        for bar in h1_data:
            bar_ts = bar[0]
            dt = datetime.fromtimestamp(bar_ts, UTC)
            bar_date = dt.strftime("%Y-%m-%d")
            if bar_date != session_date:
                continue
            if bar_ts > last_sweep_ts:
                bars_since_sweep += 1

        # ── Étape 2 : FVG créé APRÈS le sweep ──
        # Vérifier si la date du FVG H1 est après le sweep
        def _bar_ts_from_date(date_str: str) -> float:
            """Convertit '15/07 18h' → epoch timestamp approximatif."""
            if not date_str or not h1_t:
                return 0.0
            try:
                # Format: "15/07 18h" ou "15/07"
                parts = date_str.replace('h', '').split()
                day, month = parts[0].split('/')
                hour = int(parts[1]) if len(parts) > 1 else 12
                year = datetime.now(UTC).year
                dt = datetime(year, int(month), int(day), hour, 0, 0, tzinfo=UTC)
                return dt.timestamp()
            except:
                return 0.0

        # Initialiser TOUS les timestamps FVG pour éviter les NameError
        fvg_post_ts = _bar_ts_from_date(fvg_date) if fvg_date else 0.0
        fvg_bull_post_ts = _bar_ts_from_date(fvg_bull_date) if fvg_bull_date else 0.0
        fvg4_post_ts = _bar_ts_from_date(fvg4_date) if fvg4_date else 0.0
        fvg4_bull_post_ts = _bar_ts_from_date(fvg4_bull_date) if fvg4_bull_date else 0.0

        if fvg_post_ts > last_sweep_ts and fvg_top > 0:
            fvg_post_sweep = fvg_top
            fvg_post_sweep_dir = "BEAR"
        elif fvg_bull_post_ts > last_sweep_ts and fvg_bull_top > 0:
            fvg_post_sweep = fvg_bull_top
            fvg_post_sweep_dir = "BULL"

        # Vérifier aussi H4 (si pas de FVG H1 post-sweep)
        if fvg_post_sweep == 0:
            if fvg4_post_ts > last_sweep_ts and fvg4_top > 0:
                fvg_post_sweep = fvg4_top
                fvg_post_sweep_dir = "BEAR"
            elif fvg4_bull_post_ts > last_sweep_ts and fvg4_bull_top > 0:
                fvg_post_sweep = fvg4_bull_top
                fvg_post_sweep_dir = "BULL"

        # ── Étape 3 : CHoCH (MSS shift) après le sweep ──
        # Si le MSS shift est BULL ou BEAR et qu'il y a un sweep, on considère
        # que le CHoCH a eu lieu en réaction au sweep
        if sweep_timestamps:
            if mss_h1_shift_detected in ("BULL", "BEAR"):
                cho_post_sweep = True
            elif mss_h4_shift_detected in ("BULL", "BEAR"):
                cho_post_sweep = True

        # ── Étape 4 : Retest du niveau sweepé ──
        for bar in h1_data:
            dt = datetime.fromtimestamp(bar[0], UTC)
            bar_date = dt.strftime("%Y-%m-%d")
            if bar_date != session_date:
                continue
            bar_high, bar_low, _ = bar[1], bar[2], bar[3]
            if bar[0] <= last_sweep_ts:
                continue
            for _, label in sweep_timestamps:
                level = 0.0
                if label == "AH": level = asian_high
                elif label == "AL": level = asian_low
                elif label == "LH": level = london_high
                elif label == "LL": level = london_low
                if level > 0:
                    dist_h = abs(self._pips(symbol, bar_high, level))
                    dist_l = abs(self._pips(symbol, bar_low, level))
                    if min(dist_h, dist_l) < 5:
                        retest_sweep_level = True
                        retest_sweep_pips = min(dist_h, dist_l)

        # ── Étape 5 : Déterminer reversal_h1 (statut sur H1) ──
        if not sweep_timestamps:
            reversal_h1 = "N/A"
            reversal_h4 = "N/A"
        elif bars_since_sweep > 20:
            reversal_h1 = "FAILED"  # Trop vieux, plus pertinent
            reversal_h4 = "FAILED"
        elif fvg_post_sweep > 0 and cho_post_sweep:
            reversal_h1 = "CONFIRMED"  # FVG + CHoCH = confirmation
        elif fvg_post_sweep > 0 or cho_post_sweep:
            reversal_h1 = "REVERSAL"  # Au moins un signe de retournement
        else:
            reversal_h1 = "SWEEP_ONLY"  # Sweep détecté mais pas de retournement

        # reversal_h4 : CHoCH H4
        if mss_h4_shift_detected in ("BULL", "BEAR") and sweep_timestamps:
            if fvg4_post_ts > last_sweep_ts or fvg4_bull_post_ts > last_sweep_ts:
                reversal_h4 = "CONFIRMED"
            else:
                reversal_h4 = "REVERSAL"
        elif sweep_timestamps:
            reversal_h4 = "SWEEP_ONLY"

        # ── Étape 6 : Chaîne de confirmation ──
        parts = []
        if sweep_timestamps:
            parts.append(f"{last_sweep_label} sweep")
        if fvg_post_sweep > 0:
            parts.append(f"FVG {fvg_post_sweep_dir}")
        if cho_post_sweep:
            parts.append("CHoCH")
        if retest_sweep_level:
            parts.append("retest")
        if reversal_h1 == "CONFIRMED":
            parts.append(f"✅ CONFIRMED {fvg_post_sweep_dir}")
        elif reversal_h1 == "REVERSAL":
            parts.append("↩️ REVERSAL")
        elif reversal_h1 == "FAILED":
            parts.append("❌ FAILED")

        if parts:
            reversal_chaine = " → ".join(parts)

        return (bars_since_sweep, reversal_h1, reversal_h4,
                fvg_post_sweep, fvg_post_sweep_dir,
                retest_sweep_level, retest_sweep_pips,
                cho_post_sweep, reversal_chaine)

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

    # ── Generic TF cross detection helper ──

    def _detect_tf_crosses(self, sym: str, tf: int, price: float,
                            min_bars: int = 30, request_bars: int = 60) -> Optional[dict]:
        """Detecte Kijun et Tenkan crosses pour un timeframe donne.

        Retourne un dict avec: kj, tk, kj_cross_bear, kj_cross_bull,
        tk_cross_bear, tk_cross_bull, d_kj, d_tk
        ou None si pas assez de donnees.
        """
        rates = self._get_rates_min(sym, tf, min_bars, request_bars)
        if rates is None:
            return None

        highs = [x[1] for x in rates]
        lows = [x[2] for x in rates]
        closes = [x[3] for x in rates]

        kj = self._kj(highs, lows) if len(highs) >= 26 else 0.0
        tk = self._tk(highs, lows) if len(highs) >= 9 else 0.0

        d_kj = self._pips(sym, price, kj) if kj > 0 else 0.0
        d_tk = self._pips(sym, price, tk) if tk > 0 else 0.0

        kj_cross_bear = False
        kj_cross_bull = False
        if len(closes) >= 3 and kj > 0:
            for i in range(max(1, len(closes) - 3), len(closes)):
                if closes[i-1] > kj and closes[i] < kj:
                    kj_cross_bear = True
                if closes[i-1] < kj and closes[i] > kj:
                    kj_cross_bull = True

        tk_cross_bear = False
        tk_cross_bull = False
        if len(closes) >= 3 and tk > 0:
            for i in range(max(1, len(closes) - 3), len(closes)):
                if closes[i-1] > tk and closes[i] < tk:
                    tk_cross_bear = True
                if closes[i-1] < tk and closes[i] > tk:
                    tk_cross_bull = True

        return {
            'kj': kj, 'tk': tk,
            'kj_cross_bear': kj_cross_bear, 'kj_cross_bull': kj_cross_bull,
            'tk_cross_bear': tk_cross_bear, 'tk_cross_bull': tk_cross_bull,
            'd_kj': d_kj, 'd_tk': d_tk,
        }

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

        # ═══ TF Cross detection: M30, M15, M5 (Kijun + Tenkan) ═════════════
        kj_m30 = 0.0; kj_m30_cross_bear = False; kj_m30_cross_bull = False; d_kj_m30 = 0.0
        tk_m30 = 0.0; tk_m30_cross_bear = False; tk_m30_cross_bull = False; d_tk_m30 = 0.0
        kj_m15 = 0.0; kj_m15_cross_bear = False; kj_m15_cross_bull = False; d_kj_m15 = 0.0
        tk_m15 = 0.0; tk_m15_cross_bear = False; tk_m15_cross_bull = False; d_tk_m15 = 0.0
        kj_m5 = 0.0; kj_m5_cross_bear = False; kj_m5_cross_bull = False; d_kj_m5 = 0.0
        tk_m5 = 0.0; tk_m5_cross_bear = False; tk_m5_cross_bull = False; d_tk_m5 = 0.0

        for tf_info in [
            (mt5.TIMEFRAME_M30, 'm30'),
            (mt5.TIMEFRAME_M15, 'm15'),
            (mt5.TIMEFRAME_M5,  'm5'),
        ]:
            tf_val, tf_label = tf_info
            d = self._detect_tf_crosses(sym, tf_val, price, min_bars=30, request_bars=60)
            if d is not None:
                if tf_label == 'm30':
                    kj_m30 = d['kj']; d_kj_m30 = d['d_kj']
                    kj_m30_cross_bear = d['kj_cross_bear']; kj_m30_cross_bull = d['kj_cross_bull']
                    tk_m30 = d['tk']; d_tk_m30 = d['d_tk']
                    tk_m30_cross_bear = d['tk_cross_bear']; tk_m30_cross_bull = d['tk_cross_bull']
                elif tf_label == 'm15':
                    kj_m15 = d['kj']; d_kj_m15 = d['d_kj']
                    kj_m15_cross_bear = d['kj_cross_bear']; kj_m15_cross_bull = d['kj_cross_bull']
                    tk_m15 = d['tk']; d_tk_m15 = d['d_tk']
                    tk_m15_cross_bear = d['tk_cross_bear']; tk_m15_cross_bull = d['tk_cross_bull']
                else:  # m5
                    kj_m5 = d['kj']; d_kj_m5 = d['d_kj']
                    kj_m5_cross_bear = d['kj_cross_bear']; kj_m5_cross_bull = d['kj_cross_bull']
                    tk_m5 = d['tk']; d_tk_m5 = d['d_tk']
                    tk_m5_cross_bear = d['tk_cross_bear']; tk_m5_cross_bull = d['tk_cross_bull']

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

        # ═══ Order Blocks (OB) detection — H1, H4, D1 ═══════════════════════
        h1_c = [x[3] for x in h1]
        h4_c = [x[3] for x in h4]
        d1_c = [x[3] for x in d1]
        ob_h1 = self._detect_order_blocks(h1_h, h1_l, h1_c, h1_t, price, sym, "H1", 80)
        ob_h4 = self._detect_order_blocks(h4_h, h4_l, h4_c, h4_t, price, sym, "H4", 60)
        ob_d1 = self._detect_order_blocks(d1_h, d1_l, d1_c, d1_t, price, sym, "D1", 40)
        ob_h1_bear_level, ob_h1_bear_pos, ob_h1_bear_mitigated, ob_h1_bull_level, ob_h1_bull_pos, ob_h1_bull_mitigated = ob_h1
        ob_h4_bear_level, ob_h4_bear_pos, ob_h4_bear_mitigated, ob_h4_bull_level, ob_h4_bull_pos, ob_h4_bull_mitigated = ob_h4
        ob_d1_bear_level, ob_d1_bear_pos, ob_d1_bear_mitigated, ob_d1_bull_level, ob_d1_bull_pos, ob_d1_bull_mitigated = ob_d1

        # ═══ Market Structure (MSS/BOS) detection — H1, H4, D1 ═══════════════
        mss_h1 = self._detect_market_structure(h1_h, h1_l, h1_c, price, sym, "H1", 80)
        mss_h4 = self._detect_market_structure(h4_h, h4_l, h4_c, price, sym, "H4", 60)
        mss_d1 = self._detect_market_structure(d1_h, d1_l, d1_c, price, sym, "D1", 40)
        mss_h1_regime, mss_h1_bos, mss_h1_shift = mss_h1
        mss_h4_regime, mss_h4_bos, mss_h4_shift = mss_h4
        mss_d1_regime, mss_d1_bos, mss_d1_shift = mss_d1

        # ═══ Volume analysis — H1, H4, D1 ═════════════════════════════════════
        h1_v = self._get_rates_with_volume(sym, mt5.TIMEFRAME_H1, 60)
        h4_v = self._get_rates_with_volume(sym, mt5.TIMEFRAME_H4, 60)
        d1_v = self._get_rates_with_volume(sym, mt5.TIMEFRAME_D1, 60)
        vol_avg_h1 = vol_spike_h1 = vol_hvn_h1 = vol_lvn_h1 = 0.0
        vol_avg_h4 = vol_spike_h4 = vol_hvn_h4 = vol_lvn_h4 = 0.0
        vol_avg_d1 = vol_spike_d1 = vol_hvn_d1 = vol_lvn_d1 = 0.0
        if h1_v:
            h1_v_h = [x[1] for x in h1_v]; h1_v_l = [x[2] for x in h1_v]
            h1_v_c = [x[3] for x in h1_v]; h1_v_v = [x[4] for x in h1_v]
            vol_avg_h1, vol_spike_h1, vol_hvn_h1, vol_lvn_h1 = self._detect_volume_analysis(
                h1_v_h, h1_v_l, h1_v_c, h1_v_v, price, sym, "H1", 48)
        if h4_v:
            h4_v_h = [x[1] for x in h4_v]; h4_v_l = [x[2] for x in h4_v]
            h4_v_c = [x[3] for x in h4_v]; h4_v_v = [x[4] for x in h4_v]
            vol_avg_h4, vol_spike_h4, vol_hvn_h4, vol_lvn_h4 = self._detect_volume_analysis(
                h4_v_h, h4_v_l, h4_v_c, h4_v_v, price, sym, "H4", 36)
        if d1_v:
            d1_v_h = [x[1] for x in d1_v]; d1_v_l = [x[2] for x in d1_v]
            d1_v_c = [x[3] for x in d1_v]; d1_v_v = [x[4] for x in d1_v]
            vol_avg_d1, vol_spike_d1, vol_hvn_d1, vol_lvn_d1 = self._detect_volume_analysis(
                d1_v_h, d1_v_l, d1_v_c, d1_v_v, price, sym, "D1", 30)

        # ═══ Breaker Blocks (OB inverse) — derives des OB detectes ═══════════
        # Bullish OB cassé (price < ob_h1_bull_level) = Bearish Breaker (resistance)
        # Bearish OB cassé (price > ob_h1_bear_level) = Bullish Breaker (support)
        brk_h1_bear_level = ob_h1_bull_level if (ob_h1_bull_mitigated and ob_h1_bull_level > 0 and price < ob_h1_bull_level) else 0.0
        brk_h1_bull_level = ob_h1_bear_level if (ob_h1_bear_mitigated and ob_h1_bear_level > 0 and price > ob_h1_bear_level) else 0.0
        brk_h4_bear_level = ob_h4_bull_level if (ob_h4_bull_mitigated and ob_h4_bull_level > 0 and price < ob_h4_bull_level) else 0.0
        brk_h4_bull_level = ob_h4_bear_level if (ob_h4_bear_mitigated and ob_h4_bear_level > 0 and price > ob_h4_bear_level) else 0.0
        brk_d1_bear_level = ob_d1_bull_level if (ob_d1_bull_mitigated and ob_d1_bull_level > 0 and price < ob_d1_bull_level) else 0.0
        brk_d1_bull_level = ob_d1_bear_level if (ob_d1_bear_mitigated and ob_d1_bear_level > 0 and price > ob_d1_bear_level) else 0.0

        # ═══ M5/M15/M30 FVG Detection — fresh data fetch ═══════════════════
        # Init defaults in case MT5 fetch fails
        fvg_m5_bear_top = fvg_m5_bear_bot = fvg_m5_bull_top = fvg_m5_bull_bot = 0.0
        fvg_m5_bear_mitigated = fvg_m5_bull_mitigated = False
        fvg_m5_bear_price_pos = fvg_m5_bull_price_pos = "N/A"
        fvg_m5_bear_date = fvg_m5_bull_date = ""
        fvg_m5_pip_factor = 10000.0
        fvg_m15_bear_top = fvg_m15_bear_bot = fvg_m15_bull_top = fvg_m15_bull_bot = 0.0
        fvg_m15_bear_mitigated = fvg_m15_bull_mitigated = False
        fvg_m15_bear_price_pos = fvg_m15_bull_price_pos = "N/A"
        fvg_m15_bear_date = fvg_m15_bull_date = ""
        fvg_m15_pip_factor = 10000.0
        fvg_m30_bear_top = fvg_m30_bear_bot = fvg_m30_bull_top = fvg_m30_bull_bot = 0.0
        fvg_m30_bear_mitigated = fvg_m30_bull_mitigated = False
        fvg_m30_bear_price_pos = fvg_m30_bull_price_pos = "N/A"
        fvg_m30_bear_date = fvg_m30_bull_date = ""
        fvg_m30_pip_factor = 10000.0
        ob_m5_bear_level = ob_m5_bull_level = 0.0; ob_m5_bear_pos = ob_m5_bull_pos = "N/A"
        ob_m5_bear_mitigated = ob_m5_bull_mitigated = False
        ob_m15_bear_level = ob_m15_bull_level = 0.0; ob_m15_bear_pos = ob_m15_bull_pos = "N/A"
        ob_m15_bear_mitigated = ob_m15_bull_mitigated = False
        ob_m30_bear_level = ob_m30_bull_level = 0.0; ob_m30_bear_pos = ob_m30_bull_pos = "N/A"
        ob_m30_bear_mitigated = ob_m30_bull_mitigated = False
        mss_m5_regime = mss_m5_bos = mss_m5_shift = "N/A"
        mss_m15_regime = mss_m15_bos = mss_m15_shift = "N/A"
        mss_m30_regime = mss_m30_bos = mss_m30_shift = "N/A"
        vol_avg_m5 = vol_spike_m5 = vol_hvn_m5 = vol_lvn_m5 = 0.0
        vol_avg_m15 = vol_spike_m15 = vol_hvn_m15 = vol_lvn_m15 = 0.0
        vol_avg_m30 = vol_spike_m30 = vol_hvn_m30 = vol_lvn_m30 = 0.0
        brk_m5_bear_level = brk_m5_bull_level = 0.0
        brk_m15_bear_level = brk_m15_bull_level = 0.0
        brk_m30_bear_level = brk_m30_bull_level = 0.0

        m5_raw = self._get_rates(sym, mt5.TIMEFRAME_M5, 120)
        m15_raw = self._get_rates(sym, mt5.TIMEFRAME_M15, 80)
        m30_raw = self._get_rates(sym, mt5.TIMEFRAME_M30, 60)
        if m5_raw and m15_raw and m30_raw:
            m5_h = [x[1] for x in m5_raw]; m5_l = [x[2] for x in m5_raw]; m5_c = [x[3] for x in m5_raw]; m5_t = [x[0] for x in m5_raw]
            m15_h = [x[1] for x in m15_raw]; m15_l = [x[2] for x in m15_raw]; m15_c = [x[3] for x in m15_raw]; m15_t = [x[0] for x in m15_raw]
            m30_h = [x[1] for x in m30_raw]; m30_l = [x[2] for x in m30_raw]; m30_c = [x[3] for x in m30_raw]; m30_t = [x[0] for x in m30_raw]

            fvg_m5_bear_top, fvg_m5_bear_bot, fvg_m5_bear_mitigated, fvg_m5_bear_price_pos, fvg_m5_bear_date, fvg_m5_pip_factor, \
                fvg_m5_bull_top, fvg_m5_bull_bot, fvg_m5_bull_mitigated, fvg_m5_bull_price_pos, fvg_m5_bull_date, _ = \
                self._detect_fvg(m5_h, m5_l, m5_t, price, sym, 120, False, "M5")
            fvg_m15_bear_top, fvg_m15_bear_bot, fvg_m15_bear_mitigated, fvg_m15_bear_price_pos, fvg_m15_bear_date, fvg_m15_pip_factor, \
                fvg_m15_bull_top, fvg_m15_bull_bot, fvg_m15_bull_mitigated, fvg_m15_bull_price_pos, fvg_m15_bull_date, _ = \
                self._detect_fvg(m15_h, m15_l, m15_t, price, sym, 80, False, "M15")
            fvg_m30_bear_top, fvg_m30_bear_bot, fvg_m30_bear_mitigated, fvg_m30_bear_price_pos, fvg_m30_bear_date, fvg_m30_pip_factor, \
                fvg_m30_bull_top, fvg_m30_bull_bot, fvg_m30_bull_mitigated, fvg_m30_bull_price_pos, fvg_m30_bull_date, _ = \
                self._detect_fvg(m30_h, m30_l, m30_t, price, sym, 60, False, "M30")

            # ═══ M5/M15/M30 OB Detection ═══════════════════════════════════════
            ob_m5 = self._detect_order_blocks(m5_h, m5_l, m5_c, m5_t, price, sym, "M5", 120)
            ob_m15 = self._detect_order_blocks(m15_h, m15_l, m15_c, m15_t, price, sym, "M15", 80)
            ob_m30 = self._detect_order_blocks(m30_h, m30_l, m30_c, m30_t, price, sym, "M30", 60)
            ob_m5_bear_level, ob_m5_bear_pos, ob_m5_bear_mitigated, ob_m5_bull_level, ob_m5_bull_pos, ob_m5_bull_mitigated = ob_m5
            ob_m15_bear_level, ob_m15_bear_pos, ob_m15_bear_mitigated, ob_m15_bull_level, ob_m15_bull_pos, ob_m15_bull_mitigated = ob_m15
            ob_m30_bear_level, ob_m30_bear_pos, ob_m30_bear_mitigated, ob_m30_bull_level, ob_m30_bull_pos, ob_m30_bull_mitigated = ob_m30

            # ═══ M5/M15/M30 MSS/BOS Detection ═════════════════════════════════
            mss_m5 = self._detect_market_structure(m5_h, m5_l, m5_c, price, sym, "M5", 120)
            mss_m15 = self._detect_market_structure(m15_h, m15_l, m15_c, price, sym, "M15", 80)
            mss_m30 = self._detect_market_structure(m30_h, m30_l, m30_c, price, sym, "M30", 60)
            mss_m5_regime, mss_m5_bos, mss_m5_shift = mss_m5
            mss_m15_regime, mss_m15_bos, mss_m15_shift = mss_m15
            mss_m30_regime, mss_m30_bos, mss_m30_shift = mss_m30

            # ═══ M5/M15/M30 Volume Analysis ═══════════════════════════════════
            m5_v = self._get_rates_with_volume(sym, mt5.TIMEFRAME_M5, 120)
            m15_v = self._get_rates_with_volume(sym, mt5.TIMEFRAME_M15, 80)
            m30_v = self._get_rates_with_volume(sym, mt5.TIMEFRAME_M30, 60)
            vol_avg_m5 = vol_spike_m5 = vol_hvn_m5 = vol_lvn_m5 = 0.0
            vol_avg_m15 = vol_spike_m15 = vol_hvn_m15 = vol_lvn_m15 = 0.0
            vol_avg_m30 = vol_spike_m30 = vol_hvn_m30 = vol_lvn_m30 = 0.0
            if m5_v:
                m5_v_h = [x[1] for x in m5_v]; m5_v_l = [x[2] for x in m5_v]
                m5_v_c = [x[3] for x in m5_v]; m5_v_v = [x[4] for x in m5_v]
                vol_avg_m5, vol_spike_m5, vol_hvn_m5, vol_lvn_m5 = self._detect_volume_analysis(m5_v_h, m5_v_l, m5_v_c, m5_v_v, price, sym, "M5", 60)
            if m15_v:
                m15_v_h = [x[1] for x in m15_v]; m15_v_l = [x[2] for x in m15_v]
                m15_v_c = [x[3] for x in m15_v]; m15_v_v = [x[4] for x in m15_v]
                vol_avg_m15, vol_spike_m15, vol_hvn_m15, vol_lvn_m15 = self._detect_volume_analysis(m15_v_h, m15_v_l, m15_v_c, m15_v_v, price, sym, "M15", 40)
            if m30_v:
                m30_v_h = [x[1] for x in m30_v]; m30_v_l = [x[2] for x in m30_v]
                m30_v_c = [x[3] for x in m30_v]; m30_v_v = [x[4] for x in m30_v]
                vol_avg_m30, vol_spike_m30, vol_hvn_m30, vol_lvn_m30 = self._detect_volume_analysis(m30_v_h, m30_v_l, m30_v_c, m30_v_v, price, sym, "M30", 30)

            # ═══ M5/M15/M30 Breaker Blocks ════════════════════════════════════
            brk_m5_bear_level = ob_m5_bull_level if (ob_m5_bull_mitigated and ob_m5_bull_level > 0 and price < ob_m5_bull_level) else 0.0
            brk_m5_bull_level = ob_m5_bear_level if (ob_m5_bear_mitigated and ob_m5_bear_level > 0 and price > ob_m5_bear_level) else 0.0
            brk_m15_bear_level = ob_m15_bull_level if (ob_m15_bull_mitigated and ob_m15_bull_level > 0 and price < ob_m15_bull_level) else 0.0
            brk_m15_bull_level = ob_m15_bear_level if (ob_m15_bear_mitigated and ob_m15_bear_level > 0 and price > ob_m15_bear_level) else 0.0
            brk_m30_bear_level = ob_m30_bull_level if (ob_m30_bull_mitigated and ob_m30_bull_level > 0 and price < ob_m30_bull_level) else 0.0
            brk_m30_bull_level = ob_m30_bear_level if (ob_m30_bear_mitigated and ob_m30_bear_level > 0 and price > ob_m30_bear_level) else 0.0

        # ═══ Reversal Pipeline (sweep → retournement → confirmation) ═══════
        reversal = self._detect_reversal_pipeline(
            symbol=sym, price=price,
            h1_data=h1, asian_high=asian_high, asian_low=asian_low,
            ah_swept=ah_swept, al_swept=al_swept, ah_at=ah_at, al_at=al_at,
            lh_swept=lh_swept, ll_swept=ll_swept, lh_at=lh_at, ll_at=ll_at,
            london_high=london_high, london_low=london_low,
            session_date=session_date,
            h1_h=h1_h, h1_l=h1_l, h1_c=h1_c, h1_t=h1_t,
            h4_h=h4_h, h4_l=h4_l, h4_c=h4_c, h4_t=h4_t,
            mss_h1_regime_detected=mss_h1_regime, mss_h1_shift_detected=mss_h1_shift,
            mss_h4_regime_detected=mss_h4_regime, mss_h4_shift_detected=mss_h4_shift,
            fvg_top=fvg_top, fvg_bot=fvg_bot, fvg_date=fvg_date,
            fvg_bull_top=fvg_bull_top, fvg_bull_bot=fvg_bull_bot, fvg_bull_date=fvg_bull_date,
            fvg4_top=fvg4_top, fvg4_bot=fvg4_bot, fvg4_date=fvg4_date,
            fvg4_bull_top=fvg4_bull_top, fvg4_bull_bot=fvg4_bull_bot, fvg4_bull_date=fvg4_bull_date,
        )
        r = reversal
        bars_since_sweep, reversal_h1, reversal_h4 = r[0], r[1], r[2]
        fvg_post_sweep, fvg_post_sweep_dir = r[3], r[4]
        retest_sweep_level, retest_sweep_pips = r[5], r[6]
        cho_post_sweep, reversal_chaine = r[7], r[8]

        # ═══ Scoring (58 criteres max avec Reversal Pipeline + Breaker + vol + MSS + OB + TK4/TKd1/Kj4/KjD1 + Asian Sweep + M30 cross) ═══
        score = 0
        max_score = 109 if mn_available else 107
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

        # TF Cross detection: M30, M15, M5 (6 criteres — Kj + Tk pour chaque TF)
        for tf_label, kj_val, d_kj, kj_bear, kj_bull, tk_val, d_tk, tk_bear, tk_bull in [
            ("M30", kj_m30, d_kj_m30, kj_m30_cross_bear, kj_m30_cross_bull, tk_m30, d_tk_m30, tk_m30_cross_bear, tk_m30_cross_bull),
            ("M15", kj_m15, d_kj_m15, kj_m15_cross_bear, kj_m15_cross_bull, tk_m15, d_tk_m15, tk_m15_cross_bear, tk_m15_cross_bull),
            ("M5",  kj_m5,  d_kj_m5,  kj_m5_cross_bear,  kj_m5_cross_bull,  tk_m5,  d_tk_m5,  tk_m5_cross_bear,  tk_m5_cross_bull),
        ]:
            # Kijun cross scoring
            if kj_bear and direction == -1:
                score += 1; crit.append(f"{tf_label}K")
            elif kj_bull and direction == 1:
                score += 1; crit.append(f"{tf_label}K")
            # Tenkan cross scoring
            if tk_bear and direction == -1:
                score += 1; crit.append(f"{tf_label}T")
            elif tk_bull and direction == 1:
                score += 1; crit.append(f"{tf_label}T")
            # Warning always shown for cross
            if kj_bear:
                warnings.append(f"{tf_label} Kijun CROSS BEAR {kj_val:.5f} ({d_kj:+.0f}p){" — conflit" if direction >= 0 else " — momentum OK"}")
            elif kj_bull:
                warnings.append(f"{tf_label} Kijun CROSS BULL {kj_val:.5f} ({d_kj:+.0f}p){" — conflit" if direction <= 0 else " — momentum OK"}")
            elif kj_val > 0 and price < kj_val and d_kj < -5:
                warnings.append(f"Sous {tf_label} Kijun {kj_val:.5f} ({d_kj:+.0f}p) — structure baissiere")
            if tk_bear:
                warnings.append(f"{tf_label} Tenkan CROSS BEAR {tk_val:.5f} ({d_tk:+.0f}p){" — conflit" if direction >= 0 else " — momentum OK"}")
            elif tk_bull:
                warnings.append(f"{tf_label} Tenkan CROSS BULL {tk_val:.5f} ({d_tk:+.0f}p){" — conflit" if direction <= 0 else " — momentum OK"}")
            elif tk_val > 0 and price < tk_val and d_tk < -5:
                warnings.append(f"Sous {tf_label} Tenkan {tk_val:.5f} ({d_tk:+.0f}p) — structure baissiere")

        # ── Order Block Scoring ──
        # H1 OB
        if ob_h1_bear_level > 0 and ob_h1_bear_pos == "BELOW" and direction == -1:
            score += 1; crit.append("OBH1")
        if ob_h1_bull_level > 0 and ob_h1_bull_pos == "ABOVE" and direction == 1:
            score += 1; crit.append("OBbH1")
        # H4 OB
        if ob_h4_bear_level > 0 and ob_h4_bear_pos == "BELOW" and direction == -1:
            score += 1; crit.append("OBH4")
        if ob_h4_bull_level > 0 and ob_h4_bull_pos == "ABOVE" and direction == 1:
            score += 1; crit.append("OBbH4")
        # D1 OB
        if ob_d1_bear_level > 0 and ob_d1_bear_pos == "BELOW" and direction == -1:
            score += 1; crit.append("OBD1")
        if ob_d1_bull_level > 0 and ob_d1_bull_pos == "ABOVE" and direction == 1:
            score += 1; crit.append("OBbD1")
        # Alignment bonus if OB detected on multiple TFs
        ob_tfs = 0
        if ob_m5_bear_level > 0 or ob_m5_bull_level > 0: ob_tfs += 1
        if ob_m15_bear_level > 0 or ob_m15_bull_level > 0: ob_tfs += 1
        if ob_m30_bear_level > 0 or ob_m30_bull_level > 0: ob_tfs += 1
        if ob_h1_bear_level > 0 or ob_h1_bull_level > 0: ob_tfs += 1
        if ob_h4_bear_level > 0 or ob_h4_bull_level > 0: ob_tfs += 1
        if ob_d1_bear_level > 0 or ob_d1_bull_level > 0: ob_tfs += 1
        if ob_tfs >= 3:
            score += 1; crit.append("OBx3")
        if ob_tfs >= 5:
            score += 1; crit.append("OBx5"); alignment += 1

        # ── Market Structure (MSS/BOS) Scoring ──
        # H1 regime
        if mss_h1_regime == "BULL" and direction == 1:
            score += 1; crit.append("MSSbH1")
        elif mss_h1_regime == "BEAR" and direction == -1:
            score += 1; crit.append("MSSH1")
        # H4 regime
        if mss_h4_regime == "BULL" and direction == 1:
            score += 1; crit.append("MSSbH4")
        elif mss_h4_regime == "BEAR" and direction == -1:
            score += 1; crit.append("MSSH4")
        # D1 regime
        if mss_d1_regime == "BULL" and direction == 1:
            score += 1; crit.append("MSSbD1")
        elif mss_d1_regime == "BEAR" and direction == -1:
            score += 1; crit.append("MSSD1")
        # BOS bonus (confirmation de momentum)
        for tf_label, bos_val in [("H1", mss_h1_bos), ("H4", mss_h4_bos), ("D1", mss_d1_bos)]:
            if (bos_val == "BULL" and direction == 1) or (bos_val == "BEAR" and direction == -1):
                score += 1; crit.append(f"BOS{tf_label}")
        # MSS shift bonus (retournement potentiel)
        for tf_label, shift_val in [("H1", mss_h1_shift), ("H4", mss_h4_shift), ("D1", mss_d1_shift)]:
            if (shift_val == "BULL" and direction == 1) or (shift_val == "BEAR" and direction == -1):
                score += 1; crit.append(f"CHoCH{tf_label}")

        # ── Volume Scoring ──
        # Volume spike + direction alignment
        if vol_spike_h1 and direction != 0:
            score += 1; crit.append("VOLh1")
        if vol_spike_h4 and direction != 0:
            score += 1; crit.append("VOLh4")
        if vol_spike_d1 and direction != 0:
            score += 1; crit.append("VOLd1")
        # HVN proximity (support si price > hvn, resistance si price < hvn)
        if vol_hvn_h1 > 0 and ((direction == 1 and price > vol_hvn_h1) or (direction == -1 and price < vol_hvn_h1)):
            score += 1; crit.append("HVNh1")
        if vol_hvn_h4 > 0 and ((direction == 1 and price > vol_hvn_h4) or (direction == -1 and price < vol_hvn_h4)):
            score += 1; crit.append("HVNh4")
        if vol_hvn_d1 > 0 and ((direction == 1 and price > vol_hvn_d1) or (direction == -1 and price < vol_hvn_d1)):
            score += 1; crit.append("HVNd1")
        # LVN ahead (dans la direction du trade = mouvement rapide attendu)
        if vol_lvn_h1 > 0 and ((direction == 1 and vol_lvn_h1 > price) or (direction == -1 and vol_lvn_h1 < price)):
            score += 1; crit.append("LVNh1")
        if vol_lvn_h4 > 0 and ((direction == 1 and vol_lvn_h4 > price) or (direction == -1 and vol_lvn_h4 < price)):
            score += 1; crit.append("LVNh4")
        if vol_lvn_d1 > 0 and ((direction == 1 and vol_lvn_d1 > price) or (direction == -1 and vol_lvn_d1 < price)):
            score += 1; crit.append("LVNd1")

        # ── Breaker Block Scoring ──
        # Bearish Breaker (ancien Bull OB cassé → résistance au-dessus)
        if brk_h1_bear_level > 0 and direction == -1:
            score += 1; crit.append("BRH1")
        if brk_h4_bear_level > 0 and direction == -1:
            score += 1; crit.append("BRH4")
        if brk_d1_bear_level > 0 and direction == -1:
            score += 1; crit.append("BRD1")
        # Bullish Breaker (ancien Bear OB cassé → support en-dessous)
        if brk_h1_bull_level > 0 and direction == 1:
            score += 1; crit.append("BRbH1")
        if brk_h4_bull_level > 0 and direction == 1:
            score += 1; crit.append("BRbH4")
        if brk_d1_bull_level > 0 and direction == 1:
            score += 1; crit.append("BRbD1")

        # ═══ M5/M15/M30 FVG Scoring ════════════════════════════════════
        if fvg_m5_bear_bot > 0 and direction == -1:
            score += 1; crit.append("FVGM5")
        if fvg_m5_bull_bot > 0 and direction == 1:
            score += 1; crit.append("FVGbM5")
        if fvg_m15_bear_bot > 0 and direction == -1:
            score += 1; crit.append("FVGM15")
        if fvg_m15_bull_bot > 0 and direction == 1:
            score += 1; crit.append("FVGbM15")
        if fvg_m30_bear_bot > 0 and direction == -1:
            score += 1; crit.append("FVGM30")
        if fvg_m30_bull_bot > 0 and direction == 1:
            score += 1; crit.append("FVGbM30")

        # ═══ M5/M15/M30 OB Scoring ═════════════════════════════════════
        if ob_m5_bear_level > 0 and ob_m5_bear_pos == "BELOW" and direction == -1:
            score += 1; crit.append("OBM5")
        if ob_m5_bull_level > 0 and ob_m5_bull_pos == "ABOVE" and direction == 1:
            score += 1; crit.append("OBbM5")
        if ob_m15_bear_level > 0 and ob_m15_bear_pos == "BELOW" and direction == -1:
            score += 1; crit.append("OBM15")
        if ob_m15_bull_level > 0 and ob_m15_bull_pos == "ABOVE" and direction == 1:
            score += 1; crit.append("OBbM15")
        if ob_m30_bear_level > 0 and ob_m30_bear_pos == "BELOW" and direction == -1:
            score += 1; crit.append("OBM30")
        if ob_m30_bull_level > 0 and ob_m30_bull_pos == "ABOVE" and direction == 1:
            score += 1; crit.append("OBbM30")

        # ═══ M5/M15/M30 MSS/BOS Scoring ════════════════════════════════
        for tf_lbl, regime, bos_val, shift_val in [
            ("M5", mss_m5_regime, mss_m5_bos, mss_m5_shift),
            ("M15", mss_m15_regime, mss_m15_bos, mss_m15_shift),
            ("M30", mss_m30_regime, mss_m30_bos, mss_m30_shift),
        ]:
            if (regime == "BULL" and direction == 1) or (regime == "BEAR" and direction == -1):
                score += 1; crit.append(f"MSS{tf_lbl}")
            if (bos_val == "BULL" and direction == 1) or (bos_val == "BEAR" and direction == -1):
                score += 1; crit.append(f"BOS{tf_lbl}")
            if (shift_val == "BULL" and direction == 1) or (shift_val == "BEAR" and direction == -1):
                score += 1; crit.append(f"CHoCH{tf_lbl}")

        # ═══ M5/M15/M30 Volume Scoring ═════════════════════════════════
        for tf_lbl, avg_v, spike, hvn, lvn in [
            ("M5", vol_avg_m5, vol_spike_m5, vol_hvn_m5, vol_lvn_m5),
            ("M15", vol_avg_m15, vol_spike_m15, vol_hvn_m15, vol_lvn_m15),
            ("M30", vol_avg_m30, vol_spike_m30, vol_hvn_m30, vol_lvn_m30),
        ]:
            if direction != 0 and spike:
                score += 1; crit.append(f"VOL{tf_lbl}")
            if direction != 0 and hvn > 0:
                hvn_pips = self._pips(sym, price, hvn)
                if (direction == -1 and hvn_pips < 0) or (direction == 1 and hvn_pips > 0):
                    score += 1; crit.append(f"HVN{tf_lbl}")
            if direction != 0 and lvn > 0:
                lvn_pips = self._pips(sym, price, lvn)
                if (direction == -1 and lvn_pips > 0) or (direction == 1 and lvn_pips < 0):
                    score += 1; crit.append(f"LVN{tf_lbl}")

        # ═══ M5/M15/M30 Breaker Scoring ════════════════════════════════
        if brk_m5_bear_level > 0 and direction == -1:
            score += 1; crit.append("BRM5")
        if brk_m5_bull_level > 0 and direction == 1:
            score += 1; crit.append("BRbM5")
        if brk_m15_bear_level > 0 and direction == -1:
            score += 1; crit.append("BRM15")
        if brk_m15_bull_level > 0 and direction == 1:
            score += 1; crit.append("BRbM15")
        if brk_m30_bear_level > 0 and direction == -1:
            score += 1; crit.append("BRM30")
        if brk_m30_bull_level > 0 and direction == 1:
            score += 1; crit.append("BRbM30")

        # ═══ Reversal Pipeline Scoring (9 criteres) ═══════════════════
        if bars_since_sweep >= 1 and bars_since_sweep <= 20:
            score += 1; crit.append("RSW")
        if reversal_h1 == "REVERSAL" or reversal_h1 == "CONFIRMED":
            score += 1; crit.append("REVh1")
        if reversal_h4 == "REVERSAL" or reversal_h4 == "CONFIRMED":
            score += 1; crit.append("REVh4")
        if reversal_h1 == "CONFIRMED":
            score += 1; crit.append("CFh1")
        if reversal_h4 == "CONFIRMED":
            score += 1; crit.append("CFh4")
        if fvg_post_sweep > 0:
            score += 1; crit.append("FVGpost")
        if retest_sweep_level:
            score += 1; crit.append("RETEST")
        if cho_post_sweep:
            score += 1; crit.append("CHoCHps")
        if reversal_chaine:
            score += 1; crit.append("CHAIN")
            alignment += 1

        # ── Warnings (TOUS les TFs) ──
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
        # Order Block warnings (H1/H4/D1)
        for tf_lbl, bear_lv, bear_mit, bear_ps, bull_lv, bull_mit, bull_ps in [
            ("H1", ob_h1_bear_level, ob_h1_bear_mitigated, ob_h1_bear_pos,
             ob_h1_bull_level, ob_h1_bull_mitigated, ob_h1_bull_pos),
            ("H4", ob_h4_bear_level, ob_h4_bear_mitigated, ob_h4_bear_pos,
             ob_h4_bull_level, ob_h4_bull_mitigated, ob_h4_bull_pos),
            ("D1", ob_d1_bear_level, ob_d1_bear_mitigated, ob_d1_bear_pos,
             ob_d1_bull_level, ob_d1_bull_mitigated, ob_d1_bull_pos),
        ]:
            if bear_lv > 0 and not bear_mit:
                warnings.append(f"OB BEAR {tf_lbl} {bear_lv:.5f} ({self._pips(sym, price, bear_lv):+.0f}p) — resistance intacte")
            if bull_lv > 0 and not bull_mit:
                warnings.append(f"OB BULL {tf_lbl} {bull_lv:.5f} ({self._pips(sym, price, bull_lv):+.0f}p) — support intact")
        # MSS/BOS warnings
        for tf_lbl, regime, bos, shift in [
            ("H1", mss_h1_regime, mss_h1_bos, mss_h1_shift),
            ("H4", mss_h4_regime, mss_h4_bos, mss_h4_shift),
            ("D1", mss_d1_regime, mss_d1_bos, mss_d1_shift),
        ]:
            if regime in ("BULL", "BEAR"):
                if (direction == 1 and regime == "BEAR") or (direction == -1 and regime == "BULL"):
                    warnings.append(f"MSS {tf_lbl} CONFLIT: marche {regime}, direction opposee")
            if bos != "N/A":
                if (direction == 1 and bos == "BULL") or (direction == -1 and bos == "BEAR"):
                    pass  # BOS aligns with direction — no warning needed
                else:
                    warnings.append(f"BOS {tf_lbl} {bos} — structure cassee")
            if shift != "N/A":
                if (direction == 1 and shift == "BULL") or (direction == -1 and shift == "BEAR"):
                    warnings.append(f"MSS {tf_lbl} {shift} — retournement potentiel")

        # Volume warnings (spike + HVN/LVN proximity)
        for tf_lbl, avg_v, spike, hvn, lvn in [
            ("H1", vol_avg_h1, vol_spike_h1, vol_hvn_h1, vol_lvn_h1),
            ("H4", vol_avg_h4, vol_spike_h4, vol_hvn_h4, vol_lvn_h4),
            ("D1", vol_avg_d1, vol_spike_d1, vol_hvn_d1, vol_lvn_d1),
        ]:
            if avg_v <= 0:
                continue
            if spike:
                warnings.append(f"VOL {tf_lbl} SPIKE {avg_v:.0f}×2 — volume anormal")
            if hvn > 0 and abs(self._pips(sym, price, hvn)) < 10:
                warnings.append(f"HVN {tf_lbl} {hvn:.5f} — zone de fort volume proche")
            if lvn > 0 and abs(self._pips(sym, price, lvn)) < 10:
                warnings.append(f"LVN {tf_lbl} {lvn:.5f} — zone de faible volume proche")

        # Breaker Block warnings
        for tf_lbl, brk_bear, brk_bull in [
            ("H1", brk_h1_bear_level, brk_h1_bull_level),
            ("H4", brk_h4_bear_level, brk_h4_bull_level),
            ("D1", brk_d1_bear_level, brk_d1_bull_level),
        ]:
            if brk_bear > 0:
                d = self._pips(sym, price, brk_bear)
                warnings.append(f"BRK BEAR {tf_lbl} {brk_bear:.5f} ({d:+.0f}p) — OB inverse (resistance)")
            if brk_bull > 0:
                d = self._pips(sym, price, brk_bull)
                warnings.append(f"BRK BULL {tf_lbl} {brk_bull:.5f} ({d:+.0f}p) — OB inverse (support)")

        # FVG warnings (H1 + H4 + D1, bearish + bullish)
        for tf_name, fvg_t, fvg_b, fvg_m, fvg_p, fvg_d, fvg_pf, fvg_bt, fvg_bb, fvg_bm, fvg_bp, fvg_bd, fvg_bpf in [
            ("H1", fvg_top, fvg_bot, fvg_mitigated, fvg_pos, fvg_date, fvg_pip_factor,
             fvg_bull_top, fvg_bull_bot, fvg_bull_mitigated, fvg_bull_pos, fvg_bull_date, fvg_bull_pip_factor),
            ("H4", fvg4_top, fvg4_bot, fvg4_mitigated, fvg4_pos, fvg4_date, fvg4_pip_factor,
             fvg4_bull_top, fvg4_bull_bot, fvg4_bull_mitigated, fvg4_bull_pos, fvg4_bull_date, fvg4_bull_pip_factor),
            ("D1", fvg_d1_top, fvg_d1_bot, fvg_d1_mitigated, fvg_d1_pos, fvg_d1_date, fvg_d1_pip_factor,
             fvg_d1_bull_top, fvg_d1_bull_bot, fvg_d1_bull_mitigated, fvg_d1_bull_pos, fvg_d1_bull_date, fvg_d1_bull_pip_factor),
            ("M5", fvg_m5_bear_top, fvg_m5_bear_bot, fvg_m5_bear_mitigated, fvg_m5_bear_price_pos, fvg_m5_bear_date, fvg_m5_pip_factor,
             fvg_m5_bull_top, fvg_m5_bull_bot, fvg_m5_bull_mitigated, fvg_m5_bull_price_pos, fvg_m5_bull_date, fvg_m5_pip_factor),
            ("M15", fvg_m15_bear_top, fvg_m15_bear_bot, fvg_m15_bear_mitigated, fvg_m15_bear_price_pos, fvg_m15_bear_date, fvg_m15_pip_factor,
             fvg_m15_bull_top, fvg_m15_bull_bot, fvg_m15_bull_mitigated, fvg_m15_bull_price_pos, fvg_m15_bull_date, fvg_m15_pip_factor),
            ("M30", fvg_m30_bear_top, fvg_m30_bear_bot, fvg_m30_bear_mitigated, fvg_m30_bear_price_pos, fvg_m30_bear_date, fvg_m30_pip_factor,
             fvg_m30_bull_top, fvg_m30_bull_bot, fvg_m30_bull_mitigated, fvg_m30_bull_price_pos, fvg_m30_bull_date, fvg_m30_pip_factor),
        ]:
            if fvg_t > 0 and fvg_b > 0:
                gap = abs(fvg_t - fvg_b) * fvg_pf
                mit = f"MITIGE {fvg_m:.0f}%" if fvg_m > 0 else "NON MITIGE"
                warnings.append(
                    f"FVG {tf_name} BEAR {fvg_d}: {fvg_b:.5f}-{fvg_t:.5f} ({gap:.1f}p) [{mit}] [{fvg_p}]"
                )
            if fvg_bt > 0 and fvg_bb > 0:
                gap = abs(fvg_bt - fvg_bb) * fvg_bpf
                mit = f"MITIGE {fvg_bm:.0f}%" if fvg_bm > 0 else "NON MITIGE"
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

        # ── Correctif P1 : Regle T/Kx H1 ──
        # Lecon #9 du backtest 16-17/07 : si T/Kx H1 contredit le biais,
        # le trade est condamne (5/5 perdants). Le TF le plus court domine.
        tkx1_conflict = (
            (direction == 1 and tkx1 == "BEAR") or
            (direction == -1 and tkx1 == "BULL")
        )

        # ── Correctif P0 : Filtre MFE / respiration recente ──
        # Lecon #7 du backtest : si le prix n'a pas respire (> 5% du range)
        # dans la direction du biais, le trade est probablement mort.
        # Proxy : flat bars H1 >= 8 + Kumo INSIDE = prix coince, pas de respiration.
        # NOTE : ce proxy detecte la consolidation (sideways). Le cas contre-tendance
        # (MFE=0 parce que le prix trend contre le biais) est couvert par le filtre
        # tkx1_conflict ci-dessus. Les deux filtres sont complementaires.
        no_breathing = (flat1 >= 8 and kumo1 == "INSIDE") or (flat4 >= 6 and kumo4 == "INSIDE")

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

            # ── Correctif P1 : T/Kx H1 conflit → force WAIT ──
            if tkx1_conflict:
                quality = "WAIT"
                warnings.append(
                    f"T/Kx H1 CONFLIT: biais {bias} mais TKx H1 {tkx1} "
                    f"— trade condamne (Lecon #9, 5/5 perdants)"
                )
            # ── Correctif P0 : Pas de respiration → downgrade ──
            elif no_breathing:
                if score >= strong_threshold:
                    quality = "GOOD"  # downgrade STRONG → GOOD
                elif score >= good_threshold:
                    quality = "WAIT"  # downgrade GOOD → WAIT
                else:
                    quality = "WAIT"
                warnings.append(
                    f"MFE PROXY: flat bars H1={flat1}b H4={flat4}b + Kumo INSIDE "
                    f"— pas de respiration detectee (Lecon #7)"
                )
            elif score >= strong_threshold and not has_warnings:
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
            fvg_h1_bear_mitigated_pct=fvg_mitigated, fvg_h1_bear_price_pos=fvg_pos,
            fvg_h1_bear_date=fvg_date, fvg_h1_bear_pip_factor=fvg_pip_factor,
            fvg_h1_bull_top=fvg_bull_top, fvg_h1_bull_bot=fvg_bull_bot,
            fvg_h1_bull_mitigated_pct=fvg_bull_mitigated, fvg_h1_bull_price_pos=fvg_bull_pos,
            fvg_h1_bull_date=fvg_bull_date, fvg_h1_bull_pip_factor=fvg_bull_pip_factor,
            fvg_h4_bear_top=fvg4_top, fvg_h4_bear_bot=fvg4_bot,
            fvg_h4_bear_mitigated_pct=fvg4_mitigated, fvg_h4_bear_price_pos=fvg4_pos,
            fvg_h4_bear_date=fvg4_date, fvg_h4_bear_pip_factor=fvg4_pip_factor,
            fvg_h4_bull_top=fvg4_bull_top, fvg_h4_bull_bot=fvg4_bull_bot,
            fvg_h4_bull_mitigated_pct=fvg4_bull_mitigated, fvg_h4_bull_price_pos=fvg4_bull_pos,
            fvg_h4_bull_date=fvg4_bull_date, fvg_h4_bull_pip_factor=fvg4_bull_pip_factor,
            fvg_d1_bear_top=fvg_d1_top, fvg_d1_bear_bot=fvg_d1_bot,
            fvg_d1_bear_mitigated_pct=fvg_d1_mitigated, fvg_d1_bear_price_pos=fvg_d1_pos,
            fvg_d1_bear_date=fvg_d1_date, fvg_d1_bear_pip_factor=fvg_d1_pip_factor,
            fvg_d1_bull_top=fvg_d1_bull_top, fvg_d1_bull_bot=fvg_d1_bull_bot,
            fvg_d1_bull_mitigated_pct=fvg_d1_bull_mitigated, fvg_d1_bull_price_pos=fvg_d1_bull_pos,
            fvg_d1_bull_date=fvg_d1_bull_date, fvg_d1_bull_pip_factor=fvg_d1_bull_pip_factor,
            asian_high=asian_high, asian_low=asian_low,
            asian_high_swept=ah_swept, asian_low_swept=al_swept,
            asian_high_swept_at=ah_at, asian_low_swept_at=al_at,
            asian_high_swept_session=ah_sess, asian_low_swept_session=al_sess,
            london_high=london_high, london_low=london_low,
            london_high_swept=lh_swept, london_low_swept=ll_swept,
            london_high_swept_at=lh_at, london_low_swept_at=ll_at,
            london_high_swept_session=lh_sess, london_low_swept_session=ll_sess,
            kj_m30=kj_m30, kj_m30_cross_bear=kj_m30_cross_bear,
            kj_m30_cross_bull=kj_m30_cross_bull, d_kj_m30=d_kj_m30,
            tk_m30=tk_m30, tk_m30_cross_bear=tk_m30_cross_bear,
            tk_m30_cross_bull=tk_m30_cross_bull, d_tk_m30=d_tk_m30,
            kj_m15=kj_m15, kj_m15_cross_bear=kj_m15_cross_bear,
            kj_m15_cross_bull=kj_m15_cross_bull, d_kj_m15=d_kj_m15,
            tk_m15=tk_m15, tk_m15_cross_bear=tk_m15_cross_bear,
            tk_m15_cross_bull=tk_m15_cross_bull, d_tk_m15=d_tk_m15,
            kj_m5=kj_m5, kj_m5_cross_bear=kj_m5_cross_bear,
            kj_m5_cross_bull=kj_m5_cross_bull, d_kj_m5=d_kj_m5,
            tk_m5=tk_m5, tk_m5_cross_bear=tk_m5_cross_bear,
            tk_m5_cross_bull=tk_m5_cross_bull, d_tk_m5=d_tk_m5,
            ob_h1_bear_level=ob_h1_bear_level, ob_h1_bear_pos=ob_h1_bear_pos,
            ob_h1_bear_mitigated=ob_h1_bear_mitigated,
            ob_h1_bull_level=ob_h1_bull_level, ob_h1_bull_pos=ob_h1_bull_pos,
            ob_h1_bull_mitigated=ob_h1_bull_mitigated,
            ob_h4_bear_level=ob_h4_bear_level, ob_h4_bear_pos=ob_h4_bear_pos,
            ob_h4_bear_mitigated=ob_h4_bear_mitigated,
            ob_h4_bull_level=ob_h4_bull_level, ob_h4_bull_pos=ob_h4_bull_pos,
            ob_h4_bull_mitigated=ob_h4_bull_mitigated,
            ob_d1_bear_level=ob_d1_bear_level, ob_d1_bear_pos=ob_d1_bear_pos,
            ob_d1_bear_mitigated=ob_d1_bear_mitigated,
            ob_d1_bull_level=ob_d1_bull_level, ob_d1_bull_pos=ob_d1_bull_pos,
            ob_d1_bull_mitigated=ob_d1_bull_mitigated,
            mss_h1_regime=mss_h1_regime, mss_h1_bos=mss_h1_bos, mss_h1_shift=mss_h1_shift,
            mss_h4_regime=mss_h4_regime, mss_h4_bos=mss_h4_bos, mss_h4_shift=mss_h4_shift,
            mss_d1_regime=mss_d1_regime, mss_d1_bos=mss_d1_bos, mss_d1_shift=mss_d1_shift,
            vol_avg_h1=vol_avg_h1, vol_spike_h1=vol_spike_h1,
            vol_hvn_h1=vol_hvn_h1, vol_lvn_h1=vol_lvn_h1,
            vol_avg_h4=vol_avg_h4, vol_spike_h4=vol_spike_h4,
            vol_hvn_h4=vol_hvn_h4, vol_lvn_h4=vol_lvn_h4,
            vol_avg_d1=vol_avg_d1, vol_spike_d1=vol_spike_d1,
            vol_hvn_d1=vol_hvn_d1, vol_lvn_d1=vol_lvn_d1,
            brk_h1_bear_level=brk_h1_bear_level, brk_h1_bull_level=brk_h1_bull_level,
            brk_h4_bear_level=brk_h4_bear_level, brk_h4_bull_level=brk_h4_bull_level,
            brk_d1_bear_level=brk_d1_bear_level, brk_d1_bull_level=brk_d1_bull_level,
            # FVG M5/M15/M30
            fvg_m5_bear_top=fvg_m5_bear_top, fvg_m5_bear_bot=fvg_m5_bear_bot,
            fvg_m5_bear_mitigated_pct=fvg_m5_bear_mitigated, fvg_m5_bear_price_pos=fvg_m5_bear_price_pos,
            fvg_m5_bear_date=fvg_m5_bear_date, fvg_m5_bull_top=fvg_m5_bull_top,
            fvg_m5_bull_bot=fvg_m5_bull_bot, fvg_m5_bull_mitigated_pct=fvg_m5_bull_mitigated,
            fvg_m5_bull_price_pos=fvg_m5_bull_price_pos, fvg_m5_bull_date=fvg_m5_bull_date,
            fvg_m5_pip_factor=fvg_m5_pip_factor,
            fvg_m15_bear_top=fvg_m15_bear_top, fvg_m15_bear_bot=fvg_m15_bear_bot,
            fvg_m15_bear_mitigated_pct=fvg_m15_bear_mitigated, fvg_m15_bear_price_pos=fvg_m15_bear_price_pos,
            fvg_m15_bear_date=fvg_m15_bear_date, fvg_m15_bull_top=fvg_m15_bull_top,
            fvg_m15_bull_bot=fvg_m15_bull_bot, fvg_m15_bull_mitigated_pct=fvg_m15_bull_mitigated,
            fvg_m15_bull_price_pos=fvg_m15_bull_price_pos, fvg_m15_bull_date=fvg_m15_bull_date,
            fvg_m15_pip_factor=fvg_m15_pip_factor,
            fvg_m30_bear_top=fvg_m30_bear_top, fvg_m30_bear_bot=fvg_m30_bear_bot,
            fvg_m30_bear_mitigated_pct=fvg_m30_bear_mitigated, fvg_m30_bear_price_pos=fvg_m30_bear_price_pos,
            fvg_m30_bear_date=fvg_m30_bear_date, fvg_m30_bull_top=fvg_m30_bull_top,
            fvg_m30_bull_bot=fvg_m30_bull_bot, fvg_m30_bull_mitigated_pct=fvg_m30_bull_mitigated,
            fvg_m30_bull_price_pos=fvg_m30_bull_price_pos, fvg_m30_bull_date=fvg_m30_bull_date,
            fvg_m30_pip_factor=fvg_m30_pip_factor,
            # OB M5/M15/M30
            ob_m5_bear_level=ob_m5_bear_level, ob_m5_bear_pos=ob_m5_bear_pos,
            ob_m5_bear_mitigated=ob_m5_bear_mitigated,
            ob_m5_bull_level=ob_m5_bull_level, ob_m5_bull_pos=ob_m5_bull_pos,
            ob_m5_bull_mitigated=ob_m5_bull_mitigated,
            ob_m15_bear_level=ob_m15_bear_level, ob_m15_bear_pos=ob_m15_bear_pos,
            ob_m15_bear_mitigated=ob_m15_bear_mitigated,
            ob_m15_bull_level=ob_m15_bull_level, ob_m15_bull_pos=ob_m15_bull_pos,
            ob_m15_bull_mitigated=ob_m15_bull_mitigated,
            ob_m30_bear_level=ob_m30_bear_level, ob_m30_bear_pos=ob_m30_bear_pos,
            ob_m30_bear_mitigated=ob_m30_bear_mitigated,
            ob_m30_bull_level=ob_m30_bull_level, ob_m30_bull_pos=ob_m30_bull_pos,
            ob_m30_bull_mitigated=ob_m30_bull_mitigated,
            # MSS M5/M15/M30
            mss_m5_regime=mss_m5_regime, mss_m5_bos=mss_m5_bos, mss_m5_shift=mss_m5_shift,
            mss_m15_regime=mss_m15_regime, mss_m15_bos=mss_m15_bos, mss_m15_shift=mss_m15_shift,
            mss_m30_regime=mss_m30_regime, mss_m30_bos=mss_m30_bos, mss_m30_shift=mss_m30_shift,
            # Volume M5/M15/M30
            vol_avg_m5=vol_avg_m5, vol_spike_m5=vol_spike_m5,
            vol_hvn_m5=vol_hvn_m5, vol_lvn_m5=vol_lvn_m5,
            vol_avg_m15=vol_avg_m15, vol_spike_m15=vol_spike_m15,
            vol_hvn_m15=vol_hvn_m15, vol_lvn_m15=vol_lvn_m15,
            vol_avg_m30=vol_avg_m30, vol_spike_m30=vol_spike_m30,
            vol_hvn_m30=vol_hvn_m30, vol_lvn_m30=vol_lvn_m30,
            # BRK M5/M15/M30
            brk_m5_bear_level=brk_m5_bear_level, brk_m5_bull_level=brk_m5_bull_level,
            brk_m15_bear_level=brk_m15_bear_level, brk_m15_bull_level=brk_m15_bull_level,
            brk_m30_bear_level=brk_m30_bear_level, brk_m30_bull_level=brk_m30_bull_level,
            bars_since_sweep=bars_since_sweep,
            reversal_h1=reversal_h1, reversal_h4=reversal_h4,
            fvg_post_sweep=fvg_post_sweep, fvg_post_sweep_dir=fvg_post_sweep_dir,
            retest_sweep_level=retest_sweep_level, retest_sweep_pips=retest_sweep_pips,
            cho_post_sweep=cho_post_sweep, reversal_chaine=reversal_chaine,
            sl=sl, tp=tp, rr=rr, tp_label=tp_label, horizon=horizon,
            criteria=crit, warnings=warnings,
        )

        compression_pips, compression_zone = self._detect_compression(r, sym)
        r.compression_pips = compression_pips
        r.compression_zone = compression_zone

        # ── ML Prediction ──
        self._predict_ml(r)

        # ── News Risk Filter ──
        # ── Correctif P0 : Contre-biais HIGH NEWS DAY ──
        # Lecon #8 du backtest 16-17/07 : 15/15 trades declares BULL mais
        # le marche etait structurellement BEAR (Trump, FOMC, CPI, UoM, GDP).
        # Si >=2 evenements macro majeurs → downgrade BULL + avertissement.
        _, _nwarn, _nhigh = get_news_risk()  # _ncount unused, kept for API compat
        if _nhigh:
            r.warnings.append(_nwarn)
            if r.bias == "BULL":
                # Downgrade quality for BULL on HIGH NEWS DAY
                if r.quality == "STRONG":
                    r.quality = "GOOD"
                elif r.quality == "GOOD":
                    r.quality = "WAIT"
                r.warnings.append(
                    "HIGH NEWS DAY: biais BULL downgrade — "
                    "setups BULL non fiables, privilegier BEAR ou attendre (Lecon #8, 15/15 erreurs)"
                )

        return r

    def _predict_ml(self, r: DiamondResult) -> None:
        """Ajoute la prédiction ML au DiamondResult (non-bloquant)."""
        if self._ml_predictor is None or not self._ml_predictor.is_loaded:
            return
        try:
            r.ml_win_pct = self._ml_predictor.predict(r)
        except Exception:
            pass  # silencieux — le ML est optionnel


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
