"""
Script standalone d'analyse IA reguliere pour InelidaMarketScanner.
=====================================================================
Lance les scans ICT, formate les donnees, et les envoie a Google Gemini
(IA gratuite, 1500 requetes/jour) pour obtenir une analyse de marche.

Utilisation :
    python run_ai_analysis.py
    python run_ai_analysis.py --symbols XAUUSD EURUSD GBPUSD
    python run_ai_analysis.py --scan-all
    python run_ai_analysis.py --output-dir ./analyses

Planification Windows (tous les jours a 8h30 UTC = 10h30 Paris) :
    schtasks /create /tn "InelidaAIAnalysis" /tr "python C:/Users/TSTAC/RustProjects/InelidaMarketScan/run_ai_analysis.py" /sc daily /st 10:30

Cle API Gemini (gratuite) : https://aistudio.google.com/apikey
"""

import sys
import os
import argparse
import time
from datetime import datetime, timezone

# Ajouter le répertoire du projet au path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.ai_analyst import format_market_prompt, save_analysis
from src.ai_client import GeminiAnalyst
from src.mt5_connector import MT5Connector
from src.sweep_detector import (
    scan_market_watch_asian_ranges,
    scan_market_watch_for_sweeps,
    scan_market_watch_levels,
    asians_to_dicts,
    events_to_dicts,
)
from src.config import load_dotenv, resolve_watchlist

load_dotenv()

