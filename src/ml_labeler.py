"""
ML Labeler — Génère un CSV de trades labellisés prêt pour l'entraînement XGBoost.

3 sources possibles :
  1. db     : Lit les trades CLOSED depuis la DB TradeTracker (pnl_pips → outcome)
  2. manual : Lit un CSV fourni par l'utilisateur (colonnes features + outcome)
  3. scan   : Lance un Diamond scan et sauvegarde les features pour labelling futur

Usage:
    # Depuis la DB (trades déjà fermés)
    python -m src.ml_labeler --source db --output data/trades_labeled.csv

    # Depuis un CSV manuel (ex: backtest exporté)
    python -m src.ml_labeler --source manual --input backtest_results.csv --output data/trades_labeled.csv

    # Scan live (features seulement, outcome vide — à remplir plus tard)
    python -m src.ml_labeler --source scan --symbols EURUSD --output data/features_unlabeled.csv

Format CSV généré :
    Chaque ligne = 1 trade. Colonnes = features numériques + colonne "outcome" (1=gagné, 0=perdu, vide=à remplir).
"""

import argparse
import csv
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger("MLLabeler")

UTC = timezone.utc


# ─── Feature extraction (DB mode) ──────────────────────────────────────────

def _safe_float(val, default: float = 0.0):
    """Convertit une valeur en float de manière sécurisée.
    Retourne default si la conversion échoue.
    """
    try:
        if val is None:
            return default
        return float(val)
    except (ValueError, TypeError):
        return default


def _bias_to_float(bias: str) -> float:
    """BULL=1.0, BEAR=-1.0, FLAT=0.0"""
    if bias == "BULL":
        return 1.0
    if bias == "BEAR":
        return -1.0
    return 0.0


def _quality_to_float(quality: str) -> float:
    """STRONG=2.0, GOOD=1.0, WAIT=0.0"""
    if quality == "STRONG":
        return 2.0
    if quality == "GOOD":
        return 1.0
    return 0.0


def _pip_factor(symbol: str) -> float:
    """Facteur de conversion pips selon le symbole."""
    sym_u = symbol.upper()
    if "XAUUSD" in sym_u:
        return 10.0
    if "JPY" in sym_u or "DXY" in sym_u:
        return 100.0
    if "XAG" in sym_u:
        return 500.0
    if ".cash" in sym_u.lower():
        return 1.0  # indices — 1 point = 1 unité
    return 10000.0


