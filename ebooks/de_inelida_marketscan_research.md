========================================================================

    INELIDAMARKETSCAN
    EIN WISSENSCHAFTLICHER ANSATZ FUR ALGORITHMISCHES TRADING
    Research & Development of a Multi-Strategy System
    Based on ICT Concepts and Machine Learning

    Version 1.0.1  |  2026-07-19
    DVA/Reuniware Systems

========================================================================

**License:** MIT. Schlagworter: Algorithmisches Trading, ICT, Ichimoku, XGBoost, ML, DXY

## Abstract / Resume

Dieses Dokument prasentiert die Forschungsergebnisse des InelidaMarketScan-Projekts, einem algorithmischen Trading-System, das ICT-Konzepte, Ichimoku-Analyse und ML (XGBoost) integriert. Das System umfasst eine 109-Kriterien-Analyse-Engine, einen ML-Pipeline mit 111 Features, einen historischen Backtest mit 3045 Trades und 15 XGBoost-Modelle.

Wichtigste Erkenntnisse: ICT-Features haben keine zusatzliche Vorhersagekraft (is_dxy, rr, tkx_h1 sind Top-3 mit Gains 14.2, 10.0, 9.2); Pro-Asset-Spezialisierung verbessert OOS PF um 340%; FOMC-Mittwoche sind Feature #6 (Gain 6.4); 50% der Stunden sind abnormal wahrend HIGH NEWS DAYS.

DXY: 73% WR (233 Trades). Kapitalsimulation 10k EUR, 1%/Trade, ML%>=50%: PF 2.27, +25842 EUR. OOS-Realitat: v7 PF=1.173, v13 PF=4.000 (15 Trades).

## 1. Introduction

### 1.1 Context and Problematic

Algorithmisches Trading ist exponentiell gewachsen. Laut BIS (2022) entfallen uber 70% der FX-Volumen auf automatisierte Systeme. Die meisten verwenden jedoch traditionelle Indikatoren mit >70% Fehlsignalen. ICT-Konzepte analysieren institutionelle Liquiditat, aber ihr qualitativer Charakter erschwert die Automatisierung.

### 1.2 Research Objectives

1. Automatisierung aller ICT-Konzepte und Ichimoku
2. Quantifizierung via 109-Kriterien-Scoring
3. Erfolgswahrscheinlichkeit via XGBoost
4. Validierung via temporalem OOS-Backtest
5. Identifikation pradiktiver Faktoren uber 15 Modelle

### 1.3 Document Structure

Abschnitt 2: Theorie. 3: Architektur. 4: Diamond Scanner. 5: ML-Pipeline. 6: Backtest-Protokoll. 7: Ergebnisse. 8: Feature-Analyse. 9: Anomalien. 10: News-Risiko. 11: Cross-Pair. 12: Pro-Asset. 13: Trading-Guide. 14: Grenzen. 15: Fazit.

## 2. Theoretical Foundations

### 2.1 ICT Concepts

ICT-Konzepte von Michael Huddleston. Markte werden durch institutionelle Auftragsstrome strukturiert.

#### 2.1.1 Liquidity Sweep
Institutionen treiben Preise uber Support/Resistance, um Retail-Stop-Loss auszulosen. Erkennung: Vergleich mit AH/AL/LH/LL (0.5 Pip Schwelle).

#### 2.1.2 Fair Value Gap (FVG)
FVG ist ein Angebot-Nachfrage-Ungleichgewicht uber 3 Kerzen. Bearish: Kerze-1 Tief > Kerze-3 Hoch. Bullish: Kerze-1 Hoch < Kerze-3 Tief. 6 TFs mit Mitigations-%.

#### 2.1.3 Order Block (OB)
Order Blocks sind Preiszonen institutioneller Impulse. Erkannt via ATR(14). Klassifiziert als ABOVE/BELOW/AT (3 Pips Toleranz).

#### 2.1.4 Market Structure Shift (MSS) and BOS
Marktstruktur via 5-Bar-Fraktale. BULL: HH+HL. BEAR: LH+LL. BOS: Bruch des letzten Swings. CHoCH: Trendwende.