UTC = timezone.utc

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    print("=" * 70)
    print("  CLÉ API GEMINI MANQUANTE")
    print("  Crée un fichier .env à la racine du projet avec :")
    print("    GEMINI_API_KEY=TA_CLE_ICI")
    print("  Clé gratuite : https://aistudio.google.com/apikey")
    print("=" * 70)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="InelidaMarketScanner — Analyse IA via Gemini (gratuit)"
    )
    parser.add_argument(
        "--symbols", nargs="*", default=None,
        help="Symboles à scanner (défaut : watchlist configurée).",
    )
    parser.add_argument(
        "--scan-all", action="store_true",
        help="Scanner TOUS les symboles disponibles chez le broker.",
    )
    parser.add_argument(
        "--output-dir", default=".",
        help="Répertoire de sortie pour les analyses (défaut : dossier projet).",
    )
    parser.add_argument(
        "--skip-sweeps", action="store_true",
        help="Désactiver le scan BSL/SSL (plus rapide).",
    )
    parser.add_argument(
        "--skip-levels", action="store_true",
        help="Désactiver le scan daily/weekly (plus rapide).",
    )
    args = parser.parse_args()

    now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 70)
    print("  InelidaMarketScanner — ANALYSE IA via GEMINI (gratuit)")
    print(f"  {now_str} UTC")
    print("=" * 70)
    print()

    # ═════════════════════════════════════════════════════════════════════
    # ÉTAPE 1 : Connexion MT5
    # ═════════════════════════════════════════════════════════════════════
    print("[1/4] Connexion à MetaTrader 5...")
    mt5c = MT5Connector()
    if not mt5c.ensure_connected():
        print("[ERREUR] Impossible de se connecter à MT5.")
        print("  Vérifie que MetaTrader 5 est lancé et connecté.")
        return 1

    ti = mt5c.get_terminal_info()
    if ti:
        print(f"  Terminal : {ti.get('name', '?')} (build {ti.get('build', '?')})")

    account_info = mt5c.get_account_info()
    if account_info:
        print(f"  Compte   : {account_info.get('login', '?')} @ {account_info.get('server', '?')}")
        balance = account_info.get('balance', 0)
        currency = account_info.get('currency', '')
        print(f"  Balance  : {balance:.2f} {currency}")
    print()

    # ═════════════════════════════════════════════════════════════════════
    # ÉTAPE 2 : Résolution des symboles
    # ═════════════════════════════════════════════════════════════════════
    if args.scan_all:
        symbols = mt5c.list_all_symbols()
        print(f"[2/4] Scan de TOUS les symboles du broker ({len(symbols)})")
    else:
        symbols = resolve_watchlist(args.symbols)
        print(f"[2/4] Scan de {len(symbols)} symboles")

    if not symbols:
        print("[ERREUR] Aucun symbole à scanner.")
        return 1

    # Limiter à 200 symboles max pour les performances
    if len(symbols) > 200:
        print(f"  Limité à 200 symboles (sur {len(symbols)} disponibles)")
        symbols = symbols[:200]

    # ═════════════════════════════════════════════════════════════════════
    # ÉTAPE 3 : Scans ICT
    # ═════════════════════════════════════════════════════════════════════
    print()
    print("[3/4] Lancement des scans ICT...")

    # 3a. Asian ranges (toujours)
    print("  -> Scan asiatique (H1)...", end=" ", flush=True)
    t0 = time.time()
    asian_results, scanned = scan_market_watch_asian_ranges(
        timeframe="H1",
        symbols_override=symbols,
        save_to_db=True,
    )
    t_asian = time.time() - t0
    print(f"{len(asian_results)} ranges en {t_asian:.1f}s")

    # Extraire les setups directionnels
    setups = [
        r for r in asian_results
        if r.direction_target in ("AH", "AL", "BOTH")
        and r.direction_target_label not in ("−", "·")
    ]
    active_trades = [
        r for r in setups
        if r.trade_status == "Active" and r.trade_action in ("BUY", "SELL")
    ]
    print(f"     → {len(setups)} setups directionnels")
    print(f"     → {len(active_trades)} trades actifs")

    # 3b. Sweeps BSL/SSL (optionnel)
    sweeps = []
    if not args.skip_sweeps:
        print("  -> Scan sweeps BSL/SSL (M15)...", end=" ", flush=True)
        t0 = time.time()
        max_sweep_syms = min(len(symbols), 60)
        sweeps, _ = scan_market_watch_for_sweeps(
            timeframe="M15",
            symbols_override=symbols[:max_sweep_syms],
            save_to_db=True,
        )
        t_sweeps = time.time() - t0
        bsl = sum(1 for s in sweeps if s.sweep_label == "BSL")
        ssl = sum(1 for s in sweeps if s.sweep_label == "SSL")
        print(f"{len(sweeps)} sweeps ({bsl} BSL, {ssl} SSL) en {t_sweeps:.1f}s")
    else:
        print("  -> Scan sweeps : désactivé (--skip-sweeps)")

    # 3c. Niveaux daily/weekly (optionnel)
    levels = []
    if not args.skip_levels:
        print("  -> Scan niveaux daily/weekly...", end=" ", flush=True)
        t0 = time.time()
        max_level_syms = min(len(symbols), 60)
        levels, _ = scan_market_watch_levels(
            level_type="all",
            symbols_override=symbols[:max_level_syms],
        )
        t_levels = time.time() - t0
        daily = sum(1 for l in levels if l.level_type == "daily")
        weekly = sum(1 for l in levels if l.level_type == "weekly")
        print(f"{len(levels)} niveaux ({daily} daily, {weekly} weekly) en {t_levels:.1f}s")
    else:
        print("  -> Scan niveaux : désactivé (--skip-levels)")

    print()

    # ═════════════════════════════════════════════════════════════════════
    # ÉTAPE 4 : Formatage + Analyse IA
    # ═════════════════════════════════════════════════════════════════════
    print("[4/4] Analyse IA via Gemini...")

    # Convertir en dicts pour le formatteur
    asian_dicts = asians_to_dicts(asian_results) if asian_results else []
    sweeps_dicts = events_to_dicts(sweeps) if sweeps else []
    levels_dicts = [
        {
            "symbol": r.symbol,
            "level_type": r.level_type,
            "level_high": r.level_high,
            "level_low": r.level_low,
            "current_price": r.current_price,
            "direction_target_label": r.direction_target_label,
            "high_swept": r.high_swept,
            "low_swept": r.low_swept,
        }
        for r in levels
    ] if levels else []
    setups_dicts = [
        {
            "symbol": r.symbol,
            "trade_action": r.trade_action or "-",
            "trade_status": r.trade_status or "-",
            "trade_entry": r.trade_entry,
            "trade_sl": r.trade_sl,
            "trade_tp1": r.trade_tp1,
            "trade_rr1": r.trade_rr1,
            "direction_target_label": r.direction_target_label or "-",
            "asian_high": r.asian_high,
            "asian_low": r.asian_low,
            "asian_high_swept": r.asian_high_swept,
            "asian_low_swept": r.asian_low_swept,
            "current_price": r.current_price,
            "fib_label": r.fib_label or "-",
        }
        for r in setups
    ] if setups else []

    prompt = format_market_prompt(
        asian_results=asian_dicts,
        sweeps=sweeps_dicts,
        levels=levels_dicts,
        setups=setups_dicts,
        account_info=account_info,
    )

    print(f"  Prompt : {len(prompt)} caractères")
    print(f"  " + "-" * 60)

    analyst = GeminiAnalyst(api_key=GEMINI_API_KEY)
    analysis = analyst.analyze(prompt)

    if analysis:
        print(f"  " + "-" * 60)
        print(f"\n  Analyse reçue : {len(analysis)} caractères\n")

        # Afficher un aperçu
        preview = analysis[:1500]
        print(preview)
        if len(analysis) > 1500:
            print(f"\n  ... ({len(analysis) - 1500} caractères supplémentaires)")

        # Sauvegarder
        path = save_analysis(analysis, args.output_dir)
        print(f"\n  [OK] Analyse sauvegardée : {path}")
        print(f"  [OK] Pour relire : type {path}")
        return 0
    else:
        print(f"\n  [ERREUR] L'analyse Gemini a echoue.")
        print()
        print("  Causes possibles :")
        print("  1. Cle API Gemini invalide ou suspendue → nouvelle cle sur")
        print("     https://aistudio.google.com/apikey puis mets-la dans le .env")
        print("  2. Quota journalier depasse (1500 requetes/jour)")
        print("  3. Probleme de connexion internet")
        print("  4. SDK google-genai non installe → pip install google-genai")
        return 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    try:
        exit_code = main()
    except KeyboardInterrupt:
        print("\n\n[STOP] Interrompu par l'utilisateur.")
        exit_code = 130
    except Exception as e:
        print(f"\n[ERREUR] Exception non gérée : {e}")
        import traceback
        traceback.print_exc()
        exit_code = 2
    finally:
        # Assurer la déconnexion MT5 propre
        try:
            import MetaTrader5 as mt5
            mt5.shutdown()
        except Exception:
            pass

    sys.exit(exit_code)