def extract_features_from_db_trade(trade: dict) -> Dict[str, float]:
    """Extrait un vecteur de features depuis un trade DB (diamond_trades row).

    Utilise les champs stockés dans la DB (~20 champs) + features dérivées.
    """
    sym = trade.get("symbol", "EURUSD")
    pf = _pip_factor(sym)
    price = _safe_float(trade.get("price", 0))
    sl = _safe_float(trade.get("sl", 0))
    tp = _safe_float(trade.get("tp", 0))
    kj_h4 = _safe_float(trade.get("kj_h4", 0))
    kj_d1 = _safe_float(trade.get("kj_d1", 0))

    feats: Dict[str, float] = {}

    # ── Scores et métadonnées ──
    feats["score"] = _safe_float(trade.get("score", 0))
    feats["max_score"] = _safe_float(trade.get("max_score", 12))
    feats["score_pct"] = feats["score"] / max(feats["max_score"], 1.0)
    feats["bias"] = _bias_to_float(trade.get("bias", "FLAT"))
    feats["quality"] = _quality_to_float(trade.get("quality", "WAIT"))
    feats["alignment"] = _safe_float(trade.get("alignment", 0))
    feats["bias_is_bull"] = 1.0 if trade.get("bias") == "BULL" else 0.0
    feats["bias_is_bear"] = 1.0 if trade.get("bias") == "BEAR" else 0.0

    # ── Prix et setup ──
    feats["price"] = price
    feats["sl"] = sl
    feats["tp"] = tp
    feats["rr"] = _safe_float(trade.get("rr", 0))
    feats["rr_is_above_2"] = 1.0 if feats["rr"] >= 2.0 else 0.0

    # ── Distances SL/TP en pips et % ──
    if price > 0:
        feats["dist_sl_pips"] = abs(price - sl) * pf
        feats["dist_tp_pips"] = abs(tp - price) * pf
        feats["dist_sl_pct"] = abs(price - sl) / max(price, 0.0001) * 100.0
        feats["dist_tp_pct"] = abs(tp - price) / max(price, 0.0001) * 100.0
        feats["range_sl_tp_pips"] = abs(tp - sl) * pf
    else:
        feats["dist_sl_pips"] = 0.0
        feats["dist_tp_pips"] = 0.0
        feats["dist_sl_pct"] = 0.0
        feats["dist_tp_pct"] = 0.0
        feats["range_sl_tp_pips"] = 0.0

    # ── Kijun H4/D1 ──
    feats["kj_h4"] = kj_h4
    feats["kj_d1"] = kj_d1
    feats["d_kj4"] = _safe_float(trade.get("d_kj4", 0))
    feats["d_kj_d1"] = _safe_float(trade.get("d_kj_d1", 0))
    if kj_h4 > 0:
        feats["price_vs_kj_h4_pct"] = (price - kj_h4) / kj_h4 * 100.0
    else:
        feats["price_vs_kj_h4_pct"] = 0.0
    if kj_d1 > 0:
        feats["price_vs_kj_d1_pct"] = (price - kj_d1) / kj_d1 * 100.0
    else:
        feats["price_vs_kj_d1_pct"] = 0.0

    # ── Asian Range ──
    ah = _safe_float(trade.get("asian_high", 0))
    al = _safe_float(trade.get("asian_low", 0))
    feats["asian_high"] = ah
    feats["asian_low"] = al
    if ah > 0 and al > 0:
        feats["asian_range_pips"] = abs(ah - al) * pf
        feats["price_vs_ah_pct"] = (price - ah) / ah * 100.0
        feats["price_vs_al_pct"] = (price - al) / al * 100.0
        feats["price_in_asian_range"] = 1.0 if al <= price <= ah else 0.0
    else:
        feats["asian_range_pips"] = 0.0
        feats["price_vs_ah_pct"] = 0.0
        feats["price_vs_al_pct"] = 0.0
        feats["price_in_asian_range"] = 0.0

    # ── Horizon (encodé) ──
    horizon = trade.get("horizon", "")
    for h_type in ["Intraday", "Session", "Swing", "Position"]:
        feats[f"horizon_{h_type}"] = 1.0 if horizon == h_type else 0.0

    # ── Bias × Kijun alignment (interaction features) ──
    feats["bull_x_d_kj4"] = feats["bias"] * feats["d_kj4"] if feats["bias"] > 0 else 0.0
    feats["bear_x_d_kj4"] = abs(feats["bias"]) * feats["d_kj4"] if feats["bias"] < 0 else 0.0

    return feats


# ─── DB source ──────────────────────────────────────────────────────────────

