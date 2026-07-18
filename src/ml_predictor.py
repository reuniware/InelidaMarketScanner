"""
ML Predictor — Prédiction de probabilité de trade gagnant à partir d'un DiamondResult.

Utilise un modèle XGBoost entraîné sur les backtests historiques.
Le modèle prend les 109 critères du Diamond Scanner en entrée et retourne
une probabilité de trade gagnant (0.0 → 1.0).

Usage:
    predictor = MLPredictor()
    prob = predictor.predict(diamond_result)  # 0.73 = 73% de chance de gagner
"""

import logging
import math
import os
import time
from datetime import datetime, timezone
from typing import Optional

import joblib

logger = logging.getLogger("MLPredictor")

# Chemin par défaut du modèle entraîné (unifié v7 — fallback)
_MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")
_DEFAULT_MODEL = os.path.join(_MODEL_DIR, "historical_v7.xgb")

# Per-asset v13 models (ensemble — meilleur OOS, PF=4.000)
_V13_DXY   = os.path.join(_MODEL_DIR, "historical_v13_dxy.xgb")
_V13_XAU   = os.path.join(_MODEL_DIR, "historical_v13_xau.xgb")
_V13_INDEX = os.path.join(_MODEL_DIR, "historical_v13_index.xgb")
_V13_FOREX = os.path.join(_MODEL_DIR, "historical_v13_forex.xgb")

# Asset classification helper — utilisée par MLPredictor pour sélectionner le bon modèle
_ASSET_KEYWORDS = {
    "dxy": ["DXY"],
    "xau": ["XAU", "XAG"],
    "index": ["US30", "US100", "US500", "SPX", "NAS", "DJI", "FTSE", "DAX", "NK", "HSI", "CAC"],
}


def _classify_asset(symbol: str) -> str:
    """Classifie un symbole en type d'actif : dxy, xau, index, ou forex."""
    sym_up = symbol.upper()
    for asset_type, keywords in _ASSET_KEYWORDS.items():
        if any(kw in sym_up for kw in keywords):
            return asset_type
    return "forex"  # tout le reste

# ─── Cache DXY ─────────────────────────────────────────────────────────────
# Évite de multiples appels MT5 redondants pendant un même scan
_DXY_CACHE: dict = {"price": None, "kj_h1": None, "ts": 0.0}
_DXY_TTL = 60  # secondes avant de rafraîchir le cache


def _fetch_dxy_features() -> dict:
    """Récupère les features DXY (prix + Kijun H1) avec cache TTL."""
    global _DXY_CACHE
    now = time.time()
    if _DXY_CACHE["ts"] > 0 and (now - _DXY_CACHE["ts"]) < _DXY_TTL:
        return {
            "dxy_price": _DXY_CACHE["price"] or 0.0,
            "dxy_kj_h1": _DXY_CACHE["kj_h1"] or 0.0,
            "dxy_vs_kj_h1": (_DXY_CACHE["price"] or 0.0) - (_DXY_CACHE["kj_h1"] or 0.0),
        }
    try:
        from .diamond_scanner import get_dxy_price, get_dxy_kijun_h1
        dxy_price = get_dxy_price()
        dxy_kj_h1 = get_dxy_kijun_h1()
        _DXY_CACHE = {"price": dxy_price, "kj_h1": dxy_kj_h1, "ts": now}
        p = dxy_price or 0.0
        k = dxy_kj_h1 or 0.0
        return {"dxy_price": p, "dxy_kj_h1": k, "dxy_vs_kj_h1": p - k}
    except Exception as e:
        logger.debug("DXY features indisponibles: %s", e)
        return {"dxy_price": 0.0, "dxy_kj_h1": 0.0, "dxy_vs_kj_h1": 0.0}


# ─── Cache NEWS ─────────────────────────────────────────────────────────────
_NEWS_CACHE: dict = {"count": 0, "ts": 0.0}
_NEWS_TTL = 300  # 5 minutes — le calendrier macro ne change pas toutes les minutes


def _fetch_news_features() -> dict:
    """Récupère les features macro (news_count + high_news_day) avec cache TTL.

    Appelle get_news_risk() de news_calendar avec cache de 5 minutes.
    """
    global _NEWS_CACHE
    now = time.time()

    # Cache valide ?
    if _NEWS_CACHE["ts"] > 0 and (now - _NEWS_CACHE["ts"]) < _NEWS_TTL:
        return {
            "news_count": _NEWS_CACHE["count"],
            "is_high_news_day": 1.0 if _NEWS_CACHE["count"] >= 2 else 0.0,
        }

    try:
        from .news_calendar import get_news_risk
        count, _msg, _is_high = get_news_risk()
        _NEWS_CACHE = {"count": count, "ts": now}
        return {
            "news_count": count,
            "is_high_news_day": 1.0 if count >= 2 else 0.0,
        }
    except Exception as e:
        logger.debug("News features indisponibles: %s", e)
        return {"news_count": 0.0, "is_high_news_day": 0.0}



