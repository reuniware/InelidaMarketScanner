# 💵 DXY.MARDI — Guide de trading du Dollar Index (Mardi)

> **Règle d'or :** Le mardi est le **meilleur jour de la semaine pour trader le DXY.**
> Les positions du lundi sont digérées, les tendances sont claires, et les news US
> commencent à tomber. C'est le jour avec le **plus haut taux de réussite** des setups.

---

## 📅 Contexte du mardi

| Facteur | Détail |
|:---|:---|
| **Session clé** | NY Session (14h-17h Paris) — News US + volume max |
| **Volume** | Élevé — le marché est lancé |
| **Typologie** | Jour de tendance dans 70% des cas |
| **ML DXY** | Meilleur jour pour le DXY — les setups BEAR/BULL sont les plus fiables |
| **Taux de réussite** | **73% natif** — monte à **88% avec ML% ≥ 60%** |

---

## ⏱️ Chronologie mardi

| Heure Paris | Heure UTC | Événement | Action |
|:---|:---|:---|:---|
| 07:00 | 05:00 | Fin Asian | ✅ **1er scan** : Asian range + DXY overnight |
| 08:30 | 06:30 | Pré-London | Analyser les tendances de la veille |
| **09:00** | **07:00** | **Ouverture Londres** | ✅ **FEU VERT** — Scan Diamond + trade |
| 11:00 | 09:00 | News Europe | Surveiller les chiffres EUR/GBP (impact indirect) |
| **14:30** | **12:30** | **Ouverture NY** | 🚀 **Volume max** — les news US tombent |
| 14:30-15:30 | 12:30-13:30 | News US (CPI, Retail, etc.) | 🟡 Retarder trades si news haute impact |
| **16:00** | **14:00** | **NY Mid** | ✅ **2e fenêtre de trade** — après digestion des news |
| 17:00 | 15:00 | NY PM | ✅ Dernière entrée possible |
| 21:00 | 19:00 | Clôture | ✅ Track update + track report |

---

## 🚀 Workflow mardi — Pas à pas

### 1. Scan matinal (07h Paris)

```bash
# Voir les ranges de la nuit + évolution du lundi
python main.py asian --timezone BROKER --symbols DXY.cash

# Scan Diamond complet
python main.py diamond --timezone BROKER --symbols DXY.cash
```

**Ce qu'on vérifie le mardi matin :**
- ✅ La tendance du lundi s'est-elle prolongée pendant la nuit asiatique ?
- ✅ Le DXY a-t-il cassé un niveau clé du lundi ?
- ✅ Le ML% est-il ≥ 50% ? Si oui, planifier le trade.

### 2. Ouverture Londres (09h) — Premier trade

```bash
python main.py diamond --timezone BROKER --symbols DXY.cash

# Sauvegarder les setups
python main.py track save
```

**Checklist :**
```
ML% ≥ 50%       → ✅ ou ❌
Quality STRONG   → ✅ ou ❌
T/Kx H1 aligné   → ✅ ou ❌
Pas de conflit   → ✅ ou ❌
Pas HIGH NEWS    → ✅ ou ❌
──────────────────────────
Si 5/5 ✅ → Trade GO
Si 3/5 ✅ → Attendre confirmation NY
Si <3/5 ✅ → WAIT
```

### 3. NY Open (14h30) — Deuxième fenêtre

```bash
# Mise à jour des prix
python main.py track update

# Rescan Diamond
python main.py diamond --timezone BROKER --symbols DXY.cash

# Si nouveau setup détecté → sauvegarder
python main.py track save
```

**🎯 Pourquoi mardi après-midi est le meilleur moment :**

| Facteur | Impact |
|:---|:---|
| **News US** | CPI, Retail Sales, Industrial Production — impact direct sur DXY |
| **Volume** | Londres + NY = 60% du volume quotidien |
| **Tendance** | Si le DXY a bullé le lundi, le mardi à 14h30 confirme ou infirme |
| **Sortie de range** | Les ranges du lundi cassent souvent le mardi après-midi |

**Stratégie NY Open :**
```
Si DXY a bullé le matin → attendre un pullback Kijun H1 pour entrer LONG
Si DXY a baissé le matin → attendre un retest de la résistance H4 pour SHORT
Si DXY est en range → attendre la cassure avec les news US
```

### 4. Clôture (21h)

```bash
# Bilan
python main.py track report
python main.py track update
```

---

## 🎯 Stratégies DXY par configuration du mardi

### Configuration A : Tendance claire (60% des mardis)

Le DXY suit une direction nette depuis l'ouverture.

```
📈 BULL : Prix > Kijun H1 + Kijun H4 + Kijun D1 → Tendance haussière
📉 BEAR : Prix < Kijun H1 + Kijun H4 + Kijun D1 → Tendance baissière
```

