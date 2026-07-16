"""
monitor_eurusd_breakout.py — Surveille EURUSD en continu et alerte
quand le prix casse les niveaux de breakout.

MODE DYNAMIQUE (defaut) : recalcule Tenkan H1 et Kijun H1 a chaque poll
→ les niveaux suivent le prix, pas de niveaux stales.

MODE STATIQUE (--static) : utilise les niveaux fournis manuellement.

Niveaux surveilles (H1 close):
    - RESISTANCE: Tenkan H1 (9-periodes, dynamique) ou manuelle (--res)
    - SUPPORT:    Kijun H1  (26-periodes, dynamique) ou manuelle (--sup)

Usage:
    python monitor_eurusd_breakout.py                    # dynamique
    python monitor_eurusd_breakout.py --static           # statique (1.14247/1.14228)
    python monitor_eurusd_breakout.py --res 1.14260 --sup 1.14233  # manuel

Alerte par:
    1. Console (couleur + bell)
    2. Discord (embed via webhook dans .env)

Ctrl+C pour quitter.
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from typing import Optional, Tuple

import MetaTrader5 as mt5

# ─── Configuration ──────────────────────────────────────────────────────────
SYMBOL = "EURUSD"
POLL_SEC = 15          # Intervalle entre chaque tick
KEEP_RUNNING = True    # Continuer apres alerte pour suivre les whipsaws

# Niveaux par defaut (fallback si MT5 indisponible)
DEFAULT_RESISTANCE = 1.14247
DEFAULT_SUPPORT    = 1.14228

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "eurusd_breakout_alerts.jsonl")

UTC = timezone.utc

# ─── ANSI ───────────────────────────────────────────────────────────────────
_IS_TTY = sys.stdout.isatty()

def _c(code): return code if _IS_TTY else ""
BOLD = _c("\033[1m"); RED = _c("\033[31m"); GREEN = _c("\033[32m")
YELLOW = _c("\033[33m"); CYAN = _c("\033[36m"); MAGENTA = _c("\033[35m")
BG_RED = _c("\033[41m"); BG_GREEN = _c("\033[42m"); WHITE = _c("\033[97m")
RESET = _c("\033[0m"); BELL = "\a"
DIM = _c("\033[2m")


def _fmt(v):
    if v is None:
        return "--"
    if v >= 1000:
        return f"{v:.2f}"
    if v >= 10:
        return f"{v:.4f}"
    return f"{v:.5f}"


def _now():
    return datetime.now(UTC).strftime("%H:%M:%S UTC")


def load_webhook():
    """Charge l'URL du webhook Discord depuis .env."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return os.environ.get("DISCORD_WEBHOOK_URL", "")

    with open(env_path, "rb") as f:
        raw = f.read()

    if raw[:2] == b'\xff\xfe' or (len(raw) >= 6 and raw[1:6:2] == b'\x00\x00\x00'):
        text = raw.decode("utf-16-le", errors="ignore")
    else:
        text = raw.decode("utf-8", errors="ignore")

    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("DISCORD_WEBHOOK_URL="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("DISCORD_WEBHOOK_URL", "")


# ═══ Ichimoku dynamique ═════════════════════════════════════════════════════

def fetch_tenkan_h1(symbol: str) -> Optional[float]:
    """Tenkan H1 = (highest high + lowest low) / 2 sur les 9 dernieres bougies H1."""
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 20)
    if rates is None or len(rates) < 9:
        return None
    highs = [float(r[2]) for r in rates[-9:]]
    lows = [float(r[3]) for r in rates[-9:]]
    return (max(highs) + min(lows)) / 2.0


def fetch_kijun_h1(symbol: str) -> Optional[float]:
    """Kijun H1 = (highest high + lowest low) / 2 sur les 26 dernieres bougies H1."""
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 40)
    if rates is None or len(rates) < 26:
        return None
    highs = [float(r[2]) for r in rates[-26:]]
    lows = [float(r[3]) for r in rates[-26:]]
    return (max(highs) + min(lows)) / 2.0


