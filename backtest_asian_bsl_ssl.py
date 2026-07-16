#!/usr/bin/env python3
"""
Backtest — Asian BSL/SSL → London Sweep → Continuation vers l'autre liquidite
==============================================================================
Sur les 30 derniers jours, pour chaque symbole :
  1. Detecte les BSL (swing highs) et SSL (swing lows) crees en session Asian
  2. Verifie lesquels sont sweepes par London (08:00-13:00 UTC, def. ICT)
  3. Mesure si le prix continue vers l'autre liquidite apres le sweep :
     → BSL sweepe = signal bearish → cible AL (Asian Low)
     → SSL sweepe  = signal bullish  → cible AH (Asian High)

Usage:
    python backtest_asian_bsl_ssl.py
    python backtest_asian_bsl_ssl.py --days 60 --symbols XAUUSD EURUSD
    python backtest_asian_bsl_ssl.py --days 30 --scan-all
"""

import argparse
import json
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from src.config import resolve_watchlist
from src.mt5_connector import MT5Connector
from src.sweep_detector import detect_swing_points, _bars_to_dicts
from src.display import (
    _fmt_price, _pad_cell,
    RESET, BOLD, DIM, RED, GREEN, YELLOW, CYAN, MAGENTA, GRAY,
)

try:
    from src.diamond_scanner import DiamondScanner
    def _pips(sym: str, price: float, level: float) -> float:
        return DiamondScanner._pips(DiamondScanner, sym, price, level)
except ImportError:
    def _pips(sym: str, price: float, level: float) -> float:
        if 'JPY' in sym and 'XAU' not in sym:
            return (price - level) * 100
        elif 'XAU' in sym:
            return (price - level) * 10
        elif 'XAG' in sym:
            return (price - level) * 100
        elif '.cash' in sym:
            return price - level
        return (price - level) * 10000

UTC = timezone.utc
FRACTAL_N = 2
DEFAULT_TF = "M15"

# Sessions UTC
ASIAN_START, ASIAN_END = 0, 8
LONDON_START, LONDON_END = 8, 13

try:
    import MetaTrader5 as _mt5
    _TF_MAP: Dict[str, int] = {
        "M15": _mt5.TIMEFRAME_M15, "M5": _mt5.TIMEFRAME_M5,
        "M1": _mt5.TIMEFRAME_M1, "M30": _mt5.TIMEFRAME_M30,
        "H1": _mt5.TIMEFRAME_H1,
    }
except ImportError:
    _TF_MAP = {}


@dataclass
class DayResult:
    """Resultat pour un symbole sur un jour."""
    symbol: str
    date: str
    asian_high: float = 0.0
    asian_low: float = 0.0
    range_pct: float = 0.0
    bsl_created: int = 0       # swing highs dans Asian
    ssl_created: int = 0       # swing lows dans Asian
    bsl_swept_london: int = 0  # BSL sweepes par London
    ssl_swept_london: int = 0  # SSL sweepes par London
    bsl_hit_target: int = 0    # BSL sweepe → prix touche AL
    ssl_hit_target: int = 0    # SSL sweepe  → prix touche AH
    details: List[dict] = field(default_factory=list)


@dataclass
class SymbolSummary:
    """Resume agrege pour un symbole sur toute la periode."""
    symbol: str = ""
    days_with_data: int = 0
    bsl_total: int = 0
    ssl_total: int = 0
    bsl_swept: int = 0
    ssl_swept: int = 0
    bsl_sweep_hit_al: int = 0
    ssl_sweep_hit_ah: int = 0

    @property
    def bsl_sweep_rate(self) -> float:
        return self.bsl_swept / self.bsl_total * 100 if self.bsl_total > 0 else 0.0

    @property
    def ssl_sweep_rate(self) -> float:
        return self.ssl_swept / self.ssl_total * 100 if self.ssl_total > 0 else 0.0

    @property
    def bsl_continuation_rate(self) -> float:
        return self.bsl_sweep_hit_al / self.bsl_swept * 100 if self.bsl_swept > 0 else 0.0

    @property
    def ssl_continuation_rate(self) -> float:
        return self.ssl_sweep_hit_ah / self.ssl_swept * 100 if self.ssl_swept > 0 else 0.0