def label_from_db(db_path: Optional[str] = None) -> List[Dict[str, float]]:
    """Lit les trades CLOSED depuis la DB TradeTracker et extrait features + outcome.

    Utilise d'abord la colonne features_json (80+ features complètes) si disponible.
    Fallback : extraction depuis les ~20 champs stockés dans la DB.

    Args:
        db_path: Chemin vers le fichier SQLite. Si None, utilise la DB par défaut.

    Returns:
        Liste de dicts {feature_name: value, ..., "outcome": 0 or 1}.
    """
    try:
        from .database import get_db
        db = get_db()
    except ImportError:
        logger.error("Impossible d'importer get_db(). Vérifie que src/database.py existe.")
        return []

    conn = db.conn
    if conn is None:
        logger.error("DB non disponible")
        return []

    # Vérifier si la colonne features_json existe
    has_json_column = False
    try:
        cur = conn.execute("SELECT features_json FROM diamond_trades LIMIT 1")
        has_json_column = True
    except Exception:
        has_json_column = False

    try:
        cur = conn.execute(
            "SELECT * FROM diamond_trades WHERE status = 'CLOSED' AND pnl_pips IS NOT NULL ORDER BY close_time DESC"
        )
        closed_trades = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error("Erreur lecture DB: %s", e)
        return []

    if not closed_trades:
        logger.warning("Aucun trade CLOSED avec P&L trouvé dans la DB.")
        logger.info("Lance d'abord: python main.py track save  (puis track update, puis track close manuel si besoin)")
        return []

    labeled: List[Dict[str, float]] = []
    wins = 0
    losses = 0

    for trade in closed_trades:
        pnl = _safe_float(trade.get("pnl_pips", 0))
        if pnl == 0:
            continue  # skip trades with zero P&L (inconclusive)

        # ── Priorité: features_json si disponible ──
        feats: Dict[str, float] = {}
        features_raw = trade.get("features_json") if has_json_column else None

        if features_raw and isinstance(features_raw, str) and len(features_raw) > 10:
            try:
                parsed = json.loads(features_raw)
                if isinstance(parsed, dict):
                    for k, v in parsed.items():
                        fval = _safe_float(v, None)
                        if fval is not None:
                            feats[k] = fval
            except (json.JSONDecodeError, TypeError) as e:
                logger.debug("Erreur parsing features_json trade #%s: %s", trade.get("id"), e)

        # ── Fallback si features_json non disponible ou vide ──
        if not feats:
            feats = extract_features_from_db_trade(trade)
        else:
            # Ajouter les métadonnées manquantes (non dans features_json)
            if "bias" not in feats:
                feats["bias"] = _bias_to_float(trade.get("bias", "FLAT"))
            if "quality" not in feats:
                feats["quality"] = _quality_to_float(trade.get("quality", "WAIT"))
            if "alignment" not in feats:
                feats["alignment"] = _safe_float(trade.get("alignment", 0))
            if "score" not in feats:
                feats["score"] = _safe_float(trade.get("score", 0))
            if "score_pct" not in feats:
                feats["score_pct"] = feats.get("score", 0) / max(feats.get("max_score", 109), 1.0)

        feats["outcome"] = 1.0 if pnl > 0 else 0.0
        # Métadonnées stockées séparément (PAS dans le CSV features)
        feats["_pnl_pips"] = pnl   # préfixe _ = ignoré par le CSV writer
        feats["_trade_id"] = _safe_float(trade.get("id", 0))
        feats["_symbol"] = 0.0  # placeholder string non exporté

        # Logger le nombre de features utilisées
        if features_raw and len(feats) > 40:
            logger.debug("Trade #%s: %d features (full ML), outcome=%d",
                         trade.get("id"), len(feats), feats["outcome"])

        labeled.append(feats)
        if pnl > 0:
            wins += 1
        else:
            losses += 1

    n_full = sum(1 for r in labeled if len(r) > 40)
    logger.info("DB: %d trades extraits (%d wins, %d losses, win_rate=%.0f%%) dont %d avec features completes",
                len(labeled), wins, losses,
                wins / max(len(labeled), 1) * 100,
                n_full)
    return labeled


# ─── Manual CSV source ──────────────────────────────────────────────────────

