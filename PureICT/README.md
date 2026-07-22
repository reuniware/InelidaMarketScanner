# PureICT - Asian Session Scanner

## Commandes utiles

### Scan simple

```bash
# Tous les symboles (défaut PARIS 00:00-08:00)
python PureICT/scan_asian_session.py

# Un symbole spécifique
python PureICT/scan_asian_session.py --symbol EURUSD

# Timeframe 1 minute (précision maximale)
python PureICT/scan_asian_session.py --symbol GBPJPY --timeframe M1
```

### Forcer l'activation des symboles (FTMO)

```bash
# Activer tous les symboles dans Market Watch AVANT le scan
python PureICT/scan_asian_session.py --force-select --verbose

# Avec filtre + live (recommandé pour tester)
python PureICT/scan_asian_session.py --force-select --verbose --symbol EURUSD --live
```

### État des lots max (calcul marge)

Les colonnes `LotsMax` et `Marge/Lot` apparaissent automatiquement
**(aucun flag nécessaire)** dès que le scanner peut lire les infos du compte MT5 :

```bash
# Scan simple — si marge dispo, les colonnes apparaissent
python PureICT/scan_asian_session.py --symbol EURUSD

# Mode live — colonne Lots visible à droite du tableau
python PureICT/scan_asian_session.py --live --symbol EURUSD

# Avec FVG + lots max combinés
python PureICT/scan_asian_session.py --fvg --live --symbol EURUSD
```

**Exemple de sortie en mode live :**
```
  Symbole      Prix         AH         AL   Dist AH   Dist AL  vs Mid   Sweeps    Lots   Pos
  EURUSD    1.12345    1.12500    1.12000     -0.14%    +0.31%  >0.08%       AL    3.25   IN
```

Le calcul est le même que le script MQL5 `MaxMargin_Limit` :
- Marge libre du compte ÷ marge requise pour 1 lot
- Arrondi au step du symbole (0.01 par défaut)
- Plafonné au volume max autorisé par le broker

### Détection FVG (Fair Value Gap) près AH/AL

```bash
# Détecter les FVGs quand le prix rejette l'AH ou l'AL
python PureICT/scan_asian_session.py --fvg --symbol EURUSD

# En mode live avec FVG
python PureICT/scan_asian_session.py --fvg --live --symbol EURUSD

# Seuil de FVG personnalisé (défaut: 0.02%)
python PureICT/scan_asian_session.py --fvg --fvg-min 0.05 --symbol EURUSD

# FVG + Force Select + Live (scan complet)
python PureICT/scan_asian_session.py --force-select --fvg --live --symbol EURUSD

# Tout en un : activation forcee + FVG + live + verbose (scan complet tous symboles)
python PureICT/scan_asian_session.py --force-select --verbose --fvg --live
```

Le `--fvg` scanne les timeframes M15 → M5 → M3 → M1 pour trouver des FVGs quand :
- Le prix est passé au-dessus de l'AH puis revenu **en dessous** → FVG **baissier** près AH (`B-M5`)
- Le prix est passé en dessous de l'AL puis revenu **au-dessus** → FVG **haussier** près AL (`b-M15`)

Dans le tableau live, les FVGs sont affichés en colonnes `FVG AH` / `FVG AL` :
- `B-M5` = Bearish FVG sur M5
- `b-M1` = Bullish FVG sur M1

### Mode live

```bash
# Rafraîchissement toutes les 5 secondes
python PureICT/scan_asian_session.py --live -i 5

# Tous les symboles EUR en live
python PureICT/scan_asian_session.py --live --symbol EUR*

# Avec fuseau BROKER
python PureICT/scan_asian_session.py --live --timezone BROKER --start-hour 1 --end-hour 9
```

### Détection des exclus

```bash
# Affiche le détail des symboles exclus et pourquoi
python PureICT/scan_asian_session.py --verbose

# Résumé compact automatique (même sans --verbose)
python PureICT/scan_asian_session.py
```

### Filtres

```bash
# Par motif (wildcards)
python PureICT/scan_asian_session.py --symbol EUR* --symbol *JPY --symbol *USD*

# Market Watch uniquement (plus rapide)
python PureICT/scan_asian_session.py --market-watch

# Limiter le nombre de symboles
python PureICT/scan_asian_session.py --max-symbols 30
```

### Fuseaux horaires

```bash
# Défaut : Paris 00:00-08:00 (équivaut à UTC 22:00-06:00)
python PureICT/scan_asian_session.py

# Broker FTMO (UTC+3 été) : 01:00-09:00
python PureICT/scan_asian_session.py --timezone BROKER --start-hour 1 --end-hour 9

# UTC pur : 22:00-06:00
python PureICT/scan_asian_session.py --timezone UTC --start-hour 22 --end-hour 6
```

### À propos des colonnes LotsMax / Marge/Lot

Depuis la mise à jour du **22 juillet 2026**, le scanner PureICT affiche automatiquement
deux colonnes supplémentaires dans le tableau principal et le mode live :

| Colonne | Description |
|---|---|
| `LotsMax` | Nombre de lots maximum négociable pour ce symbole, calculé depuis **la marge libre de votre compte** MT5 et la marge requise pour 1 lot. |
| `Marge/Lot` | Marge requise par le broker pour ouvrir **1 lot standard** sur ce symbole (dans la devise du compte). |

**Comment le calcul fonctionne (équivalent du script MQL5 `MaxMargin_Limit`) :**
1. Récupère la **marge libre** du compte (`ACCOUNT_MARGIN_FREE`)
2. Calcule la **marge pour 1 lot** via `mt5.order_calc_margin()`
3. `LotsMax = marge libre / marge pour 1 lot`
4. Arrondi **vers le bas** au `volume_step` du symbole (ex: 0.01 lot)
5. Plafonné au `volume_max` du symbole (limite broker)

> ⚠️ Les colonnes apparaissent **uniquement** si le scanner parvient à récupérer
> les informations de marge (compte MT5 connecté et marge libre > 0).
> Sinon, le tableau reste dans sa forme classique sans ces colonnes.

### Export

```bash
# Export CSV des niveaux (inclut les colonnes max_lots, account_currency, margin_per_lot)
python PureICT/scan_asian_session.py --export asian_levels.csv

# Export avec session précédente
python PureICT/scan_asian_session.py --previous --export asian_complet.csv
```

Le CSV exporté contient **tous les champs** de la dataclass `AsianLevels`, y compris
`max_lots`, `account_currency` et `margin_per_lot` pour une analyse offline.

### Forcer une date

```bash
# Session d'hier (même après 08:00)
python PureICT/scan_asian_session.py --date 2026-07-21

# Session d'aujourd'hui (même avant 08:00)
python PureICT/scan_asian_session.py --date 2026-07-22
```

---

## Comportement MQL5

- **Avant 08:00 Paris** → affiche la session **précédente** (hier, figée)
- **Après 08:00 Paris** → affiche la session **du jour** (terminée à 08:00)
- Pour forcer une date → utiliser `--date YYYY-MM-DD`

## Raisons d'exclusion (--verbose)

| Raison | Cause probable |
|---|---|
| `select_symbol a echoue` | Symbole hors Market Watch, FTMO bloque |
| `Pas de donnees` | Symbole connu mais pas de données OHLC |
| `Aucune barre dans la fenetre session` | Symbole ne trade pas durant l'Asian (indices, stocks) |

## Dépendances

```bash
pip install MetaTrader5
```

MT5 doit être lancé et connecté à un compte.
