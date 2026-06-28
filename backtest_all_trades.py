"""
backtest_all_trades.py
=======================
BACKTEST MASIF de TOUS les trades extraits de TOUS les rapports PDF Inelida.
Utilise MetaTrader 5 pour télécharger les barres M1 historiques et déterminer
si chaque trade a été GAGNÉ (TP touché avant SL) ou PERDU (SL touché avant TP).

Usage:
    python backtest_all_trades.py            # backtest complet
    python backtest_all_trades.py --limit 50 # test rapide (50 premiers trades)
"""

import os
import re
import sys
import time
import json
import argparse
from datetime import datetime, timezone
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from PyPDF2 import PdfReader
except ImportError:
    print("[ERREUR] PyPDF2 est requis. pip install PyPDF2")
    sys.exit(1)

import MetaTrader5 as mt5

UTC = timezone.utc
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_DIR, "reports")
RESULTS_PATH = os.path.join(PROJECT_DIR, "reports", "backtest_all_results.json")

# ==================== Constantes ELITE ====================
ELITE_START_HOUR = 9
ELITE_START_MIN = 0
ELITE_END_HOUR = 10
ELITE_END_MIN = 30
ELITE_MIN_RR = 0.5
ELITE_MAX_SPREAD_PCT = 0.10
ELITE_ALLOWED_TYPES = {"FOREX_USD", "INDEX", "METAL", "FOREX_CROSS"}


# ==================== Classification des symboles ====================
def classify_symbol(sym: str) -> str:
    sym_u = sym.upper()
    if sym in ('XAUUSD', 'XAGUSD', 'XAUAUD', 'XAGAUD'):
        return 'METAL'
    if sym_u.endswith('USD') and sym not in ('XAUUSD', 'XAGUSD'):
        return 'FOREX_USD'
    if 'JPY' in sym_u:
        return 'FOREX_JPY'
    if sym_u.startswith('USD'):
        return 'FOREX_USD'
    if any(c in sym for c in ('EUR', 'GBP', 'CAD', 'AUD', 'NZD', 'CHF',
                                'NOK', 'SEK', 'PLN', 'CZK', 'MXN', 'SGD', 'ZAR', 'HUF')):
        return 'FOREX_CROSS'
    if '.cash' in sym or sym in ('DXY.cash', 'GDAXI'):
        return 'INDEX'
    return 'OTHER'


# ==================== Extraction depuis les PDFs ====================
def extract_scan_timestamp(text: str):
    for line in text.split("\n"):
        m = re.search(r'Heure UTC[\s:]+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})', line)
        if m:
            try:
                return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
            except ValueError:
                continue
    for line in text.split("\n"):
        m = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+UTC', line)
        if m:
            try:
                return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
            except ValueError:
                continue
    return None


def parse_rr(rr_str: str) -> float:
    rr_str = rr_str.strip()
    if rr_str in ('-', chr(151), '', '_________'):
        return 0.0
    rr_str = rr_str.replace(',', '.').replace('x', '').replace('X', '')
    try:
        return float(rr_str)
    except ValueError:
        return 0.0


def parse_spread(spread_str: str):
    s = spread_str.strip()
    if s in ('-', chr(151), '', '_________'):
        return None
    s = s.replace(',', '.').replace('%', '').strip()
    try:
        return float(s)
    except ValueError:
        return None


