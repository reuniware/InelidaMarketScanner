"""
live_alerts.py — Moniteur continu Inelida Market Scanner
=========================================================
Surveille TOUS les actifs de la watchlist en boucle, détecte les signaux
d'entrée ICT (sweep asiatique + fib extension) et ALERTE en temps réel
avec le plan de trade complet : direction, entry, SL, TP, RR.

Utilise le générateur de trades intégré à detect_asian_range_for_symbol.

Usage :
    python live_alerts.py              # boucle infinie (Ctrl+C pour quitter)
    python live_alerts.py --interval 15  # toutes les 15 secondes
"""

import os
import sys
import time
import json
import argparse
from datetime import datetime, timezone
from typing import Dict, Set, Optional, List, Tuple

import MetaTrader5 as mt5

# ─── Chemin projet ──────────────────────────────────────────────────────────
PROJECT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT)

from src.sweep_detector import detect_asian_range_for_symbol
from src.config import ELITE

# ─── Constantes ─────────────────────────────────────────────────────────────
UTC = timezone.utc
DEFAULT_INTERVAL = 30          # secondes entre chaque scan
ALERT_DIR = os.path.join(PROJECT, "logs")
os.makedirs(ALERT_DIR, exist_ok=True)
ALERT_LOG = os.path.join(ALERT_DIR, "live_alerts.log")
MAX_SPREAD_PCT = 0.10          # spread max en % du prix (XPDUSD=0.7%, XAUUSD=0.012%, UK100=0.006%)

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
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _is_tradeable(name: str) -> bool:
    """Filtre les symboles negociables : forex, metaux, crypto, indices, commodites.
    Exclut les actions individuelles (AAPL, MSFT, TSLA, etc.)."""
    n = name.upper()

    # Forex 6 lettres (EURUSD, GBPJPY...)
    if len(n) == 6 and n.isalpha():
        return True

    # Paires exotiques avec pays emergents (USDMXN, USDZAR, USDTRY...)
    if n.endswith(("MXN", "ZAR", "TRY", "PLN", "HUF", "CZK",
                    "NOK", "SEK", "SGD", "HKD", "CNH", "ILS")) and len(n) == 6:
        return True

    # Metaux (XAUUSD, XAGUSD, XPDUSD, XPTUSD...)
    if any(n.startswith(p) for p in ["XAU", "XAG", "XPD", "XPT", "XCU"]):
        return True

    # Crypto : tout symbole de 5-7 lettres finissant par USD/EUR qui n'est pas du forex
    if len(n) >= 5 and len(n) <= 7 and n.endswith(("USD", "EUR")) \
       and not (len(n) == 6 and n.isalpha()):
        return True

    # Commodites et indices suffixés (.cash, .c)
    if n.endswith((".CASH", ".C")):
        return True

    # Indices sans suffixe
    if n in ("DXY", "US30", "US500", "NAS100", "SPX500", "US100", "US2000"):
        return True

    return False


def _fmt(p: Optional[float]) -> str:
    """Format adaptatif selon la magnitude du prix."""
    if p is None or p == 0:
        return "--"
    p_abs = abs(p)
    if p_abs >= 1000:
        return f"{p:.2f}"
    if p_abs >= 10:
        return f"{p:.4f}"
    return f"{p:.5f}"


def _now_str() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S") + " UTC"


def _paris_hour() -> str:
    n = datetime.now(UTC)
    h = (n.hour + 2) % 24
    return f"{h:02d}:{n.minute:02d}"


def _session() -> str:
    h = datetime.now(UTC).hour
    if 0 <= h < 8:
        return "ASIAN"
    if 8 <= h < 13:
        return "LONDON"
    if 13 <= h < 16:
        return "NY OPEN"
    if 16 <= h < 22:
        return "NY"
    return "ASIAN PRE"


def _trade_key(r) -> str:
    """Cle unique pour un trade: symbole + direction + entry arrondi."""
    if not r.trade_action or r.trade_action == "-" or r.trade_entry is None:
        return ""
    return f"{r.symbol}_{r.trade_action}_{r.trade_entry:.5f}"


def _spread_too_high(symbol: str) -> bool:
    """Verifie si le spread (en % du prix) est trop large pour etre tradeable.
    Retourne True si le spread depasse MAX_SPREAD_PCT.
    Exemple: XPDUSD=0.7% > 0.10% -> rejete. XAUUSD=0.012% -> accepte."""
    try:
        tick = mt5.symbol_info_tick(symbol)
        if tick is None or tick.bid == 0:
            return True
        spread_pct = (tick.ask - tick.bid) / tick.bid * 100
        return spread_pct > MAX_SPREAD_PCT
    except Exception:
        return True