def label_from_csv(csv_path: str) -> List[Dict[str, float]]:
    """Lit un CSV manuel avec colonnes features + outcome.

    Le CSV doit contenir une colonne "outcome" (1=gagné, 0=perdu).
    Toutes les autres colonnes numériques sont utilisées comme features.
    Les colonnes non-numériques sont ignorées.

    Args:
        csv_path: Chemin vers le fichier CSV.

    Returns:
        Liste de dicts {feature_name: value, ..., "outcome": 0 or 1}.
    """
    if not os.path.isfile(csv_path):
        logger.error("Fichier introuvable: %s", csv_path)
        return []

    labeled: List[Dict[str, float]] = []
    skipped = 0

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            logger.error("CSV sans header")
            return []

        for row in reader:
            try:
                # Extraire outcome
                if "outcome" not in row:
                    logger.warning("Colonne 'outcome' manquante dans le CSV — ligne ignorée")
                    skipped += 1
                    continue

                outcome_val = row.pop("outcome", "0")
                outcome = float(outcome_val)
                if outcome not in (0.0, 1.0):
                    logger.warning("Outcome invalide '%s' — attendu 0 ou 1. Ligne ignorée.", outcome_val)
                    skipped += 1
                    continue

                feats: Dict[str, float] = {}
                for col, val in row.items():
                    fval = _safe_float(val, None)  # type: ignore
                    if fval is not None:
                        feats[col] = fval

                feats["outcome"] = outcome
                labeled.append(feats)

            except (ValueError, KeyError) as e:
                logger.warning("Erreur parsing ligne CSV: %s", e)
                skipped += 1
                continue

    if skipped > 0:
        logger.warning("%d ligne(s) ignorée(s) (outcome manquant/invalide)", skipped)

    wins = sum(1 for r in labeled if r["outcome"] == 1.0)
    losses = sum(1 for r in labeled if r["outcome"] == 0.0)
    logger.info("CSV: %d trades chargés (%d wins, %d losses, win_rate=%.0f%%)",
                len(labeled), wins, losses,
                wins / max(len(labeled), 1) * 100)
    return labeled


# ─── Scan source (future labelling) ────────────────────────────────────────

def scan_for_features(symbols: List[str], tz_mode: str = "BROKER") -> List[Dict[str, float]]:
    """Lance un Diamond scan et extrait les features pour labelling futur.

    Le CSV généré aura la colonne 'outcome' vide (à remplir manuellement plus tard).

    Args:
        symbols: Liste des symboles à scanner.
        tz_mode: Fuseau horaire ("BROKER", "UTC", "PARIS").

    Returns:
        Liste de dicts {feature_name: value, ..., "outcome": ""}.
    """
    try:
        from .diamond_scanner import DiamondScanner
        from .ml_predictor import extract_features as extract_full_features
    except ImportError as e:
        logger.error("Import échoué: %s", e)
        return []

    scanner = DiamondScanner(symbols, tz_mode=tz_mode)
    if not scanner.initialize():
        logger.error("Connexion MT5 impossible")
        return []

    try:
        results = scanner.scan_all()
    finally:
        scanner.shutdown()

    labeled: List[Dict[str, float]] = []
    for r in results:
        # En mode scan, on garde TOUS les symboles, même WAIT/FLAT.
        # Le but est de collecter un maximum de data points pour le dataset ML.
        # L'utilisateur remplira manuellement la colonne 'outcome' plus tard.
        feats = extract_full_features(r)
        labeled.append(feats)

    logger.info("Scan: %d setups extraits sur %d symboles (features seulement, outcome à remplir)",
                len(labeled), len(results))
    return labeled


# ─── CSV writer ─────────────────────────────────────────────────────────────

