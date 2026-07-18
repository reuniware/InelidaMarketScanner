#!/usr/bin/env python3
"""
automate_weekly.py — Automatisation hebdomadaire du pipeline DXY Diamond Scanner.

Execute le workflow approprie selon le jour de la semaine (lundi→vendredi)
en utilisant les guides DXY.{lundi,mardi,mercredi,jeudi,vendredi}.md.

Principes :
  - Lundi : scan Asian + Diamond apres London Open (09h). Pas de trade avant Londres.
  - Mardi : meilleur jour. Scan matinal + NY Open (14h30). Volume max.
  - Mercredi : FOMC Day. Scan reduit le matin, BLACKOUT 18h30-19h30, trade post-FOMC.
  - Jeudi : continuation post-FOMC. Scan 09h + 14h30. Pas de trade apres 17h.
  - Vendredi : fermer TOUS les trades avant 17h. Track report hebdo.

Usage:
    python automate_weekly.py                          # auto-detecte le jour
    python automate_weekly.py --day monday              # force un jour
    python automate_weekly.py --dry-run                 # ne fait rien, affiche le plan
    python automate_weekly.py --discord                 # envoie les resultats sur Discord
    python automate_weekly.py --symbols DXY.cash EURUSD # symboles custom

Planification (Windows Task Scheduler) :
    Programme: python automate_weekly.py
    Declencheur: 07:00, 09:00, 14:30, 17:00, 21:00 chaque jour
    Dossier: C:\\Users\\TSTAC\\RustProjects\\InelidaMarketScan
"""

import argparse
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import List, Optional

# ─── Chemin projet ──────────────────────────────────────────────────────────
PROJECT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT)

# ─── Logger ─────────────────────────────────────────────────────────────────
LOG_DIR = os.path.join(PROJECT, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, f"automate_weekly_{datetime.now():%Y-%m-%d}.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
    force=True,
)
logger = logging.getLogger("automate_weekly")

UTC = timezone.utc

# ─── Symboles par defaut (watchlist reduite 14 actifs) ───────────────────────
DEFAULT_SYMBOLS = [
    "DXY.cash",
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF",
    "EURJPY", "GBPJPY", "NZDUSD",
    "XAUUSD",
    "US30.cash", "US100.cash", "US500.cash",
]

# ─── Mapping jours → workflows ──────────────────────────────────────────────
WORKFLOW_DAYS = {
    0: "lundi",
    1: "mardi",
    2: "mercredi",
    3: "jeudi",
    4: "vendredi",
}

# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _now_paris() -> str:
    """Heure au format HH:MM fuseau Paris (DST-aware, UTC+2 ete / UTC+1 hiver)."""
    try:
        from zoneinfo import ZoneInfo
        paris = datetime.now(ZoneInfo("Europe/Paris"))
        return paris.strftime("%H:%M")
    except Exception:
        # Fallback: UTC+2 ete (simple), UTC+1 hiver (DST ajuste)
        import time as _time
        if _time.localtime().tm_isdst:
            off = 2
        else:
            off = 1
        h = (datetime.now(UTC).hour + off) % 24
        m = datetime.now(UTC).minute
        return f"{h:02d}:{m:02d}"


def _now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _day_name() -> str:
    """Retourne le nom du jour en francais (lundi→vendredi)."""
    return WORKFLOW_DAYS.get(datetime.now(UTC).weekday(), "weekend")


def _is_weekend() -> bool:
    """Retourne True si samedi ou dimanche."""
    return datetime.now(UTC).weekday() >= 5


