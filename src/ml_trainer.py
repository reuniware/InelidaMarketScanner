"""
ML Trainer — Entraîne un modèle XGBoost à partir de trades labellisés.

Lit un CSV contenant les features Diamond + le résultat du trade (gagné/perdu),
entraîne un classifieur XGBoost, et sauvegarde le modèle.

Format CSV attendu :
    Chaque ligne = 1 trade. Colonnes = features numériques + colonne "outcome" (1=gagné, 0=perdu).

Usage:
    python -m src.ml_trainer --data data/trades_labeled.csv --output models/diamond_v1.xgb
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import cross_val_score, train_test_split

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger("MLTrainer")

# Paramètres XGBoost par défaut — optimisés pour petits datasets (50-500 échantillons)
DEFAULT_PARAMS = {
    "objective": "binary:logistic",
    "eval_metric": "logloss",
    "max_depth": 4,           # Peu profond pour éviter l'overfitting
    "learning_rate": 0.05,    # Lent pour généraliser
    "n_estimators": 200,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 3,    # Régularisation
    "gamma": 0.1,
    "reg_alpha": 0.5,
    "reg_lambda": 1.0,
    "random_state": 42,
}


def load_data(csv_path: str):
    """Charge le CSV de trades labellisés. Dernière colonne = outcome."""
    if not os.path.isfile(csv_path):
        logger.error("Fichier introuvable: %s", csv_path)
        return None, None, None

    df = pd.read_csv(csv_path)
    logger.info("Données chargées: %d trades × %d colonnes", len(df), len(df.columns))

    if "outcome" not in df.columns:
        logger.error("Colonne 'outcome' manquante dans le CSV.")
        return None, None, None

    # Filtrer les lignes sans outcome (NaN, vide, ou NULL)
    # Important: le mode scan génère des outcomes vides (à remplir manuellement)
    before = len(df)
    df = df.dropna(subset=["outcome"])
    # Supprimer les lignes où outcome est une string vide
    df = df[df["outcome"].astype(str).str.strip() != ""]
    # Convertir en numérique et forcer 0/1
    df["outcome"] = pd.to_numeric(df["outcome"], errors="coerce")
    df = df.dropna(subset=["outcome"])
    # Garder uniquement 0.0 ou 1.0
    df = df[df["outcome"].isin([0.0, 1.0])]

    after = len(df)
    n_filtered = before - after
    if n_filtered > 0:
        logger.warning("%d ligne(s) sans outcome valide filtrée(s) (sur %d total)", n_filtered, before)

    if df.empty:
        logger.error("Aucune ligne avec outcome valide (0 ou 1) dans le CSV.")
        logger.info("Pour le mode scan: remplis la colonne 'outcome' manuellement avant d'entraîner.")
        return None, None, None

    y = df.pop("outcome").values.astype(int)
    feature_names = list(df.columns)
    X = df.values.astype(np.float32)

    # Nettoyage: remplacer NaN/Inf par 0
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    classes = np.unique(y)
    logger.info("  Classes: %s (1=gagné, 0=perdu)", dict(zip(*np.unique(y, return_counts=True))))

    # Vérifier qu'on a au moins 2 classes pour l'entraînement binaire
    if len(classes) < 2:
        logger.error(
            "Pas assez de classes pour l'entraînement binaire. "
            "Trouvé: %s. Attendu: [0 1]. "
            "Ajoute des trades perdants (outcome=0) ou gagnants (outcome=1) au dataset.",
            classes
        )
        return None, None, None

    return X, y, feature_names


def train(X, y, feature_names, test_size: float = 0.2,
          params_override: Optional[Dict[str, Any]] = None):
    """Entraîne le modèle et retourne les métriques.

    Args:
        X: Matrice de features.
        y: Vecteur des outcomes (0/1).
        feature_names: Noms des colonnes de features.
        test_size: Fraction de l'ensemble de test.
        params_override: Dictionnaire optionnel pour surcharger les hyperparamètres
                         DEFAULT_PARAMS. Évite de muter le module global.

    Returns:
        (model, feature_names, metrics)
    """
    if len(X) < 10:
        logger.warning("Seulement %d échantillons — entraînement peu fiable.", len(X))

    # Split train/test (gère les très petits datasets)
    if len(X) < 2:
        # Pas de split possible — on entraîne sur 100% des données
        logger.warning("Seulement %d échantillon — pas de split train/test", len(X))
        X_train, X_test, y_train, y_test = X, X, y, y
        actual_test_size = 0.0
    elif len(X) < 5:
        # Très petit dataset : split minimal (1 test échantillon si possible)
        n_test = max(1, int(len(X) * test_size))
        n_test = min(n_test, len(X) - 1)  # Garder au moins 1 pour le train
        actual_test_size = n_test / len(X)
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=actual_test_size, random_state=42,
            stratify=y if len(np.unique(y)) > 1 else None
        )
    else:
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=42,
            stratify=y if len(np.unique(y)) > 1 else None
        )
        actual_test_size = test_size

    # Poids de classe pour compenser le déséquilibre
    scale_pos_weight = (len(y_train) - sum(y_train)) / max(sum(y_train), 1)

    # Fusionner les params par défaut avec les overrides (sans muter le module)
    merged_params = {**DEFAULT_PARAMS, "scale_pos_weight": scale_pos_weight}
    if params_override:
        merged_params.update(params_override)

    model = xgb.XGBClassifier(
        **merged_params,
        early_stopping_rounds=20,
    )

    logger.info("Entraînement XGBoost (%d features, %d échantillons)...", len(feature_names), len(X_train))
    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=False,
    )

    # ── Métriques ──
    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1] if model.classes_.size > 1 else y_pred

    acc = accuracy_score(y_test, y_pred)
    prec = precision_score(y_test, y_pred, zero_division=0)
    rec = recall_score(y_test, y_pred, zero_division=0)
    f1 = f1_score(y_test, y_pred, zero_division=0)

    logger.info("=" * 60)
    logger.info("  RÉSULTATS SUR L'ENSEMBLE DE TEST (%d échantillons)", len(X_test))
    logger.info("  Accuracy  : %.1f%%", acc * 100)
    logger.info("  Precision : %.1f%%", prec * 100)
    logger.info("  Recall    : %.1f%%", rec * 100)
    logger.info("  F1 Score  : %.3f", f1)
    logger.info("=" * 60)

    # Cross-validation (si assez de données)
    if len(X) >= 30:
        cv_scores = cross_val_score(model, X, y, cv=min(5, len(X) // 5), scoring="accuracy")
        logger.info("  CV Accuracy: %.1f%% (+/- %.1f%%)", cv_scores.mean() * 100, cv_scores.std() * 100)

    # Matrice de confusion
    cm = confusion_matrix(y_test, y_pred)
    logger.info("  Matrice de confusion:")
    logger.info("                Prédit PERDU  Prédit GAGNÉ")
    logger.info("  Vrai PERDU        %4d          %4d", cm[0, 0] if cm.shape[0] > 0 else 0, cm[0, 1] if cm.shape[0] > 0 and cm.shape[1] > 1 else 0)
    logger.info("  Vrai GAGNÉ        %4d          %4d", cm[1, 0] if cm.shape[0] > 1 else 0, cm[1, 1] if cm.shape[0] > 1 and cm.shape[1] > 1 else 0)

    # ── Feature importance ──
    importance = model.get_booster().get_score(importance_type="gain")
    if importance:
        importance_sorted = sorted(importance.items(), key=lambda x: x[1], reverse=True)
        logger.info("")
        logger.info("  Top 10 Features (par gain):")
        for i, (fname, gain) in enumerate(importance_sorted[:10]):
            logger.info("    %2d. %-25s  gain=%.1f", i + 1, fname, gain)

    return model, feature_names, {
        "accuracy": acc,
        "precision": prec,
        "recall": rec,
        "f1": f1,
        "n_train": len(X_train),
        "n_test": len(X_test),
    }


def save_model(model, feature_names, output_path: str) -> str:
    """Sauvegarde le modèle + métadonnées."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    bundle = {
        "model": model,
        "feature_names": feature_names,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "framework": "xgboost",
        "version": xgb.__version__,
    }
    joblib.dump(bundle, output_path)
    size_kb = os.path.getsize(output_path) / 1024
    logger.info("Modèle sauvegardé: %s (%.0f KB)", output_path, size_kb)
    return output_path


def main():
    parser = argparse.ArgumentParser(description="ML Trainer — Entraîne un modèle XGBoost pour Diamond Scanner")
    parser.add_argument("--data", required=True, help="CSV des trades labellisés (colonnes features + outcome)")
    parser.add_argument("--output", default="models/diamond_v1.xgb", help="Chemin de sortie du modèle")
    parser.add_argument("--test-size", type=float, default=0.2, help="Fraction test (défaut: 0.2)")
    args = parser.parse_args()

    X, y, feature_names = load_data(args.data)
    if X is None:
        return 1

    model, feature_names, metrics = train(X, y, feature_names, test_size=args.test_size)
    save_model(model, feature_names, args.output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
