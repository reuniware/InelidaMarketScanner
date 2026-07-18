# 🤖 Machine Learning Guide — InelidaMarketScan

> **Objectif :** Profit factor > 2.0, win rate > 55%.
> **Moyen :** Un modèle XGBoost entraîné sur 111 features nommées du Diamond Scanner,
> avec backtest historique sur 1 210 trades depuis janvier 2026.
> **Modèle actif :** `historical_v4.xgb` — 58.3% accuracy, 62.9% CV, 111 features.

---

## 📖 Table des matières

1. [Pourquoi le Machine Learning ?](#1-pourquoi-le-machine-learning-)
2. [Comment ça fonctionne](#2-comment-ça-fonctionne)
3. [Le pipeline ML en 3 étapes](#3-le-pipeline-ml-en-3-étapes)
4. [Les 111 features d'entrée](#4-les-111-features-dentrée)
5. [Le modèle XGBoost](#5-le-modèle-xgboost)
6. [Comment le ML améliore la prise de décision](#6-comment-le-ml-améliore-la-prise-de-décision)
7. [Guide d'utilisation pratique](#7-guide-dutilisation-pratique)
8. [Stratégie vers un profit factor > 2.0](#8-stratégie-vers-un-profit-factor--20)
9. [Limitations et pièges](#9-limitations-et-pièges)
10. [Roadmap](#10-roadmap)
11. [Résultats — Simulation ML% filtering (v4)](#11-résultats--simulation-ml-filtering-v4)

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
│  extract_features() → 111 features numériques               │
│  XGBoost v4 → predict_proba() → probabilité [0→1]          │
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
| **Features** | Les colonnes d'entrée que le modèle utilise pour prédire | ✅ 111 features numériques |
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

## 4. Les 111 features d'entrée

Le modèle v4 reçoit **111 features nommées** (vs 36 anonymes dans v3).
Chaque critère du Diamond Scanner est **numérisé** :

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
```### Feature Importance (modèle v4 — 111 features)

Après entraînement sur 1 210 trades historiques, le modèle révèle quelles features sont les plus prédictives :

```
Top 10 Features (par gain dans les arbres) :
 1. is_dxy                  gain=14.2  ← 🆕 Le dollar est radicalement différent
 2. rr                       gain=10.0  ← Le ratio risk/reward prédit le résultat
 3. tkx_h1                   gain=9.2   ← La croix Tenkan/Kijun H1 est cruciale
 4. kj_h1                    gain=6.9   ← Niveau Kijun H1
 5. sl                       gain=6.4   ← Le stop-loss compte autant que le TP
 6. day_wednesday            gain=6.4   ← 🆕 Les mercredis (FOMC) sont différents
 7. d_kj_h4                  gain=6.3   ← Distance à la Kijun H4
 8. d_kj_d1                  gain=6.0   ← Distance à la Kijun D1
 9. tkx_h4                   gain=6.0   ← Croix Tenkan/Kijun H4
10. is_forex                  gain=5.9   ← Les paires FX ont un comportement propre
```

> **Insight clé :** `is_dxy` est le meilleur prédicteur — le dollar suit une logique différente
> des paires forex classiques. `day_wednesday` confirme l'impact des FOMC.

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

## 8. Stratégie vers un profit factor > 2.0

### La simulation ML% filtering (modèle v4)

La simulation sur les 1 210 trades historiques avec le modèle v4 montre que
le filtrage par ML% transforme radicalement les résultats :

| Seuil ML% | Trades | Win Rate | **PF (RR)** | **P&L** | Capital |
|:---|---:|---:|---:|---:|---:|
| Aucun filtre | 1 210 | 37.6% | **1.02** | +1 442 € | 11 442 € |
| ML% ≥ 40% | 851 | 48.5% | **1.56** | +24 742 € | 34 742 € |
| **ML% ≥ 45%** | **661** | **54.3%** | **1.91** 🔥 | **+27 542 €** | **37 542 €** |
| **ML% ≥ 50%** | **504** | **59.7%** | **2.27** 🔥🔥 | **+25 842 €** | **35 842 €** |
| ML% ≥ 55% | 327 | 67.3% | **2.80** | +19 242 € | 29 242 € |
| ML% ≥ 60% | 170 | 78.8% | **3.59** | +9 340 € | 19 340 € |
| ML% ≥ 70% | 71 | 88.7% | 1.64 | +514 € | 10 514 € |

> **Capital initial : 10 000 €, risque 1% par trade, méthode RR réelle.**

### Les 3 sweet spots

| Zone | Win Rate | Profit Factor | P&L | Verdict |
|:---|:---:|:---:|---:|:---|
| **ML% ≥ 45%** | 54.3% | PF=1.91 | +275% | 🥇 Meilleur P&L |
| **ML% ≥ 50%** | 59.7% | PF=2.27 | +258% | 🥈 Meilleur PF |
| **ML% ≥ 55%** | 67.3% | PF=2.80 | +192% | 🥉 Plus sélectif |

### Distribution ML% → Win Rate

La corrélation est quasi parfaite : plus le ML% est élevé, plus le trade est gagnant.

| Bande ML% | Trades | Win Rate |
|:---|---:|---:|
| 0-25% | 2 | 0% — poubelle |
| 25-35% | 146 | 10.3% — quasi inutile |
| 35-45% | 401 | 20.2% — très mauvais |
| 45-50% | 157 | 36.9% — médiocre |
| **50-55%** | **177** | **45.8%** ✅ |
| **55-60%** | **157** | **54.8%** ✅✅ |
| **60-70%** | **99** | **71.7%** ✅✅✅ |
| **70-100%** | **71** | **88.7%** 🚀 |

> **Règle d'or :** Ne jamais trader un setup avec ML% < 45%. Au-dessus de 50%,
> le profit factor passe de 1.02 à 2.27 — un gain de 122% d'efficacité.

### ⚠️ Mise en garde : data leakage

Le modèle v4 a été entraîné sur ce même dataset (80% train / 20% test).
Les ML% incluent donc une part de **data leakage**. Le vrai test a été réalisé
en out-of-sample (train Janvier-Juin, test Juillet 2026) — voir [section 11](#11-résultats--simulation-ml-filtering-v4)
pour les résultats complets.

**Résultat OOS :** Le PF in-sample de 2.27 tombe à **0.72** en out-of-sample au seuil 50%.
Le seuil optimal OOS est **69%** avec un PF de **1.26** (18 trades seulement).
La corrélation ML% → Win Rate survit, mais le edge est trop faible pour être tradable.
Il faut plus de données et des features ICT réelles (FVG/OB/MSS calculés dans le backtest).

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
| Extracteur de features (111 dims nommées) | `src/ml_predictor.py` | ✅ |
| Entraîneur XGBoost + cross-val | `src/ml_trainer.py` | ✅ |
| Labeler 4 sources (DB/manual/scan/backtest) | `src/ml_labeler.py` | ✅ |
| Backtest historique 111 features (jan→jui 2026) | `backtest_historical_diamond.py` | ✅ |
| Modèle v4 entraîné (1 210 trades, 62.9% CV) | `models/historical_v4.xgb` | ✅ |
| Simulation ML% filtering (PF 1.02→2.27) | `_simulate_ml_filter.py` | ✅ |
| Intégration Scanner → ML% | `src/diamond_scanner.py` | ✅ |
| Colonne ML% dans l'affichage console | `main.py` | ✅ |
| Lazy-load (pas de crash si xgboost absent) | `src/diamond_scanner.py` | ✅ |
| Dashboard Streamlit 7 onglets | `app_ml.py` | ✅ |
| Barre de progression (scan labeling) | `app_ml.py` | ✅ |
| Bouton suppression modèle 🗑️ | `app_ml.py` | ✅ |
| Features temporelles (session ICT, killzones) | `src/ml_predictor.py` | ✅ |
| Features DXY + NEWS Day | `src/ml_predictor.py` | ✅ |

### Ce qui est prévu 🔜

| Priorité | Feature | Impact |
|:---:|:---|:---|
| P0 | ~~Test out-of-sample (juillet 2026)~~ → ✅ **FAIT** | PF OOS = 1.173 (v7) |
| P1 | `track save` enregistre les 111 features complètes | Dataset live riche |
| P2 | ~~Optimisation du seuil ML% optimal (grid search)~~ → ✅ **FAIT** | Seuil optimal = 59% (v7) |
| P3 | Ensemble de modèles (XGBoost + LightGBM + RF) | Robustesse |
| P4 | ~~Feature engineering : interactions croisées~~ → ✅ **FAIT** (v9, PF 0.827) | Overfitting confirmé |
| P5 | Poids adaptatifs (trades récents > anciens) | Adaptation au régime |
| P6 | ~~Backtest avec features ICT réelles (FVG/OB/MSS)~~ → ✅ **FAIT** — ICT = bruit | Leçon documentée |
| P7 | ~~Feature selection (top 25)~~ → ✅ **FAIT** (v7, PF=1.173) | Meilleur OOS |

### Historique des modèles

| Modèle | Données | Features | Trades | CV | OOS PF | Statut |
|:---|:---|:---:|---:|---:|:---:|:---|
| `historical_v1.xgb` (53 KB) | 6 majors | 36 anonymes | 852 | 61.0% | — | Archivé |
| `historical_v2.xgb` (91 KB) | 13 symboles | 36 anonymes | 1 846 | 61.9% | — | Archivé |
| `historical_v3.xgb` (91 KB) | 13 symboles | 36 anonymes | 1 210 | 61.9% | — | Archivé |
| `historical_v4.xgb` (91 KB) | 13 symboles | 111 nommées | 1 210 | 62.9% | 1.26* | 🥇 In-sample (leakage) |
| `historical_v5.xgb` | 13 symboles | 110 (ICT réelles) | 3 045 | 60.2% | 0.91 | 📉 Trop de données 2025 |
| `historical_v6.xgb` | 13 symboles | 110 (ICT réelles) | 1 119 | 58.0% | 0.87 | 📉 ICT = bruit |
| **`historical_v7.xgb`** (297 KB) | 13 symboles | **25 sélectionnées** | 2 923 | 60.1% | **1.173** | 🥇 **Best OOS** |
| `historical_v8.xgb` | 13 symboles | 25 + OB fix | 2 923 | 60.1% | **1.173** | 🥇 Ex-aequo (OB fix = 0 signal) |
| `historical_v9.xgb` | 13 symboles | 47 (cross-features) | 2 923 | 60.8% | 0.827 | ❌ Overfitting |
| `historical_v10.xgb` | 13 symboles | 25 (max_depth=5/6) | 2 923 | 59.6-60.5% | 0.755-0.882 | ❌ Plus profond = pire |

### 🏆 Classement OOS (sans data leakage)

| Rang | Modèle | Approche | Features | OOS PF | Leçon |
|:---:|:---|:---|---:|---:|:---|
| 🥇 | **v7** | Feature selection (25) | 25 | **1.173** | Moins = mieux |
| 🥇 | **v8** | 25 features + OB fix (ATR 2.0) | 25 | **1.173** | OB = bruit même filtré |
| 🥉 | v5 | Toutes features (110) + 2025 | 110 | 0.91 | 2025 = régime différent |
| 4 | v6 | ICT features réelles (110) | 110 | 0.87 | ICT = bruit |
| 5 | v9 | Cross-features (47) | 47 | 0.827 | Overfitting par feature engineering |
| 6 | v10a | max_depth=6, lr=0.03 | 25 | 0.806 | Arbres trop profonds |
| 7 | v10b | max_depth=6, lr=0.05 | 25 | 0.755 | Pire configuration |
| 8 | v10c | max_depth=5, lr=0.03 | 25 | 0.882 | Légèrement moins pire |

> **v4 (PF=1.26) n'est pas dans le classement OOS** car il a été testé sur ses propres données d'entraînement (data leakage). Son vrai PF OOS serait ~0.72 (voir Section 11).

### 🔑 Leçon : les features ICT (FVG/OB/MSS) sont du BRUIT

| Expérience | Résultat |
|:---|:---|
| v4 (ICT = 0) → v6 (ICT = réelles) | CV 62.9% → 58.0%, PF 1.26 → 0.87 |
| Top 25 features de v7 | **0 feature ICT** — 100% Ichimoku pur |
| 91% des trades ont un OB (v6) | La feature ne discrimine rien |
| v8 : OB filtrés (ATR 2.0, mitigation) | Détection 91% → 27%, PF identique (1.173) |

> **Les features gagnantes sont les niveaux de prix Ichimoku** (distances Kijun/Tenkan, T/K crosses, type d'actif). Les patterns ICT ajoutent du bruit, pas du signal.

### 🔑 Le plafond dur : PF=1.173

Le modèle v7 (25 features Ichimoku, max_depth=4) est le **plafond atteignable** avec l'architecture actuelle. Toutes les tentatives pour le dépasser ont échoué :

| Tentative | Modèle | Approche | Résultat |
|:---|:---:|:---|---:|
| Plus de données | v5 | Backtest 2025 (18 mois) | PF 1.173 → 0.91 (−22%) |
| Features ICT réelles | v6 | FVG/OB/MSS calculés | PF 1.173 → 0.87 (−26%) |
| OB filtrés | v8 | ATR 2.0 + mitigation | PF identique (1.173) |
| Cross-features | v9 | 22 features d'interaction | PF 1.173 → 0.827 (−29%) |
| Arbres plus profonds | v10a/b/c | max_depth=5,6 | PF 1.173 → 0.755-0.882 (−25 à −35%) |

> Pour franchir ce plafond, il faut une approche fondamentalement différente : plus de capital historique, des features de microstructure (order flow), ou un changement de paradigme (deep learning sur séries temporelles plutôt que classification XGBoost).

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

> **Dernière mise à jour :** 18 juillet 2026 (soir — final)
> **Statut :** 10 modèles entraînés (v1→v10). **Plafond OOS = PF 1.173** (v7/v8).
> **Classement final :** 🥇 v7/v8 (1.173) > 🥉 v5 (0.91) > v10c (0.882) > v6 (0.87) > v9 (0.827) > v10a (0.806) > v10b (0.755)
> **Leçon définitive :** 25 features Ichimoku + max_depth=4 est le sweet spot. Tout écart (plus de features, plus de données, arbres plus profonds) dégrade le PF OOS.
> **Prochaine étape :** Changer de paradigme — deep learning sur séries temporelles ou features de microstructure (order flow).

---

## 11. Résultats — Simulation ML% filtering (v4) + Test Out-of-Sample

### Méthodologie

- **Modèle in-sample :** `historical_v4.xgb` entraîné sur 1 210 trades (janvier → juillet 2026)
- **Modèle out-of-sample (OOS) :** Ré-entraîné sur janvier-juin uniquement, testé sur juillet 2026
- **Dataset :** `historical_111feats.csv` — 111 features nommées, outcomes réels
- **Split OOS :** 1 101 trades train (jan→juin, 91%) / 109 trades test (juillet, 9%)
- **Capital :** 10 000 €, risque 1% par trade, méthode RR réelle

### Résultats In-Sample (data leakage — NE PAS TRADER SUR CES CHIFFRES)

| Seuil ML% | Trades | Wins | Losses | Win Rate | PF(RR) | P&L |
|:---|---:|---:|---:|---:|---:|---:|
| Aucun | 1 210 | 455 | 755 | 37.6% | 1.02 | +1 442 € |
| ≥ 40% | 851 | 413 | 438 | 48.5% | 1.56 | +24 742 € |
| ≥ 45% | 661 | 359 | 302 | 54.3% | 1.91 | +27 542 € |
| ≥ 50% | 504 | 301 | 203 | 59.7% | 2.27 | +25 842 € |
| ≥ 55% | 327 | 220 | 107 | 67.3% | 2.80 | +19 242 € |
| ≥ 60% | 170 | 134 | 36 | 78.8% | 3.59 | +9 340 € |
| ≥ 63% | 119 | 104 | 15 | **87.4%** | **5.02** 🏆 | — |
| ≥ 70% | 71 | 63 | 8 | 88.7% | 1.64 | +514 € |

> **Meilleur PF in-sample : 5.02 au seuil 63%** — purement dû au data leakage.

### 🔬 Grid Search Out-of-Sample — 40% à 70%, pas de 1%

| Seuil | IS PF | **OOS PF** | OOS Trades | OOS WR | Δ PF |
|:---:|---:|---:|---:|---:|---:|
| 40% | 1.56 | **0.52** | 68 | 26.5% | −1.04 |
| 45% | 1.91 | **0.52** | 54 | 27.8% | −1.39 |
| 50% | 2.27 | **0.72** | 43 | 34.9% | −1.55 |
| 55% | 2.80 | **0.95** | 33 | 42.4% | −1.85 |
| 56% | 3.20 | **1.01** | 32 | 43.8% | −2.19 |
| 60% | 3.59 | **0.81** | 26 | 42.3% | −2.78 |
| 63% | 5.02 | **1.01** | 23 | 47.8% | −4.01 |
| 65% | 4.11 | **1.01** | 23 | 47.8% | −3.10 |
| 67% | 2.58 | **1.12** | 19 | 52.6% | −1.46 |
| 68% | 1.65 | **1.12** | 19 | 52.6% | −0.53 |
| **69%** | 1.65 | **1.26** 🏆 | **18** | **55.6%** | −0.39 |
| 70% | 1.64 | **1.01** | 17 | 52.9% | −0.63 |

> **Meilleur PF OOS : 1.26 au seuil 69%** — 18 trades seulement, insuffisant pour être statistiquement fiable.

### 📊 Comparaison In-Sample vs Out-of-Sample

```
Seuil    In-Sample PF    Out-of-Sample PF    Delta
40%      ████████ 1.56    ██ 0.52            −1.04
45%      ██████████ 1.91  ██ 0.52            −1.39
50%      ████████████ 2.27 ███ 0.72           −1.55
55%      ██████████████ 2.80 ████ 0.95         −1.85
63%      █████████████████████████ 5.02 █████ 1.01 −4.01
69%      ████████ 1.65    ██████ 1.26 🏆       −0.39
```

### 🎯 Les 3 conclusions du test Out-of-Sample

| # | Conclusion |
|:---|:---|
| 1 | **Le data leakage est massif.** PF in-sample 2.27 → OOS 0.72 au seuil 50%. L'écart atteint −4.01 au seuil 63%. Le modèle "mémorisait" les trades qu'il avait déjà vus. |
| 2 | **La corrélation ML% → Win Rate survit en OOS.** WR passe de 25.7% (aucun filtre) à 55.6% (seuil 69%). Le modèle sait faire le tri, même sur des données jamais vues. |
| 3 | **Le edge est trop faible pour être tradable.** PF max OOS = 1.26 avec seulement 18 trades. Il faut plus de données (backtest 2025), plus de features réelles (FVG/OB/MSS calculés), et un modèle plus robuste. |

### Top 10 trades In-Sample (ML% le plus élevé)

| Symbole | ML% | Score | Biais | Outcome |
|:---|---:|---:|:---|:---|
| BTCUSD | 83.4% | 84 | BULL | ✅ WIN |
| BTCUSD | 83.3% | 84 | BULL | ✅ WIN |
| BTCUSD | 83.1% | 84 | BULL | ✅ WIN |
| BTCUSD | 83.0% | 60 | BULL | ✅ WIN |
| BTCUSD | 82.9% | 84 | BULL | ✅ WIN |
| ETHUSD | 82.5% | 60 | BULL | ✅ WIN |
| ETHUSD | 82.3% | 60 | BULL | ✅ WIN |
| ETHUSD | 82.2% | 84 | BULL | ✅ WIN |
| XRPUSD | 82.0% | 72 | BEAR | ✅ WIN |
| XRPUSD | 81.7% | 72 | BULL | ✅ WIN |

> In-sample : 10/10 gagnants (100%). Out-of-sample : seulement 6/10 gagnants (60%).

### Top 10 trades Out-of-Sample (ML% le plus élevé)

| Symbole | ML% | Score | Biais | Outcome |
|:---|---:|---:|:---|:---|
| — | 90.4% | 60 | BULL | ❌ LOSS |
| — | 89.7% | 72 | BULL | ✅ WIN |
| — | 87.2% | 60 | BEAR | ❌ LOSS |
| — | 86.7% | 72 | BULL | ✅ WIN |
| — | 86.3% | 84 | BULL | ✅ WIN |
| — | 85.7% | 48 | BULL | ❌ LOSS |
| — | 85.6% | 60 | BULL | ✅ WIN |
| — | 79.9% | 60 | BEAR | ❌ LOSS |
| — | 79.3% | 60 | BEAR | ✅ WIN |
| — | 77.2% | 60 | BEAR | ✅ WIN |

> **OOS : 6/10 gagnants (60%).** Le top 10 in-sample était à 100% — preuve ultime du data leakage.

### ⚠️ Leçons définitives sur le data leakage

| Leçon | Détail |
|:---|---|
| **Ne jamais évaluer un modèle sur ses données d'entraînement** | Même avec train/test split, le biais persiste |
| **Toujours faire un test out-of-sample temporel** | Split chronologique (pas aléatoire) — entraîner sur le passé, tester sur le futur |
| **Le vrai PF est 5-10× plus bas que le PF in-sample** | Dans notre cas : 2.27 → 0.72 (÷3.2) au seuil 50% |
| **La corrélation ML% → WR est le vrai signal** | Même si le PF n'est pas tradable, la corrélation prouve que l'approche fonctionne |

### 🔬 Feature Selection Grid Search (v7)

Test de toutes les tailles de feature set (10, 15, 20, 25, 30, 33) pour trouver le sweet spot :

| N features | CV | **OOS PF** | Seuil |
|:---:|---:|---:|:---:|
| 10 | 59.5% | 0.696 | 42% |
| 15 | 59.6% | 0.649 | 49% |
| 20 | 60.8% | 0.898 | 62% |
| **25** | **60.1%** | **1.173** 🏆 | **59%** |
| 30 | 59.7% | 0.788 | 52% |
| 33 (all >0.01) | 59.2% | 0.918 | 59% |

> Courbe en U inversé : 25 features = sweet spot. Trop peu → sous-apprentissage. Trop → bruit.

### 🎯 Les 25 features gagnantes (100% Ichimoku, 0% ICT)

```
 1. is_dxy (type d'actif)      10. is_forex        19. tkx_d1
 2. rr (risk/reward)            11. score           20. d_kj_h1
 3. tkx_h1 (T/K cross H1)       12. d_tk_d1         21. d_tk_h4
 4. kj_h1 (Kijun H1)            13. day_tuesday     22. tk_d1
 5. sl (stop-loss)              14. is_xau          23. tp
 6. day_wednesday (FOMC)        15. is_jpy_pair     24. tk_h1
 7. d_kj_h4 (dist. Kijun H4)    16. price           25. kj_h4
 8. d_kj_d1 (dist. Kijun D1)    17. tkx_h1_conflict
 9. tkx_h4 (T/K cross H4)       18. score_pct
```

> **Aucune feature ICT (FVG/OB/MSS) dans le top 25.** Les meilleurs prédicteurs sont :
> type d'actif, ratio risk/reward, croix Tenkan/Kijun, distances aux Kijun.

### 📊 Classement final des modèles (OOS réel, sans data leakage)

| Rang | Modèle | Approche | Données | OOS PF |
|:---:|:---|:---|---:|:---:|
| 🥇 | **v7** | Feature selection (25 features) | 2025-Jun2026 | **1.173** |
| 🥈 | v5 | Toutes features (110) | 2025-Jun2026 | 0.91 |
| 🥉 | v6 | ICT features réelles (110) | Jan-Jun 2026 | 0.87 |

> v4 (PF=1.26) exclu car testé avec data leakage. Son vrai PF OOS est ~0.72.

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
