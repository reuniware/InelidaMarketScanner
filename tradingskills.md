# Trading Skills — Référence ICT & Analyse Marché

> Document destiné à optimiser les futures analyses en centralisant les concepts,
> formules, conventions et méthodologies utilisés dans InelidaMarketScan.
> Dernière mise à jour : 25 juin 2026.

---

## 1. Architecture du Projet

```
InelidaMarketScan/
├── src/
│   ├── __init__.py
│   ├── config.py           # Configuration centralisée (watchlist, MT5, sweep params)
│   ├── mt5_connector.py    # Connexion MT5 (singleton)
│   ├── market_scanner.py   # Scanner ticks temps réel
│   ├── sweep_detector.py   # Détection sweeps BSL/SSL + Asian range + Fibonacci
│   ├── database.py         # SQLite persistence (asian, sweeps, levels)
│   ├── display.py          # Affichage console formaté
│   ├── ai_analyst.py       # Analyse AI des données
│   ├── ai_client.py        # Client API AI (Gemini)
│   └── trade_executor.py   # Exécution trades automatisée
├── backtest_report_trades.py # Backtest trades depuis PDF (M1/M5/M15/H1)
├── generate_live_report.py # Générateur PDF rapport live
├── generate_user_guide_pdf.py # Générateur PDF guide utilisateur
├── generate_report.py     # Générateur rapport template
├── app.py                  # Dashboard Streamlit
├── live_monitor.py         # Surveillance temps réel (sweeps fractals + daily)
├── live_alerts.py          # Moniteur continu signaux trades (entry, SL, TP, RR)
├── main.py                 # Point d'entrée CLI
├── reports/                # Tous les PDFs générés (rapports, guide)
├── tradingskills.md        # ← Ce document
└── .env                    # Variables d'environnement (clés API)
```

### Fichiers importants :

| Fichier | Rôle | Usage |
|---------|------|-------|
| `src/sweep_detector.py` | Détection sweeps, Asian range, Fibonacci, trades, **spread** | Cœur de l'analyse |
| `src/config.py` | Watchlist, paramètres MT5/Sweep/DB | Personnalisation |
| `src/display.py` | Affichage console formaté (setups, asian, niveaux) | Tableaux couleur |
| `generate_live_report.py` | PDF complet avec tous les scans + **spread** | Rapport final |
| `backtest_report_trades.py` | Backtest M1/M5/M15/H1 depuis un PDF | Vérification a posteriori |
| `live_monitor.py` | Sweeps fractals (BSL/SSL) + daily/weekly en temps réel | Surveillance - aucune exécution |
| `live_alerts.py` | Signaux trades ICT (entry, SL, TP, RR) + filtre spread | Moniteur 30s avec BEEP |
| `app.py` | Dashboard Streamlit | Visualisation live |

---

## 2. Concepts ICT (Inner Circle Trader)

### 2.1 BSL / SSL (Buy-side / Sell-side Liquidity)

| Terme | Définition | Détection |
|-------|-----------|-----------|
| **BSL** | Buy-side liquidity — stops au-dessus des swing highs | `bar.high > swing.level AND bar.close < swing.level` |
| **SSL** | Sell-side liquidity — stops en-dessous des swing lows | `bar.low < swing.level AND bar.close > swing.level` |
| **Sweep** | La mèche traverse le niveau + close rejette de l'autre côté | Condition ICT stricte |
| **Breach** | La mèche traverse juste le niveau (peu importe le close) | Détection moins contraignante |

### 2.2 Williams Fractals

```
Swing haut = bar[i].high > toutes les highs dans [i-N, i+N] (i exclu)
Swing bas  = bar[i].low  < toutes les lows  dans [i-N, i+N] (i exclu)

N = 2 par défaut (fractal_n dans config.py)
```

### 2.3 Asian Session Range

```
Session asiatique : UTC 00:00 — 08:00 (8 heures)
Timeframe         : H1 par défaut (8 bougies pour couvrir la session)

AH = Asian High = max(high) des bougies asiatiques
AL = Asian Low  = min(low)  des bougies asiatiques
Range = AH - AL
```