def _in_window(config) -> Tuple[bool, str]:
    """Verifie si l'heure actuelle est dans la fenetre ELITE (v2).
    Retourne (True/False, message statut)."""
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
    """Un trade est valide si action, entry, SL, TP1 et RR > 0, spread acceptable.
    NB: le filtre ELITE est informatif (badge + compteurs), il NE bloque JAMAIS."""
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
    # Note: le filtre ELITE est informatif uniquement (badge + compteurs),
    # il ne bloque JAMAIS une alerte. Tous les trades valides s'affichent.
    return True

def _spread_str(symbol: str) -> str:
    """Retourne le spread en % sous forme de chaine lisible."""
    try:
        tick = mt5.symbol_info_tick(symbol)
        if tick is None or tick.bid == 0:
            return "?"
        spread_pct = (tick.ask - tick.bid) / tick.bid * 100
        return f"{spread_pct:.3f}%"
    except Exception:
        return "?"


def _log_alert(r, trade_key: str):
    """Ecrit une alerte dans le fichier log JSON."""
    try:
        with open(ALERT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts_utc": datetime.now(UTC).isoformat(),
                "symbol": r.symbol,
                "action": r.trade_action,
                "entry": r.trade_entry,
                "sl": r.trade_sl,
                "tp1": r.trade_tp1,
                "tp2": r.trade_tp2,
                "tp3": r.trade_tp3,
                "rr1": r.trade_rr1,
                "rr2": r.trade_rr2,
                "fib_state": r.fib_state,
                "asian_high": r.asian_high,
                "asian_low": r.asian_low,
                "current_price": r.current_price,
                "trade_key": trade_key,
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _print_alert(r, no_sound: bool = False):
    """Imprime une alerte visuelle bien formatée avec beep."""
    if not no_sound:
        print(BELL, end="")
    bar = "=" * 74
    action_color = RED if r.trade_action == "SELL" else GREEN
    action_bg = BG_RED if r.trade_action == "SELL" else BG_GREEN

    # Badges ELITE V1 / V2 si applicables
    badges = []
    if getattr(r, 'is_elite_v1', False):
        badges.append(f"{BG_YELLOW}{WHITE}{BOLD} ELITE V1 {RESET}")
    if getattr(r, 'is_elite_v2', False):
        badges.append(f"{BG_CYAN}{WHITE}{BOLD} ELITE V2 {RESET}")
    elite_str = " ".join(badges)
    if elite_str:
        elite_str = "  " + elite_str

    # ── En-tête ─────────────────────────────────────────────
    print(f"\n{action_bg}{WHITE}{BOLD}{bar}{RESET}")
    print(f"{action_bg}{WHITE}{BOLD}  !!! NOUVEAU SIGNAL {r.trade_action} !!!  {_now_str()}  |  {_session()}{elite_str}{RESET}")
    print(f"{action_bg}{WHITE}{BOLD}  {r.symbol}{RESET}")
    print(f"{action_bg}{WHITE}{BOLD}{bar}{RESET}")

    # ── Infos range asiatique ───────────────────────────────
    rg = r.asian_high - r.asian_low
    sweeps = []
    if r.asian_high_swept: sweeps.append("AH")
    if r.asian_low_swept: sweeps.append("AL")
    sweep_str = "+".join(sweeps) if sweeps else "-"
    print(f"\n  Range asiatique : AH={_fmt(r.asian_high)}  AL={_fmt(r.asian_low)}  "
          f"Range={_fmt(rg)}  Sweeps={sweep_str}")

    # ── Fib ─────────────────────────────────────────────────
    fib_str = r.fib_label if r.fib_label else r.fib_state if r.fib_state else "-"
    print(f"  Fib extension   : {fib_str}")

    # ── Plan de trade ───────────────────────────────────────
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

    # ── Position actuelle ───────────────────────────────────
    if r.current_price and r.trade_entry and r.trade_entry != 0:
        diff = r.current_price - r.trade_entry if r.trade_action == "BUY" else r.trade_entry - r.current_price
        diff_pct = diff / r.trade_entry * 100
        status_color = GREEN if diff > 0 else RED if diff < 0 else YELLOW
        print(f"\n  {'Prix actuel':18}: {_fmt(r.current_price)}  {status_color}({diff_pct:+.2f}%){RESET}")

    # ── Explication ─────────────────────────────────────────
    expl_parts = []
    if r.asian_high_swept:
        expl_parts.append(f"AH sweep (liquidite acheteurs prise a {_fmt(r.asian_high)})")
    if r.asian_low_swept:
        expl_parts.append(f"AL sweep (liquidite vendeurs prise a {_fmt(r.asian_low)})")
    if r.fib_state and not r.fib_state.endswith("_DONE"):
        expl_parts.append(f"Prochaine cible fib {r.fib_state}")
    if r.trade_rr1:
        expl_parts.append(f"RR {r.trade_rr1:.2f}x")

    if expl_parts:
        print(f"\n  {BOLD}Analyse :{RESET}")
        for part in expl_parts:
            print(f"    - {part}")

    # ── Session ─────────────────────────────────────────────
    print(f"\n  Session : {_session()}  |  Paris : {_paris_hour()}")
    print(f"{action_bg}{WHITE}{BOLD}{bar}{RESET}\n")
    sys.stdout.flush()


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="live_alerts.py — Moniteur continu de signaux ICT avec SL/TP"
    )
    parser.add_argument(
        "--interval", type=int, default=DEFAULT_INTERVAL,
        help=f"Intervalle entre chaque scan en secondes (defaut: {DEFAULT_INTERVAL})"
    )
    parser.add_argument(
        "--symbols", type=str, default=None,
        help="Liste de symboles separes par des virgules (ex: EURUSD,GBPUSD,XAUUSD)"
    )
    parser.add_argument(
        "--no-sound", action="store_true",
        help="Desactiver le beep sonore"
    )
    args = parser.parse_args()

    interval = max(args.interval, 10)  # minimum 10s
    no_sound = args.no_sound
    alerted: Set[str] = set()          # trades deja alertes (evite les doublons)

    # ── Connexion MT5 ───────────────────────────────────────
    if not mt5.initialize():
        print(f"  {RED}[ERREUR] Connexion MT5 impossible.{RESET}")
        sys.exit(1)

    # ── Watchlist dynamique depuis MT5 ──────────────────────
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
            print(f"  {YELLOW}[!] {len(symbols)} symboles negociables trouves. Utilise --symbols pour filtrer.{RESET}")
            print(f"  {YELLOW}    Premier scan lent (~{len(symbols)}s). Les suivants seront plus rapides.{RESET}")

    print()
    print(f"{BOLD}{CYAN}{'='*74}{RESET}")
    print(f"{BOLD}{CYAN}  Inelida Market Scanner — ALERTES EN DIRECT{RESET}")
    print(f"{BOLD}{CYAN}{'='*74}{RESET}")
    print(f"\n  Heure           : {_now_str()}")
    print(f"  Paris           : {_paris_hour()}")
    print(f"  Session         : {_session()}")
    print(f"  Intervalle scan : {interval}s")
    print(f"  Symboles        : {len(symbols)}")
    for s in symbols:
        print(f"    - {s}")
    print(f"  Log alertes     : {ALERT_LOG}")
    print(f"\n  {YELLOW}Surveillance en cours... (Ctrl+C pour quitter){RESET}")
    print()

    session_date = datetime.now(UTC).strftime("%Y-%m-%d")
    check_num = 0

    # Forcer UTF-8 sur la console Windows (evite les UnicodeEncodeError)
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

            # ── Nouveau jour ? ───────────────────────────────
            if today_str != session_date:
                print(f"\n  {CYAN}[NOUVEAU JOUR] {today_str} — reset des alertes{RESET}")
                session_date = today_str
                alerted.clear()

            # ── Scan de tous les symboles ────────────────────
            n_detected = 0
            n_elite_v1 = 0
            n_elite_v2 = 0
            for sym in symbols:
                try:
                    r = detect_asian_range_for_symbol(
                        sym, "H1", session_date=today_str
                    )
                except Exception:
                    continue

                if r is None:
                    continue

                # Compteurs pour la ligne de statut
                if r.trade_action and r.trade_action != "-":
                    n_detected += 1
                    # Les flags ELITE V1 et V2 sont pre-calcules dans sweep_detector.py
                    is_v1 = getattr(r, 'is_elite_v1', False)
                    is_v2 = getattr(r, 'is_elite', False)
                    if is_v1:
                        n_elite_v1 += 1
                    if is_v2:
                        n_elite_v2 += 1

                # ── Trade valide ? (inclut filtre ELITE) ─────
                if not _is_valid_trade(r):
                    continue

                key = _trade_key(r)
                if not key or key in alerted:
                    continue

                # ── NOUVEAU TRADE ! ──────────────────────────
                alerted.add(key)
                _print_alert(r, no_sound)
                _log_alert(r, key)

            # ── Ligne de statut ──────────────────────────────
            n_active = len(alerted)
            _, elite_v2_status = _in_window(ELITE)
            print(f"  {_now_str()} | {_session()} | Paris {_paris_hour()} | "
                  f"Check #{check_num} | Setups: {n_detected} | "
                  f"V1: {n_elite_v1} | V2: {n_elite_v2} | "
                  f"Fenetre: {elite_v2_status} | "
                  f"Signaux: {n_active} | "
                  f"{DIM}Ctrl+C pour quitter{RESET}  ", end="\r")
            sys.stdout.flush()

            elapsed = time.time() - cycle_start
            sleep_time = max(1, interval - elapsed)
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print(f"\n\n  {YELLOW}[STOP] Arrete par l'utilisateur.{RESET}")

    finally:
        n = len(alerted)
        print(f"\n  {GREEN}[OK] {n} alerte(s) detectee(s) pendant la session.{RESET}")
        print(f"  {GREEN}[OK] Log : {ALERT_LOG}{RESET}")
        mt5.shutdown()


if __name__ == "__main__":
    main()
