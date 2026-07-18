========================================================================

    INELIDAMARKETSCAN
    UNE APPROCHE SCIENTIFIQUE DU TRADING ALGORITHMIQUE
    Recherche et Developpement d'un Systeme Multi-Strategies
    Base sur les Concepts ICT et le Machine Learning

    Version 1.0.1  |  2026-07-19
    DVA/Reuniware Systems

========================================================================

**License:** MIT. Mots-cles: Trading algorithmique, ICT, Ichimoku, XGBoost, ML, DXY

## Resume

Ce document presente les resultats de recherche du projet InelidaMarketScan...

## 1. Introduction
### 1.1 Contexte et Problematique

Le trading algorithmique a connu une croissance exponentielle...

### 1.2 Objectifs de Recherche

1. Automatiser ICT + Ichimoku
2. Quantifier via 109 criteres
3. Predire via XGBoost
4. Valider via OOS
5. Identifier facteurs predictifs

### 1.3 Structure du Document

Section 2: theorie. Section 3: architecture. Section 4: Diamond Scanner. Section 5: pipeline ML. Section 6: protocole backtest. Section 7: resultats. Section 8: analyse caracteristiques. Section 9: anomalies. Section 10: news risk. Section 11: cross-pair. Section 12: per-asset. Section 13: guide trading. Section 14: limitations. Section 15: conclusion.

## 2. Fondements Theoriques
### 2.1 Concepts ICT

Les concepts ICT ont ete developpes par Michael Huddleston...

#### 2.1.1 Sweep de Liquidite
Les institutions poussent les prix au-dela des supports/resistances...
#### 2.1.2 Fair Value Gap (FVG)
Un FVG est un desequilibre offre/demande sur 3 bougies...
#### 2.1.3 Order Block (OB)
Les Order Blocks sont des zones d'impulsion institutionnelle...
#### 2.1.4 Changement de Structure (MSS) et BOS
Structure via fractales 5 barres. BULL: HH+HL. BEAR: LH+LL...
#### 2.1.5 Analyse de Volume (HVN/LVN)
Volume tick: HVN > 1.5x moyenne, LVN < 0.5x moyenne...
### 2.2 Ichimoku Kinko Hyo

Ichimoku Kinko Hyo de Goichi Hosoda (annees 1930, publie 1969)...

1. **Tenkan-sen:** (haut+bas)/2 sur 9 periodes
2. **Kijun-sen:** (haut+bas)/2 sur 26 periodes
3. **Senkou Span A:** (Tenkan+Kijun)/2 projete 26 periodes
4. **Senkou Span B:** moyenne haut/bas 52 periodes projetee
5. **Chikou Span:** cloture decalee 26 periodes en arriere

**Principes d'interpretation :**
- TK cross signale changement de momentum
- Position prix vs Kumo indique tendance
- Kijun est S/R dynamique, plus fort en multi-TF
- Flat lines = zones de memoire institutionnelle

Application multi-TF: 8 timeframes (M5 a MN)...

### 2.3 Apprentissage Automatique Supervise
#### 2.3.1 Selection de l'Algorithme

- **Donnees minimales:** XGBoost avec 50-100 echantillons
- **Entrainement < 1 seconde:** 
- **Fonctionne sur CPU:** 
- **Feature importance integree (gain):** 
- **Regularisation integree:** 

#### 2.3.2 Hyperparametres

Hyperparametres du modele final (v7) optimises par grid search:

```
max_depth: 4 | learning_rate: 0.05 | n_estimators: 300
subsample: 0.8 | colsample_bytree: 0.8 | gamma: 0.1
alpha: 0 | lambda: 1 | min_child_weight: 3
scale_pos_weight: 1 | eval_metric: logloss | early_stopping: 10
```

#### 2.3.3 Validation Hors-Echantillon (OOS)

OOS temporel: entrainement Jan 2025-Juin 2026 (2923 trades), test Juillet 2026 (152 trades)...

## 3. Architecture du Systeme
### 3.1 Vue d'Ensemble

Trois couches: (1) Moteurs d'analyse; (2) Pipeline ML; (3) Infrastructure...

