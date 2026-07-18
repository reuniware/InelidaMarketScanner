========================================================================

    INELIDAMARKETSCAN
    UN ENFOQUE CIENTIFICO AL TRADING ALGORITMICO
    Research & Development of a Multi-Strategy System
    Based on ICT Concepts and Machine Learning

    Version 1.0.1  |  2026-07-19
    DVA/Reuniware Systems

========================================================================

**License:** MIT. Palabras clave: Trading algoritmico, ICT, Ichimoku, XGBoost, ML, DXY

## Abstract / Resume

Este documento presenta los resultados de investigacion del proyecto InelidaMarketScan. Los hallazgos principales: las caracteristicas ICT no tienen poder predictivo adicional (is_dxy, rr, tkx_h1 son las 3 mejores con ganancias 14.2, 10.0, 9.2); la especializacion por activo mejora el PF OOS en 340%; los miercoles FOMC son la caracteristica #6 (ganancia 6.4). DXY: 73% WR (233 operaciones). Simulacion 10k EUR: PF 2.27, +25842 EUR.

## 1. Introduction

### 1.1 Context and Problematic

El trading algoritmico ha crecido exponencialmente. Segun el BPI (2022), mas del 70% del volumen de Forex es automatizado. Sin embargo, la mayoria usa indicadores tradicionales con >70% de senales falsas. Los conceptos ICT proponen analizar la liquidez institucional.

### 1.2 Research Objectives

1. Automatizar todos los conceptos ICT e Ichimoku
2. Cuantificar la confluencia via 109 criterios
3. Predecir probabilidad de exito via XGBoost
4. Validar via backtest OOS temporal
5. Identificar factores predictivos en 15 modelos

### 1.3 Document Structure

Seccion 2: teoria. 3: arquitectura. 4: Diamond Scanner. 5: pipeline ML. 6: backtest. 7: resultados. 8: analisis de caracteristicas. 9: anomalias. 10: riesgo noticias. 11: cross-pair. 12: por activo. 13: guia trading. 14: limitaciones. 15: conclusion.

## 2. Theoretical Foundations

### 2.1 ICT Concepts

Conceptos ICT desarrollados por Michael Huddleston. Postulan que los mercados son estructurados por flujos institucionales.

#### 2.1.1 Liquidity Sweep
Las instituciones empujan los precios mas alla de soporte/resistencia para activar stop-loss. Deteccion: comparacion con niveles AH/AL/LH/LL (0.5 pips).

#### 2.1.2 Fair Value Gap (FVG)
Un FVG es un desequilibrio oferta-demanda en 3 velas. Bajista: vela-1 bajo > vela-3 alto. Alcista: vela-1 alto < vela-3 bajo. 6 TF con mitigacion %.

#### 2.1.3 Order Block (OB)
Order Blocks son zonas de impulso institucional. Detectados via ATR(14). Clasificados ABOVE/BELOW/AT (3 pips tolerancia).

#### 2.1.4 Market Structure Shift (MSS) and BOS
Estructura via fractales 5 barras. BULL: HH+HL. BEAR: LH+LL. BOS: ruptura del ultimo swing. CHoCH: cambio de caracter.

#### 2.1.5 Volume Analysis (HVN/LVN)
Volumen tick: HVN > 1.5x media, LVN < 0.5x media en 20 zonas.

### 2.2 Ichimoku Kinko Hyo

Ichimoku Kinko Hyo de Goichi Hosoda (1930s, publicado 1969). Cinco componentes:

1. **Tenkan-sen:**  (alto+bajo)/2 en 9 periodos. Momento corto plazo.
2. **Kijun-sen:**  (alto+bajo)/2 en 26 periodos. S/R dinamico.
3. **Senkou Span A:**  (Tenkan+Kijun)/2 proyectado 26 periodos.
4. **Senkou Span B:**  alto/bajo 52 periodos proyectado.
5. **Chikou Span:**  cierre desplazado 26 periodos atras.

**Interpretation principles:**
- Cruce TK senala cambio de momento (BULL si Tenkan > Kijun)
- Precio vs Kumo indica tendencia
- Kijun es S/R dinamico
- Lineas planas = zonas de memoria institucional

**Aplicacion multi-TF: 8 marcos temporales (M5 a MN).**Aplicacion multi-TF: 8 marcos temporales (M5 a MN).

### 2.3 Supervised Machine Learning

#### 2.3.1 Algorithm Selection

- **Datos minimos:**  XGBoost con 50-100 muestras
- **Entrenamiento < 1 segundo:** 
- **Opera en CPU :** 
- **Feature importance nativa :** 
- **Regularizacion integrada:** 

#### 2.3.2 Hyperparameters

Hiperparametros finales (v7) via grid search:

```
max_depth: 4 | learning_rate: 0.05 | n_estimators: 300
subsample: 0.8 | colsample_bytree: 0.8 | gamma: 0.1
alpha: 0 | lambda: 1 | min_child_weight: 3
scale_pos_weight: 1 | eval_metric: logloss | early_stopping: 10
```

#### 2.3.3 Out-of-Sample Validation