### 2.4 Séances de Trading (ICT)

| Session | UTC | Heure Paris (CEST) | Rôle ICT |
|---------|-----|--------------------|----------|
| Asian | 00:00-08:00 | 02:00-10:00 | Range « fair value », point de départ |
| London Open | 08:00-09:00 | 10:00-11:00 | Manipulation, sweep du range asiatique |
| London | 08:00-13:00 | 10:00-15:00 | Direction principale souvent établie |
| NY Open | 13:00-14:00 | 15:00-16:00 | Deuxième manipulation, double sweep possible |
| NY | 13:00-21:00 | 15:00-23:00 | Continuation ou retournement |
| Asian pre | 22:00-00:00 | 00:00-02:00 | Pré-session asiatique |

### 2.5 CHoCH / MSS (Change of Character / Market Structure Shift)

```
CHoCH HAUSSIER :
  1. Prix casse un swing LOW (nouveau plus bas)
  2. Puis casse un swing HIGH (plus haut que le précédent)
  → « Higher high + higher low » = uptrend

CHoCH BAISSIER :
  1. Prix casse un swing HIGH (nouveau plus haut)
  2. Puis casse un swing LOW (plus bas que le précédent)
  → « Lower high + lower low » = downtrend

MSS = Market Structure Shift = synonyme ICT de CHoCH
```

#### Détection algorithmique :

```python
# H1 CHoCH check (basé sur les 12 dernières H1)
early_highs = max(h1_highs[:5])   # premières 5 H1
late_highs  = max(h1_highs[5:])   # dernières 7 H1
early_lows  = min(h1_lows[:5])
late_lows   = min(h1_lows[5:])

if late_highs > early_highs AND late_lows > early_lows:
    CHoCH = HAUSSIER
elif late_highs < early_highs AND late_lows < early_lows:
    CHoCH = BAISSIER
else:
    CHoCH = RANGÉE/INCERTAIN
```

### 2.6 Sweep + Fib = Trade ICT

**Conditions pour un trade (modèle classique) :**

```
BUY  = (AL sweepé + prix > AH) OU (AH+AL sweepés + prix > AH)
SELL = (AH sweepé + prix < AL) OU (AH+AL sweepés + prix < AL)
```

**SL = 0.10 × range** au-delà du côté opposé :

```
BUY  SL = AL − 0.10 × range
SELL SL = AH + 0.10 × range
```

**Patterns supplémentaires (fakeout / continuation) — non implémentés :**

Quand le prix continue dans la même direction que le sweep au lieu de traverser
vers l'autre liquidité (à implémenter dans `sweep_detector.py`) :

```
AH sweepé + prix > AH → BUY continuation (fakeout baissier → bullish)
AL sweepé + prix < AL → SELL continuation (fakeout haussier → bearish)
```

Exemple USDCHF 26/06/2026 :
```
AL = 0.80849 | Sweep London | Prix = 0.80819 (sous le AL)
→ SELL continuation bearish (SSL pris, le prix continue de descendre)
```

### 2.7 Diagnostic « 0 trade »

Quand un scan produit 0 trade malgré des setups détectés, vérifier :

| Cause | Symptôme | Pattern | Implémenté |
|-------|----------|---------|:----------:|
| **Fakeout haussier** | AH sweepé, prix > AH | BSL pris → prix monte (pas de SELL valide) | ❌ |
| **Fakeout baissier** | AL sweepé, prix < AL | SSL pris → prix descend (pas de BUY valide) | ❌ |
| **Range trop serré** | Range < 0.05% du midpoint | Pas assez d'amplitude pour un trade | ✅ filtré |
| **Session trop tôt** | Post-Asian < 2 barres H1 | Pas assez de données pour détecter les sweeps | ✅ implicite |
| **Pas de sweep** | Breach sans rejet | Pas de sweep ICT complet | ✅ filtré |

> ⚠️ Les patterns de fakeout (continuation après sweep) ne sont **pas encore implémentés**
> dans `sweep_detector.py`. Ils sont documentés ici pour référence et ajout futur.