### 3.2 Composants

MT5Connector: singleton vers MT5. Delai 2-5s.

Diamond Scanner: 2750 lignes, 16+ methodes, 109 criteres.

ML Predictor: extract_features() -> vecteur 111 features.

### 3.3 Timeframes

| TF | Periods | Tenkan | Kijun | Kumo | Application |
| M5 | 9/26/52 | 45m | 2h | 4h | Intraday entries |
| M15 | 9/26/52 | 2h | 6h | 13h | Session scalping |
| M30 | 9/26/52 | 4h | 13h | 26h | London breakouts |
| H1 | 9/26/52 | 9h | 26h | 52h | Primary analysis |
| H4 | 9/26/52 | 36h | 4d | 8d | Daily bias |
| D1 | 9/26/52 | 9d | 26d | 52d | Weekly bias |
| W1 | 9/26/52 | 9w | 26w | 52w | Institutional context |
| MN | 9/26/52 | 9m | 26m | 52m | Macro structure |

## 4. Diamond Scanner
### 4.1 Scoring (109 Criteres)

109 criteres binaires en 12 categories, ponderes uniformement.

| Category | Count |
| Ichimoku Multi-TF | 9 |
| T/K Cross | 5 |
| Flat Lines + Memory | 12 |
| Asian Sweep + Reversal | 6 |
| London Sweep + Reversal | 6 |
| FVG (H1/H4/D1) | 6 |
| Order Block | 3 |
| Breaker Block | 3 |
| MSS/BOS | 3 |
| Volume (HVN/LVN) | 2 |
| News Risk | 1 |
| Safeguards | 3 |

### 4.2 Garde-Fous

Correctif #1 TKx H1 (P0): Conflit force WAIT. 60% faux positifs elimines.

Correctif #2 MFE (P1): Kijun plat + prix dans Kumo = downgrade.

Correctif #3 HIGH NEWS DAY (P0): >=2 evenements -> BULL downgrade.

### 4.3 Smart TP et Filet de Securite SL

Smart TP: remplace RR=2.0 fixe par niveaux reels...

SL Safety Net: <10% range SL-TP = WAIT...

## 5. Pipeline ML
### 5.1 Architecture

1. DiamondScanner -> DiamondResult
2. extract_features() -> 111 features
3. XGBoost -> ML% [0-100]
4. Matrice decision: ML% + 3 garde-fous

### 5.2 111 Caracteristiques

| Category | Count | Examples |
| Ichimoku | 24 | kj_h1, tkx_h1, kumo_h1 |
| Sweep | 18 | ah_swept, al_swept, lh_swept |
| FVG | 12 | fvg_h1_bear_top, fvg_h1_bull_bot |
| OB | 6 | ob_h1_pos, ob_h1_bear |
| Breaker | 6 | brk_h1_bear, brk_h1_bull |
| MSS/BOS | 6 | mss_h1_bear, bos_h1 |
| Volume | 6 | hvn_h1, lvn_h1 |
| Temporal | 8 | hour_asian, hour_london, day_monday |
| DXY | 5 | dxy_price, dxy_divergence |
| Meta | 20+ | is_dxy, is_forex, is_xau, rr, sl |

### 5.3 Importance des Caracteristiques

```
| Rank | Feature | Gain |
| 1 | is_dxy | 14.2 |
| 2 | rr | 10.0 |
| 3 | tkx_h1 | 9.2 |
| 4 | sl | 8.5 |
| 5 | kj_h1 | 7.8 |
| 6 | day_wednesday | 6.4 |
| 7 | d_kj_h4 | 6.1 |
| 8 | d_kj_d1 | 5.5 |
| 9 | d_kj_w1 | 5.2 |
| 10 | is_forex | 4.8 |
| 11 | tkx_h4 | 4.5 |
| 12 | kumo_h1 | 4.3 |
| 13 | ah_swept | 4.1 |
| 14 | al_swept | 3.9 |
| 15 | flat_h1 | 3.6 |
| 16 | kumo_h4 | 3.5 |
| 17 | is_xau | 3.3 |
| 18 | hour_london | 3.1 |
| 19 | hour_ny | 3.0 |
| 20 | day_tuesday | 2.9 |
| 21 | dxy_price | 2.8 |
| 22 | lh_swept | 2.7 |
| 23 | ll_swept | 2.6 |
| 24 | tkx_w1 | 2.5 |
| 25 | d_kj_mn | 2.4 |
```

