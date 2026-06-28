# backtest_ict_fvg_v1.py — Version Simple (sans filtres stricts)

> **Fichier** : `backtest_ict_fvg_v1.py`
> **Sortie** : `reports/backtest_ict_fvg_v1_results.json`
> **Résultat** : 214 trades, 17.8% WR, +105.08R, 2000€ → 4856€ (+143%)

---

## Ce que fait ce script

Backtest d'une stratégie de trading ICT (Inner Circle Trader) basée sur les Fair Value Gaps (FVG), appliquée à l'or (XAUUSD) en timeframe M3 du 2 janvier au 26 juin 2026.

Le script est **volontairement simple** : il n'applique **aucun filtre macro, kill zone, equal highs/lows, NWOG, IFVG ou breakeven**. C'est la version qui maximise le nombre de trades et le R total.

---

## Algorithme (5 étapes simplifiées)

### Étape 1 — Draw On Liquidity (DOL)
Pour chaque jour de trading, 4 paires DOL/niveau opposé sont calculées :
- **PDH** (Previous Day High) → cible haussière, opposé = PDL
- **PDL** (Previous Day Low) → cible baissière, opposé = PDH
- **Asian High** (00:00–08:00 UTC) → cible haussière, opposé = Asian Low
- **Asian Low** (00:00–08:00 UTC) → cible baissière, opposé = Asian High

### Étape 2 — Raid de liquidité opposée
Pour chaque paire, le script cherche un **raid de la liquidité opposée** dans les 480 dernières barres (24h en M3). Un raid est :
- **BSL** (Buy Side Liquidity) : le high traverse le niveau ET le close rejette en dessous
- **SSL** (Sell Side Liquidity) : le low traverse le niveau ET le close rejette au-dessus

**Aucune validation supplémentaire** (pas de macro 10/50, pas de kill zone, pas d'equal highs/lows).

### Étape 3 — Premier FVG + retracement
Après le raid, le script scanne les 240 barres suivantes pour trouver le **premier FVG** dans la direction du DOL. Un FVG est un déséquilibre en 3 bougies où C1 et C3 ne se chevauchent pas. Le FVG doit avoir une taille ≥ 0.02% du prix.

Une fois le FVG trouvé, le script attend que le prix **retrace dans la zone** du FVG (jusqu'à 120 barres). L'entrée se fait au **midpoint** de la zone FVG.

Si pas de FVG ou pas de retracement → pas de trade.

### Étape 4 — Stop Loss
Le SL est placé au-delà de la **bougie #1 du FVG** + un buffer de `gap_size × 0.2`.

### Étape 5 — Take Profits
- **TP1** (50% de la position) : au point médian entre l'entrée et le DOL
- **TP2** (50% restant) : juste avant le DOL (dol_level ± gap_size)

Pas de breakeven après TP1.

---

## Fichier de sortie

`reports/backtest_ict_fvg_v1_results.json` contient pour chaque trade :
```json
{
  "day": "2026-01-08",
  "dol_label": "PDH(2026-01-07)",
  "dol_level": 4500.44,
  "dol_direction": "bull",
  "opposing_label": "PDL(2026-01-07)",
  "opposing_level": 4423.36,
  "raid_time": 1767889800,
  "fvg_time": 1767890880,
  "fvg_type": "bullish",
  "fvg_gap_pct": 0.023,
  "entry_price": 4432.51,
  "sl_price": 4424.97,
  "tp1_price": 4466.48,
  "tp2_price": 4499.44,
  "direction": "bull",
  "status": "WIN_FULL",
  "pnl_r": 6.69,
  "tp1_hit": true,
  "tp2_hit": true,
  "sl_hit": false,
  "exit_time": 1767978540
}
```

---

## Résultats

| Métrique | Valeur |
|----------|--------|
| Trades | 214 |
| Gagnants (full) | 38 |
| Perdants | 176 |
| Winrate | 17.8% |
| R moyen / trade | +0.49R |
| R total | +105.08R |
| BUY winrate | 14.0% |
| SELL winrate | 21.5% |
| Capital 2000€ → | **4 856,39 € (+143%)** |

---

## Utilisation

```bash
python backtest_ict_fvg_v1.py
```

Prérequis : le fichier `reports/xauusd_m3_2026_01_01_to_2026_06_26.json` doit exister (généré par `download_xauusd_m1.py`).

---

## Pourquoi cette version ?

- **Maximise le volume** : 214 trades en 6 mois (~35/mois)
- **Maximise le R total** : +105R, soit ~5000€ avec 2000€ de capital
- **Simple à comprendre et répliquer** : pas de logique complexe de timezone, DST, ou equal highs
- **Idéal pour le live trading** : beaucoup d'opportunités, expectancy positive

---

## Scripts live associés

| Script | Description |
|--------|-------------|
| **`live_ict_monitor.py XAUUSD`** | Surveillance temps réel de CETTE stratégie (alertes + log JSON) |
| `backtest_ict_universal.py XAUUSD` | Même algorithme, paramétrable pour tout symbole |
| `download_historical.py XAUUSD` | Télécharger les données M3 depuis MT5 |

> 📖 **Guide utilisateur complet** : `new_analysis_02/guide_ict_fvg_live.md`
> 📖 **Algorithme détaillé** : `new_analysis_02/algo.md`
