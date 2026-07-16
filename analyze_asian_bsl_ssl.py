#!/usr/bin/env python3
"""
🔍 Asian Session BSL/SSL Liquidity Scanner
===========================================
Analyse les swing highs (BSL — Buy-side Liquidity) et swing lows
(SSL — Sell-side Liquidity) créés pendant la session asiatique
(UTC 00:00-08:00) via Williams fractals (N=2).

Réutilise les modules src/ existants (MT5Connector, sweep_detector, display, config)
pour éviter toute duplication de code.

Usage standalone:
    python analyze_asian_bsl_ssl.py
    python analyze_asian_bsl_ssl.py --symbols XAUUSD EURUSD GBPUSD --tf M5
    python analyze_asian_bsl_ssl.py --scan-all --json

Usage via CLI unifié:
    python main.py asian-liquidity
    python main.py asian-liquidity --symbols XAUUSD --tf M5
"""

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from src.config import (
    resolve_watchlist,
    ASIAN,
    SWEEP,
)
from src.mt5_connector import MT5Connector
from src.sweep_detector import (
    detect_swing_points,
    _session_for_epoch,
    _classify_symbol,
)
from src.display import (
    _fmt_price,
    _pad_cell,
    RESET, BOLD, DIM, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, GRAY,
)

UTC = timezone.utc

# ── Constantes ──────────────────────────────────────────────────────────────
FRACTAL_N = 2                # Williams fractal window

_TIMEFRAME_MAP: Dict[str, int] = {}
try:
    import MetaTrader5 as _mt5_ref
    _TIMEFRAME_MAP = {
        "M1":  _mt5_ref.TIMEFRAME_M1,
        "M5":  _mt5_ref.TIMEFRAME_M5,
        "M15": _mt5_ref.TIMEFRAME_M15,
        "M30": _mt5_ref.TIMEFRAME_M30,
        "H1":  _mt5_ref.TIMEFRAME_H1,
    }
except ImportError:
    pass


# ── Dataclasses ─────────────────────────────────────────────────────────────
@dataclass
class AsianSwingPoint:
    """Un swing high (BSL) ou swing low (SSL) détecté pendant la session asiatique."""
    kind: str                 # "BSL" (swing high) ou "SSL" (swing low)
    level: float
    bar_time: float           # epoch UTC de la bougie du swing
    bar_time_str: str         # "HH:MM" UTC
    bar_index: int            # index dans les barres asiatiques
    swept: bool = False
    swept_at: Optional[float] = None
    swept_at_str: Optional[str] = None
    swept_session: Optional[str] = None
    swept_close: Optional[float] = None
    dist_pips: float = 0.0


@dataclass
class SymbolAsianLiquidity:
    """Résultat complet pour un symbole."""
    symbol: str
    symbol_type: str
    current_price: float
    current_time: float
    spread_pct: float
    session_date: str
    asian_high: float
    asian_low: float
    asian_range_pct: float
    asian_bar_count: int
    bsl_points: List[AsianSwingPoint] = field(default_factory=list)
    ssl_points: List[AsianSwingPoint] = field(default_factory=list)
    all_swings: List[AsianSwingPoint] = field(default_factory=list)


# ── Helpers ─────────────────────────────────────────────────────────────────
def _pips(sym: str, price: float, level: float) -> float:
    """Convertit une différence de prix en pips selon l'instrument."""
    if 'JPY' in sym and 'XAU' not in sym and 'XAG' not in sym:
        return (price - level) * 100
    elif 'XAU' in sym:
        return (price - level) * 10
    elif 'XAG' in sym:
        return (price - level) * 100
    elif any(sym.startswith(p) for p in ('BTC', 'ETH', 'SOL', 'BNB')):
        return price - level
    elif '.cash' in sym or sym in ('DXY.cash',):
        return price - level
    else:
        return (price - level) * 10000


