"""
Point d'entrée CLI du scanner de marché temps réel InelidaMarketScanner.
Modes disponibles :
  - snapshot  : une capture ponctuelle puis sortie
  - watch     : boucle continue jusqu'à Ctrl+C
  - watchlist : affiche simplement la watchlist configurée
  - account   : affiche les infos du compte MT5
  - terminal  : affiche les infos du terminal MT5
  - sweeps    : scan Market Watch pour BSL/SSL sweeps (ICT fractals)
  - asian     : scan range session asiatique + sweeps post-Asian (ICT)
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime as _dt

from src.config import (
    DB, MT5, OUT, SWEEP, ASIAN, resolve_watchlist, DEFAULT_WATCHLIST,
)
from src.mt5_connector import MT5Connector
from src.market_scanner import MarketScanner
from src.display import (
    render_snapshot,
    render_sweeps, render_sweeps_plain, make_display,
    render_asian_ranges, render_asian_ranges_plain,
    _fmt_price,
    RESET, BOLD, DIM, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, GRAY,
)
from src.database import get_db
from src.sweep_detector import (
    detect_sweeps_for_symbol,
    scan_market_watch_for_sweeps,
    sort_events,
    events_to_dicts,
    detect_asian_range_for_symbol,
    scan_market_watch_asian_ranges,
    asians_to_dicts,
    detect_daily_levels_for_symbol,
    detect_weekly_levels_for_symbol,
    scan_market_watch_levels,
)
from src.trade_executor import (
    TradeExecutor,
    TradeDecision,
    TradeResult,
    INELIDA_MAGIC,
    asian_to_decisions,
)


def _setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    for name in ("MT5Connector", "MarketScanner", "SweepDetector"):
        logging.getLogger(name).setLevel(
            logging.DEBUG if verbose else logging.INFO
        )


def _print_snapshot_json(scanner: MarketScanner, snap: dict) -> None:
    out = {sym: {
        "bid": s.bid, "ask": s.ask, "last": s.last,
        "spread": s.spread, "spread_points": s.spread_points,
        "bid_delta": s.bid_delta, "bid_pct": s.bid_pct,
        "ask_delta": s.ask_delta, "ask_pct": s.ask_pct,
        "last_pct": s.last_pct,
        "time": s.time,
    } for sym, s in snap.items()}
    print(json.dumps(out, indent=2, ensure_ascii=False))


# ─── Commandes CLI ───────────────────────────────────────────────────────────
def cmd_snapshot(args):
    _setup_logging(args.verbose)
    symbols = resolve_watchlist(args.symbols)
    if not symbols:
        print("Aucune watchlist. Spécifie --symbols ou configure INELIDA_WATCHLIST.")
        return 1

    scanner = MarketScanner(symbols)
    if not scanner.prepare():
        return 2

    try:
        snap = scanner.scan_once()
        if args.json:
            _print_snapshot_json(scanner, snap)
        else:
            print(render_snapshot(scanner, snap, show_header=True))
            print(f"\n{GREEN}Capture ponctuelle OK ({len(snap)} symboles).{RESET}")
    finally:
        scanner.shutdown()
    return 0


def cmd_watch(args):
    _setup_logging(args.verbose)
    symbols = resolve_watchlist(args.symbols)
    if not symbols:
        print("Aucune watchlist. Spécifie --symbols ou configure INELIDA_WATCHLIST.")
        return 1

    scanner = MarketScanner(symbols)
    if not scanner.prepare():
        return 2

    try:
        display_fn = make_display(verbose=True)
        scanner.watch(display_fn)
    finally:
        scanner.shutdown()
    return 0


def cmd_watchlist(args):
    symbols = resolve_watchlist(args.symbols)
    print(f"Watchlist configurée ({len(symbols)} symboles) :")
    for s in symbols:
        print(f"  - {s}")
    print(f"\nDéfaut (DEFAULT_WATCHLIST) : {len(DEFAULT_WATCHLIST)} symboles.")
    return 0


def cmd_account(args):
    _setup_logging(args.verbose)
    mt5c = MT5Connector()
    if not mt5c.initialize():
        print("[FAIL] Initialisation MT5 impossible.")
        return 2
    try:
        info = mt5c.get_account_info()
        if not info:
            print("Impossible de récupérer les infos compte.")
            return 3
        print("Informations compte MT5 :")
        for k, v in info.items():
            print(f"  {k:>18} : {v}")
    finally:
        mt5c.shutdown()
    return 0


def cmd_terminal(args):
    _setup_logging(args.verbose)
    mt5c = MT5Connector()
    if not mt5c.initialize():
        print("[FAIL] Initialisation MT5 impossible.")
        return 2
    try:
        info = mt5c.get_terminal_info()
        if not info:
            print("Impossible de récupérer les infos terminal.")
            return 3
        print("Informations terminal MT5 :")
        for k, v in info.items():
            print(f"  {k:>18} : {v}")
    finally:
        mt5c.shutdown()
    return 0


def cmd_sweeps(args):
    """Scan les sweeps BSL/SSL sur la Market Watch ou sur --symbols explicites."""
    _setup_logging(args.verbose)
    timeframe = args.timeframe or SWEEP.timeframe
    fractal_n = args.fractal if args.fractal is not None else SWEEP.fractal_n
    lookback = args.lookback if args.lookback is not None else SWEEP.lookback
    sensitivity = args.sensitivity if args.sensitivity is not None else SWEEP.sensitivity
    max_syms = None if args.all else (args.limit if args.limit is not None else SWEEP.max_symbols)
    scan_all = getattr(args, "scan_all", False)
    save_to_db = DB.auto_save_sweeps and not args.json  # pas de sauvegarde en mode JSON

    all_events: list = []
    scanned_count = 0
    symbols_override = None

    if args.symbols:
        explicit = [s.strip().upper() for s in args.symbols if s.strip()]
        if not explicit:
            print("--symbols fourni mais vide.")
            return 1
        scanned_count = len(explicit)
        logger = logging.getLogger("cmd_sweeps")
        for sym in explicit:
            evs = detect_sweeps_for_symbol(
                sym, timeframe=timeframe, fractal_n=fractal_n,
                lookback=lookback, sensitivity=sensitivity,
            )
            if evs:
                all_events.extend(evs)
                logger.info("[SWEEP] %s: %d evenement(s).", sym, len(evs))
            else:
                logger.info("[SWEEP] %s: 0 evenement.", sym)
        # Sauvegarde en DB si demande
        if save_to_db and all_events:
            get_db().save_sweep_events_bulk(all_events)
    else:
        # Mode --scan-all : tous les symboles disponibles chez le broker
        if scan_all:
            mt5c = MT5Connector()
            if not mt5c.ensure_connected():
                return 2
            symbols_override = mt5c.list_all_symbols()
            print(f"{YELLOW}Scan de TOUS les symboles ({len(symbols_override)})...{RESET}")

        all_events, scanned = scan_market_watch_for_sweeps(
            timeframe=timeframe, fractal_n=fractal_n,
            lookback=lookback, sensitivity=sensitivity,
            max_symbols=max_syms,
            symbols_override=symbols_override,
            save_to_db=save_to_db,
        )
        scanned_count = len(scanned) if not symbols_override else len(symbols_override)

    all_events = sort_events(all_events, by_distance=args.sort_by_distance)

    if args.json:
        print(json.dumps(events_to_dicts(all_events), indent=2, ensure_ascii=False))
    elif all_events:
        print(render_sweeps(all_events, scanned_count=scanned_count, timeframe=timeframe))
        print(f"\n{GREEN}{len(all_events)} sweep(s) detecte(s) sur {timeframe}.{RESET}")
        if save_to_db:
            print(f"  {GRAY}Donnees enregistrees dans la base SQLite.{RESET}")
    else:
        print(render_sweeps([], scanned_count=scanned_count, timeframe=timeframe))
        print(f"\n{YELLOW}Aucun sweep detecte sur {scanned_count} symboles scanne(s) ({timeframe}).{RESET}")

    return 0


def cmd_asian(args):
    """Scan le range de la session asiatique (UTC 00:00-08:00) par symbole
    et detecte si le High / Low a été swept en post-Asian."""
    _setup_logging(args.verbose)
    timeframe = (args.timeframe or ASIAN.timeframe).upper()
    session_date = args.session_date if args.session_date else None
    cap = None if args.all else (
        args.limit if args.limit is not None else ASIAN.max_symbols
    )
    scan_all = getattr(args, "scan_all", False)
    save_to_db = DB.auto_save_asian and not args.json

    all_results: list = []
    scanned_count = 0
    symbols_override = None

    if args.symbols:
        explicit = [s.strip().upper() for s in args.symbols if s.strip()]
        if not explicit:
            print("--symbols fourni mais vide.")
            return 1
        scanned_count = len(explicit)
        for sym in explicit:
            r = detect_asian_range_for_symbol(
                sym, timeframe=timeframe, session_date=session_date,
            )
            if r is not None:
                all_results.append(r)
        # Sauvegarde en DB si demande
        if save_to_db and all_results:
            get_db().save_asian_results_bulk(all_results)
    else:
        # Mode --scan-all : tous les symboles disponibles chez le broker
        if scan_all:
            mt5c = MT5Connector()
            if not mt5c.ensure_connected():
                return 2
            symbols_override = mt5c.list_all_symbols()
            print(f"{YELLOW}Scan de TOUS les symboles ({len(symbols_override)})...{RESET}")

        all_results, scanned = scan_market_watch_asian_ranges(
            timeframe=timeframe, session_date=session_date, max_symbols=cap,
            symbols_override=symbols_override,
            save_to_db=save_to_db,
        )
        scanned_count = len(scanned) if not symbols_override else len(symbols_override)

    date_str = session_date or _dt.utcfromtimestamp(time.time()).strftime("%Y-%m-%d")

    if args.json and not args.execute:
        print(json.dumps(asians_to_dicts(all_results), indent=2, ensure_ascii=False))
    elif all_results:
        print(render_asian_ranges(
            all_results, scanned_count=scanned_count,
            session_date=date_str, timeframe=timeframe,
        ))
        n_swept = sum(
            1 for r in all_results
            if r.asian_high_swept or r.asian_low_swept
        )
        print(
            f"\n{GREEN}{n_swept}/{len(all_results)} symbole(s) ont eu leur "
            f"High ou Low asiatique sweep sur {timeframe} (session {date_str}).{RESET}"
        )
        if save_to_db:
            print(f"  {GRAY}Donnees enregistrees dans la base SQLite.{RESET}")
    else:
        print(render_asian_ranges(
            [], scanned_count=scanned_count,
            session_date=date_str, timeframe=timeframe,
        ))
        print(
            f"\n{YELLOW}Aucun range asiatique calcule sur {scanned_count} "
            f"symboles pour {date_str}.{RESET}"
        )

    # ── Dispatch execution si --execute ─────────────────────────────
    if args.execute:
        # Reutilise all_results deja scannes (evite le double scan MT5).
        decisions = _scan_to_decisions(
            timeframe,
            args.symbols,
            args.lots,
            args.rr_min,
            args.symbol,
            precomputed_results=all_results,
        )
        return _dispatch_execution(
            decisions, args,
            header=f"{BOLD}{CYAN}== Trade Ideas (asian {timeframe} {date_str}) =={RESET}",
        )

    return 0


def _dispatch_execution(decisions: list, args, header: str = "") -> int:
    """Helper partage entre 'trade execute' et 'asian --execute' :
    render la table + Y/N + executor.execute_many + render resultats.
    Respecte args.dry_run, args.yes, args.json.
    """
    if not decisions:
        print(f"{YELLOW}Aucun trade 'Active' (filtre RR >= {getattr(args, 'rr_min', None) or 0}).{RESET}")
        return 0

    dry_run = getattr(args, "dry_run", False)
    executor = TradeExecutor(
        dry_run=dry_run,
        confirm_each=False,  # confirmation globale ci-dessous
    )

    print(_render_trade_decisions(decisions, dry_run=dry_run, header=header))
    if not dry_run and not args.yes:
        print(
            f"\n{BOLD}{RED}=== LIVE EXECUTION ==={RESET}\n"
            f"  {YELLOW}{len(decisions)} ordre(s) vont etre envoyes (LIVE).{RESET}\n"
            f"  Lot={args.lots}, RR_min={getattr(args, 'rr_min', None) or 'no'}\n"
            f"  Confirmer ? [y/N] ",
            end="", flush=True,
        )
        try:
            ans = input()
        except EOFError:
            ans = ""
        ans = (ans or "").strip().lower()
        if ans not in ("y", "yes", "o", "oui"):
            print(f"{YELLOW}Annule.{RESET}")
            return 130
    elif not dry_run and args.yes:
        print(
            f"\n{YELLOW}  --yes active : envoi LIVE sans confirmation "
            f"interactive de {len(decisions)} ordre(s).{RESET}"
        )

    results_tr = executor.execute_many(decisions, batch_confirm=False)
    if getattr(args, "json", False):
        print(json.dumps(
            [
                {
                    "symbol": tr.decision.symbol,
                    "action": tr.decision.action,
                    "lots": tr.decision.lots,
                    "entry": tr.decision.entry,
                    "sl": tr.decision.sl,
                    "tp1": tr.decision.tp1,
                    "deviation": tr.decision.deviation,
                    "rr": tr.decision.rr,
                    "status": tr.status,
                    "retcode": tr.retcode,
                    "retcode_label": tr.retcode_label,
                    "order_id": tr.order_id,
                    "deal_id": tr.deal_id,
                    "ask": tr.ask,
                    "bid": tr.bid,
                    "message": tr.message,
                    "advice": tr.advice,
                } for tr in results_tr
            ], indent=2, ensure_ascii=False,
        ))
    else:
        print(_render_trade_results(results_tr))
    n_filled = sum(1 for r in results_tr if r.status in ("FILLED", "PARTIAL"))
    if n_filled == 0:
        n_dry = sum(1 for r in results_tr if r.status == "DRY_RUN")
        return 0 if n_dry == len(results_tr) else 2
    return 0


def _render_trade_decisions(ds: list, dry_run: bool, header: str = "") -> str:
    """Tableau ASCII d'une liste de TradeDecision (preview avant envoi)."""
    lines: List[str] = []
    tag = "[DRY-RUN]" if dry_run else "[LIVE]"
    if header:
        lines.append(header)
    lines.append(
        f"{BOLD}{'Symbole':<10} {'Action':>6} {'Lots':>5}  "
        f"{'EP':>14}  {'SL':>14}  {'TP1':>14}  {'Dev':>4}  {'RR':>5}  {'Magic'}{RESET}"
    )
    lines.append(
        f"{GRAY}{'-' * (len(lines[-1]) - len(BOLD) - len(RESET))}{RESET}"
    )
    for d in ds:
        rr = f"{d.rr:.1f}x" if d.rr and d.rr > 0 else "-"
        act_col = f"{GREEN}{d.action}{RESET}" if d.action == "BUY" else f"{RED}{d.action}{RESET}"
        lines.append(
            f"{MAGENTA}{d.symbol:<10}{RESET} {act_col:>20} {d.lots:>5.2f}  "
            f"{d.entry:>14.5f}  {d.sl:>14.5f}  {d.tp1:>14.5f}  "
            f"{d.deviation:>4}  {YELLOW}{rr}{RESET}  {INELIDA_MAGIC}"
        )
    lines.append(f"\n{tag} {len(ds)} ordre(s) prets (sources: AsianSession_Fib_*).")
    return "\n".join(lines)


