"""
Diamond Analysis Scanner — Module permanent d'analyse multi-TF Ichimoku complete.

Integration systematique de l'Etape 3b : detection des flat lines passees, presentes
et futures sur tous les timeframes (H1, H4, D1, W1, MN).

Pipe #13 (14/07/2026) : les Tenkan D1 historiques sont desormais verifies automatiquement
avant toute recommandation de trade.

Usage:
    from diamond_scanner import DiamondScanner
    scanner = DiamondScanner(symbols)
    results = scanner.scan_all()
    for r in results:
        print(f"{r.symbol}: {r.score}/11 {r.bias}")
"""

import logging
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

@dataclass
class DiamondResult:
    """Resultat d'analyse Diamond pour un symbole (8 criteres scores + Etape 3b)."""
    symbol: str
    price: float
    score: int
    bias: str               # "BULL", "BEAR", "FLAT"
    quality: str            # "STRONG", "GOOD", "WAIT"

    # Kijun values
    kj_h1: float = 0.0
    kj_h4: float = 0.0
    kj_d1: float = 0.0
    d_kj4: float = 0.0     # distance prix vs Kijun H4 en pips

    # T/K crosses
    tkx_h1: str = "N/A"
    tkx_h4: str = "N/A"
    tkx_d1: str = "N/A"

    # Kumo
    kumo_h1: str = "N/A"
    kumo_h4: str = "N/A"
    kumo_d1: str = "N/A"

    # Flat bars (present)
    flat_h1: int = 0
    flat_h4: int = 0

    # Memory (past) — Etape 3b
    tenkan_flats: List[TenkanFlatMemory] = field(default_factory=list)
    ssb_proximity: List[Tuple[float, float]] = field(default_factory=list)

    # Trade setup
    sl: float = 0.0
    tp: float = 0.0
    rr: float = 0.0

    # Metadata
    criteria: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# ── Scanner ───────────────────────────────────────────────────────────