---

## 3. Fibonacci Extensions

### 3.1 Niveaux

```python
_FIB_LEVELS_BULL = (1.618, 2.0, 2.618, 3.0, 3.618, 4.0)
_FIB_LEVELS_BEAR = (-1.618, -2.0, -2.618, -3.0, -3.618, -4.0)
```

### 3.2 Formules

```
Bull level = AH + fib × range    (ex: AH + 1.618 × range)
Bear level = AL + fib × range    (ex: AL + (-2.618) × range = AL − 2.618 × range)
```

### 3.3 Détermination du fib_state

```python
def _next_bear(price, al, rs):
    for n in (-1.618, -2.0, -2.618, -3.0, -3.618, -4.0):
        lvl = al + n * rs          # n négatif → lvl < al
        if price > lvl:            # prix ENCORE au-dessus du niveau ?
            return f"{n}"          # prochain niveau à atteindre
    return f"{last}_DONE"          # tous dépassés

def _next_bull(price, ah, rs):
    for n in (1.618, 2.0, 2.618, 3.0, 3.618, 4.0):
        lvl = ah + n * rs          # n positif → lvl > ah
        if price < lvl:            # prix ENCORE en-dessous du niveau ?
            return f"+{n}"         # prochain niveau à atteindre
    return f"+{last}_DONE"         # tous dépassés
```

### 3.4 Exemple UKOIL.cash (24 juin 2026)

```
AH = 76.963    AL = 76.020    Range = 0.943

Fib −1.618 = 76.020 + (-1.618) × 0.943 = 74.494  ← TP1 original
Fib −2.0   = 76.020 + (-2.0)   × 0.943 = 74.134  ← TP2 original
Fib −2.618 = 76.020 + (-2.618) × 0.943 = 73.551  ← TP1 nouveau signal
Fib −3.0   = 76.020 + (-3.0)   × 0.943 = 73.191
Fib −3.618 = 76.020 + (-3.618) × 0.943 = 72.608
Fib −4.0   = 76.020 + (-4.0)   × 0.943 = 72.248
```

---

## 4. Analyse des Gaps Daily

### 4.1 Définition

```
Gap = Open[jour N+1] − Close[jour N]

Si Gap > 0 : Gap haussier (prix ouvre au-dessus de la veille)
Si Gap < 0 : Gap baissier (prix ouvre en-dessous de la veille)
```

### 4.2 Rôle en ICT

- Les gaps non comblés agissent comme des **aimants** — le prix tend à revenir les combler
- Un gap baissier **au-dessus** du prix = résistance
- Un gap haussier **en-dessous** du prix = support
- Un gap **hausster** non comblé au-dessus du prix = le prix peut descendre pour le combler (bearish pull)

### 4.3 Identification des niveaux de gap

```
Exemple UKOIL 27 février 2026 :
  27/02 Close = 73.417    02/03 Open = 77.590
  Gap = 77.590 − 73.417 = +4.173 (HAUSSIER)

  Haut du gap = 77.590 (open 02/03)
  Bas du gap  = 73.417 (close 27/02)

  MAIS AUSSI : High de la bougie 27/02 = 73.834 → premier support
  Le « vrai » bottom de la zone gap inclut le range de la bougie précédente
```

---

## 5. Position Sizing

### 5.1 Formule générale

```
Lots = (Capital × Risque%) ÷ (SL_distance × ValeurPointParLot)
```

### 5.2 Spécificités par instrument (MT5)

| Symbole | Contract Size | Valeur point (1 lot) | Notes |
|---------|---------------|---------------------|-------|
| Forex (EURUSD, etc.) | 100 000 | ~10 USD/pip | 1 pip = 0.0001 |
| XAUUSD | 100 | ~1 USD/pip | 1 pip = 0.01 |
| XAGUSD | 5 000 | ~5 USD/0.01 | 0.01 = 1 cent |
| UKOIL.cash | 100 | ~0.088 USD/tick | tick = 0.01 |
| BTCUSD | 1 | ~1 USD/point | 1 point = 1.00 |
| ETHUSD | **10** | ~8.81 USD/point | **Contract size = 10** |