def _safe_float(val, default: float = 0.0) -> float:
    """Convertit une valeur en float de manière sécurisée."""
    try:
        return float(val) if val is not None else default
    except (ValueError, TypeError):
        return default


def _safe_bool(val) -> float:
    """Convertit un booléen en 0.0/1.0."""
    if val is None:
        return 0.0
    return 1.0 if val else 0.0


def _bias_to_float(bias: str) -> float:
    """BULL=1.0, BEAR=-1.0, FLAT=0.0"""
    if bias == "BULL": return 1.0
    if bias == "BEAR": return -1.0
    return 0.0


def _kumo_to_float(kumo: str) -> float:
    """ABOVE=1.0, INSIDE=0.0, BELOW=-1.0, N/A=0.0"""
    if kumo == "ABOVE": return 1.0
    if kumo == "BELOW": return -1.0
    return 0.0


def _tkx_to_float(tkx: str) -> float:
    """BULL=1.0, BEAR=-1.0, N/A=0.0"""
    if tkx == "BULL": return 1.0
    if tkx == "BEAR": return -1.0
    return 0.0


def extract_features(result, scan_time: Optional[datetime] = None,
                     dxy_price_ht: Optional[float] = None) -> dict:
    """Extrait un vecteur de features numériques depuis un DiamondResult.

    Args:
        result: Instance de DiamondResult (ou n'importe quel objet avec les mêmes attributs).
        scan_time: datetime UTC optionnel pour les features temporelles.
                   Si None, utilise datetime.now(UTC).
        dxy_price_ht: Prix DXY historique (pour le backtest). Si None, utilise le prix live (cache).

    Returns:
        Dictionnaire {nom_feature: valeur_float} prêt pour la prédiction.
    """
    feats = {}

    # ── Asset category (one-hot encoded) ──
    symbol = (getattr(result, "symbol", "") or "").upper()
    feats["is_forex"] = 1.0 if (
        symbol in ("EURUSD","GBPUSD","USDJPY","AUDUSD","USDCAD","USDCHF",
                   "EURJPY","GBPJPY","EURGBP","EURAUD","GBPAUD","AUDJPY",
                   "CHFJPY","NZDUSD","GBPNZD","EURCHF","AUDCHF","CADCHF")
    ) else 0.0
    feats["is_jpy_pair"] = 1.0 if "JPY" in symbol else 0.0
    feats["is_xau"] = 1.0 if "XAU" in symbol else 0.0
    feats["is_xag"] = 1.0 if "XAG" in symbol else 0.0
    _idx_keywords = ["US30","US100","US500","SPX","NAS","DJI","FTSE","DAX","NK","HSI","CAC","IBEX"]
    feats["is_index"] = 1.0 if any(x in symbol for x in _idx_keywords) else 0.0
    _crypto_symbols = ("BTCUSD","ETHUSD","LTCUSD","XRPUSD","BCHUSD","ADAUSD","DOTUSD")
    feats["is_crypto"] = 1.0 if symbol in _crypto_symbols else 0.0
    feats["is_dxy"] = 1.0 if "DXY" in symbol else 0.0

    # ── Time features (ICT sessions, killzones, day of week) ──
    _now = scan_time if scan_time is not None else datetime.now(timezone.utc)
    _h = _now.hour         # 0-23
    _w = _now.weekday()    # 0=Monday

    # ICT Sessions
    feats["session_asian"] = 1.0 if _h < 8 else 0.0
    feats["session_london"] = 1.0 if 8 <= _h < 16 else 0.0
    feats["session_ny"] = 1.0 if 13 <= _h < 21 else 0.0

    # ICT Killzones
    feats["killzone_asian_open"] = 1.0 if _h == 0 else 0.0
    feats["killzone_london_open"] = 1.0 if 8 <= _h < 10 else 0.0
    feats["killzone_london_close"] = 1.0 if 11 <= _h < 12 else 0.0
    feats["killzone_ny_open"] = 1.0 if 13 <= _h < 15 else 0.0
    feats["killzone_ny_close"] = 1.0 if 15 <= _h < 16 else 0.0

    # Day of week (one-hot)
    feats["day_monday"] = 1.0 if _w == 0 else 0.0
    feats["day_tuesday"] = 1.0 if _w == 1 else 0.0
    feats["day_wednesday"] = 1.0 if _w == 2 else 0.0
    feats["day_thursday"] = 1.0 if _w == 3 else 0.0
    feats["day_friday"] = 1.0 if _w == 4 else 0.0

    # Hour cyclic encoding (sin/cos pour que le modèle comprenne la circularité du temps)
    feats["hour_sin"] = math.sin(2 * math.pi * _h / 24.0)
    feats["hour_cos"] = math.cos(2 * math.pi * _h / 24.0)

    # ── DXY context (prix + tendance via Kijun H1) ──
    _dxy = _fetch_dxy_features()
    _dxy_px = dxy_price_ht if dxy_price_ht is not None else _dxy["dxy_price"]
    _dxy_kj = _dxy["dxy_kj_h1"]
    feats["dxy_price"] = _dxy_px
    feats["dxy_kj_h1"] = _dxy_kj
    feats["dxy_vs_kj_h1"] = _dxy_px - _dxy_kj

    # ── Cross-pair features (DXY vs current symbol) ──
    _cur_px = _safe_float(getattr(result, "price", 0))
    _cur_bias_str = getattr(result, "bias", "FLAT")
    _cur_bias = _bias_to_float(_cur_bias_str)
    # DXY / current price ratio (scaled) — correlation inverse typique
    feats["dxy_vs_price_ratio"] = _dxy_px / max(_cur_px, 0.0001) if _cur_px > 0 else 0.0
    # DXY Kijun distance normalized
    feats["dxy_kj_h1_norm"] = (_dxy_px - _dxy_kj) / max(_dxy_px, 0.01) if _dxy_px > 0 else 0.0
    # DXY divergence: 1 = anomaly in DXY/pair correlation
    # Direct pairs (EURUSD, GBPUSD, etc.): inverse corr with DXY
    #   Normal: DXY up + EURUSD down. Anomaly: BOTH same direction
    # JPY pairs (USDJPY): direct corr with DXY
    #   Normal: DXY up + USDJPY up. Anomaly: OPPOSITE directions
    _is_jpy = "JPY" in symbol
    _dxy_bull = _dxy_px > _dxy_kj
    _dxy_bear = _dxy_px < _dxy_kj
    if _is_jpy:
        # JPY pairs: anomaly = moving opposite to DXY
        feats["dxy_divergence"] = 1.0 if (
            (_dxy_bull and _cur_bias < 0) or
            (_dxy_bear and _cur_bias > 0)
        ) else 0.0
    else:
        # Direct pairs, XAU, indices: anomaly = moving same direction as DXY
        feats["dxy_divergence"] = 1.0 if (
            (_dxy_bull and _cur_bias > 0) or
            (_dxy_bear and _cur_bias < 0)
        ) else 0.0
    # DXY trend itself (bull=1, bear=-1, flat=0)
    _dxy_trend = 1.0 if _dxy_bull else (-1.0 if _dxy_bear else 0.0)
    feats["dxy_trend"] = _dxy_trend
    # DXY trend × bias interaction (high positive = aligned, negative = conflict)
    feats["dxy_trend_x_bias"] = _dxy_trend * _cur_bias

    # ── Macro news context (HIGH NEWS DAY detection) ──
    _news = _fetch_news_features()
    feats["news_count"] = _news["news_count"]
    feats["is_high_news_day"] = _news["is_high_news_day"]

    # ── Prix et scores ──
    feats["price"] = _safe_float(getattr(result, "price", 0))
    feats["score"] = _safe_float(getattr(result, "score", 0))
    feats["max_score"] = _safe_float(getattr(result, "max_score", 109))
    feats["score_pct"] = feats["score"] / max(feats["max_score"], 1.0)
    feats["bias"] = _bias_to_float(getattr(result, "bias", "FLAT"))
    feats["alignment"] = _safe_float(getattr(result, "alignment", 0))

    # ── Setup levels (SL/TP) — critiques pour le backtest ──
    feats["sl"] = _safe_float(getattr(result, "sl", 0))
    feats["tp"] = _safe_float(getattr(result, "tp", 0))
    feats["rr"] = _safe_float(getattr(result, "rr", 0))

    # ── Kijun distances (pips) ──
    for tf in ["h1", "m30", "m15", "m5", "h4", "d1"]:
        feats[f"kj_{tf}"] = _safe_float(getattr(result, f"kj_{tf}", 0))
        feats[f"d_kj_{tf}"] = _safe_float(getattr(result, f"d_kj_{tf}", 0))

    # ── Tenkan distances ──
    for tf in ["h1", "m30", "m15", "m5", "h4", "d1"]:
        feats[f"tk_{tf}"] = _safe_float(getattr(result, f"tk_{tf}", 0))
        feats[f"d_tk_{tf}"] = _safe_float(getattr(result, f"d_tk_{tf}", 0))

    # ── T/K crosses ──
    for tf in ["h1", "h4", "d1", "w1", "mn"]:
        feats[f"tkx_{tf}"] = _tkx_to_float(getattr(result, f"tkx_{tf}", "N/A"))

    # ── Kumo positions ──
    for tf in ["h1", "h4", "d1", "w1", "mn"]:
        feats[f"kumo_{tf}"] = _kumo_to_float(getattr(result, f"kumo_{tf}", "N/A"))

    # ── M5/M15/M30 crosses (booléens) ──
    for tf in ["m30", "m15", "m5"]:
        feats[f"kj_{tf}_cross_bear"] = _safe_bool(getattr(result, f"kj_{tf}_cross_bear", False))
        feats[f"kj_{tf}_cross_bull"] = _safe_bool(getattr(result, f"kj_{tf}_cross_bull", False))
        feats[f"tk_{tf}_cross_bear"] = _safe_bool(getattr(result, f"tk_{tf}_cross_bear", False))
        feats[f"tk_{tf}_cross_bull"] = _safe_bool(getattr(result, f"tk_{tf}_cross_bull", False))

    # ── Flat bars ──
    feats["flat_h1"] = _safe_float(getattr(result, "flat_h1", 0))
    feats["flat_h4"] = _safe_float(getattr(result, "flat_h4", 0))

    # ── FVG non-mitigated count + closest distance ──
    fvg_count = 0
    for tf in ["h1", "h4", "d1", "m30", "m15", "m5"]:
        for side in ["bear", "bull"]:
            top = _safe_float(getattr(result, f"fvg_{tf}_{side}_top", 0))
            mit = _safe_float(getattr(result, f"fvg_{tf}_{side}_mitigated_pct", 100))
            if top > 0 and mit < 50:  # Non ou partiellement mitigé
                fvg_count += 1
    feats["fvg_active_count"] = float(fvg_count)

    # ── OB distances ──
    for tf in ["h1", "h4", "d1"]:
        feats[f"ob_{tf}_bear_level"] = _safe_float(getattr(result, f"ob_{tf}_bear_level", 0))
        feats[f"ob_{tf}_bull_level"] = _safe_float(getattr(result, f"ob_{tf}_bull_level", 0))

    # ── Sweeps AH/AL ──
    feats["asian_high_swept"] = _safe_bool(getattr(result, "asian_high_swept", False))
    feats["asian_low_swept"] = _safe_bool(getattr(result, "asian_low_swept", False))
    feats["london_high_swept"] = _safe_bool(getattr(result, "london_high_swept", False))
    feats["london_low_swept"] = _safe_bool(getattr(result, "london_low_swept", False))
    feats["swept_both"] = _safe_bool(
        getattr(result, "asian_high_swept", False) and getattr(result, "asian_low_swept", False)
    )

    # ── Volume HVN/LVN ──
    for tf in ["h1", "h4", "d1"]:
        feats[f"vol_hvn_{tf}"] = _safe_float(getattr(result, f"vol_hvn_{tf}", 0))
        feats[f"vol_lvn_{tf}"] = _safe_float(getattr(result, f"vol_lvn_{tf}", 0))

    # ── Market Structure ──
    for tf in ["h1", "h4", "d1"]:
        regime = getattr(result, f"mss_{tf}_regime", "N/A")
        feats[f"mss_{tf}_bull"] = _safe_bool(regime == "BULL")
        feats[f"mss_{tf}_bear"] = _safe_bool(regime == "BEAR")

    # ── Compression ──
    feats["compression_pips"] = _safe_float(getattr(result, "compression_pips", 0))

    # ── TKx H1 conflict flag ──
    bias_str = getattr(result, "bias", "FLAT")
    tkx_h1_str = getattr(result, "tkx_h1", "N/A")
    feats["tkx_h1_conflict"] = _safe_bool(
        (bias_str == "BULL" and tkx_h1_str == "BEAR") or
        (bias_str == "BEAR" and tkx_h1_str == "BULL")
    )

    # ── Metadata pour backtest (préfixe _ = ignoré par le feature set ML) ──
    feats["_symbol"] = symbol
    feats["_scan_time"] = time.time()

    return feats