def _render_trade_results(rs: list) -> str:
    """Tableau ASCII du resultat apres envoi."""
    lines: List[str] = []
    lines.append(f"{BOLD}{CYAN}== Trade Execution Results =={RESET}")
    lines.append("")
    if not rs:
        lines.append(f"{YELLOW}Aucun ordre traite.{RESET}")
        return "\n".join(lines)
    lines.append(
        f"{BOLD}{'Symbole':<10} {'Status':>9}  {'Action':>6}  "
        f"{'Lots':>5}  {'OrderID':>10}  {'DealID':>10}  {'Retcode':>15}  {'Note'}{RESET}"
    )
    for r in rs:
        d = r.decision
        if r.status == "FILLED":
            st = f"{GREEN}{r.status}{RESET}"
        elif r.status == "PARTIAL":
            st = f"{YELLOW}{r.status}{RESET}"
        elif r.status == "DRY_RUN":
            st = f"{CYAN}{r.status}{RESET}"
        elif r.status == "SKIPPED":
            st = f"{GRAY}{r.status}{RESET}"
        else:
            st = f"{RED}{r.status}{RESET}"
        lines.append(
            f"{MAGENTA}{d.symbol:<10}{RESET} {st:>27} {d.action:>6}  "
            f"{d.lots:>5.2f}  "
            f"{(r.order_id if r.order_id else '-'):>10}  "
            f"{(r.deal_id if r.deal_id else '-'):>10}  "
            f"{r.retcode_label:>15}  "
            f"{GRAY}{r.message}{RESET}"
        )
        if r.advice:
            # Indice actionnable sur une 2e ligne pour ne pas briser la parsabilité JSON / log-line.
            lines.append(
                f"           {YELLOW}>>> HINT(retcode={r.retcode}): "
                f"{r.advice}{RESET}"
            )
    n_filled = sum(1 for r in rs if r.status in ("FILLED", "PARTIAL"))
    n_dry = sum(1 for r in rs if r.status == "DRY_RUN")
    n_fail = sum(1 for r in rs if r.status == "FAILED")
    n_skip = sum(1 for r in rs if r.status == "SKIPPED")
    lines.append(
        f"\n{GREEN}{n_filled} filled{RESET} | "
        f"{CYAN}{n_dry} dry-run{RESET} | "
        f"{RED}{n_fail} failed{RESET} | "
        f"{GRAY}{n_skip} skipped{RESET} (sur {len(rs)} total)"
    )
    return "\n".join(lines)


