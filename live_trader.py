"""
live_trader.py — Moniteur continu + Exécution automatique
=========================================================
Fusion de live_alerts.py (scan H1 en boucle + alertes visuelles)
et de src/trade_executor.py (envoi d'ordres MT5).

DRY-RUN par défaut : rien n'est envoyé au broker sans le flag --live.

Usage :
    python live_trader.py                           # DRY-RUN (sécurisé)
    python live_trader.py --live                    # EXÉCUTION RÉELLE
    python live_trader.py --live --lots 0.02        # lots custom
    python live_trader.py --rr-min 1.0              # filtre RR >= 1.0
    python live_trader.py --interval 60             # scan toutes les 60s
    python live_trader.py --symbols "XAUUSD,EURUSD"
"""

import os
import sys
import time
import json
import argparse
from datetime import datetime, timezone
from typing import Dict, Set, Optional, List, Tuple

import MetaTrader5 as mt5

PROJECT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT)

from src.sweep_detector import detect_asian_range_for_symbol
from src.config import ELITE
from src.trade_executor import (
    TradeExecutor,
    TradeDecision,
    TradeResult,
    asian_to_decisions,
)

UTC = timezone.utc
DEFAULT_INTERVAL = 30
ALERT_DIR = os.path.join(PROJECT, "logs")
os.makedirs(ALERT_DIR, exist_ok=True)
ALERT_LOG = os.path.join(ALERT_DIR, "live_trader.log")
EXEC_LOG = os.path.join(ALERT_DIR, "live_trader_executions.jsonl")
MAX_SPREAD_PCT = 0.10

# ─── ANSI ───────────────────────────────────────────────────────────────────
_IS_TTY = sys.stdout.isatty()
def _c(c): return c if _IS_TTY else ""
BOLD  = _c("\033[1m")
DIM   = _c("\033[2m")
RED   = _c("\033[31m")
GREEN = _c("\033[32m")
YELLOW= _c("\033[33m")
CYAN  = _c("\033[36m")
MAGENTA=_c("\033[35m")
WHITE = _c("\033[97m")
BG_RED   = _c("\033[41m")
BG_GREEN = _c("\033[42m")
BG_YELLOW= _c("\033[43m")
BG_CYAN  = _c("\033[46m")
RESET = _c("\033[0m")
BELL  = "\a"


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS (reprise de live_alerts.py)
# ═══════════════════════════════════════════════════════════════════════════════

def _is_tradeable(name: str) -> bool:
    n = name.upper()
    if len(n) == 6 and n.isalpha():
        return True
    if n.endswith(("MXN", "ZAR", "TRY", "PLN", "HUF", "CZK",
                    "NOK", "SEK", "SGD", "HKD", "CNH", "ILS")) and len(n) == 6:
        return True
    if any(n.startswith(p) for p in ["XAU", "XAG", "XPD", "XPT", "XCU"]):
        return True
    if len(n) >= 5 and len(n) <= 7 and n.endswith(("USD", "EUR")) \
       and not (len(n) == 6 and n.isalpha()):
        return True
    if n.endswith((".CASH", ".C")):
        return True
    if n in ("DXY", "US30", "US500", "NAS100", "SPX500", "US100", "US2000"):
        return True
    return False


def _fmt(p: Optional[float]) -> str:
    if p is None or p == 0:
        return "--"
    p_abs = abs(p)
    if p_abs >= 1000:   return f"{p:.2f}"
    if p_abs >= 10:     return f"{p:.4f}"
    return f"{p:.5f}"


def _now_str() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S") + " UTC"


def _paris_hour() -> str:
    n = datetime.now(UTC)
    h = (n.hour + 2) % 24
    return f"{h:02d}:{n.minute:02d}"


def _session() -> str:
    h = datetime.now(UTC).hour
    if 0 <= h < 8:      return "ASIAN"
    if 8 <= h < 13:     return "LONDON"
    if 13 <= h < 16:    return "NY OPEN"
    if 16 <= h < 22:    return "NY"
    return "ASIAN PRE"


def _trade_key(r) -> str:
    if not r.trade_action or r.trade_action == "-" or r.trade_entry is None:
        return ""
    return f"{r.symbol}_{r.trade_action}"


def _spread_too_high(symbol: str) -> bool:
    try:
        tick = mt5.symbol_info_tick(symbol)
        if tick is None or tick.bid == 0:
            return True
        spread_pct = (tick.ask - tick.bid) / tick.bid * 100
        return spread_pct > MAX_SPREAD_PCT
    except Exception:
        return True