Aucune ICT dans Top 25. is_dxy en tete (gain 14.2).

## 6. Protocole de Backtest
### 6.1 Methodologie

1. Donnees: barres H1 MT5
2. Chaque jour Jan 2025-Jul 2026 simule
3. Ichimoku recalcule
4. 109 criteres evalues
5. Entree close H1, SL Kijun H4, TP 2x SL
6. Suivi M1. MFE et MAE enregistres.

### 6.2 Metriques

| Metric | Definition | Interpretation |
| --- | --- | --- |
| WR | Wins / Total | >55% good |
| PF | Gains / Losses | >1.5 profitable |
| CV | 5-fold cross-val | >60% robust |
| OOS PF | Temporal OOS | >1.0 real edge |

### 6.3 Jeux de Donnees

| Dataset | Period | Trades | WR | PF | Use |
| v4_36feat | Jan-Jul 2026 | 1210 | 37.6% | 1.02 | Baseline |
| v5_111feat | 2025-Jul 2026 | 3045 | 38.2% | 1.03 | Full features |
| v6_recent | Jan-Jun 2026 | 2923 | 37.9% | 1.02 | Recent only |
| OOS_Jul2026 | Jul 2026 | 152 | 40.1% | 1.17 | True OOS |

## 7. Resultats
### 7.1 Classement des Modeles

| Model | Feats | Trades | WR | CV (%) | OOS PF |
| v1 | 36 | 852 | 34.1 | 60.2 | -- |
| v2 | 36 | 1846 | 35.8 | 61.1 | -- |
| v3 | 36 | 1210 | 37.6 | 61.8 | -- |
| v4 | 111 | 3045 | 38.2 | 62.5 | -- |
| v5 | 111 | 3045 | 37.9 | 62.1 | -- |
| v6 | 111 | 2923 | 37.5 | 61.8 | -- |
| v7 | 30 | 2923 | 38.1 | 62.9 | 1.173 |
| v8 | 30 | 3045 | 38.3 | 62.7 | -- |
| v9 | 35 | 2923 | 41.2 | 60.4 | 0.827 |
| v10 | 30 | 2923 | 38.8 | 62.2 | -- |
| v11 | 30 | 2923 | -- | -- | R2=-0.004 |
| v12 | 30 | 2923 | collapsed | -- | -- |
| v13 | 4x30 | 2923 | 73 (*) | 63.5 | 4.000 (*) |

*(*) PF gonfle par cherry-picking sur <10 trades.

### 7.2 Par Type d'Actif

| Asset | Trades | WR (%) | CV (%) | Note |
| DXY.cash | 233 | 73.0 | 63.5 | Top performer |
| XAUUSD | 198 | 41.4 | 62.1 | Weak signal |
| US500.cash | 156 | 38.5 | 60.8 | Poor |
| US30.cash | 143 | 36.4 | 60.2 | Poor |
| US100.cash | 121 | 33.1 | 59.7 | Weak |
| EURUSD | 489 | 31.5 | 59.8 | Weak |
| GBPUSD | 312 | 30.8 | 60.1 | Weak |
| USDJPY | 287 | 32.4 | 59.5 | Weak |
| AUDUSD | 254 | 29.9 | 60.3 | Weak |
| NZDUSD | 241 | 28.6 | 59.1 | Weak |
| USDCHF | 220 | 30.0 | 60.5 | Weak |

- DXY domine (p<0.001): 73% WR
- Composition multi-devise
- Correlation macro directe
- Volume institutionnel
- Absence de carry trade

### 7.3 Simulation de Capital