def _scan_to_decisions(timeframe: str, symbols, lots: float, rr_min,
                      only_symbol: str, precomputed_results=None):
    """Convertit des resultats de scan en TradeDecisions selon les filtres.

    Si `precomputed_results` est fourni (deja scannes par cmd_asian), on
    reutilise directement SANS relancer le scan MT5. Sinon on scan ici.

    Filtres appliques (dans l'ordre):
      - rr_min    (filtre RR minimal)
      - only_symbol  (filtre sur 1 symbole)
    """
    if precomputed_results is not None:
        results = list(precomputed_results)
    else:
        explicit = (
            [s.strip().upper() for s in (symbols or []) if s.strip()]
            if symbols else None
        )
        if explicit:
            results = [
                r for sym in explicit
                if (r := detect_asian_range_for_symbol(sym, timeframe)) is not None
            ]
            # Sauvegarde en DB pour les stats
            if DB.auto_save_asian and results:
                get_db().save_asian_results_bulk(results)
        else:
            results, _scanned = scan_market_watch_asian_ranges(
                timeframe=timeframe, save_to_db=True,
            )
    decisions = asian_to_decisions(results, lots=lots, rr_min=rr_min)
    if only_symbol:
        decisions = [d for d in decisions if d.symbol == only_symbol.upper()]
    return decisions