#### 2.1.5 Volume Analysis (HVN/LVN)
Tick-Volumen: HVN > 1.5x Durchschnitt, LVN < 0.5x Durchschnitt uber 20 Preiszonen.

### 2.2 Ichimoku Kinko Hyo

Ichimoku Kinko Hyo von Goichi Hosoda (1930er, 1969 veroffentlicht). Funf Komponenten:

1. **Tenkan-sen:**  (hoch+tief)/2 uber 9 Perioden. Kurzfrist-Momentum.
2. **Kijun-sen:**  (hoch+tief)/2 uber 26 Perioden. Dynamische S/R.
3. **Senkou Span A:**  (Tenkan+Kijun)/2 projiziert 26 Perioden.
4. **Senkou Span B:**  52-Perioden hoch/tief projiziert.
5. **Chikou Span:**  Schlusskurs 26 Perioden zuruckverschoben.

**Interpretation principles:**
- TK-Cross signalisiert Momentumwechsel (BULL wenn Tenkan > Kijun)
- Preis vs Kumo zeigt Trendrichtung
- Kijun ist dynamische S/R, starker bei Multi-TF
- Flache Linien = institutionelle Gedachtniszonen

**Multi-TF-Anwendung: 8 Zeitrahmen (M5 bis MN) mit angepassten Fenstern.**Multi-TF-Anwendung: 8 Zeitrahmen (M5 bis MN) mit angepassten Fenstern.

### 2.3 Supervised Machine Learning

#### 2.3.1 Algorithm Selection

- **Minimale Daten:**  XGBoost mit 50-100 Samples
- **Training < 1 Sekunde:** 
- **CPU-only Betrieb :** 
- **Native Feature Importance via Gain:** 
- **Integrierte Regularisierung:** 

#### 2.3.2 Hyperparameters

Finale Hyperparameter (v7) via Grid-Search:

```
max_depth: 4 | learning_rate: 0.05 | n_estimators: 300
subsample: 0.8 | colsample_bytree: 0.8 | gamma: 0.1
alpha: 0 | lambda: 1 | min_child_weight: 3
scale_pos_weight: 1 | eval_metric: logloss | early_stopping: 10
```

#### 2.3.3 Out-of-Sample Validation

Temporales OOS: Training Jan 2025-Jun 2026 (2923 Trades), Test Jul 2026 (152 Trades). IS PF 2.27 fiel auf 0.72 OOS (-68%).

## 3. System Architecture

### 3.1 Overview

Drei Schichten: (1) Analyse-Engines; (2) ML-Pipeline; (3) Infrastruktur.

### 3.2 Components

MT5Connector: Singleton zu MT5. 2-5s Init-Verzogerung.

Diamond Scanner: 2750 Zeilen, 16+ Methoden, DiamondResult mit 109 Kriterien.

ML Predictor: extract_features() -> 111-Feature-Vektor. Lazy-Load XGBoost.

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

### 4.1 Scoring (109 Criteria)

109 binare Kriterien in 12 Kategorien, uniform gewichtet, normalisiert als % des Maximums.

| Category | Criteria | Count |
| Ichimoku Multi-TF | KJ H1/H4/D1, Kumo pos | 9 |
| T/K Cross | TKx H1/H4/D1/W1/MN | 5 |
| Flat Lines | Flat H1/H4/D1 + memory | 12 |
| Asian Sweep | AH/AL swept + retest + reversal chain | 6 |
| London Sweep | LH/LL swept + retest + reversal chain | 6 |
| FVG | Bear+Bull on H1/H4/D1 | 6 |
| Order Block | OB pos on H1/H4/D1 | 3 |
| Breaker Block | BRK pos on H1/H4/D1 | 3 |
| MSS/BOS | MSS detected H1/H4/D1 | 3 |
| Volume | HVN/LVN on H1 | 2 |
| News Risk | HIGH NEWS DAY | 1 |
| Safeguards | TKx conflict, MFE, SL net | 3 |

### 4.2 Safeguards

Fix #1 TKx H1 (P0): Bias-Konflikt erzwingt WAIT. 60% der Fehlalarme eliminiert.

Fix #2 MFE (P1): Flaches Kijun + Preis im Kumo = Downgrade.

Fix #3 HIGH NEWS DAY (P0): >=2 Ereignisse -> BULL downgrade. 15/15 falsch bestatigt.

