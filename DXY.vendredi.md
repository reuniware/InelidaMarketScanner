# 💵 DXY.VENDREDI — Guide de trading du Dollar Index (Vendredi)

> **⚠️ RÈGLE SPÉCIALE VENDREDI :** Le vendredi est le **jour le plus dangereux** pour le DXY.
> Le risque de **gap weekend** est maximal. Tous les trades doivent être fermés avant 18h CET.
> **Aucun trade maintenu ouvert pendant le week-end.**

---

## 📅 Contexte du vendredi

| Facteur | Détail |
|:---|:---|
| **Session clé** | London (09h) → NY Mid (17h) — **rien après** |
| **Volume** | **Élevé jusqu'à 17h**, puis s'effondre brutalement |
| **Typologie** | Jour de clôture — les positions sont soldées |
| **Pire moment** | **Vendredi 18h+** → pas de liquidité, spreads ×5, gap imminent |
| **News** | Possible (rare) — jamais de FOMC le vendredi |
| **Tendance** | **Reversal** fréquent (profit-taking) vs **continuation** |
| **ML DXY** | WR 73% mais **bruit plus élevé** — ML% ≥ 55% recommandé |

---

## ⏱️ Chronologie vendredi

| Heure Paris | Heure UTC | Événement | Action |
|:---|:---|:---|:---|
| 07:00 | 05:00 | Fin Asian | ✅ Dernier scan matinal de la semaine |
| **09:00** | **07:00** | **Ouverture Londres** | ✅ **FEU VERT** — dernière vraie entrée possible |
| 11:00 | 09:00 | Profit-taking possible | 🟡 Les bullish de la semaine vendent |
| **14:30** | **12:30** | **NY Open** | ✅ **DERNIÈRE fenêtre de trading** |
| 14:30 | 12:30 | News US possibles | Impact modéré |
| **16:00** | **14:00** | ⚠️ **DÉBUT FERMETURE** | ❌ Plus de nouveaux trades |
| **17:00** | **15:00** | **⛔ STOP** | ❌ **Forcer la fermeture de TOUS les trades** |
| 17:30 | 15:30 | NY PM | Spreads augmentent |
| 21:00 | 19:00 | Clôture NY | Marché fermé pour le week-end |
| 22:00 | 20:00 | **TRACK REPORT HEBDOMADAIRE** | ✅ Bilan complet de la semaine |

---

## 🚀 Workflow vendredi — Pas à pas

### 1. Scan matinal (07h) — Dernière analyse

```bash
python main.py diamond --timezone BROKER --symbols DXY.cash
python main.py track update
```

**Ce qu'on analyse :**
- ✅ Le P&L de la semaine → `python main.py track report`
- ✅ Les trades ouverts → combien sont en profit ?
- ✅ La tendance de la semaine → continuation ou exhaustion ?
- ✅ Le DXY est-il proche d'un niveau D1 clé ?

### 2. London Open (09h) — Fenêtre d'entrée

```bash
python main.py diamond --timezone BROKER --symbols DXY.cash
```

**⚠️ Vendredi = jour de profit-taking.**
Les traders qui sont LONG depuis mardi commencent à vendre pour sécuriser leurs gains.
=> Les breakouts haussiers le vendredi sont **moins fiables** qu'en début de semaine.

| Type de trade | Vendredi matin | Verdict |
|:---|:---|:---:|
| **Continuation** | Possible si tendance très forte | 🟡 OK mais SL serré |
| **Reversal** | Plus probable (profit-taking) | ✅ Privilégier |
| **Breakout** | À éviter (fausses cassures fréquentes) | ❌ |
| **Range trade** | OK si range clair | ✅ |

### 3. ⚠️ NY Open (14h30) — Dernière fenêtre

```bash
python main.py diamond --timezone BROKER --symbols DXY.cash
```

**🚨 Dernière entrée possible à 14h30 avant la fermeture de 16h.**

Si un setup STRONG apparaît :
- Entrer à 14h30
- SL normal (Kijun H4)
- TP **serré** (1.5× SL max, pas plus)
- **Fermer avant 17h** quoi qu'il arrive

