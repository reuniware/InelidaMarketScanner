<div align="center">

# 📊 Inelida Market Scanner

*Stratégie ICT (Inner Circle Trader) automatisée pour MetaTrader 5*

![Python](https://img.shields.io/badge/python-3.10+-blue?style=flat-square)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)
![Status](https://img.shields.io/badge/status-experimental-red?style=flat-square)

[Installation](#-installation) •
[Quick Start](#-quick-start) •
[Configuration](#-configuration) •
[Commandes CLI](#-commandes-cli) •
[Trading Automatique](#-trading-automatique) •
[Monitoring Live](#-monitoring-live) •
[Rapports & Backtest](#-rapports--backtest) •
[Dashboard](#-dashboard-streamlit) •
[Dépannage](#-dépannage)

</div>

---

> ## 🛑 PROJET EXPÉRIMENTAL — DÉMONSTRATION UNIQUEMENT
>
> **InelidaMarketScanner est un projet de recherche et d'apprentissage du concept ICT (Inner Circle Trader).**
>
> ⛔ **N'utilisez JAMAIS ce logiciel sur un compte de trading réel.** Les algorithmes de détection et d'exécution sont fournis à titre éducatif et expérimental. Ils peuvent contenir des bugs, des erreurs de logique, ou produire des décisions de trading financièrement désastreuses.
>
> ✅ **Utilisez exclusivement des comptes de démonstration (demo)** fournis par votre broker MetaTrader 5 pour tester, apprendre et évaluer le comportement du scanner.
>
> ⚠️ Le trading comporte un risque de perte en capital. L'auteur ne saura être tenu responsable des pertes résultant de l'utilisation de cet outil.

---

**InelidaMarketScanner** scanne en temps réel les marchés via MetaTrader 5, détecte automatiquement les setups ICT (sweeps de liquidité, range asiatique, Fibonacci, Fair Value Gaps) et peut exécuter les ordres de façon sécurisée — le tout depuis votre terminal.

---

## 📦 Installation

**Prérequis :** Windows + MetaTrader 5 installé et connecté à un compte (demo ou réel).

```bash
git clone https://github.com/reuniware/InelidaMarketScanner
cd InelidaMarketScanner
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env  # édite GEMINI_API_KEY (optionnel, pour les analyses AI)
```

> MetaTrader5 est un binding Windows-only. Le projet ne fonctionne que sur Windows.

---

## 🚀 Quick Start

```bash
# 1. Scan ponctuel de tous les symboles
python main.py snapshot

# 2. Analyse complète de la session asiatique avec plans de trade
python main.py asian

# 3. Détection live des sweeps ICT (alerte visuelle, pas de trade)
python live_monitor.py

# 4. Trading automatique (DRY-RUN par défaut — sans risque)
python live_trader.py --interval 30

# 5. Trading automatique (LIVE — envoi réel des ordres)
python live_trader.py --live --risk-pct 1.0 --rr-min 1.0 --interval 30
```

---

## 📚 Ebooks de Recherche — Téléchargement

> **InelidaMarketScan — Analyse Scientifique des Marchés Financiers avec Machine Learning**
> Par *Didier Vally / Reuniware Systems*

Téléchargez l'ebook complet (16 sections, 109 critères de scoring, 111 features ML,
analyse de 15 modèles XGBoost, validation OOS, feature importance, matrice de décision)
dans votre langue :

| Langue | 📄 Markdown | 📖 EPUB | 📕 PDF |
|:-------|:-----------:|:-------:|:------:|
| 🇫🇷 **Français** | [Lire](https://github.com/reuniware/InelidaMarketScanner/blob/main/ebooks/fr_inelida_marketscan_research.md) | [Télécharger](https://github.com/reuniware/InelidaMarketScanner/blob/main/ebooks/fr_inelida_marketscan_research.epub) | [Télécharger](https://github.com/reuniware/InelidaMarketScanner/blob/main/ebooks/fr_inelida_marketscan_research.pdf) |
| 🇬🇧 **English** | [Read](https://github.com/reuniware/InelidaMarketScanner/blob/main/ebooks/en_inelida_marketscan_research.md) | [Download](https://github.com/reuniware/InelidaMarketScanner/blob/main/ebooks/en_inelida_marketscan_research.epub) | [Download](https://github.com/reuniware/InelidaMarketScanner/blob/main/ebooks/en_inelida_marketscan_research.pdf) |
| 🇩🇪 **Deutsch** | [Lesen](https://github.com/reuniware/InelidaMarketScanner/blob/main/ebooks/de_inelida_marketscan_research.md) | [Herunterladen](https://github.com/reuniware/InelidaMarketScanner/blob/main/ebooks/de_inelida_marketscan_research.epub) | [Herunterladen](https://github.com/reuniware/InelidaMarketScanner/blob/main/ebooks/de_inelida_marketscan_research.pdf) |
| 🇪🇸 **Español** | [Leer](https://github.com/reuniware/InelidaMarketScanner/blob/main/ebooks/es_inelida_marketscan_research.md) | [Descargar](https://github.com/reuniware/InelidaMarketScanner/blob/main/ebooks/es_inelida_marketscan_research.epub) | [Descargar](https://github.com/reuniware/InelidaMarketScanner/blob/main/ebooks/es_inelida_marketscan_research.pdf) |
| 🇮🇹 **Italiano** | [Leggi](https://github.com/reuniware/InelidaMarketScanner/blob/main/ebooks/it_inelida_marketscan_research.md) | [Scarica](https://github.com/reuniware/InelidaMarketScanner/blob/main/ebooks/it_inelida_marketscan_research.epub) | [Scarica](https://github.com/reuniware/InelidaMarketScanner/blob/main/ebooks/it_inelida_marketscan_research.pdf) |
| 🇵🇹 **Português** | [Ler](https://github.com/reuniware/InelidaMarketScanner/blob/main/ebooks/pt_inelida_marketscan_research.md) | [Baixar](https://github.com/reuniware/InelidaMarketScanner/blob/main/ebooks/pt_inelida_marketscan_research.epub) | [Baixar](https://github.com/reuniware/InelidaMarketScanner/blob/main/ebooks/pt_inelida_marketscan_research.pdf) |
| 🇨🇳 **中文** | [阅读](https://github.com/reuniware/InelidaMarketScanner/blob/main/ebooks/zh_inelida_marketscan_research.md) | [下载](https://github.com/reuniware/InelidaMarketScanner/blob/main/ebooks/zh_inelida_marketscan_research.epub) | [下载](https://github.com/reuniware/InelidaMarketScanner/blob/main/ebooks/zh_inelida_marketscan_research.pdf) |
| 🇯🇵 **日本語** | [読む](https://github.com/reuniware/InelidaMarketScanner/blob/main/ebooks/ja_inelida_marketscan_research.md) | [ダウンロード](https://github.com/reuniware/InelidaMarketScanner/blob/main/ebooks/ja_inelida_marketscan_research.epub) | [ダウンロード](https://github.com/reuniware/InelidaMarketScanner/blob/main/ebooks/ja_inelida_marketscan_research.pdf) |

> **Contenu :** 16 sections couvrant les fondements théoriques ICT, l'architecture du scanner Diamond (109 critères),
> le pipeline ML (111 features, 15 modèles XGBoost, validation OOS), la simulation de capital,
> la matrice de décision biais × alignment × news × Wednesday, et les limites connues.

---

## ⚙️ Configuration

Trois façons de configurer la watchlist (symboles scannés) :

| Méthode | Exemple |
|---------|--------|
| **Variable d'environnement** | `set INELIDA_WATCHLIST=XAUUSD,EURUSD,BTCUSD` |
| **Drapeau CLI** | `python main.py watch --symbols XAUUSD EURUSD BTCUSD` |
| **Édition directe** | Modifier `DEFAULT_WATCHLIST` dans `src/config.py` |

Le chemin du terminal MT5 et les credentials peuvent être forcés dans `src/config.py` :

```python
MT5 = MT5Config(
    terminal_path=r"C:\Program Files\FTMO Global Markets MT5 Terminal\terminal64.exe",
    login=None, password=None, server=None,  # None = utilise le compte déjà connecté
)
```

> 💡 Si `login=None`, MT5 utilise le compte déjà ouvert dans le terminal — le plus simple.

La clé API Gemini (optionnelle, pour les analyses AI) se configure dans `.env` :
```
GEMINI_API_KEY=ta_cle_ici
```

---

## 🎯 À qui s'adresse cet outil ?

| Public | Description |
|--------|-------------|
| **Trader ICT/SMC** | Scannez automatiquement tous les symboles qui correspondent aux concepts ICT (Asian → London sweep → continuation) |
| **Trader prop firm** (FTMO, MFF, FundedNext) | Visualisez les opportunités en un coup d'œil et exécutez en micro-lots |
| **Développeur Python curieux** | Code modulaire, chaque composant (MT5, détecteur ICT, exécuteur) est isolable |

---

## ✨ Fonctionnalités

| Fonctionnalité | Description |
|---------------|-------------|
| 🔍 **Scan multi-actifs** | Forex, Métaux, Indices, Crypto — tous les symboles disponibles chez le broker |
| 🌏 **Session Asiatique** | Calcul du range AH/AL (00-08 UTC) + sweeps post-Asian + extensions Fibonacci ±1.618 à ±4.0 + timestamps de sweep |
| 🔷 **BSL/SSL Sweeps** | Détection Williams fractals (N=2) avec sweep detection sur M15 à H4 |
| 💎 **Diamond Analysis** | Ichimoku multi-TF (M5/M15/M30/H1/H4/D1/W1/MN) + mémoire institutionnelle (Tenkan/Kijun flat history) + **scoring 109 critères** (FVG 6 TFs, OB 6 TFs, MSS/BOS 6 TFs, Volume HVN/LVN 6 TFs, Breaker Blocks 6 TFs, AH/AL sweeps, Reversal Pipeline) + **Smart TP** (Kijun, FVG, SSB, nuages, Ext Fibonacci) + **SL proximity safety net** + **--discord** flag + **P&L Tracker** intégré |
| 📈 **Backtest Asian** | Backtest 30 jours BSL/SSL asiatique → sweep London → continuation vers l'autre liquidité |
| 🏛️ **Niveaux Daily/Weekly** | PDH/PDL / PWH/PWL avec sweeps, breaches et direction cible |
| 🎯 **ICT FVG** | Stratégie complète en 5 étapes : DOL → Raid → FVG → Retracement → SL/TP |
| 🏆 **Filtres ELITE** | Badges V1 et V2 basés sur des backtests (97.7-100% WR sur les trades filtrés) |
| 🛡️ **Exécution sécurisée** | DRY-RUN par défaut, anti-double-ordre, validation lot, spread max |
| 📊 **Rapports PDF** | Générateur de rapports horodatés avec tous les scans |
| 🎨 **Dashboard Streamlit ML** | Interface web (**7 onglets**) pour gérer le pipeline ML complet (**123 features**) : Dashboard, Labeling, Training, Predictions (ML%), Data Explorer, CSV Viewer, Feature Importance |
| 🧠 **ML Pipeline** | Labeler (DB/manual/scan/backtest) → Entraînement XGBoost (**123 features nommées**) → Prédiction (ML% via v18) → **MLPredictor simplifié** (1 joblib.load au lieu de 5) via `app_ml.py` |
| 🗄️ **Base SQLite** | Enregistrement automatique des sessions, sweeps et niveaux |
| 📊 **P&L Tracker** | Suivi automatisé des setups Diamond : save → update → rapport win rate / P&L + watchlist niveaux LH/LL |
| ⏱️ **M5/M15/M30 Extension** | Détection FVG, OB, MSS/BOS, CHoCH, Volume HVN/LVN et Breaker Blocks sur M5/M15/M30 (6 TFs simultanés, 36+ critères de scoring) |
| 📈 **ML Model v18** | `models/historical_v18.xgb` — 1 210 trades, 64.0% CV, 123 features nommées, F1=0.503. **MLPredictor simplifié** (1 load au lieu de 5). ML% filtering validé |
| 🧮 **Finance Quantitative** | **Ornstein-Uhlenbeck** (mean-reversion), **Hurst Exponent** (régime range/trend), **GARCH(1,1)** (prévision volatilité), **Monte Carlo** (P(SL)/P(TP)), **Kelly Criterion** (position sizing par actif), **FTMO Ruin** (probabilité drawdown 10%) |
| 🔄 **Reversal Pipeline** | Détection sweep → retournement → confirmation (FVG post-sweep, retest LH/LL) avec compteur de barres pour entrée tardive |
| 🧮 **Stochastic Analytics** | **OU%** (overextension mean-reversion), **Hst** (Hurst exponent range/trend), **GARCH vol forecast**, Monte Carlo P(SL/TP), Kelly Criterion par actif, FTMO Ruin prob — affichés dans le scan Diamond |
| 🔗 **Sweep Watchlist** | Sauvegarde des niveaux LH/LL London avec obstacles Ichimoku inter-TF pour vérification de sweep en fin de session NY |
| 🐛 **Intra-Asian Sweep Fix** | Détection des sweeps AH/AL pendant la session asiatique (avant 08:00 UTC) — corrigé 16/07 |
| 💎 **Asian Sweep Scoring** | Les sweeps AH/AL sont des critères de scoring dans le Diamond Scanner (max_score: 109) avec affichage console + Discord |

---

## 🧰 Commandes CLI

```bash
python main.py <commande> [options]
```

| Commande | Description |
|----------|-------------|
| `snapshot` | Capture unique + tableau |
| `watch` | Boucle temps réel (Ctrl+C) |
| `asian` | Analyse range asiatique + Fibonacci + trades |
| `sweeps` | Détection sweeps BSL/SSL |
| `asian-liquidity` | Scan BSL/SSL session asiatique (Williams fractals) |
| `diamond` | Diamond Analysis Ichimoku multi-TF + mémoire institutionnelle |
| `track` | **P&L Tracking** — sauvegarde, mise à jour, rapport de performance des setups Diamond |
| `levels` | Niveaux PDH/PDL + PWH/PWL |
| `setups` | Setups directionnels filtrés |
| `trade` | Liste ou exécute des ordres MT5 |
| `account` | Infos compte MT5 |
| `terminal` | Infos terminal MT5 |
| `db` | Statistiques et requêtes SQLite |
| `watchlist` | Affiche la watchlist configurée |

### 🛡️ Garde-fous automatiques (Leçons du backtest 16-17/07/2026)

Le Diamond Scanner applique **3 filtres de sécurité** basés sur l'analyse
rétrospective de 15 trades réels :

| Filtre | Règle | Effet |
|:---|:---|:---|
| **T/Kx H1 conflit** | Si le biais contredit le croisement Tenkan/Kijun H1 | Qualité → WAIT |
| **Respiration MFE** | Si Kijun plat + prix coincé dans le Kumo | Downgrade -1 niveau |
| **HIGH NEWS DAY** | Si ≥2 événements macro (Trump, FOMC, CPI...) | BULL downgradé |

> 📖 Guide complet : [GUIDE_UTILISATEUR.md](GUIDE_UTILISATEUR.md)

### Exemples

```bash
# Boucle temps réel
python main.py watch --symbols XAUUSD,EURUSD

# Scan asiatique (Market Watch, max 50)
python main.py asian --timeframe H1 --symbols XAUUSD,EURUSD

# Scan asiatique exhaustif (tous les symboles du broker, ~167)
python main.py asian --scan-all

# Scan asiatique sans limite de Market Watch (--all ≠ --scan-all)
python main.py asian --all

# Sweeps avec timeframe custom
python main.py sweeps --timeframe M15 --lookback 100

# Scan BSL/SSL asiatique (exhaustif)
python main.py asian-liquidity --scan-all --tf M15

# Diamond Analysis Ichimoku multi-TF
python main.py diamond --symbols XAUUSD EURUSD GBPUSD

# Diamond Analysis + publication Discord automatique
python main.py diamond --discord

# Diamond Analysis + sauvegarde P&L des setups actifs
python main.py track save

# Diamond Analysis + fuseau horaire BROKER
python main.py diamond --timezone BROKER

# Volume uniquement (HVN/LVN)
python main.py diamond --volume-only

# Backtest 30 jours Asian BSL/SSL → London continuation
python backtest_asian_bsl_ssl.py --days 30

# Trade exécution (DRY-RUN par défaut)
python main.py trade execute --dry-run --lots 0.01

# Trade exécution (LIVE avec filtre RR)
python main.py trade execute --rr-min 1.5 --yes

# Base de données
python main.py db stats
python main.py db list --symbol XAUUSD
```

📖 **Documentation détaillée des colonnes et des flags** → `tradingskills.md`

---

## 🎮 Trading Automatique

> ⛔ **Réservez ce mode aux comptes de démonstration.** Le mode `--live` envoie de véritables ordres à votre broker. Testez toujours avec `python live_trader.py` (DRY-RUN) ou sur un compte demo avant toute utilisation sur compte réel.

Le script `live_trader.py` fusionne le scan continu et l'exécution automatique :

```bash
# DRY-RUN (sécurisé — rien n'est envoyé au broker)
python live_trader.py

# LIVE avec risque 1% du capital
python live_trader.py --live --risk-pct 1.0 --rr-min 1.0 --interval 30

# Lots fixes
python live_trader.py --live --lots 0.02 --symbols XAUUSD,EURUSD
```

**Cycle d'exécution :** (toutes les N secondes)
1. Charge le range asiatique H1 du jour
2. Détecte les sweeps AH/AL post-Asian
3. Calcule les extensions Fibonacci
4. Génère le plan de trade (Entry / SL / TP1-3 / RR)
5. Valide le trade (spread < 0.10%, RR ≥ seuil)
6. Calcule les lots dynamiques (1% du capital ou lots fixes)
7. Vérifie anti-double-ordre
8. Envoie l'ordre MT5

📖 **Algorithme détaillé** → `new_analysis_02/algo.md`

---

## 📡 Monitoring Live

### Détection de sweeps (sans trade)

```bash
python live_monitor.py
```

Surveille en continu les sweeps ICT (Asian + Fractal + Daily/Weekly). Pas d'ordre envoyé.

### ICT FVG Monitor

```bash
# Mono-symbole
python live_ict_monitor.py XAUUSD

# Multi-actifs (tous les symboles du broker)
python live_ict_monitor_global.py

# Avec filtres ICT (macro 10/50 + killzones)
python live_ict_monitor_global.py --require-macro --require-killzone
```

📖 **Guide complet** → `new_analysis_02/guide_ict_fvg_live.md`

---

## 📊 Rapports & Backtest

Le projet génère des **rapports PDF horodatés** avec tous les scans (sweeps, asian, levels, setups) et peut **backtester les trades rétroactivement** contre les données MT5 réelles.

```bash
# Générer un rapport LIVE complet
python generate_live_report.py

# Backtest des trades d'un rapport existant (48-72h plus tard)
python backtest_report_trades.py --pdf reports/inelida_report_YYYY-MM-DD.pdf
```

---

## 📊 Dashboard Streamlit

```bash
streamlit run app.py
```

Pages disponibles : Dashboard, Sessions Asiatiques, Niveaux Daily/Weekly, Sweep Events, Base de Données, Scan en Direct.

---

## 📁 Structure du Projet

```
InelidaMarketScanner/
├── main.py                   # CLI principale (argparse)
├── app.py                    # Dashboard Streamlit
├── live_trader.py            # Trading automatique continu
├── live_monitor.py           # Détecteur live de sweeps
├── live_ict_monitor.py       # Moniteur ICT FVG (1 symbole)
├── live_ict_monitor_global.py# Moniteur ICT FVG (multi-actifs)
├── analyze_asian_bsl_ssl.py  # Scanner BSL/SSL session asiatique
├── backtest_asian_bsl_ssl.py # Backtest Asian BSL/SSL → London continuation
│
├── src/
│   ├── config.py             # Configuration centralisée
│   ├── mt5_connector.py      # Connexion MT5 (singleton)
│   ├── market_scanner.py     # Scan tick + deltas
│   ├── sweep_detector.py     # Détection sweeps + asian + Fibonacci + FVG
│   ├── diamond_scanner.py    # Scanner Ichimoku multi-TF + mémoire institutionnelle
│   ├── trade_executor.py     # Exécution d'ordres MT5
│   ├── display.py            # Rendu console ANSI
│   ├── database.py           # Base SQLite
│   ├── ai_analyst.py         # Analyse via Gemini AI
│   └── ai_client.py          # Client Gemini API
│
├── new_analysis_02/
│   ├── algo.md               # Documentation détaillée de l'algorithme
│   └── guide_ict_fvg_live.md # Guide utilisateur ICT FVG
│
├── reports/                  # Rapports PDF générés (gitignoré partiellement)
├── logs/                     # Logs d'exécution (gitignoré)
├── .env.example              # Template des variables d'environnement
├── requirements.txt
└── README.md
```

---

## 🔒 Sécurité et Garde-fous

| Mécanisme | Détail |
|-----------|--------|
| **DRY-RUN par défaut** | Aucun ordre envoyé sans le flag `--live` |
| **Anti-double-ordre** | Skip si une position existe déjà sur ce symbole+direction (magic 888001) |
| **Validation volume** | Lot aligné sur `volume_step`, clampé min/max |
| **Spread max** | Refus si spread > 0.10% du prix |
| **RR minimum** | Filtre optionnel via `--rr-min` |
| **Risk %** | Calcul dynamique : `lots = risk_amount / |profit_1_lot|` |
| **Filling mode** | Auto-détection FOK/IOC du symbole |
| **Mapping retcodes** | Tous les codes d'erreur MT5 traduits en messages lisibles |
| **Anti-frozen** | Détection des comptes FTMO en daily drawdown |
| **Secrets** | `.env` (API keys) dans `.gitignore` |

---

## 🐞 Dépannage

| Erreur | Cause / Solution |
|--------|------------------|
| `No module named 'MetaTrader5'` | Windows uniquement. `pip install MetaTrader5` |
| `initialize() returned None` | Terminal MT5 pas lancé ou pas connecté |
| `Terminal: Unauthorized` | Login/password erronés ou terminal pas connecté |
| `INVALID_VOLUME` | Lot < volume_min ou pas aligné sur lot_step |
| `FROZEN (retcode 10027)` | Daily drawdown FTMO atteint ou marché fermé |
| `NO_MONEY` | Fonds insuffisants sur le compte |
| `MARKET_CLOSED` | Week-end, jours fériés, ou pause broker |

---

## 📜 Licence

MIT — voir le fichier `LICENSE`.

---

## 👨‍💻 À propos du développeur

Ce projet est développé par un **ingénieur en développement et chef de projet** avec plus de 25 ans d'expérience dans le pilotage de projets informatiques et le développement logiciel multisectoriel : banque et finance, télécommunications, industrie, automobile, distribution, BTP.

### Expertise

| Domaine | Compétences |
|---------|-------------|
| **Gestion de projet** | Méthodologies Agile (Scrum) et cycle en V, pilotage de bout en bout, spécifications, coordination d'équipes |
| **Développement** | Full-stack, API / Web services, applications mobiles natives, systèmes embarqués |
| **Infrastructure** | Cloud (Azure, AWS), architectures SOA/middleware, CI/CD, bases de données, IA / Machine Learning |

### Philosophie

> *La finance de marché et le trading algorithmique sont le terrain de jeu idéal pour appliquer une double compétence : rigueur d'ingénierie système et vision stratégique de chef de projet. InelidaMarketScanner est né de cette conviction — un outil qui parle le langage des traders tout en restant modulaire, testable et documenté comme un logiciel professionnel.*

---

## 🙏 Crédits

- Concepts ICT / SMC : Inner Circle Trader (Michael Huddleston)
- Framework backtest : Analyse quantitative des marchés financiers
- Binding MetaTrader5 : MetaQuotes Ltd.