# ── Analyse d'un symbole ───────────────────────────────────────────────────
def analyze_symbol(
    mt5c: MT5Connector,
    sym: str,
    session_date: str,
    tf_name: str = "M15",
    start_utc: int = 0,
    end_utc: int = 8,
) -> Optional[SymbolAsianLiquidity]:
    """Analyse complète : BSL/SSL asiatiques + sweeps post-Asian."""

    import MetaTrader5 as mt5

    tf = _TIMEFRAME_MAP.get(tf_name.upper())
    if tf is None:
        return None

    mt5c.select_symbol(sym)

    # Charger les barres : M15 → 120 barres = 30h ; M5 → 250 barres
    bars_needed = 250 if tf_name == "M5" else 120
    rates = mt5.copy_rates_from_pos(sym, tf, 0, bars_needed)
    if rates is None or len(rates) == 0:
        return None

    bars_raw: List[dict] = []
    for r in rates:
        bars_raw.append({
            "time":  int(r[0]),
            "open":  float(r[1]),
            "high":  float(r[2]),
            "low":   float(r[3]),
            "close": float(r[4]),
        })
    bars_raw.sort(key=lambda b: b["time"])

    # Filtrer : barres de la session asiatique du jour
    asian_bars: List[dict] = []
    for b in bars_raw:
        d = datetime.fromtimestamp(b["time"], UTC).strftime("%Y-%m-%d")
        if d != session_date:
            continue
        h_utc = (b["time"] % 86400) // 3600
        if start_utc <= h_utc < end_utc:
            asian_bars.append(b)

    if len(asian_bars) < 2 * FRACTAL_N + 1:
        return None

    # AH / AL
    asian_high = max(b["high"] for b in asian_bars)
    asian_low = min(b["low"] for b in asian_bars)
    last_asian_time = max(b["time"] for b in asian_bars)
    midpoint = (asian_high + asian_low) / 2.0
    asian_range_pct = (asian_high - asian_low) / midpoint * 100.0 if midpoint > 0 else 0.0

    # Prix actuel
    tick = mt5.symbol_info_tick(sym)
    if tick:
        current_price = float(tick.bid)
        current_time = float(tick.time)
        spread_pct = (tick.ask - tick.bid) / tick.bid * 100.0 if tick.bid > 0 else 0.0
    else:
        current_price = asian_bars[-1]["close"]
        current_time = time.time()
        spread_pct = 0.0

    # Williams fractals sur les barres asiatiques
    swing_points = detect_swing_points(asian_bars, FRACTAL_N)

    bsl_points: List[AsianSwingPoint] = []
    ssl_points: List[AsianSwingPoint] = []

    for sw in swing_points:
        dt = datetime.fromtimestamp(sw.time, UTC)
        sp = AsianSwingPoint(
            kind="BSL" if sw.kind == "high" else "SSL",
            level=sw.level,
            bar_time=sw.time,
            bar_time_str=dt.strftime("%H:%M"),
            bar_index=sw.bar_index,
            dist_pips=_pips(sym, current_price, sw.level),
        )
        if sw.kind == "high":
            bsl_points.append(sp)
        else:
            ssl_points.append(sp)

    # ── Sweeps post-Asian ──
    post_bars = [b for b in bars_raw if b["time"] > last_asian_time]

    def _is_bsl_sweep(bar: dict, lvl: float) -> bool:
        return bar["high"] > lvl and bar["close"] < lvl

    def _is_ssl_sweep(bar: dict, lvl: float) -> bool:
        return bar["low"] < lvl and bar["close"] > lvl

    for sp in bsl_points:
        for b in post_bars:
            if _is_bsl_sweep(b, sp.level):
                sp.swept = True
                sp.swept_at = b["time"]
                sp.swept_at_str = datetime.fromtimestamp(b["time"], UTC).strftime("%H:%M")
                sp.swept_session = _session_for_epoch(b["time"])[1]
                sp.swept_close = b["close"]
                break

    for sp in ssl_points:
        for b in post_bars:
            if _is_ssl_sweep(b, sp.level):
                sp.swept = True
                sp.swept_at = b["time"]
                sp.swept_at_str = datetime.fromtimestamp(b["time"], UTC).strftime("%H:%M")
                sp.swept_session = _session_for_epoch(b["time"])[1]
                sp.swept_close = b["close"]
                break

    all_swings = sorted(
        bsl_points + ssl_points,
        key=lambda s: s.level, reverse=True,
    )

    return SymbolAsianLiquidity(
        symbol=sym,
        symbol_type=_classify_symbol(sym),
        current_price=current_price,
        current_time=current_time,
        spread_pct=spread_pct,
        session_date=session_date,
        asian_high=asian_high,
        asian_low=asian_low,
        asian_range_pct=asian_range_pct,
        asian_bar_count=len(asian_bars),
        bsl_points=bsl_points,
        ssl_points=ssl_points,
        all_swings=all_swings,
    )


