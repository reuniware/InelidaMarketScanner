# 📖 Guide d'Utilisation — Inelida Market Scanner

> **Bienvenue !** Ce guide est conçu pour les débutants. Il explique pas à pas
> comment utiliser chaque fonction de l'outil, sans jargon technique inutile.

---

## 🚀 Avant de commencer

### Ce dont vous avez besoin

1. **MetaTrader 5** installé et connecté à un compte (démo ou réel)
2. **Python 3.10+** installé sur votre machine
3. Le projet cloné depuis GitHub

### Installation rapide

```bash
pip install -r requirements.txt
```

### Premier test

```bash
python main.py scan --symbols EURUSD
```

Si vous voyez un tableau avec des prix, c'est que tout fonctionne ! 🎉

---

## 📋 Table des matières

1. [Scan rapide d'un symbole](#1-scan-rapide-dun-symbole)
2. [Scan de tous les symboles](#2-scan-de-tous-les-symboles)
3. [Analyse de la session asiatique (ICT)](#3-analyse-de-la-session-asiatique-ict)
4. [Analyse Diamond (Ichimoku multi-TF)](#4-analyse-diamond-ichimoku-multi-tf)
5. [Suivi P&L des trades](#5-suivi-pl-des-trades)
6. [Backtest des trades détectés](#6-backtest-des-trades-détectés)
7. [Publication Discord automatique](#7-publication-discord-automatique)
8. [Monitoring en temps réel](#8-monitoring-en-temps-réel)
9. [Configuration avancée](#9-configuration-avancée)
10. [Dépannage](#10-dépannage)

---

## 1. Scan rapide d'un symbole

### Commande

```bash
python main.py scan --symbols EURUSD
```

### Ce que ça fait

Affiche les prix actuels et les indicateurs techniques de base (Kijun, Tenkan, Kumo)
pour le(s) symbole(s) demandé(s).

### Variantes

```bash
# Un seul symbole
python main.py scan --symbols XAUUSD

# Plusieurs symboles
python main.py scan --symbols EURUSD GBPUSD USDJPY

# Avec plus de détails (mode verbose)
python main.py scan --symbols EURUSD --verbose
```

---

## 2. Scan de tous les symboles

### Commande

```bash
python main.py scan
```

### Ce que ça fait

Scanne **tous les symboles** de la watchlist configurée (par défaut : ~13 symboles
majeurs : EURUSD, GBPUSD, USDJPY, XAUUSD, indices US, etc.).

### Comment changer la watchlist ?

Dans le fichier `.env` (créez-le si nécessaire) :

```
INELIDA_WATCHLIST=EURUSD,GBPUSD,USDJPY,XAUUSD
```

Ou directement en ligne de commande :

```bash
python main.py scan --symbols EURUSD GBPUSD
```

---

## 3. Analyse de la session asiatique (ICT)

C'est la fonctionnalité **la plus puissante** pour le day trading ICT.

### Qu'est-ce que c'est ?

La session asiatique crée un range (plus haut = AH, plus bas = AL).
Les institutions viennent ensuite « sweeper » (casser brièvement) ces niveaux
pour piéger les traders avant de partir dans l'autre direction.

### Commandes

```bash
# Scan asiatique de base (watchlist)
python main.py asian

# Scan EXHAUSTIF de TOUS les symboles du broker (~167 paires)
python main.py asian --scan-all

# Afficher UNIQUEMENT les symboles qui ont sweepé AH ou AL
python main.py asian --scan-all --swept-only

# Avec fuseau horaire spécifique (BROKER = heure MT5, UTC, PARIS)
python main.py asian --scan-all --swept-only --timezone BROKER
```

### Comment lire les résultats ?

```
Symbole    AsianHigh   AsianLow   AH Swp  AL Swp  Swept H@  Swept L@
EURUSD     1.14482     1.14345    OUI     NON     10:00     --
```

- **AH Swp** : le plus haut asiatique a été sweepé
- **AL Swp** : le plus bas asiatique a été sweepé
- **Swept H@** : heure du sweep (fuseau configuré)
- Si les DEUX sont sweepés → range épuisé, pas de trade directionnel

### Stratégie ICT classique

1. Attendre qu'AH ou AL soit sweepé (un seul des deux)
2. Entrer dans la direction opposée (si AL sweepé → LONG vers AH)
3. Placer le TP sur l'autre liquidité

---

## 4. Analyse Diamond (Ichimoku multi-TF)

### Qu'est-ce que c'est ?

L'analyse la plus complète : combine **Ichimoku** (H1, H4, D1, W1, MN) avec
les concepts **ICT** (FVG, Order Blocks, Breaker Blocks, MSS/BOS, Volume)
sur **109 critères de scoring**.

### Commandes

```bash
# Scan Diamond complet (watchlist)
python main.py diamond

# Sur des symboles spécifiques
python main.py diamond --symbols EURUSD USDJPY XAUUSD

# Avec fuseau horaire
python main.py diamond --timezone BROKER

# Avec envoi Discord automatique
python main.py diamond --discord

# Volume uniquement (HVN/LVN)
python main.py diamond --volume-only
```

### Comment lire les résultats ?

```
Symbole    Score  Biais   Qualité  Prix      Kj H1     T/Kx H1  Kumo H1
EURUSD     40/109 BULL    WAIT     1.14472   1.14537   BEAR     INSIDE
```

| Colonne | Signification |
|:---|:---|
| **Score** | Note sur 109 : plus c'est haut, plus les critères sont alignés |
| **Biais** | Direction probable : BULL (achat), BEAR (vente), FLAT (neutre) |
| **Qualité** | STRONG (feu vert), GOOD (orange), WAIT (rouge — ne pas trader) |
| **T/Kx H1** | Tenkan/Kijun croisement H1 : BULL ou BEAR |
| **Kumo H1** | Position par rapport au nuage : ABOVE (au-dessus), BELOW (en-dessous), INSIDE (dedans) |
| **OU%** | Ornstein-Uhlenbeck : score d'overextension (0-100%). >80% = retournement probable |
| **Hst** | Exposant de Hurst : <0.45=RANGE, >0.55=TREND. Indique le régime de marché |
| **ML%** | Probabilité de gain prédite par le modèle XGBoost v18 (123 features) |

### 🧮 Indicateurs quantitatifs (nouveautés 19/07/2026)

Le scan Diamond affiche désormais des indicateurs de finance quantitative :

| Indicateur | Description |
|:---|:---|
| **OU%** | Score Ornstein-Uhlenbeck (0-100%) — détecte quand le prix est trop loin de sa moyenne. >80% = retournement très probable |
| **Hst** | Exposant de Hurst (0-1) — classifie le régime : <0.45 = RANGE (mean-reversion), >0.55 = TREND (momentum) |
| **GARCH** | Prévision de volatilité — persistance des chocs, volatilité long-terme, demi-vie |
| **Monte Carlo** | Simulation de 10 000 trajectoires — probabilité que le TP soit touché avant le SL |
| **Kelly Criterion** | Dimensionnement optimal des positions par type d'actif (DXY=73%, Forex=31%, etc.) |
| **FTMO Ruin** | Probabilité de ruine d'un compte prop firm avec drawdown 10% |

Ces indicateurs sont visibles dans la ligne de détail des setups actifs :
```
OU: 85% | Hurst: 0.32 RANGE | MC P(TP): 72% | Garch: P=0.97 HL=23b
```

### ⚠️ Les 3 garde-fous automatiques (ajoutés le 17/07/2026)

Le scanner applique automatiquement 3 règles apprises du backtest :

1. **T/Kx H1 conflit** : si le biais est BULL mais T/Kx H1 est BEAR → qualité = WAIT
2. **Pas de respiration** : si le Kijun est plat et le prix coincé dans le Kumo → downgrade
3. **HIGH NEWS DAY** : si ≥2 événements macro majeurs (Trump, FOMC, CPI...) → BULL downgradé

> **Règle d'or :** Ne tradez que les setups **STRONG** ou **GOOD**.
> Si tout est **WAIT**, restez sur le côté.

---

## 5. Suivi P&L des trades

### Concept

Vous pouvez **sauvegarder** les setups Diamond détectés, puis **vérifier** plus tard
s'ils ont atteint leur TP ou leur SL.

### Commandes

```bash
# 1. Scanner et sauvegarder les setups actifs
python main.py diamond
python main.py track save

# 2. Voir le rapport P&L (tous les trades suivis)
python main.py track report

# 3. Voir l'historique d'un trade spécifique
python main.py track history --id 1

# 4. Mettre à jour les prix de tous les trades ouverts
python main.py track update

# 5. Fermer manuellement un trade
python main.py track close --id 1 --reason "TP atteint manuellement"

# 6. Voir toutes les sessions de scan
python main.py track sessions
```

### Cycle de vie d'un trade

```
1. diamond scan → détecte les setups
2. track save  → sauvegarde en base
3. track update → met à jour les prix (à faire régulièrement)
4. track report → vérifie le P&L
5. track close → ferme le trade (manuel ou auto si SL/TP touché)
```

---

## 6. Backtest des trades détectés

### Qu'est-ce que c'est ?

Revérifie, barre par barre (M1), si les trades que le scanner avait détectés
auraient été gagnants ou perdants. Extrêmement utile pour **valider la stratégie**.

### Commandes

```bash
# Backtest des trades détectés le 16/07
python backtest_trades_detected.py

# Backtest exhaustif des setups du 17/07
python backtest_exhaustif_17jul.py
```

### Métriques importantes

| Métrique | Signification |
|:---|:---|
| **P&L** | Profit/Perte en pips |
| **MFE** | Maximum Favorable Excursion — meilleur prix atteint |
| **MAE** | Maximum Adverse Excursion — pire prix atteint |
| **MFE%** | MFE en % du range SL→TP. Si 0% → le trade n'a jamais respiré |

> **Leçon du backtest :** Si MFE = 0 après 30 barres M1, le trade est mort.
> Coupez la position, n'attendez pas le SL.

---

## 7. Publication Discord automatique

### Configuration

Dans le fichier `.env` :

```
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/VOTRE_URL
```

### Commandes

```bash
# Scan Diamond + envoi sur Discord
python main.py diamond --discord

# Scan Asian + envoi sur Discord (via l'option --discord si disponible)
python main.py asian --scan-all --swept-only
```

### Ce qui est envoyé

- Résumé des scores et biais
- Top 5 setups avec SL/TP/RR
- Warnings (HIGH NEWS DAY, conflits H1, etc.)
- Statistiques globales (STRONG/GOOD/WAIT, BULL/BEAR)

---

## 8. Monitoring en temps réel

### Moniteur ICT FVG

```bash
# Surveiller un seul symbole
python main.py monitor-ict --symbols EURUSD

# Tous les symboles du broker
python main.py monitor-ict --scan-all
```

### Moniteur de sweeps (sans trade)

```bash
python main.py monitor --symbols EURUSD GBPUSD
```

### Alertes live

```bash
python live_alerts.py
python live_ict_monitor.py
python live_ict_monitor_global.py
```

---

## 9. ML Dashboard — Interface Machine Learning

### Qu'est-ce que c'est ?

Le **ML Dashboard** (`app_ml.py`) est une interface web Streamlit qui permet
de gérer tout le pipeline Machine Learning sans écrire une ligne de commande.

### Lancement

```bash
streamlit run app_ml.py
```

Puis ouvrez [http://localhost:8501](http://localhost:8501) dans votre navigateur.

### Les 7 onglets

| Onglet | À quoi ça sert ? |
|:---|:---|
| 📊 **Dashboard** | Vue d'ensemble : statut MT5, DB, modèle ML chargé |
| 🏷️ **Labeling** | Génère le CSV d'entraînement — 3 sources : DB (trades fermés), CSV manuel, ou scan Diamond live |
| 🏋️ **Training** | Entraîne le modèle XGBoost avec réglage des hyperparamètres et visualisation des features importantes |
| 🔮 **Predictions** | Lance un scan Diamond avec prédiction ML% (probabilité de gain) |
| 🔍 **Data Explorer** | Consulte les trades en DB, le P&L cumulé, exporte en CSV |
| 📄 **CSV Viewer** | Ouvre et explore n'importe quel CSV avec filtres, statistiques, distribution et matrice de corrélation |
| 📈 **Feature Importance** | Analyse quels critères pèsent le plus dans les décisions du modèle |

### Workflow ML complet via Dashboard

```
1. 📡 Onglet Labeling → Scan → CSV généré + sauvegarde DB
2. ⏳ Attendre fermeture des trades (SL/TP touché)
3. 🗄️ Onglet Labeling → DB → CSV avec outcome automatique
4. 🏋️ Onglet Training → Entraînement XGBoost
5. 🔮 Onglet Predictions → ML% dans les scans
```

---

## 10. Configuration avancée

### Fichier `.env`

```bash
# Watchlist par défaut
INELIDA_WATCHLIST=EURUSD,GBPUSD,USDJPY,AUDUSD,USDCAD,USDCHF,EURJPY,GBPJPY,XAUUSD

# Webhook Discord
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# Fuseau horaire (BROKER, UTC, PARIS)
INELIDA_TZ=BROKER
```

### Tous les fuseaux horaires supportés

| Option | Description | Décalage (été) |
|:---|:---|---:|
| `BROKER` | Heure du serveur MT5 (défaut) | GMT+3 |
| `UTC` | Temps universel | GMT+0 |
| `PARIS` | Heure de Paris | GMT+2 |

---

## 11. Dépannage

### « MT5 initialization failed »

→ MetaTrader 5 n'est pas lancé ou pas connecté.
   Ouvrez MT5, connectez-vous à un compte, puis relancez.

### « Aucune watchlist »

→ Ajoutez `INELIDA_WATCHLIST` dans le fichier `.env` ou utilisez `--symbols`.

### « Aucune donnée disponible pour [symbole] »

→ Le symbole n'est pas dans la Market Watch MT5.
   Ajoutez-le manuellement dans MT5 (Ctrl+U → chercher le symbole → double-clic).

### « UnicodeEncodeError »

→ Problème d'encodage Windows. Solution :
```bash
chcp 65001
```
Avant de lancer la commande Python.

### « ModuleNotFoundError: No module named 'MetaTrader5' »

```bash
pip install MetaTrader5
```

---

## 🎯 Résumé : quel scan utiliser selon votre besoin ?

| Vous voulez... | Commande |
|:---|:---|
| Voir les prix et indicateurs rapidement | `python main.py scan --symbols EURUSD` |
| Trouver des setups ICT (sweep AH/AL) | `python main.py asian --scan-all --swept-only` |
| Analyse complète Ichimoku + ICT | `python main.py diamond --timezone BROKER` |
| Sauvegarder les trades pour suivi | `python main.py diamond && python main.py track save` |
| Vérifier le P&L des trades passés | `python main.py track report` |
| Backtester la stratégie | `python backtest_trades_detected.py` |
| Envoyer l'analyse sur Discord | `python main.py diamond --discord` |
| Trader automatiquement (DRY-RUN) | `python main.py trade --symbols EURUSD` |

---

> **Dernier conseil :** Commencez toujours par un scan Diamond le matin
> pour avoir une vue d'ensemble. Ensuite utilisez le scan Asian pour
> détecter les setups ICT de la journée. Et surtout : **ne tradez pas
> les jours HIGH NEWS DAY sans une conviction très forte.**

---

> **Didier Vally / Reuniware Systems** — InelidaMarketScan