def fetch_kijun_h4(symbol: str) -> Optional[float]:
    """Kijun H4 pour le calcul de SL."""
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H4, 0, 40)
    if rates is None or len(rates) < 26:
        return None
    highs = [float(r[2]) for r in rates[-26:]]
    lows = [float(r[3]) for r in rates[-26:]]
    return (max(highs) + min(lows)) / 2.0


def refresh_dynamic_levels(symbol: str) -> Tuple[float, float]:
    """Recalcule Tenkan H1 et Kijun H1 dynamiquement.
    Returns (resistance, support).
    """
    res = fetch_tenkan_h1(symbol)
    sup = fetch_kijun_h1(symbol)
    if res is None:
        res = DEFAULT_RESISTANCE
    if sup is None:
        sup = DEFAULT_SUPPORT
    return res, sup


# ═══ Detection ═══════════════════════════════════════════════════════════════

def get_h1_candle(symbol) -> Optional[Tuple[float, float, float, float, float]]:
    """Retourne la bougie H1 en cours: (open, high, low, close, close_prev)."""
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 2)
    if rates is None or len(rates) < 2:
        return None
    current = rates[-1]
    prev = rates[-2]
    return (
        float(current[1]),
        float(current[2]),
        float(current[3]),
        float(current[4]),
        float(prev[4]),
    )


def check_breakout(close: float, resistance: float, support: float) -> Optional[str]:
    """Detecte breakout H1 vs niveaux fournis."""
    if close > resistance:
        return "BULL"
    elif close < support:
        return "BEAR"
    return None


def _trade_params(breakout_type: str, price: float, resistance: float, support: float,
                  kj4: Optional[float] = None, kj1: Optional[float] = None) -> Tuple[float, float, float, float]:
    """Calcule SL, TP, dist, RR avec niveaux structurels."""
    if breakout_type == "BULL":
        sl = kj4 if kj4 and kj4 < price else (kj1 if kj1 and kj1 < price else price - 0.00050)
        tp = price + (price - sl) * 2.0  # RR 2:1 depuis l'entree
        dist = round((price - resistance) * 10000, 1)
    else:
        sl = kj1 if kj1 and kj1 > price else price + 0.00050
        tp = price - (sl - price) * 2.0  # RR 2:1 depuis l'entree
        dist = round((price - support) * 10000, 1)
    rr = abs((tp - price) / (price - sl)) if abs(price - sl) > 0.00001 else 0
    return sl, tp, dist, rr


# ═══ Alertes ═════════════════════════════════════════════════════════════════

def send_discord_alert(webhook_url, breakout_type, price, dist_pips, close_prev,
                       sl_level, tp_level, rr, res_level, sup_level):
    """Envoie un embed Discord quand un breakout est detecte."""
    now_utc = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    if breakout_type == "BULL":
        title = "EURUSD — BREAKOUT HAUSSIER !"
        color = 0x2ECC71
        description = (
            f"**Le prix a casse la Tenkan H1 a {_fmt(res_level)}**\n\n"
            f"Close H1 : **{_fmt(price)}** (+{dist_pips:.1f} pips)\n"
            f"Close H1 precedente : **{_fmt(close_prev)}**\n"
            f"Kijun H1 (support) : **{_fmt(sup_level)}**\n\n"
            f"SL: **{_fmt(sl_level)}** | TP: **{_fmt(tp_level)}** | RR: **{rr:.1f}x**\n\n"
            f"Niveaux DYNAMIQUES — mis a jour chaque poll (15s)"
        )
    else:
        title = "EURUSD — BREAKDOWN BAISSIER !"
        color = 0xE74C3C
        description = (
            f"**Le prix a casse la Kijun H1 a {_fmt(sup_level)}**\n\n"
            f"Close H1 : **{_fmt(price)}** ({dist_pips:+.1f} pips)\n"
            f"Close H1 precedente : **{_fmt(close_prev)}**\n"
            f"Tenkan H1 (resistance) : **{_fmt(res_level)}**\n\n"
            f"SL: **{_fmt(sl_level)}** | TP: **{_fmt(tp_level)}** | RR: **{rr:.1f}x**\n\n"
            f"Niveaux DYNAMIQUES — mis a jour chaque poll (15s)"
        )

    embed = {
        "title": title,
        "description": description,
        "color": color,
        "footer": {"text": f"Inelida Breakout Monitor • {now_utc}"},
    }

    payload = {"embeds": [embed]}
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "InelidaBreakoutMonitor/1.0",
        },
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status == 204
    except Exception as e:
        print(f"  {RED}[Discord] Erreur: {e}{RESET}")
        return False