def cmd_trade(args):
    """Sous-commande trade : pilote MT5 pour ouvrir les Trade Ideas.

    Actions :
      list      : affiche les idees du dernier scan (sans rien envoyer)
      execute   : envoie activement (LIVE par defaut ; --dry-run pour preview)
    """
    _setup_logging(args.verbose)
    action = args.trade_action
    timeframe = (args.timeframe or "H1").upper()

    if action == "list":
        decisions = _scan_to_decisions(
            timeframe, args.symbols, args.lots, args.rr_min, args.symbol,
        )
        if args.json:
            print(json.dumps(
                [d.__dict__ for d in decisions], indent=2, ensure_ascii=False,
            ))
        else:
            print(_render_trade_decisions(
                decisions, dry_run=True,
                header=f"{BOLD}{CYAN}== Available Trade Ideas (scan {timeframe}) =={RESET}",
            ))
        return 0

    if action == "execute":
        decisions = _scan_to_decisions(
            timeframe, args.symbols, args.lots, args.rr_min, args.symbol,
        )
        return _dispatch_execution(
            decisions, args,
            header=f"{BOLD}{CYAN}== Trade Execution (scan {timeframe}) =={RESET}",
        )

    return 0

# ─── Base de données ──────────────────────────────────────────────────────────
def cmd_db(args):
    """Commandes d'interaction avec la base de données SQLite."""
    _setup_logging(args.verbose)

    db_action = args.db_action

    if db_action == "stats":
        db = get_db()
        if not db.connect():
            print(f"{RED}Impossible d'ouvrir la base de donnees.{RESET}")
            return 2
        stats = db.get_statistics()
        if not stats:
            print(f"{YELLOW}Aucune statistique disponible.{RESET}")
            return 0

        print(f"{BOLD}{CYAN}== Statistiques de la base de donnees =={RESET}")
        print(f"  {GRAY}Fichier:{RESET} {db.db_path}")
        print(f"")
        print(f"  {BOLD}Sessions asiatiques :{RESET}")
        print(f"    Total enregistrees : {stats.get('asian_total', 0)}")
        print(f"    Symboles suivis     : {stats.get('symbols_tracked', 0)}")
        print(f"    High sweeps         : {stats.get('asian_high_swept', 0)}")
        print(f"    Low sweeps          : {stats.get('asian_low_swept', 0)}")
        print(f"")
        print(f"  {BOLD}Sweep events :{RESET}")
        print(f"    Total sweeps        : {stats.get('sweep_total', 0)}")
        print(f"    BSL sweeps          : {stats.get('bsl_total', 0)}")
        print(f"    SSL sweeps          : {stats.get('ssl_total', 0)}")
        print(f"")
        print(f"  {BOLD}Dernieres sessions:{RESET}")
        for d in stats.get("last_dates", []):
            print(f"    {d['session_date']} : {d['cnt']} symbole(s)")
        return 0

    if db_action == "list":
        db = get_db()
        if not db.connect():
            print(f"{RED}Impossible d'ouvrir la base de donnees.{RESET}")
            return 2

        limit = args.limit or 30
        what = args.what
        symbol_filter = args.symbol.upper() if args.symbol else None

        if what == "asian":
            rows = db.get_asian_sessions(
                symbol=symbol_filter,
                session_date=args.date,
                limit=limit,
            )
            if not rows:
                print(f"{YELLOW}Aucune session asiatique trouvee.{RESET}")
                return 0
            print(f"{BOLD}{CYAN}== Sessions asiatiques enregistrees =={RESET}")
            print(
                f"{BOLD}{'Symbole':<12} {'Date':<12} {'AH':>11} {'AL':>11} "
                f"{'AH Swp':>8} {'AL Swp':>8} {'Swept H@':>22} {'Swept L@':>22}{RESET}"
            )
            for r in rows:
                ah_s = f"{GREEN}OUI{RESET}" if r["asian_high_swept"] else f"{GRAY}non{RESET}"
                al_s = f"{GREEN}OUI{RESET}" if r["asian_low_swept"] else f"{GRAY}non{RESET}"
                h_at = (
                    time.strftime("%Y-%m-%d %H:%M", time.gmtime(r["high_swept_at"]))
                    if r["high_swept_at"] else f"{GRAY}---{RESET}"
                )
                l_at = (
                    time.strftime("%Y-%m-%d %H:%M", time.gmtime(r["low_swept_at"]))
                    if r["low_swept_at"] else f"{GRAY}---{RESET}"
                )
                print(
                    f"{MAGENTA}{r['symbol']:<12}{RESET} {r['session_date']:<12} "
                    f"{r['asian_high']:>11.5f} {r['asian_low']:>11.5f} "
                    f"{ah_s:>16} {al_s:>16} "
                    f"{h_at:>22} {l_at:>22}"
                )
            print(f"\n{GRAY}{len(rows)} ligne(s) affichee(s) sur {limit} max.{RESET}")

        elif what == "sweeps":
            rows = db.get_sweep_events(
                symbol=symbol_filter,
                limit=limit,
            )
            if not rows:
                print(f"{YELLOW}Aucun sweep event trouve.{RESET}")
                return 0
            print(f"{BOLD}{CYAN}== Sweep events enregistres =={RESET}")
            print(
                f"{BOLD}{'Symbole':<12} {'Label':>5} {'Level':>14} "
                f"{'Sweep Time':>19} {'Dir':>14}{RESET}"
            )
            for r in rows:
                sweep_time = (
                    time.strftime("%Y-%m-%d %H:%M", time.gmtime(r["sweep_time"]))
                    if r["sweep_time"] else "---"
                )
                dir_col = f"{GREEN}{r['direction']}{RESET}" if r["direction"] == "reversal_up" else f"{RED}{r['direction']}{RESET}"
                label_col = f"{YELLOW}{r['sweep_label']}{RESET}"
                print(
                    f"{MAGENTA}{r['symbol']:<12}{RESET} "
                    f"{label_col:>13} "
                    f"{r['level']:>14.5f} "
                    f"{sweep_time:>19} "
                    f"{dir_col:>22}"
                )
            print(f"\n{GRAY}{len(rows)} ligne(s) affichee(s) sur {limit} max.{RESET}")

        return 0

    if db_action == "path":
        db = get_db()
        print(f"{BOLD}Chemin de la base de donnees :{RESET}")
        print(f"  {CYAN}{os.path.abspath(db.db_path)}{RESET}")
        taille = os.path.getsize(db.db_path) if os.path.exists(db.db_path) else 0
        if taille > 0:
            print(f"  Taille : {taille / 1024:.1f} Ko")
        return 0

    print(f"{RED}Action inconnue : {db_action}{RESET}")
    return 1


