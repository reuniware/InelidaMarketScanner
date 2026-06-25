"""
discord_notifier.py — Notificateur Discord réutilisable pour InelidaMarketScan.

Usage:
    python discord_notifier.py --webhook <URL> --json <fichier.json>
    python discord_notifier.py --webhook <URL> --scan-data  (lit depuis stdin)

Variables d'environnement:
    DISCORD_WEBHOOK_URL  — URL du webhook (prioritaire sur --webhook)

Format du message: embed Discord avec titre, description, fields, couleur.
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone


# ─── Couleurs Discord ────────────────────────────────────────────────────────
COLOR_GREEN  = 0x2ECC71   # Trade gagnant / haussier
COLOR_RED    = 0xE74C3C   # Trade perdant / baissier
COLOR_BLUE   = 0x1E90FF   # Info / neutre
COLOR_ORANGE = 0xE67E22   # Alerte / attention
COLOR_PURPLE = 0x9B59B6   # Setup / analyse


def send_discord(webhook_url: str, payload: dict, timeout: int = 15) -> bool:
    """Envoie un payload JSON au webhook Discord.

    Args:
        webhook_url: URL complete du webhook
        payload: Dictionnaire compatible Discord (content ou embeds)
        timeout: Timeout HTTP en secondes.

    Returns:
        True si OK (HTTP 204), False sinon.
    """
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
        resp = urllib.request.urlopen(req, timeout=timeout)
        if resp.status == 204:
            return True
        print(f"[discord] HTTP {resp.status}: {resp.read().decode()[:200]}", file=sys.stderr)
        return False
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        print(f"[discord] HTTP ERROR {e.code}: {body}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[discord] ERROR: {e}", file=sys.stderr)
        return False


def _fmt(v):
    """Formate un prix/nombre pour affichage Discord."""
    if v is None:
        return "?"
    if isinstance(v, (int, float)):
        if v >= 1000:
            return f"{v:.2f}"
        if v >= 10:
            return f"{v:.4f}"
        return f"{v:.5f}"
    return str(v)


def build_scan_embed(data: dict, include_backtest: bool = False) -> dict:
    """Construit un embed Discord à partir des données de scan.

    Args:
        data: Dictionnaire contenant les clés:
            - scanned: int (nombre de symboles scannés)
            - setups: int (nombre de setups)
            - spread_skipped: int (filtrés par spread)
            - trades: list de dicts {symbol, action, rr, spread, entry, sl, tp1}
            - haussier: int, baissier: int, mixte: int
            - report_path: str optionnel
            - winrate: float optionnel (si backtest)
        include_backtest: ajoute les résultats du dernier backtest

    Returns:
        Dictionnaire embed Discord.
    """
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    scanned = data.get("scanned", 0)
    setups = data.get("setups", 0)
    skipped = data.get("spread_skipped", 0)
    trades = data.get("trades", [])
    n_haussier = data.get("haussier", 0)
    n_baissier = data.get("baissier", 0)
    n_mixte = data.get("mixte", 0)

    # ── Top 3 ──
    top3 = "\n".join(
        f"{i+1}. **{t['symbol']}** {t['action']} | RR {t['rr']:.1f}x | Spr {t['spread']:.3f}%"
        for i, t in enumerate(trades[:3])
    ) if trades else "Aucun trade actif"

    # ── Details top 3 ──
    top3_detail = "\n".join(
        f"**{t['symbol']}** {t['action']}\n"
        f"> Entry {_fmt(t.get('entry'))} → SL {_fmt(t.get('sl'))} → TP1 {_fmt(t.get('tp1'))}\n"
        f"> RR {t['rr']:.1f}x | Spread {t['spread']:.3f}%"
        for t in trades[:3]
    ) if trades else "Aucun détail disponible"

    # ── Tous les trades ──
    all_trades = "\n".join(
        f"`{t['symbol']:<10} {t['action']:>4} {t['rr']:.1f}x  {t['spread']:.3f}%`"
        for t in trades[:15]
    ) if trades else "`—`"

    # ── Résumé directionnel ──
    resume = (
        f"🟢 **{n_haussier}** HAUSSIER | "
        f"🔴 **{n_baissier}** BAISSIER | "
        f"🟡 **{n_mixte}** MIXTE"
    )
    if skipped > 0:
        resume += f" | ❌ **{skipped}** filtrés spread"

    # ── Alerte RR ──
    rr_trades = [t for t in trades if t.get("rr", 0) >= 1.0]
    if not rr_trades and trades:
        alert = "⚠️ **Aucun trade avec RR ≥ 1.0** — attendre le prochain scan ou vérifier les setups en attente."
    elif not trades:
        alert = "ℹ️ Aucun trade actif détecté."
    else:
        alert = f"✅ **{len(rr_trades)}** trade(s) avec RR ≥ 1.0 — signaux exploitables."

    # ── Backtest ──
    backtest_field = None
    if include_backtest and "backtest" in data:
        bt = data["backtest"]
        backtest_field = {
            "name": "🔙 Dernier backtest",
            "value": (
                f"`{bt.get('gagnes',0)}` GAGNÉS | "
                f"`{bt.get('perdus',0)}` PERDUS | "
                f"`{bt.get('ouverts',0)}` OUVERTS\n"
                f"Winrate: **{bt.get('winrate',0):.0f}%** "
                f"({bt.get('gagnes',0)}/{bt.get('gagnes',0)+bt.get('perdus',0)} closed)"
            ),
        }

    report_path = data.get("report_path", "")

    fields = [
        {"name": "🏆 Top 3 Trades", "value": top3_detail if trades else top3, "inline": False},
        {"name": "📈 Tous les trades actifs", "value": all_trades, "inline": False},
        {"name": "⚠️ Alerte", "value": alert, "inline": False},
        {"name": "📋 Résumé directionnel", "value": resume, "inline": False},
    ]
    if backtest_field:
        fields.insert(3, backtest_field)
    if report_path:
        fields.append({"name": "📁 Rapport", "value": f"`{report_path}`", "inline": False})

    # Couleur: vert si trades RR≥1, orange si aucun RR≥1, bleu sinon
    if rr_trades:
        color = COLOR_GREEN
    elif trades and not rr_trades:
        color = COLOR_ORANGE
    else:
        color = COLOR_BLUE

    embed = {
        "title": f"📊 InelidaMarketScan — Analyse {now_utc}",
        "description": f"Scan complet • {scanned} symboles • {setups} setups",
        "color": color,
        "fields": fields,
        "footer": {"text": "InelidaMarketScanner"},
    }

    return embed


def load_scan_json(path: str = None) -> dict:
    """Charge les données de scan depuis un fichier JSON ou stdin."""
    if path:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        return json.load(sys.stdin)


# ─── CLI ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Notificateur Discord pour InelidaMarketScan"
    )
    parser.add_argument(
        "--webhook", default=None,
        help="URL du webhook Discord (sinon DISCORD_WEBHOOK_URL env var)"
    )
    parser.add_argument(
        "--json", dest="json_file", default=None,
        help="Fichier JSON contenant les données de scan"
    )
    parser.add_argument(
        "--message", default=None,
        help="Message texte simple à envoyer (ignore --json)"
    )
    parser.add_argument(
        "--test", action="store_true",
        help="Envoie un message de test pour vérifier la connexion"
    )
    args = parser.parse_args()

    webhook_url = args.webhook or os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not webhook_url:
        print("[ERREUR] Aucun webhook URL fourni (--webhook ou DISCORD_WEBHOOK_URL)", file=sys.stderr)
        return 1

    # ── Test ──
    if args.test:
        payload = {"content": "🧪 InelidaMarketScanner — Test de connexion Discord OK ✅"}
        ok = send_discord(webhook_url, payload)
        print("Discord test: OK" if ok else "Discord test: FAILED")
        return 0 if ok else 2

    # ── Message simple ──
    if args.message:
        payload = {"content": args.message[:2000]}  # Discord limit
        ok = send_discord(webhook_url, payload)
        return 0 if ok else 3

    # ── Scan depuis fichier JSON ──
    if args.json_file:
        data = load_scan_json(args.json_file)
    elif not sys.stdin.isatty():
        data = load_scan_json()
    else:
        print("[ERREUR] --json <fichier> requis (pas de pipe detecte)", file=sys.stderr)
        return 1

    embed = build_scan_embed(data, include_backtest=("backtest" in data))
    payload = {"embeds": [embed]}
    ok = send_discord(webhook_url, payload)
    return 0 if ok else 4


if __name__ == "__main__":
    sys.exit(main())