### 5.3 Calcul pour 50€ de risque

```
Exemple ETHUSD SELL:
  Entry    = 1618.38
  SL       = 1625.00 (distance = 6.62 pts)
  Valeur   = 8.81 USD/pt pour 1 lot
  Risk/lot = 6.62 × 8.81 = 58.32 USD
  EUR/USD  = 1.1348
  50€      = 56.74 USD
  Lots     = 56.74 / 58.32 = 0.97 lot
```

### 5.4 Budget risque recommandé

| Type de compte | Risque par trade |
|---------------|-----------------|
| Compte personnel < 5k€ | 1-2% |
| Compte personnel 5-20k€ | 0.5-1% |
| FTMO / Prop firm (100k$) | 0.25-0.5% |
| Stop quotidien max | 3-5% du capital |

---

## 6. Structure des Analyses

### 6.1 Rapport complet (synthèse)

Chaque rapport doit contenir :

1. **Timestamp** (UTC + Paris/CEST)
2. **Bilan trades du matin/jour précédent** — TP/SL touchés, P&L
3. **Trades actifs** (tableau) — Symbole, Dir, Entry, BID, SL, TP1-TP3, RR, Fib, Sweeps, P&L%
4. **Détail par trade** — Analyse CHoCH/MSS, bougies récentes, position vs fib
5. **Symboles sans trade** — Pourquoi pas de signal
6. **Classement par probabilité** — Top trades
7. **Roadmap visuelle** — Niveaux clés avec représentation ASCII

### 6.2 Analyse approfondie (zoom)

1. **Prix live** — BID, ASK, Spread, Low/High du jour
2. **Setup Asian** — AH, AL, Range, Sweeps, Breaches
3. **Bougies M5/M15/H1** — Structure micro
4. **Analyse CHoCH/MSS** — Par timeframe (M15, H1, H4, D1)
5. **Gaps Daily** — Identification et position du prix
6. **Niveaux Fibonacci** — Tous les niveaux bear/bull
7. **Position vs niveaux clés** — Distances
8. **Setup trade recommandé** — Entry, SL, TP, Lots, RR
9. **Scénarios probables** — Hausster / Baissier / Range

### 6.3 Roadmap ASCII standard

```
NIVEAU ──── Niveau clé
  │
  │   ██████  Zone de résistance/support  ██████
  │
NIVEAU ──── 📍 PRIX ACTUEL
         ─ ─ ─ ─ zone de gap ─ ─ ─ ─
NIVEAU ──── Fib level
```

---

## 7. Conventions d'écriture des analyses

### 7.1 Emojis

| Contexte | Emoji | Signification |
|----------|-------|---------------|
| Trade gagnant | ✅ | TP touché, trade gagné |
| Trade perdant | ❌ | SL touché, trade perdu |
| Trade ouvert | 🟡 | En cours, P&L latent |
| Prix monte | 🟢 | Bougie verte, hausse |
| Prix baisse | 🔴 | Bougie rouge, baisse |
| Tendance | 🔴🟢 | Direction du trend |
| Alerte | ⚠️ | Attention, niveau critique |
| Important | 📝 | Note, résumé |
| Nouveau | 🆕 | Nouveau signal/événement |
| Fusée | 🚀 | Accélération, breakout |
| Lampe | 💡 | Insight, idée |
| Cible | 🎯 | TP ou objectif |
| Rang | 🥇🥈🥉 | Classement |

### 7.2 Terminologie (FR → EN → ICT)

