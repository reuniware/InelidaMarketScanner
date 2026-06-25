r"""
auto_scan_and_post.py — Scan automatique + Rapport PDF + Backtest + Post Discord.

Usage:
    python auto_scan_and_post.py                          # scan + rapport + backtest + discord
    python auto_scan_and_post.py --no-report              # scan + discord sans PDF
    python auto_scan_and_post.py --no-discord             # scan + rapport + backtest sans discord
    python auto_scan_and_post.py --webhook <URL>          # webhook custom

Planification Windows (Task Scheduler):
    Programme: python auto_scan_and_post.py
    Declencheur: toutes les heures / a 08:00, 13:00, 16:00 UTC
    Dossier: C:\\Users\\TSTAC\\RustProjects\\InelidaMarketScan

Variables d'environnement:
    DISCORD_WEBHOOK_URL  — URL du webhook Discord
"""

import os
import sys
import time
import json
import logging
import subprocess
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.WARNING, format="%(asctime)s | %(levelname)-7s | %(message)s")
logger = logging.getLogger("auto_scan")

UTC = timezone.utc

# ─── Imports locaux ──────────────────────────────────────────────────────────
try:
    from generate_live_report import fetch_all_data, build_report, REPORTS_DIR
    from discord_notifier import send_discord, build_scan_embed
except ImportError as e:
    print(f"[ERREUR] Import manquant: {e}")
    print("Verifie que generate_live_report.py et discord_notifier.py sont dans le meme dossier.")
    sys.exit(1)

# Backtest: via subprocess (evite les problemes de signature et d'import MT5)
def _parse_backtest_output(output: str) -> dict:
    """Parse la sortie de backtest_report_trades.py pour extraire les stats."""
    import re
    # Cherche: "X GAGNES | Y PERDUS | Z OUVERTS" ou "X GAGNE" etc.
    m = re.search(r'(\d+)\s+GAGN[EÉ]S?\s*\|?\s*(\d+)\s+PERDUS?', output)
    if not m:
        # Alternative: "4 GAGNES, 1 PERDUS"
        m = re.search(r'(\d+)\s+GAGN[EÉ]S?.*?(\d+)\s+PERDUS?', output)
    if not m:
        return {}
    gagnes = int(m.group(1))
    perdus = int(m.group(2))
    ouverts_m = re.search(r'(\d+)\s+OUVERTS?', output)
    ouverts = int(ouverts_m.group(1)) if ouverts_m else 0
    total_closed = gagnes + perdus
    winrate = (gagnes / total_closed * 100) if total_closed > 0 else 0
    return {
        "gagnes": gagnes,
        "perdus": perdus,
        "ouverts": ouverts,
        "winrate": winrate,
        "total": gagnes + perdus + ouverts,
    }

_BACKTEST_AVAILABLE = True  # subprocess toujours dispo


def run_backtest_on_latest() -> dict:
    """Lance backtest_report_trades.py en subprocess et parse les stats."""
    try:
        pdf_files = sorted(
            [f for f in os.listdir(REPORTS_DIR)
             if f.endswith('.pdf') and f.startswith('inelida_report_')],
            reverse=True,
        )
        if not pdf_files:
            logger.warning("Aucun PDF trouve dans %s", REPORTS_DIR)
            return {}

        latest = os.path.join(REPORTS_DIR, pdf_files[0])
        script = os.path.join(os.path.dirname(__file__), "backtest_report_trades.py")

        result = subprocess.run(
            [sys.executable, script, "--pdf", latest],
            capture_output=True, text=True, timeout=180,
        )
        output = result.stdout + result.stderr

        stats = _parse_backtest_output(output)
        if stats:
            stats["pdf"] = os.path.basename(latest)
        return stats
    except subprocess.TimeoutExpired:
        logger.error("Backtest timeout")
        return {}
    except Exception as e:
        logger.error("Backtest failed: %s", e)
        return {}