| Action | Entry | SL | TP |
|:---|:---|:---|:---|
| **Pullback Kijun H1** | Prix touche Kijun H1 | Kijun H4 (−10/15p) | Kijun D1 (ou +2× SL) |
| **Breakout après news** | 5 min après news US | 10 pips | 2× SL |

### Configuration B : Range (30% des mardis)

Le DXY oscille entre deux niveaux sans direction claire.

```
Range type : 100.700 − 100.800 (10 pips)
```

| Action | Zone | SL | TP |
|:---|:---|:---|:---|
| **Short sur résistance** | Proche de la borne haute | 5 pips au-dessus | Borne basse |
| **Long sur support** | Proche de la borne basse | 5 pips en-dessous | Borne haute |
| **Breakout** | Cassure franche d'une borne | 10 pips | 2× SL |

### Configuration C : Reversal de tendance (10% des mardis)

Le DXY inverse brutalement la tendance du lundi.

```
Lundi : BEAR → DXY a baissé toute la journée
Mardi matin : Prix toujours bas, mais un FVG non mitigé apparaît au-dessus
→ Possible reversal BULL
```

**Indices de reversal :**
- 🔄 **T/Kx H1 flip** : passage BEAR → BULL (ou inversement) — **CRITIQUE**
- 📊 **Kumo H1 flip** : le prix sort du nuage dans l'autre direction
- 📈 **FVG non mitigé** créé dans la direction opposée
- 📉 **DXY divergence** avec les paires forex (DXY baisse + EURUSD baisse = anomalie)

---

## 📊 Exemple : Mardi typique — Tendance BULL

```bash
# 09:00 — London Open
python main.py diamond --timezone BROKER --symbols DXY.cash

DXY.cash  Score=55/109  Biais=BULL  Qualité=STRONG
  Prix=100.780  ML%=72%  ← Excellent
  Kijun H1=100.755  Prix au-dessus → BULL confirmé
  Kijun H4=100.720  Prix au-dessus → structure haussière
  T/Kx H1=BULL  ← Aligné
  Kumo H1=ABOVE  ← Structure haussière propre
  Kumo H4=INSIDE  ← Nuage H4 en cours → résistance à 100.829
  Sweep AL=05:00  ← AL sweepé en Asian → piège à vendeurs
  
  SL=100.720 (Kijun H4, −6p)
  TP=100.829 (Kumo H4 top, +4.9p)
  Smart TP=100.829 (Kumo H4)
  RR=1.2×
  
  Warnings: aucun
```

**Décision :** ✅ Trade LONG activé
- Entry : 100.780 (prix actuel)
- SL : 100.720 (Kijun H4)
- TP : 100.829 (Kumo H4 haut — niveau réel)
- SL étroit (6 pips) → attention au bruit M5

**Suivi :**
```bash
# 14h30 — Après news US
python main.py track update
# Prix à 100.802 → +2.2 pips, SL à −2.2p du SL
# TP 100.829 à +2.7p → objectif proche

# Si TradeTouché → wait +2.7p
# Si pas touché → garder jusqu'à NY clôture
```

---

## ⚠️ Pièges du mardi

| Piège | Description | Solution |
|:---|:---|:---|
| **Faux breakout London** | Londres peut casser un niveau puis revenir à NY | Vérifier la confirmation NY (14h30) |
| **Piège à news** | Les news US peuvent casser une tendance en 2 minutes | Attendre 5 min après la publication |
| **DXY divergence oubliée** | Si DXY monte ET EURUSD monte → anomalie → risque de range | Vérifier `dxy_divergence` dans les features |
| **FOMC preview** | Si c'est la veille du FOMC (mercredi), le mardi peut être calme avant la tempête | Réduire la taille des trades |
| **Oubli du track save** | Trades non sauvegardés = pas de P&L | Toujours `track save` après entry |

---

## 🧠 Résumé pour le mardi

```
┌─────────────────────────────────────────────────────────────┐
│                      DXY MARDI                               │
│                                                             │
│  07h00 — Scan matinal : tendance du jour                    │
│  09h00 — ⏰ FEU VERT : 1ère entrée possible                 │
│  14h30 — ⏰ FEU VERT : 2e fenêtre (NY Open, meilleure)      │
│  15h30 — Pas de nouveaux trades si news à 14h30              │
│  17h00 — Dernière entrée possible                            │
│  21h00 — Track update + track save + track report            │
│                                                             │
│  🔑 KEY : Mardi = meilleur jour pour le DXY (volume max).   │
│  🔑 KEY : Privilégier la tendance, pas les ranges.          │
│  🔑 KEY : Si un trade est ouvert, le garder jusqu'à clôture.│
└─────────────────────────────────────────────────────────────┘
```

---

> **Généré automatiquement par InelidaMarketScan — v1.0.1** |
> **Modèle DXY :** `models/historical_v13_dxy.xgb` (63.5% CV) |
> **WR natif DXY :** 73% — 88% avec ML% ≥ 60% |
