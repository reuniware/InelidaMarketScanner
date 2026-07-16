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
import urllib.request
import urllib.error
from datetime import datetime as _dt, timezone as _tz

from src.config import (
    DB, MT5, OUT, SWEEP, ASIAN, resolve_watchlist, DEFAULT_WATCHLIST,
)
from src.mt5_connector import MT5Connector
from src.market_scanner import MarketScanner
from src.display import (
    render_snapshot,
    render_sweeps, render_sweeps_plain, make_display,
    render_asian_ranges, render_asian_ranges_plain,
    _fmt_price, _pad_cell,
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
from src.diamond_scanner import (
    DiamondScanner,
    DiamondResult,
    TenkanFlatMemory,
    get_dxy_price,
    get_dxy_kijun_h1,
)
from src.trade_tracker import TradeTracker
from analyze_asian_bsl_ssl import (
    scan_all_symbols,
    render_all_results,
    results_to_json,
    analyze_symbol,
    AsianSwingPoint,
    SymbolAsianLiquidity,
)


def _setup_logging(verbose: bool):
    from src.logger_config import LOGS_DIR

    level = logging.DEBUG if verbose else logging.INFO
    os.makedirs(LOGS_DIR, exist_ok=True)
    log_file = os.path.join(LOGS_DIR, f"main_{_dt.now():%Y-%m-%d}.log")

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-7s | %(name)-18s | %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
        force=True,
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

    # Filtre --swept-only
    display_results = all_results
    if getattr(args, 'swept_only', False):
        display_results = [r for r in all_results if r.asian_high_swept or r.asian_low_swept]

    if args.json and not args.execute:
        print(json.dumps(asians_to_dicts(display_results), indent=2, ensure_ascii=False))
    elif all_results:
        print(render_asian_ranges(
            display_results, scanned_count=scanned_count,
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
            f"{_pad_cell(type_cell, 7)}  "
            f"{_pad_cell(sweep_cell, 8)}  "
            f"{_pad_cell(dir_cell, 18)}  "
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

    # Filtrer les trades avec spread > 0.10% (seuil reel)
    MAX_SPREAD_PCT = 0.10
    n_spread_skipped = 0
    setups_filtered = []
    for r in setups:
        if r.spread_pct > 0 and r.spread_pct > MAX_SPREAD_PCT:
            n_spread_skipped += 1
        else:
            setups_filtered.append(r)
    setups = setups_filtered

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
        f"{'Spread':>8}  {'RR':>5}  {'Trade':>6}  {'Plan':>26}{RESET}"
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

        # Spread en %
        if r.spread_pct > 0:
            if r.spread_pct <= 0.10:
                sp_cell = f"{GREEN}{r.spread_pct:.3f}%{RESET}"
            elif r.spread_pct <= 0.30:
                sp_cell = f"{YELLOW}{r.spread_pct:.3f}%{RESET}"
            else:
                sp_cell = f"{RED}{r.spread_pct:.3f}%{RESET}"
        else:
            sp_cell = f"{GRAY}?{RESET}"

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
            f"{_pad_cell(sweep_cell, 8)}  "
            f"{_pad_cell(dir_cell, 18)}  "
            f"{_pad_cell(sess_cell, 14)}  "
            f"{_fmt_price(r.asian_high):>11} {_fmt_price(r.asian_low):>11} {_fmt_price(r.current_price):>11}  "
            f"{_pad_cell(sp_cell, 8)}  "
            f"{_pad_cell(rr_cell, 5)}  "
            f"{_pad_cell(trade_cell, 6)}  "
            f"{_pad_cell(plan_cell, 26)}"
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
    if n_spread_skipped > 0:
        lines.append(
            f"{RED}{n_spread_skipped} filtre(s) spread (> {MAX_SPREAD_PCT:.2f}%){RESET}"
        )

    print("\n".join(lines))
    return 0


# ─── Asian Session BSL/SSL ───────────────────────────────────────────────────

def cmd_asian_liquidity(args):
    """
    Scan les BSL (swing highs) et SSL (swing lows) crees pendant la session
    asiatique (UTC 00:00-08:00) via Williams fractals (N=2).

    Pour chaque symbole : détecte les swing points dans les barres M15 de
    la session asiatique, verifie s'ils ont ete sweepes en post-Asian
    (London/NY), et affiche un tableau detaille avec distances en pips.
    """
    _setup_logging(args.verbose)

    session_date = getattr(args, 'session_date', None) or \
        _dt.utcfromtimestamp(time.time()).strftime("%Y-%m-%d")

    tf_name = getattr(args, 'tf', 'M15').upper()
    scan_all = getattr(args, "scan_all", False)

    if scan_all:
        mt5c = MT5Connector()
        if not mt5c.ensure_connected():
            print(f"{RED}Connexion MT5 impossible.{RESET}")
            return 2
        symbols = mt5c.list_all_symbols()
        print(f"{YELLOW}Scan de TOUS les symboles ({len(symbols)})...{RESET}")
    else:
        symbols = resolve_watchlist(args.symbols)

    if not symbols:
        print("Aucun symbole a analyser.")
        return 1

    results = scan_all_symbols(symbols, session_date, tf_name)

    if args.json:
        print(json.dumps(results_to_json(results), indent=2, ensure_ascii=False))
    else:
        print(render_all_results(results))

    return 0


# ─── Diamond Analysis ────────────────────────────────────────────────────────

def cmd_diamond(args):
    """
    Scan Diamond Analysis complet : Ichimoku multi-TF (H1/H4/D1) + Etape 3b
    (Tenkan D1 historique, SSB proximity) + scoring 8 criteres + trade setup.

    Combine le scan ICT asiatique avec l'analyse Ichimoku complete et la
    detection de memoire institutionnelle (flat lines passees).
    """
    _setup_logging(args.verbose)
    symbols = resolve_watchlist(args.symbols)
    if not symbols:
        print("Aucune watchlist. Spécifie --symbols ou configure INELIDA_WATCHLIST.")
        return 1

    scanner = DiamondScanner(symbols)
    if not scanner.initialize():
        print(f"{RED}Connexion MT5 impossible pour Diamond Scanner.{RESET}")
        return 2

    try:
        results = scanner.scan_all()
        _render_diamond_results(results, symbols)

        # ── Discord posting ────────────────────────────────────────────
        if getattr(args, 'discord', False):
            webhook_url = _load_discord_webhook()
            if webhook_url:
                ok = _post_diamond_to_discord(webhook_url, results, symbols)
                if ok:
                    print(f"\n{GREEN}📤 Resultats postes sur Discord.{RESET}")
                else:
                    print(f"\n{RED}❌ Echec de l'envoi Discord.{RESET}")
            else:
                print(f"\n{YELLOW}⚠ --discord active mais aucun webhook (DISCORD_WEBHOOK_URL non defini).{RESET}")
    finally:
        scanner.shutdown()
    return 0


# ─── Track P&L ────────────────────────────────────────────────────────────────

def cmd_track(args):
    """
    Suivi P&L automatise des setups Diamond dans le temps.

    Sous-commandes :
      save         : sauvegarde les setups actifs d'un scan Diamond
      update       : met a jour tous les trades ouverts avec les prix actuels
      report       : affiche le rapport P&L global
      history      : affiche l'historique detaille d'un trade
      sessions     : liste les sessions de scan enregistrees
      close        : ferme manuellement un trade
    """
    _setup_logging(args.verbose)
    action = args.track_action

    tracker = TradeTracker()

    if action == "save":
        # Lancer un scan Diamond puis sauvegarder
        symbols = resolve_watchlist(args.symbols)
        if not symbols:
            print(f"{YELLOW}Aucun symbole. Specifie --symbols ou configure INELIDA_WATCHLIST.{RESET}")
            return 1

        scanner = DiamondScanner(symbols)
        if not scanner.initialize():
            print(f"{RED}Connexion MT5 impossible.{RESET}")
            return 2
        try:
            results = scanner.scan_all()
            saved = tracker.save_setups(results)
            if saved > 0:
                print(f"{GREEN}{saved} setup(s) Diamond sauvegarde(s).{RESET}")
                print(f"{GRAY}Utilise 'track update' pour mettre a jour les prix, 'track report' pour le P&L.{RESET}")
            else:
                print(f"{YELLOW}Aucun setup actif (STRONG/GOOD) a sauvegarder.{RESET}")
        finally:
            scanner.shutdown()
        return 0

    if action == "update":
        # Fetch current prices from MT5 for all open trades
        prices = {}
        log = logging.getLogger("cmd_track")
        mt5_initialized = False
        try:
            import MetaTrader5 as mt5
            mt5_initialized = mt5.initialize()
            if mt5_initialized:
                # Fetch price for each open trade symbol
                cur = tracker.db.conn.execute(
                    "SELECT DISTINCT symbol FROM diamond_trades WHERE status = 'OPEN'"
                ) if tracker.db.conn else None
                if cur:
                    symbols = [r["symbol"] for r in cur.fetchall()]
                    for sym in symbols:
                        mt5.symbol_select(sym, True)
                        tick = mt5.symbol_info_tick(sym)
                        if tick:
                            prices[sym] = float(tick.bid)
        except Exception as e:
            log.warning("Impossible de recuperer les prix MT5: %s", e)
        finally:
            if mt5_initialized:
                try:
                    import MetaTrader5 as mt5
                    mt5.shutdown()
                except Exception:
                    pass

        if prices:
            updated = tracker.update_all(prices)
        else:
            log.warning("Aucun prix MT5 recu, mise a jour sans verification SL/TP")
            updated = tracker.update_all()

        if updated > 0:
            print(f"{GREEN}{updated} trade(s) mis a jour.{RESET}")
            if prices:
                print(f"  {GRAY}Prix MT5 recus pour {len(prices)} symbole(s).{RESET}")
        else:
            print(f"{YELLOW}Aucun trade ouvert a mettre a jour.{RESET}")
        return 0

    if action == "report":
        report = tracker.get_report(limit=args.limit or 20)
        if "error" in report:
            print(f"{RED}Erreur: {report['error']}{RESET}")
            return 1

        print(f"{BOLD}{CYAN}═══════════════════════════════════════{RESET}")
        print(f"{BOLD}{CYAN}  📊 RAPPORT P&L — Diamond Trades{RESET}")
        print(f"{BOLD}{CYAN}═══════════════════════════════════════{RESET}")
        print(f"")
        print(f"  {BOLD}Statistiques globales :{RESET}")
        print(f"    Total trades     : {report['total_trades']}")
        print(f"    Ouverts          : {report['open_trades']}")
        print(f"    Fermes           : {report['closed_trades']}")
        print(f"    Gains            : {GREEN}{report['wins']}{RESET}")
        print(f"    Pertes           : {RED}{report['losses']}{RESET}")
        print(f"    Win rate         : {report['win_rate']}%")
        if report['total_pnl_pips']:
            pnl_color = GREEN if report['total_pnl_pips'] >= 0 else RED
            print(f"    P&L total        : {pnl_color}{report['total_pnl_pips']:+.1f} pips{RESET}")
            print(f"    P&L moyen/trade  : {report['avg_pnl_pips']:+.1f} pips")
            print(f"    RR moyen         : {report['avg_rr']:.2f}x")
        print(f"")
        if report['best_trade']:
            b = report['best_trade']
            print(f"  {GREEN}🏆 Meilleur trade : {b['symbol']} {b['pnl_pips']:+.1f}p ({b['reason']}){RESET}")
        if report['worst_trade']:
            w = report['worst_trade']
            print(f"  {RED}💀 Pire trade     : {w['symbol']} {w['pnl_pips']:+.1f}p ({w['reason']}){RESET}")
        print(f"")

        # Derniers trades
        if report['trades']:
            print(f"  {BOLD}Derniers trades :{RESET}")
            header = (
                f"{BOLD}{'#':>4} {'Symbole':<10} {'Statut':>7} {'Score':>5} {'Biais':>5} "
                f"{'Prix':>10} {'SL':>10} {'TP':>10} {'P&L':>8}{RESET}"
            )
            print(f"  {header}")
            print(f"  {GRAY}{'-' * (len(header) - len(BOLD) - len(RESET))}{RESET}")
            for i, t in enumerate(report['trades']):
                if t['status'] == 'OPEN':
                    st = f"{CYAN}OPEN{RESET}"
                    pnl = f"{GRAY}?{RESET}"
                else:
                    pnl_v = t['pnl_pips'] or 0
                    pnl_c = GREEN if pnl_v > 0 else RED
                    st = f"{DIM}FERME{RESET}" if t['close_reason'] in ('SL_HIT',) else f"{GREEN}GAGNE{RESET}"
                    pnl = f"{pnl_c}{pnl_v:+.1f}{RESET}"

                bias_c = GREEN if t['bias'] == 'BULL' else (RED if t['bias'] == 'BEAR' else GRAY)
                print(
                    f"  {t['id']:>4} "
                    f"{MAGENTA}{t['symbol']:<10}{RESET} "
                    f"{st:>15} "
                    f"{bias_c}{t['bias']:>5}{RESET} "
                    f"{t['price']:>10.4f} "
                    f"{t['sl']:>10.4f} "
                    f"{t['tp']:>10.4f} "
                    f"{pnl:>8}"
                )

        print(f"")
        print(f"  {GRAY}Pour le detail d'un trade : track history --id <num>{RESET}")
        return 0

    if action == "history":
        trade_id = args.id
        if not trade_id:
            print(f"{RED}Specifie --id <numero du trade>{RESET}")
            return 1

        trade = tracker.get_history(trade_id)
        if trade is None:
            print(f"{RED}Trade #{trade_id} introuvable.{RESET}")
            return 1

        print(f"{BOLD}{CYAN}═══ Historique trade #{trade_id} — {trade['symbol']} ═══{RESET}")
        print(f"  Session   : {trade['session_id']}")
        print(f"  Statut    : {trade['status']}")
        print(f"  Score     : {trade['score']}/{trade['max_score']} | Biais: {trade['bias']} | Align: {trade['alignment']}")
        print(f"  Prix      : {trade['price']:.5f}")
        print(f"  SL        : {trade['sl']:.5f} | TP: {trade['tp']:.5f} ({trade['tp_label']}) | RR: {trade['rr']:.1f}x")
        if trade['asian_high'] and trade['asian_high'] > 0:
            print(f"  Asian R.  : AH={trade['asian_high']:.5f} AL={trade['asian_low']:.5f}")
        if trade['status'] == 'CLOSED':
            close_time = time.strftime("%Y-%m-%d %H:%M", time.gmtime(trade['close_time'])) if trade['close_time'] else "?"
            print(f"  Fermeture : {trade['close_reason']} a {trade['close_price']:.5f} ({close_time})")
            pnl_color = GREEN if (trade['pnl_pips'] or 0) >= 0 else RED
            print(f"  P&L       : {pnl_color}{trade['pnl_pips']:+.1f}p ({trade['pnl_percent']:+.0f}%) RR: {trade['pnl_rr']:.1f}x{RESET}")
        print(f"")

        snapshots = trade.get('snapshots', [])
        if snapshots:
            print(f"  {BOLD}Snapshots ({len(snapshots)}) :{RESET}")
            print(f"  {'#':>3} {'Heure':>16} {'Prix':>10} {'DistSL(p)':>10} {'DistTP(p)':>10} {'%Range':>8} {'Type'}")
            for i, s in enumerate(snapshots):
                ts = time.strftime("%H:%M", time.gmtime(s['timestamp']))
                stype = "💾" if s['snapshot_type'] == 'SAVE' else ("🏁" if s['snapshot_type'] == 'CLOSE' else " ")
                print(
                    f"  {i+1:>3} {ts:>16} "
                    f"{s['price']:>10.5f} {s['dist_to_sl_pips']:>10.1f} {s['dist_to_tp_pips']:>10.1f} "
                    f"{s['dist_to_sl_pct']:>7.1f}% {stype}"
                )
        return 0

    if action == "sessions":
        sessions = tracker.list_sessions(limit=args.limit or 10)
        if not sessions:
            print(f"{YELLOW}Aucune session enregistree.{RESET}")
            return 0
        print(f"{BOLD}{CYAN}═══ Sessions de scan Diamond ═══{RESET}")
        print(f"  {'Session':<12} {'Date':>16} {'Trades':>8} {'Ouverts':>8} {'Fermes':>8}")
        for s in sessions:
            first = time.strftime("%Y-%m-%d %H:%M", time.gmtime(s['first_scan'])) if s['first_scan'] else "?"
            print(f"  {s['session_id']:<12} {first:>16} {s['trades_count']:>8} {s['open_count']:>8} {s['closed_count']:>8}")
        print(f"")
        print(f"  {GRAY}Utilise 'track report' pour le P&L global.{RESET}")
        return 0

    if action == "close":
        trade_id = args.id
        if not trade_id:
            print(f"{RED}Specifie --id <numero du trade>{RESET}")
            return 1
        reason = args.reason or "MANUAL"
        ok = tracker.close_trade(trade_id, reason=reason)
        if ok:
            print(f"{GREEN}Trade #{trade_id} ferme ({reason}).{RESET}")
        else:
            print(f"{RED}Impossible de fermer le trade #{trade_id}.{RESET}")
        return 0

    # ── Sweep Watchlist ─────────────────────────────────────────────────
    if action == "watch":
        """Sauvegarde les niveaux London LH/LL a surveiller."""
        symbols = resolve_watchlist(args.symbols)
        if not symbols:
            print(f"{YELLOW}Aucun symbole. Specifie --symbols.{RESET}")
            return 1

        scanner = DiamondScanner(symbols)
        if not scanner.initialize():
            print(f"{RED}Connexion MT5 impossible.{RESET}")
            return 2
        try:
            results = scanner.scan_all()
            watch_data = tracker.save_sweep_watchlist(results)
            entries = watch_data.get("entries", [])
            count = watch_data.get("count", 0)

            print(f"{BOLD}{CYAN}═══════════════════════════════════════{RESET}")
            print(f"{BOLD}{CYAN}  🎯 SWEEP WATCHLIST — Niveaux London a surveiller{RESET}")
            print(f"{BOLD}{CYAN}═══════════════════════════════════════{RESET}")
            print(f"")
            print(f"  {GRAY}Session:{RESET} {watch_data.get('session_id', '?')}")
            now_str = _dt.now(_tz.utc).strftime("%Y-%m-%d %H:%M UTC")
            print(f"  {GRAY}Cree le:{RESET} {now_str}")
            print(f"")

            if count == 0:
                print(f"  {YELLOW}Aucun symbole avec un seul sweep London.{RESET}")
                print(f"  {GRAY}Il faut exactement 1 des 2 niveaux (LH ou LL) sweepe par NY.{RESET}")
            else:
                # Header
                print(f"  {'Symbole':<10} {'Dir':>5} {'Cible':>8} {'Target':>12} {'Dist':>6} {'Obstacles'}")
                print(f"  {GRAY}{'-'*65}{RESET}")
                for e in entries:
                    dir_icon = f"{GREEN}BULL{RESET}" if e["direction"] == "BULL" else f"{RED}BEAR{RESET}"
                    obs = e.get("obstacles", [])
                    obs_str = ", ".join([f"{o['label']}@{o['dist_pips']:+.0f}p" for o in obs[:3]])
                    if not obs_str:
                        obs_str = f"{GRAY}aucun{RESET}"
                    print(
                        f"  {MAGENTA}{e['symbol']:<10}{RESET} "
                        f"{dir_icon:>13} "
                        f"{e['target_label']:>8} "
                        f"{e['target']:>12.5f} "
                        f"{e['distance_pips']:>5.0f}p "
                        f"{obs_str}"
                    )

                print(f"")
                print(f"  {GREEN}{count} niveau(x) a surveiller. JSON exporte.{RESET}")
                json_path = watch_data.get("json_path", "")
                if json_path:
                    print(f"  {GRAY}Fichier: {json_path}{RESET}")
                print(f"")
                print(f"  {GRAY}Demain, utilise 'track verify --session {watch_data.get('session_id', '?')}'{RESET}")
                print(f"  {GRAY}pour verifier quels niveaux ont ete sweeps.{RESET}")
        finally:
            scanner.shutdown()
        return 0

    if action == "verify":
        """Verifie les niveaux d'une watchlist contre les prix actuels."""
        session_id = args.session
        if not session_id:
            print(f"{RED}Specifie --session <id> (ex: abcd1234).{RESET}")
            print(f"  {GRAY}Utilise 'track watchlist' pour voir les sessions disponibles.{RESET}")
            return 1

        symbols = resolve_watchlist(args.symbols)
        if not symbols:
            print(f"{YELLOW}Aucun symbole specifie.{RESET}")
            return 1

        scanner = DiamondScanner(symbols)
        if not scanner.initialize():
            print(f"{RED}Connexion MT5 impossible.{RESET}")
            return 2
        try:
            results = scanner.scan_all()
            verify_data = tracker.verify_sweep_watchlist(session_id, results)

            if "error" in verify_data:
                print(f"{RED}Erreur: {verify_data['error']}{RESET}")
                return 1

            print(f"{BOLD}{CYAN}═══════════════════════════════════════{RESET}")
            print(f"{BOLD}{CYAN}  ✅ VERIFICATION SWEEP WATCHLIST{RESET}")
            print(f"{BOLD}{CYAN}═══════════════════════════════════════{RESET}")
            print(f"")
            print(f"  {GRAY}Session:{RESET} {session_id}")
            print(f"  {GRAY}Verifie le:{RESET} {verify_data.get('verified_at', '?')}")
            print(f"")

            if verify_data.get("count", 0) == 0:
                print(f"  {YELLOW}{verify_data.get('message', 'Aucune entree PENDING')}{RESET}")
            else:
                print(f"  {GREEN}{verify_data['hits']} HIT{RESET} | {YELLOW}{verify_data['pending']} PENDING{RESET} | {GRAY}{verify_data['unknown']} UNKNOWN{RESET}")
                print(f"")
                print(f"  {'Symbole':<10} {'Target':>12} {'Status':>10} {'Message'}")
                print(f"  {GRAY}{'-'*65}{RESET}")
                for v in verify_data.get("results", []):
                    if v["status"] == "HIT":
                        st = f"{GREEN}HIT{RESET}"
                    elif v["status"] == "PENDING":
                        st = f"{YELLOW}PENDING{RESET}"
                    else:
                        st = f"{GRAY}UNKNOWN{RESET}"
                    print(
                        f"  {MAGENTA}{v['symbol']:<10}{RESET} "
                        f"{v['target']:>12.5f} "
                        f"{st:>18} "
                        f"{v.get('message', '')}"
                    )

                json_path = verify_data.get("json_path", "")
                if json_path:
                    print(f"  \n{GRAY}Rapport exporte : {json_path}{RESET}")
        finally:
            scanner.shutdown()
        return 0

    if action == "watchlist":
        """Liste les sessions de watchlist enregistrees."""
        watchlists = tracker.list_sweep_watchlists(limit=args.limit or 10)
        if not watchlists:
            print(f"{YELLOW}Aucune watchlist enregistree.{RESET}")
            print(f"  {GRAY}Utilise 'track watch' pour en creer une.{RESET}")
            return 0

        print(f"{BOLD}{CYAN}═══ Sweep Watchlists enregistrees ═══{RESET}")
        print(f"  {'Session':<12} {'Entrees':>8} {'Pending':>8} {'HIT':>5} {'Missed':>7} {'Cree le'}")
        for w in watchlists:
            created = w.get("created_at", "?")[:19] if w.get("created_at") else "?"
            print(
                f"  {w['session_id']:<12} "
                f"{w['entries_count']:>8} "
                f"{w.get('pending_count', 0):>8} "
                f"{GREEN}{w.get('hit_count', 0):>5}{RESET} "
                f"{w.get('missed_count', 0):>7} "
                f"{created}"
            )
        print(f"")
        print(f"  {GRAY}Pour verifier : track verify --session <id> --symbols ...{RESET}")
        return 0

    print(f"{RED}Action inconnue : {action}{RESET}")
    print(f"Actions: save, update, report, history, sessions, close, watch, verify, watchlist")
    return 1


def _load_discord_webhook():
    """Charge l'URL du webhook Discord depuis .env ou la variable d'environnement."""
    # 1. Check .env file (UTF-16 LE aware)
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.isfile(env_path):
        raw = None
        with open(env_path, "rb") as f:
            raw = f.read()
        # Detect UTF-16 LE
        if raw[:2] == b'\xff\xfe' or (len(raw) >= 6 and raw[1:6:2] == b'\x00\x00\x00'):
            text = raw.decode("utf-16-le", errors="ignore")
        else:
            text = raw.decode("utf-8", errors="ignore")
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("DISCORD_WEBHOOK_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    # 2. Check env var
    return os.environ.get("DISCORD_WEBHOOK_URL")


def _fmt(v):
    """Formate un prix pour Discord (sans codes ANSI)."""
    if v is None or v == 0:
        return "?"
    if isinstance(v, float):
        if abs(v) >= 1000:
            return f"{v:.2f}"
        if abs(v) >= 10:
            return f"{v:.4f}"
        return f"{v:.5f}"
    return str(v)


def _build_diamond_discord_embed(results, symbols_count: int) -> dict:
    """Construit un embed Discord a partir des resultats du Diamond Scanner."""
    now_str = _dt.now(_tz.utc).strftime("%Y-%m-%d %H:%M UTC")

    active = [r for r in results if r.bias != "FLAT" and r.quality != "WAIT"]
    n_strong = sum(1 for r in results if r.quality == "STRONG")
    n_good = sum(1 for r in results if r.quality == "GOOD")
    n_bull = sum(1 for r in results if r.bias == "BULL")
    n_bear = sum(1 for r in results if r.bias == "BEAR")

    # DXY info
    dxy_price = get_dxy_price()
    dxy_kj = get_dxy_kijun_h1()
    dxy_line = ""
    if dxy_price:
        dxy_line = f"DXY: **{dxy_price:.3f}**"
        if dxy_kj:
            vs = "AU-DESSUS 🔼" if dxy_price > dxy_kj else "EN-DESSOUS 🔽"
            dxy_line += f" | Kijun H1: {dxy_kj:.3f} | **{vs}**"

    # Top symboles (all)
    top_setups = []
    for r in sorted(results, key=lambda x: (0 if x.quality != "WAIT" else 1, -x.score))[:12]:
        d_kj = f" Δ{_fmt(r.d_kj4)}p" if r.d_kj4 != 0 else ""
        warn_str = " ⚠️" if r.warnings else ""
        top_setups.append(
            f"`{r.symbol:<10} {r.score:>2}/{r.max_score} {r.bias:<5} {r.quality:<7} "
            f"Kj4:{_fmt(r.kj_h4)}{d_kj}{warn_str}`"
        )
    if not top_setups:
        top_setups.append("Aucun symbole scanne.")

    # Active setups detail
    active_detail = []
    for r in active:
        bias_icon = "🔺" if r.bias == "BULL" else "🔻"
        tp_str = f"{_fmt(r.tp)}"
        if r.tp_label:
            tp_str += f" ({r.tp_label})"

        detail = (
            f"**{r.symbol}** {bias_icon} {r.bias} | Score: {r.score}/{r.max_score} | Align: {r.alignment} | RR: {r.rr:.1f}x\n"
            f"> SL: {_fmt(r.sl)} | TP: {tp_str} | ΔKj4: {_fmt(r.d_kj4)}p"
        )
        if r.horizon:
            detail += f" | Horizon: {r.horizon}"
        detail += f"\n> Criteres: {' '.join(r.criteria[:8])}"

        # Sweep AH/AL + LH/LL
        sweep_sp = []
        if r.asian_high_swept:
            sweep_sp.append(f"AH ✅ ({r.asian_high_swept_session or '?'})")
        if r.asian_low_swept:
            sweep_sp.append(f"AL ✅ ({r.asian_low_swept_session or '?'})")
        if r.london_high_swept:
            sweep_sp.append(f"LH ✅ ({r.london_high_swept_session or '?'})")
        if r.london_low_swept:
            sweep_sp.append(f"LL ✅ ({r.london_low_swept_session or '?'})")
        if sweep_sp:
            detail += f"\n> 🏹 {' | '.join(sweep_sp)}"

        if r.warnings:
            detail += f"\n> ⚠️ {' | '.join(r.warnings[:3])}"
        if r.compression_zone:
            detail += f"\n> 🔒 {r.compression_zone[:100]}"

        active_detail.append(detail)
    if not active_detail:
        active_detail.append("Aucun setup actif detecte.")

    # Warnings section
    warned = [r for r in results if r.warnings]
    warn_lines = []
    for r in warned[:6]:
        warn_lines.append(f"**{r.symbol}**: {' | '.join(r.warnings[:3])}")
    if not warn_lines:
        warn_lines.append("Aucun avertissement.")

    color = 0x2ECC71 if n_strong + n_good > 0 else (0xE67E22 if n_bull + n_bear > 0 else 0x3498DB)

    return {
        "title": f"💎 Diamond Analysis — {now_str}",
        "description": f"Scan Ichimoku multi-TF (H1→MN) sur {symbols_count} symboles\n{dxy_line}",
        "color": color,
        "fields": [
            {"name": "📊 Tous les symboles", "value": "\n".join(top_setups) or "—", "inline": False},
            {"name": "🎯 Setups actifs", "value": "\n\n".join(active_detail[:4]) or "—", "inline": False},
            {"name": "⚠️ Avertissements", "value": "\n".join(warn_lines[:8]) or "—", "inline": False},
            {"name": "📋 Resume", "value": (
                f"🟢 **{n_strong}** STRONG | 🟡 **{n_good}** GOOD | ⚪ **{symbols_count - n_strong - n_good}** WAIT\n"
                f"🔺 **{n_bull}** BULL | 🔻 **{n_bear}** BEAR"
            ), "inline": False},
        ],
        "footer": {"text": "Inelida Diamond Scanner"},
    }


def _post_diamond_to_discord(webhook_url: str, results, symbols) -> bool:
    """Envoie le scan Diamond sur Discord."""
    embed = _build_diamond_discord_embed(results, len(symbols))
    payload = json.dumps({"embeds": [embed]}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "InelidaDiamondScanner/1.0",
        },
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.status == 204
    except Exception as e:
        print(f"[Discord] Error: {e}", file=sys.stderr)
        return False


def _render_diamond_results(results: list, scanned_symbols: list):
    """Affichage complet du scan Diamond Analysis."""
    lines: list = []
    now_str = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    lines.append(f"{BOLD}{CYAN}{'='*100}{RESET}")
    lines.append(f"{BOLD}{CYAN}  💎 DIAMOND ANALYSIS — Scan Ichimoku Multi-TF + Memoire Institutionnelle (Etape 3b){RESET}")
    lines.append(f"{BOLD}{CYAN}{'='*100}{RESET}")
    lines.append(f"  {GRAY}UTC:{RESET} {now_str}  |  "
                 f"{GRAY}Symboles scannes:{RESET} {len(scanned_symbols)}  |  "
                 f"{GRAY}Setups Diamond:{RESET} {len(results)}")

    # DXY info
    dxy_price = get_dxy_price()
    dxy_kj = get_dxy_kijun_h1()
    if dxy_price:
        dxy_line = f"  {GRAY}DXY:{RESET} {dxy_price:.3f}"
        if dxy_kj:
            dxy_line += f"  {GRAY}Kijun H1:{RESET} {dxy_kj:.3f}"
            vs = "AU-DESSUS" if dxy_price > dxy_kj else "EN-DESSOUS"
            dxy_color = GREEN if dxy_price > dxy_kj else RED
            dxy_line += f"  {dxy_color}{vs}{RESET}"
        lines.append(dxy_line)
    lines.append("")

    if not results:
        lines.append(f"{YELLOW}  Aucun symbole scanne avec succes.{RESET}")
        lines.append(f"{BOLD}{CYAN}{'='*100}{RESET}")
        print("\n".join(lines))
        return

    # Table pour TOUS les resultats (actifs ET WAIT)
    lines.append(f"{BOLD}{CYAN}═══ TOUS LES SYMBOLES SCANNES ═══{RESET}")

    # Header
    header = (
        f"{BOLD}"
        f"{'Symbole':<10} {'Score':>6} {'Biais':>6} {'Qualite':>8}  "
        f"{'Prix':>10} {'Kj H1':>10} {'Kj H4':>10} {'Kj D1':>10}  "
        f"{'T/Kx H1':>8} {'T/Kx H4':>8} {'T/Kx D1':>8}  "
        f"{'Kumo H1':>8} {'Kumo H4':>8} {'Kumo D1':>8}  "
        f"{'Flat H1':>8} {'Flat H4':>8}  "
        f"{'Lon H':>10} {'Lon L':>10} {'Lon Swp':>8}"
        f"{RESET}"
    )
    lines.append(header)
    lines.append(f"{GRAY}{'─'*100}{RESET}")

    for r in results:
        # Score color (relative to max_score)
        score_pct = r.score / r.max_score if r.max_score > 0 else 0
        if score_pct >= 0.75:
            sc_col = f"{GREEN}{r.score}{RESET}"
        elif score_pct >= 0.55:
            sc_col = f"{YELLOW}{r.score}{RESET}"
        elif score_pct >= 0.35:
            sc_col = f"{DIM}{r.score}{RESET}"
        else:
            sc_col = f"{RED}{r.score}{RESET}"

        # Bias color
        if r.bias == "BULL":
            bias_col = f"{GREEN}{r.bias}{RESET}"
        elif r.bias == "BEAR":
            bias_col = f"{RED}{r.bias}{RESET}"
        else:
            bias_col = f"{GRAY}{r.bias}{RESET}"

        # Quality
        if r.quality == "STRONG":
            qual_col = f"{BOLD}{GREEN}STRONG{RESET}"
        elif r.quality == "GOOD":
            qual_col = f"{YELLOW}GOOD{RESET}"
        else:
            qual_col = f"{DIM}WAIT{RESET}"

        # Kumo colors
        def _kc(val):
            if val == "ABOVE":
                return f"{GREEN}ABOVE{RESET}"
            elif val == "BELOW":
                return f"{RED}BELOW{RESET}"
            return f"{YELLOW}INSIDE{RESET}"

        # T/K cross colors
        def _tkc(val):
            if val == "BULL":
                return f"{GREEN}BULL{RESET}"
            if val == "BEAR":
                return f"{RED}BEAR{RESET}"
            return f"{GRAY}N/A{RESET}"

        def _ff(val):
            if val >= 8:
                return f"{GREEN}{val:>3}b{RESET}"
            elif val >= 4:
                return f"{YELLOW}{val:>3}b{RESET}"
            elif val > 0:
                return f"{DIM}{val:>3}b{RESET}"
            return f"{GRAY}  0{RESET}"

        def _london_swp(r_lo) -> str:
            """Indicateur de sweep London (LH/LL) pour le tableau principal."""
            if r_lo.london_high <= 0 or r_lo.london_low <= 0:
                return f"{GRAY}--{RESET}"
            if r_lo.london_high_swept and r_lo.london_low_swept:
                return f"{YELLOW}H+L{RESET}"
            if r_lo.london_high_swept:
                return f"{RED}LH{RESET}"
            if r_lo.london_low_swept:
                return f"{GREEN}LL{RESET}"
            return f"{GRAY}--{RESET}"

        lines.append(
            f"{MAGENTA}{r.symbol:<10}{RESET} "
            f"{_pad_cell(sc_col, 6)} "
            f"{_pad_cell(bias_col, 6)} "
            f"{_pad_cell(qual_col, 8)}  "
            f"{_fmt_price(r.price):>10} {_fmt_price(r.kj_h1):>10} {_fmt_price(r.kj_h4):>10} {_fmt_price(r.kj_d1):>10}  "
            f"{_pad_cell(_tkc(r.tkx_h1), 8)} {_pad_cell(_tkc(r.tkx_h4), 8)} {_pad_cell(_tkc(r.tkx_d1), 8)}  "
            f"{_pad_cell(_kc(r.kumo_h1), 8)} {_pad_cell(_kc(r.kumo_h4), 8)} {_pad_cell(_kc(r.kumo_d1), 8)}  "
            f"{_pad_cell(_ff(r.flat_h1), 8)} {_pad_cell(_ff(r.flat_h4), 8)}  "
            f"{_fmt_price(r.london_high):>10} {_fmt_price(r.london_low):>10} {_pad_cell(_london_swp(r), 8)}"
        )

    lines.append(f"{GRAY}{'─'*100}{RESET}")
    lines.append("")

    # ── Detail des setups actifs ──
    active = [r for r in results if r.bias != "FLAT" and r.quality != "WAIT"]
    if active:
        lines.append(f"{BOLD}{CYAN}═══ SETUPS DIAMOND ACTIFS (BULL/BEAR + STRONG/GOOD) ═══{RESET}")
        lines.append("")
        for r in active:
            _render_diamond_detail(r, lines)

    # ── Warning section (tous les symboles avec avertissements) ──
    warned = [r for r in results if r.warnings]
    if warned:
        lines.append(f"{BOLD}{YELLOW}═══ AVERTISSEMENTS (Etape 3b — Memoire institutionnelle) ═══{RESET}")
        lines.append("")
        for r in warned:
            sym_warn = f"  {MAGENTA}{r.symbol:<10}{RESET} "
            for w in r.warnings:
                sym_warn += f"{YELLOW}[{w}]{RESET}  "
            lines.append(sym_warn)
        lines.append("")

    lines.append(f"{BOLD}{CYAN}{'='*100}{RESET}")

    # Summary
    n_strong = sum(1 for r in results if r.quality == "STRONG")
    n_good = sum(1 for r in results if r.quality == "GOOD")
    n_wait = sum(1 for r in results if r.quality == "WAIT")
    n_bull = sum(1 for r in results if r.bias == "BULL")
    n_bear = sum(1 for r in results if r.bias == "BEAR")
    lines.append(
        f"{GREEN}{n_strong} STRONG{RESET} | "
        f"{YELLOW}{n_good} GOOD{RESET} | "
        f"{GRAY}{n_wait} WAIT{RESET} | "
        f"BULL: {n_bull} | BEAR: {n_bear}"
    )

    print("\n".join(lines))


def _kc_mini(val: str) -> str:
    """Mini indicateur Kumo (1 char)."""
    if val == "ABOVE": return f"{GREEN}▲{RESET}"
    if val == "BELOW": return f"{RED}▼{RESET}"
    if val == "INSIDE": return f"{YELLOW}◆{RESET}"
    return f"{GRAY}?{RESET}"

def _tkc_mini(val: str) -> str:
    """Mini indicateur T/K cross."""
    if val == "BULL": return f"{GREEN}TK▲{RESET}"
    if val == "BEAR": return f"{RED}TK▼{RESET}"
    return f"{GRAY}TK?{RESET}"

def _render_diamond_detail(r, lines: list):
    """Affiche le detail d'un setup Diamond actif (incluant W1/MN)."""
    quality_icon = "STRONG" if r.quality == "STRONG" else "GOOD"
    bias_icon = "🔺" if r.bias == "BULL" else "🔻"

    horizon_str = f"  |  {CYAN}Horizon: {r.horizon}{RESET}" if r.horizon else ""
    kj_d1_str = f"  |  ΔKjD1: {r.d_kj_d1:+.1f}p" if r.kj_d1 > 0 else ""
    tk_h4_str = f"  |  ΔTkH4: {r.d_tk_h4:+.1f}p" if r.d_tk_h4 != 0 else ""
    lines.append(f"  {BOLD}{quality_icon} {MAGENTA}{r.symbol}{RESET}  "
                 f"{bias_icon} {r.bias}  "
                 f"Score: {r.score}/{r.max_score}  |  Align: {r.alignment}  |  "
                 f"ΔKj4: {r.d_kj4:+.1f}p"
                 f"{kj_d1_str}"
                 f"{tk_h4_str}  |  "
                 f"RR: {r.rr:.1f}x"
                 f"{horizon_str}")
    # Asian Range (ICT extensions)
    if r.asian_high > 0 and r.asian_low > 0:
        asi_range = abs(r.asian_high - r.asian_low)
        asi_range_pips = asi_range * (100 if hasattr(r, 'symbol') and ('JPY' in r.symbol or 'DXY' in r.symbol) else 10000)
        ext_label = r.tp_label if 'Ext' in r.tp_label else ""
        line = (f"    {GRAY}Asian Range:{RESET} AH={_fmt_price(r.asian_high)}  "
                f"AL={_fmt_price(r.asian_low)}  "
                f"Range={asi_range_pips:.1f}p")
        if ext_label:
            line += f"  {CYAN}▶ {ext_label}{RESET}"
        lines.append(line)
        # Sweep status
        sweep_parts = []
        if r.asian_high_swept:
            hs = r.asian_high_swept_session or "?"
            sweep_parts.append(f"{RED}AH sweepé{RESET} ({hs})")
        if r.asian_low_swept:
            ls = r.asian_low_swept_session or "?"
            sweep_parts.append(f"{GREEN}AL sweepé{RESET} ({ls})")
        if sweep_parts:
            lines.append(f"    {GRAY}Sweeps:{RESET} {' | '.join(sweep_parts)}")
    # London Range (LH/LL sweeps by NY)
    if r.london_high > 0 and r.london_low > 0:
        london_range_pips = abs(r.london_high - r.london_low) * (100 if hasattr(r, 'symbol') and ('JPY' in r.symbol or 'DXY' in r.symbol) else 10000)
        line = (f"    {GRAY}London Range:{RESET} LH={_fmt_price(r.london_high)}  "
                f"LL={_fmt_price(r.london_low)}  "
                f"Range={london_range_pips:.1f}p")
        lines.append(line)
        lh_parts = []
        if r.london_high_swept:
            lh_s = r.london_high_swept_session or "?"
            lh_parts.append(f"{RED}LH sweepé{RESET} ({lh_s})")
        if r.london_low_swept:
            ll_s = r.london_low_swept_session or "?"
            lh_parts.append(f"{GREEN}LL sweepé{RESET} ({ll_s})")
        if lh_parts:
            lines.append(f"    {GRAY}Sweeps L:{RESET} {' | '.join(lh_parts)}")

    lines.append(f"    {GRAY}Critères:{RESET} {' '.join(r.criteria)}")

    if r.bias != "FLAT":
        tp_detail = f"{GRAY}TP:{RESET} {_fmt_price(r.tp)}"
        if r.tp_label:
            tp_detail += f" {DIM}({r.tp_label}){RESET}"
        lines.append(f"    {GRAY}Kijun H4:{RESET} {_fmt_price(r.kj_h4)}  "
                     f"{GRAY}SL:{RESET} {_fmt_price(r.sl)}  "
                     f"{tp_detail}")

    # Tenkan/Kijun values par TF (niveaux exacts)
    tk_kj_parts = []
    for tf_name, tk_val, kj_val in [
        ("H1", r.tk_h1, r.kj_h1),
        ("H4", r.tk_h4, r.kj_h4),
        ("D1", r.tk_d1, r.kj_d1),
    ]:
        if kj_val > 0:
            tk_kj_parts.append(f"{GRAY}{tf_name}:{RESET} T={_fmt_price(tk_val)} K={_fmt_price(kj_val)}")
    # W1/MN only if available
    if r.kj_w1 > 0:
        tk_kj_parts.append(f"{GRAY}W1:{RESET} T={_fmt_price(r.tk_w1)} K={_fmt_price(r.kj_w1)}")
    if r.kj_mn > 0:
        tk_kj_parts.append(f"{GRAY}MN:{RESET} T={_fmt_price(r.tk_mn)} K={_fmt_price(r.kj_mn)}")
    if tk_kj_parts:
        lines.append(f"    {GRAY}Niveaux:{RESET} {' | '.join(tk_kj_parts)}")

    # W1/MN Kijun values
    w1mn_parts = []
    if r.kj_w1 > 0:
        w1mn_parts.append(f"{GRAY}W1:{RESET} {_fmt_price(r.kj_w1)} "
                          f"{_kc_mini(r.kumo_w1)} "
                          f"{_tkc_mini(r.tkx_w1)}")
    if r.kj_mn > 0:
        mn_extra = ""
        if r.months_vs_kj_mn > 0:
            mn_extra = f" [AU-DESSUS {r.months_vs_kj_mn}mo]"
        elif r.price < r.kj_mn:
            mn_extra = " [EN-DESSOUS]"
        w1mn_parts.append(f"{GRAY}MN:{RESET} {_fmt_price(r.kj_mn)} "
                          f"{_kc_mini(r.kumo_mn)} "
                          f"{_tkc_mini(r.tkx_mn)}"
                          f"{mn_extra}")
    if w1mn_parts:
        lines.append(f"    {' | '.join(w1mn_parts)}")

    # Clouds
    cloud_parts = []
    if r.cloud_w1_color != "N/A":
        cloud_parts.append(f"{GRAY}Nuage W1:{RESET} {r.cloud_w1_color} "
                           f"{_fmt_price(r.cloud_w1_bot)}-{_fmt_price(r.cloud_w1_top)}")
    if r.cloud_mn_color != "N/A":
        cloud_parts.append(f"{GRAY}Nuage MN:{RESET} {r.cloud_mn_color} "
                           f"{_fmt_price(r.cloud_mn_bot)}-{_fmt_price(r.cloud_mn_top)}")
    if cloud_parts:
        lines.append(f"    {' | '.join(cloud_parts)}")

    # Etape 3b : Tenkan flat history (TOUS les TFs)
    tenkan_display = [
        (r.tenkan_flat_h1, "Tenkan H1", "b", 2),
        (r.tenkan_flat_h4, "Tenkan H4", "b", 2),
        (r.tenkan_flats, "Tenkan D1", "j", 3),
        (r.tenkan_flat_w1, "Tenkan W1", "sem", 1),
        (r.tenkan_flat_mn, "Tenkan MN", "mois", 1),
    ]
    for flats, label, unit, max_show in tenkan_display:
        for tf in flats[:max_show]:
            d_icon = "R" if tf.direction == "RESISTANCE" else "S"
            dm_tag = " [DOUBLE MEMOIRE]" if (label == "Tenkan MN" and r.double_memory) else ""
            if label in ("Tenkan D1",):
                lines.append(
                    f"    {DIM}{label} hist:{RESET} {d_icon} "
                    f"{_fmt_price(tf.level)} ({tf.dist_pips:+.0f}p, {tf.duration}{unit} "
                    f"{tf.start_dt.strftime('%d/%m')}-{tf.end_dt.strftime('%d/%m')}) "
                    f"{tf.direction}{dm_tag}"
                )
            else:
                lines.append(
                    f"    {DIM}{label} hist:{RESET} {_fmt_price(tf.level)} "
                    f"({tf.dist_pips:+.0f}p, {tf.duration}{unit}) {tf.direction}{dm_tag}"
                )

    # Kumo FUTUR (TOUS les TFs)
    fut_parts = []
    for cf_top, cf_bot, cf_color, cf_flat, label in [
        (r.cloud_fut_h1_top, r.cloud_fut_h1_bot, r.cloud_fut_h1_color, r.cloud_fut_h1_flat, "H1"),
        (r.cloud_fut_h4_top, r.cloud_fut_h4_bot, r.cloud_fut_h4_color, r.cloud_fut_h4_flat, "H4"),
        (r.cloud_fut_d1_top, r.cloud_fut_d1_bot, r.cloud_fut_d1_color, r.cloud_fut_d1_flat, "D1"),
        (r.cloud_fut_w1_top, r.cloud_fut_w1_bot, r.cloud_fut_w1_color, r.cloud_fut_w1_flat, "W1"),
        (r.cloud_fut_mn_top, r.cloud_fut_mn_bot, r.cloud_fut_mn_color, r.cloud_fut_mn_flat, "MN"),
    ]:
        if cf_color != "N/A":
            flat_tag = " [PLAT]" if cf_flat else ""
            fut_parts.append(
                f"{GRAY}{label}:{RESET} {cf_color} "
                f"{_fmt_price(cf_bot)}-{_fmt_price(cf_top)}{flat_tag}"
            )
    if fut_parts:
        lines.append(f"    {GRAY}Kumo Futur (+26b):{RESET} {' | '.join(fut_parts)}")

    # Kijun flat history (TOUS les TFs)
    kijun_display = [
        (r.kijun_flats_h1, "Kijun H1", "b"),
        (r.kijun_flats_h4, "Kijun H4", "b"),
        (r.kijun_flats_d1, "Kijun D1", "j"),
        (r.kijun_flats_w1, "Kijun W1", "sem"),
        (r.kijun_flats_mn, "Kijun MN", "mois"),
    ]
    for flats, label, unit in kijun_display:
        for kf in flats[:1]:
            lines.append(
                f"    {DIM}{label} hist:{RESET} {_fmt_price(kf.level)} "
                f"({kf.dist_pips:+.0f}p, {kf.duration}{unit}) {kf.direction}"
            )

    # SSB proximity (TOUS les TFs)
    ssb_display = [
        (r.ssb_h1, "SSB H1"),
        (r.ssb_h4, "SSB H4"),
        (r.ssb_d1, "SSB D1"),
        (r.ssb_w1, "SSB W1"),
        (r.ssb_mn, "SSB MN"),
    ]
    for ssb_list, label in ssb_display:
        for sb_l, sb_d in ssb_list[:1]:
            lines.append(
                f"    {DIM}{label}:{RESET} {_fmt_price(sb_l)} ({sb_d:.1f}p)"
            )

    # FVG H1 (bearish gap — e.g. 18h-20h Paris)
    if r.fvg_h1_bear_top > 0 and r.fvg_h1_bear_bot > 0:
        gap_pips = abs(r.fvg_h1_bear_top - r.fvg_h1_bear_bot) * r.fvg_h1_bear_pip_factor
        mit = "MITIGE" if r.fvg_h1_bear_mitigated else "NON MITIGE"
        pos_col = GREEN if r.fvg_h1_bear_price_pos == "ABOVE" else (RED if r.fvg_h1_bear_price_pos == "BELOW" else YELLOW)
        lines.append(
            f"    {RED}FVG H1 Bear {r.fvg_h1_bear_date}:{RESET} {_fmt_price(r.fvg_h1_bear_bot)}-{_fmt_price(r.fvg_h1_bear_top)} "
            f"({gap_pips:.0f}p) [{mit}] [{pos_col}{r.fvg_h1_bear_price_pos}{RESET}]"
        )
    if r.fvg_h1_bull_top > 0 and r.fvg_h1_bull_bot > 0:
        gap_pips = abs(r.fvg_h1_bull_top - r.fvg_h1_bull_bot) * r.fvg_h1_bull_pip_factor
        mit = "MITIGE" if r.fvg_h1_bull_mitigated else "NON MITIGE"
        pos_col = GREEN if r.fvg_h1_bull_price_pos == "ABOVE" else (RED if r.fvg_h1_bull_price_pos == "BELOW" else YELLOW)
        lines.append(
            f"    {GREEN}FVG H1 Bull {r.fvg_h1_bull_date}:{RESET} {_fmt_price(r.fvg_h1_bull_bot)}-{_fmt_price(r.fvg_h1_bull_top)} "
            f"({gap_pips:.0f}p) [{mit}] [{pos_col}{r.fvg_h1_bull_price_pos}{RESET}]"
        )

    # FVG H4
    if r.fvg_h4_bear_top > 0 and r.fvg_h4_bear_bot > 0:
        gap_pips = abs(r.fvg_h4_bear_top - r.fvg_h4_bear_bot) * r.fvg_h4_bear_pip_factor
        mit = "MITIGE" if r.fvg_h4_bear_mitigated else "NON MITIGE"
        pos_col = GREEN if r.fvg_h4_bear_price_pos == "ABOVE" else (RED if r.fvg_h4_bear_price_pos == "BELOW" else YELLOW)
        lines.append(
            f"    {RED}FVG H4 Bear {r.fvg_h4_bear_date}:{RESET} {_fmt_price(r.fvg_h4_bear_bot)}-{_fmt_price(r.fvg_h4_bear_top)} "
            f"({gap_pips:.0f}p) [{mit}] [{pos_col}{r.fvg_h4_bear_price_pos}{RESET}]"
        )
    if r.fvg_h4_bull_top > 0 and r.fvg_h4_bull_bot > 0:
        gap_pips = abs(r.fvg_h4_bull_top - r.fvg_h4_bull_bot) * r.fvg_h4_bull_pip_factor
        mit = "MITIGE" if r.fvg_h4_bull_mitigated else "NON MITIGE"
        pos_col = GREEN if r.fvg_h4_bull_price_pos == "ABOVE" else (RED if r.fvg_h4_bull_price_pos == "BELOW" else YELLOW)
        lines.append(
            f"    {GREEN}FVG H4 Bull {r.fvg_h4_bull_date}:{RESET} {_fmt_price(r.fvg_h4_bull_bot)}-{_fmt_price(r.fvg_h4_bull_top)} "
            f"({gap_pips:.0f}p) [{mit}] [{pos_col}{r.fvg_h4_bull_price_pos}{RESET}]"
        )

    # FVG D1
    if r.fvg_d1_bear_top > 0 and r.fvg_d1_bear_bot > 0:
        gap_pips = abs(r.fvg_d1_bear_top - r.fvg_d1_bear_bot) * r.fvg_d1_bear_pip_factor
        mit = "MITIGE" if r.fvg_d1_bear_mitigated else "NON MITIGE"
        pos_col = GREEN if r.fvg_d1_bear_price_pos == "ABOVE" else (RED if r.fvg_d1_bear_price_pos == "BELOW" else YELLOW)
        lines.append(
            f"    {RED}FVG D1 Bear {r.fvg_d1_bear_date}:{RESET} {_fmt_price(r.fvg_d1_bear_bot)}-{_fmt_price(r.fvg_d1_bear_top)} "
            f"({gap_pips:.0f}p) [{mit}] [{pos_col}{r.fvg_d1_bear_price_pos}{RESET}]"
        )
    if r.fvg_d1_bull_top > 0 and r.fvg_d1_bull_bot > 0:
        gap_pips = abs(r.fvg_d1_bull_top - r.fvg_d1_bull_bot) * r.fvg_d1_bull_pip_factor
        mit = "MITIGE" if r.fvg_d1_bull_mitigated else "NON MITIGE"
        pos_col = GREEN if r.fvg_d1_bull_price_pos == "ABOVE" else (RED if r.fvg_d1_bull_price_pos == "BELOW" else YELLOW)
        lines.append(
            f"    {GREEN}FVG D1 Bull {r.fvg_d1_bull_date}:{RESET} {_fmt_price(r.fvg_d1_bull_bot)}-{_fmt_price(r.fvg_d1_bull_top)} "
            f"({gap_pips:.0f}p) [{mit}] [{pos_col}{r.fvg_d1_bull_price_pos}{RESET}]"
        )

    # Compression (Etape 7b)
    if r.compression_zone:
        lines.append(f"    {YELLOW}⚠ {r.compression_zone}{RESET}")

    # Warnings
    if r.warnings:
        for w in r.warnings:
            lines.append(f"    {YELLOW}⚠ {w}{RESET}")
    lines.append("")


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
    p_asian.add_argument("--swept-only", action="store_true",
                         help="N'affiche que les symboles avec AH ou AL sweep (filtre les non-sweep).")
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

    # ── diamond ──────────────────────────────────────────────────────────
    p_diamond = sub.add_parser(
        "diamond",
        help="Scan Diamond Analysis complet : Ichimoku multi-TF (H1/H4/D1) + "
             "Etape 3b (Tenkan D1 historique, SSB) + scoring + trade setup.",
    )
    _add_common(p_diamond)
    p_diamond.add_argument(
        "--discord", action="store_true",
        help="Poste automatiquement les resultats sur Discord (via DISCORD_WEBHOOK_URL env var)."
    )

    # ── track (P&L) ───────────────────────────────────────────────────────
    p_track = sub.add_parser(
        "track",
        help="Suivi P&L automatise des setups Diamond. Actions: save, update, report, history.",
    )
    p_track.add_argument(
        "track_action",
        choices=["save", "update", "report", "history", "sessions", "close",
                 "watch", "verify", "watchlist"],
        help="Action a executer",
    )
    _add_common(p_track)
    p_track.add_argument("--id", type=int, default=None,
                         help="ID du trade (pour history/close)")
    p_track.add_argument("--reason", default="MANUAL",
                         help="Raison de fermeture (pour close)")
    p_track.add_argument("--session", default=None,
                         help="Session ID pour verify/watchlist (ex: abcd1234)")
    p_track.add_argument("--limit", type=int, default=20,
                         help="Nombre max de trades/sessions a afficher")

    # ── asian-liquidity ───────────────────────────────────────────────────
    p_asian_liq = sub.add_parser(
        "asian-liquidity",
        help="Scan BSL/SSL intra-Asian : swing points (Williams fractals) "
             "crees pendant la session asiatique + statut de sweep post-Asian.",
    )
    p_asian_liq.add_argument("--tf", default="M15",
                             choices=["M1", "M5", "M15", "M30", "H1"],
                             help="Timeframe (defaut: M15)")
    p_asian_liq.add_argument("--session-date", dest="session_date", default=None,
                             help="Date YYYY-MM-DD (defaut: aujourd'hui UTC)")
    p_asian_liq.add_argument("--scan-all", action="store_true",
                             help="Scanner TOUS les symboles MT5 disponibles")
    p_asian_liq.add_argument("--json", action="store_true",
                             help="Sortie JSON au lieu du tableau ASCII")
    _add_common(p_asian_liq)

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
        "setups":          cmd_setups,
        "diamond":         cmd_diamond,
        "track":            cmd_track,
        "asian-liquidity": cmd_asian_liquidity,
    }
    try:
        return handlers[args.command](args)
    except KeyboardInterrupt:
        print("\nInterrompu.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