def _in_window(config) -> Tuple[bool, str]:
    if not config.enabled:
        return True, "OFF"
    now = datetime.now(UTC)
    in_window = (
        (now.hour > config.start_hour_utc or (now.hour == config.start_hour_utc and now.minute >= config.start_minute_utc))
        and (now.hour < config.end_hour_utc or (now.hour == config.end_hour_utc and now.minute <= config.end_minute_utc))
    )
    if in_window:
        return True, f"{GREEN}OUVERTE{RESET} (jusqu'a {config.end_hour_utc:02d}:{config.end_minute_utc:02d})"
    return False, f"{YELLOW}FERMEE{RESET} (ouverture a {config.start_hour_utc:02d}:{config.start_minute_utc:02d})"


def _is_valid_trade(r) -> bool:
    if not r.trade_action or r.trade_action == "-":
        return False
    if r.trade_entry is None or r.trade_sl is None or r.trade_tp1 is None:
        return False
    if r.trade_rr1 is None or r.trade_rr1 <= 0:
        return False
    if r.trade_status in ("Range too tight", "No valid TP", "Targets hit", "-"):
        return False
    if _spread_too_high(r.symbol):
        return False
    return True


def _spread_str(symbol: str) -> str:
    try:
        tick = mt5.symbol_info_tick(symbol)
        if tick is None or tick.bid == 0:
            return "?"
        spread_pct = (tick.ask - tick.bid) / tick.bid * 100
        return f"{spread_pct:.3f}%"
    except Exception:
        return "?"


def _calculate_lots_for_risk(symbol: str, entry: float, sl: float,
                              action: str, risk_pct: float) -> Optional[float]:
    """Calcule la taille de lot dynamique pour risquer risk_pct% du capital.

    Utilise mt5.order_calc_profit() pour estimer la perte sur 1 lot standard
    si le SL est touché, puis scale pour que la perte = risk_amount.

    Retourne le lot arrondi au volume_step du symbole, ou None en cas d'erreur.
    """
    try:
        account_info = mt5.account_info()
        if account_info is None or account_info.equity <= 0:
            return None

        risk_amount = account_info.equity * risk_pct / 100.0

        # Perte sur 1 lot standard si le SL est touché
        order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL
        profit_1_lot = mt5.order_calc_profit(order_type, symbol, 1.0, entry, sl)

        if profit_1_lot is None or profit_1_lot >= 0:
            return None  # profit positif ou None = pas de perte, calcul impossible

        lots = risk_amount / abs(profit_1_lot)

        # Arrondir au volume_step du symbole
        info = mt5.symbol_info(symbol)
        if info is None:
            return None

        step = info.volume_step or 0.01
        lots = (int(lots / step)) * step
        lots = max(lots, info.volume_min)
        lots = min(lots, info.volume_max)
        return round(lots, 8)

    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# AFFICHAGE ALERTE (identique à live_alerts.py)
# ═══════════════════════════════════════════════════════════════════════════════