def console_alert(breakout_type, price, dist_pips, close_prev,
                  sl_level, tp_level, rr, res_level, sup_level):
    """Alerte visuelle + sonore dans la console."""
    print(BELL)
    bar = "=" * 60

    if breakout_type == "BULL":
        bg = BG_GREEN
        emoji = "BULL"
        level_name = f"Tenkan H1 ({_fmt(res_level)})"
    else:
        bg = BG_RED
        emoji = "BEAR"
        level_name = f"Kijun H1 ({_fmt(sup_level)})"

    print(f"\n{bg}{WHITE}{BOLD}{bar}{RESET}")
    print(f"{bg}{WHITE}{BOLD}  !!! BREAKOUT {emoji} EURUSD !!!  {_now()}{RESET}")
    print(f"{bg}{WHITE}{BOLD}{bar}{RESET}")
    print(f"\n  {BOLD}EURUSD H1 — {emoji} BREAKOUT (DYNAMIQUE){RESET}")
    print(f"  Close H1 actuelle     : {BOLD}{_fmt(price)}{RESET}")
    print(f"  Close H1 precedente   : {_fmt(close_prev)}")
    print(f"  Niveau casse          : {level_name}")
    print(f"  Distance du breakout  : {BOLD}{dist_pips:+.1f} pips{RESET}")
    print(f"  Tenkan H1 (res)       : {_fmt(res_level)}")
    print(f"  Kijun H1  (sup)       : {_fmt(sup_level)}")
    print(f"  SL                    : {_fmt(sl_level)}")
    print(f"  TP                    : {_fmt(tp_level)}")
    print(f"  RR                    : {BOLD}{rr:.1f}x{RESET}")
    print(f"{bg}{WHITE}{BOLD}{bar}{RESET}\n")
    sys.stdout.flush()


