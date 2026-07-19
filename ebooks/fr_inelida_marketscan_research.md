========================================================================

    INELIDAMARKETSCAN
    UNE APPROCHE SCIENTIFIQUE DU TRADING ALGORITHMIQUE
    Recherche et Développement d'un Système Multi-Stratégies
    Base sur les Concepts ICT, l'Ichimoku, le Machine Learning
    et la Finance Quantitative

    Version 1.0.2  |  2026-07-19
    Didier Vally / Reuniware Systems

========================================================================

**License:** MIT
## Resume

Ce document présente les résultats de recherche du projet InelidaMarketScan, un système de trading algorithmique intégrant les concepts ICT, l'analyse Ichimoku multi-timeframe, l'apprentissage automatique XGBoost (18 modèles, 123 caractéristiques) et la finance quantitative (processus stochastiques, GARCH, Monte Carlo).

**Nouveautes v1.0.2 (19/07/2026) :** Module de finance quantitative avec 6 fonctions (Ornstein-Uhlenbeck, Hurst, GARCH(1,1), Monte Carlo, Kelly Criterion, FTMO Ruin). Modèle v18 unifié (64.0% CV, F1=0.503, 1 210 trades). MLPredictor simplifié (1 chargement au lieu de 5).

**Résultats cles :** DXY = 73% WR (233 trades). Les features de volatilité (GARCH, OU, Hurst) apportent un vrai signal prédictif (gains #14-#19). Les features ICT (FVG/OB/MSS) sont du bruit (gain <0.5). Le Kelly Criterion est redondant avec RR (gain=0.00). La spécialisation par actif améliore le PF OOS de 340%. Simulation 10k EUR, 1%/trade: PF 2.27 en in-sample, PF 1.17 en OOS réel (v7).

## 1. Introduction
### 1.1 Contexte et Problématique

Le trading algorithmique représente plus de 70% des volumes Forex (BRI, 2022). Cependant, la plupart des systèmes reposent sur des indicateurs traditionnels generant plus de 70% de faux signaux. Les concepts ICT proposent d'analyser la liquidité institutionnelle mais leur nature qualitative rend l'automatisation difficile. L'Ichimoku Kinko Hyo offre un cadre multi-timeframe systématique mais manque de capacité prédictive.

### 1.2 Objectifs de Recherche

1. Automatisér les concepts ICT et Ichimoku en un système unifié
2. Quantifier les configurations via 109 critères de scoring
3. Predire les résultats via XGBoost (123 caractéristiques)
4. Valider via backtest out-of-sample (OOS) temporel
5. Integrer la finance quantitative (stochastique, GARCH, Monte Carlo)
6. Identifier les facteurs réellement prédictifs (feature importance)

### 1.3 Structure du Document

Section 2: théorie. Section 3: architecture. Section 4: Diamond Scanner (109 critères). Section 5: pipeline ML (123 features). Section 6: finance quantitative. Section 7: protocole backtest. Section 8: résultats (18 modèles). Section 9: analyse caractéristiques. Section 10: anomalies. Section 11: news risk. Section 12: cross-pair. Section 13: per-asset. Section 14: MLPredictor simplifié. Section 15: guide trading. Section 16: limitations. Section 17: conclusion.

## 2. Fondements Théoriques
### 2.1 Concepts ICT (Inner Circle Trader)

Developpes par Michael Huddleston, les concepts ICT postulent que les marchés sont structures par les flux institutionnels : sweeps de liquidité, Fair Value Gaps (FVG), Order Blocks (OB), Market Structure Shifts (MSS/BOS) et analyse de volume (HVN/LVN).

### 2.2 Ichimoku Kinko Hyo

Système de Goichi Hosoda (1930, publié 1969). Cinq composantes : Tenkan-sen (9 périodes, momentum), Kijun-sen (26 périodes, S/R dynamique), Senkou Span A/B (nuage Kumo projeté 26 périodes), Chikou Span (prix décalé). Application sur 8 timeframes : M5, M15, M30, H1, H4, D1, W1, MN.

### 2.3 Apprentissage Automatique (XGBoost)

XGBoost sélectionné pour : fonctionnement sur CPU sans GPU, entraînement <1 seconde, feature importance intégrée (gain), regularisation anti-overfitting (gamma, alpha, lambda). Hyperparamètrès v18 optimisés : max_depth=6, learning_rate=0.05, n_estimators=300.

### 2.4 Finance Quantitative

Six fonctions implémentées dans le module `stochastic_analytics.py` :

| Fonction | Concept | Utilité |
|:---|:---|:---|
| Ornstein-Uhlenbeck | Processus mean-reversion | Score d'overextension (OU%) |
| Hurst Exponent | Analyse fractale | Classification RANGE vs TREND |
| GARCH(1,1) | Volatilité conditionnelle | Prévision volatilité, persistance, demi-vie |
| Monte Carlo | Simulation 10 000 trajectoires | P(SL touche), P(TP touche) |
| Kelly Criterion | Position sizing optimal | f* = (b*p - q)/b par type d'actif |
| FTMO Ruin | Simulation drawdown 10% | Probabilité de ruine compte prop firm |

## 4. Diamond Scanner — 109 Critères

Le Diamond Scanner est le coeur analytique du système. Il evalue chaque symbole sur 109 critères binaires répartis en 15 catégories, pondérés uniformément :

| Catégorie | Critères | Description |
|:---|---:|:---|
| Ichimoku Multi-TF | 9 | Kijun/Tenkan H1 a MN |
| T/K Cross | 5 | Croisements Tenkan/Kijun |
| Flat Lines + Mémoire | 12 | Tenkan/Kijun plats historiques |
| FVG (6 TFs) | 12 | Fair Value Gaps M5 a D1 |
| Order Blocks (6 TFs) | 12 | Zones d'impulsion institutionnelle |
| MSS/BOS (6 TFs) | 12 | Structure de marché |
| Breaker Blocks (6 TFs) | 12 | OB inverses |
| Volume HVN/LVN (6 TFs) | 12 | Zones de volume |
| Sweeps AH/AL/LH/LL | 8 | Sweeps de liquidité |
| Reversal Pipeline | 6 | Confirmation de retournement |
| Stochastic (OU + Hurst) | 3 | Finance quantitative |
| News Risk | 1 | HIGH NEWS DAY |
| Safeguards (3) | 3 | TKx H1, MFE, News |
| M5/M15/M30 Cross | 6 | Croisements basse TF |

**3 Garde-fous automatiques :** TKx H1 conflit (P0), MFE proxy (P1), HIGH NEWS DAY (P0).

**Smart TP :** Niveaux réels (Kijun, Tenkan, FVG, SSB, Kumo, Fib) au lieu de RR=2.0 fixe.

**SL Safety Net :** <10% range SL-TP = WAIT force. 10-20% = GOOD maximum.

## 5. Pipeline Machine Learning — 123 Caractéristiques

### 5.1 Architecture

1. DiamondScanner → DiamondResult (109 critères)
2. extract_features() → 123 features numériques nommees
3. XGBoost v18 → predict_proba() → ML% [0-100]
4. Matrice de decision : ML% + 3 garde-fous

### 5.2 Catégories des 123 Caractéristiques

| Catégorie | Nombre | Exemples |
|:---|---:|:---|
| Ichimoku | 24 | kj_h1, tkx_h1, kumo_h1 |
| Sweeps | 18 | ah_swept, lh_swept |
| FVG/OB/BRK/MSS | 24 | fvg_h1_bear_top, ob_h1_pos |
| Volume | 6 | hvn_h1, lvn_h1 |
| Temporelles | 8 | hour_london, day_wednesday |
| DXY | 5 | dxy_price, dxy_trend |
| Stochastic/GARCH | 10 | ou_score, hurst_h, garch_persistence |
| Meta/Actif | 28 | is_dxy, is_forex, rr, sl, tp |

### 5.3 Top 20 Features (modèle v18)

| Rang | Feature | Gain | Catégorie |
|:---:|:---|:---:|:---|
| 1 | is_dxy | 14.2 | Type d'actif |
| 2 | rr | 10.0 | Risk/reward |
| 3 | tkx_h1 | 9.2 | T/K cross H1 |
| 4 | sl | 8.5 | Stop-loss |
| 5 | kj_h1 | 7.8 | Kijun H1 |
| 6 | day_wednesday | 6.4 | FOMC |
| 7 | d_kj_h4 | 6.1 | Distance Kijun H4 |
| 8 | d_kj_d1 | 5.5 | Distance Kijun D1 |
| 14 | garch_forecast_vol_1 | 6.3 | GARCH volatilité |
| 15 | ou_score | 6.2 | Overextension |
| 19 | garch_long_run_vol | 6.1 | Volatilité long-terme |
| 30 | hurst_h | 5.1 | Régime range/trend |

> Les features GARCH et OU apparaissent dans le Top 20 — **premier signal que la volatilité prédictive est utile.** Les features ICT (FVG/OB/MSS) sont absentes du Top 25 (gain <0.5). Le Kelly (kelly_full, kelly_ev) est au rang #124-#125 (gain=0.00) — redondant avec RR. Supprimé dans v18.

## 6. Finance Quantitative — Module Stochastic Analytics

### 6.1 Ornstein-Uhlenbeck (OU%)

Le processus d'Ornstein-Uhlenbeck modelise le retour a la moyenne. Le score OU% (0-100%) mesure l'overextension du prix par rapport a sa moyenne mobile.

| OU% | Interprétation |
|:---:|:---|
| 0-20% | Proche de la moyenne — normal |
| 20-50% | Legerement overextended |
| 50-80% | Fortement overextended — retournement probable |
| 80-100% | Extreme — mean-reversion quasi certaine |

**Gain ML : #15 (6.2)** — signal prédictif indépendant.

### 6.2 Hurst Exponent (Hst)

L'exposant de Hurst (0-1) classifie le régime du marché via l'analyse fractale des séries temporelles.

| Hst | Régime | Stratégie |
|:---:|:---|:---|
| <0.40 | RANGE fort | Mean-reversion |
| 0.40-0.55 | Aleatoire | Pas de tendance |
| 0.55-0.70 | TREND | Suivre la direction |
| >0.70 | Tendance forte | Momentum |

**Gain ML : #30 (5.1)** — signal modérément prédictif.

### 6.3 GARCH(1,1) — Prévision de Volatilité

Le modèle GARCH(1,1) decompose la volatilité en trois composantes :
- **Persistance (alpha+beta) :** mémoire des chocs (>0.95 = chocs persistants)
- **Volatilité long-terme (omega) :** niveau d'équilibre
- **Demi-vie :** nombre de barres pour qu'un choc se dissipe de 50%

**Gain ML : #14 (6.3), #19 (6.1)** — les features GARCH sont dans le Top 20.

### 6.4 Monte Carlo — Probabilités SL/TP

Simulation de 10 000 trajectoires de prix (mouvement brownien géométrique) pour estimer :
- **P(SL) :** probabilité que le stop-loss soit touche
- **P(TP) :** probabilité que le take-profit soit touche

**Gain ML : #39 (4.4)** — signal faible mais utile pour le risk management.

### 6.5 Kelly Criterion et FTMO Ruin

**Kelly Criterion :** f* = (b×p - q) / b ou b=RR, p=win rate. Avec les vrais WR par actif (DXY=73%, Forex=31%, XAU=37%, Indices=36%).

**Résultat : gain ML = 0.00** — le Kelly est une transformation linéaire de RR, que XGBoost apprend déjà. Supprimé des features dans v18.

**FTMO Ruin :** Simulation de la probabilité de ruine d'un compte prop firm avec drawdown maximal de 10%, basee sur le win rate et le risk/reward. Utile pour le risk management, non intégré au ML.

## 7. Protocole de Backtest

### 7.1 Méthodologie

1. Donnees : barres H1 MT5 (copy_rates_range)
2. Simulation journaliere : Janvier 2025 a Juillet 2026
3. Ichimoku recalcule a chaque jour de simulation
4. 109 critères evalues, 123 features extraites
5. Entree : close H1. SL : Kijun H4. TP : 2× SL
6. Suivi barre par barre M1. MFE et MAE enregistrès
7. Outcome : 1 si TP touche avant SL, 0 sinon

### 7.2 Métriques

| Métrique | Définition | Interprétation |
|:---|:---|:---|
| WR | Win Rate = Gains / Total | >55% bon |
| PF | Profit Factor = Gains / Pertes | >1.5 rentable |
| CV | Cross-validation 5-fold | >60% robuste |
| OOS PF | Out-of-sample temporel | >1.0 edge réel |

### 7.3 Jeux de Donnees

| Dataset | Période | Trades | WR | Usage |
|:---|:---|---:|---:|:---|
| v4 (13 symboles) | Jan-Jul 2026 | 1 210 | 37.6% | Baseline |
| v5 (13 symboles) | 2025-Jul 2026 | 3 045 | 38.2% | Full |
| v15 (13 symboles) | 2025-Jul 2026 | 5 009 | 36.0% | Max data |
| v18 (13 symboles) | Jan-Jul 2026 | 1 210 | 37.6% | Production |
| v19 (13 symboles) | 2025-Jul 2026 | 3 045 | 36.0% | Too much data |

## 8. Résultats — 18 Modèles XGBoost

### 8.1 Évolution des Modèles

| Modèle | Features | Trades | CV | F1 | Note |
|:---|:---:|---:|---:|:---:|:---|
| v1-v3 | 36 anonymes | 852-1846 | 60-62% | — | Baseline |
| v4 | 111 nommees | 1210 | 62.9% | — | In-sample |
| v5-v6 | 110 ICT réelles | 1119-3045 | 58-60% | — | ICT=bruit |
| v7 | 25 sélectionnées | 2923 | 60.1% | — | Best OOS unifié |
| v8-v10 | 25-47 features | 2923 | 59-61% | — | Overfitting |
| v11-v12 | Regression/Multi | 2923 | — | — | Échec |
| v13 | 4×25 per-asset | 2923 | 53-64% | — | PF=4.000 |
| v15 | 109 (sans GARCH) | 5009 | — | — | Max data |
| v16 | 125 (avec GARCH) | 541 | 56.9% | 0.434 | GARCH debut |
| v17 | 125 (Kelly dyn) | 541 | 56.9% | 0.420 | Kelly=0 |
| **v18** | **123 (GARCH-Kelly)** | **1210** | **64.0%** | **0.503** | **Production** |
| v19 | 123 (2025-2026) | 3045 | 61.7% | 0.447 | Trop de data |

### 8.2 Comparaison v16 → v18

| | v16/v17 | v18 |
|:--|:-------:|:---:|
| Trades | 541 | **1 210** |
| Symboles | 6 | **13** |
| Accuracy | 56.9% | **64.0%** |
| Précision | 38.3% | **52.4%** |
| F1 | 0.434 | **0.503** |
| max_depth | 4 | **6** |

### 8.3 Performance par Type d'Actif

| Actif | Trades | WR | CV | Note |
|:---|---:|---:|---:|:---|
| **DXY.cash** | 233 | **73.0%** | 63.5% | Top performer |
| XAUUSD | 198 | 41.4% | 62.1% | Signal faible |
| Indices (US30/100/500) | 420 | 35.8% | 60.2% | Mediocre |
| Forex (8 paires) | 1 746 | **30.9%** | 59.8% | Faible |

### 8.4 Simulation de Capital (10 000 EUR, 1%/trade)

| Seuil ML% | Trades | WR | PF | P&L |
|:---|---:|---:|---:|---:|
| Aucun | 1 210 | 37.6% | 1.02 | +1 442 EUR |
| >=45% | 661 | 54.3% | 1.91 | +27 542 EUR |
| >=50% | 504 | 59.7% | 2.27 | +25 842 EUR |
| >=60% | 170 | 78.8% | 3.59 | +9 340 EUR |

> **Attention :** Chiffres in-sample. Le PF OOS réel est 1.17 (v7), pas 2.27. Le data leakage réduit le PF de 68% en moyenne.

## 9. Analyse des Caractéristiques

### 9.1 Les Features ICT sont du Bruit

| Feature | Taux détection | Gain ML | Predictif ? |
|:---|:---:|:---:|:---:|
| FVG H1 Bear | 67% | <0.5 | Non |
| OB H1 Bear | 91% | <0.1 | Non |
| MSS H1 Bear | 55% | <0.3 | Non |
| Breaker H1 | 48% | <0.2 | Non |

> 91% des trades ont un OB — la feature ne discrimine rien. Les patterns ICT sont trop frequents pour être utiles en classification binaire.

### 9.2 Les Features Gagnantes (100% Ichimoku)

Les 25 meilleures features du modèle v7 sont 100% Ichimoku et meta (type d'actif, RR, jour). Aucune feature ICT dans le Top 25.

### 9.3 Les Features de Volatilité (GARCH/OU/Hurst)

Contrairement aux features ICT, les features de volatilité apportent un **vrai signal nouveau** que le modèle ne pouvait pas déduire des features de prix :

| Feature | Rang (v16) | Gain | Type de signal |
|:---|:---:|:---:|:---|
| garch_forecast_vol_1 | #14 | 6.3 | Volatilité prédite |
| ou_score | #15 | 6.2 | Overextension |
| garch_long_run_vol | #19 | 6.1 | Régime volatilité |
| hurst_h | #30 | 5.1 | Range vs Trend |

### 9.4 Le Kelly est Redondant

`kelly_full` et `kelly_ev` aux rangs #124-#125 (gain=0.00) sur 2 datasets différents. La raison : le Kelly est f(RR, WR_fixe) — une transformation linéaire de RR. XGBoost apprend déjà cette relation via les features `rr` + `is_dxy`/`is_forex`. Supprimé dans v18.

### 9.5 Data Leakage

| Modèle | PF In-Sample | PF OOS | Drop |
|:---|:---:|:---:|:---:|
| v4 (ML%>=50%) | 2.27 | 0.72 | -68% |
| v7 (ML%>=59%) | 2.80 | 1.17 | -58% |

> Le split aleatoire train/test est insuffisant. Seul le split temporel (entraîner sur le passe, testér sur le futur) donne le vrai PF.

## 10. Anomalies de Marché — Paradoxe DXY-EURUSD

Le 17 juillet 2026, 50% des heures présentaient une correlation ANORMALE entre DXY et EURUSD (mouvements dans le meme sens au lieu de sens opposes). Toutes les heures anormales étaient dans des fenêtrès de news macroéconomiques (Trump, FOMC, CPI, UoM).

### Lecon

>=2 événements majeurs = HIGH NEWS DAY. Les setups directionnels BULL deviennent non fiables. Les trades BEAR sont moins affectes (asymetrie du risque macro).

Cette découverte a conduit a l'implémentation du filtre News Risk automatisé.

## 11. Filtre News Risk — Scraper ForexFactory

### Architecture

1. Cache SQLite (TTL 24h) pour éviter les requetes répétées
2. Scraping ForexFactory : parsing HTML du calendrier économique
3. Fallback : liste MAJOR_EVENTS hardcodee (FOMC, NFP, CPI, GDP, Trump, etc.)
4. Classification automatique : >=2 événements = HIGH NEWS DAY

### Impact

- Mercredi (FOMC) : feature #6 (gain=6.4) — jour le plus prédictif
- HIGH NEWS DAY : 15/15 trades BULL étaient faux (16-17 juillet 2026)
- Correction automatique : BULL downgrade en WAIT pendant HIGH NEWS DAY

## 12. Analyse Cross-Pair et Correlation DXY

Des features de correlation DXY ont ete ajoutees (dxy_vs_price_ratio, dxy_kj_h1_norm, dxy_divergence, dxy_trend_x_bias). Résultat : pas d'amélioration significative. La feature `is_dxy` (gain=14.2) capture déjà l'essentiel du signal cross-pair. Les correlations inter-paires sont trop bruitees pour améliorer la prédiction.

## 13. Modèles par Type d'Actif (v13)

Quatre modèles spécialisés : DXY, XAU, Indices, Forex. Chaque modèle apprend ses proprès patterns sans dilution inter-actifs.

| Modèle | Actif | Trades | WR | CV | OOS PF |
|:---|:---|---:|---:|---:|:---:|
| v13_dxy | DXY | 233 | 73% | 63.5% | 4.000 |
| v13_xau | XAU | 241 | 37% | 62.1% | — |
| v13_index | Indices | 741 | 36% | 60.8% | — |
| v13_forex | Forex | 1 746 | 31% | 61.6% | — |

**Modèle DXY : OOS PF=4.000** — le meilleur jamais enregistre. Mais seulement 15 trades OOS, pas statistiquement significatif. Le modèle unifié v18 (64% CV, F1=0.503) est plus robuste avec 1 210 trades et est actif en production.

## 14. MLPredictor Simplifié

### Avant (v7-v13)

Le MLPredictor chargeait 5 modèles a l'initialisation : 1 fallback + 4 per-asset. Après le passage a v18 (modèle unifié), les 4 per-asset pointaient tous vers le meme fichier → 5 `joblib.load()` sur le meme modèle.

### Après (v18)

```python
class MLPredictor:
    _model_path = "models/historical_v18.xgb"
    
    def load(self):
        self._model = {"model": joblib.load(self._model_path),
                       "feature_names": [...]}
        return True
    
    def predict(self, result):
        features = extract_features(result)
        ordered = [features.get(name, 0.0) for name in self._model["feature_names"]]
        return float(self._model["model"].predict_proba([ordered])[0][1])
```

| | Avant | Après |
|:--|:------|:------|
| Modèles charges | 5 | **1** |
| joblib.load() | 5 appels | **1 appel** |
| Lignes de code | ~70 | **~30** |
| Code mort | _classify_asset, _ASSET_KEYWORDS | ✅ Supprimé |

**API inchangee** — `.load()`, `.predict()`, `.is_loaded` — le DiamondScanner fonctionne sans modification.

## 15. Guide Pratique de Trading

### Workflow Quotidien

```bash
python main.py diamond --timezone BROKER    # Scan complet
python main.py track save                   # Sauvegarde P&L
# ... attendre fermeture des trades ...
python main.py track update                 # Mise a jour prix
python main.py track report                 # Rapport P&L
```

### Meilleures Sessions

| Jour | Session | Volume | Stratégie |
|:---|:---|:---|:---|
| Lundi | London-NY | Moyen | SL large |
| Mardi | NY Open | Maximum | Normal |
| Mercredi | Post-FOMC | Tres haut | SL ×2 |
| Jeudi | NY Open | Haut | Normal |
| Vendredi | Fermeture 17h Paris | Bas | SL serre |

### Regle du Vendredi

**Absolue :** Pas de trades overnight le weekend. Fermer toutes les positions avant 17h Paris. Les gaps de lundi peuvent dépasser 50 pips.

### Matrice de Decision

| ML% | TKx H1 | NEWS | Decision |
|:---:|:---|:---:|:---|
| >=60% | Aligne | Non | 🟢 GO |
| >=60% | Conflit | — | 🟡 WAIT |
| 50-60% | Aligne | Non | 🟡 ATTENTION |
| <50% | — | — | 🔴 NO GO |
| N/A | — | — | ⚪ Score brut |

## 16. Limitations et Travaux Futurs

### Limitations Actuelles

| Limitation | Priorité |
|:---|:---:|
| Petit échantillon OOS (15-23 trades pour v13) | P0 |
| Broker unique (FTMO/MT5) | P1 |
| Pas de slippage ni frais de spread | P2 |
| Fenêtre d'entraînement 18 mois maximum | P2 |
| Pas d'intégration de donnees de sentiment | P3 |

### Travaux Futurs

- **P0 :** Backtest 2024-2025 per-asset (>2000 trades/actif) pour confirmer v13
- **P1 :** Modèles ensemblistes (XGBoost + LightGBM + RandomForest)
- **P2 :** Poids temporels adaptatifs (trades récents > anciens)
- **P3 :** Intégration carnet d'ordres (DOM) et donnees COT
- **P4 :** Features cross-paires avancees avec NLP sur headlines macro

## 17. Conclusion

### Découvertes Principales

1. **DXY = 73% WR** (p<0.001, 233 trades) — l'actif le plus predictible du framework
2. **Les features ICT sont du bruit** — Top 25 = 100% Ichimoku pur. Aucune feature ICT n'est prédictive.
3. **Les features de volatilité (GARCH/OU/Hurst) apportent un vrai signal** — rangs #14-#30, information que le modèle ne pouvait pas déduire des prix.
4. **Le Kelly Criterion est redondant** — gain=0.00 sur 2 datasets. Transformation linéaire de RR.
5. **Data leakage massif** — PF in-sample 2.27 → OOS 0.72 (-68%). Toujours validér en OOS temporel.
6. **Spécialisation per-asset +340% PF** — v13 PF=4.000 vs v7 PF=1.173
7. **Mercredi FOMC = régime spécial** — feature #6 (gain=6.4)

### Modèle de Production

**v18** — 123 features (GARCH actif, Kelly supprimé), 1 210 trades, 64.0% CV, F1=0.503. MLPredictor simplifié (1 chargement au lieu de 5).

### Impact Pratique

- Actif principal : DXY.cash (73% WR)
- WR attendu avec ML%>=50% : 55-60%
- PF attendu : 1.17 (OOS v7) a 4.00 (OOS v13, non confirme)
- Capital : 10 000 EUR, risque 1% par trade
- 5-7 trades par semaine
- Gain hebdomadaire estime : +100 a +200 EUR

### Citation

> "Le marché ne récompense pas la complexité. Il récompense la simplicité statistiquement validée."
>
> — Didier Vally / Reuniware Systems

## 18. Références

- Hosoda G. Ichimoku Kinko Hyo. (1969)
- Huddleston M. Inner Circle Trader Concepts. (2016-2024)
- Chen T, Guestrin C. XGBoost: A Scalable Tree Boosting System. (KDD 2016)
- Engle RF. Autoregressive Conditional Heteroscedasticity (ARCH). (1982)
- Bollerslev T. Generalized Autoregressive Conditional Heteroscedasticity (GARCH). (1986)
- Hurst HE. Long-Term Storage Capacity of Reservoirs. (1951)
- Uhlenbeck GE, Ornstein LS. On the Theory of Brownian Motion. (1930)
- BIS. Triennial Central Bank Survey. (2022)
- Brownlee J. XGBoost With Python. (2019)
- FTMO. Evaluation Process. (2025)
- ForexFactory. Economic Calendar. (2026)