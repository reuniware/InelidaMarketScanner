# InelidaMarketScanner

**Trouver les bons trades ICT (Asian session, sweeps, Fibonacci) et les exécuter automatiquement sur MetaTrader 5.**

InelidaMarketScanner est un outil en ligne de commande pour traders MT5 qui analyse la **session asiatique**, détecte les **liquidity sweeps** (BSL/SSL), calcule les **extensions Fibonacci** (-4.0 à +4.0), et propose un **plan de trade complet** (Entry / SL / TP1-3 / Risk-Reward) — avec option d'**envoi automatique au broker**.

Tout se passe depuis votre terminal, sans interface graphique, sans cloud, sans Docker. Juste MetaTrader 5 + Python.

> ⚠️ Statut : projet en cours de conception. Le code est fonctionnel mais l'API peut évoluer.

---

## 🎯 À qui s'adresse cet outil ?

- ✅ **Trader ICT/SMC** : vous tradez le concept « Asian session → London sweep → NY continuation » et vous voulez scanner automatiquement tous les symboles qui correspondent.
- ✅ **Trader prop firm** (FTMO, MFF, FundedNext, etc.) : vous voulez voir d'un coup d'œil quels actifs ont une opportunité claire, et optionnellement exécuter en micro-lots (0.01) pour tester.
- ✅ **Dev Python curieux** : le code est lisible, modulaire ; chaque composant (MT5 connector, ICT detector, broker executor) est isolable et testable.
- ❌ **Pas pour vous si** : vous cherchez un bot « plug & play rentable ». Cet outil *affiche* les opportunités et *facilite* l'exécution — la décision finale reste la vôtre.

---

## ✨ Ce que l'outil fait pour vous

- 📊 **Scan de marché temps réel** — voyez en un coup d'œil le bid/ask, le spread et la variation de chaque symbole de votre watchlist.
- 🔍 **Détection automatique des sweeps ICT** — l'outil identifie les swings BSL/SSL qui ont été *raids* (sweep) en M15, M30, H1 ou H4.
- 🌏 **Analyse de la session asiatique** — pour chaque symbole, calcule le High/Low de la session (UTC 00:00–08:00) et détecte si le prix est au-dessus/en-dessous, avec extensions Fibonacci ±1.618 / ±2.618 / ±3.618 / ±4.0.
- 📈 **Niveaux Daily & Weekly** — détecte les sweeps des PDH/PDL (Previous Day) et PWH/PWL (Previous Week) avec direction target.
- 💡 **Idée de trade complète** — affiche le trade recommandé (BUY / SELL), le point d'entrée, le stop-loss, et trois take-profits, avec le ratio risque:récompense.
- 🚨 **Détection de « breach »** — en plus des sweeps classiques (avec rejet), détecte aussi quand la mèche traverse un niveau sans rejet (breach), dans les deux sens.
- 🎮 **Exécution automatique MT5** — envoie réellement l'ordre au broker depuis le CLI, avec garde-fous (anti-double-ordre, DRY-RUN de previsualisation, magic number d'identification, retcode mapping lisible).
- 🎨 **Dashboard Streamlit** — interface web pour visualiser les résultats, filtrer les données, et lancer les scans en direct.
- 🗄️ **Base de données SQLite intégrée** — les sessions asiatiques (AH/AL + timestamps), niveaux daily/weekly, et les sweeps (BSL/SSL) sont automatiquement enregistrés dans une base SQLite pour les statistiques futures.
- 📈 **Scan multi-actifs** — scanne tous les symboles visibles dans MarketWatch (`--all`) ou **tous les symboles disponibles chez le broker** (`--scan-all`) pour une couverture maximale.
- ⚙️ **Aucune dépendance exotique** — juste Python + MetaTrader5 + Streamlit. SQLite est intégré à Python. Pas de cloud, pas de Docker.

---

## 📁 Structure

```
InelidaMarketScanner/
├── main.py                  # Entrée CLI (argparse)
├── app.py                   # Dashboard Streamlit
├── live_monitor.py          # Détecteur live de sweeps (Asian + Fractal + Daily/Weekly) - NO TRADE
├── live_ict_monitor.py      # Détecteur live ICT FVG (1 symbole) - alertes + log JSONL
├── live_ict_monitor_global.py  # Détecteur live ICT FVG MULTI-ACTIFS - alertes + log JSONL
├── start_scan.bat           # Lanceur Windows pour le mode watch
├── start_dashboard.bat      # Lanceur Windows pour le dashboard Streamlit
├── requirements.txt
├── README.md
├── LICENSE
├── .gitignore
└── src/
    ├── __init__.py
    ├── config.py            # Watchlist & dataclasses de config
    ├── mt5_connector.py     # Singleton MT5 (init / reconnect / shutdown)
    ├── market_scanner.py    # Scan tick + deltas + CSV
    ├── display.py           # Rendu console ANSI
    ├── sweep_detector.py    # Détection sweeps BSL/SSL + range asiatique + Fibonacci + niveaux daily/weekly + breach
    ├── trade_executor.py    # Exécution d'ordres MT5 (DRY-RUN / LIVE)
    └── database.py          # Base SQLite (sessions asiatiques + sweeps + levels)
```

---

## 🚀 Installation

```bash
cd InelidaMarketScanner
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt
```

> ⚠️ **MetaTrader5** est un binding Python **Windows-only** distribué par MetaQuotes. InelidaMarketScanner ne fonctionne donc que sur Windows avec un terminal MT5 lancé et connecté à un compte.

---

## ⚙️ Configuration

Trois façons de configurer la watchlist :

1. **Variable d'environnement** (séparée par virgules) :
   ```bash
   set INELIDA_WATCHLIST=XAUUSD,EURUSD,BTCUSD,NAS100
   ```
2. **Drapeau CLI** :
   ```bash
   python main.py watch --symbols XAUUSD EURUSD BTCUSD NAS100
   ```
3. **Édition directe de `DEFAULT_WATCHLIST`** dans `src/config.py`.

Le chemin du terminal MT5 peut être forcé dans `src/config.py` (champ `MT5Config.terminal_path`) :

```python
MT5 = MT5Config(
    terminal_path=r"C:\Program Files\FTMO Global Markets MT5 Terminal\terminal64.exe",
    login=None, password=None, server=None,
    ...
)
```