def scan_all_symbols(
    symbols: List[str],
    session_date: str,
    tf_name: str = "M15",
) -> List[SymbolAsianLiquidity]:
    """Scanne tous les symboles et retourne les résultats."""
    mt5c = MT5Connector()
    if not mt5c.ensure_connected():
        print(f"{RED}Connexion MT5 impossible.{RESET}", file=sys.stderr)
        return []

    results: List[SymbolAsianLiquidity] = []
    for i, sym in enumerate(symbols):
        try:
            r = analyze_symbol(mt5c, sym, session_date, tf_name)
            if r is not None:
                results.append(r)
        except Exception as e:
            logging.getLogger("asian_liq").debug("%s: erreur — %s", sym, e)

        if (i + 1) % 10 == 0 or i == len(symbols) - 1:
            print(f"\r  Scan... {i+1}/{len(symbols)}", end="", flush=True,
                  file=sys.stderr)
    print(file=sys.stderr)

    return results


# ── Rendu ───────────────────────────────────────────────────────────────────
def render_all_results(results: List[SymbolAsianLiquidity]) -> str:
    """Tableau complet pour tous les symboles."""
    lines: List[str] = []
    now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")

    n_bsl_total = sum(len(r.bsl_points) for r in results)
    n_ssl_total = sum(len(r.ssl_points) for r in results)
    n_swept = sum(sum(1 for s in r.all_swings if s.swept) for r in results)

    lines.append(f"{BOLD}{CYAN}{'='*110}{RESET}")
    lines.append(
        f"{BOLD}{CYAN}  🔍 ASIAN SESSION LIQUIDITY — BSL/SSL intra-Asian "
        f"(Williams Fractals, N={FRACTAL_N}){RESET}"
    )
    lines.append(f"{BOLD}{CYAN}{'='*110}{RESET}")
    lines.append(
        f"  {GRAY}UTC:{RESET} {now_str}  |  "
        f"{GRAY}Symboles:{RESET} {len(results)}  |  "
        f"{GRAY}BSL:{RESET} {GREEN}{n_bsl_total}{RESET}  |  "
        f"{GRAY}SSL:{RESET} {RED}{n_ssl_total}{RESET}  |  "
        f"{GRAY}Sweepés:{RESET} {YELLOW}{n_swept}{RESET}"
    )
    lines.append("")

    if not results:
        lines.append(f"{YELLOW}  Aucun symbole avec des barres asiatiques.{RESET}")
        return "\n".join(lines)

    # ── Résumé par symbole ──
    lines.append(f"{BOLD}{CYAN}═══ RÉSUMÉ PAR SYMBOLE ═══{RESET}")
    lines.append(
        f"{BOLD}{'Symbole':<12} {'Type':<12} {'AH':>11} {'AL':>11} "
        f"{'Now':>13} {'Spr%':>7} {'Range%':>7} {'#B':>4} "
        f"{'BSL':>4} {'SSL':>4} {'Swp':>4}{RESET}"
    )
    lines.append(f"{GRAY}{'─'*95}{RESET}")

    for r in results:
        n_swept_r = sum(1 for s in r.all_swings if s.swept)
        n_bsl = len(r.bsl_points)
        n_ssl = len(r.ssl_points)

        sp_col = (
            f"{GREEN}{r.spread_pct:.2f}%{RESET}" if r.spread_pct <= 0.10
            else f"{YELLOW}{r.spread_pct:.2f}%{RESET}" if r.spread_pct <= 0.30
            else f"{RED}{r.spread_pct:.2f}%{RESET}"
        )
        bsl_col = f"{GREEN}{n_bsl}{RESET}" if n_bsl > 0 else f"{GRAY}0{RESET}"
        ssl_col = f"{RED}{n_ssl}{RESET}" if n_ssl > 0 else f"{GRAY}0{RESET}"
        swept_col = f"{YELLOW}{n_swept_r}{RESET}" if n_swept_r > 0 else f"{GRAY}0{RESET}"

        lines.append(
            f"{MAGENTA}{r.symbol:<12}{RESET} "
            f"{DIM}{r.symbol_type:<12}{RESET} "
            f"{_fmt_price(r.asian_high):>11} {_fmt_price(r.asian_low):>11} "
            f"{_fmt_price(r.current_price):>13} "
            f"{_pad_cell(sp_col, 7)} "
            f"{r.asian_range_pct:>6.2f}% "
            f"{r.asian_bar_count:>4} "
            f"{_pad_cell(bsl_col, 4)} {_pad_cell(ssl_col, 4)} "
            f"{_pad_cell(swept_col, 4)}"
        )

    lines.append("")
    lines.append("")

    # ── Détail complet ──
    lines.append(f"{BOLD}{CYAN}═══ DÉTAIL BSL/SSL PAR SYMBOLE ═══{RESET}")
    lines.append("")

    for r in results:
        lines.append(
            f"{BOLD}{MAGENTA}─── {r.symbol} "
            f"({r.symbol_type}) "
            f"AH={_fmt_price(r.asian_high)} "
            f"AL={_fmt_price(r.asian_low)} "
            f"Now={_fmt_price(r.current_price)} "
            f"Range={r.asian_range_pct:.2f}% "
            f"───{RESET}"
        )

        if not r.all_swings:
            lines.append(f"  {GRAY}Aucun swing point détecté.{RESET}")
            lines.append("")
            continue

        lines.append(
            f"  {BOLD}{'Type':>5} {'Niveau':>12} {'UTC':>8} "
            f"{'Dist (pips)':>12} {'Statut':>24} {'Sweepé par':>14}{RESET}"
        )
        lines.append(f"  {GRAY}{'─'*80}{RESET}")

        for sp in r.all_swings:
            type_col = f"{GREEN}BSL ▲{RESET}" if sp.kind == "BSL" else f"{RED}SSL ▼{RESET}"

            dist_col = f"{DIM}{sp.dist_pips:+.1f}p{RESET}"

            if sp.swept:
                status_col = (
                    f"{RED}SWEEPÉ ←{RESET} "
                    f"{DIM}@{_fmt_price(sp.swept_close or 0)}{RESET}"
                )
            elif sp.kind == "BSL" and sp.level < r.current_price:
                status_col = f"{YELLOW}TRAVERSÉ (pas sweep){RESET}"
            elif sp.kind == "SSL" and sp.level > r.current_price:
                status_col = f"{YELLOW}TRAVERSÉ (pas sweep){RESET}"
            else:
                status_col = f"{GREEN}INTACT ✓{RESET}"

            sess_col = (
                f"{YELLOW}{sp.swept_session}{RESET}" if sp.swept_session
                else f"{GRAY}—{RESET}"
            )

            lines.append(
                f"  {_pad_cell(type_col, 5)} "
                f"{_fmt_price(sp.level):>12} "
                f"{sp.bar_time_str:>8} "
                f"{_pad_cell(dist_col, 12)} "
                f"{_pad_cell(status_col, 24)} "
                f"{_pad_cell(sess_col, 14)}"
            )

        lines.append("")

    # ── Résumé trading ──
    intact_bsl = sum(
        1 for r in results for s in r.bsl_points
        if not s.swept and s.level > r.current_price
    )
    intact_ssl = sum(
        1 for r in results for s in r.ssl_points
        if not s.swept and s.level < r.current_price
    )
    lines.append(f"{BOLD}{CYAN}{'='*110}{RESET}")
    lines.append(
        f"{BOLD}Résumé Trading :{RESET} "
        f"{GREEN}{intact_bsl} BSL intacts au-dessus{RESET} (cibles London ↑)  |  "
        f"{RED}{intact_ssl} SSL intacts en-dessous{RESET} (cibles London ↓)  |  "
        f"{YELLOW}{n_swept} déjà sweepés{RESET}"
    )

    return "\n".join(lines)