def _pips(sym: str, price: float, level: float) -> float:
    if 'JPY' in sym and 'XAU' not in sym:
        return (price - level) * 100
    elif 'XAU' in sym:
        return (price - level) * 10
    elif 'XAG' in sym:
        return (price - level) * 100
    elif '.cash' in sym:
        return price - level
    return (price - level) * 10000


def _bars_to_dicts(rates) -> List[dict]:
    out = []
    for r in rates:
        out.append({
            "time": int(r[0]), "open": float(r[1]),
            "high": float(r[2]), "low": float(r[3]),
            "close": float(r[4]),
        })
    return out


def _is_bsl_sweep(bar: dict, lvl: float) -> bool:
    """Sweep ICT : wick au-dessus + close en-dessous = BSL pris."""
    return bar["high"] > lvl and bar["close"] < lvl


def _is_ssl_sweep(bar: dict, lvl: float) -> bool:
    """Sweep ICT : wick en-dessous + close au-dessus = SSL pris."""
    return bar["low"] < lvl and bar["close"] > lvl


def analyze_day(
    mt5_mod, sym: str, date_str: str, tf_name: str = DEFAULT_TF
) -> Optional[DayResult]:
    """Analyse un jour complet pour un symbole.

    Utilise copy_rates_range (range de dates) pour auto-telecharger
    l'historique manquant depuis le serveur du broker.
    """
    import MetaTrader5 as _mt5
    tf = _TF_MAP.get(tf_name.upper(), _mt5.TIMEFRAME_M15)

    # Supporte les deux modes : module MT5 direct ou MT5Connector
    if hasattr(mt5_mod, 'select_symbol'):
        mt5_mod.select_symbol(sym)
    else:
        _mt5.symbol_select(sym, True)

    # Telechargement par range de dates exacte.
    # copy_rates_range(start, end) retourne les barres DANS l'intervalle.
    # Attention: copy_rates_from(date, count) retourne les barres AVANT date,
    # pas apres — d'ou l'utilisation de copy_rates_range qui est correcte.
    try:
        start_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(
            hour=0, minute=0, second=0, tzinfo=UTC)
        end_dt = start_dt.replace(hour=23, minute=59, second=59)
    except ValueError:
        return None

    rates = _mt5.copy_rates_range(sym, tf, start_dt, end_dt)

    # Fallback : si copy_rates_range echoue, utiliser le cache local
    if rates is None or len(rates) < 30:
        rates = _mt5.copy_rates_from_pos(sym, tf, 0, 500)
    if rates is None or len(rates) < 30:
        return None

    bars = _bars_to_dicts(rates)
    bars.sort(key=lambda b: b["time"])

    # Filtrer par date
    day_bars = [b for b in bars if datetime.fromtimestamp(
        b["time"], UTC).strftime("%Y-%m-%d") == date_str]
    if len(day_bars) < 5:
        return None

    # Extraire Asian (00-08 UTC) et London (08-13 UTC)
    asian_bars, london_bars, day_bars_all = [], [], []
    for b in day_bars:
        h = (b["time"] % 86400) // 3600
        if ASIAN_START <= h < ASIAN_END:
            asian_bars.append(b)
        elif LONDON_START <= h < LONDON_END:
            london_bars.append(b)
        day_bars_all.append(b)

    if len(asian_bars) < 2 * FRACTAL_N + 1:
        return None

    ah = max(b["high"] for b in asian_bars)
    al = min(b["low"] for b in asian_bars)
    midpoint = (ah + al) / 2.0
    range_pct = (ah - al) / midpoint * 100.0 if midpoint > 0 else 0.0

    # Swing points dans Asian
    swings = detect_swing_points(asian_bars, FRACTAL_N)
    bsl_swings = [(s.level, s.bar_index, s.time) for s in swings if s.kind == "high"]
    ssl_swings = [(s.level, s.bar_index, s.time) for s in swings if s.kind == "low"]

    # Verifier sweeps London
    bsl_swept_info = []  # (level, sweep_close, sweep_time)
    ssl_swept_info = []

    for level, _, _ in bsl_swings:
        for b in london_bars:
            if _is_bsl_sweep(b, level):
                bsl_swept_info.append((level, b["close"], b["time"]))
                break

    for level, _, _ in ssl_swings:
        for b in london_bars:
            if _is_ssl_sweep(b, level):
                ssl_swept_info.append((level, b["close"], b["time"]))
                break

    # Verifier continuation apres sweep : on regarde TOUTES les barres du jour
    # posterieures au sweep (pas seulement London).
    # Note: le sweep bar lui-meme est exclu (time > sweep_time) — on ne compte
    # que la continuation STRICTEMENT apres le signal, pas sur la meme bougie.
    bsl_hit = 0
    for lvl, sweep_close, sweep_time in bsl_swept_info:
        for b in day_bars_all:
            if b["time"] > sweep_time and b["low"] <= al:
                bsl_hit += 1
                break

    ssl_hit = 0
    for lvl, sweep_close, sweep_time in ssl_swept_info:
        for b in day_bars_all:
            if b["time"] > sweep_time and b["high"] >= ah:
                ssl_hit += 1
                break

    # Details
    details = []
    for lvl, sw_close, sw_time in bsl_swept_info:
        dt = datetime.fromtimestamp(sw_time, UTC).strftime("%H:%M")
        details.append({
            "type": "BSL", "level": lvl, "sweep_time_utc": dt,
            "sweep_close": sw_close,
            "target": al, "target_label": "AL",
        })
    for lvl, sw_close, sw_time in ssl_swept_info:
        dt = datetime.fromtimestamp(sw_time, UTC).strftime("%H:%M")
        details.append({
            "type": "SSL", "level": lvl, "sweep_time_utc": dt,
            "sweep_close": sw_close,
            "target": ah, "target_label": "AH",
        })

    return DayResult(
        symbol=sym, date=date_str,
        asian_high=ah, asian_low=al, range_pct=range_pct,
        bsl_created=len(bsl_swings), ssl_created=len(ssl_swings),
        bsl_swept_london=len(bsl_swept_info), ssl_swept_london=len(ssl_swept_info),
        bsl_hit_target=bsl_hit, ssl_hit_target=ssl_hit,
        details=details,
    )