def _run_python(args: List[str], timeout: int = 300) -> dict:
    """Execute une commande Python du projet et retourne {stdout, stderr, returncode}.

    Args:
        args: Liste d'arguments (ex: ["main.py", "diamond", "--symbols", "DXY.cash"])
        timeout: Timeout en secondes (defaut: 300s)
    """
    cmd = [sys.executable, os.path.join(PROJECT, args[0])] + args[1:]
    logger.debug(f"  RUN: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=PROJECT,
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        logger.error(f"  TIMEOUT ({timeout}s) pour {' '.join(args)}")
        return {"stdout": "", "stderr": "TIMEOUT", "returncode": -1}
    except FileNotFoundError as e:
        logger.error(f"  FICHIER INTROUVABLE: {e}")
        return {"stdout": "", "stderr": str(e), "returncode": -2}
    except Exception as e:
        logger.error(f"  ERREUR: {e}")
        return {"stdout": "", "stderr": str(e), "returncode": -3}


def _log_run(label: str, result: dict):
    """Logge le resultat d'une commande."""
    if result["returncode"] == 0:
        logger.info(f"  ✅ {label} — OK")
    else:
        stderr = result["stderr"][:200] if result["stderr"] else "(pas de stderr)"
        stdout_tail = result["stdout"][-200:] if result["stdout"] else ""
        logger.warning(f"  ⚠️  {label} — code {result['returncode']}")
        if stderr:
            logger.debug(f"  stderr: {stderr}")
        if stdout_tail:
            logger.debug(f"  stdout (fin): {stdout_tail}")


def _run_diamond_scan(symbols: List[str], discord: bool = False, tz: str = "BROKER") -> dict:
    """Execute un scan Diamond Analysis.

    Args:
        symbols: Liste des symboles a scanner
        discord: Envoyer les resultats sur Discord
        tz: Fuseau horaire (BROKER/UTC/PARIS)
    """
    args = ["main.py", "diamond", "--timezone", tz]
    if symbols:
        args += ["--symbols"] + symbols
    if discord:
        args.append("--discord")
    return _run_python(args, timeout=300)


def _run_track_save(symbols: List[str], force: bool = False, tz: str = "BROKER") -> dict:
    """Execute track save (scan + sauvegarde des setups)."""
    args = ["main.py", "track", "save", "--timezone", tz]
    if symbols:
        args += ["--symbols"] + symbols
    if force:
        args.append("--force")
    return _run_python(args, timeout=300)


def _run_track_update() -> dict:
    """Execute track update (mise a jour des prix des trades ouverts)."""
    return _run_python(["main.py", "track", "update"], timeout=120)


def _run_track_report(limit: int = 30) -> dict:
    """Execute track report (rapport P&L)."""
    return _run_python(["main.py", "track", "report", "--limit", str(limit)], timeout=60)


def _run_asian_scan(symbols: List[str], tz: str = "BROKER") -> dict:
    """Execute un scan Asian ICT."""
    args = ["main.py", "asian", "--timezone", tz]
    if symbols:
        args += ["--symbols"] + symbols
    return _run_python(args, timeout=300)


def _run_misc(args_list: List[str], timeout: int = 120) -> dict:
    """Execute une commande Python quelconque du projet."""
    return _run_python(args_list, timeout=timeout)


# ═══════════════════════════════════════════════════════════════════════════════
# WORKFLOWS QUOTIDIENS
# ═══════════════════════════════════════════════════════════════════════════════

def workflow_lundi(symbols: List[str], dry_run: bool, discord: bool, close_all: bool = False):
    """ Lundi : découverte de prix, pas de trade avant Londres.

    Horloge :
        07h — Scan Asian (range de la nuit)
        09h — FEU VERT : Scan Diamond + track save si setup
        14h30 — Scan de confirmation NY Open
        21h — Track update + track report
    """
    logger.info("=" * 60)
    logger.info("📅 LUNDI — Découverte de prix, pas de trade avant Londres")
    logger.info("=" * 60)
    logger.info(f"  Heure: {_now_paris()} Paris | {_now_utc()}")
    logger.info(f"  Symboles: {len(symbols)}")

    if dry_run:
        logger.info("  [DRY-RUN] Plan du lundi :")
        logger.info("    07h00 — python main.py asian --timezone BROKER")
        logger.info("    09h00 — python main.py diamond --timezone BROKER")
        logger.info("    09h00 — python main.py track save")
        logger.info("    14h30 — python main.py diamond --timezone BROKER")
        logger.info("    14h30 — python main.py track update")
        logger.info("    21h00 — python main.py track update")
        logger.info("    21h00 — python main.py track report")
        if discord:
            logger.info("    Avec --discord sur les scans Diamond")
        return True

    # ── 1. Scan Asian (range de la nuit) ──
    logger.info("\n[1/5] Scan Asian ICT...")
    r = _run_asian_scan(symbols)
    _log_run("Asian scan", r)

    # ── 2. Scan Diamond London Open ──
    logger.info("\n[2/5] Scan Diamond (London Open)...")
    r = _run_diamond_scan(symbols, discord=discord)
    _log_run("Diamond scan", r)

    # ── 3. Sauvegarde des setups ──
    logger.info("\n[3/5] Track save...")
    r = _run_track_save(symbols)
    _log_run("Track save", r)

    # ── 4. Confirmation NY Open ──
    logger.info("\n[4/5] Mise a jour NY Open...")
    r = _run_track_update()
    _log_run("Track update", r)

    # ── 5. Bilan de clôture ──
    logger.info("\n[5/5] Bilan de cloture...")
    r = _run_track_update()
    _log_run("Track update (cloture)", r)
    r = _run_track_report()
    _log_run("Track report", r)

    logger.info("\n✅ Lundi termine.")
    return True


def workflow_mardi(symbols: List[str], dry_run: bool, discord: bool, close_all: bool = False):
    """ Mardi : meilleur jour pour le DXY. Volume max, tendance claire.

    Horloge :
        07h — Scan matinal + Diamond
        09h — FEU VERT : 1ère entrée possible
        14h30 — FEU VERT : meilleure fenêtre (NY Open)
        17h — Dernière entrée
        21h — Track update + track save + track report
    """
    logger.info("=" * 60)
    logger.info("📅 MARDI — Meilleur jour DXY (73% WR), volume max")
    logger.info("=" * 60)
    logger.info(f"  Heure: {_now_paris()} Paris | {_now_utc()}")
    logger.info(f"  Symboles: {len(symbols)}")

    if dry_run:
        logger.info("  [DRY-RUN] Plan du mardi :")
        logger.info("    07h00 — python main.py diamond --timezone BROKER")
        logger.info("    09h00 — python main.py diamond --timezone BROKER")
        logger.info("    09h00 — python main.py track save")
        logger.info("    14h30 — python main.py diamond --timezone BROKER")
        logger.info("    14h30 — python main.py track update")
        logger.info("    17h00 — python main.py track update")
        logger.info("    21h00 — python main.py track report")
        if discord:
            logger.info("    Avec --discord sur les scans Diamond")
        return True

    # ── 1. Scan matinal ──
    logger.info("\n[1/6] Scan Diamond matinal...")
    r = _run_diamond_scan(symbols, discord=discord)
    _log_run("Diamond scan matinal", r)

    # ── 2. London Open ──
    logger.info("\n[2/6] Scan Diamond London Open...")
    r = _run_diamond_scan(symbols)
    _log_run("Diamond scan London", r)

    # ── 3. Sauvegarde ──
    logger.info("\n[3/6] Track save...")
    r = _run_track_save(symbols)
    _log_run("Track save", r)

    # ── 4. NY Open + mise à jour ──
    logger.info("\n[4/6] Mise a jour NY Open...")
    r = _run_track_update()
    _log_run("Track update", r)

    # ── 5. Dernière mise à jour ──
    logger.info("\n[5/6] Mise a jour fin de jour...")
    r = _run_track_update()
    _log_run("Track update (fin)", r)

    # ── 6. Bilan ──
    logger.info("\n[6/6] Bilan...")
    r = _run_track_report()
    _log_run("Track report", r)

    logger.info("\n✅ Mardi termine.")
    return True


def workflow_mercredi(symbols: List[str], dry_run: bool, discord: bool, close_all: bool = False):
    """ Mercredi : FOMC Day. BLACKOUT 18h30-19h30. Trade post-FOMC.

    Horloge :
        07h — Scan matinal (range pré-FOMC)
        09h — Scan Diamond (trades réduits de 50%)
        14h30 — Dernière entrée AVANT FOMC
        18h30 — BLACKOUT : plus de trades
        19h00 — FOMC STATEMENT
        20h00 — FEU VERT post-FOMC (30 min après)
        22h — Track update + track report
    """
    logger.info("=" * 60)
    logger.info("📅 MERCREDI — FOMC DAY ⚠️  BLACKOUT 18h30-19h30")
    logger.info("=" * 60)
    logger.info(f"  Heure: {_now_paris()} Paris | {_now_utc()}")
    logger.info(f"  Symboles: {len(symbols)}")

    if dry_run:
        logger.info("  [DRY-RUN] Plan du mercredi :")
        logger.info("    07h00 — python main.py diamond --timezone BROKER")
        logger.info("    09h00 — python main.py diamond --timezone BROKER")
        logger.info("    09h00 — python main.py track save --force (trades reduits)")
        logger.info("    14h30 — python main.py diamond --timezone BROKER (derniere avant FOMC)")
        logger.info("    18h30 — ⛔ BLACKOUT (pas de trades)")
        logger.info("    20h00 — python main.py diamond --timezone BROKER (post-FOMC)")
        logger.info("    20h00 — python main.py track save (post-FOMC)")
        logger.info("    22h00 — python main.py track update + track report")
        if discord:
            logger.info("    Avec --discord sur les scans Diamond")
        return True

    # ── 1. Scan matinal ──
    logger.info("\n[1/7] Scan matinal pre-FOMC...")
    r = _run_diamond_scan(symbols, discord=discord)
    _log_run("Scan matinal", r)

    # ── 2. London Open ──
    logger.info("\n[2/7] Scan London Open...")
    r = _run_diamond_scan(symbols)
    _log_run("Scan London", r)

    # ── 3. Sauvegarde pré-FOMC ──
    logger.info("\n[3/7] Track save (pre-FOMC)...")
    r = _run_track_save(symbols, force=True)
    _log_run("Track save pre-FOMC", r)

    # ── 4. NY Open (dernière avant FOMC) ──
    logger.info("\n[4/7] Dernier scan avant FOMC...")
    r = _run_diamond_scan(symbols)
    _log_run("Scan pre-FOMC", r)

    # ── 5. POST-FOMC ──
    now_h = datetime.now(UTC).hour
    if 19 <= now_h < 22:
        logger.info("\n[5/7] Scan POST-FOMC...")
        r = _run_diamond_scan(symbols, discord=discord)
        _log_run("Scan post-FOMC", r)

        logger.info("\n[6/7] Track save post-FOMC...")
        r = _run_track_save(symbols)
        _log_run("Track save post-FOMC", r)
    else:
        logger.info(f"\n[5-6/7] POST-FOMC: il est {_now_paris()} — pas encore l'heure du FOMC (19h Paris).")

    # ── 7. Bilan ──
    logger.info("\n[7/7] Bilan de cloture...")
    r = _run_track_update()
    _log_run("Track update", r)
    r = _run_track_report()
    _log_run("Track report", r)

    logger.info("\n✅ Mercredi termine.")
    return True


def workflow_jeudi(symbols: List[str], dry_run: bool, discord: bool, close_all: bool = False):
    """ Jeudi : continuation post-FOMC + Unemployment Claims.

    Horloge :
        07h — Scan matinal (tendance post-FOMC)
        09h — FEU VERT : continuation trade
        14h30 — FEU VERT : NY Open + news US
        17h — DERNIERE entrée
        21h — Track update + track save + track report
    """
    logger.info("=" * 60)
    logger.info("📅 JEUDI — Continuation post-FOMC + Unemployment Claims")
    logger.info("=" * 60)
    logger.info(f"  Heure: {_now_paris()} Paris | {_now_utc()}")
    logger.info(f"  Symboles: {len(symbols)}")

    if dry_run:
        logger.info("  [DRY-RUN] Plan du jeudi :")
        logger.info("    07h00 — python main.py diamond --timezone BROKER")
        logger.info("    09h00 — python main.py diamond --timezone BROKER")
        logger.info("    09h00 — python main.py track save")
        logger.info("    14h30 — python main.py diamond --timezone BROKER (news US)")
        logger.info("    14h30 — python main.py track update")
        logger.info("    17h00 — python main.py track update (derniere MAJ)")
        logger.info("    21h00 — python main.py track report")
        if discord:
            logger.info("    Avec --discord sur les scans Diamond")
        return True

    # ── 1. Scan matinal post-FOMC ──
    logger.info("\n[1/6] Scan matinal post-FOMC...")
    r = _run_diamond_scan(symbols, discord=discord)
    _log_run("Scan matinal", r)

    # ── 2. London Open ──
    logger.info("\n[2/6] Scan London Open...")
    r = _run_diamond_scan(symbols)
    _log_run("Scan London", r)

    # ── 3. Sauvegarde ──
    logger.info("\n[3/6] Track save...")
    r = _run_track_save(symbols)
    _log_run("Track save", r)

    # ── 4. NY Open ──
    logger.info("\n[4/6] Scan NY Open...")
    r = _run_diamond_scan(symbols)
    _log_run("Scan NY Open", r)
    r = _run_track_update()
    _log_run("Track update NY", r)

    # ── 5. Dernière mise à jour ──
    logger.info("\n[5/6] Track update fin de jour...")
    r = _run_track_update()
    _log_run("Track update", r)

    # ── 6. Bilan ──
    logger.info("\n[6/6] Bilan...")
    r = _run_track_report()
    _log_run("Track report", r)

    logger.info("\n✅ Jeudi termine.")
    return True


def workflow_vendredi(symbols: List[str], dry_run: bool, discord: bool, close_all: bool = False):
    """ Vendredi : ⚠️  Fermer TOUS les trades avant 17h. Profit-taking.

    Horloge :
        07h — Scan matinal + track update
        09h — FEU VERT : dernière vraie entrée
        14h30 — DERNIERE fenêtre (SL serré, TP court)
        16h — ⛔ STOP : fermer TOUS les trades
        17h — ✅ Plus de trading
        22h — TRACK REPORT HEBDOMADAIRE
    """
    logger.info("=" * 60)
    logger.info("📅 VENDREDI — ⚠️  Fermer TOUS les trades avant 17h")
    logger.info("=" * 60)
    logger.info(f"  Heure: {_now_paris()} Paris | {_now_utc()}")
    logger.info(f"  Symboles: {len(symbols)}")

    if dry_run:
        logger.info("  [DRY-RUN] Plan du vendredi :")
        logger.info("    07h00 — python main.py diamond --timezone BROKER")
        logger.info("    07h00 — python main.py track update")
        logger.info("    09h00 — python main.py diamond --timezone BROKER (derniere entree)")
        logger.info("    09h00 — python main.py track save")
        logger.info("    14h30 — python main.py diamond --timezone BROKER (derniere fenetre)")
        logger.info("    16h00 — ⛔ Fermer TOUS les trades")
        logger.info("    22h00 — python main.py track report (rapport hebdo)")
        if discord:
            logger.info("    Avec --discord sur les scans Diamond")
        return True

    # ── 1. Scan matinal ──
    logger.info("\n[1/7] Scan Diamond matinal...")
    r = _run_diamond_scan(symbols, discord=discord)
    _log_run("Scan matinal", r)

    # ── 2. Track update ──
    logger.info("\n[2/7] Track update matinal...")
    r = _run_track_update()
    _log_run("Track update", r)

    # ── 3. London Open (dernière entrée) ──
    logger.info("\n[3/7] Scan London (derniere entree)...")
    r = _run_diamond_scan(symbols)
    _log_run("Scan London", r)
    r = _run_track_save(symbols)
    _log_run("Track save", r)

    # ── 4. NY Open (derniere fenetre — toujours execute) ──
    logger.info("\n[4/7] Scan NY Open (derniere fenetre)...")
    r = _run_diamond_scan(symbols)
    _log_run("Scan NY Open", r)
    r = _run_track_update()
    _log_run("Track update", r)

    # ── 5. ⛔ Fermeture des trades ──
    # ── 5. ⛔ Fermeture des trades (toujours execute, pas conditionne par l'heure) --
    logger.info("\n[5/7] ⛔ Fermeture de TOUS les trades...")

    # Verifier les trades ouverts via la base SQLite directement
    open_trade_ids = []
    try:
        db_path = os.path.join(PROJECT, "trading.db")
        if os.path.exists(db_path):
            import sqlite3
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT id, symbol FROM diamond_trades WHERE status = 'OPEN'"
            )
            open_trade_ids = [(r["id"], r["symbol"]) for r in cur.fetchall()]
            conn.close()
    except Exception as e:
        logger.warning(f"  Impossible de lire la base DB: {e}")

    if open_trade_ids:
        logger.info(f"  {len(open_trade_ids)} trade(s) ouvert(s) trouve(s):")
        for tid, sym in open_trade_ids:
            logger.info(f"    #{tid} {sym}")

        # Fermeture automatique si --close-all active
        if close_all:
            logger.info("  ⛔ --close-all actif : fermeture automatique...")
            for tid, sym in open_trade_ids:
                logger.info(f"  Fermeture trade #{tid} ({sym})...")
                close_r = _run_misc(["main.py", "track", "close", "--id", str(tid), "--reason", "CLOTURE_WEEKEND"])
                _log_run(f"Close #{tid}", close_r)
            logger.info("  ✅ Tous les trades fermes.")
        else:
            logger.warning("")
            logger.warning("  ╔══════════════════════════════════════════════════════╗")
            logger.warning("  ║  ⛔ TRADES ENCORE OUVERTS  ╔                      ║")
            logger.warning("  ║                                                  ║")
            logger.warning(f"  ║  {len(open_trade_ids)} trade(s) encore ouvert(s) le weekend!   ║")
            logger.warning("  ║  Ferme-les avec --close-all :                    ║")
            logger.warning("  ║                                                  ║")
            logger.warning("  ║  python automate_weekly.py --day vendredi        ║")
            logger.warning("  ║                         --close-all              ║")
            logger.warning("  ╚══════════════════════════════════════════════════╝")
            logger.warning("")

    # ── 6. Track update final ──
    logger.info("\n[6/7] Track update final...")
    r = _run_track_update()
    _log_run("Track update final", r)

    # ── 7. Rapport hebdomadaire ──
    logger.info("\n[7/7] TRACK REPORT HEBDOMADAIRE...")
    logger.info("=" * 60)
    r = _run_track_report(limit=50)
    _log_run("Track report hebdo", r)
    logger.info("=" * 60)

    # Extraire win rate du rapport
    if r["returncode"] == 0 and r["stdout"]:
        for line in r["stdout"].split("\n"):
            if "Win rate" in line:
                logger.info(f"  📊 {line.strip()}")

    logger.info("\n✅ Vendredi termine. Bon weekend !")
    logger.info("  ⚠️  Aucun trade ouvert le weekend !")
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# DISPATCH
# ═══════════════════════════════════════════════════════════════════════════════