def results_to_json(results: List[SymbolAsianLiquidity]) -> list:
    """Convertit les résultats en liste JSON-sérialisable."""
    out = []
    for r in results:
        swings = []
        for sp in r.all_swings:
            swings.append({
                "kind": sp.kind,
                "level": sp.level,
                "bar_time_utc": datetime.fromtimestamp(sp.bar_time, UTC).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "swept": sp.swept,
                "swept_at_utc": (
                    datetime.fromtimestamp(sp.swept_at, UTC).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ) if sp.swept_at else None
                ),
                "swept_session": sp.swept_session,
                "dist_pips": round(sp.dist_pips, 1),
            })
        out.append({
            "symbol": r.symbol,
            "symbol_type": r.symbol_type,
            "current_price": r.current_price,
            "spread_pct": round(r.spread_pct, 4),
            "session_date": r.session_date,
            "asian_high": r.asian_high if r.asian_bar_count > 0 else None,
            "asian_low": r.asian_low if r.asian_bar_count > 0 else None,
            "asian_range_pct": round(r.asian_range_pct, 4),
            "asian_bar_count": r.asian_bar_count,
            "n_bsl": len(r.bsl_points),
            "n_ssl": len(r.ssl_points),
            "n_swept": sum(1 for s in r.all_swings if s.swept),
            "swings": swings,
        })
    return out


