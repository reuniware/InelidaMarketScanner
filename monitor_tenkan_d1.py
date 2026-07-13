"""
monitor_tenkan_d1.py — Monitore GBPUSD en continu et alerte quand le prix
touche la Tenkan Daily (Ichimoku).

Usage:
    python monitor_tenkan_d1.py

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

import MetaTrader5 as mt5

# ─── Configuration ──────────────────────────────────────────────────────────
SYMBOL = "GBPUSD"
POLL_SEC = 15          # Intervalle entre chaque tick
TENKAN_PERIOD = 9      # Periodes pour la Tenkan
TENKAN_FETCH = TENKAN_PERIOD + 5  # Barres a recuperer (marge de securite)
KEEP_RUNNING = True    # Continuer apres la 1ere alerte

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "tenkan_d1_alerts.jsonl")

UTC = timezone.utc

# ─── ANSI ───────────────────────────────────────────────────────────────────
_IS_TTY = sys.stdout.isatty()

def _c(code): return code if _IS_TTY else ""
BOLD = _c("\033[1m"); RED = _c("\033[31m"); GREEN = _c("\033[32m")
YELLOW = _c("\033[33m"); CYAN = _c("\033[36m")
BG_RED = _c("\033[41m"); BG_GREEN = _c("\033[42m"); WHITE = _c("\033[97m")
RESET = _c("\033[0m"); BELL = "\a"


def _fmt(v):
    """Formate un prix selon sa magnitude."""
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
    """Charge l'URL du webhook Discord depuis .env (UTF-16 LE)."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return os.environ.get("DISCORD_WEBHOOK_URL", "")

    with open(env_path, "rb") as f:
        raw = f.read()
    text = raw.replace(b"\x00", b"").decode("ascii", errors="ignore")
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("DISCORD_WEBHOOK_URL="):
            return line.split("=", 1)[1].strip()
    return os.environ.get("DISCORD_WEBHOOK_URL", "")


def fetch_tenkan_d1(symbol):
    """Calcule la Tenkan D1 actuelle (highest high + lowest low) / 2 sur 9 periodes."""
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, TENKAN_FETCH)
    if rates is None or len(rates) < TENKAN_PERIOD + 1:
        return None

    # Dernieres N bougies COMPLETEES (on exclut la bougie du jour en cours)
    completed = rates[:-1]  # Drop la bougie en cours
    window = completed[-TENKAN_PERIOD:]  # Dernieres N bougies terminees

    if len(window) < TENKAN_PERIOD:
        return None

    highs = [float(r[2]) for r in window]
    lows = [float(r[3]) for r in window]
    hh = max(highs)
    ll = min(lows)
    return (hh + ll) / 2.0


def send_discord_alert(webhook_url, price, tenkan, dist_pips):
    """Envoie un embed Discord quand la Tenkan est touchée."""
    now_utc = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    side = "below" if price < tenkan else "at"

    embed = {
        "title": f"GBPUSD — Tenkan D1 touchée !",
        "description": (
            f"**Le prix a atteint la Tenkan Daily**\n\n"
            f"Prix actuel : **{_fmt(price)}**\n"
            f"Tenkan D1  : **{_fmt(tenkan)}**\n"
            f"Distance   : **{dist_pips:+.1f} pips**\n\n"
            f"Prochain support : **Kijun D1** (à surveiller)"
        ),
        "color": 0xE67E22,  # Orange = alerte
        "footer": {"text": f"InelidaMarketScan • {now_utc}"},
    }

    payload = {"embeds": [embed]}
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "InelidaMarketScanner/1.0",
        },
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status == 204
    except Exception as e:
        print(f"  {RED}[Discord] Erreur: {e}{RESET}")
        return False


def console_alert(price, tenkan, dist_pips):
    """Alerte visuelle + sonore dans la console."""
    print(BELL)
    bar = "=" * 60
    print(f"\n{BG_RED}{WHITE}{BOLD}{bar}{RESET}")
    print(f"{BG_RED}{WHITE}{BOLD}  !!! TENKAN D1 TOUCHÉE !!!  {_now()}{RESET}")
    print(f"{BG_RED}{WHITE}{BOLD}{bar}{RESET}")
    print(f"\n  {BOLD}GBPUSD Tenkan Daily (9){RESET}")
    print(f"  Prix actuel : {BOLD}{_fmt(price)}{RESET}")
    print(f"  Tenkan D1   : {BOLD}{_fmt(tenkan)}{RESET}")
    print(f"  Distance    : {BOLD}{dist_pips:+.1f} pips{RESET}")
    print(f"\n  {YELLOW}Prochain objectif : Kijun D1{RESET}")
    print(f"{BG_RED}{WHITE}{BOLD}{bar}{RESET}\n")
    sys.stdout.flush()