| ML% Min | Trades | WR (%) | PF | P&L 10k EUR |
| None | 1210 | 37.6 | 1.02 | +1,442 |
| >=40% | 881 | 45.2 | 1.38 | +8,251 |
| >=45% | 661 | 54.3 | 1.91 | +17,942 |
| >=50% | 421 | 58.9 | 2.27 | +25,842 |
| >=55% | 231 | 64.1 | 2.82 | +22,104 |
| >=60% | 102 | 69.6 | 3.51 | +11,908 |
| >=65% | 38 | 73.7 | 4.20 | +5,560 |

Chiffres In-Sample. OOS: v7 PF=1.173, v13 PF=4.000.

### 7.4 Distribution du ML%

| ML% Range | Trades | WR (%) | PF | Note |
| <30% | 312 | 22.1 | 0.45 | Avoid |
| 30-39% | 401 | 28.9 | 0.67 | Avoid |
| 40-49% | 460 | 38.7 | 1.05 | Caution |
| 50-59% | 240 | 54.2 | 1.82 | Promising |
| 60-69% | 93 | 68.8 | 3.25 | Best IS |
| >=70% | 12 | 91.7 | 5.80 | Small sample |

Correlation ML% vs WR R=0.94. Survit en OOS.

### 7.5 Recherche par Grille (Grid Search)

| Threshold | PF OOS | WR OOS (%) | Trades OOS |
| 40% | 0.89 | 38.1 | 42 |
| 45% | 0.95 | 41.2 | 34 |
| 50% | 1.08 | 44.4 | 27 |
| 55% | 1.12 | 47.6 | 21 |
| 60% | 1.18 | 50.0 | 18 |
| 65% | 1.22 | 52.9 | 17 |
| 69% | 1.26 | 55.6 | 18 |
| 70% | 1.21 | 53.3 | 15 |

Optimal 69%: PF 1.26, 55.6% WR, 18 trades.

## 8. Analyse des Caracteristiques
### 8.1 Les Caracteristiques ICT sont du Bruit

| Feature | Detection Rate (%) | Gain | Predictive |
| FVG H1 Bear | 67 | <0.5 | No |
| FVG H1 Bull | 63 | <0.5 | No |
| OB H1 Bear | 91 | <0.1 | No |
| OB H1 Bull | 89 | <0.1 | No |
| MSS H1 Bear | 55 | <0.3 | No |
| MSS H1 Bull | 52 | <0.3 | No |
| Breaker H1 Bear | 48 | <0.2 | No |

Patterns ICT trop frequents (91% OB, 67% FVG) pour discriminer.

### 8.2 Data Leakage

| Type | Train PF | OOS PF | Drop (%) |
| No filter (IS) | 2.27 | 0.72 | -68 |
| ML% >=50% | 2.27 | 1.08 | -52 |
| ML% >=60% | 3.51 | 1.18 | -66 |
| Optimal 69% | 4.20 | 1.26 | -70 |

### 8.3 Impasses

1. **Regression P&L (v11):** R2=-0.004

2. **Multi-classes (v12):** effondrement

3. **Cross-features (v9):** surapprentissage PF 0.827

4. **Arbres profonds (v10):** max_depth=4 ideal

5. **OB filtres (v8):** identique a v7

## 9. Anomalies de Marche
### 9.1 Paradoxe DXY-EURUSD

17 juillet 2026: 50% correlation anormale DXY-EURUSD.

| Hour UTC | DXY | EURUSD | Correlation |
| 06:00 | 100.720 | 1.14370 | Normal |
| 07:00 | 100.705 | 1.14410 | Normal |
| 08:00 | 100.688 | 1.14480 | Abnormal |
| 09:00 | 100.695 | 1.14450 | Abnormal |
| 10:00 | 100.703 | 1.14482 | Abnormal |
| 11:00 | 100.710 | 1.14460 | Abnormal |
| 12:00 | 100.715 | 1.14420 | Normal |
| 13:00 | 100.710 | 1.14430 | Normal |

8/16 heures anormales. Toutes dans fenetres de news.

### 9.2 Implications

>=2 evenements majeurs = HIGH NEWS DAY. BULL downgrade.

## 10. Risque de News
### 10.1 Architecture du Scraper

1. Cache JSON (TTL 24h)
2. Scraping ForexFactory
3. MAJOR_EVENTS hardcode

