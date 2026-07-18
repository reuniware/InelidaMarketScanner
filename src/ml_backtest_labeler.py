"""
ML Backtest Labeler — Détermine l'outcome (gagné/perdu) via backtest MT5.

Pour chaque setup Diamond détecté :
  1. Récupère les barres M1 après le timestamp du scan
  2. Parcourt les barres pour vérifier si TP ou SL a été touché en premier
  3. outcome = 1.0 si TP touché, 0.0 si SL touché, None si indéterminé

Usage:
    from src.ml_backtest_labeler import backtest_results
    labeled = backtest_results(results)  # List[Dict] avec outcome
    
    # Ou depuis la DB TradeTracker
    labeled = backtest_from_db(max_lookback_hours=48)
"""

import json
import logging
import time as _time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from .ml_predictor import extract_features
from .diamond_scanner import DiamondResult
from .ml_labeler import _safe_float

logger = logging.getLogger("MLBacktestLabeler")

UTC = timezone.utc

# ─── MT5 singleton — init UNE SEULE fois ─────────────────────────────────

_MT5_INITIALIZED = False

def _ensure_mt5() -> bool:
    """Initialise MT5 une seule fois. Retourne True si OK."""
    global _MT5_INITIALIZED
    if _MT5_INITIALIZED:
        return True
    try:
        import MetaTrader5 as mt5
        if mt5.initialize():
            _MT5_INITIALIZED = True
            logger.debug("MT5 initialisé pour le backtest")
            return True
        logger.warning("Échec initialisation MT5")
        return False
    except ImportError:
        logger.warning("MetaTrader5 non installé — backtest impossible")
        return False
    except Exception as e:
        logger.warning("Erreur MT5: %s", e)
        return False


def _shutdown_mt5():
    """Ferme MT5 proprement."""
    global _MT5_INITIALIZED
    if _MT5_INITIALIZED:
        try:
            import MetaTrader5 as mt5
            mt5.shutdown()
        except Exception:
            pass
        _MT5_INITIALIZED = False


# ─── Helpers ──────────────────────────────────────────────────────────────

def _check_tp_sl_first(highs: List[float], lows: List[float],
                       timestamps: List[int], price: float,
                       sl: float, tp: float, bias: str) -> Optional[Tuple[str, int]]:
    """Parcourt les barres pour savoir si TP ou SL touché en premier.

    Args:
        highs: Liste des plus hauts (prix).
        lows: Liste des plus bas (prix).
        timestamps: Timestamps Unix des barres.
        price: Prix d'entrée.
        sl: Stop-loss.
        tp: Take-profit.
        bias: 'BULL' ou 'BEAR'.

    Returns:
        (résultat, index) ou None si aucun touché.
    """
    for i, (h, l) in enumerate(zip(highs, lows)):
        if i == 0:
            continue  # Ignorer la bougie du scan lui-même

        if bias == "BULL":
            if l <= sl:
                return ("SL_HIT", i)
            if h >= tp:
                return ("TP_HIT", i)
        else:
            if h >= sl:
                return ("SL_HIT", i)
            if l <= tp:
                return ("TP_HIT", i)

    return None


def _get_bars_after_ts(symbol: str, from_ts: float,
                       max_hours: int = 48) -> Optional[Tuple[List[float], List[float], List[int]]]:
    """Récupère les barres (M1 ou M5 en fallback) après un timestamp.

    MT5 est initialisé UNE SEULE FOIS par le caller (backtest_results ou backtest_from_db).

    Args:
        symbol: Symbole MT5.
        from_ts: Timestamp Unix de départ.
        max_hours: Nombre max d'heures de lookback.

    Returns:
        (highs, lows, timestamps) ou None si indisponible.
    """
    try:
        import MetaTrader5 as mt5
    except ImportError:
        return None

    if not _ensure_mt5():
        return None

    mt5.symbol_select(symbol, True)
    from_dt = datetime.fromtimestamp(from_ts, tz=UTC)
    now_dt = datetime.now(UTC)

    # Essayer M1 d'abord
    max_bars_m1 = min(max_hours * 60, 2880)
    rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M1, from_dt, now_dt)

    tf_label = "M1"
    if rates is None or len(rates) < 2:
        # Fallback M5
        max_bars_m5 = min(max_hours * 12, 576)
        rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M5, from_dt, now_dt)
        tf_label = "M5"

        if rates is None or len(rates) < 2:
            logger.debug("Aucune barre pour %s depuis %s", symbol, from_dt)
            return None

        if len(rates) > max_bars_m5:
            rates = rates[:max_bars_m5]
    else:
        if len(rates) > max_bars_m1:
            rates = rates[:max_bars_m1]

    highs = [float(r[2]) for r in rates]
    lows = [float(r[3]) for r in rates]
    timestamps = [int(r[0]) for r in rates]

    logger.debug("%s: %d barres %s depuis %s", symbol, len(rates), tf_label, from_dt)
    return (highs, lows, timestamps)