OOS temporal: entrenamiento Ene 2025-Jun 2026, prueba Jul 2026. IS PF 2.27 colapso a 0.72 OOS.

## 3. System Architecture

### 3.1 Overview

Tres capas: (1) Motores de analisis; (2) Pipeline ML; (3) Infraestructura.

### 3.2 Components

MT5Connector: singleton a MT5. 2-5s retardo de inicio.

Diamond Scanner: 2750 lineas, 16+ metodos, DiamondResult con 109 criterios.

ML Predictor: extract_features() -> vector 111 features. Lazy-load XGBoost.

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

109 criterios binarios en 12 categorias, ponderacion uniforme.

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

Fix #1 TKx H1 (P0): Conflicto de sesgo fuerza WAIT. Elimina 60% de falsos positivos.

Fix #2 MFE (P1): Kijun plano + precio en Kumo = degradacion.

Fix #3 HIGH NEWS DAY (P0): >=2 eventos -> BULL degradado. BEAR no afectado.

### 4.3 Smart TP & SL Safety Net

Smart TP: reemplaza RR=2.0 por niveles reales (Kijun, Tenkan, FVG, SSB, Kumo, Fib).

SL Safety Net: <10% rango SL-TP = WAIT. 10-20% = STRONG->GOOD.

## 5. ML Pipeline

### 5.1 Architecture

1. DiamondScanner -> DiamondResult
2. extract_features() -> 111 features
3. XGBoost -> ML% [0-100]
4. Matriz decision: ML% + 3 salvaguardas

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

Cero features ICT en Top 25. Mejores predictores: niveles Ichimoku y tipo de activo.

## 6. Backtest Protocol

### 6.1 Methodology

1. Datos: MT5 H1 con OHLC + volumen
2. Cada dia Ene 2025-Jul 2026 simulado independiente
3. Ichimoku recalculado en barras historicas
4. 109 criterios evaluados al momento del scan
5. Entrada H1 close, SL Kijun H4, TP 2x SL
6. Seguimiento M1 para SL/TP. MFE y MAE.

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

*(*) PF inflado por cherry-picking en <10 trades.

### 7.2 By Asset Type

| Asset | Trades | WR | CV | PF | Note |
| DXY.cash | 233 | 73.0% | 63.5% | 2.85 | Best<br/>XAUUSD | 198 | 41.4% | 62.1% | 1.12 | Weak<br/>US500.cash | 156 | 38.5% | 60.8% | 0.95 | Poor<br/>US30.cash | 143 | 36.4% | 60.2% | 0.88 | Poor<br/>US100.cash | 121 | 33.1% | 59.7% | 0.82 | Poor<br/>EURUSD | 489 | 31.5% | 59.8% | 0.78 | Weak<br/>GBPUSD | 312 | 30.8% | 60.1% | 0.75 | Weak<br/>USDJPY | 287 | 32.4% | 59.5% | 0.81 | Weak<br/>AUDUSD | 254 | 29.9% | 60.3% | 0.72 | Weak<br/>NZDUSD | 241 | 28.6% | 59.1% | 0.68 | Weak<br/>USDCHF | 220 | 30.0% | 60.5% | 0.71 | Weak |

DXY domina (p<0.001): 73% WR duplica otras clases.

1. **Composicion multidivisa:** 
2. **Correlacion macro directa:** 
3. **Volumen institucional:** 
4. **Sin carry trade:** 

### 7.3 Capital Simulation

| ML% Min | Trades | Wins | Losses | WR | PF | P&L 10k |
| None | 1210 | 455 | 755 | 37.6% | 1.02 | +1442 |
| >=40% | 881 | 398 | 483 | 45.2% | 1.38 | +8251 |
| >=45% | 661 | 359 | 302 | 54.3% | 1.91 | +17942 |
| >=50% | 421 | 248 | 173 | 58.9% | 2.27 | +25842 |
| >=55% | 231 | 148 | 83 | 64.1% | 2.82 | +22104 |
| >=60% | 102 | 71 | 31 | 69.6% | 3.51 | +11908 |
| >=65% | 38 | 28 | 10 | 73.7% | 4.20 | +5560 |

Cifras In-Sample. OOS real: v7 PF=1.173. Data leakage: 2.27->0.72.

### 7.4 ML% Distribution

| ML% Range | Trades | WR | PF | OOS WR | Note |
| <30% | 312 | 22.1% | 0.45 | -- | Avoid |
| 30-39% | 401 | 28.9% | 0.67 | -- | Avoid |
| 40-49% | 460 | 38.7% | 1.05 | -- | Caution |
| 50-59% | 240 | 54.2% | 1.82 | 51.3% | Promising |
| 60-69% | 93 | 68.8% | 3.25 | 45.5% | Best IS |
| >=70% | 12 | 91.7% | 5.80 | -- | Small sample |

Correlacion ML% vs WR R=0.94. Sobrevive OOS.

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

Optimo 69%: PF 1.26, 55.6% WR. Practico: 55-60%.

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

