"""PureICT — Affichage des resultats et export CSV/JSON.

Dependances :
  - PureICT.models, PureICT.config
  - src.config.format_epoch (importe comme _fmt_epoch_tz)
  - src.time_utils.now_datetime
"""

import csv
import json
import logging
import os
import sys
from dataclasses import asdict, fields
from datetime import timedelta
from typing import List, Optional, Tuple

# Chemin projet
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.config import format_epoch as _fmt_epoch_tz
from src.time_utils import now_datetime

from .models import AsianLevels, PreviousAsianLevels, fmt_price
from .config import (
    DEFAULT_TIMEZONE, _tz_offset,
)

logger = logging.getLogger("PureICT.Display")


# ===============================================================================
# TABLEAU PRINCIPAL
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

    results.sort(key=lambda r: r.symbol)
    n_total = len(results)
    n_live = sum(1 for r in results if r.is_live)
    offset = _tz_offset(tz_mode)
    local_now = now_datetime() + timedelta(hours=offset)

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

    _has_margin_info = any(r.max_lots is not None for r in results)

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
               f"{'AL':>12} {'@UTC':>7} {'@Paris':>9} {'@Bkr':>9}")
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
    print("  TZ: UTC / Paris / Broker  |  Live = session en cours (donnees partielles)")
    if _has_margin_info:
        currency = next((r.account_currency for r in results if r.account_currency), "")
        dev_label = f" {currency}" if currency else ""
        print(f"  LotsMax = lots max negociables (marge libre{dev_label})  |  Marge/Lot = marge requise pour 1 lot{dev_label}")

    _print_fibonacci(results)
    if show_ote:
        _print_ote(results)
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
    print("  -- Extensions Fibonacci (depuis le midpoint) --")
    sep = "  " + "-" * 140
    print(sep)
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
            row += f" {fmt_price(getattr(r, key, 0.0)):>12}"
        row += "  |"
        for key in fib_dn_keys:
            row += f" {fmt_price(getattr(r, key, 0.0)):>12}"
        print(row)
    print(sep)


def _print_ote(results: List[AsianLevels]):
    """Affiche la zone OTE (Optimal Trade Entry 0.618-0.382) pour chaque symbole."""
    ote_results = [r for r in results if r.range_pips > 0]
    if not ote_results:
        return

    print()
    print("  -- OTE (Optimal Trade Entry) : retracement 0.618-0.382 --")
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
        bear_zone = "[Z]" if r.in_ote_bear else "   "
        bull_zone = "[Z]" if r.in_ote_bull else "   "
        print(f"  {r.symbol:<14}"
              f"{range_str:>10} "
              f"{fmt_price(r.asian_high):>12} {fmt_price(r.asian_low):>12} "
              f"{fmt_price(r.ote_bear_high):>12} {fmt_price(r.ote_bear_low):>12} {bear_zone:>5} "
              f"{fmt_price(r.ote_bull_high):>12} {fmt_price(r.ote_bull_low):>12} {bull_zone:>5} "
              f"{fmt_price(r.current_price):>12}")

    print(sep)
    print("  BZ = Prix dans la zone OTE  |  Bear zone = retracement 38.2%-61.8% depuis AH vers AL")
    print("                                   Bull zone = retracement 38.2%-61.8% depuis AL vers AH")


def _print_previous(previous: List[PreviousAsianLevels]):
    """Affiche la session precedente (figee)."""
    if not previous:
        return
    previous.sort(key=lambda p: -p.range_pips)

    print()
    print(f"  -- Session PRECEDENTE ({previous[0].session_date}) - Figee --")
    print("  (Equivalent des lignes var du Pine Script)")
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


# ===============================================================================
# EXCLUSIONS
# ===============================================================================

def display_exclusions(excluded: List[Tuple[str, str]], scanned_count: int):
    """Affiche le tableau des symboles exclus avec la raison."""
    if not excluded:
        return

    by_reason: dict = {}
    for sym, reason in excluded:
        by_reason.setdefault(reason, []).append(sym)

    print()
    print(f"  -- Symboles EXCLUS du scan ({len(excluded)} exclus / {scanned_count} retenus) --")
    sep = "  " + "-" * 80
    print(sep)
    print(f"  {'Symbole':<30} {'Raison':<45}")
    print(sep)

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


# ===============================================================================
# EXPORT CSV / JSON
# ===============================================================================

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
    """Exporte les resultats en JSON."""
    if not results:
        print("  Aucun resultat a exporter.")
        return
    data = [asdict(r) for r in results]
    for d in data:
        for k, v in d.items():
            if isinstance(v, float) and (v != v):
                d[k] = None
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"\n  \u2705 {len(results)} symboles exportes -> {os.path.abspath(filepath)}")