# ─── Main backtest functions ────────────────────────────────────────────

def backtest_single_result(result: DiamondResult,
                           max_lookback_hours: int = 48) -> Optional[Dict[str, float]]:
    """Backteste un seul DiamondResult et retourne les features avec outcome.

    Args:
        result: Un setup Diamond à backtester.
        max_lookback_hours: Nombre max d'heures à regarder en arrière.

    Returns:
        Dictionnaire de features avec 'outcome' rempli, ou None si impossible.
    """
    symbol = (getattr(result, "symbol", "") or "").upper()
    price = _safe_float(getattr(result, "price", 0))
    sl = _safe_float(getattr(result, "sl", 0))
    tp = _safe_float(getattr(result, "tp", 0))
    bias = getattr(result, "bias", "FLAT")

    if not symbol or price == 0 or sl == 0 or tp == 0:
        logger.debug("Setup %s invalide pour backtest: price=%s sl=%s tp=%s",
                     symbol, price, sl, tp)
        return None

    if bias not in ("BULL", "BEAR"):
        return None

    scan_time = _time.time()
    bars = _get_bars_after_ts(symbol, scan_time, max_hours=max_lookback_hours)

    if bars is None:
        return None

    highs, lows, timestamps = bars
    result_check = _check_tp_sl_first(highs, lows, timestamps, price, sl, tp, bias)

    feats = extract_features(result)
    feats["_scan_time"] = scan_time

    if result_check is None:
        feats["outcome"] = -1.0
        feats["_backtest_result"] = "PENDING"
        feats["_backtest_bars"] = float(len(highs))
    else:
        hit_type, bar_idx = result_check
        feats["_backtest_bars_until_result"] = float(bar_idx)
        feats["_backtest_result"] = hit_type
        feats["outcome"] = 1.0 if hit_type == "TP_HIT" else 0.0

    return feats


def backtest_results(results: List[DiamondResult],
                     max_lookback_hours: int = 48) -> List[Dict[str, float]]:
    """Backteste une liste de DiamondResult et retourne les features avec outcome.

    MT5 est initialisé UNE SEULE FOIS pour tout le lot.

    Args:
        results: Liste des setups Diamond.
        max_lookback_hours: Nombre max d'heures à regarder en arrière.

    Returns:
        Liste de dicts avec outcome rempli.
    """
    if not _ensure_mt5():
        logger.error("MT5 non disponible — backtest impossible")
        return []

    labeled: List[Dict[str, float]] = []
    total = len(results)
    wins = 0
    losses = 0
    pending = 0
    skipped = 0

    try:
        for i, result in enumerate(results):
            logger.info("Backtest [%d/%d] %s...", i + 1, total,
                        getattr(result, "symbol", "?"))

            feats = backtest_single_result(result, max_lookback_hours)

            if feats is None:
                skipped += 1
                continue

            outcome = feats.get("outcome", -1)
            if outcome == 1.0:
                wins += 1
            elif outcome == 0.0:
                losses += 1
            else:
                pending += 1

            labeled.append(feats)
    finally:
        _shutdown_mt5()

    logger.info("=" * 50)
    logger.info("RÉSULTATS DU BACKTEST (%d setups)", total)
    total_labeled = len(labeled)
    logger.info("  Gagnés   : %d (%.0f%%)", wins, wins / max(total_labeled, 1) * 100)
    logger.info("  Perdus   : %d (%.0f%%)", losses, losses / max(total_labeled, 1) * 100)
    logger.info("  En cours : %d", pending)
    logger.info("  Ignorés  : %d (pas de SL/TP ou non directionnel)", skipped)
    logger.info("=" * 50)

    return labeled


