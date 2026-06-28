"""
Backtest automatique des trades depuis un rapport PDF Inelida.
Lit le PDF via PyPDF2, extrait les trades de la section TRADE TRACKING,
puis les simule contre les donnees MT5 reelles posterieures.

Usage:
    python backtest_report_trades.py --pdf reports/inelida_report_2026-06-19.pdf
    python backtest_report_trades.py --pdf reports/inelida_report_2026-06-23.pdf
"""
import sys, os, re, time, argparse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import MetaTrader5 as mt5

UTC = timezone.utc

# Répertoire par défaut des rapports PDF
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_DIR, "reports")

# ─── Extraction des trades depuis le PDF ────────────────────────────────

def extract_date_from_filename(pdf_path: str) -> str:
    """Extrait YYYY-MM-DD du nom de fichier (ex: inelida_report_2026-06-23.pdf)."""
    basename = os.path.basename(pdf_path)
    match = re.search(r'(\d{4}-\d{2}-\d{2})', basename)
    if match:
        return match.group(1)
    # Fallback : date du fichier
    return datetime.fromtimestamp(os.path.getmtime(pdf_path), UTC).strftime("%Y-%m-%d")


def extract_scan_timestamp_from_text(full_text: str):
    """Extrait l'heure UTC du scan depuis le texte complet du PDF.

    Cherche une ligne du type : Heure UTC: 2026-06-23 22:09:37 UTC
    Retourne un datetime UTC, ou None si pas trouve.
    """
    for line in full_text.split("\n"):
        # Accepter avec ou sans deux-points : "Heure UTC: 2026..." ou "Heure UTC   2026..."
        m = re.search(r'Heure UTC[:\s]+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})', line)
        if m:
            try:
                return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
            except ValueError:
                continue
    # Fallback : chercher "Genere le YYYY-MM-DD HH:MM:SS UTC" dans le pied de page
    for line in full_text.split("\n"):
        m = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+UTC', line)
        if m:
            try:
                return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
            except ValueError:
                continue
    return None


def extract_broker_from_pdf(pdf_path: str) -> dict:
    """Extrait le broker et le serveur depuis la page de garde du PDF.

    Cherche les lignes :
        Broker : FTMO Global Markets MT5 Terminal
        Compte : 541320891 @ FTMO-Server4

    Returns:
        dict with keys 'broker' and 'server' (strings, or None if not found).
    """
    try:
        from PyPDF2 import PdfReader
    except ImportError:
        return {"broker": None, "server": None}

    if not os.path.exists(pdf_path):
        return {"broker": None, "server": None}

    reader = PdfReader(pdf_path)
    full_text = ""
    # Lire seulement les 2 premieres pages (page de garde + debut)
    for page in reader.pages[:2]:
        t = page.extract_text()
        if t:
            full_text += t + "\n"

    broker = None
    server = None

    for line in full_text.split("\n"):
        # "Broker : FTMO Global Markets MT5 Terminal"
        m = re.search(r'Broker\s*:\s*(.+)', line, re.IGNORECASE)
        if m:
            broker = m.group(1).strip()
        # "Compte : 541320891 @ FTMO-Server4"
        m = re.search(r'Compte\s*:.*@\s*(.+)', line, re.IGNORECASE)
        if m:
            server = m.group(1).strip()

    return {"broker": broker, "server": server}