| Français | ICT / Anglais |
|----------|--------------|
| Sweep de liquidité acheteuse | BSL (Buy-side Liquidity) |
| Sweep de liquidité vendeuse | SSL (Sell-side Liquidity) |
| Changement de caractère | CHoCH (Change of Character) |
| Changement de structure | MSS (Market Structure Shift) |
| Plus haut asiatique | AH (Asian High) |
| Plus bas asiatique | AL (Asian Low) |
| Écart | Range |
| Extension Fibonacci | Fibonacci Extension / Fib expansion |
| Trou / écart de prix | Gap / Inefficiency (ICT) |
| Rejet violent en V | V-reversal / Liquidity grab |
| Fausse cassure | Fakeout / Liquidity sweep |
| Retour sur les stops | Reversal / Stop hunt |
| Zone d'expansion | Displacement (ICT) |
| Range qui se resserre | Coil / Consolidation |
| Objectif de cours | TP (Take Profit) |
| Stop de protection | SL (Stop Loss) |

### 7.3 Tableaux standard

```markdown
| Symbole | Dir | Entry | BID | SL | TP1 | TP2 | RR | Fib | DistSL% | DistTP% | Sweeps | P&L% |
|---------|-----|-------|-----|-----|-----|-----|-----|-----|----------|----------|--------|------|
| ETHUSD  | SELL| 1619  | 1619| 1682| 1612| 1600| 0.12| -2.0| 3.86%   | 0.46%   | AH+AL  |+0.00%|
```

---

## 8. Métriques et Calculs

### 8.1 Distance au SL/TP

```
DistSL% = |BID − SL| / Entry × 100
DistTP% = |BID − TP1| / Entry × 100
```

### 8.2 P&L latent

```
SELL : P&L% = (Entry − BID) / Entry × 100
BUY  : P&L% = (BID − Entry) / Entry × 100
```

### 8.3 Risk:Reward (RR)

```
RR = |Entry − TP| / |Entry − SL|

Pour SELL : RR = (Entry − TP1) / (SL − Entry)
Pour BUY  : RR = (TP1 − Entry) / (Entry − SL)
```

### 8.4 Ratio de tendance D1

```
Ratio = Close_moyen_5_derniers / Close_moyen_5_premiers

> 1.01 = HAUSSIER
< 0.99 = BAISSIER
sinon  = RANGÉE
```

### 8.5 Range 30 jours D1

```
Range = Plus_haut_30j − Plus_bas_30j
```

---

## 9. Sessions et Timing

### 9.1 Heures de publication économiques (events majeurs)

| Heure UTC | Heure Paris | Événement | Impact |
|:---------:|:-----------:|-----------|:------:|
| 08:00-09:00 | 10:00-11:00 | London Open, données UK/EU | Élevé |
| 13:00-14:00 | 15:00-16:00 | NY Open, salle des marchés US | Très élevé |
| 14:30 | 16:30 | Données US (NFP, CPI, etc.) | Majeur |
| 20:00-21:00 | 22:00-23:00 | Clôture NY, fixings | Moyen |
| 00:00-01:00 | 02:00-03:00 | Ouverture Tokyo | Faible-moyen |

### 9.2 Timing des sweeps post-Asian

```
Asian range fixé à 08:00 UTC.

London (08:00-13:00)  → Premier sweep probable (AH ou AL)
NY Open (13:00-14:00) → Deuxième sweep possible (l'autre côté → double sweep)
NY afternoon (14:00-21:00) → Direction établie, expansions fib
```

### 9.3 Conventions d'horodatage

- **Toutes les heures sont en UTC** sauf mention explicite
- Heure Paris = UTC + 2 (CEST, été) / UTC + 1 (CET, hiver)
- Le fuseau serveur MT5 peut différer (souvent UTC+2 ou UTC+3)
- Les bougies OHLC de `copy_rates_from_pos()` utilisent le timestamp serveur

---

## 10. Analyse des Bougies

### 10.1 Structure multi-timeframe

```
D1  → Trend global (30 jours)
H4  → Structure intermédiaire (8-12 bougies)
H1  → CHoCH, structure de la session
M15 → Breakouts, expansions
M5  → Micro-structure, entrées/sorties
```

### 10.2 Bougie d'expansion

Critères d'une bougie d'expansion (displacement) :

```
Corps > 2× le corps moyen des 5 bougies précédentes
OU
Range > 1.5× le range moyen des 5 bougies précédentes
```

### 10.3 Bougie de rejet / Liquidity grab