def backtest_from_db(max_lookback_hours: int = 48) -> List[Dict[str, float]]:
    """Backteste les trades de la DB TradeTracker avec un seul cycle MT5.

    Priorité aux features_json complètes (108 features) si disponibles.
    Fallback : extract_features_from_db_trade() (~20 features).

    Args:
        max_lookback_hours: Nombre max d'heures à regarder en arrière.

    Returns:
        Liste de dicts avec outcome rempli.
    """
    try:
        from .database import get_db
    except ImportError:
        logger.error("Impossible d'importer les modules nécessaires")
        return []

    if not _ensure_mt5():
        logger.error("MT5 non disponible — backtest DB impossible")
        return []

    db = get_db()
    conn = db.conn
    if conn is None:
        logger.error("DB non disponible")
        _shutdown_mt5()
        return []

    # Vérifier si la colonne features_json existe
    has_json = False
    try:
        conn.execute("SELECT features_json FROM diamond_trades LIMIT 1")
        has_json = True
    except Exception:
        has_json = False

    try:
        cur = conn.execute(
            "SELECT * FROM diamond_trades WHERE status IN ('OPEN', 'CLOSED') ORDER BY scan_time DESC"
        )
        trades = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error("Erreur lecture DB: %s", e)
        _shutdown_mt5()
        return []

    if not trades:
        logger.warning("Aucun trade trouvé dans la DB.")
        _shutdown_mt5()
        return []

    logger.info("Backtest DB: %d trades à analyser...", len(trades))

    labeled: List[Dict[str, float]] = []
    wins = 0
    losses = 0
    pending = 0
    skipped = 0

    try:
        for i, trade in enumerate(trades):
            symbol = trade.get("symbol", "")
            price = _safe_float(trade.get("price", 0))
            sl = _safe_float(trade.get("sl", 0))
            tp = _safe_float(trade.get("tp", 0))
            bias = trade.get("bias", "FLAT")
            scan_time = _safe_float(trade.get("scan_time", _time.time()))

            if not symbol or price == 0 or sl == 0 or tp == 0:
                skipped += 1
                continue

            if bias not in ("BULL", "BEAR"):
                skipped += 1
                continue

            logger.info("Backtest DB [%d/%d] %s (scan=%s)...",
                        i + 1, len(trades), symbol,
                        datetime.fromtimestamp(scan_time, UTC).strftime("%m-%d %H:%M"))

            bars = _get_bars_after_ts(symbol, scan_time, max_hours=max_lookback_hours)
            if bars is None:
                pending += 1
                continue

            highs, lows, timestamps = bars
            result_check = _check_tp_sl_first(highs, lows, timestamps, price, sl, tp, bias)

            # ─── Extraire les features ───
            # Priorité : features_json (108 features) > extract_features_from_db_trade (~20)
            feats = _extract_features_from_db(trade, has_json)

            # Ajouter les métadonnées de backtest
            feats["_symbol"] = symbol
            feats["_scan_time"] = scan_time
            feats["_db_trade_id"] = float(trade.get("id", 0))

            if result_check is None:
                feats["outcome"] = -1.0
                feats["_backtest_result"] = "PENDING"
                pending += 1
            else:
                hit_type, bar_idx = result_check
                feats["_backtest_bars_until_result"] = float(bar_idx)
                feats["_backtest_result"] = hit_type
                feats["outcome"] = 1.0 if hit_type == "TP_HIT" else 0.0
                if hit_type == "TP_HIT":
                    wins += 1
                else:
                    losses += 1

            labeled.append(feats)
    finally:
        _shutdown_mt5()

    logger.info("=" * 50)
    logger.info("RÉSULTATS DU BACKTEST DB (%d trades)", len(trades))
    total_labeled = len(labeled)
    logger.info("  Gagnés   : %d (%.0f%%)", wins, wins / max(total_labeled, 1) * 100)
    logger.info("  Perdus   : %d (%.0f%%)", losses, losses / max(total_labeled, 1) * 100)
    logger.info("  En cours : %d", pending)
    logger.info("  Ignorés  : %d", skipped)
    logger.info("=" * 50)

    return labeled


def _extract_features_from_db(trade: dict, has_json: bool) -> Dict[str, float]:
    """Extrait les features depuis un trade DB, priorité à features_json.

    Args:
        trade: Ligne de diamond_trades.
        has_json: True si la colonne features_json existe.

    Returns:
        Dictionnaire de features.
    """
    # Essayer features_json d'abord (108 features complètes)
    if has_json:
        features_raw = trade.get("features_json")
        if features_raw and isinstance(features_raw, str) and len(features_raw) > 10:
            try:
                parsed = json.loads(features_raw)
                if isinstance(parsed, dict):
                    feats = {}
                    for k, v in parsed.items():
                        fv = _safe_float(v, None)
                        if fv is not None:
                            feats[k] = fv
                    if len(feats) > 40:
                        return feats
            except (json.JSONDecodeError, TypeError):
                pass

    # Fallback : extraction depuis les ~20 champs DB (déjà inclut sl, tp, rr, bias)
    from .ml_labeler import extract_features_from_db_trade
    return extract_features_from_db_trade(trade)
