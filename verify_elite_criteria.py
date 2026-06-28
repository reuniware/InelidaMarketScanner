"""
verify_elite_criteria.py
========================
Analyse TOUS les rapports PDF disponibles pour verifier les criteres
du filtre ELITE (fenetre 09:00-10:30 UTC, type d'instrument, RR >= 0.5,
spread < 0.10%).

Usage:
    python verify_elite_criteria.py
"""

import os
import re
import sys
from datetime import datetime, timezone
from collections import Counter, defaultdict

# Forcer UTF-8 sur Windows
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    from PyPDF2 import PdfReader
except ImportError:
    print("[ERREUR] PyPDF2 est requis. Installe avec: pip install PyPDF2")
    sys.exit(1)


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
    """Classe un symbole par type d'instrument pour le filtre ELITE."""
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
REPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")


def extract_scan_timestamp(text: str):
    """Extrait le timestamp UTC du scan depuis le texte du PDF."""
    for line in text.split("\n"):
        m = re.search(r'Heure UTC[\s:]+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})', line)
        if m:
            try:
                return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    for line in text.split("\n"):
        m = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+UTC', line)
        if m:
            try:
                return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def parse_rr(rr_str: str) -> float:
    """Parse une chaine RR comme '1.5x' ou '0.4x' en float."""
    rr_str = rr_str.strip()
    if rr_str in ('-', chr(151), '', '_________'):
        return 0.0
    rr_str = rr_str.replace(',', '.').replace('x', '').replace('X', '')
    try:
        return float(rr_str)
    except ValueError:
        return 0.0


def parse_spread(spread_str: str):
    """Parse une chaine spread comme '0.018%' en float (pourcentage)."""
    s = spread_str.strip()
    if s in ('-', chr(151), '', '_________'):
        return None
    s = s.replace(',', '.').replace('%', '').strip()
    try:
        return float(s)
    except ValueError:
        return None


def extract_trades_from_pdf(pdf_path: str) -> list:
    """Extrait tous les trades d'un rapport PDF."""
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
    n_cols = 0  # nombre de colonnes detectees

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Detection de l'en-tete du tableau
        if not in_tracking:
            words = set(stripped.split())
            if header_tokens.issubset(words):
                in_tracking = True
                # Compter le nombre de colonnes
                header_parts = stripped.split()
                n_cols = len([p for p in header_parts if p.strip()])
                continue

        if not in_tracking:
            continue

        # Fin de section
        if stripped.startswith("*"):
            if "GAGN" in stripped or "PERDU" in stripped or "remplir" in stripped.lower():
                break

        # Ligne de trade
        if not stripped.startswith("Setup "):
            continue

        parts = stripped.split()
        if len(parts) < 7:
            continue

        # parts[0] = "Setup", parts[1] = SYMBOLE, parts[2] = ACTION
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

        # Spread detection: dans les nouveaux rapports, colonne apres RR
        # Format 1: Setup SYMBOLE ACTION ENTRY SL TP1 RR Spread ...
        # Format 2: Setup SYMBOLE ACTION ENTRY SL TP1 TP2 TP3 RR ...
        spread_pct = None
        if len(parts) >= 8:
            # Le spread est la colonne juste apres RR
            candidate = parts[7]
            if '%' in candidate:
                spread_pct = parse_spread(candidate)
            elif len(parts) >= 9 and '%' in parts[8]:
                spread_pct = parse_spread(parts[8])

        sym_type = classify_symbol(symbol)

        # Verification fenetre horaire
        time_ok = False
        if timestamp:
            h, m = timestamp.hour, timestamp.minute
            time_ok = (
                (h > ELITE_START_HOUR or (h == ELITE_START_HOUR and m >= ELITE_START_MIN))
                and (h < ELITE_END_HOUR or (h == ELITE_END_HOUR and m <= ELITE_END_MIN))
            )

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
            "scan_time": timestamp.strftime("%H:%M UTC") if timestamp else "?",
            "scan_hour": timestamp.hour if timestamp else None,
            "sym_type": sym_type,
            "criteria": {
                "time_ok": time_ok,
                "type_ok": type_ok,
                "rr_ok": rr_ok,
                "spread_ok": spread_ok,
            },
            "is_elite": elite,
        })

    return trades, timestamp