# ─── Levels (daily / weekly) ────────────────────────────────────────────────
def cmd_levels(args):
    """
    Scanne les niveaux quotidiens (PDH/PDL) et hebdomadaires (PWH/PWL)
    pour détecter les sweeps + direction vers l'autre côté.
    """
    _setup_logging(args.verbose)
    level_type = getattr(args, "level_type", "all")
    scan_all = getattr(args, "scan_all", False)

    mt5c = MT5Connector()
    if not mt5c.ensure_connected():
        print(f"{RED}Connexion MT5 impossible.{RESET}")
        return 2

    symbols_override = None
    if scan_all:
        symbols_override = mt5c.list_all_symbols()
        print(f"{YELLOW}Scan de TOUS les symboles ({len(symbols_override)})...{RESET}")
    elif args.symbols:
        explicit = [s.strip().upper() for s in args.symbols if s.strip()]
        if explicit:
            symbols_override = explicit

    all_results: list = []
    scanned_count = 0

    # Daily levels
    if level_type in ("all", "daily"):
        d_results, d_scanned = scan_market_watch_levels(
            level_type="daily", scan_tf="H1",
            symbols_override=symbols_override,
        )
        if d_results:
            get_db().save_level_sweeps_bulk(d_results)
        all_results.extend(d_results)
        scanned_count = max(scanned_count, len(d_scanned))

    # Weekly levels
    if level_type in ("all", "weekly"):
        w_results, w_scanned = scan_market_watch_levels(
            level_type="weekly", scan_tf="D1",
            symbols_override=symbols_override,
        )
        if w_results:
            get_db().save_level_sweeps_bulk(w_results)
        all_results.extend(w_results)
        scanned_count = max(scanned_count, len(w_scanned))

    if not all_results:
        print(f"{YELLOW}Aucun niveau calcule.{RESET}")
        return 0

    # Filtrer les setups directionnels
    setups = [
        r for r in all_results
        if r.direction_target in ("AH", "AL", "BOTH")
        and r.direction_target_label not in ("−", "·")
    ]

    # Pas de filtre RR pour les niveaux daily/weekly (pas de trade plan)
    setups.sort(key=lambda r: (r.level_type, r.symbol))

    if not setups:
        print(f"{YELLOW}Aucun setup directionnel detecte sur {len(all_results)} niveaux.{RESET}")
        return 0

    # ── Affichage ───────────────────────────────────────────────────────
    lines: list = []
    lines.append(f"{BOLD}{CYAN}== Niveaux (PDH/PDL / PWH/PWL) - Setups directionnels =={RESET}")
    lines.append(
        f"  {GRAY}Scannes:{RESET} {scanned_count} symboles  |  "
        f"{GRAY}Niveaux:{RESET} {len(all_results)}  |  "
        f"{GRAY}Setups:{RESET} {len(setups)}"
    )
    lines.append("")

    header = (
        f"{BOLD}{'Symbole':<10}  {'Type':>7}  {'Sweep':>8}  {'Direction':>18}  "
        f"{'Niv.Haut':>11} {'Niv.Bas':>11} {'Now':>11}{RESET}"
    )
    lines.append(header)
    lines.append(f"{GRAY}{'-' * (len(header) - len(BOLD) - len(RESET))}{RESET}")

    for r in setups:
        # Type label
        type_cell = f"{CYAN}Daily{RESET}" if r.level_type == "daily" else f"{MAGENTA}Weekly{RESET}"

        # Sweep / Breach
        if r.high_swept and r.low_swept:
            sweep_cell = f"{YELLOW}H+L{RESET}"
        elif r.high_swept:
            sweep_cell = f"{RED}H{RESET}"
        elif r.low_swept:
            sweep_cell = f"{GREEN}L{RESET}"
        elif r.high_breached or r.low_breached:
            parts = []
            if r.high_breached:
                parts.append(f"{DIM}H'{RESET}")
            if r.low_breached:
                parts.append(f"{DIM}L'{RESET}")
            sweep_cell = "+".join(parts)
        else:
            sweep_cell = f"{GRAY}---{RESET}"

        # Direction
        if r.direction_target == "AH":
            dir_cell = f"{GREEN}{r.direction_target_label}{RESET}"
        elif r.direction_target == "AL":
            dir_cell = f"{RED}{r.direction_target_label}{RESET}"
        else:
            dir_cell = f"{YELLOW}{r.direction_target_label}{RESET}"

        lines.append(
            f"{MAGENTA}{r.symbol:<10}{RESET}  "
            f"{type_cell:>15}  "
            f"{sweep_cell:>16}  "
            f"{dir_cell:>18}  "
            f"{_fmt_price(r.level_high):>11} {_fmt_price(r.level_low):>11} {_fmt_price(r.current_price):>11}"
        )

    n_haut = sum(1 for r in setups if r.direction_target == "AH")
    n_bas = sum(1 for r in setups if r.direction_target == "AL")
    n_mix = sum(1 for r in setups if r.direction_target == "BOTH")
    lines.append("")
    lines.append(
        f"{BOLD}Resume :{RESET} {GREEN}{n_haut} HAUSSIER{RESET} (-> H)  |  "
        f"{RED}{n_bas} BAISSIER{RESET} (-> B)  |  "
        f"{YELLOW}{n_mix} MIXTE{RESET} (H+L sweepes)"
    )

    print("\n".join(lines))
    return 0