### 4. ⛔ 16h — FERMETURE OBLIGATOIRE

```bash
# 1. Vérifier tous les trades ouverts
python main.py track report

# 2. Fermeture manuelle si trades encore ouverts
python main.py track close --id <ID> --reason "Cloture weekend"

# 3. Track save final
python main.py track save

# 4. Rapport hebdomadaire
python main.py track report
```

**Règle ABSOLUE :**

```python
# Aucun trade ne doit traverser le week-end.
# Raisons :
#   - Gap de 50+ pips possible le lundi
#   - News macro du week-end (Trump, conflits, etc.)
#   - Pas de SL garanti sur le gap
#   
# Si le trade est gagnant → fermer. Un gain pris vaut mieux qu'un gap perdu.
# Si le trade est perdant → fermer. 10 pips de perte valent mieux qu'un gap de 50.
```

---

## 🎯 Stratégies DXY vendredi

### Configuration A : Profit-taking (40% des vendredis)

Les traders LONG de la semaine vendent massivement.

```
DXY a bullé de 100.700 à 100.850 (+15 pips) cette semaine
Vendredi 09h → DXY redescend à 100.780
```

| Action | Zone | SL | TP | RR |
|:---|:---|:---|:---|:---:|
| SHORT sur résistance | 100.810-100.830 (H1 Kijun) | 100.850 (+4p) | 100.720 (−9p) | 2.2× |

### Configuration B : Continuation (30% des vendredis)

La tendance est tellement forte que même le vendredi continue.

```
DXY a bullé toute la semaine, aucun signe d'épuisement
ML% ≥ 60%, T/Kx H1 aligné, pas de résistance D1 proche
```

| Action | Entry | SL | TP | RR |
|:---|:---|:---|:---|:---:|
| LONG continuation | Pullback Kijun H1 | Kijun H4 | 1.5× SL max | 1.5× |

### Configuration C : Range de clôture (30% des vendredis)

Le DXY se stabilise pour le week-end.

```
Range serré : 100.740 − 100.770 (3 pips)
```

→ **Ne pas trader.** Le range est trop serré, le mouvement du lundi mangera
certainement les 3 pips de gain potentiel.

---

## 📊 Exemple : Vendredi — Profit-taking

```bash
# 09:00 — London Open
python main.py diamond --timezone BROKER --symbols DXY.cash

# Contexte : DXY a bullé de lundi à jeudi (+25 pips)
DXY.cash  Score=48/109  Biais=BEAR  Qualité=GOOD
  Prix=100.750  ML%=58%  ← Acceptable
  Kijun H1=100.760  Prix en-dessous → BEAR
  T/Kx H1=BEAR  ← Aligné
  Kumo H1=BELOW  ← Sous le nuage
  Kijun H4=100.720  Support en dessous
  
  SL=100.790 (Kijun H1 +4p, SL serré)
  TP=100.720 (Kijun H4, −3p)
  RR=1.3×  ← Faible
  
  Warnings: aucun
```

**Décision :** ⚠️ Short possible mais RR faible
- Entry : 100.750
- SL : 100.790
- TP : 100.720
- **Fermeture avant 16h impérative**

**Suivi :**
```bash
# 14h30 — NY Open
python main.py track update
# Prix à 100.740 → +1 pip, tendance OK mais lente

# 16h00 — FERMETURE
# Prix à 100.735 → +1.5 pips, TP pas touché
# FORCER LA FERMETURE
python main.py track close --id 1 --reason "Cloture weekend +1.5p"
# Résultat : +1.5 pip, petit gain mais pas d'exposition weekend
```

### ✅ Meilleur trade du vendredi : fermer en profit

| Scénario | Décision | Résultat |
|:---|:---|:---|
| Trade gagnant (+5 pips) | Fermer | ✅ +5 pips sécurisés |
| Trade gagnant (+15 pips) | Fermer | ✅ +15 pips — belle semaine |
| Trade perdant (−3 pips) | Fermer | ✅ −3 pips — acceptable |
| Trade PERDANT (−3 pips) | GARDER pour lundi | ❌ Gap weekend de −25 pips → −28 pips |

