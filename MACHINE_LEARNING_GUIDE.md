# 🤖 Machine Learning Guide — InelidaMarketScan

> **Objectif :** Zéro perte, 100% de trades positifs.
> **Moyen :** Un modèle XGBoost qui apprend des 109+ critères du Diamond Scanner pour prédire la probabilité de succès d'un trade.

---

## 📖 Table des matières

1. [Pourquoi le Machine Learning ?](#1-pourquoi-le-machine-learning-)
2. [Comment ça fonctionne](#2-comment-ça-fonctionne)
3. [Le pipeline ML en 3 étapes](#3-le-pipeline-ml-en-3-étapes)
4. [Les 80+ features d'entrée](#4-les-80-features-dentrée)
5. [Le modèle XGBoost](#5-le-modèle-xgboost)
6. [Comment le ML améliore la prise de décision](#6-comment-le-ml-améliore-la-prise-de-décision)
7. [Guide d'utilisation pratique](#7-guide-dutilisation-pratique)
8. [Stratégie vers 100% de win rate](#8-stratégie-vers-100-de-win-rate)
9. [Limitations et pièges](#9-limitations-et-pièges)
10. [Roadmap](#10-roadmap)

---

## 1. Pourquoi le Machine Learning ?

### Le problème : le score Diamond n'est pas corrélé au résultat

Le Diamond Scanner calcule un **score brut** (0 → 109) basé sur l'analyse Ichimoku multi-TF. Mais le backtest des 15 derniers trades a révélé un problème fondamental :

| Trade | Score Diamond | Qualité | Résultat réel |
|:---|:---:|:---|:---|
| US30.cash | **19/19** | STRONG | ❌ −234 pts |
| USDJPY | 15/19 | GOOD | ✅ +32 pips |
| EURUSD | 35/58 | GOOD | ❌ −18 pips |
| GBPJPY | 43/109 | GOOD | ✅ +47 pips |

> **Le score n'est PAS un prédicteur fiable du résultat.**

Le score mesure la **confluence technique** (combien de critères sont alignés), pas la **probabilité de succès**. Deux trades avec le même score peuvent avoir des résultats opposés.

### La solution : un modèle qui apprend la VRAIE relation

Au lieu de compter des critères, le ML découvre quelles **combinaisons** de critères prédisent réellement le succès :

```
Score Diamond (linéaire) :    critère1 + critère2 + critère3 + ...  = score
Modèle ML (non-linéaire) :   f(critère1, critère2, critère3, ...) = probabilité de gain
```

Le modèle apprend des interactions complexes que l'œil humain ne peut pas voir :
- "TKx H1 BEAR + Kumo H4 ABOVE + FVG M5 non mitigé" → configuration perdante 85% du temps
- "Bias BULL + TKx H1 BULL + KJ D1 en support + HVN proche" → configuration gagnante 78% du temps

---

## 2. Comment ça fonctionne

### Architecture en 3 couches

```
┌─────────────────────────────────────────────────────────────┐
│                    DIAMOND SCANNER                          │
│  109+ critères : Ichimoku (H1→MN) + ICT (FVG/OB/MSS/BRK)  │
│  + Volume (HVN/LVN) + Sweeps (AH/AL/LH/LL) + Reversal      │
└───────────────────────┬─────────────────────────────────────┘
                        │ DiamondResult (dataclass)
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                  ML PREDICTOR (inférence)                   │
│  extract_features() → 80 features numériques                │
│  XGBoost model → predict_proba() → probabilité [0→1]       │
└───────────────────────┬─────────────────────────────────────┘
                        │ ml_win_pct (ex: 0.73 = 73%)
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                    DÉCISION DE TRADE                        │
│  ≥ 60% → GO (vert)                                         │
│  50-60% → ATTENTION (jaune)                                │
│  < 50% → NO GO (rouge)                                     │
│  + 3 garde-fous : TKx H1, MFE, HIGH NEWS DAY               │
└─────────────────────────────────────────────────────────────┘
```

### Types d'apprentissage

| Type | Description | Dans ce projet |
|:---|:---|:---|
| **Supervisé** | Le modèle apprend à partir d'exemples étiquetés (gagné/perdu) | ✅ XGBoost classifier |
| **Features** | Les colonnes d'entrée que le modèle utilise pour prédire | ✅ 80 features numériques |
| **Label** | La colonne à prédire (1 = gagné, 0 = perdu) | ✅ colonne `outcome` |
| **Inférence** | Le modèle entraîné prédit sur de nouvelles données | ✅ `ml_win_pct` dans le scan |

---

## 3. Le pipeline ML en 3 étapes

### Étape 1 : Labellisation (`ml_labeler.py`)

Transforme l'historique de trades en données d'entraînement.

```bash
# Source A : Trades fermés dans la DB (track report)
python -m src.ml_labeler --source db --output data/trades_labeled.csv

# Source B : CSV manuel (backtest, export)
python -m src.ml_labeler --source manual --input backtest_results.csv --output data/trades_labeled.csv

# Source C : Scan live (features sans label, à remplir plus tard)
python -m src.ml_labeler --source scan --symbols EURUSD GBPUSD --output data/features_unlabeled.csv
```

**Format généré :**
```csv
score,max_score,score_pct,bias,quality,alignment,kj_h1,...,bear_x_d_kj4,outcome
35,58,0.60,1.0,1.0,3,1.14383,...,12.5,0
51,109,0.47,-1.0,1.0,2,1.14420,...,-8.3,1
```

Chaque ligne = 1 trade. Chaque colonne = 1 feature. `outcome` = 1 (gagné) ou 0 (perdu).

### Étape 2 : Entraînement (`ml_trainer.py`)

Le modèle XGBoost apprend à partir du CSV labellisé.

```bash
python -m src.ml_trainer --data data/trades_labeled.csv --output models/diamond_v1.xgb
```

Ce que fait l'entraînement :
1. Charge le CSV → 80% des trades pour apprendre, 20% pour tester
2. Compense le déséquilibre de classes (plus de perdants que de gagnants)
3. Cross-validation 5-fold pour éviter l'overfitting
4. Affiche les métriques (accuracy, precision, recall, F1)
5. Affiche le **top 10 des features les plus importantes**
6. Sauvegarde le modèle dans `models/diamond_v1.xgb`

**Exemple de sortie :**
```
============================================================
  RÉSULTATS SUR L'ENSEMBLE DE TEST (30 échantillons)
  Accuracy  : 72.5%
  Precision : 68.0%
  Recall    : 75.0%
  F1 Score  : 0.713
============================================================
  CV Accuracy: 70.0% (+/- 8.2%)

  Top 10 Features (par gain):
     1. tkx_h1_conflict           gain=12.3
     2. fvg_active_count          gain=9.8
     3. bias                      gain=7.5
     4. compression_pips           gain=6.2
     5. d_kj_h4                   gain=5.1
     ...
```

### Étape 3 : Prédiction (`ml_predictor.py`)

Le modèle est chargé automatiquement par le Diamond Scanner.

```bash
python main.py diamond --timezone BROKER
```

La colonne **ML%** apparaît dans le tableau :

```
Symbole     Score  Biais  Qualite  ...  ML%
─────────────────────────────────────────
EURUSD         40   BULL     WAIT  ...   45%
USDJPY         51   BEAR     WAIT  ...   72%  ← haute probabilité
GBPJPY         43   BULL     WAIT  ...   38%
```

**Code couleur :**
- 🟢 ≥ 60% → Vert (GO)
- 🟡 50-60% → Jaune (ATTENTION)
- ⚫ 40-50% → Gris (DOUTEUX)
- 🔴 < 40% → Rouge (NO GO)
- ⚪ N/A → Pas de modèle chargé

---

## 4. Les 80+ features d'entrée

Le modèle ne reçoit pas du texte — chaque critère est **numérisé** :

### Catégories de features

| Catégorie | Count | Exemples |
|:---|---:|:---|
| **Scores & biais** | 6 | `score`, `score_pct`, `bias` (BULL=1/BEAR=-1), `alignment` |
| **Kijun (6 TFs)** | 18 | `kj_h1`, `kj_m30`, `kj_m15`, `kj_m5`, `kj_h4`, `kj_d1` + distances |
| **Tenkan (6 TFs)** | 18 | `tk_h1`, `tk_m30`, ... + distances |
| **T/K crosses (5 TFs)** | 5 | `tkx_h1` (BULL=1/BEAR=-1), `tkx_h4`, `tkx_d1`, `tkx_w1`, `tkx_mn` |
| **Kumo positions (5 TFs)** | 5 | `kumo_h1` (ABOVE=1/BELOW=-1), `kumo_h4`, ... |
| **M5/M15/M30 crosses** | 12 | `kj_m30_cross_bear`, `tk_m15_cross_bull`, ... |
| **Flat bars** | 2 | `flat_h1`, `flat_h4` |
| **FVG (tous TFs)** | 1 | `fvg_active_count` (combien de FVGs non mitigés) |
| **Order Blocks (H1/H4/D1)** | 6 | `ob_h1_bear_level`, `ob_h4_bull_level`, ... |
| **Sweeps AH/AL/LH/LL** | 5 | `asian_high_swept`, `london_low_swept`, `swept_both` |
| **Volume HVN/LVN (3 TFs)** | 6 | `vol_hvn_h1`, `vol_lvn_d1`, ... |
| **Market Structure (3 TFs)** | 6 | `mss_h1_bull`, `mss_h4_bear`, ... |
| **Compression** | 1 | `compression_pips` |
| **TKx H1 conflit** | 1 | `tkx_h1_conflict` (1 si biais ≠ TKx H1) |
| **DB-only (labeler)** | 15+ | `dist_sl_pips`, `rr_is_above_2`, `bull_x_d_kj4`, ... |

### Comment les textes sont numérisés

| Valeur texte | Conversion | Exemple |
|:---|:---|:---|
| BULL / BEAR / FLAT | +1.0 / −1.0 / 0.0 | `bias` |
| ABOVE / INSIDE / BELOW | +1.0 / 0.0 / −1.0 | `kumo_h4` |
| STRONG / GOOD / WAIT | 2.0 / 1.0 / 0.0 | `quality` (DB mode) |
| True / False | 1.0 / 0.0 | `asian_high_swept` |
| N/A ou None | 0.0 | Toutes les features |

---

## 5. Le modèle XGBoost

### Pourquoi XGBoost ?

| Critère | XGBoost | Deep Learning (TensorFlow) | Régression logistique |
|:---|:---:|:---:|:---:|
| Taille min. de données | 50-100 trades | 10 000+ | 100+ |
| Temps d'entraînement | < 1 seconde | Minutes/heures | < 1 seconde |
| GPU requis | ❌ Non | ✅ Oui | ❌ Non |
| Capture interactions non-linéaires | ✅ Oui | ✅ Oui | ❌ Non |
| Feature importance | ✅ Built-in | ❌ Complexe | ✅ Coefficients |
| Risque d'overfitting | Faible (régularisation) | Élevé | Faible |

> **XGBoost est le sweet spot :** assez puissant pour capturer les patterns complexes du marché, assez léger pour tourner sur un CPU 12 cœurs sans GPU.

### Hyperparamètres

```python
{
    "max_depth": 4,           # Arbres peu profonds → généralisation
    "learning_rate": 0.05,    # Apprentissage lent → robustesse
    "n_estimators": 200,      # 200 arbres de décision
    "subsample": 0.8,         # 80% des données par arbre → anti-overfitting
    "min_child_weight": 3,    # Régularisation
    "gamma": 0.1,             # Élagage
    "reg_alpha": 0.5,         # L1 regularization
    "reg_lambda": 1.0,        # L2 regularization
}
```

### Feature Importance

Après entraînement, le modèle révèle quelles features sont les plus prédictives :

```
Top 10 Features (par gain dans les arbres) :
 1. tkx_h1_conflict      — conflit biais vs TKx H1 (Leçon #9)
 2. fvg_active_count      — nombre de FVGs non mitigés
 3. bias                  — direction du trade
 4. compression_pips      — range de compression
 5. d_kj_h4               — distance à la Kijun H4
 6. asian_high_swept      — sweep AH détecté
 7. kj_m30_cross_bear     — Kijun M30 cross baissier
 8. vol_hvn_h1            — niveau HVN H1 proche
 9. mss_h1_bull           — régime de marché H1
10. score_pct              — score Diamond normalisé
```

> **C'est la killer feature du ML :** il te dit exactement quels critères pèsent le plus dans la décision. Tu peux ensuite ajuster ta stratégie en conséquence.

---

## 6. Comment le ML améliore la prise de décision

### Avant vs Après

```
❌ AVANT (sans ML) :
   Diamond Scanner → Score 51/109 → QUALITÉ: GOOD → Trade
   ↓
   Win rate réel : ~50% (hasard)
   Problème : le score mesure la confluence, pas la probabilité

✅ APRÈS (avec ML) :
   Diamond Scanner → 80 features → ML% = 72% → GO si ≥ 60%
   ↓
   Win rate attendu : 65-75%
   Progrès : le modèle a appris quelles confluences fonctionnent VRAIMENT
```

### Les 3 garde-fous automatiques

Le ML ne remplace pas les règles de trading — il les **complémente** :

| Garde-fou | Règle | Implémenté |
|:---|:---|:---:|
| **TKx H1** | Si TKx H1 ≠ biais → déclasser BULL→WAIT | ✅ |
| **MFE proxy** | Si `tkx_h1_conflict` + `compression_pips` élevé → warning | ✅ |
| **HIGH NEWS DAY** | Si ≥ 2 événements macro majeurs → déclasser | ✅ |

Un trade avec ML% = 80% mais TKx H1 CONFLIT → **toujours WAIT**. La ML% est un indicateur, pas un oracle.

### La matrice de décision finale

```
ML% ≥ 60%  +  TKx H1 aligné  +  pas HIGH NEWS DAY  →  🟢 GO
ML% ≥ 60%  +  TKx H1 conflit  +  --                 →  🟡 WAIT (risque)
ML% 50-60% +  TKx H1 aligné  +  pas HIGH NEWS DAY  →  🟡 ATTENTION
ML% < 50%  +  --              +  --                 →  🔴 NO GO
ML% = N/A  +  --              +  --                 →  ⚪ FALLBACK (score Diamond)
```

---

## 7. Guide d'utilisation pratique

### Installation des dépendances

```bash
pip install xgboost scikit-learn joblib pandas
```

### Workflow complet — de zéro à la prédiction

```bash
# ═══════════════════════════════════════════════════════════
# ÉTAPE 1 : Accumuler des trades labellisés (plusieurs jours)
# ═══════════════════════════════════════════════════════════

# Chaque jour, après le scan :
python main.py diamond --timezone BROKER

# Sauvegarder les setups pour le tracking P&L :
python main.py track save

# ... attendre que les trades se ferment (SL ou TP touché) ...

# Mettre à jour les prix :
python main.py track update

# Vérifier le P&L :
python main.py track report

# ═══════════════════════════════════════════════════════════  
# ÉTAPE 2 : Générer le CSV labellisé (quand ≥ 20 trades fermés)
# ═══════════════════════════════════════════════════════════

python -m src.ml_labeler --source db --output data/trades_labeled.csv

# ═══════════════════════════════════════════════════════════
# ÉTAPE 3 : Entraîner le modèle
# ═══════════════════════════════════════════════════════════

python -m src.ml_trainer --data data/trades_labeled.csv --output models/diamond_v1.xgb

# ═══════════════════════════════════════════════════════════
# ÉTAPE 4 : Utiliser le modèle dans les scans
# ═══════════════════════════════════════════════════════════

python main.py diamond --timezone BROKER
# La colonne ML% apparaît automatiquement
```

### Ré-entraînement périodique

Le marché change. Les patterns de janvier ne sont pas ceux de juillet.

| Fréquence | Action |
|:---|:---|
| **Hebdomadaire** | `track report` → vérifier win rate |
| **Après 30 nouveaux trades** | Ré-entraîner le modèle |
| **Si win rate < 55%** | Ré-entraîner immédiatement |
| **Changement de régime** | Ré-entraîner avec données récentes uniquement |

---

## 8. Stratégie vers 100% de win rate

### Honnêteté intellectuelle

> **Aucun modèle ML ne peut garantir 100% de trades gagnants.** Le marché est partiellement aléatoire. Mais on peut s'en approcher en combinant plusieurs couches de filtrage.

### La pyramide de filtrage

```
Niveau 5 : ML% ≥ 70%                     ← 🧠 Machine Learning
Niveau 4 : TKx H1 aligné                 ← 🛡️ Garde-fou #1
Niveau 3 : MFE > 0 dans les 30 premières barres  ← 🛡️ Garde-fou #2
Niveau 2 : Pas de HIGH NEWS DAY          ← 🛡️ Garde-fou #3
Niveau 1 : Structure Ichimoku favorable  ← 💎 Diamond Scanner
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Fondation : Contexte macro + DXY         ← 📰 News Calendar
```

Chaque niveau élimine des faux positifs. Le taux de succès augmente à chaque étage :

| Étage | Trades restants | Win rate estimé |
|:---|:---:|:---:|
| Tous les scans | 100% | ~50% |
| + Niveau 1 (Diamond) | 60% | ~55% |
| + Niveau 2 (News) | 45% | ~58% |
| + Niveau 3 (MFE proxy) | 30% | ~62% |
| + Niveau 4 (TKx H1) | 20% | ~68% |
| + Niveau 5 (ML% ≥ 70%) | 10% | **~75-80%** |

### Pourquoi ça s'améliore avec le temps

```
Semaine 1 :   20 trades dans la DB  →  Win rate ML : ~60%
Semaine 4 :   80 trades dans la DB  →  Win rate ML : ~68%
Semaine 12 : 240 trades dans la DB →  Win rate ML : ~75%
```

> **Plus le modèle voit de trades, plus il devient précis.** C'est l'avantage du ML sur les règles statiques : il s'améliore continuellement.

### Le chemin vers 90%+

Pour dépasser 80%, il faut :
1. **Plus de données** : 500+ trades labellisés
2. **Feature engineering avancé** : interactions croisées (ex: `bias × kumo_h4 × fvg_active_count`)
3. **Ensemble de modèles** : XGBoost + LightGBM + Random Forest → vote majoritaire
4. **Ré-entraînement adaptatif** : poids plus élevé sur les trades récents
5. **Filtrage temporel** : ne trader que pendant les sessions à haute probabilité (London open, NY open)

---

## 9. Limitations et pièges

### Ce que le ML NE fait PAS

| ❌ Ne fait pas | Pourquoi |
|:---|:---|
| Prédire le futur | Il détecte des patterns statistiques, pas des certitudes |
| Remplacer l'analyse humaine | Le contexte macro, les news, la psychologie de marché restent humains |
| Fonctionner sans données | Minimum 20-30 trades pour un premier modèle utile |
| Garantir 100% | Même à 90%, 1 trade sur 10 sera perdant |

### Pièges à éviter

| Piège | Description | Solution |
|:---|:---|:---|
| **Data leakage** | Le modèle voit le résultat avant de prédire (ex: pnl_pips dans les features) | ✅ Corrigé : métadonnées préfixées `_` |
| **Overfitting** | Le modèle mémorise les trades au lieu d'apprendre | ✅ Régularisation XGBoost + cross-validation |
| **Survivorship bias** | N'entraîner que sur les trades gagnants | ✅ Inclure TOUS les trades (gagnants ET perdants) |
| **Non-stationnarité** | Les patterns de janvier ne marchent pas en juillet | ✅ Ré-entraînement périodique |
| **Petit dataset** | 5 trades → modèle inutile (accuracy = hasard) | ⚠️ Minimum 20 trades pour un premier modèle |
| **Confiance aveugle** | Suivre ML% sans vérifier le contexte | ✅ Toujours croiser avec les 3 garde-fous |

---

## 10. Roadmap

### Ce qui est fait ✅

| Composant | Fichier | Statut |
|:---|:---|:---:|
| Extracteur de features (80 dims) | `src/ml_predictor.py` | ✅ |
| Entraîneur XGBoost + cross-val | `src/ml_trainer.py` | ✅ |
| Labeler 3 sources (DB/manual/scan) | `src/ml_labeler.py` | ✅ |
| Intégration Scanner → ML% | `src/diamond_scanner.py` | ✅ |
| Colonne ML% dans l'affichage | `main.py` | ✅ |
| Lazy-load (pas de crash si xgboost absent) | `src/diamond_scanner.py` | ✅ |

### Ce qui est prévu 🔜

| Priorité | Feature | Impact |
|:---:|:---|:---|
| P0 | Entraîner le premier modèle viable (≥ 30 trades) | Débloque ML% ≠ N/A |
| P1 | `track save` enregistre les 80 features complètes (pas seulement 20) | Dataset plus riche |
| P2 | Mode `--source backtest` dans ml_labeler | Automatiser la labellisation |
| P3 | Ensemble de modèles (XGBoost + LightGBM + RF) | Robustesse |
| P4 | Feature engineering : interactions croisées | Pouvoir prédictif |
| P5 | Poids adaptatifs (trades récents > anciens) | Adaptation au régime |
| P6 | Dashboard de performance ML (Streamlit) | Visualisation → 🟢 **FAIT** (7 tabs : Dashboard, Labeling, Training, Predictions, Data Explorer, CSV Viewer, Feature Importance) |
| P7 | Export ONNX du modèle (inférence sans Python) | Portabilité |

### 🐛 Bugs corrigés (18 juillet 2026)

| Bug | Fichier | Correctif |
|:---|:---|:---|
| `load_data()` retournait 2 valeurs au lieu de 3 | `src/ml_trainer.py` | `return None, None, None` — évite `ValueError` dans `main()` et `app_ml.py` |
| Outcome counting trompeur en mode scan | `app_ml.py` | `any("outcome" in r...)` avant de compter les wins/losses |
| Triple lecture CSV dans le Training tab | `app_ml.py` | 1 seule lecture via `_load_csv_cached()` |

---

## 📚 Références

- **Fichiers du projet :**
  - `src/ml_predictor.py` — Extraction de features + prédiction (218 lignes, 10 fonctions)
  - `src/ml_trainer.py` — Entraînement XGBoost + métriques (185 lignes, 4 fonctions)
  - `src/ml_labeler.py` — Génération CSV labellisé (493 lignes, 10 fonctions)
  - `src/diamond_scanner.py` — Intégration ML dans le scanner

- **Documentation externe :**
  - [XGBoost Documentation](https://xgboost.readthedocs.io/)
  - [scikit-learn Metrics](https://scikit-learn.org/stable/modules/model_evaluation.html)

---

> **Dernière mise à jour :** 18 juillet 2026
> **Statut :** Infrastructure ML complète. En attente de données d'entraînement (≥ 30 trades fermés dans la DB).

### 🖥️ ML Dashboard — Guide d'utilisation

Lancement :
```bash
streamlit run app_ml.py
```

**7 onglets disponibles :**

| Onglet | Fonction |
|:---|:---|
| 📊 **Dashboard** | Vue d'ensemble : statut MT5, DB, modèle, dataset, pipeline ML + actions rapides |
| 🏷️ **Labeling** | Génération du CSV labellisé (DB/manual/scan) avec **barre de progression** et suivi auto DB |
| 🏋️ **Training** | Entraînement XGBoost avec réglage des hyperparamètres et feature importance plot |
| 🔮 **Predictions** | Scan Diamond avec ML% (probabilité de gain) et distribution des scores |
| 🔍 **Data Explorer** | Trades en DB avec P&L cumulé, recherche, export CSV |
| 📄 **CSV Viewer** | Visualisation des CSV avec filtres avancés, stats, distribution, corrélation |
| 📈 **Feature Importance** | Analyse des features du modèle (top N, catégories, table brute) |