# ─── Setups (sweep + direction) ──────────────────────────────────────────────
def cmd_setups(args):
    """
    Scan asiatique + filtre pour n'afficher QUE les setups directionnels :
    un sweep (AH ou AL) détecté + prix qui se dirige vers l'autre côté de la range.
    """
    _setup_logging(args.verbose)
    timeframe = (args.timeframe or "H1").upper()
    session_date = args.session_date if args.session_date else None
    scan_all = getattr(args, "scan_all", False)
    save_to_db = DB.auto_save_asian
    rr_min = args.rr_min

    # ── Scan ────────────────────────────────────────────────────────────────
    mt5c = MT5Connector()
    if not mt5c.ensure_connected():
        print(f"{RED}Connexion MT5 impossible.{RESET}")
        return 2

    symbols_override = None
    if scan_all:
        symbols_override = mt5c.list_all_symbols()
        print(f"{YELLOW}Scan de TOUS les symboles ({len(symbols_override)})...{RESET}")
    elif args.symbols:
        explicit = [s.strip().upper() for s in args.symbols if s.strip()]
        if explicit:
            symbols_override = explicit

    all_results, scanned = scan_market_watch_asian_ranges(
        timeframe=timeframe, session_date=session_date,
        symbols_override=symbols_override,
        save_to_db=save_to_db,
    )

    if not all_results:
        print(f"{YELLOW}Aucun range asiatique calcule.{RESET}")
        return 0

    # ── Filtrer les setups directionnels ───────────────────────────────────
    # direction_target = "AH" (AL swept → vers AH), "AL" (AH swept → vers AL), "BOTH"
    setups = [
        r for r in all_results
        if r.direction_target in ("AH", "AL", "BOTH")
        and r.direction_target_label not in ("−", "·")
    ]

    # Si --rr-min est fourni, ne garder que les trades avec RR >= rr_min
    if rr_min is not None:
        setups = [
            r for r in setups
            if r.trade_action != "-" and r.trade_rr1 is not None and r.trade_rr1 >= rr_min
        ]

    # Tri : trades actifs avec RR en premier, puis par direction
    def _sort_key(r):
        rr = r.trade_rr1 or 0
        # Priorité : RR élevé d'abord, puis actif avant inactif
        is_active = 1 if r.trade_status == "Active" else 0
        return (is_active, rr)

    setups.sort(key=_sort_key, reverse=True)

    # ── Affichage ──────────────────────────────────────────────────────────
    if not setups:
        print(f"{YELLOW}Aucun setup directionnel detecte sur {len(all_results)} symboles.{RESET}")
        return 0

    date_str = session_date or time.strftime("%Y-%m-%d", time.gmtime())
    lines: list = []
    lines.append(f"{BOLD}{CYAN}== Setups directionnels (sweep AH/AL + mouvement vers l'autre liquidite) =={RESET}")
    lines.append(
        f"  {GRAY}Session UTC:{RESET} {date_str}  |  "
        f"{GRAY}Scannes:{RESET} {len(all_results)}  |  "
        f"{GRAY}Setups:{RESET} {len(setups)}"
    )
    lines.append("")

    # Header
    header = (
        f"{BOLD}{'Symbole':<10}  {'Sweep':>8}  {'Direction':>18}  "
        f"{'Session':>14}  {'AH':>11} {'AL':>11} {'Now':>11}  "
        f"{'RR':>5}  {'Trade':>6}  {'Plan':>26}{RESET}"
    )
    lines.append(header)
    lines.append(f"{GRAY}{'-' * (len(header) - len(BOLD) - len(RESET))}{RESET}")

    for r in setups:
        # Sweep / Breach label
        if r.asian_high_swept and r.asian_low_swept:
            sweep_cell = f"{YELLOW}AH+AL{RESET}"
        elif r.asian_high_swept:
            sweep_cell = f"{RED}AH{RESET}"
        elif r.asian_low_swept:
            sweep_cell = f"{GREEN}AL{RESET}"
        elif r.asian_high_breached or r.asian_low_breached:
            parts = []
            if r.asian_high_breached:
                parts.append(f"{DIM}AH'{RESET}")
            if r.asian_low_breached:
                parts.append(f"{DIM}AL'{RESET}")
            sweep_cell = "+".join(parts)
        else:
            sweep_cell = f"{GRAY}---{RESET}"

        # Direction target
        if r.direction_target == "AH":
            dir_cell = f"{GREEN}{r.direction_target_label}{RESET}"
        elif r.direction_target == "AL":
            dir_cell = f"{RED}{r.direction_target_label}{RESET}"
        else:
            dir_cell = f"{YELLOW}{r.direction_target_label}{RESET}"

        # Session
        if r.asian_high_swept and r.asian_low_swept:
            sess_cell = f"{DIM}H:{r.high_swept_session_label or '?'}/L:{r.low_swept_session_label or '?'}{RESET}"
        elif r.asian_high_swept:
            sess_cell = f"{RED}{r.high_swept_session_label or '?'}{RESET}"
        else:
            sess_cell = f"{GREEN}{r.low_swept_session_label or '?'}{RESET}"

        # RR
        if r.trade_rr1 and r.trade_rr1 > 0:
            rr_cell = f"{YELLOW}{r.trade_rr1:.1f}x{RESET}" if r.trade_rr1 >= 1.0 else f"{DIM}{r.trade_rr1:.1f}x{RESET}"
        else:
            rr_cell = f"{GRAY}-{RESET}"

        # Trade action
        if r.trade_action == "BUY":
            trade_cell = f"{GREEN}BUY{RESET}"
        elif r.trade_action == "SELL":
            trade_cell = f"{RED}SELL{RESET}"
        else:
            trade_cell = f"{GRAY}-{RESET}"

        # Plan
        if r.trade_status == "Active" and r.trade_sl and r.trade_tp1:
            plan_cell = f"{CYAN}SL {_fmt_price(r.trade_sl)} -> TP1 {_fmt_price(r.trade_tp1)}{RESET}"
        elif r.trade_status == "Targets hit":
            plan_cell = f"{DIM}TP hit{RESET}"
        else:
            plan_cell = f"{GRAY}-{RESET}"

        lines.append(
            f"{MAGENTA}{r.symbol:<10}{RESET}  "
            f"{sweep_cell:>16}  "
            f"{dir_cell:>18}  "
            f"{sess_cell:>22}  "
            f"{_fmt_price(r.asian_high):>11} {_fmt_price(r.asian_low):>11} {_fmt_price(r.current_price):>11}  "
            f"{rr_cell:>5}  "
            f"{trade_cell:>6}  "
            f"{plan_cell:>26}"
        )

    # Summary
    n_active = sum(1 for r in setups if r.trade_status == "Active" and r.trade_rr1 and r.trade_rr1 >= 1.0)
    n_ah = sum(1 for r in setups if r.direction_target == "AH")
    n_al = sum(1 for r in setups if r.direction_target == "AL")
    n_both = sum(1 for r in setups if r.direction_target == "BOTH")

    lines.append("")
    lines.append(
        f"{BOLD}Resume :{RESET} {GREEN}{n_ah} HAUSSIER{RESET} (-> AH)  |  "
        f"{RED}{n_al} BAISSIER{RESET} (-> AL)  |  "
        f"{YELLOW}{n_both} MIXTE{RESET} (les deux)  |  "
        f"{CYAN}{n_active} trade(s) avec RR >= 1.0{RESET}"
    )

    print("\n".join(lines))
    return 0