def _print_alert(r, execution_result: Optional[TradeResult] = None, no_sound: bool = False):
    if not no_sound:
        print(BELL, end="")
    bar = "=" * 74
    action_color = RED if r.trade_action == "SELL" else GREEN
    action_bg = BG_RED if r.trade_action == "SELL" else BG_GREEN

    badges = []
    if getattr(r, 'is_elite_v1', False):
        badges.append(f"{BG_YELLOW}{WHITE}{BOLD} ELITE V1 {RESET}")
    if getattr(r, 'is_elite_v2', False):
        badges.append(f"{BG_CYAN}{WHITE}{BOLD} ELITE V2 {RESET}")
    elite_str = " ".join(badges)
    if elite_str:
        elite_str = "  " + elite_str

    print(f"\n{action_bg}{WHITE}{BOLD}{bar}{RESET}")
    exec_tag = ""
    if execution_result:
        if execution_result.status == "FILLED":
            exec_tag = f"  {BG_GREEN}{BOLD}EXECUTÉ{RESET}"
        elif execution_result.status == "DRY_RUN":
            exec_tag = f"  {BG_YELLOW}{BOLD}DRY-RUN{RESET}"
        elif execution_result.status in ("FAILED", "SKIPPED"):
            exec_tag = f"  {BG_RED}{BOLD}{execution_result.status}{RESET}"
    print(f"{action_bg}{WHITE}{BOLD}  !!! NOUVEAU SIGNAL {r.trade_action} !!!  {_now_str()}  |  {_session()}{elite_str}{exec_tag}{RESET}")
    print(f"{action_bg}{WHITE}{BOLD}  {r.symbol}{RESET}")
    print(f"{action_bg}{WHITE}{BOLD}{bar}{RESET}")

    rg = r.asian_high - r.asian_low
    sweeps = []
    if r.asian_high_swept: sweeps.append("AH")
    if r.asian_low_swept: sweeps.append("AL")
    sweep_str = "+".join(sweeps) if sweeps else "-"
    print(f"\n  Range asiatique : AH={_fmt(r.asian_high)}  AL={_fmt(r.asian_low)}  "
          f"Range={_fmt(rg)}  Sweeps={sweep_str}")

    fib_str = r.fib_label if r.fib_label else r.fib_state if r.fib_state else "-"
    print(f"  Fib extension   : {fib_str}")

    print(f"\n  {BOLD}{action_color}[TRADE] {r.trade_action} {_fmt(r.trade_entry)}{RESET}")
    print(f"  {'Entry':18}: {BOLD}{_fmt(r.trade_entry)}{RESET}")
    print(f"  {'SL':18}: {RED}{_fmt(r.trade_sl)}{RESET}")
    if r.trade_tp1:  print(f"  {'TP1':18}: {GREEN}{_fmt(r.trade_tp1)}{RESET}")
    if r.trade_tp2:  print(f"  {'TP2':18}: {GREEN}{_fmt(r.trade_tp2)}{RESET}")
    if r.trade_tp3:  print(f"  {'TP3':18}: {GREEN}{_fmt(r.trade_tp3)}{RESET}")
    spread = _spread_str(r.symbol)
    if r.trade_rr1:  print(f"  {'RR1':18}: {BOLD}{r.trade_rr1:.2f}x{RESET}")
    if r.trade_rr2 and r.trade_rr2 != r.trade_rr1: print(f"  {'RR2':18}: {r.trade_rr2:.2f}x")
    if spread != "?": print(f"  {'Spread':18}: {spread} pts")

    if r.current_price and r.trade_entry and r.trade_entry != 0:
        diff = r.current_price - r.trade_entry if r.trade_action == "BUY" else r.trade_entry - r.current_price
        diff_pct = diff / r.trade_entry * 100
        status_color = GREEN if diff > 0 else RED if diff < 0 else YELLOW
        print(f"\n  {'Prix actuel':18}: {_fmt(r.current_price)}  {status_color}({diff_pct:+.2f}%){RESET}")

    # Résultat d'exécution
    if execution_result:
        if execution_result.status == "FILLED":
            print(f"\n  {BG_GREEN}{BOLD}  ✓ EXÉCUTÉ : {execution_result.decision.lots} lots "
                  f"@ {execution_result.ask:.5f}  Order #{execution_result.order_id}  {RESET}")
        elif execution_result.status == "DRY_RUN":
            print(f"\n  {BG_YELLOW}{BOLD}  🚧 DRY-RUN : {execution_result.decision.lots} lots "
                  f"@ {execution_result.ask:.5f}  (pas d'envoi réel){RESET}")
        elif execution_result.status == "SKIPPED":
            print(f"\n  {YELLOW}  ⏭ SKIPPED : {execution_result.message}{RESET}")
        elif execution_result.status == "FAILED":
            print(f"\n  {RED}  ✗ ÉCHEC : {execution_result.message}{RESET}")
            if execution_result.advice:
                print(f"  {YELLOW}  HINT : {execution_result.advice}{RESET}")

    expl_parts = []
    if r.asian_high_swept:
        expl_parts.append(f"AH sweep (liquidité acheteurs prise à {_fmt(r.asian_high)})")
    if r.asian_low_swept:
        expl_parts.append(f"AL sweep (liquidité vendeurs prise à {_fmt(r.asian_low)})")
    if r.fib_state and not r.fib_state.endswith("_DONE"):
        expl_parts.append(f"Prochaine cible fib {r.fib_state}")
    if r.trade_rr1:
        expl_parts.append(f"RR {r.trade_rr1:.2f}x")

    if expl_parts:
        print(f"\n  {BOLD}Analyse :{RESET}")
        for part in expl_parts:
            print(f"    - {part}")

    print(f"\n  Session : {_session()}  |  Paris : {_paris_hour()}")
    print(f"{action_bg}{WHITE}{BOLD}{bar}{RESET}\n")
    sys.stdout.flush()