def run_backtest(symbols: List[str], days: int, tf_name: str = DEFAULT_TF
                 ) -> Tuple[List[DayResult], Dict[str, SymbolSummary]]:
    """Execute le backtest complet."""
    import MetaTrader5 as mt5

    # Utiliser mt5.initialize() directement pour eviter les conflits MT5Connector
    if not mt5.initialize():
        print(f"{RED}MT5 initialize() failed: {mt5.last_error()}{RESET}", file=sys.stderr)
        return [], {}

    today = datetime.now(UTC).date()
    all_results: List[DayResult] = []
    summaries: Dict[str, SymbolSummary] = defaultdict(SymbolSummary)
    errors = 0

    for d_offset in range(days, 0, -1):
        date_obj = today - timedelta(days=d_offset)
        date_str = date_obj.strftime("%Y-%m-%d")

        for sym in symbols:
            try:
                r = analyze_day(mt5, sym, date_str, tf_name)
                if r is not None and (r.bsl_created > 0 or r.ssl_created > 0):
                    all_results.append(r)
                    s = summaries[sym]
                    s.symbol = sym
                    s.days_with_data += 1
                    s.bsl_total += r.bsl_created
                    s.ssl_total += r.ssl_created
                    s.bsl_swept += r.bsl_swept_london
                    s.ssl_swept += r.ssl_swept_london
                    s.bsl_sweep_hit_al += r.bsl_hit_target
                    s.ssl_sweep_hit_ah += r.ssl_hit_target
            except Exception as e:
                errors += 1
                if errors <= 3:
                    print(f"  {RED}Err {sym} {date_str}: {e}{RESET}", file=sys.stderr)

        if d_offset % 2 == 0 or d_offset == 1:
            print(f"\r  Backtest... {days - d_offset + 1}/{days} jours "
                  f"({len(all_results)} setups trouves)",
                  end="", flush=True, file=sys.stderr)
    print(file=sys.stderr)
    if errors:
        print(f"{YELLOW}  {errors} erreurs ignorees.{RESET}", file=sys.stderr)

    return all_results, dict(summaries)


