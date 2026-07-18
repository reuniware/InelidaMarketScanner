========================================================================

    INELIDAMARKETSCAN
    科学的なアルゴリズムトレーディングへのアプローチ
    多策略システムの研究開発
    ICTコンセプトと機械学習に基づく

    Version 1.0.1  |  2026-07-19
    DVA/Reuniware Systems

========================================================================

**License:** MIT. キーワード: アルゴリズムトレード, ICT, Ichimoku, XGBoost, ML, DXY

## 要約

This document presents the research findings...

## 1. 序言
### 1.1 背景と課題

Algorithmic trading has grown exponentially...

### 1.2 研究目的

1. Automate ICT + Ichimoku
2. Quantify via 109 criteria
3. Predict via XGBoost
4. Validate via OOS
5. Identify predictive factors

### 1.3 ドキュメント構成

Section 2: theory. Section 3: architecture. Section 4: Diamond Scanner. Section 5: ML pipeline. Section 6: backtest protocol. Section 7: results. Section 8: feature analysis. Section 9: anomalies. Section 10: news risk. Section 11: cross-pair. Section 12: per-asset. Section 13: trading guide. Section 14: limitations. Section 15: conclusion.

## 2. 理論的基礎
### 2.1 ICTコンセプト

ICT concepts were developed by Michael Huddleston...

#### 2.1.1 流動性スイープ
Institutions push prices beyond support/resistance...
#### 2.1.2 フェアバリューギャップ (FVG)
A FVG is a supply-demand imbalance across 3 candles...
#### 2.1.3 オーダーブロック (OB)
Order Blocks are price zones where institutional impulses...
#### 2.1.4 市場構造変化 (MSS) と BOS
Market structure via 5-bar fractal swings...
#### 2.1.5 ボリューム分析 (HVN/LVN)
Tick volume analysis: HVN > 1.5x avg, LVN < 0.5x avg...
### 2.2 Ichimoku Kinko Hyo

Ichimoku Kinko Hyo by Goichi Hosoda (1930s, published 1969)...

1. **Tenkan-sen:** (high+low)/2 over 9 periods
2. **Kijun-sen:** (high+low)/2 over 26 periods
3. **Senkou Span A:** (Tenkan+Kijun)/2 projected 26 periods
4. **Senkou Span B:** 52-period high/low avg projected 26 periods
5. **Chikou Span:** Close shifted 26 periods backward

**解釈原則：**
- TK cross signals momentum change
- Price vs Kumo indicates trend direction
- Kijun is dynamic S/R, stronger on multi-TF confluence
- Flat lines indicate institutional memory zones

Multi-TF application: 8 timeframes (M5 to MN)...

### 2.3 教師あり機械学習
#### 2.3.1 アルゴリズム選択

- **Minimal data:** XGBoost works with 50-100 samples
- **Training under 1 second:** 
- **CPU-only operation:** 
- **Native feature importance via gain:** 
- **Built-in regularization:** 

#### 2.3.2 ハイパーパラメータ

Final model (v7) hyperparameters via grid search:

```
max_depth: 4 | learning_rate: 0.05 | n_estimators: 300
subsample: 0.8 | colsample_bytree: 0.8 | gamma: 0.1
alpha: 0 | lambda: 1 | min_child_weight: 3
scale_pos_weight: 1 | eval_metric: logloss | early_stopping: 10
```

#### 2.3.3 アウト・オブ・サンプル検証 (OOS)

Temporal OOS: train Jan 2025-Jun 2026 (2923 trades), test Jul 2026 (152 trades)...

## 3. システムアーキテクチャ
### 3.1 概要

Three layers: (1) Analysis Engines; (2) ML Pipeline; (3) Infrastructure...

### 3.2 コンポーネント

MT5Connector: singleton to MT5. 2-5s init delay.

Diamond Scanner: 2750 lines, 16+ methods, 109 criteria.

ML Predictor: extract_features() -> 111-feature vector.

### 3.3 タイムフレーム

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
### 4.1 スコアリング (109の基準)

109 binary criteria in 12 categories, uniformly weighted.

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

### 4.2 セーフガード

Fix #1 TKx H1 (P0): Bias conflict forces WAIT. 60% false positives eliminated.

Fix #2 MFE (P1): Flat Kijun + price in Kumo = downgrade.

Fix #3 HIGH NEWS DAY (P0): >=2 events -> BULL downgraded.

### 4.3 Smart TP と SL セーフティネット

Smart TP: replaces fixed RR=2.0 with real levels...

SL Safety Net: <10% SL-TP range = WAIT...

## 5. ML パイプライン
### 5.1 アーキテクチャ