```
Mèche longue (wick > 2× corps)
Close dans la direction opposée à la mèche
La mèche dépasse un niveau clé (AH, AL, fib level, swing point)
```

---

## 11. Alertes et Seuils

### 11.1 Seuils de distance pour les trades actifs

| Distance au TP | Action |
|:--------------:|--------|
| < 0.1% du prix | TP imminent (quelques bougies M1) |
| 0.1-0.5% | TP probable dans l'heure |
| 0.5-2% | Mouvement nécessaire significatif |
| > 2% | TP lointain |

### 11.2 Seuils de sweep

```
min_distance_pct = 0.0 (config) → pas de filtre
Un sweep à < 0.5% du prix = niveau très proche, alerte immédiate
```

---

## 12. Rappels et Pièges

### 12.1 Erreurs fréquentes à éviter

1. **Confondre TP1 système (fib −1.618) et TP recommandé (fib courant)**
   - Le TP1 change quand le fib_state change
   - Toujours préciser « TP1 (fib −X.X) » dans les analyses

2. **Supposer un TP touché sans vérifier les bougies**
   - Le code vérifie `BID ≤ TP1` pour SELL
   - Les bougies M5/M15 donnent le prix exact (low/high)

3. **Entrer SELL trop tard après un move déjà fait**
   - À −2.618 ou plus, le move est statistiquement en fin de course
   - Privilégier les entrées à −1.618 ou +1.618

4. **Ignorer le contexte D1**
   - Un trade ICT sur H1 dans un trend D1 opposé = risque élevé
   - Prioriser les trades alignés avec le trend D1

5. **Oublier le spread dans l'exécution**
   - Pour un SELL : on entre à BID mais le prix doit traverser ASK pour le TP
   - La distance réelle au TP = TP1 − (ASK) pour SELL

### 12.2 Vérification des gaps

```python
# Code de vérification (à utiliser systématiquement)
for i in range(len(d1_bars) - 1):
    c = d1_bars[i].close
    o = d1_bars[i + 1].open
    gap = o - c
    if abs(gap) > 0.3:   # seuil variable selon l'instrument
        print(f"{date_i} → {date_i+1}: Gap {gap:+.3f}")
```

### 12.3 Filtre de spread global (intégré dans toutes les analyses)

Le spread est désormais calculé et affiché dans **toutes** les analyses :

```python
# Calcul dans sweep_detector.py (AsianRangeResult.spread_pct)
spread_pct = (tick.ask - tick.bid) / tick.bid * 100.0

# Seuil de filtrage dans cmd_setups (main.py)
MAX_SPREAD_PCT = 0.10  # les trades avec spread > 0.10% sont automatiquement exclus
```

**Affichage dans tous les outils :**

| Outil | Où voir le spread |
|-------|-------------------|
| `main.py setups --scan-all` | Colonne Spread dans le tableau (vert ≤0.10%, jaune ≤0.30%, rouge >0.30%) |
| `main.py asian --scan-all` | Colonne Spread dans le tableau |
| `generate_live_report.py` | Colonne Spread dans toutes les tables PDF (asian, setups, tracking) |
| `live_alerts.py` | Filtre MAX_SPREAD_PCT = 0.10 (trades écartés) |

**Exemples avec le seuil 0.10% :**

```
USDCHF  (spread 0.007%)  → 🟢 Accepté
EURJPY  (spread 0.008%)  → 🟢 Accepté
XLMUSD  (spread 0.054%)  → 🟢 Accepté
XPDUSD  (spread 0.490%)  → 🔴 Rejeté
HEATOIL (spread 1.08%)   → 🔴 Rejeté
XPTUSD  (spread 0.784%)  → 🔴 Rejeté
```

### 12.4 Backtest avec granularité M1

Le backtest (`backtest_report_trades.py`) utilise désormais **M1** comme timeframe primaire :

```
10 000 barres M1  (~7 jours) → vérifie le SL/TP minute par minute
Puis fallback M5 (3000 barres) → M15 (1000) → H1 (500)

Le SL est vérifié AVANT le TP dans chaque barre → worst-case conservateur
```

