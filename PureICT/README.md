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

### Export

```bash
# Export CSV des niveaux
python PureICT/scan_asian_session.py --export asian_levels.csv

# Export avec session précédente
python PureICT/scan_asian_session.py --previous --export asian_complet.csv
```

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