def extract_trades_from_pdf(pdf_path: str) -> tuple:
    """Extrait tous les trades d'un rapport PDF.
    Retourne (liste_de_trades, timestamp_scan)."""
    reader = PdfReader(pdf_path)
    full_text = ""
    for page in reader.pages:
        t = page.extract_text()
        if t:
            full_text += t + "\n"

    timestamp = extract_scan_timestamp(full_text)
    lines = full_text.split("\n")

    in_tracking = False
    header_tokens = {"Source", "Symbole", "Action", "Entry", "SL", "TP1"}
    trades = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if not in_tracking:
            words = set(stripped.split())
            if header_tokens.issubset(words):
                in_tracking = True
                continue

        if not in_tracking:
            continue

        if stripped.startswith("*"):
            if "GAGN" in stripped or "PERDU" in stripped or "remplir" in stripped.lower():
                break

        if not stripped.startswith("Setup "):
            continue

        parts = stripped.split()
        if len(parts) < 7:
            continue

        symbol = parts[1]
        action = parts[2].upper()
        if action not in ("BUY", "SELL"):
            continue

        try:
            entry = float(parts[3])
            sl = float(parts[4])
            tp1 = float(parts[5])
        except (ValueError, IndexError):
            continue

        rr_str = parts[6] if len(parts) > 6 else "-"
        rr = parse_rr(rr_str)

        spread_pct = None
        if len(parts) >= 8:
            candidate = parts[7]
            if '%' in candidate:
                spread_pct = parse_spread(candidate)
            elif len(parts) >= 9 and '%' in parts[8]:
                spread_pct = parse_spread(parts[8])

        sym_type = classify_symbol(symbol)

        # Verification ELITE
        time_ok = False
        if timestamp:
            h, m = timestamp.hour, timestamp.minute
            time_ok = ((h > ELITE_START_HOUR or (h == ELITE_START_HOUR and m >= ELITE_START_MIN))
                       and (h < ELITE_END_HOUR or (h == ELITE_END_HOUR and m <= ELITE_END_MIN)))
        type_ok = sym_type in ELITE_ALLOWED_TYPES
        rr_ok = rr >= ELITE_MIN_RR
        spread_ok = spread_pct is None or spread_pct < ELITE_MAX_SPREAD_PCT
        elite = time_ok and type_ok and rr_ok and spread_ok

        trades.append({
            "report": os.path.basename(pdf_path),
            "symbol": symbol,
            "action": action,
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "rr": rr,
            "spread_pct": spread_pct,
            "scan_time": timestamp.strftime("%Y-%m-%d %H:%M:%S") + " UTC" if timestamp else "?",
            "scan_epoch": int(timestamp.timestamp()) if timestamp else 0,
            "scan_hour": timestamp.hour if timestamp else None,
            "sym_type": sym_type,
            "is_elite": elite,
        })

    return trades, timestamp


# ==================== Backtest ====================
def bars_to_dicts(rates_raw):
    return [{"time": int(r[0]), "open": float(r[1]), "high": float(r[2]),
             "low": float(r[3]), "close": float(r[4])} for r in rates_raw]