### 12.5 Tous les PDFs dans reports/

Tous les scripts écrivent et lisent les PDFs depuis le dossier `reports/` :

```
reports/inelida_report_YYYY-MM-DD_HHMM.pdf    # Rapports live
reports/inelida_report.pdf                     # Rapport template
reports/Comment_trader_et_gagner_avec_Inelida_Market_Scanner.pdf
reports/ict_analysis_*.pdf                     # Analyses ICT
```

### 12.6 Rappel : Les niveaux de gap incluent la bougie d'avant

```
Pour vérifier un gap :
- Close bougie J → Open bougie J+1 = écart
- MAIS le niveau de support/résistance du gap inclut
  le High (si gap haussier) ou Low (si gap baissier)
  de la bougie qui précède le gap.

Ex: Gap 27/02 UKOIL
Close 27/02 = 73.417 → Open 02/03 = 77.590
Mais le High 27/02 = 73.834 est aussi un niveau clé !
```

---

## 13. Commandes de Scan Rapides

```bash
# Backtest des trades depuis un PDF (granularité M1 minimum)
python backtest_report_trades.py                                    # auto-détection dernier PDF dans reports/
python backtest_report_trades.py --pdf reports/inelida_report_2026-06-25_1315.pdf

# Moniteur continu (signaux trades avec SL/TP, filtre spread intégré)
python live_alerts.py                         # tous les symboles, intervalle 30s
python live_alerts.py --interval 15           # toutes les 15s
python live_alerts.py --symbols EURUSD,GBPUSD # symboles spécifiques
python live_alerts.py --no-sound              # sans beep

# Détection sweeps fractale + daily/weekly
python live_monitor.py                        # sweeps BSL/SSL en temps réel

# Scan complet + rapport PDF
python generate_live_report.py

# Générer le guide utilisateur complet
python generate_user_guide_pdf.py

# Scan Asian range uniquement (tous symboles)
python -c "from src.sweep_detector import scan_market_watch_asian_ranges; from src.config import resolve_watchlist; r, s = scan_market_watch_asian_ranges(symbols_override=resolve_watchlist()); print(f'{len(r)} results'); [print(f'{x.symbol}: {x.trade_action} fib={x.fib_state}') for x in r if x.trade_action and x.trade_action != '-']"

# Vérifier un tick live
python -c "import MetaTrader5 as mt5; mt5.initialize(); t=mt5.symbol_info_tick('ETHUSD'); print(f'BID={t.bid} ASK={t.ask}') if t else print('N/A')"

# Bougies M15
python -c "import MetaTrader5 as mt5; from datetime import datetime,timezone; mt5.initialize(); r=mt5.copy_rates_from_pos('ETHUSD',mt5.TIMEFRAME_M15,0,5); [print(datetime.fromtimestamp(x[0],tz=timezone.utc).strftime('%H:%M'),x[1],x[2],x[3],x[4]) for x in r]"

# Vérifier les contract specs
python -c "import MetaTrader5 as mt5; mt5.initialize(); i=mt5.symbol_info('ETHUSD'); print(f'contract={i.trade_contract_size} tick_val={i.trade_tick_value} tick_size={i.trade_tick_size}') if i else print('N/A')"

# Vérifier le compte
python -c "import MetaTrader5 as mt5; mt5.initialize(); a=mt5.account_info(); print(f'Balance={a.balance} {a.currency} Levier=1:{a.leverage}') if a else print('N/A')"
```

---

## 14. Format de Rapport PDF

Le fichier `generate_live_report.py` génère un PDF en 6 sections :

| Section | Contenu |
|---------|---------|
| **Page de garde** | Horodatages, compte, résumé global |
| **1. Sweeps BSL/SSL** | Top 30 sweeps M15 triés par distance |
| **2. Session Asiatique** | Tous les AH/AL, trades actifs |
| **3. Niveaux Daily/Weekly** | PDH/PDL, PWH/PWL avec direction |
| **4. Setups & Trade Ideas** | Trades actifs + en attente |
| **5. Trade Tracking** | Suivi pour vérification ultérieure |
| **6. Méthodologie** | Règles de vérification |