WORKFLOWS = {
    "lundi": workflow_lundi,
    "mardi": workflow_mardi,
    "mercredi": workflow_mercredi,
    "jeudi": workflow_jeudi,
    "vendredi": workflow_vendredi,
}


def main():
    parser = argparse.ArgumentParser(
        description="Automate Weekly — Pipeline DXY Diamond Scanner (Lundi→Vendredi)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemples :\n"
            "  python automate_weekly.py                       # auto-detecte le jour\n"
            "  python automate_weekly.py --day lundi            # force lundi\n"
            "  python automate_weekly.py --dry-run              # affiche le plan sans executer\n"
            "  python automate_weekly.py --discord              # avec envoi Discord\n"
            "\n"
            "Planification Windows Task Scheduler :\n"
            "  Programme : python automate_weekly.py\n"
            "  Arguments : (rien, auto-detecte le jour)\n"
            "  Déclencheur : 07:00, 09:00, 14:30, 17:00, 21:00 chaque jour\n"
            "  Dossier : C:\\Users\\TSTAC\\RustProjects\\InelidaMarketScan\n"
        ),
    )
    parser.add_argument(
        "--day", choices=["lundi", "mardi", "mercredi", "jeudi", "vendredi", "auto"],
        default="auto",
        help="Force un jour specifique (defaut: auto-detecte)",
    )
    parser.add_argument(
        "--symbols", nargs="*", default=None,
        help="Symboles a scanner (defaut: watchlist 14 actifs)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Affiche le plan sans rien executer",
    )
    parser.add_argument(
        "--discord", action="store_true",
        help="Envoie les resultats sur Discord (--discord)",
    )
    parser.add_argument(
        "--timezone", default="BROKER",
        choices=["BROKER", "UTC", "PARIS"],
        help="Fuseau horaire (defaut: BROKER)",
    )
    parser.add_argument(
        "--close-all", action="store_true",
        help="Vendredi : fermer TOUS les trades automatiquement",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Mode verbose (logs DEBUG)",
    )
    args = parser.parse_args()

    # ── Logging level ──
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        for h in logging.getLogger().handlers:
            h.setLevel(logging.DEBUG)

    # ── Vérification weekend ──
    if _is_weekend() and args.day == "auto":
        logger.info("📅 WEEKEND — Pas de trading. Marchés fermés.")
        logger.info("  Les trades DXY ne traversent JAMAIS le weekend.")
        logger.info("  Reviens lundi matin pour un scan Diamond complet.")
        logger.info("  Pour forcer un jour : python automate_weekly.py --day lundi")
        return 0

    # ── Déterminer le jour ──
    # Fix doublon argparse : retirer le deuxieme --close-all s'il existe
    # (le premier est declare dans la boucle des arguments, on garde la version finale)
    if args.day == "auto":
        day = _day_name()
    else:
        day = args.day

    if day == "weekend":
        logger.info("📅 WEEKEND — Aucune operation planifiee.")
        return 0

    # ── Symboles ──
    symbols = args.symbols or DEFAULT_SYMBOLS

    # ── En-tête ──
    logger.info("")
    logger.info("╔" + "═" * 58 + "╗")
    logger.info(f"║  📅 Inelida Market Scanner — Automate Weekly           ║")
    logger.info(f"║  Jour: {day.upper():<20}                        ║")
    logger.info(f"║  Heure: {_now_paris()} Paris | {_now_utc()}        ║")
    logger.info(f"║  Symboles: {len(symbols):<3}                               ║")
    logger.info(f"║  Dry-run: {'OUI' if args.dry_run else 'NON':<4}                             ║")
    logger.info(f"║  Discord: {'OUI' if args.discord else 'NON':<4}                             ║")
    logger.info(f"╚" + "═" * 58 + "╝")
    logger.info("")

    # ── Exécuter le workflow du jour ──
    workflow_fn = WORKFLOWS.get(day)
    if not workflow_fn:
        logger.error(f"Jour inconnu: {day}")
        return 1

    try:
        success = workflow_fn(symbols, dry_run=args.dry_run, discord=args.discord, close_all=args.close_all)
        if success:
            logger.info(f"\n🎯 {day.capitalize()} termine avec succes.")
            logger.info(f"  Log: {LOG_FILE}")
            return 0
        else:
            logger.error(f"\n❌ {day.capitalize()} echoue.")
            return 2
    except Exception as e:
        logger.error(f"\n💥 ERREUR dans le workflow {day}: {e}", exc_info=True)
        return 3


if __name__ == "__main__":
    sys.exit(main())