---

## 📊 Rapport hebdomadaire (vendredi 22h)

```bash
python main.py track report
```

**Ce que tu dois voir :**

```
═══════════════════════════════════════════════
  RAPPORT HEBDOMADAIRE — DXY.cash
═══════════════════════════════════════════════
  Trades ouverts : 0 ✅  (rien ouvert le weekend)
  
  PERFORMANCE DE LA SEMAINE :
    Total trades  : 5
    Gagnants      : 3 (60.0%)
    Perdants      : 2 (40.0%)
    P&L total     : +18.2 pips
    Profit Factor : 1.85
    Win Rate      : 60%
    Suivi ML%     : ⌀ 64% sur les trades gagnants
```

**Si WR < 55% cette semaine :**
→ Ré-entraîner le modèle : `streamlit run app_ml.py` → onglet Training
→ Vérifier que les features sont toujours pertinentes

**Si PF < 1.0 cette semaine :**
→ Revoir la stratégie : trop de trades ? Pas assez filtrés ?
→ Augmenter le seuil ML% de 50% à 55% la semaine prochaine

---

## ⚠️ Pièges du vendredi

| Piège | Description | Solution |
|:---|:---|:---|
| **Gap weekend** | Le + grand risque. 50+ pips possibles | TOUS les trades fermés avant 17h |
| **Profit-taking** | Les bulls de la semaine vendent → fake breakout haussier | Privilégier les SHORTs le vendredi |
| **Volume qui chute** | Après 17h, plus de liquidité | Pas de trade après 16h |
| **News du weekend** | Trump tweet, conflit géopolitique, etc. | Pas d'exposition |
| **Faux espoir lundi** | Un trade laissé ouvert pourrait être gagnant... ou gapé à −50 pips | Fermer. Toujours. |
| **Oubli track report** | Pas de bilan hebdo = pas de visibilité sur sa performance | Track report obligatoire vendredi soir |

---

## 🧠 Résumé pour le vendredi

```
┌─────────────────────────────────────────────────────────────┐
│                      DXY VENDREDI                            │
│                                                             │
│  07h00 — Scan matinal + track update                        │
│  09h00 — ⏰ FEU VERT : dernière vraie entrée possible        │
│  14h30 — ⏰ DERNIÈRE fenêtre (SL serré, TP court)            │
│  16h00 — ⛔ STOP : fermer TOUS les trades                   │
│  17h00 — ❌ Plus de trading — spreads trop larges             │
│  22h00 — ✅ TRACK REPORT HEBDOMADAIRE                         │
│                                                             │
│  🔑 KEY : Aucun trade ouvert le week-end. JAMAIS.           │
│  🔑 KEY : Privilégier les reversals (profit-taking).        │
│  🔑 KEY : ML% ≥ 55% recommandé (pas 50%).                   │
│  🔑 KEY : Track report obligatoire le vendredi soir.         │
└─────────────────────────────────────────────────────────────┘
```

---

## 📋 Checklist hebdomadaire (vendredi soir)

- [ ] **Track report** généré → vérifier WR + PF de la semaine
- [ ] **Tous les trades fermés** → 0 position ouverte pour le weekend
- [ ] **Diamond scan final** → comparer les niveaux annoncés lundi vs réalisés
- [ ] **Si WR < 55%** → ré-entraîner le modèle ML
- [ ] **GUIDE_UTILISATEUR.md** mis à jour si besoin
- [ ] **Mise à jour** `weekend_watchlist_{date}.md` avec les niveaux de la semaine prochaine
- [ ] **Préparation lundi matin** : quels niveaux surveiller ? (D1, W1)

---

> **Généré automatiquement par InelidaMarketScan — v1.0.1** |
> **Modèle DXY :** `models/historical_v13_dxy.xgb` (63.5% CV) |
> **Règle absolue :** TOUS les trades fermés avant 17h le vendredi. |

---

> **Didier Vally / Reuniware Systems** — InelidaMarketScan