### Nom du fichier
```
inelida_report_YYYY-MM-DD_HHMM.pdf
```
Exemple : `inelida_report_2026-06-24_1600.pdf`

---

## 15. Conventions Discord

### 15.1 Méthode de publication (IMPORTANT)

**NE JAMAIS utiliser de script Python inline avec `urllib.request` pour poster sur Discord.**
Les scripts inline échouent systématiquement avec HTTP 403 (Cloudflare/WAF bloque
les requêtes sans User-Agent cohérent).

**Toujours utiliser `discord_notifier.py` :**

```bash
# Écrire le JSON dans un fichier temporaire
python -c "
import json
embeds = [{...}]
with open('tmp_discord.json', 'w', encoding='utf-8') as f:
    json.dump({'embeds': embeds}, f, ensure_ascii=False)
"

# Poster via discord_notifier.py
python discord_notifier.py \
    --webhook \"https://discord.com/api/webhooks/...\" \
    --json tmp_discord.json

# Nettoyer
rm tmp_discord.json
```

**Pourquoi ça marche :** `discord_notifier.py` définit `User-Agent: InelidaMarketScanner/1.0`
et `Content-Type: application/json; charset=utf-8` que les scripts inline oublient.

### 15.2 Webhook URL

L'URL du webhook est stockée dans `.env` et injectée via `DISCORD_WEBHOOK_URL`.
Quand cette variable est définie, le flag `--webhook` est **optionnel** —
`discord_notifier.py` la lit automatiquement.

```bash
# Avec variable d'environnement (recommandé)
python discord_notifier.py --json tmp_discord.json

# Avec flag explicite (fallback)
python discord_notifier.py --webhook "<URL>" --json tmp_discord.json

# Message texte simple (pas besoin de fichier JSON !)
python discord_notifier.py --message "Alerte : EURCAD sweep détecté"
```

### 15.3 Structure d'un embed

```json
{
  "embeds": [{
    "title": "Titre (max 256 chars)",
    "description": "Description sous le titre",
    "color": 3447003,
    "fields": [
      {"name": "Nom du champ", "value": "Valeur", "inline": true},
      {"name": "Champ 2", "value": "Valeur 2", "inline": true},
      {"name": "Champ 3", "value": "Valeur 3", "inline": true}
    ],
    "footer": {"text": "Texte en bas"}
  }]
}
```

> ⚠️ Discord limite à **3 champs inline par ligne**. Au-delà, les champs
> passent à la ligne suivante. Pour un affichage propre, grouper par 3.

### 15.4 Couleurs Discord

| Usage | Hex | Décimal |
|-------|-----|---------|
| Vert (gain, haussier) | `0x2ECC71` | 3066993 |
| Rouge (perte, baissier) | `0xE74C3C` | 15158332 |
| Bleu (info, neutre) | `0x1E90FF` | 3447003 |
| Orange (alerte, attention) | `0xE67E22` | 15105570 |
| Violet (setup, analyse) | `0x9B59B6` | 10181046 |
| Jaune/Or (avertissement) | `0xF1C40F` | 15844367 |

### 15.5 Format des prix dans les embeds

```python
def _fmt(v):
    if v is None: return "?"
    if isinstance(v, (int, float)):
        if v >= 1000: return f"{v:.2f}"      # XAUUSD, BTCUSD, indices
        if v >= 10:   return f"{v:.4f}"      # USDJPY, EURJPY
        return f"{v:.5f}"                     # Forex 5-digit
    return str(v)
```

### 15.6 Test de connexion

```bash
python discord_notifier.py --webhook "<URL>" --test
```

---

## 16. Mise à jour

Ce document est amené à évoluer. Pour le mettre à jour :

1. Ajouter les nouveaux concepts ICT découverts
2. Corriger les erreurs constatées dans les analyses
3. Ajouter des exemples concrets de trades réels
4. Ajuster les formules si le code change
