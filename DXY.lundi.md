# 💵 DXY.LUNDI — Guide de trading du Dollar Index (Lundi)

> **Règle d'or :** Le lundi, le marché est en phase de **découverte de prix** après le week-end.
> Les gaps de Sydney/Tokyo sont souvent piégés. **Ne pas trader avant Londres (09h Paris).**

---

## 📅 Contexte du lundi

| Facteur | Détail |
|:---|:---|
| **Session clé** | London Open (09h Paris / 08h UTC) → NY Open (14h30 Paris) |
| **Volume** | Faible jusqu'à 09h, max à 14h30-17h |
| **Gaps** | Possibles à l'ouverture Sydney (00h Paris) — souvent comblés avant Londres |
| **Typologie** | Jour de range : les institutions positionnent leurs niveaux pour la semaine |
| **ML DXY** | Le modèle per-asset DXY (v13) a un **CV de 63.5%** et un **WR natif de 73%** |

---

## ⏱️ Chronologie lundi

| Heure Paris | Heure UTC | Événement | Action |
|:---|:---|:---|:---|
| 00:00 | 22:00 dim | Ouverture Sydney | 🟡 Surveiller les gaps, NE PAS TRADER |
| 03:00 | 01:00 | Ouverture Tokyo | 🟡 Range asiatique commence à se former |
| **07:00** | **05:00** | **Fin Asian M5** | ✅ **1er scan possible** — range asiatique établi |
| **09:00** | **07:00** | **Ouverture Londres** | ✅ **FEU VERT** — liquidité réelle, début des trades |
| 09:00 | 07:00 | Scan Diamond complet | `python main.py diamond --timezone BROKER` |
| **14:30** | **12:30** | **Ouverture NY** | ✅ Volume max — les news US tombent |
| 15:30 | 13:30 | News US possibles | Retarder les entrées si High Impact attendu |
| 17:00 | 15:00 | NY Mid | Fin de la fenêtre de trade idéale |
| 21:00 | 19:00 | Clôture NY | ✅ Track update + track report |
| 22:00 | 20:00 | Fin de session | ✅ Clôture des trades ou SL → fermeture weekend |

---

## 🚀 Workflow lundi — Pas à pas

### 1. Avant l'ouverture (07h Paris — fin Asian)

```bash
# Scan Asian pour voir les ranges de la nuit
python main.py asian --timezone BROKER --symbols DXY.cash

# Vérifier les sweeps AH/AL asiatiques
python main.py asian --scan-all --swept-only --timezone BROKER
```

**Ce qu'on regarde :**
- ✅ Le DXY a-t-il créé un range serré (< 10 pips) ? → Breakout probable
- ✅ Le DXY a-t-il déjà gappé ? → Attendre le comblement
- ✅ Les paires forex (EURUSD, GBPUSD) ont-elles des ranges cohérents ?

### 2. Ouverture Londres (09h Paris) — Scan Diamond

```bash
python main.py diamond --timezone BROKER --symbols DXY.cash
```

**Checklist visuelle :**

| Colonne | Vert | Rouge | Action |
|:---|:---|:---|:---|
| **ML%** | ≥ 50% | < 50% | Ne pas trader |
| **Bias** | BULL ou BEAR | FLAT | Attendre |
| **Quality** | STRONG ou GOOD | WAIT | Ne pas trader |
| **T/Kx H1** | Aligné avec bias | Conflit | Attendre le flip |

**⚠️ Lundi particuliers :**
- **Gap weekend** : si DXY gap de +20 pips → attendre le comblement avant d'entrer
- **Asian range large** (> 30 pips) → privilégier les retracements, pas les breakouts
- **HIGH NEWS DAY** lundi : rare, mais le système flash le filtre automatiquement

### 3. NY Open (14h30 Paris) — Confirmation

```bash
# Rescan Diamond avec mise à jour des prix
python main.py track update
python main.py diamond --timezone BROKER --symbols DXY.cash
```

**Ce qui change à NY :**
- Les news US sont publiées → le DXY peut changer brutalement de direction
- Les positions de weekend sont fermées → + de volume
- Les vrais niveaux D1 de la semaine se dessinent

### 4. Clôture (21h Paris) — Bilan

```bash
# Sauvegarder les trades ouverts
python main.py track save

# Vérifier le P&L
python main.py track report

# Scanner l'évolution
python main.py diamond --timezone BROKER --symbols DXY.cash
```

---

## 🎯 Stratégies DXY par configuration du lundi

### Configuration A : Range asiatique serré (< 10 pips)