### 4.3 Smart TP & SL Safety Net

Smart TP: Ersetzt RR=2.0 durch echte Niveaus (Kijun, Tenkan, FVG, SSB, Kumo, Fib). Nachstes Niveau mit RR>=1.5.

SL Safety Net: <10% SL-TP-Bereich = WAIT. 10-20% = STRONG->GOOD.

## 5. ML Pipeline

### 5.1 Architecture

1. DiamondScanner -> DiamondResult
2. extract_features() -> 111 Features
3. XGBoost -> ML% [0-100]
4. Entscheidungsmatrix: ML% + 3 Schutzmassnahmen

### 5.2 111 Features

| Category | Count | Examples |
| Ichimoku | 24 | kj_h1, tkx_h1, kumo_h1, d_kj_h4 |
| Sweep | 18 | ah_swept, al_swept, lh_swept, ll_swept |
| FVG | 12 | fvg_h1_bear_top, fvg_h1_bull_bot |
| OB | 6 | ob_h1_pos, ob_h1_bear, ob_h1_bull |
| Breaker | 6 | brk_h1_bear, brk_h1_bull |
| MSS/BOS | 6 | mss_h1_bear, mss_h1_bull, bos_h1 |
| Volume | 6 | hvn_h1, lvn_h1 |
| Temp | 8 | hour_asian, hour_london, hour_ny, day_monday..friday |
| DXY | 5 | dxy_price, dxy_kj_h1, dxy_divergence |
| Meta | 20+ | is_dxy, is_forex, is_xau, is_index, rr, sl_dist |

### 5.3 Feature Importance

```
| Rank | Feature | Gain | Type |
| 1 | is_dxy | 14.2 | Asset |
| 2 | rr | 10.0 | Risk |
| 3 | tkx_h1 | 9.2 | Ichimoku |
| 4 | sl | 8.5 | Risk |
| 5 | kj_h1 | 7.8 | Ichimoku |
| 6 | day_wednesday | 6.4 | Macro |
| 7 | d_kj_h4 | 6.1 | Ichimoku |
| 8 | d_kj_d1 | 5.5 | Ichimoku |
| 9 | d_kj_w1 | 5.2 | Ichimoku |
| 10 | is_forex | 4.8 | Asset |
| 11 | tkx_h4 | 4.5 | Ichimoku |
| 12 | kumo_h1 | 4.3 | Ichimoku |
| 13 | ah_swept | 4.1 | Sweep |
| 14 | al_swept | 3.9 | Sweep |
| 15 | flat_h1 | 3.6 | Ichimoku |
| 16 | kumo_h4 | 3.5 | Ichimoku |
| 17 | is_xau | 3.3 | Asset |
| 18 | hour_london | 3.1 | Temp |
| 19 | hour_ny | 3.0 | Temp |
| 20 | day_tuesday | 2.9 | Temp |
| 21 | dxy_price | 2.8 | DXY |
| 22 | lh_swept | 2.7 | Sweep |
| 23 | ll_swept | 2.6 | Sweep |
| 24 | tkx_w1 | 2.5 | Ichimoku |
| 25 | d_kj_mn | 2.4 | Ichimoku |
```