class MLPredictor:
    """Prédicteur ML — utilise des modèles per-asset (v13) avec fallback v7 unifié.

    Charge 4 modèles spécialisés (DXY, XAU, Indices, Forex) + le modèle v7 unifié
    comme fallback. La prédiction sélectionne automatiquement le bon modèle
    selon le symbole du résultat analysé.
    """

    _ASSET_MODEL_MAP = {
        "dxy": _V13_DXY,
        "xau": _V13_XAU,
        "index": _V13_INDEX,
        "forex": _V13_FOREX,
    }

    def __init__(self, model_path: Optional[str] = None):
        self._fallback_path = model_path or _DEFAULT_MODEL
        # Modèle unifié v7 (fallback)
        self._fallback: Optional[dict] = None   # {model, feature_names}
        # Modèles per-asset v13
        self._per_asset: dict = {}  # asset_name -> {model, feature_names}

    @property
    def is_loaded(self) -> bool:
        return self._fallback is not None

    def load(self) -> bool:
        """Charge tous les modèles (fallback v7 + 4 per-asset v13)."""
        # Fallback v7 uniforme
        if self._fallback is not None:
            return True  # déjà chargé

        if not os.path.isfile(self._fallback_path):
            logger.warning("Modele fallback v7 introuvable: %s", self._fallback_path)
            return False

        try:
            bundle = joblib.load(self._fallback_path)
            self._fallback = {
                "model": bundle.get("model"),
                "feature_names": bundle.get("feature_names", []),
            }
            logger.info("Fallback v7 charge: %s (%d features)",
                        self._fallback_path, len(self._fallback["feature_names"] or []))
        except Exception as e:
            logger.error("Erreur chargement fallback v7: %s", e)
            return False

        # Per-asset v13 models (non-bloquant: pas de crash si 1 modele manque)
        loaded_count = 0
        for asset_type, model_path in self._ASSET_MODEL_MAP.items():
            if not os.path.isfile(model_path):
                logger.debug("Modele per-asset %s introuvable: %s", asset_type, model_path)
                continue
            try:
                bundle = joblib.load(model_path)
                self._per_asset[asset_type] = {
                    "model": bundle.get("model"),
                    "feature_names": bundle.get("feature_names", []),
                }
                loaded_count += 1
            except Exception as e:
                logger.warning("Erreur chargement modele %s: %s", asset_type, e)

        logger.info("Per-asset v13: %d/4 modeles charges", loaded_count)
        return True

    def _get_model_for_asset(self, asset_type: str):
        """Retourne (model, feature_names) pour un type d'actif,
        ou le fallback v7 si non disponible."""
        entry = self._per_asset.get(asset_type)
        if entry and entry.get("model") is not None:
            return entry["model"], entry["feature_names"]
        # Fallback v7
        if self._fallback:
            return self._fallback["model"], self._fallback["feature_names"]
        return None, None

    def predict(self, result) -> Optional[float]:
        """Prédit la probabilité de trade gagnant pour un DiamondResult.

        Sélectionne automatiquement le modèle per-asset correspondant au symbole.
        Si le modèle per-asset n'est pas disponible, utilise le fallback v7 unifié.

        Args:
            result: Instance de DiamondResult.

        Returns:
            Probabilité entre 0.0 et 1.0, ou None si aucun modèle chargé.
        """
        if not self.is_loaded and not self.load():
            return None

        features = extract_features(result)
        symbol = (getattr(result, "symbol", "") or "").upper()
        asset_type = _classify_asset(symbol)

        model, fnames = self._get_model_for_asset(asset_type)
        if model is None:
            return None

        # Aligner l'ordre des features avec celui du modèle
        if fnames:
            ordered = [features.get(name, 0.0) for name in fnames]
        else:
            ordered = list(features.values())

        try:
            import numpy as np
            X = np.array([ordered], dtype=np.float32)
            proba = model.predict_proba(X)[0]
            # proba[0] = probabilité classe 0 (perdant), proba[1] = classe 1 (gagnant)
            return float(proba[1]) if len(proba) > 1 else float(proba[0])
        except Exception as e:
            logger.error("Erreur prediction ML (%s): %s", asset_type, e)
            return None