# ==================== Analyse principale ====================
def main():
    bar = "=" * 85
    print(bar)
    print("  VERIFICATION DES CRITERES ELITE - TOUS LES RAPPORTS DISPONIBLES")
    print(bar)
    print()

    all_pdfs = sorted(
        [f for f in os.listdir(REPORTS_DIR)
         if f.endswith('.pdf') and f.startswith('inelida_report')]
    )

    print(f"  Rapports trouves : {len(all_pdfs)}")
    print()
    print(f"  {'Rapport':<50s} {'Heure':<12s} {'Trades'}")
    print("  " + "-" * 75)

    all_trades = []
    reports_without_trades = 0

    for pdf_name in all_pdfs:
        pdf_path = os.path.join(REPORTS_DIR, pdf_name)
        trades, ts = extract_trades_from_pdf(pdf_path)
        ts_label = ts.strftime("%H:%M UTC") if ts else "?heure?"
        if trades:
            print(f"  {pdf_name:<50s} {ts_label:<12s} {len(trades):>3d} trades")
            all_trades.extend(trades)
        else:
            print(f"  {pdf_name:<50s} {ts_label:<12s}   0 trades (pas de section TRADE TRACKING)")
            reports_without_trades += 1

    print()
    print(f"  Total rapports avec trades : {len(all_pdfs) - reports_without_trades}")
    print(f"  Total trades extraits      : {len(all_trades)}")
    print()

    if not all_trades:
        print("  [ERREUR] Aucun trade trouve dans les rapports.")
        return

    # ===== STATISTIQUES GLOBALES =====
    n_elite = sum(1 for t in all_trades if t["is_elite"])
    n_non_elite = len(all_trades) - n_elite
    trades_with_spread = [t for t in all_trades if t["spread_pct"] is not None]

    time_ok_count = sum(1 for t in all_trades if t["criteria"]["time_ok"])
    type_ok_count = sum(1 for t in all_trades if t["criteria"]["type_ok"])
    rr_ok_count = sum(1 for t in all_trades if t["criteria"]["rr_ok"])
    spread_ok_known = sum(1 for t in trades_with_spread if t["criteria"]["spread_ok"])

    print("  " + "-" * 75)
    print(f"  {'RESULTATS GLOBAUX':^75s}")
    print("  " + "-" * 75)
    print(f"  {'Critere':<40s} {'Pass':>8s} {'Total':>8s} {'%':>8s}")
    print("  " + "-" * 75)
    print(f"  {'Fenetre horaire (09:00-10:30 UTC)':<40s} {time_ok_count:>8d} {len(all_trades):>8d} {time_ok_count/len(all_trades)*100:>7.1f}%")
    print(f"  {'Type instrument (ELITE types)':<40s} {type_ok_count:>8d} {len(all_trades):>8d} {type_ok_count/len(all_trades)*100:>7.1f}%")
    print(f"  {'RR >= 0.5':<40s} {rr_ok_count:>8d} {len(all_trades):>8d} {rr_ok_count/len(all_trades)*100:>7.1f}%")

    if trades_with_spread:
        print(f"  {'Spread < 0.10%':<40s} {spread_ok_known:>8d} {len(trades_with_spread):>8d} {spread_ok_known/len(trades_with_spread)*100:>7.1f}%")
        print(f"  {'  (trades sans donnee spread: ' + str(len(all_trades)-len(trades_with_spread)) + ')':<40s}")
    else:
        print(f"  {'Spread < 0.10%':<40s} {'N/A':>8s} {'N/A':>8s} {'N/A':>8s}")
    print("  " + "-" * 75)
    print(f"  {'Filtre ELITE COMPLET':<40s} {n_elite:>8d} {len(all_trades):>8d} {n_elite/len(all_trades)*100:>7.1f}%")
    print("  " + "-" * 75)
    print()

    # ===== RAISONS D'ECHEC =====
    print("  " + "-" * 75)
    print(f"  {'RAISONS D ECHEC DU FILTRE ELITE':^75s}")
    print("  " + "-" * 75)

    failure_reasons = Counter()
    for t in all_trades:
        if not t["is_elite"]:
            reasons = []
            if not t["criteria"]["time_ok"]:
                reasons.append("hors fenetre")
            if not t["criteria"]["type_ok"]:
                reasons.append("mauvais type")
            if not t["criteria"]["rr_ok"]:
                reasons.append("RR trop bas")
            if not t["criteria"]["spread_ok"] and t["spread_pct"] is not None:
                reasons.append("spread trop large")
            failure_reasons[" + ".join(reasons)] += 1

    for reason, count in failure_reasons.most_common():
        pct = count / n_non_elite * 100 if n_non_elite > 0 else 0
        print(f"  {reason:<50s} {count:>4d} trades ({pct:>5.1f}%)")
    print()

    # ===== PAR TYPE D'INSTRUMENT =====
    print("  " + "-" * 75)
    print(f"  {'REPARTITION PAR TYPE D INSTRUMENT':^75s}")
    print("  " + "-" * 75)
    print(f"  {'Type':<20s} {'Total':>7s} {'ELITE':>8s} {'% ELITE':>8s}")
    print("  " + "-" * 75)

    types = Counter(t["sym_type"] for t in all_trades)
    for tname in ["FOREX_USD", "FOREX_CROSS", "INDEX", "METAL", "FOREX_JPY", "OTHER"]:
        if types[tname] == 0:
            continue
        elite_in_type = sum(1 for t in all_trades if t["sym_type"] == tname and t["is_elite"])
        print(f"  {tname:<20s} {types[tname]:>7d} {elite_in_type:>8d} "
              f"{elite_in_type/types[tname]*100:>7.1f}%")
    print()

    # ===== PAR RAPPORT =====
    print("  " + "-" * 75)
    print(f"  {'DETAIL PAR RAPPORT':^75s}")
    print("  " + "-" * 75)
    print(f"  {'Rapport':<50s} {'Heure':<10s} {'Tr':>4s} {'EL':>4s} {'%':>5s}")
    print("  " + "-" * 75)

    reports_data = defaultdict(lambda: {"trades": 0, "elite": 0, "time": "?"})
    for t in all_trades:
        r = t["report"]
        reports_data[r]["trades"] += 1
        reports_data[r]["time"] = t["scan_time"]
        if t["is_elite"]:
            reports_data[r]["elite"] += 1

    for rname in sorted(reports_data.keys()):
        d = reports_data[rname]
        pct = d["elite"] / d["trades"] * 100 if d["trades"] > 0 else 0
        print(f"  {rname:<50s} {d['time']:<10s} {d['trades']:>4d} {d['elite']:>4d} {pct:>4.0f}%")
    print()

    # ===== DISTRIBUTION DES RR =====
    print("  " + "-" * 75)
    print(f"  {'DISTRIBUTION DES RR':^75s}")
    print("  " + "-" * 75)

    rr_buckets = Counter()
    for t in all_trades:
        rr = t["rr"]
        if rr == 0:
            rr_buckets["0.0 (pas de RR)"] += 1
        elif rr < 0.5:
            rr_buckets["0.01 - 0.49"] += 1
        elif rr < 1.0:
            rr_buckets["0.50 - 0.99"] += 1
        elif rr < 2.0:
            rr_buckets["1.00 - 1.99"] += 1
        elif rr < 3.0:
            rr_buckets["2.00 - 2.99"] += 1
        else:
            rr_buckets["3.00+"] += 1

    for bucket in ["0.0 (pas de RR)", "0.01 - 0.49", "0.50 - 0.99", "1.00 - 1.99", "2.00 - 2.99", "3.00+"]:
        if rr_buckets[bucket] > 0:
            print(f"  {bucket:<20s} {rr_buckets[bucket]:>4d} trades ({rr_buckets[bucket]/len(all_trades)*100:>5.1f}%)")
    print()

    # ===== DISTRIBUTION DES SPREADS =====
    if trades_with_spread:
        print("  " + "-" * 75)
        print(f"  {'DISTRIBUTION DES SPREADS':^75s}")
        print("  " + "-" * 75)

        spread_buckets = Counter()
        for t in trades_with_spread:
            s = t["spread_pct"]
            if s < 0.01:
                spread_buckets["< 0.01%"] += 1
            elif s < 0.05:
                spread_buckets["0.01 - 0.05%"] += 1
            elif s < 0.10:
                spread_buckets["0.05 - 0.10%"] += 1
            elif s < 0.50:
                spread_buckets["0.10 - 0.50%"] += 1
            elif s < 1.0:
                spread_buckets["0.50 - 1.0%"] += 1
            else:
                spread_buckets["1.0%+"] += 1

        for bucket in ["< 0.01%", "0.01 - 0.05%", "0.05 - 0.10%",
                       "0.10 - 0.50%", "0.50 - 1.0%", "1.0%+"]:
            if spread_buckets[bucket] > 0:
                print(f"  {bucket:<20s} {spread_buckets[bucket]:>4d} trades ({spread_buckets[bucket]/len(trades_with_spread)*100:>5.1f}%)")
        print()

    # ===== DISTRIBUTION PAR HEURE =====
    print("  " + "-" * 75)
    print(f"  {'DISTRIBUTION PAR TRANCHE HORAIRE DU SCAN':^75s}")
    print("  " + "-" * 75)
    print(f"  {'Tranche':<20s} {'Rapports':>9s} {'Trades':>8s} {'ELITE':>8s}")
    print("  " + "-" * 75)

    reports_by_hour = defaultdict(lambda: {"reports": set(), "trades": 0, "elite": 0})
    for t in all_trades:
        hour = t["scan_hour"]
        if hour is None:
            continue
        bucket = f"{hour:02d}:00-{hour:02d}:59"
        reports_by_hour[bucket]["reports"].add(t["report"])
        reports_by_hour[bucket]["trades"] += 1
        if t["is_elite"]:
            reports_by_hour[bucket]["elite"] += 1

    for bucket in sorted(reports_by_hour.keys()):
        d = reports_by_hour[bucket]
        print(f"  {bucket:<20s} {len(d['reports']):>9d} {d['trades']:>8d} {d['elite']:>8d}")
    print()

    # ===== LISTE DES TRADES ELITE =====
    print("  " + "-" * 75)
    print(f"  {'LISTE DES TRADES ELITE':^75s}")
    print("  " + "-" * 75)
    print(f"  {'Rapport':<30s} {'Heure':<10s} {'Symbole':<16s} {'Action':>5s} {'RR':>5s} {'Spread':>7s}")
    print("  " + "-" * 75)

    elite_trades = sorted([t for t in all_trades if t["is_elite"]],
                          key=lambda t: (t["report"], t["symbol"]))
    for t in elite_trades:
        spread_s = f"{t['spread_pct']:.3f}%" if t['spread_pct'] is not None else "N/A"
        print(f"  {t['report']:<30s} {t['scan_time']:<10s} {t['symbol']:<16s} {t['action']:>5s} "
              f"{t['rr']:>4.1f}x {spread_s:>7s}")
    print()


if __name__ == "__main__":
    main()