def _log_alert(r, trade_key: str, execution_result: Optional[TradeResult] = None):
    try:
        entry = {
            "ts_utc": datetime.now(UTC).isoformat(),
            "symbol": r.symbol,
            "action": r.trade_action,
            "entry": r.trade_entry,
            "sl": r.trade_sl,
            "tp1": r.trade_tp1,
            "tp2": r.trade_tp2,
            "rr1": r.trade_rr1,
            "rr2": r.trade_rr2,
            "fib_state": r.fib_state,
            "asian_high": r.asian_high,
            "asian_low": r.asian_low,
            "current_price": r.current_price,
            "trade_key": trade_key,
        }
        with open(ALERT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        if execution_result:
            exec_entry = {
                **entry,
                "exec_status": execution_result.status,
                "exec_retcode": execution_result.retcode,
                "exec_retcode_label": execution_result.retcode_label,
                "exec_order_id": execution_result.order_id,
                "exec_deal_id": execution_result.deal_id,
                "exec_ask": execution_result.ask,
                "exec_bid": execution_result.bid,
                "exec_message": execution_result.message,
                "exec_advice": execution_result.advice,
                "lots": execution_result.decision.lots if execution_result.decision else None,
            }
            with open(EXEC_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(exec_entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="live_trader.py — Moniteur continu + EXÉCUTION automatique des signaux ICT"
    )
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                        help=f"Intervalle entre chaque scan en secondes (défaut: {DEFAULT_INTERVAL})")
    parser.add_argument("--symbols", type=str, default=None,
                        help="Liste de symboles séparés par des virgules (ex: EURUSD,GBPUSD,XAUUSD)")
    parser.add_argument("--no-sound", action="store_true",
                        help="Désactiver le beep sonore")
    parser.add_argument("--live", action="store_true",
                        help="ACTIVER l'envoi réel des ordres (SANS ce flag = DRY-RUN, rien n'est envoyé)")
    parser.add_argument("--lots", type=float, default=0.01,
                        help="Volume en lots par ordre (défaut: 0.01, ignoré si --risk-pct est utilisé)")
    parser.add_argument("--risk-pct", type=float, default=None,
                        help="%% du capital à risquer par trade (ex: 1.0 = 1%% du compte). "
                             "Remplace --lots par un calcul dynamique via MT5.")
    parser.add_argument("--rr-min", type=float, default=None,
                        help="Filtre RR minimum (ex: 1.0 pour ne trader que les RR ≥ 1)")
    args = parser.parse_args()

    interval = max(args.interval, 10)
    no_sound = args.no_sound
    is_live = args.live
    lots = args.lots
    risk_pct = args.risk_pct
    rr_min = args.rr_min

    use_risk_pct = risk_pct is not None and risk_pct > 0
    alerted: Set[str] = set()

    # ── Connexion MT5 ───────────────────────────────────────
    if not mt5.initialize():
        print(f"  {RED}[ERREUR] Connexion MT5 impossible.{RESET}")
        sys.exit(1)

    # ── Initialisation TradeExecutor ─────────────────────────
    executor = TradeExecutor(
        dry_run=not is_live,
        confirm_each=False,  # pas de confirmation interactive en continu
    )

    # ── Watchlist ───────────────────────────────────────────
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        for sym in symbols:
            info = mt5.symbol_info(sym)
            if info and not info.visible:
                mt5.symbol_select(sym, True)
    else:
        all_symbols = mt5.symbols_get()
        symbols = []
        for s in all_symbols:
            if not _is_tradeable(s.name):
                continue
            if not s.visible:
                mt5.symbol_select(s.name, True)
            symbols.append(s.name)
        symbols.sort()
        if len(symbols) > 80:
            print(f"  {YELLOW}[!] {len(symbols)} symboles négociables trouvés.{RESET}")

    mode_str = f"{BG_RED}{WHITE}{BOLD} LIVE {RESET}" if is_live else f"{BG_YELLOW}{WHITE}{BOLD} DRY-RUN {RESET}"

    # ── Afficher le mode risk% ou lots fixes (MT5 doit être initialisé) ──
    risk_display = f"{risk_pct}%"
    if use_risk_pct:
        acc = mt5.account_info()
        if acc:
            risk_display = f"{risk_pct}% du capital ({acc.equity:.2f} {acc.currency})"
        else:
            risk_display = f"{risk_pct}% (capital inconnu)"

    print()
    print(f"{BOLD}{CYAN}{'='*74}{RESET}")
    print(f"{BOLD}{CYAN}  Inelida Market Scanner — TRADER AUTOMATIQUE{RESET}")
    print(f"{BOLD}{CYAN}{'='*74}{RESET}")
    print(f"\n  Mode            : {mode_str}")
    print(f"  Heure           : {_now_str()}")
    print(f"  Paris           : {_paris_hour()}")
    print(f"  Session         : {_session()}")
    print(f"  Intervalle scan : {interval}s")
    if use_risk_pct:
        print(f"  Risk/trade      : {CYAN}{risk_display}{RESET}")
    else:
        print(f"  Lots            : {lots}")
    if rr_min is not None:
        print(f"  RR minimum      : {rr_min}x")
    print(f"  Symboles        : {len(symbols)}")
    print(f"  Log alertes     : {ALERT_LOG}")
    print(f"  Log exécutions  : {EXEC_LOG}")
    print(f"\n  {YELLOW}Surveillance en cours... (Ctrl+C pour quitter){RESET}")
    print()

    session_date = datetime.now(UTC).strftime("%Y-%m-%d")
    check_num = 0
    n_executed = 0
    n_dry_run = 0

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    try:
        while True:
            check_num += 1
            cycle_start = time.time()
            now_dt = datetime.now(UTC)
            today_str = now_dt.strftime("%Y-%m-%d")

            if today_str != session_date:
                print(f"\n  {CYAN}[NOUVEAU JOUR] {today_str} — reset des alertes{RESET}")
                session_date = today_str
                alerted.clear()

            n_detected = 0
            n_elite_v1 = 0
            n_elite_v2 = 0

            for sym in symbols:
                try:
                    r = detect_asian_range_for_symbol(sym, "H1", session_date=today_str)
                except Exception:
                    continue

                if r is None:
                    continue

                if r.trade_action and r.trade_action != "-":
                    n_detected += 1
                    is_v1 = getattr(r, 'is_elite_v1', False)
                    is_v2 = getattr(r, 'is_elite', False)
                    if is_v1: n_elite_v1 += 1
                    if is_v2: n_elite_v2 += 1

                if not _is_valid_trade(r):
                    continue

                key = _trade_key(r)
                if not key or key in alerted:
                    continue

                # ── Calcul du lot (fixe ou risk%) ──────────────
                signal_lots = lots
                if use_risk_pct:
                    calculated = _calculate_lots_for_risk(
                        r.symbol, r.trade_entry, r.trade_sl,
                        r.trade_action, risk_pct,
                    )
                    if calculated is not None and calculated > 0:
                        signal_lots = calculated
                    else:
                        print(f"\n  {YELLOW}[WARN] Calcul risk% impossible pour {r.symbol}, "
                              f"fallback {lots} lots{RESET}")

                # ── NOUVEAU SIGNAL → convertir en TradeDecision ──
                decisions = asian_to_decisions(
                    [r], lots=signal_lots, rr_min=rr_min,
                )
                if not decisions:
                    continue

                alerted.add(key)
                decision = decisions[0]

                # ── Exécution ────────────────────────────────────
                result = executor.execute(decision)

                # ── Stats ────────────────────────────────────────
                if result.status == "FILLED":
                    n_executed += 1
                elif result.status == "DRY_RUN":
                    n_dry_run += 1

                # ── Affichage + log ──────────────────────────────
                _print_alert(r, execution_result=result, no_sound=no_sound)
                _log_alert(r, key, execution_result=result)

            n_active = len(alerted)
            _, elite_v2_status = _in_window(ELITE)
            mode_tag = "LIVE" if is_live else "DRY"
            risk_tag = f"{risk_pct}%" if use_risk_pct else f"{lots} lots"
            print(f"  {_now_str()} | {_session()} | Paris {_paris_hour()} | "
                  f"Check #{check_num} | {mode_tag} | "
                  f"Risk: {risk_tag} | "
                  f"Setups: {n_detected} | "
                  f"V1: {n_elite_v1} | V2: {n_elite_v2} | "
                  f"Fenetre: {elite_v2_status} | "
                  f"Exec: {n_executed} | Dry: {n_dry_run} | "
                  f"Signaux: {n_active} | "
                  f"{DIM}Ctrl+C pour quitter{RESET}  ", end="\r")
            sys.stdout.flush()

            elapsed = time.time() - cycle_start
            sleep_time = max(1, interval - elapsed)
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print(f"\n\n  {YELLOW}[STOP] Arrêté par l'utilisateur.{RESET}")

    finally:
        n_total = n_executed + n_dry_run
        print(f"\n  {GREEN}[OK] Session terminée.{RESET}")
        print(f"  {GREEN}  Exécutés : {n_executed} trades{RESET}" if is_live
              else f"  {YELLOW}  DRY-RUN  : {n_dry_run} trades simulés{RESET}")
        print(f"  {GREEN}  Alertes  : {len(alerted)}{RESET}")
        print(f"  {GREEN}  Logs     : {ALERT_LOG}{RESET}")
        if is_live:
            print(f"  {GREEN}  Exec logs: {EXEC_LOG}{RESET}")
        mt5.shutdown()


if __name__ == "__main__":
    main()
