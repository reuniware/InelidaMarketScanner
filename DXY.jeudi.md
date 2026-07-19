# 💵 DXY.JEUDI — Guide de trading du Dollar Index (Jeudi)

> **Règle d'or :** Le jeudi est le jour de **continuation post-FOMC.** La tendance initiée
> le mercredi soir se prolonge généralement avec un volume normal (plus de blackout).
> C'est le deuxième meilleur jour pour le DXY après le mardi.

---

## 📅 Contexte du jeudi

| Facteur | Détail |
|:---|:---|
| **Contexte** | Post-FOMC — digestion des décisions de taux |
| **Session clé** | NY Open (14h30) + London (09h) |
| **Volume** | Élevé — les institutions positionnent pour le week-end |
| **Typologie** | **Continuation** dans 65% des cas (après FOMC) |
| **News** | Jobless Claims (14h30), Philly Fed, Existing Home Sales |
| **ML DXY** | 73% WR natif — tendance claire après FOMC |
| **Risque** | Gap weekend dans 24h — pas de nouveaux trades après 17h |

---

## ⏱️ Chronologie jeudi

| Heure Paris | Heure UTC | Événement | Action |
|:---|:---|:---|:---|
| 07:00 | 05:00 | Fin Asian | ✅ Scan matinal — ouverture post-FOMC analysée |
| 09:00 | 07:00 | Ouverture Londres | ✅ **FEU VERT** — 1ère entrée |
| **14:30** | **12:30** | **News US + NY Open** | 🚀 **Volume max** — meilleure fenêtre |
| 14:30 | 12:30 | Unemployment Claims | Impact élevé sur DXY |
| 15:00 | 13:00 | Philly Fed Manufacturing | Impact moyen |
| 16:00 | 14:00 | Post-news digestion | ✅ 2e fenêtre |
| **17:00** | **15:00** | ⏰ **DERNIÈRE ENTRÉE** | ❌ Plus de nouveaux trades |
| 17:00-21:00 | 15:00-19:00 | Suivi des trades | 🟡 Fermeture avant weekend si +10 pips |
| 21:00 | 19:00 | Clôture NY | ✅ Track update + track save |

---

## 🚀 Workflow jeudi — Pas à pas

### 1. Scan matinal (07h) — Analyse post-FOMC

```bash
python main.py diamond --timezone BROKER --symbols DXY.cash
python main.py track update
```

**Checklist matin :**
- ✅ Quelle est la direction post-FOMC ? (Hawkish = BULL, Dovish = BEAR)
- ✅ Le DXY a-t-il déjà parcouru 50% de son objectif D1 ?
- ✅ Y a-t-il un gap à l'ouverture ? (possible si mercredi volatil)
- ✅ Le ML% confirme-t-il la direction attendue ?

**⚠️ Gap jeudi matin :**
```
Si DXY a fait un spike FOMC violent et que le prix a gappé à l'ouverture :
→ Attendre 30 min pour voir si le gap se comble
→ Si comblement → trade dans la direction du FOMC
→ Si pas de comblement → éviter (mouvement déjà fait)
```

### 2. London Open (09h) — Trade de continuation

```bash
python main.py diamond --timezone BROKER --symbols DXY.cash
```

**Stratégie de continuation :**

```
Le FOMC a donné la direction (ex: haussière).

Entry : Pullback sur Kijun H1
SL    : Kijun H4
TP    : Kijun D1 (ou 2× SL)

Exemple :
  Prix = 100.820  Kijun H1 = 100.800
  Kijun H4 = 100.720  Kijun D1 = 100.588
  
  LONG entry = 100.800 (sur pullback)
  SL = 100.720 (−8 pips)
  TP1 = 100.900 (+10 pips)
  TP2 = 101.050 (+25 pips)
```

### 3. NY Open + News (14h30) — Fenêtre principale

```bash
# Avant les news
python main.py diamond --timezone BROKER --symbols DXY.cash

# Les news US (Claims, Philly Fed) sont publiées à 14h30
# Attendre 5 min après la publication pour entrer
```

**🎯 La meilleure stratégie du jeudi :**

```
14h30 — Unemployment Claims
  → Si DXY réagit haussier → LONG après pullback
  → Si DXY réagit baissier → SHORT après retest
  
15h30 — Post-news
  → La tendance initiale (pré-news) reprend dans 70% des cas
  → Si le DXY était BULL avant 14h30 → racheter la baisse des news
```

### 4. ⏰ Dernière entrée à 17h (limite)

```bash
python main.py track save
```

**Après 17h, plus de nouveaux trades — raisons :**
1. **Gap weekend** dans 24h → risque de SL franchi
2. **Volume réduit** après 18h → spreads plus larges
3. **Positionnement weekend** → mouvements erratiques

---

## 🎯 Stratégies DXY jeudi

### Configuration A : Continuation post-FOMC (65%)

