# backtest_ict_fvg.py — Version Complète (filtres ICT stricts)

> **Fichier** : `backtest_ict_fvg.py`
> **Sortie** : `reports/backtest_ict_fvg_results.json`
> **Résultat** : 21 trades, 19.0% WR, +18.66R, 2000€ → 2363€ (+18%)

---

## Ce que fait ce script

Backtest d'une stratégie ICT FVG **100% conforme au framework SMC/ICT en 5 étapes**, appliquée au XAUUSD M3 (janvier–juin 2026).

Contrairement à la v1, cette version applique **tous les filtres ICT** : macros 10/50, kill zones (London Open, NY Open, London Close), equal highs/lows, NWOG, IFVG, et breakeven après TP1.

Le résultat : beaucoup moins de trades, mais de meilleure qualité par trade.

---

## Algorithme (5 étapes complètes)

### Étape 1 — Draw On Liquidity (3 sources)

| Source | Description |
|--------|-------------|
| **PDH/PDL** | Previous Day High/Low du jour de trading précédent |
| **Asian H/L** | Session asiatique 00:00–08:00 UTC |
| **NWOG** | New Week Opening Gap (gap vendredi close → lundi open), uniquement les lundis |

Pour chaque source, 2 paires DOL/niveau opposé sont créées (une haussière, une baissière).

### Étape 2 — Raid de liquidité opposée + validation stricte

Le raid doit :
1. **Être sur la liquidité OPPOSÉE** (pas le DOL lui-même)
2. **Tomber sur une macro 10/50** (±5 minutes autour de :10 ou :50 de chaque heure, avec wraparound)
3. **Être dans une kill zone ICT** (heures ET converties en UTC avec gestion DST)

#### Kill zones (Eastern Time → UTC)

| Kill Zone | Heures ET | UTC (EST, hiver) | UTC (EDT, été) |
|-----------|-----------|-------------------|-----------------|
| London Open | 2:00–5:00 AM | 7:00–10:00 | 6:00–9:00 |
| NY Open | 8:30–11:00 AM | 13:30–16:00 | 12:30–15:00 |
| London Close | 10:00 AM–12:00 PM | 15:00–17:00 | 14:00–16:00 |

Le DST 2026 commence le 8 mars (passage EST→EDT).

#### Equal highs/lows (optionnel, désactivé par défaut)
Vérifie que le raid « nettoie » un cluster d'au moins 2 swing highs/lows dans une tolérance de 0.08% du prix sur les 96 dernières barres.

### Étape 3 — Entrée FVG ou IFVG

**Option A — FVG standard** : premier Fair Value Gap après le raid, dans la direction du DOL. Entrée au midpoint de la zone après retracement.

**Option B — IFVG** (fallback si Option A échoue) : Inverse FVG formé dans la direction opposée au DOL pendant la jambe de manipulation, qui a été traversé par le prix (inversé), et dont le prix est revenu dans la zone **après** l'inversion.

### Étape 4 — Stop Loss dur
SL au-delà de la bougie #1 du FVG + buffer `gap_size × 0.2`. Ancré mécaniquement, sans discrétion.

### Étape 5 — Take Profits + Breakeven
- **TP1** : 50% de la position au milieu entrée→DOL
- **Breakeven** : après TP1 touché, le SL est déplacé au prix d'entrée
- **TP2** : 50% restant juste avant le DOL

---

## Fichier de sortie

`reports/backtest_ict_fvg_results.json` — même structure que la v1, avec des champs supplémentaires :
```json
{
  "entry_type": "fvg",       // "fvg" ou "ifvg"
  "breakeven_activated": true, // si le SL a été remonté au BE
  ...
}
```

---

## Résultats

| Métrique | Valeur |
|----------|--------|
| Trades | 21 |
| Gagnants (full) | 4 |
| Perdants | 17 |
| Winrate | 19.0% |
| R moyen / trade | +0.89R |
| R total | +18.66R |
| BUY winrate | 18.2% |
| SELL winrate | 20.0% |
| Capital 2000€ → | **2 362,70 € (+18%)** |

### Filtrage des raids

| Étape | Raids |
|-------|------:|
| Raids détectés | 297 |
| Rejetés (macro) | 172 |
| Rejetés (kill zone) | 102 |
| Rejetés (equal H/L) | 0 |
| **Survivants** | **23** |
| FVG trouvés | 23 |
| IFVG trouvés | 2 |
| Trades exécutés | 21 |

---

## Configuration

Tous les paramètres sont ajustables en début de fichier :

```python
USE_PDH_PDL        = True    # DOL : Previous Day High/Low
USE_ASIAN_HL        = True    # DOL : Asian Session High/Low
USE_NWOG            = True    # DOL : New Week Opening Gap

REQUIRE_MACRO       = True    # Exiger macro 10/50
REQUIRE_KILL_ZONE   = True    # Exiger kill zone ICT
REQUIRE_EQUAL_HL    = False   # Exiger equal highs/lows

MACRO_TOLERANCE_MIN = 5       # ± minutes autour de :10/:50
BREAKEVEN_AFTER_TP1 = True    # SL → entrée après TP1
USE_IFVG            = True    # Chercher aussi les IFVGs
```

---

## Utilisation

```bash
python backtest_ict_fvg.py
```

---

## Comparaison v1 vs v2

| | v1 (simple) | v2 (filtres ICT) |
|---|---|---|
| Trades | 214 | 21 |
| Winrate | 17.8% | 19.0% |
| R/trade | +0.49R | +0.89R |
| R total | +105R | +19R |
| Capital final | 4 856 € | 2 363 € |

**Conclusion** : la v2 est plus conforme au framework ICT mais beaucoup moins rentable en absolu car elle filtre 93% des opportunités. La v1 est recommandée pour le trading réel.

---

## Scripts live associés

| Script | Description |
|--------|-------------|
| **`live_ict_monitor.py XAUUSD`** | Surveillance live de la stratégie (v1 par défaut) |
| `backtest_ict_universal.py XAUUSD` | Version universelle paramétrable |
| `download_historical.py XAUUSD` | Données M3 depuis MT5 |

> 📖 **Guide utilisateur complet** : `new_analysis_02/guide_ict_fvg_live.md`
> 📖 **Algorithme détaillé** : `new_analysis_02/algo.md`