def run_scan(raw_data: dict = None) -> dict:
    """Parse les donnees de scan en structure Discord.
    
    Args:
        raw_data: Donnees brutes de fetch_all_data(). Si None, appelle fetch_all_data().
    """
    try:
        data = raw_data if raw_data is not None else fetch_all_data()
    except Exception as e:
        logger.error("Scan failed: %s", e)
        raise

    setups = data.get("setups_data", [])
    active = data.get("active_setups", [])

    # Filtrer les trades avec spread > 0.10%
    MAX_SPREAD = 0.10
    trades_filtered = []
    n_skipped = 0
    for s in active:
        sp = s.get("spread_pct", 0)
        if sp > 0 and sp > MAX_SPREAD:
            n_skipped += 1
        else:
            trades_filtered.append(s)

    # Tri par RR décroissant
    trades_filtered.sort(key=lambda t: t.get("rr", 0) or 0, reverse=True)

    trades_list = []
    for t in trades_filtered:
        trades_list.append({
            "symbol": t.get("symbol", "?"),
            "action": t.get("trade", "-"),
            "rr": t.get("rr") or 0,
            "spread": t.get("spread_pct", 0),
            "entry": t.get("entry"),
            "sl": t.get("sl"),
            "tp1": t.get("tp1"),
        })

    # Direction counts
    n_haussier = 0
    n_baissier = 0
    n_mixte = 0
    for s in setups:
        sweep = s.get("sweep", "")
        if sweep == "AH+AL":
            n_mixte += 1
        elif sweep == "AH":
            n_baissier += 1
        elif sweep == "AL":
            n_haussier += 1

    return {
        "scanned": data.get("asian_scanned", 0),
        "setups": len(setups),
        "spread_skipped": n_skipped,
        "trades": trades_list,
        "haussier": n_haussier,
        "baissier": n_baissier,
        "mixte": n_mixte,
        "report_path": "",  # sera rempli après build_report
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Scan auto + Rapport + Discord")
    parser.add_argument("--no-report", action="store_true", help="Ne pas générer le PDF")
    parser.add_argument("--no-discord", action="store_true", help="Ne pas poster sur Discord")
    parser.add_argument("--no-backtest", action="store_true", help="Ne pas lancer le backtest")
    parser.add_argument("--webhook", default=None, help="URL du webhook Discord")
    parser.add_argument("--json", action="store_true", help="Sortir les données en JSON (pour pipe)")
    args = parser.parse_args()

    webhook_url = args.webhook or os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not args.no_discord and not webhook_url:
        print("[ERREUR] --webhook requis ou définir DISCORD_WEBHOOK_URL", file=sys.stderr)
        return 1

    now_utc = datetime.now(UTC)
    print(f"[{now_utc.strftime('%H:%M:%S')}] Auto-scan démarré...")

    # ═══ 1. SCAN ═══
    print("  [1/4] Scan en cours...")
    raw_data = None
    try:
        raw_data = fetch_all_data()
        scan_data = run_scan(raw_data)
    except Exception as e:
        print(f"  [ERREUR] Scan: {e}")
        return 2

    print(f"  {scan_data['scanned']} symboles, {scan_data['setups']} setups, "
          f"{len(scan_data['trades'])} trades actifs, {scan_data['spread_skipped']} filtrés spread")

    # ═══ 2. RAPPORT ═══
    report_path = ""
    if not args.no_report:
        print("  [2/4] Génération rapport PDF...")
        try:
            report_path = build_report(raw_data)
            scan_data["report_path"] = os.path.basename(report_path)
            print(f"  PDF: {report_path}")
        except Exception as e:
            print(f"  [WARN] Rapport échoué: {e}")

    # ═══ 3. BACKTEST ═══
    if not args.no_backtest:
        print("  [3/4] Backtest M1...")
        bt = run_backtest_on_latest()
        if bt:
            scan_data["backtest"] = bt
            print(f"  {bt.get('gagnes',0)}G/{bt.get('perdus',0)}P/{bt.get('ouverts',0)}O "
                  f"({bt.get('winrate',0):.0f}% WR)")
        else:
            print("  Pas de backtest disponible")

    # ═══ 4. DISCORD ═══
    if not args.no_discord:
        print("  [4/4] Envoi Discord...")
        embed = build_scan_embed(scan_data, include_backtest=("backtest" in scan_data))
        payload = {"embeds": [embed]}

        # Sauvegarde JSON locale pour debug
        json_path = os.path.join(REPORTS_DIR, "last_scan_data.json")
        os.makedirs(REPORTS_DIR, exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(scan_data, f, ensure_ascii=False, indent=2)

        ok = send_discord(webhook_url, payload)
        if ok:
            print("  Discord: OK")
        else:
            print("  Discord: FAILED")

    # ── Sortie JSON ──
    if args.json:
        print(json.dumps(scan_data, ensure_ascii=False, indent=2))

    print(f"[{datetime.now(UTC).strftime('%H:%M:%S')}] Terminé.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