def main():
    webhook_url = load_webhook()
    has_discord = bool(webhook_url)
    if has_discord:
        print(f"  {GREEN}Discord: webhook trouvé ({len(webhook_url)} chars){RESET}")
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
    tenkan = fetch_tenkan_d1(SYMBOL)
    if tenkan is None:
        print(f"{RED}[ERREUR] Impossible de calculer la Tenkan D1.{RESET}")
        mt5.shutdown()
        return 1

    dist_pips = round((price - tenkan) * 10000, 1)

    print(f"\n{BOLD}{CYAN}{'='*60}{RESET}")
    print(f"{BOLD}{CYAN}  Monitor Tenkan D1 — {SYMBOL}{RESET}")
    print(f"{BOLD}{CYAN}  {'='*60}{RESET}")
    print(f"  Prix actuel   : {BOLD}{_fmt(price)}{RESET}")
    print(f"  Tenkan D1 (9) : {BOLD}{_fmt(tenkan)}{RESET}")
    print(f"  Distance      : {BOLD}{dist_pips:+.1f} pips{RESET}")
    print(f"  Poll          : toutes les {POLL_SEC}s")
    if KEEP_RUNNING:
        print(f"  Mode          : continu (Ctrl+C pour quitter)")
    else:
        print(f"  Mode          : arret apres alerte")
    print(f"  Alerte quand  : prix <= Tenkan D1")
    print(f"{BOLD}{CYAN}{'='*60}{RESET}\n")

    last_tenkan = tenkan
    alert_fired = False
    poll_count = 0

    try:
        while True:
            poll_count += 1
            time.sleep(POLL_SEC)

            # ── Prix live ───────────────────────────────────────────────
            tick = mt5.symbol_info_tick(SYMBOL)
            if not tick:
                print(f"  {RED}[{_now()}] Tick indisponible{RESET}")
                continue
            price = float(tick.bid)

            # ── Recalculer la Tenkan (peut changer en debut de jour) ────
            tenkan = fetch_tenkan_d1(SYMBOL)
            if tenkan is None:
                tenkan = last_tenkan
            else:
                last_tenkan = tenkan

            dist_pips = round((price - tenkan) * 10000, 1)
            abs_dist = abs(dist_pips)

            # ── Log périodique ──────────────────────────────────────────
            if poll_count % 4 == 0:  # Toutes les ~60s
                direction = "au-dessus" if dist_pips > 0 else "en-dessous"
                bar = "|" * max(1, min(20, int(abs_dist)))
                print(f"  [{_now()}] {_fmt(price)} | Tenkan={_fmt(tenkan)} | "
                      f"{dist_pips:+.1f} pip {'↓' if dist_pips < 0 else '↑'} {bar}",
                      end="\r")
                sys.stdout.flush()

            # ── Détection touche Tenkan ─────────────────────────────────
            if not alert_fired and price <= tenkan:
                alert_fired = True
                console_alert(price, tenkan, dist_pips)

                # ── Log fichier ────────────────────────────────────
                log_entry = json.dumps({
                    "ts_utc": datetime.now(UTC).isoformat(),
                    "symbol": SYMBOL,
                    "price": price,
                    "tenkan_d1": tenkan,
                    "dist_pips": dist_pips,
                }, ensure_ascii=False)
                with open(LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(log_entry + "\n")

                if has_discord:
                    ok = send_discord_alert(webhook_url, price, tenkan, dist_pips)
                    status = f"{GREEN}OK{RESET}" if ok else f"{RED}ÉCHEC{RESET}"
                    print(f"  Discord: {status}")

                if not KEEP_RUNNING:
                    break

            # ── Si déjà alerté mais prix remonte ────────────────────────
            if alert_fired and price > tenkan and KEEP_RUNNING:
                print(f"  [{_now()}] Prix remonté au-dessus de la Tenkan "
                      f"({_fmt(price)} > {_fmt(tenkan)}), poursuite du monitoring...")

    except KeyboardInterrupt:
        print(f"\n\n  {YELLOW}[STOP] Arrêt demandé.{RESET}")

    finally:
        mt5.shutdown()
        if alert_fired:
            print(f"  {GREEN}[OK] Alerte envoyée. Tenkan D1 touchée.{RESET}")
        else:
            print(f"  {YELLOW}[OK] Aucune alerte. Tenkan D1 non atteinte.{RESET}")

    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