def render_results(all_results: List[DayResult], summaries: Dict[str, SymbolSummary],
                   days: int, tf_name: str) -> str:
    """Affiche les resultats du backtest."""
    lines = []
    now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")

    # Totaux globaux
    tot_bsl = sum(s.bsl_total for s in summaries.values())
    tot_ssl = sum(s.ssl_total for s in summaries.values())
    tot_bsl_swept = sum(s.bsl_swept for s in summaries.values())
    tot_ssl_swept = sum(s.ssl_swept for s in summaries.values())
    tot_bsl_hit = sum(s.bsl_sweep_hit_al for s in summaries.values())
    tot_ssl_hit = sum(s.ssl_sweep_hit_ah for s in summaries.values())

    bsl_sweep_rate = tot_bsl_swept / tot_bsl * 100 if tot_bsl > 0 else 0
    ssl_sweep_rate = tot_ssl_swept / tot_ssl * 100 if tot_ssl > 0 else 0
    bsl_cont_rate = tot_bsl_hit / tot_bsl_swept * 100 if tot_bsl_swept > 0 else 0
    ssl_cont_rate = tot_ssl_hit / tot_ssl_swept * 100 if tot_ssl_swept > 0 else 0

    # En-tete
    lines.append(f"{BOLD}{CYAN}{'='*110}{RESET}")
    lines.append(f"{BOLD}{CYAN}  BACKTEST — Asian BSL/SSL → London Sweep → Continuation{RESET}")
    lines.append(f"{BOLD}{CYAN}{'='*110}{RESET}")
    lines.append(
        f"  {GRAY}UTC:{RESET} {now_str}  |  {GRAY}TF:{RESET} {tf_name}  |  "
        f"{GRAY}Periode:{RESET} {days} jours  |  {GRAY}Symboles:{RESET} {len(summaries)}  |  "
        f"{GRAY}Jours avec data:{RESET} {len(set(r.date for r in all_results))}"
    )
    lines.append("")
    lines.append(
        f"  {GRAY}Regles:{RESET} BSL/SSL = Williams fractals N=2 sur barres Asian (00-08 UTC).  "
        f"London = 08-13 UTC.  Continuation = prix atteint l'autre liquidite."
    )
    lines.append("")

    # ── Resume global ──
    lines.append(f"{BOLD}{CYAN}═══ RESULTATS GLOBAUX ═══{RESET}")
    lines.append("")
    lines.append(f"  {BOLD}BSL (Swing Highs → Bearish){RESET}")
    lines.append(
        f"    Crees: {tot_bsl}  |  Sweepes par London: {GREEN}{tot_bsl_swept}{RESET} "
        f"({bsl_sweep_rate:.1f}%)  |  "
        f"Ont touche AL: {RED if bsl_cont_rate < 50 else GREEN}{tot_bsl_hit}{RESET} "
        f"({bsl_cont_rate:.1f}% continuation)"
    )
    lines.append("")
    lines.append(f"  {BOLD}SSL (Swing Lows → Bullish){RESET}")
    lines.append(
        f"    Crees: {tot_ssl}  |  Sweepes par London: {RED}{tot_ssl_swept}{RESET} "
        f"({ssl_sweep_rate:.1f}%)  |  "
        f"Ont touche AH: {GREEN if ssl_cont_rate > 50 else RED}{tot_ssl_hit}{RESET} "
        f"({ssl_cont_rate:.1f}% continuation)"
    )
    lines.append("")

    # ── Par symbole ──
    lines.append(f"{BOLD}{CYAN}═══ DETAIL PAR SYMBOLE ═══{RESET}")
    lines.append(
        f"{BOLD}{'Symbole':<12} {'Jours':>5} "
        f"{'BSL crees':>9} {'BSL swp':>7} {'%swp':>6} {'→AL':>4} {'%cont':>6}  "
        f"{'SSL crees':>9} {'SSL swp':>7} {'%swp':>6} {'→AH':>4} {'%cont':>6}{RESET}"
    )
    lines.append(f"{GRAY}{'─'*100}{RESET}")

    for sym in sorted(summaries.keys()):
        s = summaries[sym]

        def _pct_cell(val: float, threshold: float = 40) -> str:
            c = f"{val:.0f}%"
            if val >= 60:
                return f"{GREEN}{c}{RESET}"
            elif val >= threshold:
                return f"{YELLOW}{c}{RESET}"
            return f"{RED}{c}{RESET}"

        lines.append(
            f"{MAGENTA}{sym:<12}{RESET} {s.days_with_data:>5} "
            f"{s.bsl_total:>9} {s.bsl_swept:>7} "
            f"{_pad_cell(_pct_cell(s.bsl_sweep_rate), 6)} "
            f"{s.bsl_sweep_hit_al:>4} "
            f"{_pad_cell(_pct_cell(s.bsl_continuation_rate), 6)}  "
            f"{s.ssl_total:>9} {s.ssl_swept:>7} "
            f"{_pad_cell(_pct_cell(s.ssl_sweep_rate), 6)} "
            f"{s.ssl_sweep_hit_ah:>4} "
            f"{_pad_cell(_pct_cell(s.ssl_continuation_rate), 6)}"
        )

    lines.append("")
    lines.append(f"{BOLD}{CYAN}{'='*110}{RESET}")

    # Verdict
    lines.append(f"{BOLD}VERDICT :{RESET}")
    if bsl_cont_rate >= 55:
        lines.append(
            f"  {GREEN}BSL sweepe → continuation vers AL : {bsl_cont_rate:.1f}% "
            f"(EDGE positif){RESET}"
        )
    else:
        lines.append(
            f"  {RED}BSL sweepe → continuation vers AL : {bsl_cont_rate:.1f}% "
            f"(pas d'edge){RESET}"
        )
    if ssl_cont_rate >= 55:
        lines.append(
            f"  {GREEN}SSL sweepe  → continuation vers AH : {ssl_cont_rate:.1f}% "
            f"(EDGE positif){RESET}"
        )
    else:
        lines.append(
            f"  {RED}SSL sweepe  → continuation vers AH : {ssl_cont_rate:.1f}% "
            f"(pas d'edge){RESET}"
        )

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Backtest Asian BSL/SSL → London Sweep → Continuation",
    )
    parser.add_argument("--days", type=int, default=30,
                        help="Nombre de jours de backtest (defaut: 30)")
    parser.add_argument("--symbols", nargs="*", default=None,
                        help="Symboles (defaut: watchlist)")
    parser.add_argument("--tf", default=DEFAULT_TF,
                        choices=["M1", "M5", "M15", "M30", "H1"],
                        help="Timeframe (defaut: M15)")
    parser.add_argument("--scan-all", action="store_true",
                        help="Scanner tous les symboles MT5")
    parser.add_argument("--json", action="store_true",
                        help="Sortie JSON")
    args = parser.parse_args()

    if args.scan_all:
        mt5c = MT5Connector()
        if not mt5c.ensure_connected():
            print(f"{RED}Connexion MT5 impossible.{RESET}", file=sys.stderr)
            return 1
        symbols = mt5c.list_all_symbols()
        print(f"{YELLOW}Backtest de TOUS les symboles ({len(symbols)}) "
              f"sur {args.days} jours...{RESET}", file=sys.stderr)
    else:
        symbols = resolve_watchlist(args.symbols)

    if not symbols:
        print("Aucun symbole.", file=sys.stderr)
        return 1

    t0 = time.time()
    all_results, summaries = run_backtest(symbols, args.days, args.tf.upper())
    elapsed = time.time() - t0
    print(f"{GRAY}Backtest termine en {elapsed:.1f}s.{RESET}", file=sys.stderr)

    if args.json:
        out = {
            "params": {"days": args.days, "tf": args.tf, "fractal_n": FRACTAL_N},
            "summaries": {
                sym: {
                    "days_with_data": s.days_with_data,
                    "bsl_total": s.bsl_total,
                    "bsl_swept": s.bsl_swept,
                    "bsl_sweep_rate_pct": round(s.bsl_sweep_rate, 1),
                    "bsl_hit_al": s.bsl_sweep_hit_al,
                    "bsl_continuation_rate_pct": round(s.bsl_continuation_rate, 1),
                    "ssl_total": s.ssl_total,
                    "ssl_swept": s.ssl_swept,
                    "ssl_sweep_rate_pct": round(s.ssl_sweep_rate, 1),
                    "ssl_hit_ah": s.ssl_sweep_hit_ah,
                    "ssl_continuation_rate_pct": round(s.ssl_continuation_rate, 1),
                }
                for sym, s in summaries.items()
            },
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        print(render_results(all_results, summaries, args.days, args.tf.upper()))

    return 0


if __name__ == "__main__":
    sys.exit(main())