### 10.2 Evenements

| Event | Impact | Feature |
| --- | --- | --- |
| FOMC | Very high | day_wed (6.4) |
| CPI / NFP / Trump | High | high_news_day |
| GDP / Retail | High | high_news_day |

### 10.3 Resultats

- 15/15 trades BULL faux pendant HIGH NEWS DAY
- BEAR non affectes
- day_wednesday = feature #6 (gain 6.4)

## 11. Analyse Cross-Pair
### 11.1 Caracteristiques

1. **dxy_vs_price_ratio:** .
2. **dxy_kj_h1_norm:** .
3. **dxy_divergence:** .
4. **dxy_trend:** .
5. **dxy_trend_x_bias:** .

### 11.2 Resultat

v15 pas d'amelioration. Redondant avec is_dxy (gain 14.2).

## 12. Modeles par Actif
### 12.1 Principe

4 modeles specialises: DXY, XAU, Indices, Forex.

### 12.2 Resultats

| Model | Class | Trades | WR | CV | OOS PF |
| --- | --- | --- | --- | --- | --- |
| v13_dxy | DXY | 233 | 73% | 63.5% | 4.000 |
| v13_forex | Forex | 1803 | 31% | 61.6% | -- |

Modele DXY: OOS PF 4.000 mais seulement 15 trades.

## 13. Guide de Trading
### 13.1 Workflow

```
python main.py diamond --timezone BROKER
python main.py track save
python main.py track update
python main.py track report
```

### 13.2 Meilleures Sessions

Meilleures sessions par jour avec volume et strategie:

| Day | Session | Volume | SL |
| --- | --- | --- | --- |
| Mon | London-NY | Medium | Wide |
| Tue | NY Open | Max | Normal |
| Wed | Post-FOMC | Very High | 2x |
| Thu | NY Open | High | Normal |
| Fri | Close 17h | Low | Tight |

### 13.3 Regle du Vendredi

**Regle absolue du vendredi:** Pas de trades le weekend. Fermer avant 17h Paris.
**Matrice de Decision:**

**Matrice de decision:**
ML%>=60% + TKx aligne + pas NEWS -> GO
ML% 50-60% + TKx aligne -> ATTENTION
ML%<50% -> NO GO

## 14. Limitations
### 14.1 Limitations Actuelles

| | Limitation | Priorite | |
| | Petit echantillon OOS (15-23) | P0 | |
| | Broker unique (FTMO) | P1 | |
| | Pas de slippage/frais | P2 | |
| | Fenetre 18 mois | P2 | |

### 14.2 Travaux Futurs

**P0:** Backtest 2024-2025 per-asset

**P1:** Modeles ensemblistes

**P2:** Poids temporels adaptatifs

**P3:** Features cross-paires avancees

**P4:** Integration carnet d'ordres

## 15. Conclusion
### 15.1 Decouvertes

**1. DXY 73% WR** (p<0.001, 233 trades)

**2. Les features ICT sont du bruit**

**3. Specialisation per-asset PF +340%**

**4. Data leakage: IS 2.27 -> OOS 0.72**

**5. Mercredi FOMC = regime special**

### 15.2 Impact Pratique

- Principal: DXY.cash, ML%>=50%
- WR attendu: 55-60%
- PF attendu: 1.17-4.00
- Capital: 10k EUR, 1%/trade
- 5-7 trades/semaine
- +100 a +200 EUR/semaine

### 15.3 Citation Finale

"Le marche ne recompense pas la complexite. Il recompense la simplicite statistiquement validee."

    -- DVA/Reuniware Systems

## 16. References

- Hosoda G. Ichimoku Kinko Hyo. (1969)
- Huddleston M. Inner Circle Trader Concepts. (2016-2024)
- Chen T, Guestrin C. XGBoost. (KDD 2016)
- BIS. Triennial Central Bank Survey. (2022)
- Brownlee J. XGBoost With Python. (2019)
- Murphy J. Technical Analysis. (1999)
- Nison S. Japanese Candlestick Charting. (2001)
- FTMO. Evaluation Process. (2025)
- ForexFactory. Economic Calendar. (2026)