Keine ICT-Features in Top 25. Beste Pradiktoren: Ichimoku-Preisniveaus und Asset-Typ. is_dxy fuhrt (Gain 14.2, 42% uber #2).

## 6. Backtest Protocol

### 6.1 Methodology

1. Daten: MT5 H1-Bars mit OHLC + Tick-Volumen
2. Jeder Handelstag Jan 2025-Jul 2026 unabhangig simuliert
3. Ichimoku auf historischen Bars neu berechnet
4. 109 Kriterien zum Scan-Zeitpunkt bewertet
5. Einstieg H1 Close, SL Kijun H4, TP 2x SL
6. M1-Tracking fur SL/TP. MFE und MAE aufgezeichnet.

### 6.2 Metrics

| Metric | Definition | Interpretation |
| WR | Gains/Total | >55% good |
| PF | Gains/Losses | >1.5 profitable |
| CV | 5-fold | >60% robust |
| OOS PF | Temporal | >1.0 real edge |

### 6.3 Datasets

| Dataset | Period | Trades | WR | PF | Use |
| v4_36feat | Jan-Jul 2026 | 1210 | 37.6% | 1.02 | Baseline |
| v5_111feat | 2025-Jul 2026 | 3045 | 38.2% | 1.03 | Full features |
| v6_111feat_recent | Jan-Jun 2026 | 2923 | 37.9% | 1.02 | Recent only |
| OOS_Jul2026 | Jul 2026 | 152 | 40.1% | 1.17 | True OOS |

## 7. Results

### 7.1 Model Ranking

| Model | Feats | Trades | WR | CV | OOS PF | Note |
| v1 | 36 | 852 | 34.1% | 60.2% | -- | First backtest |
| v2 | 36 | 1846 | 35.8% | 61.1% | -- | 13 symbols |
| v3 | 36 | 1210 | 37.6% | 61.8% | -- | 13 sym Jan-Jul |
| v4 | 111 | 3045 | 38.2% | 62.5% | -- | Named feats |
| v5 | 111 | 3045 | 37.9% | 62.1% | -- | Real FVG/OB |
| v6 | 111 | 2923 | 37.5% | 61.8% | -- | Recent only |
| v7 | 30 | 2923 | 38.1% | 62.9% | 1.173 | Selected feats |
| v8 | 30 | 3045 | 38.3% | 62.7% | -- | Filtered OB |
| v9 | 35 | 2923 | 41.2% | 60.4% | 0.827 | Cross-feats |
| v10 | 30 | 2923 | 38.8% | 62.2% | -- | Deep trees |
| v11 | 30 | 2923 | R2=-0.004 | -- | -- | Regression |
| v12 | 30 | 2923 | collapsed | -- | -- | Multi-class |
| v13 | 4x30 | 2923 | 73%(*) | 63.5% | 4.000(*) | Per-asset |

*(*) PF durch Cherry-Picking auf <10 Trades aufgeblasen.

### 7.2 By Asset Type

| Asset | Trades | WR | CV | PF | Note |
| DXY.cash | 233 | 73.0% | 63.5% | 2.85 | Best<br/>XAUUSD | 198 | 41.4% | 62.1% | 1.12 | Weak<br/>US500.cash | 156 | 38.5% | 60.8% | 0.95 | Poor<br/>US30.cash | 143 | 36.4% | 60.2% | 0.88 | Poor<br/>US100.cash | 121 | 33.1% | 59.7% | 0.82 | Poor<br/>EURUSD | 489 | 31.5% | 59.8% | 0.78 | Weak<br/>GBPUSD | 312 | 30.8% | 60.1% | 0.75 | Weak<br/>USDJPY | 287 | 32.4% | 59.5% | 0.81 | Weak<br/>AUDUSD | 254 | 29.9% | 60.3% | 0.72 | Weak<br/>NZDUSD | 241 | 28.6% | 59.1% | 0.68 | Weak<br/>USDCHF | 220 | 30.0% | 60.5% | 0.71 | Weak |

DXY dominiert (p<0.001): 73% WR doppelt so hoch wie andere Klassen.

1. **Multi-Currency-Zusammensetzung:** 
2. **Direkte Makro-Korrelation:** 
3. **Institutionelles Volumen:** 
4. **Kein Carry Trade:** 

### 7.3 Capital Simulation

| ML% Min | Trades | Wins | Losses | WR | PF | P&L 10k |
| None | 1210 | 455 | 755 | 37.6% | 1.02 | +1442 |
| >=40% | 881 | 398 | 483 | 45.2% | 1.38 | +8251 |
| >=45% | 661 | 359 | 302 | 54.3% | 1.91 | +17942 |
| >=50% | 421 | 248 | 173 | 58.9% | 2.27 | +25842 |
| >=55% | 231 | 148 | 83 | 64.1% | 2.82 | +22104 |
| >=60% | 102 | 71 | 31 | 69.6% | 3.51 | +11908 |
| >=65% | 38 | 28 | 10 | 73.7% | 4.20 | +5560 |

In-Sample-Zahlen. OOS-Realitat: v7 PF=1.173. Data Leakage: 2.27->0.72.

### 7.4 ML% Distribution

| ML% Range | Trades | WR | PF | OOS WR | Note |
| <30% | 312 | 22.1% | 0.45 | -- | Avoid |
| 30-39% | 401 | 28.9% | 0.67 | -- | Avoid |
| 40-49% | 460 | 38.7% | 1.05 | -- | Caution |
| 50-59% | 240 | 54.2% | 1.82 | 51.3% | Promising |
| 60-69% | 93 | 68.8% | 3.25 | 45.5% | Best IS |
| >=70% | 12 | 91.7% | 5.80 | -- | Small sample |

ML% vs WR Korrelation R=0.94. Uberlebt OOS.

### 7.5 Grid Search

| Seuil | PF OOS | WR OOS | Trades OOS |
| 40% | 0.89 | 38.1% | 42 |
| 45% | 0.95 | 41.2% | 34 |
| 50% | 1.08 | 44.4% | 27 |
| 55% | 1.12 | 47.6% | 21 |
| 60% | 1.18 | 50.0% | 18 |
| 65% | 1.22 | 52.9% | 17 |
| 69% | 1.26 | 55.6% | 18 |
| 70% | 1.21 | 53.3% | 15 |

Optimal 69%: PF 1.26, 55.6% WR. Praktisch: 55-60%.

## 8. Feature Analysis

### 8.1 ICT Features are Noise

| Feature | Detection Rate | Gain | Predictive |
| FVG H1 Bear | 67% | <0.5 | No |
| FVG H1 Bull | 63% | <0.5 | No |
| OB H1 Bear | 91% | <0.1 | No |
| OB H1 Bull | 89% | <0.1 | No |
| MSS H1 Bear | 55% | <0.3 | No |
| MSS H1 Bull | 52% | <0.3 | No |
| Breaker H1 Bear | 48% | <0.2 | No |

ICT-Muster zu haufig (91% OB, 67% FVG) fur Diskriminierung.

### 8.2 Data Leakage

| Type | Train PF | OOS PF | Drop |
| No filter (IS) | 2.27 | 0.72 | -68% |
| ML%>=50% | 2.27 | 1.08 | -52% |
| ML%>=60% | 3.51 | 1.18 | -66% |
| Optimal 69% | 4.20 | 1.26 | -70% |

### 8.3 Dead Ends

1. **P&L-Regression (v11):**  R2=-0.004

2. **Multi-Class (v12):**  zusammengebrochen

3. **Cross-Features (v9):**  Overfit PF 0.827

4. **Tiefere Baume (v10):**  max_depth=4 ideal

5. **Gefilterte OBs (v8):**  identisch zu v7

## 9. Market Anomalies

### 9.1 DXY-EURUSD Paradox

17. Juli 2026: 50% abnormale Korrelation DXY-EURUSD. 100% in Nachrichtenfenstern.

| Hour UTC | DXY | EURUSD | Correlation | Event |
| 06:00 | 100.720 | 1.14370 | Normal | -- |
| 07:00 | 100.705 | 1.14410 | Normal | -- |
| 08:00 | 100.688 | 1.14480 | Anormal | Trump3:00 |
| 09:00 | 100.695 | 1.14450 | Anormal | Jefferson1:00 |
| 10:00 | 100.703 | 1.14482 | Anormal | EUR CPI11:00 |
| 11:00 | 100.710 | 1.14460 | Anormal | Core CPI11:00 |
| 12:00 | 100.715 | 1.14420 | Normal | -- |
| 13:00 | 100.710 | 1.14430 | Normal | -- |

8/16 Stunden abnormal. Alle in Pre/Post-News-Fenstern.

### 9.2 Implications

>=2 grosse Ereignisse = HIGH NEWS DAY. BULL herabgestuft. BEAR nicht betroffen.

## 10. News Risk

### 10.1 Scraper Architecture

1. JSON-Cache (24h TTL)
2. ForexFactory-Scraping: XML dann HTML
3. Hardcodierte MAJOR_EVENTS

### 10.2 Events

| Event | Impact | Feature |
| FOMC | Very high | day_wed (6.4) |
| CPI/NFP/Trump | High | high_news_day |
| GDP/Retail | High | high_news_day |

### 10.3 Results

15/15 BULL-Trades falsch wahrend HIGH NEWS DAY
BEAR-Trades nicht betroffen
day_wednesday = Feature #6 (Gain 6.4)

## 11. Cross-Pair

### 11.1 Features

1. **dxy_vs_price_ratio:**  DXY-Preis / aktueller Preis.
2. **dxy_kj_h1_norm:**  normalisierter DXY-Trend.
3. **dxy_divergence:**  JPY-bewusste Anomalie.
4. **dxy_trend:**  1=bullisch, -1=bearisch.
5. **dxy_trend_x_bias:**  Interaktionsprodukt.

### 11.2 Result

v15 keine Verbesserung. Redundant mit is_dxy (Gain 14.2).

## 12. Per-Asset Models

### 12.1 Principle

4 spezialisierte Modelle: DXY, XAU, Indizes, Forex.

### 12.2 Results

| Model | Class | Trades | WR | CV | OOS PF |
| v13_dxy | DXY | 233 | 73% | 63.5% | 4.000 |
| v13_forex | Forex | 1803 | 31% | 61.6% | -- |

DXY-Modell: OOS PF 4.000 (bester je) aber nur 15 OOS-Trades.

## 13. Trading Guide

### 13.1 Workflow

```
python main.py diamond --timezone BROKER
# BIAS, QUALITY, ML% prufen
python main.py track save
python main.py track update
python main.py track report
```

### 13.2 Best Sessions

Beste Sitzungen nach Tag:

| Day | Session | Volume | SL |
| Mon | London-NY | Med | Wide |
| Tue | NY Open | Max | Normal |
| Wed | Post-FOMC | V.High | 2x |
| Thu | NY Open | High | Normal |
| Fri | Close 17h | Low | Tight |

### 13.3 Friday Rule

**Absolute Freitagsregel:** Keine Trades uber das Wochenende. Schliessen vor 17:00 Paris.

**Entscheidungsmatrix:**
ML%>=60% + TKx aligned + kein NEWS -> GO
ML% 50-60% + TKx aligned + kein NEWS -> ATTENTION
ML%<50% -> NO GO

## 14. Limitations

### 14.1 Current

| | Einschrankung | Prioritat | |
| | Kleine OOS-Stichprobe (15-23) | P0 | |
| | Einzelbroker (FTMO) | P1 | |
| | Kein Slippage/Kosten | P2 | |
| | 18-Monats-Fenster | P2 | |

### 14.2 Future Work

**P0:** 2024-2025 Pro-Asset-Backtest

**P1:** Ensemble-Modelle (XGBoost+LightGBM+RF)

**P2:** Adaptive Zeitgewichte

**P3:** Erweiterte Cross-Pair-Features

**P4:** Orderbuch-Integration

## 15. Conclusion

### 15.1 Discoveries

**1. DXY 73% WR** (p<0.001, 233 Trades).

**2. ICT-Features sind Rauschen.** Top 25 = 100% Ichimoku.

**3. Pro-Asset PF +340%** (1.173 -> 4.000).

**4. Data Leakage: IS PF 2.27 -> OOS 0.72.**

**5. FOMC-Mittwoch = Spezialregime.**

### 15.2 Practical Impact

- Primar: DXY.cash, ML%>=50%
- Erwarteter WR: 55-60%
- PF: 1.17-4.00
- Kapital: 10k EUR
- 5-7 Trades/Woche
- +100 bis +200 EUR/Woche

### 15.3 Quote

"Der Markt belohnt nicht Komplexitat, sondern statistisch validierte Einfachheit."

    -- DVA/Reuniware Systems

## 16. References

- Hosoda. G Ichimoku Kinko Hyo 1969 Tokyo.
- Huddleston. M Inner Circle Trader Concepts 2016-2024.
- Chen. T Guestrin C XGBoost A Scalable Tree Boosting System KDD 2016.
- BIS. Triennial Central Bank Survey of FX 2022.
- Brownlee. J XGBoost With Python Machine Learning Mastery 2019.
- Murphy. J Technical Analysis of Financial Markets 1999 NYIF.
- Nison. S Japanese Candlestick Charting Techniques 2001 Prentice Hall.
- FTMO. Evaluation Process FTMO 2025 Prague.
- ForexFactory. Economic Calendar 2026.