Le DXY suit la direction du FOMC de la veille.

```
Mercredi FOMC Hawkish → DXY UP
Jeudi → Continuer LONG
```

| Fenêtre | Entry | SL | TP | RR |
|:---|:---|:---|:---|:---:|
| 09h London | Pullback Kijun H1 | Kijun H4 | Kijun D1 | 2.0× |
| 14h30 NY Open | 5 min après news | Kijun H4 +5p | Kijun D1 | 1.5× |

### Configuration B : Range jeudi (25%)

Le DXY hésite, les volumes sont moyens.

```
Range : 100.720 − 100.800 (8 pips)
```

| Action | Zone | SL | TP |
|:---|:---|:---|:---|
| **Range trade** | Bornes du range | 5p de l'autre côté | Borne opposée |
| **Breakout** | Cassure ≥ 10p | Range opposé | 2× SL |

### Configuration C : Reversal (10%)

Le DXY inverse la tendance post-FOMC.

```
FOMC Hawkish → DXY UP mercredi
Jeudi 09h → DXY redescend sous Kijun H1
```

🔴 **Reversal confirmé si :**
- T/Kx H1 flip dans le sens du reversal
- FVG créé dans la direction du reversal
- ML% ≥ 50% pour la nouvelle direction

---

## 📊 Exemple : Jeudi de continuation

```bash
# 09:00 — London Open
python main.py diamond --timezone BROKER --symbols DXY.cash

# Contexte : FOMC Hawkish hier → DXY up
DXY.cash  Score=58/109  Biais=BULL  Qualité=STRONG
  Prix=100.825  ML%=71%  ← Excellent (≥ 50%)
  Kijun H1=100.810  Prix au-dessus → BULL confirmé
  Kijun H4=100.780  Prix au-dessus → structure haussière
  Kijun D1=100.588  Support structurel lointain
  T/Kx H1=BULL  ← Aligné
  Kumo H1=ABOVE  ← Nuage haussier
  Kumo H4=INSIDE  ← En cours de cassure
  
  SL=100.780 (Kijun H4, −4.5p)
  TP1=100.850 (+2.5p)  → RR insuffisant
  TP2=100.900 (+7.5p, Kijun D1) → RR=1.66×
  
  Warnings: aucun (FOMC digéré)
```

**Décision :** ✅ Trade LONG
- Entry : 100.825 (prix actuel)
- SL : 100.780 (Kijun H4)
- TP2 : 100.900 (Kijun D1)
- Suivi : Si TP1 touché → déplacer SL au point mort

**Suivi :**
```bash
# 14h30 — Unemployment Claims
# DXY spike down sur les news → 100.810
# Pas de SL touché → rester en trade

# 16h00 — Post-news
# DXY remonte à 100.835 → TP1 touché, SL au point mort
# Nouveau statut : trade gratuit

# 17h00 — Fermeture
python main.py track save
# Trade toujours ouvert, SL au point mort
# Risque 0 → garder jusqu'à vendredi
```

---

## ⚠️ Pièges du jeudi

| Piège | Description | Solution |
|:---|:---|:---|
| **Gap jeudi matin** | Après un FOMC violent, gap de 10-20 pips possible | Attendre 30 min avant d'entrer |
| **News Claims** | Les chiffres des Claims peuvent contredire la tendance post-FOMC | Attendre 5 min après news |
| **Volume faiblissant après 17h** | Moins de liquidité = spreads plus larges | Pas de nouveaux trades après 17h |
| **Positionnement weekend** | Les institutions ferment leurs positions pour le week-end | Trades existants à sécuriser |
| **Oubli track save** | Les trades du jeudi sont importants pour le P&L hebdo | Toujours sauvegarder après entry |

---

## 🧠 Résumé pour le jeudi

```
┌─────────────────────────────────────────────────────────────┐
│                      DXY JEUDI                               │
│                                                             │
│  07h00 — Scan post-FOMC : direction confirmée               │
│  09h00 — ⏰ FEU VERT : trade de continuation                 │
│  14h30 — ⏰ FEU VERT : fenêtre NY Open + news               │
│  17h00 — ⛔ Dernière entrée (risque gap weekend)             │
│  21h00 — Track update + track save                           │
│                                                             │
│  🔑 KEY : Le jeudi continue la tendance post-FOMC.           │
│  🔑 KEY : Unemployment Claims à 14h30 = meilleur catalyseur. │
│  🔑 KEY : Pas de nouveaux trades après 17h (gap weekend).    │
└─────────────────────────────────────────────────────────────┘
```

---

> **Généré automatiquement par InelidaMarketScan — v1.0.1** |
> **Modèle DXY :** `models/historical_v13_dxy.xgb` (63.5% CV) |
> **WR natif :** 73% — 2e meilleur jour après le mardi |

---

> **Didier Vally / Reuniware Systems** — InelidaMarketScan