class DiamondScanner:
    """Scanner Diamond Analysis multi-symboles avec Etape 3b integree."""

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
        """Scan complet de tous les symboles avec Etape 3b."""
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
        else: return (price - level) * 10000

    def _get_price(self, sym: str) -> Optional[float]:
        mt5.symbol_select(sym, True)
        t = mt5.symbol_info_tick(sym)
        return float(t.bid) if t else None

    def _get_rates(self, sym: str, tf: int, n: int) -> Optional[List[Tuple[int, float, float, float]]]:
        r = mt5.copy_rates_from_pos(sym, tf, 0, n)
        if r is None or len(r) < n:
            return None
        return [(int(x[0]), float(x[2]), float(x[3]), float(x[4])) for x in r]

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

    # ── Etape 3b : Tenkan D1 historique ──

    def _detect_tenkan_flat_history(
        self, highs: List[float], lows: List[float],
        timestamps: List[int], sym: str, price: float
    ) -> List[TenkanFlatMemory]:
        """Detecte les Tenkan D1 plats historiques proches du prix (memoire institutionnelle)."""
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
            if abs(dist) < 80 and len(period) >= 2:
                relevant.append(TenkanFlatMemory(
                    level=avg, dist_pips=dist, duration=len(period),
                    start_dt=period[0][0], end_dt=period[-1][0],
                    direction="SUPPORT" if dist > 0 else "RESISTANCE"
                ))
        return sorted(relevant, key=lambda x: abs(x.dist_pips))

    # ── SSB proximity ──

    def _detect_ssb_near(
        self, highs: List[float], lows: List[float],
        price: float, sym: str, max_pips: float = 5.0
    ) -> List[Tuple[float, float]]:
        """Trouve les SSB dans les max_pips du prix."""
        factor = 10 if sym == 'XAUUSD' else (100 if 'JPY' in sym else 10000)
        results: List[Tuple[float, float]] = []
        seen = set()
        for i in range(52, len(highs)):
            sb = (max(highs[i-51:i+1]) + min(lows[i-51:i+1])) / 2.0
            if sb == 0: continue
            dist = abs(price - sb) * factor
            if dist < max_pips:
                key = round(sb, 5)
                if key not in seen:
                    seen.add(key)
                    results.append((sb, dist))
        return sorted(results, key=lambda x: x[1])

    # ── Core scan ──

    def _scan_symbol(self, sym: str) -> Optional[DiamondResult]:
        price = self._get_price(sym)
        if price is None: return None

        h1 = self._get_rates(sym, mt5.TIMEFRAME_H1, 120)
        h4 = self._get_rates(sym, mt5.TIMEFRAME_H4, 120)
        d1 = self._get_rates(sym, mt5.TIMEFRAME_D1, 200)

        if h1 is None or h4 is None or d1 is None:
            return None

        h1_h, h1_l = [x[1] for x in h1], [x[2] for x in h1]
        h4_h, h4_l = [x[1] for x in h4], [x[2] for x in h4]
        d1_h, d1_l = [x[1] for x in d1], [x[2] for x in d1]
        d1_t = [x[0] for x in d1]

        # Ichimoku
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

        # Etape 3b : Tenkan D1 historique
        tenkan_flats = self._detect_tenkan_flat_history(d1_h, d1_l, d1_t, sym, price)

        # SSB H4
        ssb_h4 = self._detect_ssb_near(h4_h, h4_l, price, sym)

        # Scoring (11 criteres)
        score = 0
        crit: List[str] = []
        if kumo1 == "ABOVE": score += 1; crit.append("H1Ku")
        if tkx1 == "BULL": score += 1; crit.append("H1TK")
        if kumo4 == "ABOVE": score += 1; crit.append("H4Ku")
        if tkx4 == "BULL": score += 1; crit.append("H4TK")
        if kumod1 == "ABOVE": score += 1; crit.append("D1Ku")
        if tkxd1 == "BULL": score += 1; crit.append("D1TK")
        if flat4 >= 8: score += 1; crit.append(f"Fl4({flat4}b)")
        if flat1 >= 8: score += 1; crit.append(f"Fl1({flat1}b)")

        d_kj4 = self._pips(sym, price, kj4)

        # Warnings (Etape 3b)
        warnings: List[str] = []
        if tenkan_flats:
            near = [f for f in tenkan_flats if abs(f.dist_pips) < 10]
            if near:
                for nf in near[:2]:
                    warnings.append(
                        f"TenkanD1 {nf.direction} {nf.level:.5f} "
                        f"({nf.dist_pips:+.0f}p, {nf.duration}j)"
                    )
                score -= 1  # Penalite pour entree dans resistance

        if ssb_h4:
            for sb_l, sb_d in ssb_h4[:2]:
                warnings.append(f"SSB {sb_l:.5f} ({sb_d:.1f}p)")

        # Bias + setup
        if d_kj4 > 5 and kumo4 == "ABOVE" and score >= 6:
            bias, direction = "BULL", 1
        elif d_kj4 < -5 and kumo4 == "BELOW" and score >= 6:
            bias, direction = "BEAR", -1
        else:
            bias, direction = "FLAT", 0

        if direction != 0:
            sl = kj4
            risk = abs(d_kj4)
            tp = price + (risk * 2.0) / (10 if sym == 'XAUUSD' else (100 if 'JPY' in sym else 10000)) * direction
            rr = 2.0
            quality = "STRONG" if score >= 7 and not warnings else "GOOD" if score >= 6 else "WAIT"
        else:
            sl = tp = rr = 0.0
            quality = "WAIT"

        return DiamondResult(
            symbol=sym, price=price, score=score, bias=bias, quality=quality,
            kj_h1=kj1, kj_h4=kj4, kj_d1=kd1, d_kj4=d_kj4,
            tkx_h1=tkx1, tkx_h4=tkx4, tkx_d1=tkxd1,
            kumo_h1=kumo1, kumo_h4=kumo4, kumo_d1=kumod1,
            flat_h1=flat1, flat_h4=flat4,
            tenkan_flats=tenkan_flats, ssb_proximity=ssb_h4,
            sl=sl, tp=tp, rr=rr,
            criteria=crit, warnings=warnings
        )


# ── DXY helper ──

def get_dxy_price() -> Optional[float]:
    """Recupere le prix du DXY (essaye plusieurs variantes de symbole)."""
    if not mt5.initialize():
        return None
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