# ═══ Main ════════════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Monitor breakout EURUSD H1")
    parser.add_argument("--static", action="store_true",
                        help="Mode statique: utilise les niveaux par defaut sans recalcule")
    parser.add_argument("--res", type=float, default=None,
                        help="Resistance manuelle (override)")
    parser.add_argument("--sup", type=float, default=None,
                        help="Support manuel (override)")
    args = parser.parse_args()

    dynamic_mode = not args.static

    webhook_url = load_webhook()
    has_discord = bool(webhook_url)
    if has_discord:
        print(f"  {GREEN}Discord: webhook trouve ({len(webhook_url)} chars){RESET}")
    else:
        print(f"  {YELLOW}Discord: pas de webhook (alerte console seulement){RESET}")

    # ── Connexion MT5 ──────────────────────────────────────────────────
    if not mt5.initialize():
        print(f"{RED}[ERREUR] Connexion MT5 impossible.{RESET}")
        return 1

    mt5.symbol_select(SYMBOL, True)
    tick = mt5.symbol_info_tick(SYMBOL)
    if not tick:
        print(f"{RED}[ERREUR] {SYMBOL} introuvable.{RESET}")
        mt5.shutdown()
        return 1

    price = float(tick.bid)
    spread = (tick.ask - tick.bid) * 10000 if tick.ask else 0

    # ── Niveaux initiaux (toujours frais, meme en statique) ─────────
    res_init, sup_init = refresh_dynamic_levels(SYMBOL)
    if dynamic_mode or args.static:
        # Toujours partir de niveaux frais
        resistance = res_init
        support = sup_init
    if args.res is not None:
        resistance = args.res
        dynamic_mode = False
    if args.sup is not None:
        support = args.sup
        dynamic_mode = False
    if args.res is not None and args.sup is not None:
        dynamic_mode = False

    # Kijun H4 pour SL structurel
    kj4_init = fetch_kijun_h4(SYMBOL)
    kj1_init = sup_init  # Kijun H1 = support initial

    # ── H1 en cours ───────────────────────────────────────────────────
    candle = get_h1_candle(SYMBOL)
    if candle is None:
        print(f"{RED}[ERREUR] Impossible de recuperer les bougies H1.{RESET}")
        mt5.shutdown()
        return 1

    o, h, l, c, cp = candle
    dist_up = round((resistance - c) * 10000, 1)
    dist_dn = round((c - support) * 10000, 1)

    mode_str = f"{CYAN}DYNAMIQUE{RESET}" if dynamic_mode else f"{YELLOW}STATIQUE{RESET}"
    print(f"\n{BOLD}{CYAN}{'='*60}{RESET}")
    print(f"{BOLD}{CYAN}  Monitor Breakout — {SYMBOL} H1  [{mode_str}{BOLD}{CYAN}]{RESET}")
    print(f"{BOLD}{CYAN}  {'='*60}{RESET}")
    print(f"  Bid/Ask        : {_fmt(price)} / {_fmt(tick.ask) if tick.ask else '--'} (spread {spread:.1f}p)")
    print(f"  H1 en cours    : O={_fmt(o)} H={_fmt(h)} L={_fmt(l)} C={_fmt(c)}")
    print(f"  H1 precedente  : C={_fmt(cp)}")
    print(f"  {RED}Resistance{RESET}     : {BOLD}{_fmt(resistance)}{RESET} ({dist_up:+.1f}p) {'[Tenkan H1]' if dynamic_mode else '[fixe]'}")
    print(f"  {GREEN}Support{RESET}        : {BOLD}{_fmt(support)}{RESET} ({dist_dn:+.1f}p) {'[Kijun H1]' if dynamic_mode else '[fixe]'}")
    print(f"  Poll           : toutes les {POLL_SEC}s")
    if dynamic_mode:
        print(f"  Recalcul       : Tenkan/Kijun H1 recalcules a chaque poll")
    if has_discord:
        print(f"  Discord        : {GREEN}active{RESET}")
    print(f"{BOLD}{CYAN}{'='*60}{RESET}\n")

    # ── Verifier breakout initial ──────────────────────────────────────
    last_breakout = check_breakout(c, resistance, support)
    if last_breakout:
        sl, tp, dist, rr = _trade_params(last_breakout, c, resistance, support, kj4_init, kj1_init)
        console_alert(last_breakout, c, dist, cp, sl, tp, rr, resistance, support)
        log_entry = json.dumps({
            "ts_utc": datetime.now(UTC).isoformat(),
            "symbol": SYMBOL,
            "breakout": last_breakout,
            "price": c,
            "close_prev": cp,
            "dist_pips": round(dist, 1),
            "resistance": resistance,
            "support": support,
            "mode": "dynamic" if dynamic_mode else "static",
        }, ensure_ascii=False)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry + "\n")
        if has_discord:
            ok = send_discord_alert(webhook_url, last_breakout, c, dist, cp, sl, tp, rr,
                                    resistance, support)
            status = f"{GREEN}OK{RESET}" if ok else f"{RED}ECHEC{RESET}"
            print(f"  Discord: {status}")

    poll_count = 0

    try:
        while True:
            poll_count += 1
            time.sleep(POLL_SEC)

            # ── Recalcul dynamique des niveaux ─────────────────────────
            if dynamic_mode:
                new_res, new_sup = refresh_dynamic_levels(SYMBOL)
                res_changed = (abs(new_res - resistance) > 0.00001 or
                               abs(new_sup - support) > 0.00001)
                if res_changed:
                    print(f"\n  [{_now()}] {MAGENTA}Niveaux mis a jour:{RESET} "
                          f"Res {_fmt(resistance)}→{_fmt(new_res)} "
                          f"Sup {_fmt(support)}→{_fmt(new_sup)}")
                resistance = new_res
                support = new_sup

            # ── Prix live ───────────────────────────────────────────────
            tick = mt5.symbol_info_tick(SYMBOL)
            if not tick:
                print(f"  {RED}[{_now()}] Tick indisponible{RESET}")
                continue
            price = float(tick.bid)

            # ── H1 en cours ─────────────────────────────────────────────
            candle = get_h1_candle(SYMBOL)
            if candle is None:
                continue
            o, h, l, c, cp = candle

            breakout = check_breakout(c, resistance, support)

            # ── Log periodique ──────────────────────────────────────────
            if poll_count % 4 == 0:
                dist_up = (resistance - c) * 10000
                dist_dn = (c - support) * 10000
                bar_len = max(1, min(15, int(abs(dist_up)) if abs(dist_up) < abs(dist_dn) else int(abs(dist_dn))))
                bar = "|" * bar_len
                bias = "▲" if c > (support + resistance) / 2 else "▼"
                mode_tag = "DYN" if dynamic_mode else "STAT"
                print(f"  [{_now()}] {_fmt(c)} | Res:{_fmt(resistance)} "
                      f"({dist_up:+.1f}p) | Sup:{_fmt(support)} ({dist_dn:+.1f}p) "
                      f"{bias} {DIM}[{mode_tag}]{RESET} {DIM}{bar}{RESET}",
                      end="\r")
                sys.stdout.flush()

            # ── Detection breakout ──────────────────────────────────────
            if breakout and breakout != last_breakout:
                kj4 = fetch_kijun_h4(SYMBOL)
                kj1 = fetch_kijun_h1(SYMBOL)
                sl, tp, dist, rr = _trade_params(breakout, c, resistance, support, kj4, kj1)
                console_alert(breakout, c, dist, cp, sl, tp, rr, resistance, support)
                last_breakout = breakout

                log_entry = json.dumps({
                    "ts_utc": datetime.now(UTC).isoformat(),
                    "symbol": SYMBOL,
                    "breakout": breakout,
                    "price": c,
                    "close_prev": cp,
                    "dist_pips": dist,
                    "resistance": resistance,
                    "support": support,
                    "mode": "dynamic" if dynamic_mode else "static",
                }, ensure_ascii=False)
                with open(LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(log_entry + "\n")

                if has_discord:
                    ok = send_discord_alert(webhook_url, breakout, c, dist, cp, sl, tp, rr,
                                            resistance, support)
                    status = f"{GREEN}OK{RESET}" if ok else f"{RED}ECHEC{RESET}"
                    print(f"  Discord: {status}")

                if not KEEP_RUNNING:
                    break

            # ── Reset si retour dans la zone ────────────────────────────
            if breakout is None and last_breakout is not None:
                print(f"\n  [{_now()}] Prix revenu dans la zone ({_fmt(c)}) — "
                      f"reset detection. Dernier breakout: {last_breakout}")
                last_breakout = None

    except KeyboardInterrupt:
        print(f"\n\n  {YELLOW}[STOP] Arret demande.{RESET}")

    finally:
        mt5.shutdown()
        print(f"  {YELLOW}[OK] Monitoring termine.{RESET}")

    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
