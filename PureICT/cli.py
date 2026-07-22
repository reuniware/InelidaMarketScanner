#!/usr/bin/env python
"""PureICT — CLI : point d'entree principal du scanner asiatique.

Usage :
  python -m PureICT.cli
  python PureICT/cli.py
  python PureICT/scan_asian_session.py (entry point heritage)
"""

import argparse
import logging
import os
import sys
from datetime import timedelta
from typing import List, Tuple

# Chemin projet
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from .config import (
    DEFAULT_START_HOUR, DEFAULT_END_HOUR, DEFAULT_TIMEZONE,
    TIMEFRAMES, DEFAULT_TF, DEFAULT_FVG_MIN_PCT,
    _tz_offset, _session_true_utc_end,
    is_in_asian_session, _smart_session_date,
    paris_now,
)
from .scanner import scan_all_symbols
from .display import display_results, display_exclusions, export_csv, export_json
from src.time_utils import now_datetime

from .live import live_monitor

logger = logging.getLogger("PureICT.CLI")


# ===============================================================================
# CLI
# ===============================================================================

def build_parser() -> argparse.ArgumentParser:
    """Construit le parseur d'arguments CLI."""
    parser = argparse.ArgumentParser(
        description="PureICT - Scan Session Asiatique (niveaux AH/AL/Mid)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
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
                        help="Inclure la session precedente (figee).")
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
                             "Peut etre utilise plusieurs fois.")
    parser.add_argument("--timeframe", "-tf", default=DEFAULT_TF,
                        choices=list(TIMEFRAMES.keys()),
                        help=f"Timeframe pour les bougies. Defaut: {DEFAULT_TF}.")
    parser.add_argument("--market-watch", action="store_true",
                        help="Utiliser uniquement les symboles visibles dans Market Watch.")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Mode verbeux (logs debug).")
    parser.add_argument("--live", "-l", action="store_true",
                        help="Mode live : rafraichit le prix en continu (Ctrl+C pour quitter).")
    parser.add_argument("--interval", "-i", type=int, default=10,
                        help="Intervalle de rafraichissement en secondes (defaut: 10s).")
    parser.add_argument("--force-select", action="store_true",
                        help="Pre-active tous les symboles dans Market Watch avant le scan.")
    parser.add_argument("--fvg", action="store_true",
                        help="Active la detection des FVGs pres AH/AL.")
    parser.add_argument("--fvg-min", type=float, default=DEFAULT_FVG_MIN_PCT,
                        help=f"Taille minimum du FVG en %% (defaut: {DEFAULT_FVG_MIN_PCT}%%).")
    parser.add_argument("--ote", action="store_true",
                        help="Affiche la zone OTE (retracement 0.618-0.382).")
    parser.add_argument("--swept-only", action="store_true",
                        help="Filtre les resultats pour n'afficher que les symboles "
                             "ou un sweep AH ou AL a ete detecte.")
    parser.add_argument("--json", default=None,
                        help="Exporte les resultats au format JSON (chemin du fichier). "
                             "Compatible avec --export.")
    return parser


def main(argv: List[str] = None) -> int:
    """Point d'entree principal du scanner PureICT.

    Args:
        argv: Arguments CLI (defaut: sys.argv[1:]).

    Returns:
        Code de sortie (0 = OK, 1 = erreur, 2 = pas de donnees).
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    print()
    print()
    print("  ====== PureICT ======")
    print("  Asian Session Scan")
    print("  =====================")
    print()

    offset = _tz_offset(args.timezone)

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

    true_end_utc = _session_true_utc_end(session_date, args.end_hour, args.timezone)
    true_start_utc = true_end_utc - timedelta(hours=(args.end_hour - args.start_hour))
    print(f"  Intervalle UTC : {true_start_utc.strftime('%Y-%m-%d %H:%M')} -> {true_end_utc.strftime('%H:%M')}")
    print(f"  Heure {args.timezone} : {paris_now().strftime('%H:%M:%S')}")

    in_session = is_in_asian_session(args.start_hour, args.end_hour, args.timezone)
    print(f"  {'(Session en cours)' if in_session else '(Session terminee)'}")
    if in_session:
        fin = true_end_utc.strftime('%H:%M')
        remaining = (true_end_utc - now_datetime()).total_seconds()
        print(f"  Fin de session dans ~{remaining:.0f}s ({fin} UTC)")

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
        print("  Aucune donnee asiatique trouvee.")
        print("  Verifie que MT5 est connecte et que les symboles sont disponibles.")
        return 1

    # -- Filtre --swept-only --
    if args.swept_only:
        n_before = len(current)
        current = [r for r in current if r.ah_swept or r.al_swept]
        n_after = len(current)
        n_filtre = n_before - n_after
        if n_filtre > 0:
            print(f"  Filtre --swept-only : {n_after} symbole(s) avec sweep / {n_filtre} exclus")
        elif n_before == 0:
            print("  Aucun symbole avec sweep detecte.")
        else:
            print(f"  Filtre --swept-only : tous les {n_after} symboles ont un sweep.")
        if not current:
            print("  Aucun resultat apres filtrage --swept-only.")
            return 1

    if args.live:
        if args.export or args.json:
            print("  !! --live est incompatible avec --export et --json, les exports sont ignores.\n")
        live_monitor(current, args.timezone, args.interval, show_ote=args.ote)
        return 0

    display_results(current, previous if args.previous else None, args.timezone,
                    is_previous_session=is_previous, show_ote=args.ote)

    if excluded and args.verbose:
        display_exclusions(excluded, len(current))
    elif excluded and not args.verbose:
        reasons = {}
        for _, reason in excluded:
            reasons[reason] = reasons.get(reason, 0) + 1
        resume = ", ".join(f"{n}x {r}" for r, n in sorted(reasons.items()))
        print(f"\n  {len(excluded)} symbole(s) exclus ({resume})")
        print("  Utilise --verbose (-v) pour voir le detail.")

    if args.export:
        export_csv(current, args.export)
    if args.json:
        export_json(current, args.json)

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