def extract_trades_from_pdf(pdf_path: str) -> list:
    """Extrait les trades de la section TRADE TRACKING du PDF.

    Format attendu par ligne :
        Source Symbole Action Entry SL TP1 RR _________ _________

    Returns:
        Liste de dicts avec symbol, dir (BUY/SELL), entry, sl, tp, date.
    """
    try:
        from PyPDF2 import PdfReader
    except ImportError:
        print("[ERREUR] PyPDF2 non installe -> pip install PyPDF2")
        return []

    if not os.path.exists(pdf_path):
        print(f"[ERREUR] Fichier introuvable: {pdf_path}")
        return []

    reader = PdfReader(pdf_path)
    full_text = ""
    for page in reader.pages:
        t = page.extract_text()
        if t:
            full_text += t + "\n"

    # Trouver la section TRADE TRACKING via la ligne d'en-tete du tableau
    # "Source Symbole Action Entry SL TP1 RR" est stable et independant des accents
    lines = full_text.split("\n")
    in_tracking = False
    date_str = extract_date_from_filename(pdf_path)
    trades = []

    # Mots-cles de la ligne d'en-tete (invariants, sans accents)
    HEADER_TOKENS = {"Source", "Symbole", "Action", "Entry", "SL", "TP1"}

    for line in lines:
        stripped = line.strip()

        # Detection du debut: ligne d'en-tete du tableau
        if not in_tracking:
            words = set(stripped.split())
            if HEADER_TOKENS.issubset(words):
                in_tracking = True
                continue

        if not in_tracking:
            continue

        # Detection de la fin: ligne d'asterisque avec GAGN ou PERDU (invariants)
        if stripped.startswith("*") and ("GAGN" in stripped or "PERDU" in stripped):
            break  # fin de section, on arrete tout

        # Ignorer les lignes qui ne sont pas des trades
        if not stripped.startswith("Setup "):
            continue

        # Parser la ligne de trade : Setup SYMBOLE ACTION ENTRY SL TP1 RR ____ ____
        # Ex: "Setup ALGUSD BUY 0.09590 0.08806 0.10002 0.5x _________ _________"
        # ou  "Setup DXY.cash BUY 101.3850 100.9333 101.2241 - _________ _________"
        parts = stripped.split()
        if len(parts) < 7:
            continue

        # parts[0] = "Setup"
        # parts[1] = SYMBOLE
        # parts[2] = ACTION (BUY/SELL)
        # parts[3] = ENTRY
        # parts[4] = SL
        # parts[5] = TP1
        # parts[6] = RR (peut etre "-" ou "0.0x" ou "1.2x")

        source = parts[0]
        symbol = parts[1]
        action = parts[2].upper()

        if action not in ("BUY", "SELL"):
            # Cas ou le symbole a un espace (ex: "NATGAS.cash" -> 2 mots)
            # Verifier si parts[2] ressemble a un float (entry) -> source=parts[0], symbol=parts[1..n-5], action=BUY/SELL, ...
            continue

        try:
            entry = float(parts[3])
            sl = float(parts[4])
            tp = float(parts[5])
        except (ValueError, IndexError):
            continue

        # RR est optionnel, on ne le parse pas pour le backtest
        trades.append({
            "symbol": symbol,
            "dir": action,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "date": date_str,
        })

    # Extraire le timestamp du scan depuis le texte complet
    scan_ts = extract_scan_timestamp_from_text(full_text)
    scan_epoch = int(scan_ts.timestamp()) if scan_ts else 0

    if scan_ts is None:
        print("[AVERTISSEMENT] Timestamp 'Heure UTC' introuvable dans le PDF."
              " Le backtest utilisera minuit UTC (barres pre-scan incluses).")
    else:
        print(f"  Scan a  : {scan_ts.strftime('%Y-%m-%d %H:%M UTC')}")

    # Injecter scan_epoch dans chaque trade
    for t in trades:
        t["scan_epoch"] = scan_epoch

    return trades


# ─── Backtest ────────────────────────────────────────────────────────────

def bars_to_dicts(rates_raw):
    return [{"time": int(r[0]), "open": float(r[1]), "high": float(r[2]),
             "low": float(r[3]), "close": float(r[4])} for r in rates_raw]


