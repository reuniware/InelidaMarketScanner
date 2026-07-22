# 💵 DXY.MERCREDI — Guide de trading du Dollar Index (Mercredi — FOMC)

> **⚠️ RÈGLE SPÉCIALE MERCREDI :** Le mercredi est le jour du **FOMC** (Federal Open Market Committee).
> Le DXY peut se retourner de 100 pips en 10 minutes. Le système affiche automatiquement
> le warning `FOMC WEDNESDAY: volatilite elevee`.
>
> **Ne tradez JAMAIS pendant la publication du FOMC (19h-20h Paris / 18h-19h UTC).**
> Attendez 30 minutes après la publication pour entrer.

---

## 📅 Contexte du mercredi

| Facteur | Détail |
|:---|:---|
| **Événement clé** | **FOMC Statement à 19h Paris (18h UTC)** — décision de taux US |
| **Session clé** | NY Open (14h30) → FOMC (19h) |
| **Volume** | **Maximum de la semaine** — les institutions se positionnent avant/après FOMC |
| **Volatilité** | Très élevée — spreads ×2 à ×3 pendant le FOMC |
| **Typologie** | Range avant FOMC → explosion directionnelle après |
| **ML DXY** | `day_wednesday` = feature #6 du modèle (gain=6.4) — le FOMC change tout |
| **Taux de réussite** | 73% natif, mais **tous les trades BULL sont downgradés** (Correctif P0) |

---

## ⏱️ Chronologie mercredi

| Heure Paris | Heure UTC | Événement | Action |
|:---|:---|:---|:---|
| 07:00 | 05:00 | Fin Asian | ✅ Scan matinal — range pré-FOMC |
| 09:00 | 07:00 | Ouverture Londres | ✅ Scan Diamond possible (attention au FOMC) |
| **14:30** | **12:30** | **NY Open** | ✅ **Dernière fenêtre AVANT FOMC** |
| 14:30-18:00 | 12:30-17:00 | Pré-FOMC | 🟡 Réduire la taille des trades de 50% |
| **18:30** | **17:30** | **⛔ BLACKOUT** | ❌ **NE PAS TRADER** — 30 min avant FOMC |
| **19:00** | **18:00** | **📊 FOMC STATEMENT** | ❌ **VOLATILITÉ MAX** — attendre ! |
| **19:30** | **18:30** | **🎤 FOMC Press Conference** | ❌ Powell parle encore — attendre ! |
| **20:00** | **19:00** | **Post-FOMC** | ✅ **FEU VERT** — la tendance post-FOMC est claire |
| 21:00 | 20:00 | Clôture | ✅ Trade possible jusqu'à clôture |
| 22:00 | 21:00 | Fin de session | ✅ Track update + track report |

---

## 🚀 Workflow mercredi — Pas à pas

### 1. Scan matinal (07h)

```bash
python main.py diamond --timezone BROKER --symbols DXY.cash
```

**Vérifier :**
- ✅ Le `FOMC WEDNESDAY` warning est-il affiché ? (Normal, oui)
- ✅ Le `HIGH NEWS DAY` warning est-il présent ? (Si oui, + de précautions)
- ✅ Le DXY est-il en range ou en tendance ?

### 2. Pré-FOMC (09h-18h) — Trades réduits

```bash
python main.py diamond --timezone BROKER --symbols DXY.cash
python main.py track save
```

**Règles pré-FOMC :**

| Règle | Appliquer |
|:---|:---|
| **Taille des trades** | 50% de la taille normale |
| **New trades après 16h** | ❌ NON — trop proche du FOMC |
| **SL large** | 2× le SL normal (volatilité accrue) |
| **HIGH NEWS DAY BULL** | Déjà downgradé par le système |

**⚠️ Le correctif P0 s'applique automatiquement :**
- Si BULL → qualité downgradée (STRONG→GOOD, GOOD→WAIT)
- Si BEAR → pas de downgrade (privilégier les shorts)

### 3. ❌ BLACKOUT FOMC (18h30-19h30)

```python
# Aucun trade. Même si le DXY fait un mouvement XXL.
# Les spreads sont ×3, les slippages sont violents.
# Les ordres peuvent être exécutés à 50 pips du prix demandé.
```

### 4. Post-FOMC (20h-22h) — La VRAIE session de trading

```bash
# Attendre 30 min après le FOMC pour que le marché se calme
python main.py diamond --timezone BROKER --symbols DXY.cash
```

**Après 30 min, analyser :**

| Signal | Interprétation | Action |
|:---|:---|:---|
| **DXY flèche UP** + Kijun H1 cassé | FOMC haussier (hawkish) | LONG si retracement Kijun |
| **DXY flèche DOWN** + Kijun H1 cassé | FOMC baissier (dovish) | SHORT si retest résistance |
| **DXY + EURUSD UP** | Anomalie → range post-FOMC probable | Attendre |
| **DXY - EURUSD UP** | Corrélation normale → tendance propre | Trade directionnel |

**🎯 Stratégie post-FOMC gagnante :**

```
ENTRÉE : 30 min après le FOMC
  → Le prix a fait son spike, le vrai mouvement commence
  
CONFIRMATION :
  → T/Kx H1 aligné avec la direction post-FOMC
  → Kijun H4 dans la même direction
  → ML% ≥ 50%
  
SORTIE :
  → TP = Kijun D1 (objectif lointain, 2-3 jours)
  → Ou fermeture à la clôture du mercredi si déjà +20 pips
```