def write_labeled_csv(rows: List[Dict[str, float]], output_path: str) -> str:
    """Écrit les trades labellisés dans un CSV.

    Args:
        rows: Liste de dicts {feature: value, ..., outcome: 0/1}.
        output_path: Chemin de sortie.

    Returns:
        Chemin absolu du fichier créé.
    """
    if not rows:
        logger.warning("Aucune donnée à écrire — fichier vide.")
        # Créer quand même un fichier vide avec juste le header
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            f.write("outcome\n")
        return os.path.abspath(output_path)

    # Collecter toutes les clés de features (union de toutes les lignes)
    all_keys: List[str] = []
    seen = set()
    for row in rows:
        for k in row:
            if k not in seen:
                all_keys.append(k)
                seen.add(k)

    # S'assurer que 'outcome' est en dernière colonne
    if "outcome" in all_keys:
        all_keys.remove("outcome")
    # Retirer les colonnes non-features (préfixe _ = métadonnées)
    feature_keys = [k for k in all_keys if not k.startswith("_")]

    # Colonnes dans l'ordre: features d'abord, outcome à la fin
    fieldnames = feature_keys + ["outcome"]

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    abs_path = os.path.abspath(output_path)
    size_kb = os.path.getsize(abs_path) / 1024
    n_features = len(all_keys)
    logger.info("CSV écrit: %s (%d trades × %d features, %.0f KB)",
                abs_path, len(rows), n_features, size_kb)

    # ── Résumé ──
    wins = sum(1 for r in rows if r.get("outcome", 0) == 1.0)
    losses = sum(1 for r in rows if r.get("outcome", 0) == 0.0)
    unlabeled = len(rows) - wins - losses
    print(f"\n{'='*60}")
    print(f"  [ML Labeler] CSV genere : {abs_path}")
    print(f"  Trades       : {len(rows)}")
    if unlabeled == 0:
        print(f"  Gagnants     : {wins} ({wins/max(len(rows),1)*100:.0f}%)")
        print(f"  Perdants     : {losses} ({losses/max(len(rows),1)*100:.0f}%)")
        print(f"  Win rate     : {wins/max(len(rows),1)*100:.0f}%")
    else:
        print(f"  Labellises   : {wins + losses}")
        print(f"  A remplir    : {unlabeled} (colonne 'outcome' vide)")
    print(f"  Features     : {n_features}")
    print(f"  Taille       : {size_kb:.0f} KB")
    print(f"{'='*60}")
    print(f"")
    if wins + losses > 0:
        print(f"  Pret pour l'entrainement :")
        print(f"     python -m src.ml_trainer --data {abs_path} --output models/diamond_v1.xgb")
    else:
        print(f"  Remplis la colonne 'outcome' manuellement, puis :")
        print(f"     python -m src.ml_trainer --data {abs_path} --output models/diamond_v1.xgb")

    return abs_path


# ─── Main CLI ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="ML Labeler — Génère un CSV de trades labellisés pour l'entraînement XGBoost."
    )
    parser.add_argument(
        "--source", required=True, choices=["db", "manual", "scan"],
        help="Source des données: db (trades fermés DB), manual (CSV fourni), scan (Diamond live)"
    )
    parser.add_argument(
        "--output", default="data/trades_labeled.csv",
        help="Chemin du CSV de sortie (défaut: data/trades_labeled.csv)"
    )
    parser.add_argument(
        "--input",
        help="[source=manual] Chemin du CSV d'entrée (doit contenir une colonne 'outcome')"
    )
    parser.add_argument(
        "--symbols", nargs="+",
        help="[source=scan] Symboles à scanner (ex: EURUSD GBPUSD). Défaut: watchlist configurée."
    )
    parser.add_argument(
        "--timezone", default="BROKER",
        help="[source=scan] Fuseau horaire (BROKER, UTC, PARIS). Défaut: BROKER."
    )
    args = parser.parse_args()

    # ── Dispatch par source ──
    if args.source == "db":
        rows = label_from_db()
        if not rows:
            logger.error("Aucun trade labellisé extrait de la DB.")
            return 1
        write_labeled_csv(rows, args.output)

    elif args.source == "manual":
        if not args.input:
            logger.error("--input requis pour source=manual")
            return 1
        rows = label_from_csv(args.input)
        if not rows:
            logger.error("Aucun trade valide extrait du CSV.")
            return 1
        write_labeled_csv(rows, args.output)

    elif args.source == "scan":
        symbols = list(args.symbols) if args.symbols else []
        if not symbols:
            # Fallback: utiliser la watchlist configurée
            try:
                from .config import resolve_watchlist
                symbols = resolve_watchlist()
            except ImportError:
                logger.error("Aucun symbole spécifié et impossible de résoudre la watchlist.")
                return 1
        rows = scan_for_features(symbols, tz_mode=args.timezone)
        if not rows:
            logger.error("Aucun setup extrait du scan.")
            return 1
        write_labeled_csv(rows, args.output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