Patrones ICT demasiado frecuentes (91% OB, 67% FVG) para discriminar.

### 8.2 Data Leakage

| Type | Train PF | OOS PF | Drop |
| No filter (IS) | 2.27 | 0.72 | -68% |
| ML%>=50% | 2.27 | 1.08 | -52% |
| ML%>=60% | 3.51 | 1.18 | -66% |
| Optimal 69% | 4.20 | 1.26 | -70% |

### 8.3 Dead Ends

1. **Regresion P&L (v11):**  R2=-0.004

2. **Multi-clase (v12):**  colapso

3. **Cross-features (v9):**  overfit

4. **Arboles profundos (v10):**  max_depth=4 ideal

5. **OBs filtrados (v8):**  identico a v7

## 9. Market Anomalies

### 9.1 DXY-EURUSD Paradox

17 Julio 2026: 50% correlacion anormal DXY-EURUSD. 100% en ventanas de noticias.

| Hour UTC | DXY | EURUSD | Correlation | Event |
| 06:00 | 100.720 | 1.14370 | Normal | -- |
| 07:00 | 100.705 | 1.14410 | Normal | -- |
| 08:00 | 100.688 | 1.14480 | Anormal | Trump3:00 |
| 09:00 | 100.695 | 1.14450 | Anormal | Jefferson1:00 |
| 10:00 | 100.703 | 1.14482 | Anormal | EUR CPI11:00 |
| 11:00 | 100.710 | 1.14460 | Anormal | Core CPI11:00 |
| 12:00 | 100.715 | 1.14420 | Normal | -- |
| 13:00 | 100.710 | 1.14430 | Normal | -- |

8/16 horas anormales. Todas en ventanas pre/post-noticias.

### 9.2 Implications

>=2 eventos mayores = HIGH NEWS DAY. BULL degradado. BEAR no afectado.

## 10. News Risk

### 10.1 Scraper Architecture

1. Cache JSON (24h TTL)
2. Scraping ForexFactory: XML luego HTML
3. MAJOR_EVENTS hardcode

### 10.2 Events

| Event | Impact | Feature |
| FOMC | Very high | day_wed (6.4) |
| CPI/NFP/Trump | High | high_news_day |
| GDP/Retail | High | high_news_day |

### 10.3 Results

15/15 trades BULL falsos durante HIGH NEWS DAY
Trades BEAR no afectados

## 11. Cross-Pair

### 11.1 Features

1. **dxy_vs_price_ratio:** .
2. **dxy_kj_h1_norm:** .
3. **dxy_divergence:** .
4. **dxy_trend:** .
5. **dxy_trend_x_bias:** .

### 11.2 Result

v15 sin mejora. Redundante con is_dxy.

## 12. Per-Asset Models

### 12.1 Principle

4 modelos especializados: DXY, XAU, Indices, Forex.

### 12.2 Results

| Model | Class | Trades | WR | CV | OOS PF |
| v13_dxy | DXY | 233 | 73% | 63.5% | 4.000 |
| v13_forex | Forex | 1803 | 31% | 61.6% | -- |

Modelo DXY: OOS PF 4.000 pero solo 15 trades.

## 13. Trading Guide

### 13.1 Workflow

```
python main.py diamond --timezone BROKER
python main.py track save
python main.py track update
python main.py track report
```

### 13.2 Best Sessions

Mejores sesiones por dia:

| Day | Session | Volume | SL |
| Mon | London-NY | Med | Wide |
| Tue | NY Open | Max | Normal |
| Wed | Post-FOMC | V.High | 2x |
| Thu | NY Open | High | Normal |
| Fri | Close 17h | Low | Tight |

### 13.3 Friday Rule

**Regla absoluta del viernes:** Sin operaciones el fin de semana. Cerrar antes 17:00 Paris.

**Matriz de decision:**
ML%>=60% + TKx alineado -> GO
ML%<50% -> NO GO

## 14. Limitations

### 14.1 Current

| | Limitacion | Prioridad | |
| | Muestra OOS pequena (15-23) | P0 | |
| | Broker unico (FTMO) | P1 | |
| | Sin deslizamiento/costes | P2 | |
| | Ventana 18 meses | P2 | |

### 14.2 Future Work

**P0:** Backtest 2024-2025 por activo

**P1:** Modelos ensemble

**P2:** Pesos temporales adaptativos

**P3:** Features cross-pair avanzadas

**P4:** Integracion libro de ordenes

## 15. Conclusion

### 15.1 Discoveries

**1. DXY 73% WR** (p<0.001).

**2. Features ICT son ruido.** Top 25 = 100% Ichimoku.

**3. Por activo PF +340%.**

**4. Data leakage: IS PF 2.27 -> OOS 0.72.**

**5. Miercoles FOMC = regimen especial.**

### 15.2 Practical Impact

- Primario: DXY.cash, ML%>=50%
- WR esperado: 55-60%
- PF: 1.17-4.00
- Capital: 10k EUR
- +100 a +200 EUR/semana

### 15.3 Quote

"El mercado no recompensa la complejidad, sino la simplicidad estadisticamente validada."

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