def backtest_trade(trade: dict, max_lookback_days: int = 30) -> dict:
    """Backtest un trade sur les barres M1.

    Returns:
        dict avec outcome, time_hit, price_hit, tf_used, etc.
    """
    symbol = trade["symbol"]
    entry = trade["entry"]
    sl = trade["sl"]
    tp = trade["tp1"]
    is_buy = trade["action"] == "BUY"
    scan_epoch = trade["scan_epoch"]
    action = trade["action"]

    result = {
        "symbol": symbol,
        "action": action,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "scan_epoch": scan_epoch,
        "outcome": "INDETERMINE",
        "outcome_detail": "",
        "time_hit": None,
        "price_hit": None,
        "tf_used": None,
        "bars_count": 0,
        "last_bar_time": None,
        "last_bar_close": None,
    }

    # Essayer M1 d'abord (precision max), puis M5, M15, H1 en fallback
    timeframes = [
        ("M1", mt5.TIMEFRAME_M1, 30000),   # ~21 jours
        ("M5", mt5.TIMEFRAME_M5, 10000),   # ~35 jours
        ("M15", mt5.TIMEFRAME_M15, 5000),  # ~52 jours
        ("H1", mt5.TIMEFRAME_H1, 1000),    # ~42 jours
    ]

    for tf_name, tf_const, n_bars in timeframes:
        try:
            rates = mt5.copy_rates_from_pos(symbol, tf_const, 0, n_bars)
            if rates is None or len(rates) == 0:
                continue

            bars = bars_to_dicts(rates)
            bars.sort(key=lambda b: b["time"])

            # Ne garder que les barres APRES le scan
            post_bars = [b for b in bars if b["time"] >= scan_epoch]
            if not post_bars:
                # Fallback: dernieres barres
                post_bars = bars[-500:]

            result["bars_count"] = len(post_bars)
            result["tf_used"] = tf_name

            for b in post_bars:
                if is_buy:
                    if b["low"] <= sl:
                        result["outcome"] = "PERDU"
                        result["outcome_detail"] = "SL touche"
                        result["time_hit"] = b["time"]
                        result["price_hit"] = sl
                        return result
                    if b["high"] >= tp:
                        result["outcome"] = "GAGNE"
                        result["outcome_detail"] = "TP touche"
                        result["time_hit"] = b["time"]
                        result["price_hit"] = tp
                        return result
                else:  # SELL
                    if b["high"] >= sl:
                        result["outcome"] = "PERDU"
                        result["outcome_detail"] = "SL touche"
                        result["time_hit"] = b["time"]
                        result["price_hit"] = sl
                        return result
                    if b["low"] <= tp:
                        result["outcome"] = "GAGNE"
                        result["outcome_detail"] = "TP touche"
                        result["time_hit"] = b["time"]
                        result["price_hit"] = tp
                        return result

            # Aucun SL/TP touche -> trade encore ouvert
            last = post_bars[-1]
            result["last_bar_time"] = last["time"]
            result["last_bar_close"] = last["close"]
            if is_buy:
                pnl_pct = (last["close"] - entry) / entry * 100
            else:
                pnl_pct = (entry - last["close"]) / entry * 100
            result["outcome"] = "OUVERT"
            result["outcome_detail"] = f"En gain +{pnl_pct:.2f}%" if pnl_pct > 0 else f"En perte {pnl_pct:.2f}%"
            return result

        except Exception as e:
            continue

    # Aucune donnee disponible
    result["outcome"] = "INDETERMINE"
    result["outcome_detail"] = "Pas de donnees MT5"
    return result


