# Guide Utilisateur — ICT FVG Live Monitor

> **Fonctionnalité** : Surveillance temps réel des setups ICT FVG  
> **Version** : 1.0 — Juin 2026  
> **Script** : `live_ict_monitor.py`

---

## Table des matières

1. [Présentation](#1-présentation)
2. [Installation rapide](#2-installation-rapide)
3. [Utilisation de base](#3-utilisation-de-base)
4. [Toutes les options](#4-toutes-les-options)
5. [Ce que vous voyez à l'écran](#5-ce-que-vous-voyez-à-lécran)
6. [Format des alertes](#6-format-des-alertes)
7. [Fichier de log JSON](#7-fichier-de-log-json)
8. [Comment fonctionne l'algorithme](#8-comment-fonctionne-lalgorithme)
9. [Paramètres avancés](#9-paramètres-avancés)
10. [FAQ](#10-faq)

---

## 1. Présentation

`live_ict_monitor.py` est un **surveillant temps réel** qui détecte les opportunités de trading basées sur la stratégie ICT FVG (Inner Circle Trader / Fair Value Gap).

**Ce qu'il fait :**
- Se connecte à MetaTrader 5 en lecture seule (ne trade **jamais**)
- Récupère les barres M3 en continu
- Détecte les setups ICT FVG complets : **DOL → Raid opposé → FVG → Retracement**
- Affiche une **alerte visuelle** avec le plan de trade complet (Entry, SL, TP1, TP2, RR)
- Sauvegarde chaque signal dans un **fichier JSON** pour analyse ultérieure

**Ce qu'il ne fait PAS :**
- ❌ N'envoie **aucun ordre** au broker
- ❌ Ne prend **aucune décision** à votre place
- ❌ Ne garantit pas que tous les signaux seront gagnants

---

## 2. Installation rapide

```bash
# 1. Ouvrir MetaTrader 5 et se connecter à un compte

# 2. Lancer le moniteur (XAUUSD par défaut)
cd C:\Users\TSTAC\RustProjects\InelidaMarketScan
python live_ict_monitor.py
```

**Prérequis :**
- MetaTrader 5 **ouvert et connecté** à un compte (demo ou réel)
- Python 3.8+ avec `MetaTrader5` installé (`pip install MetaTrader5`)

---

## 3. Utilisation de base

### Lancer sur XAUUSD (défaut)
```bash
python live_ict_monitor.py
```
Équivaut à :
```bash
python live_ict_monitor.py XAUUSD --interval 30
```

### Lancer sur un autre symbole
```bash
python live_ict_monitor.py EURUSD
python live_ict_monitor.py GER40.cash
python live_ict_monitor.py US30.cash
```

### Changer l'intervalle de scan
```bash
python live_ict_monitor.py XAUUSD --interval 15   # toutes les 15 secondes
python live_ict_monitor.py XAUUSD --interval 60   # toutes les minutes
```

### Arrêter le moniteur
```
Ctrl+C
```

---

## 4. Toutes les options

| Option | Défaut | Description |
|--------|:------:|-------------|
| `SYMBOLE` | `XAUUSD` | Symbole MT5 à surveiller (positionnel, premier argument) |
| `--interval` | `30` | Secondes entre chaque scan (minimum 5) |
| `--fvg-min` | `0.02` | Taille minimum du FVG en % du prix (ex: `0.05` pour 0.05%) |
| `--dol-min` | `0.15` | Distance minimum Entry→DOL en % du prix (ex: `0.20` pour 0.20%) |
| `--no-sound` | — | Désactive le beep sonore lors des alertes |

### Exemples avec options

```bash
# FVGs plus grands uniquement (filtre plus strict)
python live_ict_monitor.py XAUUSD --fvg-min 0.05

# DOL plus éloigné requis (évite les petits moves)
python live_ict_monitor.py XAUUSD --dol-min 0.30

# Scan rapide, pas de bruit
python live_ict_monitor.py EURUSD --interval 10 --no-sound

# Combinaison : FVGs moyens, DOL raisonnable, scan toutes les 20s
python live_ict_monitor.py XAUUSD --interval 20 --fvg-min 0.03 --dol-min 0.20
```

---

## 5. Ce que vous voyez à l'écran

### Au démarrage
```
======================================================================
  ICT FVG Monitor — Surveillance en direct
======================================================================

  Connexion MT5...
  Compte : 541320891 @ FTMO-Server4
  Symbole       : XAUUSD (digits=2)
  Intervalle    : 30s
  FVG min       : 0.02%
  DOL min       : 0.15%
  Log signaux   : new_analysis_02/live_ict_signals.jsonl

  Surveillance en cours... (Ctrl+C pour quitter)
```

### Ligne de statut (mise à jour à chaque scan)
```
  2026-06-30 09:15:30 UTC | LONDON | Paris 11:15 | Check #42 | XAUUSD | DOLs: 4 | Raids: 3 | FVGs: 2 | Signaux: 1 | Ctrl+C pour quitter
```

**Légende de la ligne de statut :**

| Champ | Signification |
|-------|---------------|
| `2026-06-30 09:15:30 UTC` | Heure du dernier scan |
| `LONDON` | Session ICT en cours (ASIAN / LONDON / NY OPEN / NY / ASIAN PRE) |
| `Paris 11:15` | Heure de Paris (UTC+2 en été) |
| `Check #42` | Numéro du scan depuis le démarrage |
| `DOLs: 4` | Nombre de paires DOL actives (PDH↑, PDL↓, AH↑, AL↓) |
| `Raids: 3` | Nombre de raids de liquidité détectés |
| `FVGs: 2` | Nombre de FVGs trouvés après les raids |
| `Signaux: 1` | Nombre de signaux uniques alertés aujourd'hui |

### Si le marché est fermé
```
  2026-06-28 21:00:00 UTC | Marché fermé — en attente...
```
Le moniteur attend automatiquement la réouverture (dimanche 22h UTC).

---

## 6. Format des alertes

Quand un setup ICT FVG complet est détecté, une alerte visuelle s'affiche :

```
======================================================================
  !!! NOUVEAU SETUP ICT FVG — BUY !!!  2026-06-30 09:18:45 UTC
  XAUUSD  |  PDH(2026-06-27)
======================================================================

  DOL (cible)    : 4380.00  (PDH(2026-06-27))
  Liquidité opposée: 4330.00  (raid SSL à 2026-06-30 08:45:00 UTC)
  FVG             : bullish, gap=0.045%  (top=4355.00 / bot=4350.00)

  [ENTRÉE] 4352.50
  Entry             : 4352.50
  SL                : 4345.20  (risque=7.30)
  TP1 (50%)         : 4366.25  (RR=1.88x)
  TP2 (DOL)         : 4377.80  (RR=3.47x, dist=DOL=0.63%)

  Session : LONDON  |  Paris : 11:18
  Log     : new_analysis_02/live_ict_signals.jsonl
======================================================================
```

### Explication des champs de l'alerte

| Champ | Signification |
|-------|---------------|
| **DOL (cible)** | Niveau que le prix cherche à atteindre (Draw On Liquidity) |
| **Liquidité opposée** | Niveau qui a été « raidé » (sweep) avant le retournement |
| **FVG** | Fair Value Gap — zone de déséquilibre où entrer |
| **Entry** | Point d'entrée recommandé (milieu du FVG) |
| **SL** | Stop Loss — au-delà de la bougie #1 du FVG + buffer |
| **TP1 (50%)** | Take Profit 1 — 50% de la position au milieu Entry→DOL |
| **TP2 (DOL)** | Take Profit 2 — 50% restant juste avant le DOL |
| **RR** | Ratio Risque/Récompense (ex: 1.88x = vous gagnez 1.88€ pour 1€ risqué) |

---

## 7. Fichier de log JSON

Chaque signal est automatiquement sauvegardé dans :
```
new_analysis_02/live_ict_signals.jsonl
```

Format (une ligne JSON par signal) :
```json
{
  "ts_utc": "2026-06-30T09:18:45.123456+00:00",
  "symbol": "XAUUSD",
  "direction": "bull",
  "action": "BUY",
  "dol_label": "PDH(2026-06-27)",
  "dol_level": 4380.00,
  "opposing_label": "PDL(2026-06-27)",
  "opposing_level": 4330.00,
  "raid_type": "ssl",
  "raid_time": 1750123456,
  "raid_time_str": "2026-06-30 08:45:00 UTC",
  "fvg_type": "bullish",
  "fvg_gap_pct": 0.045,
  "fvg_top": 4355.00,
  "fvg_bottom": 4350.00,
  "entry": 4352.50,
  "trade_plan": {
    "sl": 4345.20,
    "tp1": 4366.25,
    "tp2": 4377.80,
    "risk": 7.30,
    "rr1": 1.88,
    "rr2": 3.47,
    "dol_distance_pct": 0.63
  },
  "current_bid": 4352.45,
  "current_ask": 4352.55
}
```

### Analyser les logs

```bash
# Compter les signaux par jour
cat new_analysis_02/live_ict_signals.jsonl | python -c "
import sys, json
from collections import Counter
days = Counter()
for line in sys.stdin:
    s = json.loads(line)
    days[s['ts_utc'][:10]] += 1
for d, c in sorted(days.items()):
    print(f'{d}: {c} signaux')
"

# Extraire les signaux BUY uniquement
cat new_analysis_02/live_ict_signals.jsonl | python -c "
import sys, json
for line in sys.stdin:
    s = json.loads(line)
    if s['action'] == 'BUY':
        print(f\"{s['ts_utc'][:19]} | {s['symbol']} | Entry={s['entry']} | RR={s['trade_plan']['rr1']:.1f}x\")
"
```

---

## 8. Comment fonctionne l'algorithme

Le moniteur exécute les **5 étapes ICT FVG** en continu :

### Étape 1 — Identifier le DOL (Draw On Liquidity)
Pour chaque jour, 4 cibles sont calculées :

| Paire | Cible | Direction | Liquidité opposée |
|-------|-------|:---------:|-------------------|
| **PDH↑** | Previous Day High | BUY | PDL (plus bas de la veille) |
| **PDL↓** | Previous Day Low | SELL | PDH (plus haut de la veille) |
| **AH↑** | Asian High (00-08h UTC) | BUY | AL (plus bas asiatique) |
| **AL↓** | Asian Low (00-08h UTC) | SELL | AH (plus haut asiatique) |

### Étape 2 — Attendre un raid de liquidité opposée
Le script scanne les barres M3 à la recherche d'un **sweep** du niveau opposé :
- **SSL** (Sell-Side Liquidity) : la mèche passe sous le niveau et le close rejette au-dessus
- **BSL** (Buy-Side Liquidity) : la mèche passe au-dessus du niveau et le close rejette en dessous

### Étape 3 — Détecter le FVG et attendre le retracement
- Le **premier Fair Value Gap** après le raid est identifié
- Le script attend que le prix **retrace dans la zone** du FVG
- L'entrée se fait au **milieu** de la zone FVG

### Étape 4 — Calculer le Stop Loss
- SL placé au-delà de la **bougie #1** du FVG
- Buffer de 20% du gap pour le spread/slippage

### Étape 5 — Calculer les Take Profits
- **TP1** : 50% de la position au point médian Entry→DOL
- **TP2** : 50% restant juste avant le DOL (buffer = taille du FVG)

---

## 9. Paramètres avancés

### `--fvg-min` : Taille minimum du FVG

Filtre les FVGs trop petits (bruit). Plus la valeur est élevée, moins il y a de signaux mais de meilleure qualité.

| Valeur | Effet |
|:------:|-------|
| `0.02` (défaut) | Accepte presque tous les FVGs — beaucoup de signaux |
| `0.05` | Filtre 53% des FVGs — meilleur winrate backtesté (21% → ~25%) |
| `0.10` | Très strict — peu de signaux mais qualité maximale |

### `--dol-min` : Distance minimum Entry→DOL

Évite les trades où le DOL est trop proche de l'entrée (move insignifiant).

| Valeur | Effet |
|:------:|-------|
| `0.15` (défaut) | DOL à au moins 0.15% de l'entrée |
| `0.30` | DOL à au moins 0.30% — évite les micro-moves |
| `0.50` | Très strict — uniquement les moves significatifs |

### Sessions ICT et heures de trading

Le moniteur fonctionne **24h/24** mais les setups sont plus fiables pendant :

| Session | UTC | Paris (été) | Fiabilité |
|---------|:---:|:-----------:|:---------:|
| **London** | 08:00-13:00 | 10:00-15:00 | 🟢 Élevée |
| **NY Open** | 13:00-16:00 | 15:00-18:00 | 🟡 Moyenne |
| **Asian** | 00:00-08:00 | 02:00-10:00 | 🟠 Le range se forme |
| **NY** | 16:00-22:00 | 18:00-00:00 | 🟠 Dégradation |

> ⚠️ Le marché est fermé du **vendredi 22h UTC au dimanche 22h UTC**. Le moniteur détecte automatiquement la fermeture et attend la réouverture.

---

## 10. FAQ

### Q : Le script trade-t-il automatiquement ?
**R :** Non. `live_ict_monitor.py` est un **outil d'alerte uniquement**. Il ne place aucun ordre. La décision de trader vous appartient.

### Q : Sur quels symboles puis-je l'utiliser ?
**R :** N'importe quel symbole disponible dans votre MT5. Tests backtestés :
- **XAUUSD** : ✅ Très bon (214 trades, +143% sur 6 mois)
- **EURUSD** : ❌ Mauvais (164 trades, -23% sur 6 mois)
- **GER40.cash, US30.cash** : ⚠️ Non testé

### Q : Pourquoi je ne vois aucun signal ?
**R :** Vérifiez :
1. Le marché est-il ouvert ? (pas le week-end)
2. MT5 est-il connecté ? (vérifiez la ligne `Compte` au démarrage)
3. Le symbole est-il disponible ? (vérifiez `Symbole` au démarrage)
4. Essayez d'augmenter le nombre de signaux avec `--fvg-min 0.01`

### Q : Comment savoir si un signal est bon ?
**R :** Les backtests montrent que les meilleurs signaux ont :
- FVG gap > 0.05%
- Distance Entry→DOL < 2.0%
- DOL = Asian Low (28% WR) — éviter PDL (10% WR)
- Vendredi (35% WR) — éviter Mercredi (7% WR)

### Q : Puis-je lancer plusieurs instances ?
**R :** Oui, dans des terminaux différents :
```bash
# Terminal 1
python live_ict_monitor.py XAUUSD

# Terminal 2
python live_ict_monitor.py GER40.cash --interval 60
```

### Q : Où sont sauvegardés les signaux ?
**R :** Dans `new_analysis_02/live_ict_signals.jsonl` — un fichier JSON Lines (un objet JSON par ligne). Vous pouvez l'ouvrir avec n'importe quel éditeur de texte ou l'analyser avec Python.

---

## Scripts associés

| Script | Usage |
|--------|-------|
| `live_ict_monitor.py` | **Surveillance live mono-symbole** (ce guide) |
| `live_ict_monitor_global.py` | **Surveillance live MULTI-ACTIFS** (tous les symboles) |
| `backtest_ict_universal.py` | Backtest v1 sur n'importe quel symbole |
| `backtest_ict_fvg_v1.py` | Backtest v1 XAUUSD uniquement |
| `backtest_ict_fvg.py` | Backtest v2 avec filtres ICT complets |
| `download_historical.py` | Télécharger les données M3 depuis MT5 |
| `analyze_winners_losers.py` | Analyse comparative gagnants vs perdants |

---

---

## 11. Version multi-actifs — `live_ict_monitor_global.py`

Le projet inclut également une **version globalisée** du moniteur ICT FVG qui
scanne **tous les actifs disponibles** chez le broker simultanément.

### Utilisation

```bash
# Market Watch par défaut (50 symboles max)
python live_ict_monitor_global.py

# Tous les actifs du broker (illimité)
python live_ict_monitor_global.py --scan-all --max-symbols 0

# Liste explicite de symboles
python live_ict_monitor_global.py --symbols EURUSD XAUUSD BTCUSD

# Filtrer par type d'instrument
python live_ict_monitor_global.py --filter-type FOREX,METAL --interval 30

# Résumé périodique tous les 5 scans
python live_ict_monitor_global.py --summary-interval 5
```

### Options spécifiques au moniteur global

| Option | Défaut | Description |
|--------|:------:|-------------|
| `--symbols` | Market Watch | Liste de symboles explicites |
| `--scan-all` | — | Scanner tous les symboles disponibles chez le broker |
| `--max-symbols` | `50` | Nombre max de symboles (0 = illimité) |
| `--filter-type` | — | Filtrer par type: `FOREX,METAL,INDEX,CRYPTO,STOCK,COMMODITY` |
| `--summary-interval` | `5` | Tableau résumé tous les N scans (0 = désactivé) |

### Différences avec la version mono-symbole

| Caractéristique | `live_ict_monitor.py` | `live_ict_monitor_global.py` |
|-----------------|:---------------------:|:----------------------------:|
| Symboles | 1 seul | Tous (Market Watch / scan-all / explicite) |
| Intervalle par défaut | 30s | 60s (plus long car multi-actifs) |
| Tableau résumé | — | ✅ Périodique (tous les N scans) |
| Filtre par type | — | ✅ `--filter-type` |
| Throttle entre symboles | — | ✅ 50ms (évite de saturer MT5) |
| Log JSONL | `live_ict_signals.jsonl` | `live_ict_signals_global.jsonl` |
| Détection multi-setups | 1 par symbole | Plusieurs par symbole (PDH + AH simultanés) |

### Tableau résumé

Le moniteur global affiche périodiquement un **tableau résumé** de tous les
setups actifs, triés par RR décroissant :

```
══════════════════════════════════════════════════════════════════════════════
  📊 RÉSUMÉ — Scan #5  |  3 setup(s) actif(s)  |  2026-06-29 10:53:04 UTC
══════════════════════════════════════════════════════════════════════════════
  Symbole      Type  Action       Entry           SL          TP1    RR1          DOL    FVG%
  ────────────────────────────────────────────────────────────────────────────────
  XAUUSD      METAL    BUY     4352.50      4345.20     4366.25   1.88x     4380.00   0.63%
  EURUSD      FOREX   SELL     1.09200      1.09350     1.08950   1.67x     1.08800   0.41%
  BTCUSD     CRYPTO    BUY    60234.00    59800.00    61000.00   1.45x    62000.00   0.82%
  ────────────────────────────────────────────────────────────────────────────────
  Tri par RR décroissant  |  Log: new_analysis_02/live_ict_signals_global.jsonl
```

---

*Guide généré le 29 juin 2026 — Inelida Market Scanner*