# ─── Parser ──────────────────────────────────────────────────────────────────
def _add_common(subparser: argparse.ArgumentParser) -> None:
    """Attache --verbose et --symbols à un subparser (pattern parents=[common])."""
    subparser.add_argument("-v", "--verbose", action="store_true",
                           help="Active le logging DEBUG.")
    subparser.add_argument("--symbols", nargs="*", default=None,
                           help="Liste de symboles (surcharge la watchlist / scan manuel).")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="inelida-marketscanner",
        description="InelidaMarketScanner — scanner de marché temps réel MetaTrader 5.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_snap = sub.add_parser("snapshot",
                            help="Capture unique et sortie immédiate.")
    p_snap.add_argument("--json", action="store_true",
                        help="Sortie JSON au lieu du tableau ASCII.")
    _add_common(p_snap)

    p_watch = sub.add_parser("watch",
                             help="Boucle continue: scan temps réel de la watchlist.")
    _add_common(p_watch)

    p_list = sub.add_parser("watchlist",
                            help="Affiche la watchlist configurée.")
    _add_common(p_list)

    p_trade = sub.add_parser(
        "trade",
        help="Pilote MT5 pour ouvrir les Trade Ideas generees par 'asian' (LIVE par defaut).",
    )
    p_trade.add_argument("trade_action", choices=("list", "execute"),
                         help="Action: 'list' = preview ; 'execute' = envoi.")
    p_trade.add_argument("--timeframe", default="H1",
                         help="Timeframe du scan asiatique (defaut H1).")
    p_trade.add_argument("--lots", type=float, default=0.01,
                         help="Volume en lots par ordre (defaut 0.01).")
    p_trade.add_argument("--rr-min", type=float, default=None,
                         help="Filtre RR minimal (ex. 1.0 pour ne garder QUE les trades RR >= 1).")
    p_trade.add_argument("--symbol", default=None,
                         help="Filtre sur UN seul symbole pour execution.")
    p_trade.add_argument("--dry-run", dest="dry_run", action="store_true",
                         help="DRY-RUN opt-in (sans ce flag, LIVE ENVOI REEL par defaut).")
    p_trade.add_argument("--yes", action="store_true",
                         help="Skip la confirmation Y/N interactive (auto-confirm).")
    p_trade.add_argument("--json", action="store_true",
                         help="Sortie JSON au lieu du tableau ASCII.")
    _add_common(p_trade)

    p_acct = sub.add_parser("account",
                            help="Affiche les informations du compte MT5 connecté.")
    _add_common(p_acct)

    p_term = sub.add_parser("terminal",
                            help="Affiche les informations du terminal MT5.")
    _add_common(p_term)

    p_sweeps = sub.add_parser(
        "sweeps",
        help="Scan tous les symboles visibles en Market Watch pour détecter les sweeps BSL/SSL (ICT).",
    )
    p_sweeps.add_argument("--timeframe", default=None,
                          help="Timeframe ICT (M1|M5|M15|M30|H1|H4|D1, défaut M15).")
    p_sweeps.add_argument("--fractal", type=int, default=None,
                          help="Williams fractal N (défaut 2).")
    p_sweeps.add_argument("--lookback", type=int, default=None,
                          help="Bougies arrière pour chercher les swings (défaut 50).")
    p_sweeps.add_argument("--sensitivity", type=int, default=None,
                          help="N dernières bougies testées pour les sweeps (défaut 5).")
    p_sweeps.add_argument("--limit", type=int, default=None,
                          help="Max symboles scannés (défaut 50).")
    p_sweeps.add_argument("--all", action="store_true",
                          help="Override --limit, scan tous les symboles visibles.")
    p_sweeps.add_argument("--scan-all", action="store_true",
                          help="Scan TOUS les symboles disponibles chez le broker (visible + non-visibles).")
    p_sweeps.add_argument("--sort-by-distance", dest="sort_by_distance",
                          action="store_true", default=True,
                          help="Trie les sweeps par distance au prix actuel (défaut).")
    p_sweeps.add_argument("--no-sort-by-distance", dest="sort_by_distance",
                          action="store_false",
                          help="Trie les sweeps par ordre de détection.")
    p_sweeps.add_argument("--json", action="store_true",
                          help="Sortie JSON au lieu du tableau ASCII.")
    _add_common(p_sweeps)

    p_asian = sub.add_parser(
        "asian",
        help="Scan le high + low de la session asiatique (UTC 00:00-08:00) "
             "et detecte les sweeps post-Asian (London / NY).",
    )
    p_asian.add_argument("--timeframe", default=None,
                         help="Timeframe de travail (defaut H1; M15 possible).")
    p_asian.add_argument("--session-date", dest="session_date", default=None,
                         help="Date ISO YYYY-MM-DD UTC (defaut = aujourd'hui).")
    p_asian.add_argument("--limit", type=int, default=None,
                         help="Max symboles scannes (defaut 50).")
    p_asian.add_argument("--all", action="store_true",
                         help="Override --limit.")
    p_asian.add_argument("--scan-all", action="store_true",
                         help="Scan TOUS les symboles disponibles chez le broker (visible + non-visibles).")
    # Flags d'execution (alias pratique pour 'trade execute' inline).
    p_asian.add_argument("--execute", action="store_true",
                         help="Apres le scan, envoyer les Trade Ideas au broker "
                              "(LIVE par defaut ; ajouter --dry-run pour preview).")
    p_asian.add_argument("--dry-run", dest="dry_run", action="store_true",
                         help="DRY-RUN opt-in (sans ce flag, LIVE ENVOI REEL par defaut).")
    p_asian.add_argument("--yes", action="store_true",
                         help="Skip la confirmation Y/N interactive (auto-confirm).")
    p_asian.add_argument("--lots", type=float, default=0.01,
                         help="Volume en lots par ordre execution (defaut 0.01).")
    p_asian.add_argument("--rr-min", dest="rr_min", type=float, default=None,
                         help="Filtre RR minimal des Trade Ideas executees (ex. 1.0).")
    p_asian.add_argument("--symbol", default=None,
                         help="Filtre sur UN seul symbole a executer.")
    p_asian.add_argument("--json", action="store_true",
                         help="Sortie JSON au lieu du tableau ASCII.")
    _add_common(p_asian)

    # ── levels ───────────────────────────────────────────────────────────────
    p_levels = sub.add_parser(
        "levels",
        help="Scanne les niveaux PDH/PDL (quotidiens) et PWH/PWL (hebdomadaires) "
             "+ detecte les sweeps et la direction.",
    )
    p_levels.add_argument("--type", dest="level_type",
                          choices=("daily", "weekly", "all"), default="all",
                          help="Type de niveau a scanner (defaut: les deux).")
    p_levels.add_argument("--scan-all", action="store_true",
                          help="Scan TOUS les symboles disponibles chez le broker.")
    _add_common(p_levels)

    # ── setups ───────────────────────────────────────────────────────────────
    p_setups = sub.add_parser(
        "setups",
        help="Scan asiatique + filtre : affiche uniquement les setups directionnels "
             "(AH/AL sweep + mouvement vers l'autre liquidite).",
    )
    p_setups.add_argument("--timeframe", default=None,
                          help="Timeframe de travail (defaut H1; M15 possible).")
    p_setups.add_argument("--session-date", dest="session_date", default=None,
                          help="Date ISO YYYY-MM-DD UTC (defaut = aujourd'hui).")
    p_setups.add_argument("--scan-all", action="store_true",
                          help="Scan TOUS les symboles disponibles chez le broker.")
    p_setups.add_argument("--rr-min", type=float, default=None,
                          help="Filtre RR minimal (ex. 1.0 pour ne garder QUE les trades RR >= 1).")
    _add_common(p_setups)

    # ── db ─────────────────────────────────────────────────────────────────
    p_db = sub.add_parser(
        "db",
        help="Interagir avec la base de donnees SQLite (stats, list, path).",
    )
    p_db.add_argument("db_action", choices=("stats", "list", "path"),
                      help="Action : 'stats' = statistiques, 'list' = lister, 'path' = chemin.")
    p_db.add_argument("--what", choices=("asian", "sweeps"), default="asian",
                      help="Type de donnees a lister (defaut 'asian').")
    p_db.add_argument("--symbol", default=None,
                      help="Filtre sur un symbole (list).")
    p_db.add_argument("--date", default=None,
                      help="Filtre sur une date YYYY-MM-DD (list asian).")
    p_db.add_argument("--limit", type=int, default=30,
                      help="Nombre max de lignes a afficher (defaut 30).")
    _add_common(p_db)

    return parser


RESET = "\033[0m"
GREEN = "\033[32m"
YELLOW = "\033[33m"


def main():
    parser = build_parser()
    args = parser.parse_args()

    handlers = {
        "snapshot":  cmd_snapshot,
        "watch":     cmd_watch,
        "watchlist": cmd_watchlist,
        "account":   cmd_account,
        "terminal":  cmd_terminal,
        "sweeps":    cmd_sweeps,
        "asian":     cmd_asian,
        "trade":     cmd_trade,
        "db":        cmd_db,
        "levels":    cmd_levels,
        "setups":    cmd_setups,
    }
    try:
        return handlers[args.command](args)
    except KeyboardInterrupt:
        print("\nInterrompu.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