# ==================== Main ====================
def main():
    parser = argparse.ArgumentParser(description="Backtest massif de tous les trades")
    parser.add_argument("--limit", type=int, default=None,
                       help="Nombre max de trades a backtester (pour test)")
    parser.add_argument("--resume", action="store_true",
                       help="Reprendre un backtest interrompu (ne pas re-backtester les deja faits)")
    args = parser.parse_args()

    # Forcer UTF-8
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    bar = "=" * 90
    print(bar)
    print("  BACKTEST MASSIF - TOUS LES TRADES DE TOUS LES RAPPORTS PDF")
    print(bar)
    print()

    # ===== Connexion MT5 =====
    print("[1/5] Connexion MetaTrader 5...")
    if not mt5.initialize():
        print("  [ERREUR] Connexion MT5 impossible.")
        return 1

    ti = mt5.terminal_info()
    ai = mt5.account_info()
    print(f"  Terminal: {ti.name if ti else '?'} (build {ti.build if ti else '?'})")
    print(f"  Compte:   {ai.login if ai else '?'} @ {ai.server if ai else '?'}")
    print()

    # ===== Extraction de tous les trades =====
    print("[2/5] Extraction des trades depuis tous les PDFs...")

    # Charger les resultats existants si --resume
    existing_results = {}
    if args.resume and os.path.exists(RESULTS_PATH):
        with open(RESULTS_PATH, "r", encoding="utf-8") as f:
            existing_data = json.load(f)
        for t in existing_data.get("all_trades", []):
            key = f"{t['report']}_{t['symbol']}_{t['action']}_{t['entry']}"
            existing_results[key] = t
        print(f"  Resume: {len(existing_results)} trades deja backtestes (ignores).")

    all_pdfs = sorted(
        [f for f in os.listdir(REPORTS_DIR)
         if f.endswith('.pdf') and f.startswith('inelida_report')]
    )

    all_trades = []
    for pdf_name in all_pdfs:
        pdf_path = os.path.join(REPORTS_DIR, pdf_name)
        trades, ts = extract_trades_from_pdf(pdf_path)
        all_trades.extend(trades)
        ts_label = ts.strftime("%H:%M UTC") if ts else "?"
        if trades:
            print(f"  {pdf_name:<50s} {ts_label:<12s} {len(trades):>3d} trades")

    print(f"\n  Total: {len(all_trades)} trades extraits de {len(all_pdfs)} PDFs.")
    print()

    if args.limit:
        all_trades = all_trades[:args.limit]
        print(f"  [LIMITE] Backtest des {args.limit} premiers trades seulement.")
        print()

    # ===== Backtest =====
    print("[3/5] Backtest de tous les trades via MT5 (M1)...")
    print()

    results = []
    n_won = 0
    n_lost = 0
    n_open = 0
    n_indet = 0
    total_pnl_pct = 0.0
    closed_trades = 0

    for i, trade in enumerate(all_trades):
        key = f"{trade['report']}_{trade['symbol']}_{trade['action']}_{trade['entry']}"

        # Resume: deja backteste ?
        if args.resume and key in existing_results:
            r = existing_results[key]
            results.append(r)
            if r["outcome"] == "GAGNE":
                n_won += 1; closed_trades += 1
                total_pnl_pct += abs(r.get("pnl_pct", 1.0))
            elif r["outcome"] == "PERDU":
                n_lost += 1; closed_trades += 1
                total_pnl_pct -= 1.0
            elif r["outcome"] == "OUVERT":
                n_open += 1
            else:
                n_indet += 1

            if (i + 1) % 10 == 0 or i == 0:
                print(f"  [{i+1}/{len(all_trades)}] {trade['symbol']:<14s} {trade['action']:>4s} "
                      f"RR={trade['rr']:.1f}x -> {r['outcome']:<12s} [resume]")
            continue

        print(f"  [{i+1}/{len(all_trades)}] {trade['report'][:25]:<25s} {trade['symbol']:<14s} "
              f"{trade['action']:>4s} RR={trade['rr']:.1f}x ...", end=" ", flush=True)

        r = backtest_trade(trade)

        # Calcul P&L
        if r["outcome"] == "GAGNE":
            risk = abs(trade["entry"] - trade["sl"])
            reward = abs(trade["tp1"] - trade["entry"])
            if risk > 0:
                r["pnl_pct"] = reward / risk  # en unites de risque
            else:
                r["pnl_pct"] = 1.0
        elif r["outcome"] == "PERDU":
            r["pnl_pct"] = -1.0
        elif r["outcome"] == "OUVERT":
            if trade["action"] == "BUY":
                pnl = r["last_bar_close"] - trade["entry"]
            else:
                pnl = trade["entry"] - r["last_bar_close"]
            risk = abs(trade["entry"] - trade["sl"])
            r["pnl_pct"] = pnl / risk if risk > 0 else 0
        else:
            r["pnl_pct"] = 0.0

        # Copier les metadonnees du trade
        r["report"] = trade["report"]
        r["rr"] = trade["rr"]
        r["spread_pct"] = trade["spread_pct"]
        r["scan_time"] = trade["scan_time"]
        r["scan_hour"] = trade["scan_hour"]
        r["sym_type"] = trade["sym_type"]
        r["is_elite"] = trade["is_elite"]

        results.append(r)

        if r["outcome"] == "GAGNE":
            n_won += 1; closed_trades += 1
            total_pnl_pct += r["pnl_pct"]
            print(f"-> GAGNE! (P&L={r['pnl_pct']:.2f}R)")
        elif r["outcome"] == "PERDU":
            n_lost += 1; closed_trades += 1
            total_pnl_pct += r["pnl_pct"]
            print(f"-> PERDU! (P&L={r['pnl_pct']:.2f}R)")
        elif r["outcome"] == "OUVERT":
            n_open += 1
            print(f"-> OUVERT ({r['outcome_detail']})")
        else:
            n_indet += 1
            print(f"-> INDETERMINE ({r['outcome_detail']})")

        # Pause pour ne pas saturer MT5
        time.sleep(0.15)

    # ===== Compilation des resultats =====
    print()
    print("[4/5] Compilation des resultats...")

    output = {
        "meta": {
            "total_trades": len(all_trades),
            "backtested": len(results),
            "date": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
        },
        "summary": {
            "total": len(results),
            "gagne": n_won,
            "perdu": n_lost,
            "ouvert": n_open,
            "indetermine": n_indet,
            "closed": closed_trades,
            "winrate": round(n_won / closed_trades * 100, 1) if closed_trades > 0 else 0,
            "total_pnl_R": round(total_pnl_pct, 2),
            "avg_pnl_R": round(total_pnl_pct / closed_trades, 3) if closed_trades > 0 else 0,
            "profit_factor": round(abs(total_pnl_pct) / n_lost, 2) if n_lost > 0 and total_pnl_pct > 0 else 0,
        },
        "all_trades": results,
    }

    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)

    print(f"  Resultats sauvegardes: {RESULTS_PATH}")
    print()

    # ===== Affichage =====
    print("[5/5]", bar)
    print(f"  RESULTATS DU BACKTEST ({len(results)} trades)")
    print(bar)
    print(f"  GAGNES:     {n_won}")
    print(f"  PERDUS:     {n_lost}")
    print(f"  OUVERTS:    {n_open}")
    print(f"  INDETERM.:  {n_indet}")
    if closed_trades > 0:
        print(f"  WINRATE:    {n_won/closed_trades*100:.1f}% ({n_won}/{closed_trades})")
        print(f"  P&L TOTAL:  {total_pnl_pct:.2f}R")
        print(f"  P&L MOYEN:  {total_pnl_pct/closed_trades:.3f}R")
        print(f"  PROFIT FACTOR: {abs(total_pnl_pct)/n_lost:.2f}" if n_lost > 0 else "  PROFIT FACTOR: INF")
    print()

    # Stats ELITE
    elite_trades = [t for t in results if t["is_elite"]]
    elite_closed = [t for t in elite_trades if t["outcome"] in ("GAGNE", "PERDU")]
    elite_won = sum(1 for t in elite_closed if t["outcome"] == "GAGNE")

    print(f"  --- STATS ELITE (filtre actuel) ---")
    print(f"  Trades ELITE:     {len(elite_trades)}")
    print(f"  ELITE closed:     {len(elite_closed)}")
    if len(elite_closed) > 0:
        print(f"  ELITE winrate:    {elite_won/len(elite_closed)*100:.1f}% ({elite_won}/{len(elite_closed)})")
        elite_pnl = sum(t["pnl_pct"] for t in elite_closed if t["outcome"] == "GAGNE") - len([t for t in elite_closed if t["outcome"] == "PERDU"])
        print(f"  ELITE P&L total:  {elite_pnl:.2f}R")
        print(f"  ELITE P&L moyen:  {elite_pnl/len(elite_closed):.3f}R")
    print()

    # Stats NON-ELITE
    non_elite = [t for t in results if not t["is_elite"]]
    non_elite_closed = [t for t in non_elite if t["outcome"] in ("GAGNE", "PERDU")]
    non_elite_won = sum(1 for t in non_elite_closed if t["outcome"] == "GAGNE")

    print(f"  --- STATS NON-ELITE ---")
    print(f"  Trades:           {len(non_elite)}")
    print(f"  Closed:           {len(non_elite_closed)}")
    if len(non_elite_closed) > 0:
        print(f"  Winrate:          {non_elite_won/len(non_elite_closed)*100:.1f}% ({non_elite_won}/{len(non_elite_closed)})")
        non_elite_pnl = sum(t["pnl_pct"] for t in non_elite_closed if t["outcome"] == "GAGNE") - len([t for t in non_elite_closed if t["outcome"] == "PERDU"])
        print(f"  P&L total:        {non_elite_pnl:.2f}R")
        print(f"  P&L moyen:        {non_elite_pnl/len(non_elite_closed):.3f}R")
    print(bar)

    mt5.shutdown()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[STOP] Interrompu.")
        mt5.shutdown()
        sys.exit(130)
    except Exception as e:
        print(f"\n[ERREUR] {e}")
        import traceback; traceback.print_exc()
        mt5.shutdown()
        sys.exit(1)