def backtest_trade(trade, bars):
    """Simule le trade sur les barres M1/M5/M15/H1 dispo. Retourne outcome.

    Verifie CHAQUE barre dans l'ordre chronologique. Pour un BUY :
    si low <= SL -> PERDU. Si high >= TP -> GAGNE.
    L'ordre importe : la première condition remplie dans le temps détermine le résultat.
    Avec M1, la probabilité que SL et TP soient touchés dans la même minute
    est très faible -> précision maximale.
    """
    entry = trade["entry"]
    sl = trade["sl"]
    tp = trade["tp"]
    is_buy = trade["dir"] == "BUY"
    report_date = trade.get("date", "2026-06-19")

    # Barres APRES le scan uniquement (pas de midnight UTC qui inclut des
    # barres avant le scan). Si scan_epoch absent, fallback sur minuit.
    start_epoch = trade.get("scan_epoch", 0)
    if start_epoch == 0:
        try:
            start_dt = datetime.strptime(report_date, "%Y-%m-%d").replace(tzinfo=UTC)
            start_epoch = int(start_dt.timestamp())
        except ValueError:
            start_epoch = 0

    post_bars = [b for b in bars if b["time"] >= start_epoch]
    if not post_bars:
        post_bars = bars[-500:]  # fallback

    for b in post_bars:
        if is_buy:
            if b["low"] <= sl:
                return "PERDU (SL touche)", b["time"], sl
            if b["high"] >= tp:
                return "GAGNE (TP touche)", b["time"], tp
        else:
            if b["high"] >= sl:
                return "PERDU (SL touche)", b["time"], sl
            if b["low"] <= tp:
                return "GAGNE (TP touche)", b["time"], tp

    # Ni SL ni TP touche
    last = post_bars[-1] if post_bars else bars[-1]
    last_price = last["close"]
    if is_buy:
        pnl = last_price - entry
        status = f"OUVERT (en gain +{pnl:.4f})" if pnl > 0 else f"OUVERT (en perte {pnl:.4f})"
    else:
        pnl = entry - last_price
        status = f"OUVERT (en gain +{pnl:.4f})" if pnl > 0 else f"OUVERT (en perte {pnl:.4f})"
    return status, last["time"], last_price