# ── Main standalone ─────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="🔍 Asian Session BSL/SSL Liquidity Scanner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--symbols", nargs="*", default=None,
        help="Liste de symboles (défaut: watchlist configurée)",
    )
    parser.add_argument(
        "--tf", default="M15",
        choices=["M1", "M5", "M15", "M30", "H1"],
        help="Timeframe (défaut: M15)",
    )
    parser.add_argument(
        "--date", default=None,
        help="Date YYYY-MM-DD (défaut: aujourd'hui UTC)",
    )
    parser.add_argument(
        "--scan-all", action="store_true",
        help="Scanner TOUS les symboles MT5",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Sortie JSON au lieu du tableau ASCII",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Logging DEBUG",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")

    session_date = args.date or datetime.now(UTC).strftime("%Y-%m-%d")

    if args.scan_all:
        mt5c = MT5Connector()
        if not mt5c.ensure_connected():
            print(f"{RED}Connexion MT5 impossible.{RESET}", file=sys.stderr)
            return 1
        symbols = mt5c.list_all_symbols()
        print(f"{YELLOW}Scan de TOUS les symboles ({len(symbols)})...{RESET}",
              file=sys.stderr)
    else:
        symbols = resolve_watchlist(args.symbols)

    if not symbols:
        print("Aucun symbole à analyser.", file=sys.stderr)
        return 1

    results = scan_all_symbols(symbols, session_date, args.tf.upper())

    if args.json:
        print(json.dumps(results_to_json(results), indent=2, ensure_ascii=False))
    else:
        print(render_all_results(results))

    return 0


if __name__ == "__main__":
    sys.exit(main())