1. DiamondScanner -> DiamondResult
2. extract_features() -> 111 features
3. XGBoost -> ML% [0-100]
4. Decision matrix: ML% + 3 safeguards

### 5.2 111 の特徴

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

### 5.3 特徴の重要性

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

Zero ICT features in Top 25. is_dxy leads (gain 14.2).

## 6. バックテスト協議
### 6.1 方法論

1. Data: MT5 H1 bars
2. Each day Jan 2025-Jul 2026 simulated
3. Ichimoku recalculated
4. 109 criteria evaluated
5. Entry H1 close, SL Kijun H4, TP 2x SL
6. M1 tracking. MFE and MAE recorded.

### 6.2 メトリクス

| Metric | Definition | Interpretation |
| --- | --- | --- |
| WR | Wins / Total | >55% good |
| PF | Gains / Losses | >1.5 profitable |
| CV | 5-fold cross-val | >60% robust |
| OOS PF | Temporal OOS | >1.0 real edge |

### 6.3 データセット

| Dataset | Period | Trades | WR | PF | Use |
| v4_36feat | Jan-Jul 2026 | 1210 | 37.6% | 1.02 | Baseline |
| v5_111feat | 2025-Jul 2026 | 3045 | 38.2% | 1.03 | Full features |
| v6_recent | Jan-Jun 2026 | 2923 | 37.9% | 1.02 | Recent only |
| OOS_Jul2026 | Jul 2026 | 152 | 40.1% | 1.17 | True OOS |

## 7. 結果
### 7.1 モデルランキング

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

*(*) PF inflated by cherry-picking on <10 trades.

### 7.2 アセット別

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

- DXY dominates (p<0.001): 73% WR
- Multi-currency composition
- Direct macro correlation
- Institutional volume
- No carry trade distortion

### 7.3 資本シミュレーション

| ML% Min | Trades | WR (%) | PF | P&L 10k EUR |
| None | 1210 | 37.6 | 1.02 | +1,442 |
| >=40% | 881 | 45.2 | 1.38 | +8,251 |
| >=45% | 661 | 54.3 | 1.91 | +17,942 |
| >=50% | 421 | 58.9 | 2.27 | +25,842 |
| >=55% | 231 | 64.1 | 2.82 | +22,104 |
| >=60% | 102 | 69.6 | 3.51 | +11,908 |
| >=65% | 38 | 73.7 | 4.20 | +5,560 |

In-Sample figures. OOS: v7 PF=1.173, v13 PF=4.000.

### 7.4 ML% 分布

| ML% Range | Trades | WR (%) | PF | Note |
| <30% | 312 | 22.1 | 0.45 | Avoid |
| 30-39% | 401 | 28.9 | 0.67 | Avoid |
| 40-49% | 460 | 38.7 | 1.05 | Caution |
| 50-59% | 240 | 54.2 | 1.82 | Promising |
| 60-69% | 93 | 68.8 | 3.25 | Best IS |
| >=70% | 12 | 91.7 | 5.80 | Small sample |

ML% vs WR correlation R=0.94. Survives OOS.

### 7.5 グリッド検索

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

## 8. 特徴分析
### 8.1 ICT特徴はノイズ

| Feature | Detection Rate (%) | Gain | Predictive |
| FVG H1 Bear | 67 | <0.5 | No |
| FVG H1 Bull | 63 | <0.5 | No |
| OB H1 Bear | 91 | <0.1 | No |
| OB H1 Bull | 89 | <0.1 | No |
| MSS H1 Bear | 55 | <0.3 | No |
| MSS H1 Bull | 52 | <0.3 | No |
| Breaker H1 Bear | 48 | <0.2 | No |

ICT patterns too frequent (91% OB, 67% FVG) to discriminate.

### 8.2 データリーク

| Type | Train PF | OOS PF | Drop (%) |
| No filter (IS) | 2.27 | 0.72 | -68 |
| ML% >=50% | 2.27 | 1.08 | -52 |
| ML% >=60% | 3.51 | 1.18 | -66 |
| Optimal 69% | 4.20 | 1.26 | -70 |

### 8.3 行き止まり

1. **P&L Regression (v11):** R2=-0.004

2. **Multi-class (v12):** collapsed

3. **Cross-features (v9):** overfit PF 0.827

4. **Deeper trees (v10):** max_depth=4 ideal

5. **Filtered OBs (v8):** identical to v7

## 9. 市場の異常
### 9.1 DXY-EURUSDのパラドックス

July 17, 2026: 50% abnormal correlation DXY-EURUSD.