# ─── Main ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Backtest automatique des trades depuis un rapport PDF Inelida"
    )
    parser.add_argument("--pdf", default=None,
                       help="Chemin vers le rapport PDF (ex: reports/inelida_report_2026-06-23.pdf). "
                            "Si non specifie, utilise le dernier PDF du repertoire reports/.")
    args = parser.parse_args()

    pdf_path = args.pdf
    if pdf_path is None:
        # Chercher le PDF le plus recent dans reports/
        if not os.path.isdir(REPORTS_DIR):
            print(f"[ERREUR] Le dossier reports/ n'existe pas. Creez-le ou specifiez --pdf.")
            return 1
        pdf_files = sorted(
            [f for f in os.listdir(REPORTS_DIR) if f.endswith('.pdf') and f.startswith('inelida_report')],
            reverse=True
        )
        if pdf_files:
            pdf_path = os.path.join(REPORTS_DIR, pdf_files[0])
            print(f"[INFO] Aucun --pdf fourni, utilisation du dernier rapport : {pdf_files[0]}")
        else:
            print("[ERREUR] Aucun PDF trouve dans reports/. Specifiez --pdf.")
            return 1
    report_date = extract_date_from_filename(pdf_path)

    # ── Extraction ──────────────────────────────────────────────────────
    print("=" * 85)
    print(f"  BACKTEST AUTOMATIQUE DEPUIS PDF")
    print(f"  Rapport : {os.path.basename(pdf_path)}")
    print(f"  Date    : {report_date}")
    print("=" * 85)
    print()

    print("[1/3] Extraction des trades depuis le PDF...")
    trades = extract_trades_from_pdf(pdf_path)

    if not trades:
        print("[ERREUR] Aucun trade trouve dans le PDF.")
        print("  Verifie que le PDF contient une section TRADE TRACKING.")
        print("  Format attendu par ligne : Setup SYMBOLE ACTION ENTRY SL TP1 RR ____ ____")
        return 1

    print(f"  {len(trades)} trades extraits :")
    for t in trades:
        print(f"    {t['symbol']:<14} {t['dir']:>4}  Entry={t['entry']:<10} SL={t['sl']:<10} TP={t['tp']:<10}")
    print()

    # ── Vérification broker PDF vs MT5 ─────────────────────────────────
    print("[2/3] Verification du broker...")
    pdf_info = extract_broker_from_pdf(pdf_path)

    if not mt5.initialize():
        print("[ERREUR] Connexion MT5 - verifie que MT5 est ouvert et connecte.")
        return 1

    ti = mt5.terminal_info()
    ai = mt5.account_info()

    if ti:
        print(f"  Terminal MT5 : {ti.name} (build {ti.build})")
    if ai:
        print(f"  Compte MT5   : {ai.login} @ {ai.server}")

    # Afficher les infos du PDF
    print()
    if pdf_info["broker"] or pdf_info["server"]:
        print(f"  Rapport PDF  :", end="")
        if pdf_info["broker"]:
            print(f" Broker={pdf_info['broker']}", end="")
        if pdf_info["server"]:
            print(f" Serveur={pdf_info['server']}", end="")
        print()

    # Comparaison serveur (ground truth, le nom du terminal peut rester identique
    # meme si on change de compte dans le meme terminal binaire)
    if pdf_info["server"] and ai:
        if pdf_info["server"] != ai.server:
            print()
            print("  " + "=" * 74)
            print("  /!\ BROKER MISMATCH DETECTE !")
            print(f"  Rapport genere sur : {pdf_info['server']}")
            print(f"  Compte actuel      : {ai.server}")
            print("  => Les donnees de prix peuvent DIFFERER entre brokers !")
            print("  => Le backtest peut etre NON FIABLE.")
            print("  " + "=" * 74)
        else:
            print(f"  [OK] Broker identique : {pdf_info['server']}")
    print()

    # ── Backtest ─────────────────────────────────────────────────────────
    print(f"[3/3] Backtest de {len(trades)} trades...")
    print()

    won, lost, open_trades, indeterminate = 0, 0, 0, 0

    for i, t in enumerate(trades):
        sym = t["symbol"]
        print(f"[{i+1}/{len(trades)}] {sym:<14} {t['dir']:>4}  Entry={t['entry']:<10} ...", end=" ", flush=True)

        result = None
        # Granularité maximale : M1 d'abord (1 minute), puis M5, M15, H1 en fallback
        # Pour M1, on récupère jusqu'à 10000 barres (~7 jours) pour couvrir tout l'historique
        for tf_name, tf_const, n_bars in [
            ("M1", mt5.TIMEFRAME_M1, 10000),
            ("M5", mt5.TIMEFRAME_M5, 3000),
            ("M15", mt5.TIMEFRAME_M15, 1000),
            ("H1", mt5.TIMEFRAME_H1, 500),
        ]:
            try:
                rates = mt5.copy_rates_from_pos(sym, tf_const, 0, n_bars)
                if rates is not None and len(rates) > 0:
                    bars = bars_to_dicts(rates)
                    result = backtest_trade(t, bars)
                    if "OUVERT" not in result[0]:
                        print(f">> {result[0]} [{tf_name}] @ {datetime.fromtimestamp(result[1], UTC).strftime('%Y-%m-%d %H:%M UTC')}")
                        break
            except Exception:
                continue

        if result is None:
            print(">> INDETERMINE (pas de donnees)")
            indeterminate += 1
        elif "GAGNE" in result[0]:
            won += 1
        elif "PERDU" in result[0]:
            lost += 1
        else:
            print(f">> {result[0]} @ {datetime.fromtimestamp(result[1], UTC).strftime('%Y-%m-%d %H:%M UTC')}")
            open_trades += 1

        time.sleep(0.1)

    print()
    print("=" * 85)
    n_closed = won + lost
    winrate = (won / n_closed * 100) if n_closed > 0 else 0
    print(f"  RESULTATS : {won} GAGNES | {lost} PERDUS | {open_trades} OUVERTS | {indeterminate} INDETERMINES")
    if n_closed > 0:
        print(f"  WINRATE sur trades clotures : {winrate:.1f}% ({won}/{n_closed})")
    print("=" * 85)

    mt5.shutdown()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[STOP]")
        mt5.shutdown()
        sys.exit(130)
    except Exception as e:
        print(f"\n[ERREUR] {e}")
        import traceback; traceback.print_exc()
        mt5.shutdown()
        sys.exit(1)