```
DXY.cash: AHigh=100.750 ALow=100.720 (30p range → large)
                                     ↓
Si range < 10p → Breakout imminent
```

| Scénario | Entry | SL | TP | Condition |
|:---|:---|:---|:---|:---|
| **Breakout haussier** | Au-dessus de AH | Sous AH | 2× SL | ML% ≥ 50% + T/Kx H1 BULL |
| **Breakout baissier** | En-dessous de AL | Au-dessus AL | 2× SL | ML% ≥ 50% + T/Kx H1 BEAR |

### Configuration B : Gap weekend + comblement

```
DXY fermé vendredi à 100.749
Ouvert lundi à    100.820 (+7.1 pips gap)
```

| Timing | Action |
|:---|:---|
| **Avant 09h** | ❌ Ne PAS trader le gap. Attendre comblement ou rejet confirmé. |
| **09h-10h** | Si gap comblé → trade directionnel normal. |
| **09h-10h** | Si gap non comblé → favoriser la direction du gap (mais réduire taille). |

### Configuration C : HIGH NEWS DAY lundi (rare)

Si le scan affiche `⚠ HIGH NEWS DAY` en warning → le système applique automatiquement le contre-biais (downgrade BULL → WAIT). Dans ce cas :

```python
# Règles strictes :
# 1. Pas de BULL (le système le downgrade)
# 2. BEAR uniquement si ML% ≥ 60%
# 3. Taille réduite de 50%
# 4. Ne pas trader après 15h Paris (volatilité excessive)
```

---

## 📊 Exemple : Lundi typique

```bash
# 09:00 — London Open
# Résultat du scan Diamond :

DXY.cash  Score=48/109  Biais=BEAR  Qualité=STRONG
  Prix=100.735  ML%=67%  ← OK (≥ 50%)
  Kijun H1=100.760  Prix sous Kijun → BEAR confirmé
  T/Kx H1=BEAR  ← Aligné (pas de conflit)
  Kumo H1=BELOW  ← Structure baissière propre
  
  SL=100.825 (Kijun H4, +9p)
  TP=100.588 (Kijun D1, −14.7p)
  RR=1.6×
  
  Warnings: aucun
```

**Décision :** ✅ Trade short activé
- Entry : 100.735 (prix actuel)
- SL : 100.825 (Kijun H4)
- TP : 100.588 (Kijun D1)
- Taille : 1% du capital

**Suivi :**
```bash
# 14h00 — Mi-journée
python main.py track update
# Prix à 100.702 → +3.3 pips, MFE = 5.1 pips (OK, respiration)

# 17h00 — NY Mid
python main.py track update
# Prix à 100.690 → +4.5 pips, TP à −10.2p
# Si MFE < 5% du range → fermer manuellement

# 21h00 — Clôture
python main.py track save
```

---

## ⚠️ Pièges du lundi

| Piège | Description | Solution |
|:---|:---|:---|
| **Faux breakout asiatique** | Le range asiatique du lundi est souvent cassé à Londres | Attendre 09h pour entrer |
| **Gap trompeur** | Un gap haussier le matin peut être comblé à 10h | Ne pas entrer avant comblement |
| **Volume nul** | Pas assez de volume avant Londres pour un vrai mouvement | Pas de trade avant 09h |
| **Indécision** | Le lundi est un jour de range plus souvent que les autres | Privilégier le range, pas les breakouts |
| **HIGH NEWS DAY** | Les annonces macro du weekend sont digérées le lundi | Toujours vérifier le warning |

---

## 🧠 Résumé pour le lundi

```
┌─────────────────────────────────────────────────────────────┐
│                      DXY LUNDI                              │
│                                                             │
│  07h00 — Scan Asian (avant London)                          │
│  09h00 — ⏰ FEU VERT : Scan Diamond + trade possible        │
│  14h30 — Scan de confirmation (NY Open)                     │
│  17h00 — Plus de nouveaux trades, suivre les existants       │
│  21h00 — Bilan + track save + track report                  │
│                                                             │
│  🔑 KEY : Ne pas trader avant Londres.                      │
│  🔑 KEY : Vérifier les gaps weekend.                        │
│  🔑 KEY : Le DXY WR natif = 73% — lui faire confiance.      │
└─────────────────────────────────────────────────────────────┘
```

---

> **Généré automatiquement par InelidaMarketScan — v1.0.1** |
> **Modèle DXY :** `models/historical_v13_dxy.xgb` (63.5% CV) |
> **WR natif DXY :** 73% sur 233 trades backtestés |

---

> **Didier Vally / Reuniware Systems** — InelidaMarketScan