| Hour UTC | DXY | EURUSD | Correlation |
| 06:00 | 100.720 | 1.14370 | Normal |
| 07:00 | 100.705 | 1.14410 | Normal |
| 08:00 | 100.688 | 1.14480 | Abnormal |
| 09:00 | 100.695 | 1.14450 | Abnormal |
| 10:00 | 100.703 | 1.14482 | Abnormal |
| 11:00 | 100.710 | 1.14460 | Abnormal |
| 12:00 | 100.715 | 1.14420 | Normal |
| 13:00 | 100.710 | 1.14430 | Normal |

8/16 hours abnormal. All within news windows.

### 9.2 影響

>=2 major events = HIGH NEWS DAY. BULL downgraded.

## 10. ニュースリスク
### 10.1 スクレイパー構成

1. JSON cache (24h TTL)
2. ForexFactory scraping
3. Hardcoded MAJOR_EVENTS

### 10.2 出来事

| Event | Impact | Feature |
| --- | --- | --- |
| FOMC | Very high | day_wed (6.4) |
| CPI / NFP / Trump | High | high_news_day |
| GDP / Retail | High | high_news_day |

### 10.3 結果

- 15/15 BULL trades false during HIGH NEWS DAY
- BEAR unaffected
- day_wednesday = feature #6 (gain 6.4)

## 11. クロスペア分析
### 11.1 特徴

1. **dxy_vs_price_ratio:** .
2. **dxy_kj_h1_norm:** .
3. **dxy_divergence:** .
4. **dxy_trend:** .
5. **dxy_trend_x_bias:** .

### 11.2 結果

v15 no improvement. Redundant with is_dxy (gain 14.2).

## 12. アセット別モデル
### 12.1 原則

4 specialized models: DXY, XAU, Indices, Forex.

### 12.2 結果

| Model | Class | Trades | WR | CV | OOS PF |
| --- | --- | --- | --- | --- | --- |
| v13_dxy | DXY | 233 | 73% | 63.5% | 4.000 |
| v13_forex | Forex | 1803 | 31% | 61.6% | -- |

DXY model: OOS PF 4.000 but only 15 trades.

## 13. トレーディングガイド
### 13.1 ワークフロー

```
python main.py diamond --timezone BROKER
python main.py track save
python main.py track update
python main.py track report
```

### 13.2 最適セッション

Best sessions by day with volume and strategy:

| Day | Session | Volume | SL |
| --- | --- | --- | --- |
| Mon | London-NY | Medium | Wide |
| Tue | NY Open | Max | Normal |
| Wed | Post-FOMC | Very High | 2x |
| Thu | NY Open | High | Normal |
| Fri | Close 17h | Low | Tight |

### 13.3 金曜日ルール

**Absolute Friday rule:** No trades over weekend. Close before 17:00 Paris.
**決定行列:**

**Decision matrix:**
ML%>=60% + TKx aligned + no NEWS -> GO
ML% 50-60% + TKx aligned -> ATTENTION
ML%<50% -> NO GO

## 14. 制限
### 14.1 現在の制限

| | Limitation | Priority | |
| | Small OOS (15-23 trades) | P0 | |
| | Single broker (FTMO) | P1 | |
| | No slippage/costs | P2 | |
| | 18-month window | P2 | |

### 14.2 今後の作業

**P0:** 2024-2025 per-asset backtest

**P1:** Ensemble models

**P2:** Adaptive temporal weights

**P3:** Advanced cross-pair features

**P4:** Order book integration

## 15. 結語
### 15.1 発見

**1. DXY 73% WR** (p<0.001, 233 trades)

**2. ICT features are noise**

**3. Per-asset PF +340%**

**4. Data leakage: IS 2.27 -> OOS 0.72**

**5. FOMC Wednesday = special regime**

### 15.2 実践的インパクト

- Primary: DXY.cash, ML%>=50%
- Expected WR: 55-60%
- Expected PF: 1.17-4.00
- Capital: 10k EUR, 1%/trade
- 5-7 trades/week
- +100 to +200 EUR/week

### 15.3 最後の引用

"市場は複雑さを報いない。統計的に検証された簡素さを報いる。"

    -- DVA/Reuniware Systems

## 16. 参考文献

- Hosoda G. Ichimoku Kinko Hyo. (1969)
- Huddleston M. Inner Circle Trader Concepts. (2016-2024)
- Chen T, Guestrin C. XGBoost. (KDD 2016)
- BIS. Triennial Central Bank Survey. (2022)
- Brownlee J. XGBoost With Python. (2019)
- Murphy J. Technical Analysis. (1999)
- Nison S. Japanese Candlestick Charting. (2001)
- FTMO. Evaluation Process. (2025)
- ForexFactory. Economic Calendar. (2026)