---

## 🎯 Stratégies DXY par résultat FOMC

### Résultat A : FOMC Hawkish (DXY UP)

```
Le FOMC maintient ou augmente les taux → dollar fort
```

| Niveau | Prix attendu | Action |
|:---|:---|:---|
| Prix actuel | 100.820 | — |
| Entry post-spike | 100.800 (pullback Kijun H1) | LONG |
| SL | 100.720 (Kijun H4, −8p) | 🛡️ |
| TP1 | 100.900 (psychologique) | +10p |
| TP2 | 101.050 (Kijun W1) | +25p |

### Résultat B : FOMC Dovish (DXY DOWN)

```
Le FOMC baisse les taux ou signale une baisse → dollar faible
```

| Niveau | Prix attendu | Action |
|:---|:---|:---|
| Prix actuel | 100.820 | — |
| Entry post-spike | 100.840 (retest Kijun H1) | SHORT |
| SL | 100.900 (psychologique +10p) | 🛡️ |
| TP1 | 100.720 (Kijun H4) | −12p |
| TP2 | 100.588 (Kijun D1) | −25p |

### Résultat C : FOMC Neutre → Range (20% des cas)

```
Le FOMC ne change rien, discours équilibré → le DXY reste en range
```

→ **Ne pas trader.** Le range peut durer 24-48h. Attendre jeudi.

---

## 📊 Exemple : Mercredi FOMC Dovish

```bash
# 09:00 — Scan matinal
DXY.cash  Score=40/109  Biais=BEAR  Qualité=WAIT
  Prix=100.740  ML%=45%
  Warning: FOMC WEDNESDAY
  → BULL downgraded, BEAR OK mais WAIT
  
# 14h30 — Pré-FOMC
DXY.cash  Score=44/109  Biais=BEAR  Qualité=GOOD
  Prix=100.735  ML%=52%
  T/Kx H1=BEAR ← Aligné
  Kijun H4=100.720  Prix à 100.735 → au-dessus
  → Risqué à 4h du FOMC → attendre

# 20h00 — POST-FOMC 30min
# FOMC dovish → DXY spike down puis pullback
DXY.cash  Score=55/109  Biais=BEAR  Qualité=STRONG
  Prix=100.750  ML%=68%  ← Amélioration nette
  T/Kx H1=BEAR ← Flipé BEAR après FOMC
  Kijun H4=100.720  Prix à +3p → gap à combler
  FVG H1 non mitigé en dessous
  
  SL=100.790 (+4p, serré mais volatilité OK)
  TP=100.680 (FVG H1, −7p)
  RR=1.75×
  
  Warning: FOMC WEDNESDAY (attendu, OK)
```

**Décision :** ✅ Trade SHORT post-FOMC
- Entry : 100.750
- SL : 100.790
- TP : 100.680 (FVG H1)
- Suivi serré : TP touché en 2h → +7 pips en soirée

---

## ⚠️ Pièges du mercredi (FOMC)

| Piège | Description | Solution |
|:---|:---|:---|
| **Spike FOMC** | Mouvement de 30 pips en 10 secondes | Ne PAS trader pendant la publication |
| **Fake-out post-FOMC** | Le DXY fait un premier mouvement, puis l'inverse | Attendre 30 min après le FOMC |
| **Slipage SL** | Pendant le FOMC, les SL peuvent être dépassés de 10-20 pips | SL large ou pas de trade |
| **Spread ×3** | Le spread DXY peut passer de 1 pip à 3 pips | Vérifier le spread avant d'entrer |
| **BULL downgradé** | Le système downgrade BULL, mais BEAR peut aussi être risqué | Pas de BULL. BEAR uniquement avec ML% ≥ 60% |
| **Réouverture jeudi** | Parfois le DXY gap à l'ouverture jeudi | Fermer les trades mercredi si profit > 10 pips |

---

## 🧠 Résumé pour le mercredi

```
┌─────────────────────────────────────────────────────────────┐
│                      DXY MERCREDI (FOMC)                    │
│                                                             │
│  07h00 — Scan matinal (range pré-FOMC)                      │
│  09h00 — ⏰ FEU VERT (trades réduits de 50%)                │
│  14h30 — Dernière entrée AVANT FOMC                         │
│  18h30 — ⛔ BLACKOUT — + de trades                          │
│  19h00 — 📊 FOMC — ne pas trader                            │
│  20h00 — ⏰ FEU VERT post-FOMC — trade possible             │
│  22h00 — Clôture + track save                               │
│                                                             │
│  🔑 KEY : BLACKOUT obligatoire 30 min avant/après FOMC.     │
│  🔑 KEY : Le FOMC détermine la tendance des 3 prochains     │
│           jours. Le trade post-FOMC est le + important de    │
│           la semaine.                                        │
│  🔑 KEY : BULL downgradé automatiquement → privilégier BEAR.│
└─────────────────────────────────────────────────────────────┘
```

---

> **Généré automatiquement par InelidaMarketScan — v1.0.1** |
> **Modèle DXY :** `models/historical_v13_dxy.xgb` (63.5% CV) |
> **Feature #6 : `day_wednesday` (gain=6.4)** — le FOMC est intégré dans le modèle |

---

> **Reuniware Systems** — InelidaMarketScan
