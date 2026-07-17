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
import os
from typing import Optional

import joblib

logger = logging.getLogger("MLPredictor")

# Chemin par défaut du modèle entraîné
_MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")
_DEFAULT_MODEL = os.path.join(_MODEL_DIR, "diamond_v1.xgb")


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


def extract_features(result) -> dict:
    """Extrait un vecteur de features numériques depuis un DiamondResult.

    Args:
        result: Instance de DiamondResult (ou n'importe quel objet avec les mêmes attributs).

    Returns:
        Dictionnaire {nom_feature: valeur_float} prêt pour la prédiction.
    """
    feats = {}

    # ── Prix et scores ──
    feats["price"] = _safe_float(getattr(result, "price", 0))
    feats["score"] = _safe_float(getattr(result, "score", 0))
    feats["max_score"] = _safe_float(getattr(result, "max_score", 109))
    feats["score_pct"] = feats["score"] / max(feats["max_score"], 1.0)
    feats["bias"] = _bias_to_float(getattr(result, "bias", "FLAT"))
    feats["alignment"] = _safe_float(getattr(result, "alignment", 0))

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

    return feats


class MLPredictor:
    """Prédicteur ML chargé depuis un fichier modèle XGBoost entraîné."""

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path or _DEFAULT_MODEL
        self._model = None
        self._feature_names = None

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> bool:
        """Charge le modèle depuis le disque. Retourne True si OK."""
        if self._model is not None:
            return True

        if not os.path.isfile(self.model_path):
            logger.warning("Modèle ML introuvable: %s", self.model_path)
            return False

        try:
            bundle = joblib.load(self.model_path)
            self._model = bundle.get("model")
            self._feature_names = bundle.get("feature_names", [])
            logger.info("Modèle ML chargé: %s (%d features)", self.model_path, len(self._feature_names or []))
            return True
        except Exception as e:
            logger.error("Erreur chargement modèle ML: %s", e)
            return False

    def predict(self, result) -> Optional[float]:
        """Prédit la probabilité de trade gagnant pour un DiamondResult.

        Args:
            result: Instance de DiamondResult.

        Returns:
            Probabilité entre 0.0 et 1.0, ou None si modèle non chargé.
        """
        if not self.is_loaded and not self.load():
            return None

        features = extract_features(result)

        # Aligner l'ordre des features avec celui du modèle entraîné
        if self._feature_names:
            ordered = [features.get(name, 0.0) for name in self._feature_names]
        else:
            ordered = list(features.values())

        try:
            import numpy as np
            X = np.array([ordered], dtype=np.float32)
            proba = self._model.predict_proba(X)[0]
            # proba[0] = probabilité classe 0 (perdant), proba[1] = classe 1 (gagnant)
            return float(proba[1]) if len(proba) > 1 else float(proba[0])
        except Exception as e:
            logger.error("Erreur prédiction ML: %s", e)
            return None