> 💡 Si `login=None`, MT5 utilisera le compte déjà ouvert dans le terminal (le plus simple pour observer plusieurs comptes).

---

## 🧰 Commandes CLI

| Commande    | Description                                              |
| ----------- | -------------------------------------------------------- |
| `snapshot`  | Une seule capture, puis sortie (tableau ou JSON).        |
| `watch`     | Boucle continue : scan + affichage temps réel (Ctrl+C).   |
| `watchlist` | Affiche simplement la watchlist configurée.             |
| `account`   | Infos du compte MT5 (balance, leverage, etc.).           |
| `terminal`  | Infos du terminal MT5 (broker, build, trade_allowed...).|
| `sweeps`    | Détection des sweeps BSL/SSL (ICT Williams fractals).    |
| `asian`     | Analyse du range asiatique + sweeps post-Asian + Fibonacci.|
| `levels`    | Scanne les niveaux PDH/PDL (daily) et PWH/PWL (weekly) + sweeps.|
| `setups`    | Filtre les setups directionnels (sweep + mouvement vers l'autre liquidité).|
| `trade`     | Liste ou exécute les Trade Ideas sur MT5.                |
| `db`        | Interagit avec la base de données SQLite (stats, list, path).|
| `live`      | Détecteur live de sweeps ICT (écran + log, pas de trade). |
| `live_ict`   | Détecteur live ICT FVG mono-symbole (alertes + log JSONL). |
| `live_ict_global` | **NOUVEAU** — Détecteur live ICT FVG multi-actifs (tous les symboles du broker). |

Exemples :

```bash
# Une capture ponctuelle au format tableau
python main.py snapshot

# Une capture au format JSON
python main.py snapshot --json

# Watch temps réel sur une watchlist custom
python main.py watch --symbols XAUUSD EURUSD --verbose

# Voir la watchlist actuellement configurée
python main.py watchlist

# Infos du compte / terminal
python main.py account
python main.py terminal
```

Sur Windows, double-clique simplement sur `start_scan.bat` (équivalent à `python main.py watch`).

---

## 📊 Colonne par colonne du tableau temps réel

| Colonne        | Description                                          |
| -------------- | ---------------------------------------------------- |
| `Symbole`      | Nom du symbole MT5                                   |
| `Bid`          | Prix de vente                                        |
| `Ask`          | Prix d'achat                                         |
| `Last`         | Dernier prix traité (gris si pas dispo)              |
| `Spread(pts)`  | Spread en points (vert / jaune / rouge selon valeur) |
| `Δ Bid`        | Variation absolue et % depuis le tick précédent     |
| `Dernière MAJ` | Horodatage UTC du tick                              |

---

## 🗃️ Journalisation CSV

Active la sortie CSV en éditant `src/config.py` :

```python
OUT = OutputConfig(
    csv_log=True,
    csv_path="./inelida_ticks.csv",
    pretty=True,
    flush_each_tick=True,
)
```

Chaque ligne écrite : `time, symbol, bid, ask, last, spread, spread_points, deltas…`

---

## 🎯 Liquidity Sweeps (BSL / SSL)

Sous-commande `sweeps` qui scanne **tous les symboles visibles dans la Market Watch MT5** (ou une liste passée via `--symbols`) et identifie les swings ICT qui ont été *raids* (sweeps).

- **Swing points** : highs / lows fractals Williams (N=2 par défaut).
- **BSL (Buy-Side Liquidity)** : swing haut dont une bougie récente a fait `high > level` **et** `close < level`.
- **SSL (Sell-Side Liquidity)** : swing bas dont une bougie récente a fait `low < level` **et** `close > level`.
- Fenêtre d'observation = `--sensitivity` dernières bougies (défaut 5).
- Profondeur d'historique = `--lookback` bougies (défaut 50).

### Usage rapide

```bash
# Scan complet sur M15 (50 symboles, 50 bars d'historique, 5 bars de sensibilité)
python main.py sweeps

# Timeframe H1 avec lookback profond
python main.py sweeps --timeframe H1 --lookback 100 --sensitivity 8

# Scanner toute la market watch (override du --limit)
python main.py sweeps --all -v

# Sortie JSON pour intégration externe
python main.py sweeps --json > sweeps.json

# Limiter à 5 symboles explicites (utile pour debug FTMO)
python main.py sweeps --symbols XAUUSD EURUSD GBPUSD USDJPY BTCUSD
```

### Colonnes du tableau

| Colonne    | Description                                              |
| ---------- | -------------------------------------------------------- |
| `Side`     | `BSL` ou `SSL` (sens ICT du sweep)                       |
| `Level`    | Prix du swing point qui a été swept                      |
| `Now`      | Prix actuel du symbole                                   |
| `Distance` | % d'écart entre le prix actuel et le niveau swept        |
| `Dir`      | `reversal_up` (SSL) ou `reversal_down` (BSL)             |
| `Swept at` | Horodatage UTC de la bougie qui a swept                  |

### Flags de `sweeps`

| Option                 | Défaut | Effet                                              |
| ---------------------- | ------ | --------------------------------------------------- |
| `--timeframe`          | `M15`  | M1 / M5 / M15 / M30 / H1 / H4 / D1                 |
| `--fractal`            | `2`    | Williams fractal N                                  |
| `--lookback`           | `50`   | Bougies arrière pour les swings                     |
| `--sensitivity`        | `5`    | Dernières bougies testées pour les sweeps           |
| `--limit`              | `50`   | Cap symboles (depuis Market Watch)                  |
| `--all`                | -      | Override du cap, scanne tous les symboles visibles  |
| `--scan-all`           | -      | Scan TOUS les symboles disponibles chez le broker   |
| `--sort-by-distance`   | ✅     | Trie par distance croissante au prix actuel        |
| `--json`               | -      | Sortie JSON sinon tableau ASCII                     |
| `-v, --verbose`        | -      | Logging DEBUG                                       |

⚠️ Les sweeps ICT sont des composants **codables** de la méthodologie, mais leur interprétation reste *discrétionnaire* : un trader chevronné filtrera visuellement les sweeps « propres » vs « faibles ». Ce scanner sort les données brutes — c'est à toi de juger la qualité de chaque signal.

---

## 📈 Niveaux Daily & Weekly (PDH/PDL / PWH/PWL)

Sous-commande `levels` qui scanne les **niveaux quotidiens et hebdomadaires** pour détecter les sweeps et la direction vers l'autre côté.

- **PDH/PDL** (Previous Day High/Low) : charge les D1, prend la veille comme niveau, scanne les bougies H1 du jour courant.
- **PWH/PWL** (Previous Week High/Low) : charge les W1, prend la semaine dernière comme niveau, scanne les bougies D1 de la semaine courante.
- Détecte les **sweeps** (mèche traverse + close rejette) et les **breaches** (mèche traverse seulement).
- Direction target : si le haut a été swept, le prix se dirige vers le bas (→ AL), et inversement.

### Usage

```bash
# Daily + Weekly (défaut)
python main.py levels

# Uniquement daily
python main.py levels --type daily

# Uniquement weekly
python main.py levels --type weekly

# Tous les symboles disponibles
python main.py levels --scan-all
```

### Colonnes du tableau

| Colonne      | Signification                                                |
|------------- |------------------------------------------------------------- |
| `Symbole`    | Nom MT5                                                      |
| `Type`       | `Daily` ou `Weekly`                                           |
| `Sweep`      | `H` (high swept), `L` (low swept), `H+L` (les deux), `H'`/`L'` (breach sans rejet) |
| `Direction`  | `→ AH` / `→ AL` / `↔ Both` / `·` / `−`                       |
| `Niv.Haut`   | Prix du niveau haut (PDH ou PWH)                              |
| `Niv.Bas`    | Prix du niveau bas (PDL ou PWL)                               |
| `Now`        | Prix actuel                                                   |

---

## 🚨 Détection de Breach (sweep sans rejet)

En complément du sweep classique ICT (mèche traverse + close rejette), le détecteur identifie désormais les **breaches** : quand la **mèche traverse** un niveau, même si le close **ne rejette pas** de l'autre côté.

### Utilité

Cela permet de détecter des cas comme :
- Prix sweepe l'Asian High (rejet confirmé ✅), puis descend, traverse l'Asian Low mais **reste en dessous** (continuation baissière)
- Le breach est marqué (`AH'` ou `AL'` dans l'affichage) même si le close reste du même côté

### Où le voir

| Interface    | Indicateur                                           |
|------------- |----------------------------------------------------- |
| CLI `asian`  | `touch` (gris) au lieu de `swept` (rouge/vert)       |
| CLI `levels` | `H'` / `L'` (apostrophe) pour breach simple          |
| CLI `setups` | `AH'` / `AL'` combinés si les deux breachés          |
| Dashboard    | Colonnes `AH Touch` / `AL Touch` dans les tableaux   |

> ⚠️ La `direction_target` (→ AH / → AL) reste basée **uniquement** sur les sweeps avec rejet (logique ICT). Les breaches sont informatifs mais ne génèrent pas de signal directionnel.

---

## 🌏 Asian Session Range

Sous-commande `asian` qui calcule le **range de la session asiatique** (UTC 00:00–08:00 par défaut) pour chaque symbole visible en Market Watch, puis **détecte si le Asian High ou le Asian Low a été swept** dans les bougies post-Asian.

### Algorithme ICT

1. Récupère ~14 jours de barres `H1` (par défaut) pour le symbole.
2. Filtre les bougies dont la date UTC est aujourd'hui ET l'heure UTC ∈ [00:00, 08:00).
3. Calcule :
   - `Asian High = max(high)` sur ces bougies.
   - `Asian Low  = min(low)`  sur ces bougies.
4. Scanne les bougies post-Asian (jusqu'à 240 barres ≈ 10 jours H1) :
   - **Asian High swept** = `bar.high > Asian High` ET `bar.close < Asian High` (raid BSL).
   - **Asian Low swept**  = `bar.low  < Asian Low`  ET `bar.close > Asian Low`  (raid SSL).
5. Si sweep trouvé, identifie la **session ICT** qui en est responsable via l'heure UTC de la bougie (London / NY / NY Open / Asian pre).

### Usage

```bash
# Scan complet par défaut (50 symboles visibles Market Watch, H1, aujourd'hui UTC)
python main.py asian

# Scan TOUS les symboles disponibles chez le broker (visible + non-visibles)
python main.py asian --scan-all

# Timeframe M15 (plus granulaire, plus faux positifs)
python main.py asian --timeframe M15

# Date specifique (utile pour backtest retroactif)
python main.py asian --session-date 2026-06-15

# Liste explicite
python main.py asian --symbols XAUUSD EURUSD GBPUSD USDJPY BTCUSD

# Sortie JSON
python main.py asian --json > asians.json
```

### Colonnes du tableau

| Colonne      | Signification                                                              |
| ------------ | -------------------------------------------------------------------------- |
| `Symbole`    | Nom MT5                                                                    |
| `AsianHigh`  | Plus haut sur les bougies H1 entre 00:00 et 08:00 UTC (aujourd'hui)        |
| `AsianLow`   | Plus bas sur les bougies H1 entre 00:00 et 08:00 UTC (aujourd'hui)         |
| `Now`        | `bid` courant                                                              |
| `AH Swept`   | `swept` si Asian High a été raid, `---` sinon                              |
| `AL Swept`   | `swept` si Asian Low a été raid, `---` sinon                               |
| `Session`    | Session ICT qui a déclenché le sweep : London / NY / NY Open                |
| `Target`     | Direction « vers l'autre liquidité » (voir légende ci-dessous)             |
| `Fib`        | Extension Fibonacci ±1.618 par rapport à la range asiatique (voir légende) |
| `FibSwept`   | Plus profond niveau Fibonacci sweepé en post-Asian (voir légende)          |
| `Bars`       | Nombre de bougies post-Asian examinées                                      |
| `Trade`      | Idée de trade ICT (BUY / SELL / —, voir légende)                           |
| `Plan`       | Prix SL → prix TP1 (le scalp chiffré ; TP2/TP3 dans `--json`)             |
| `RR`         | Ratio risque:récompense au TP1 (ex. `1.6×`)                                |

### Légende de la colonne `Target`

La colonne `Target` répond à la question « *le prix est-il en train de se diriger vers l'autre extrémité de la range asiatique ?* » selon la logique ICT :

| Valeur   | Couleur | Signification                                                                                |
| -------- | ------- | -------------------------------------------------------------------------------------------- |
| `→ AH`   | vert    | Asian Low swept + prix au-dessus du midpoint → reversal haussier confirmé, on attend un run vers l'Asian High |
| `→ AL`   | rouge   | Asian High swept + prix en-dessous du midpoint → reversal baissier confirmé, on attend un run vers l'Asian Low  |
| `↔ Both` | jaune   | Les deux extrémités ont été swept → range cassée, signal mixte / continuation probable     |
| `·`      | gris    | Sweep enregistré mais le prix n'a pas encore traversé le midpoint → confirmation en attente ; ou la cible a déjà été atteinte (prix déjà sous l'AL / au-dessus du AH) |
| `−`      | gris    | Aucun sweep → pas d'info directionnelle                                                     |

### Légende de la colonne `Fib`

Détecte si le prix a « dépassé l'autre liquidité » et affiche la **prochaine extension Fibonacci non atteinte** dans la direction du mouvement. Les niveaux ICT trackés sont calculés sur la range asiatique :

```
fib_+N   = asian_high  + N × (asian_high − asian_low)   # N in {1.618, 2.0, 2.618, 3.0, 3.618, 4.0}
fib_-N   = asian_low   − N × (asian_high − asian_low)   # N idem (niveaux négatifs)
```

L'algo itère sur les niveaux dans l'ordre et affiche le **premier niveau non franchi**. Exemple : AL swept, prix > AH, prix = 1.2 × range au-dessus de AH → affiche `→ +1.618` ; si prix = 1.7 × range → affiche `→ +2.0` (1.618 est dépassé, on regarde le suivant).

| Valeur     | Couleur    | Signification                                                                          |
| ---------- | ---------- | -------------------------------------------------------------------------------------- |
| `→ +N`     | vert       | Expansion bullish en cours (AL swept + prix > AH), prochaine cible = +N               |
| `+N ✓`     | vert gras  | Tous les niveaux +N ont été franchis (on a dépassé la grille standard)                 |
| `→ -N`     | rouge      | Expansion bearish en cours (AH swept + prix < AL), prochaine cible = -N                |
| `-N ✓`     | rouge gras | Tous les niveaux -N ont été franchis                                                    |
| *(vide)*   | -          | Aucun prix n'a encore « dépassé l'autre liquidité » — la colonne reste vide           |

N ∈ {1.618, 2.0, 2.618, 3.0, 3.618, 4.0} par défaut. Pour un GBPUSD qui a déjà cassé -1.618 et -2.618 et continue à baisser, la colonne affichera `→ -3.0` puis `→ -3.618` au fur et à mesure que chaque cible est franchie.

### Légende de la colonne `FibSwept`

Détecte quand un niveau d'extension Fibonacci devient lui-même une « pocket de liquidité » et se fait sweep (BSL sur niveau bull, SSL sur niveau bear) en post-Asian. Pour chaque côté on accumule la liste des niveaux sweepés puis on reporte le **plus profond** (le plus éloigné de la range).

Détection appliquée à chaque niveau `±N` de `_FIB_LEVELS_BULL` / `_FIB_LEVELS_BEAR` :

```
bull_fib_swept (BSL) : bar.high > fib_+N ET bar.close < fib_+N
bear_fib_swept (SSL) : bar.low  < fib_-N ET bar.close > fib_-N
```

| Valeur          | Couleur        | Signification                                                              |
| --------------- | -------------- | -------------------------------------------------------------------------- |
| `↑ +1.618`      | vert           | Niveau bull Fibonacci le plus profond sweepé (= +1.618 en général)        |
| `↑ +2.618`      | vert           | +2.0 et +2.618 ont aussi été sweepés (deepest = +2.618)                   |
| `↓ -1.618`      | rouge          | Niveau bear Fibonacci le plus profond sweepé                                |
| `↓ -3.618`      | rouge          | Plusieurs niveaux bear sweepés (1.618, 2.0, 2.618, 3.0, 3.618)             |
| `↑ +N ↓ -M`     | vert + rouge   | Sweeps détectés sur les deux côtés (range + extensions cassées)            |
| `—`             | gris           | Pas de niveau Fibonacci sweepé en post-Asian                               |

### Légende de la colonne `Trade` / `Plan` / `RR`

Quand le détecteur asiatique identifie un **biais directionnel clair** (un sweep asiatique + cassure de l'autre extrémité confirmant la cible Fibonacci), il génère automatiquement un plan de trade ICT :

```
Trigger :  fib_state commence par + (bull) ou − (bear) ET range_pct >= 0.05%
Entry    : current_price  (market, pour dashboard live)
SL       : coté opposé de la range + 10% buffers (invalidation modèle complet)
TP1      : ±1.618 fib (deviation standard 1)
TP2      : ±2.618 fib (deviation standard 2)
TP3      : ±4.0   fib (deviation standard 3)
RR       : (TP1 - EP) / (EP - SL)  en valeur absolue
```

| `Trade` | `Plan`             | `RR`  | Signification                                                                       |
| ------- | ------------------ | ----- | ----------------------------------------------------------------------------------- |
| `BUY`   | `SL 1.34174 → TP1 1.34559` | `1.6×` | AL swept + prix > AH. ACHETER au prix actuel, TP 1.618 fib, RR calculé sur 1× range |
| `SELL`  | `SL 1.34245 → TP1 1.33775` | `2.0×` | AH swept + prix < AL. VENDRE au prix actuel, cible -1.618 fib                       |
| `—`     | `TP1-3 hit`        | `—`   | Tout la grille (-4.0 à +4.0) a été parcourue → ne pas chercher de nouveau trade     |
| `—`     | `Range too tight`  | `—`   | Range asiatique trop étroite (<0.05% du spot) → RR trop faible, pas de trade         |
| `—`     | `—`                | `—`   | Pas de bias directionnel encore (sweep ambigu, prix reste dans la range)            |

> **Lecture rapide** : tu prends uniquement les lignes où `Trade ∈ {BUY, SELL}` ET `RR >= 1.0`. Celles-ci constituent les setups ICT « valides » du moment. Les autres lignes sont des « wait » (pas d'invalidation : range trop étroite, range pas encore cassée, ou cibles déjà visitées).

## 🗄️ Base de données SQLite

Sous-commande `db` qui permet de consulter et analyser les données collectées automatiquement lors des scans.

Les sessions asiatiques (High/Low + timestamps) et les sweeps (BSL/SSL + date/heure de sweep) sont **automatiquement enregistrés** dans une base SQLite à chaque scan (`asian` ou `sweeps`). Pas de manipulation manuelle nécessaire.

### Structure des données

**Table `asian_sessions`** — une ligne par `(symbole, date, timeframe)` :
- `asian_high` / `asian_low` : les extrêmes de la session
- `high_swept_at` / `low_swept_at` : timestamps UTC du sweep de chaque côté
- `high_swept_session` / `low_swept_session` : session ICT responsable (London, NY...)
- `bull_fib_swept_label` / `bear_fib_swept_label` : niveaux Fibonacci sweepés
- UPSERT : si vous relancez le scan dans la même journée, la même ligne est **mise à jour** (pas de doublon)

**Table `sweep_events`** — chaque sweep BSL/SSL détecté :
- `sweep_label` : BSL ou SSL
- `level` : prix du swing point swept
- `sweep_time` : timestamp UTC de la bougie qui a swept
- `direction` : `reversal_up` ou `reversal_down`

### Commandes

```bash
# Statistiques globales (total sessions, sweeps, symboles suivis)
python main.py db stats

# Lister les 30 dernières sessions asiatiques
python main.py db list

# Filtrer par symbole
python main.py db list --symbol XAUUSD

# Filtrer par date
python main.py db list --date 2026-06-17

# Lister les sweeps plutôt que les sessions asiatiques
python main.py db list --what sweeps --symbol EURUSD

# Limiter le nombre de résultats
python main.py db list --limit 100

# Voir le chemin et la taille du fichier
python main.py db path
```

> 💡 Le fichier `inelida_market_data.db` est créé dans le dossier du projet. Tu peux aussi l'ouvrir avec n'importe quel client SQLite (DB Browser, DBeaver, etc.) pour faire des requêtes personnalisées.

---

## 🎮 Trade Execution (FTMO / broker MT5)

Sous-commande `trade` (et raccourci **`asian --execute`**) qui **pilote MT5 pour envoyer les Trade Ideas** generees par le scanner asiatique. Wrap `mt5.order_send()` avec des garde-fous (anti-double-ordre, validation lot, filling-mode auto-detect, magic 888001).

**Defaut = LIVE** (envoi reel dans MT5). Pour un preview SANS toucher au broker, passer `--dry-run`.

### Commandes

```bash
# 1) Lister TOUS les trades 'Active' du scan H1 (lecture seule)
python main.py trade list

# 2) Lister les trades pour UNE liste explicite de symboles
python main.py trade list --symbols GBPUSD EURUSD XAUUSD

# 3) DRY-RUN avant envoi : montre CE QUI SERAIT envoye, sans toucher au broker
python main.py trade execute --dry-run

# 4) ENVOI REEL sur FTMO-demo (avec confirmation Y/N globale)
python main.py trade execute

# 5) Envoi reel d'un SEUL trade (filtre --symbol)
python main.py trade execute --symbol GBPUSD --lots 0.01

# 6) Auto-confirm (skip Y/N interactif — utilise dans scripts cron / bots)
python main.py trade execute --symbol XAUUSD --yes

# 7) Filtre RR >= 1.0 (skip les trades dont le risk:reward est trop faible)
python main.py trade execute --rr-min 1.0

# 8) JSON pour integration externe
python main.py trade list --json > trades.json
python main.py trade execute --json > results.json

# 9) Raccourci 'asian --execute' : scan + envoi en UNE commande
python main.py asian --timeframe M15 --execute --dry-run --lots 0.01   # preview
python main.py asian --timeframe M15 --execute --yes --lots 0.01        # live sans confirm
```

### Flags de `trade execute` (et `asian --execute`)

| Option           | Défaut       | Effet                                                                              |
| ---------------- | ------------ | ---------------------------------------------------------------------------------- |
| `--timeframe`    | `H1`         | Timeframe du scan asiatique (H1 ou M15)                                            |
| `--lots`         | `0.01`       | Volume par ordre (aligne sur `lot_step` du symbole)                                |
| `--rr-min`       | `None`       | Filtre RR minimal (ex. `--rr-min 1.5` skip RR < 1.5)                                |
| `--symbol`       | `None`       | Filtre sur UN symbole                                                             |
| `--dry-run`      | LIVE         | Sans ce flag : **LIVE** (envoi reel). Avec `--dry-run` : preview sans rien envoyer. |
| `--yes`          | interactive  | Skip la confirmation Y/N globale (auto-confirm / cron)                              |
| `--json`         | ASCII        | Sortie JSON pour integration externe                                                |
| `-v`             | -            | Logging DEBUG                                                                      |

### Garde-fous d'execution

| Garde-fou                  | Implementation                                                                  |
| -------------------------- | ------------------------------------------------------------------------------- |
| DRY-RUN par defaut         | `TradeExecutor.dry_run=True` ; `--live` requis pour envoyer                     |
| Anti-double-ordre          | Skip si une position `magic == 888001` existe deja sur ce `symbol+direction`   |
| Validation volume          | Alignement sur `info.volume_step`, clamps `min_lot..max_lot`                    |
| Filling mode               | Auto-detection `info.filling_mode` (FOK / IOC) avant envoi                      |
| Tick price                 | Lecture `mt5.symbol_info_tick()` immediatement avant chaque ordre (pas cache)   |
| Confirmation globale       | Y/N interactif une seule fois (saute si `--yes`)                                |
| Magic + Comment            | `magic=888001`, `comment="InelidaMarketScanner ICT"` (31 chars max sur certains brokers) |
| Retcode mapping            | Toutes les issues MT5 parsees en messages lisibles (DONE, REJECT, NO_MONEY...)  |

### Exemple de sortie `trade list`

```
== Available Trade Ideas (scan H1) ==
Symbole    Action  Lots    EP          SL          TP1         Dev  RR    Magic
----------------------------------------------------------------------------------
GBPUSD       SELL  0.01    1.33946   1.34352   1.33917     20  0.1×  888001
XAUUSD        BUY  0.01  4365.31    4314.39   4401.02     20  0.7×  888001

[DRY-RUN] 2 ordre(s) prets (sources: AsianSession_Fib_*).
```

### Exemple de sortie `trade execute --live`

```
=== LIVE EXECUTION ===
  2 ordre(s) vont etre envoyes.
  Lot=0.01, RR_min=no
  Confirmer ? [y/N] y

== Trade Execution Results ==

Symbole    Status    Action    Lots  OrderID    DealID    Retcode       Note
GBPUSD    FILLED     SELL      0.01  1234567   1234567    DONE          Trade successful
XAUUSD    FILLED      BUY      0.01  1234568   1234568    DONE          Trade successful

2 filled | 0 dry-run | 0 failed | 0 skipped (sur 2 total)
```

---

---

## 🔴 LIVE SWEEP DETECTOR (sans trade)

`live_monitor.py` est un **détecteur de sweeps en temps réel** qui NE TRADE JAMAIS.

Il surveille les symboles et alerte à l'écran dès qu'un sweep ICT est détecté, avec une **explication complète** du trade potentiel. Aucun ordre n'est envoyé au broker.

### Trois couches de détection

| Couche | Mécanisme | Timeframe | Quand ? |
|--------|-----------|-----------|---------|
| 🌏 **Asian** | Mèche traverse AH/AL + close rejette (range asiatique) | M1 | Seulement après 10:00 (range verrouillé) |
| 🔷 **Fractal** | Williams N=2, BSL/SSL sur swing points | M15 | 24h/24 |
| 🏛️ **Daily/Weekly** | PDH/PDL (Previous Day High/Low) + PWH/PWL (Previous Week High/Low) | H1 / D1 | 24h/24 |

> ⚠️ **Important** : Le range asiatique évolue pendant les 8h de la session (02:00–10:00 plateforme). Les sweeps asiatiques sont **bloqués** jusqu'à ce que le range soit verrouillé à 10:00. Le statut `[EN COURS]` / `[FORME]` est affiché au démarrage. Fractal et Daily/Weekly restent actifs 24h/24.

### Usage

```bash
# Scan les 43 symboles par défaut (forex, indices, or, crypto, pétrole)
python live_monitor.py

# Watchlist custom (variable d'environnement)
set INELIDA_LIVE_WATCHLIST=GBPJPY,XAUUSD,EURUSD
python live_monitor.py

# Un seul symbole
set INELIDA_LIVE_WATCHLIST=GBPJPY
python live_monitor.py
```

**Ctrl+C** pour arrêter. Toutes les alertes sont journalisées dans `live_sweeps.log`.

### Ce que vous voyez

Quand un sweep est détecté, une alerte s'affiche avec :

- **Type de sweep** : BSL (Buy-Side Liquidity) ou SSL (Sell-Side Liquidity)
- **Niveau sweepé** : prix exact du niveau (AH/AL, PDH/PDL, PWH/PWL, ou swing fractal)
- **Trade potentiel** : BUY ou SELL avec Entry, SL, TP1, TP2, RR (Asian sweeps uniquement)
- **Direction ICT** : reversal_down (BSL) ou reversal_up (SSL)
- **Heure plateforme** et **session ICT** en cours
- **Son** (BELL) pour attirer l'attention

### ⚠️ Zéro trade

Le script utilise MT5 uniquement pour **lire** les données (barres M1/M15/H1/D1/W1, ticks). Aucun `order_send` n'est présent dans le code. C'est un pur outil de **surveillance et d'alerte**.

---

## 🔴 LIVE — ICT FVG Monitor (NOUVEAU)

Nouvelle stratégie de trading basée sur les **Fair Value Gaps (FVG)** et le **Draw On Liquidity (DOL)**, distincte de la stratégie Asian/Sweep/Fibonacci.

### Lancer le moniteur

```bash
# Moniteur mono-symbole
python live_ict_monitor.py XAUUSD              # Démarre la surveillance
python live_ict_monitor.py XAUUSD --interval 15  # Scan toutes les 15s
python live_ict_monitor.py EURUSD --fvg-min 0.05 # Filtre FVG plus strict

# Moniteur MULTI-ACTIFS (global)
python live_ict_monitor_global.py                                            # Market Watch, 50 symboles max
python live_ict_monitor_global.py --scan-all --max-symbols 0             # Tous les actifs du broker
python live_ict_monitor_global.py --symbols EURUSD XAUUSD BTCUSD
python live_ict_monitor_global.py --filter-type FOREX,METAL --interval 30
python live_ict_monitor_global.py --require-macro                        # Filtre ICT: raid sur :10/:50 ±5min
python live_ict_monitor_global.py --require-killzone                     # Filtre ICT: raid en London/NY Open/Close
python live_ict_monitor_global.py --require-macro --require-killzone     # Les deux filtres ICT
```

**Ce qu'il fait :**
- Se connecte à MT5 en lecture seule
- Détecte les setups ICT FVG en 5 étapes (DOL → Raid → FVG → Retracement)
- **Alerte visuelle** avec plan SL/TP complet
- **Log JSONL** de tous les signaux

**Résultats backtestés** (XAUUSD M3, 6 mois) : 214 trades, +105R, 2000€ → 4856€ (+143%)

📖 **Guide utilisateur complet** : `new_analysis_02/guide_ict_fvg_live.md`  
📖 **Algorithme détaillé** : `new_analysis_02/algo.md`

### Tous les scripts ICT FVG

| Script | Usage |
|--------|-------|
| `live_ict_monitor.py SYMBOLE` | Surveillance temps réel — 1 symbole (alertes) |
| `live_ict_monitor_global.py` | Surveillance temps réel — **tous les actifs** (alertes + filtres ICT optionnels) |
| `backtest_ict_universal.py SYMBOLE` | Backtest v1 sur n'importe quel symbole |
| `backtest_ict_fvg_v1.py` | Backtest v1 XAUUSD uniquement |
| `backtest_ict_fvg.py` | Backtest v2 avec filtres ICT complets |
| `download_historical.py SYMBOLE` | Télécharger les données M3 depuis MT5 |
| `analyze_winners_losers.py` | Analyse comparative gagnants vs perdants |

---

## 📋 Rapport PDF horodaté & Backtest ICT

Le projet inclut **deux scripts** de rapport :

| Script | Fichier | Description |
|--------|---------|-------------|
| `generate_live_report.py` | `inelida_report_YYYY-MM-DD.pdf` | **Scan MT5 LIVE** — se connecte à MT5, exécute les 4 scans (sweeps, asian, levels, setups) et génère un PDF horodaté |
| `backtest_report_trades.py` | *(console uniquement)* | **Backtest rétroactif** — prend un rapport existant et simule chaque trade contre les données MT5 réelles postérieures |

### 📄 generate_live_report.py — Rapport LIVE horodaté

Produit un PDF au format **identique à `generate_report.py`** (le template statique) mais avec des **données live** récupérées directement depuis MT5 :

```bash
# Générer le rapport avec tous les actifs disponibles
python generate_live_report.py
```

Le script exécute **4 scans MT5** en séquence :

| Scan | Module utilisé | Timeframe | Ce qui est détecté |
|------|---------------|-----------|-------------------|
| **1. Sweeps BSL/SSL** | `scan_market_watch_for_sweeps()` | M15 | Swings fractals Williams (N=2) sweepés — top 30 par distance au prix |
| **2. Session Asiatique** | `scan_market_watch_asian_ranges()` | H1 | Range AH/AL (UTC 00-08h), sweeps post-Asian, extensions Fibonacci, idées de trade |
| **3. Niveaux Daily/Weekly** | `scan_market_watch_levels()` | H1/D1 | PDH/PDL et PWH/PWL avec sweeps et direction cible |
| **4. Setups directionnels** | *(dérivé du scan 2)* | — | Filtre les trades actifs avec Entry/SL/TP1/RR |

**Structure du PDF généré :**
- 📄 **Page de garde** : horodatages UTC/Paris/Plateforme, infos compte, résumé global
- 🔍 **Section 1** : Sweeps BSL/SSL (top 30, triés par distance %)
- 🌏 **Section 2** : Session Asiatique (trades actifs + tous les résultats)
- 📈 **Section 3** : Niveaux Daily & Weekly (PDH/PDL, PWH/PWL)
- 🎯 **Section 4** : Setups Directionnels & Trade Ideas
- 📝 **Section 5** : **TRADE TRACKING** — tableau des trades à vérifier 24h plus tard
- 📖 **Section 6** : Méthodologie de vérification

> 💡 Chaque exécution crée un fichier `inelida_report_YYYY-MM-DD.pdf` — les anciens rapports ne sont jamais écrasés.

### 🔄 backtest_report_trades.py — Backtest rétroactif (auto depuis PDF)

Prend **n'importe quel rapport PDF horodaté**, en extrait automatiquement les trades, et les **simule contre les données MT5 réelles** postérieures pour déterminer lesquels auraient été gagnants ou perdants :

```bash
# Backtest automatique depuis un rapport PDF (extraction auto des trades)
python backtest_report_trades.py --pdf inelida_report_2026-06-19.pdf

# Avec un rapport fraîchement généré
python backtest_report_trades.py --pdf inelida_report_2026-06-23.pdf
```

**Fonctionnement :**
1. **Extraction automatique** — lit le PDF via PyPDF2, repère la section `TRADE TRACKING` et parse chaque ligne `Setup SYMBOLE ACTION ENTRY SL TP1 RR`
2. **Connexion MT5** — comme `generate_live_report.py`, utilise la connexion MT5 existante
3. **Simulation bougie par bougie** — pour chaque trade, récupère les barres M5/M15/H1 postérieures à la date du rapport
4. **Règle ICT** : si le prix touche **TP1 avant SL** → ✅ GAGNÉ, si **SL touché avant TP1** → ❌ PERDU, sinon → 🟡 OUVERT

> 💡 Plus besoin d'éditer le script ! Le `--pdf` fait tout automatiquement. Fonctionne avec n'importe quel rapport généré par `generate_live_report.py`. Nécessite `PyPDF2` (`pip install PyPDF2`).
>
> ⚙️ **Correction de timestamp (24 juin)** : le backtest extrait désormais l'heure exacte du scan depuis la ligne `Heure UTC` du PDF. Seules les barres **postérieures au scan** sont simulées — les barres antérieures (qui faussaient les résultats) sont exclues.

### 📊 Résultats des backtests

> ⚠️ **Bug corrigé le 24 juin 2026** : le TP était hardcodé à `1.618 × range` pour tous les trades. Or un trade ICT n'est généré que si le prix a déjà cassé le côté opposé du range asiatique — il peut donc être au-delà de +1.618. Dans ce cas, le TP hardcodé se retrouvait **en-dessous du prix d'entrée** pour un BUY (et au-dessus pour un SELL) → toucher le TP = perdre de l'argent. Le backtest comptait ces trades comme « gagnés » alors qu'ils étaient financièrement **perdants**.  
> **Fix** : le TP est maintenant dérivé du prochain niveau Fibonacci non atteint (`fib_state_val`) plutôt que de 1.618 en dur. Voir `src/sweep_detector.py`.

#### Rapport du 19 juin 2026 (scan à 19:20 UTC)

**8 trades** extraits du PDF. Backtesté avec le fix de timestamp + correction TP inversé :

| Issue | Détail |
|-------|--------|
| 🟢 **VRAIS GAGNÉS** | **3** — CORN.c, NATGAS.cash, CADCHF (TP correctement placé ET touché) |
| 🔴 **PERDUS** | **4** — GBPJPY, EURCAD + USDNOK, DXY.cash (ces 2 derniers avaient un **TP inversé** : le backtest disait « gagné » mais le TP était du mauvais côté → perte réelle) |
| 🟡 **OUVERT** | **1** — SOYBEAN.c (TP correct) |
| 🎯 **Winrate réel** | **42.9%** (3/7 clôturés) — le winrate de 71.4% affiché avant le fix était gonflé par les 2 faux gagnants |

#### Rapport du 23 juin 2026 (scan à 22:09 UTC, backtesté le 24 juin)

**16 trades** extraits du PDF. Backtesté avec le fix de timestamp + correction TP inversé :

| Issue | Détail |
|-------|--------|
| 🟢 **VRAIS GAGNÉS** | **3** — CORN.c, NATGAS.cash, USDCHF (TP correct ET touché) |
| 🔴 **PERDUS** | **6** — DXY.cash, EURJPY, EURUSD, GBPJPY, HEATOIL.c, USDCZK (**TP inversé** : le backtest disait « gagné à 22:10 UTC » mais le TP était du mauvais côté de l'entry → perte financière réelle) |
| 🟡 **OUVERTS** | **7** — ALGUSD, AVAUSD, CHFJPY, DASHUSD, IMXUSD, SOYBEAN.c, UK100.cash (tous avec TP correctement placé, encore en cours) |
| 🎯 **Winrate réel** | **33.3%** (3/9 clôturés) — le winrate de 100% affiché avant le fix était entièrement faux (6 faux gagnants sur 9) |

> 📝 **Leçons** :  
> 1. **Vérifier le placement du TP** : un TP doit toujours être du côté attendu (au-dessus de l'entry pour BUY, en-dessous pour SELL).  
> 2. **48-72h minimum** pour un backtest fiable — les trades du 23 juin ouverts sont encore en cours.  
> 3. Le fix de timestamp (24 juin) exclut les barres antérieures au scan pour éviter les faux SL pré-scan.

### 🔗 Workflow complet — 2 commandes seulement

Voici la **chaîne complète** d'utilisation, du scan au backtest, avec le minimum de commandes :

```bash
# ─── ÉTAPE 1 : Scan LIVE + génération du rapport horodaté ─────────────
python generate_live_report.py
#  → Produit : inelida_report_2026-06-24.pdf
#  → Contient : sweeps, session asiatique, niveaux daily/weekly,
#               setups directionnels, et 10-20 trades à tracker

# ... 48-72h plus tard, rouvre MT5 et lance :

# ─── ÉTAPE 2 : Backtest automatique depuis le PDF ──────────────────────
python backtest_report_trades.py --pdf inelida_report_2026-06-24.pdf
#  → Extrait automatiquement les trades du PDF
#  → Simule chaque trade contre les données MT5 réelles
#  → Affiche : GAGNÉ / PERDU / OUVERT + winrate
```

**Ce qui se passe en détail :**

| Étape | Commande | Durée | Résultat |
|-------|----------|-------|----------|
| **Scan** | `python generate_live_report.py` | ~2-5 min | PDF horodaté avec tous les trades ICT actifs |
| **Attente** | *(laisser les trades maturer)* | 48-72h | Les TP/SL ont le temps d'être touchés |
| **Backtest** | `python backtest_report_trades.py --pdf inelida_report_YYYY-MM-DD.pdf` | ~1-3 min | Winrate réel, trades gagnants/perdants |

> ⚠️ **MT5 doit être ouvert et connecté** pour les deux étapes (scan et backtest).
>
> 🎯 **En 2 commandes**, tu obtiens un rapport de scan complet puis un backtest chiffré — sans rien écrire à la main, sans éditer de code, et sans risque d'écraser les anciens rapports.
>
> **Variante avec filtre par type d'actif** : si tu veux scanner uniquement le Forex et les Métaux au lieu de tous les symboles, utilise `full_session_analysis.py` (qui accepte `--categories` et `--limit`) au lieu de `generate_live_report.py`. Le rapport produit est au même format et compatible avec le backtest :
> ```bash
> python full_session_analysis.py --categories Forex Métaux --limit 50
> # Puis, 48-72h plus tard :
> python backtest_report_trades.py --pdf ict_analysis_2026-06-24.pdf
> ```

---

## 📊 Dashboard Streamlit

Le projet inclut une **interface web Streamlit** pour visualiser les résultats sans passer par le terminal.

### Lancement

```bash
# Depuis le dossier du projet
streamlit run app.py

# Ou via le lanceur Windows (tue l'ancien process + nettoie le cache)
start_dashboard.bat
```

### Pages

| Page                          | Description                                                   |
|-------------------------------|---------------------------------------------------------------|
| 🏠 **Dashboard**              | Métriques globales (sessions, sweeps, taux), dernières dates  |
| 🌏 **Sessions Asiatiques**    | Tableau filtré (symbole, date, sweep, breach) avec couleurs   |
| 📈 **Niveaux Daily/Weekly**   | PDH/PDL et PWH/PWL depuis la DB                               |
| ⚡ **Sweep Events**           | BSL/SSL events avec filtres                                   |
| 🗄️ **Base de Données**        | Infos DB + liste des tables + réinitialisation du cache       |
| 🔍 **Scan en Direct**         | Boutons pour lancer les scans (asian, levels, sweeps, setups) |

Les données sont lues depuis la base SQLite avec un cache de 10 secondes. Les scans en direct appellent `main.py` en subprocess et les résultats sont sauvegardés en DB.

### start_dashboard.bat

Le batch `start_dashboard.bat` (inspiré du projet `trading`) automatise le redémarrage :
1. Tue les anciens processus Streamlit sur le port 8501 (`netstat` + `taskkill`)
2. Nettoie les caches Python (`__pycache__`, `*.pyc`)
3. Lance Streamlit fraîchement avec `python -B`

---

### Note live / FTMO

Utilise sur **FTMO-Demo** (terminal `FTMO Global Markets MT5 Terminal`, compte demo 100k). Le capital FTMO impose des regles strictes (pas de SL, pas d'algo, target journaliere 1%, max DD 5%) — garde toujours un **journal de tes executions** pour backtest.

### Disclaimer

La plage Asian utilisée est **UTC 00:00–08:00** (convention ICT). Sur FTMO-Demo, ça correspond à 03:00–11:00 horloge serveur (décalage EEST). ICT alternatif propose parfois 18:00–02:00 NY — non implémenté ici, mais modifiable dans `src/config.py` → `ASIAN.start_utc / end_utc`.

---

## 🐞 Dépannage

| Erreur                                                | Cause / Solution                                                            |
| ----------------------------------------------------- | --------------------------------------------------------------------------- |
| `ImportError: No module named 'MetaTrader5'`          | Installer sur Windows ; le binding ne tourne pas sous macOS / Linux.        |
| `initialize() returned None`                          | Terminal MT5 non lancé. Ouvre-le et connecte-toi à un compte.               |
| `[-1] Terminal: Unauthorized`                         | Login/password erronés. Renseigne `MT5Config.login/password/server` ou laisse le terminal ouvert et déjà logué. |
| `Symbole inconnu chez le broker`                      | Ton broker ne propose pas le symbole. Remplace-le dans la watchlist.        |
| Couleur ANSI cassée sous Windows                      | Utilise Windows Terminal ou PowerShell récents ; sinon le mode dégradé print les lignes sans couleur. |

---

## ⚖️ Avertissement

Ce projet est fourni à des fins éducatives. Le trading comporte un risque de perte en capital. L'auteur ne saura être tenu responsable des pertes résultant de l'utilisation de cet outil.

---

## 📜 Licence

Voir le fichier `LICENSE`.
