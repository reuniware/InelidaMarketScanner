# 📜 Historique — InelidaMarketScan

> Journal de bord des sessions d'analyse, décisions de trading, évolutions du code,
> et leçons apprises. Commencé le 16/07/2026.

---

## 16/07/2026 — Session NY PM

### ⏰ Contexte macro

- **Date** : 16 juillet 2026
- **Heure Paris** : ~16h30 (14h30 UTC)
- **Phase ICT** : NY PM Session (14-21h UTC) — fenêtre de continuation ou reversal
- **Événements** : Retail Sales US +0.9% (vs +0.2% attendu), FOMC Logan 18h30 Paris, Schmid 19h25 Paris
- **DXY** : 100.666, sous TK H4 (100.682) — résistance non cassée
- **Agenda économique** : GDP UK +0.7%, Claims 216K, Philly Fed 12.7, Housing Starts 256K

### 📊 Diamond Scanner — Évolutions du jour

#### v1 → v2 : FVG multi-TF (H1 + H4 + D1)
- `_detect_fvg_h1` → `_detect_fvg` généralisé avec `scan_window` et `use_priority`
- H1 : 72 barres, priorité 18h-20h Paris
- H4 : 48 barres, plus récent
- D1 : 30 barres, plus récent
- Bearish + Bullish sur chaque TF → 6 critères FVG max
- max_score : 15 → 19 (avec MN)

#### v2 → v3 : Tenkan/Kijun S/R barrier
- Nouveaux critères : TK4, TKd1, Kj4, KjD1 (proximité)
- Seuils instrument-aware (forex/JPY/XAU)
- Warnings quand Tenkan/Kijun agit contre la direction
- max_score : 19 → 22

#### _pips DXY fix
- DXY utilisait ×10000 au lieu de ×100
- Toutes les distances DXY étaient 100× trop grandes
- Impact : Tenkan/Kijun flat history, SSB, FVG gaps tous corrigés

#### SL proximity safety net
- Si prix < 10% du range SL→TP côté SL → forcé WAIT
- Si 10-20% → STRONG dégradé en GOOD
- Évite de greenlighter un trade à 3 pts du SL (erreur US500)

#### Smart TP (basé sur niveaux réels)
- Remplace le RR=2.0 fixe
- Collecte Kijun, Tenkan, FVG, SSB, Nuages
- Filtre par direction, prend le plus proche avec RR ≥ 1.5
- Affiche la source du TP (ex: "FVG H1 Bear")

---

### 📈 5 Setups Diamond détectés (scan initial ~12h UTC)

| # | Symbole | Score | Qualité | Biais | SL | TP initial | TP smart | Statut |
|:---:|:---|:---:|:---|:---|:---|:---|:---|:---|
| 1 | US30.cash | 19/19 | **STRONG** | BULL | 52 426 | 53 495 | Niveau réel | OK (+200p) |
| 2 | US500.cash | 15/17 | STRONG→**WAIT** | BULL | 7 538 | 7 597 | — | SL CRITIQUE (5%) |
| 3 | GBPUSD | 15/19 | GOOD→**WAIT** | BULL | 1.3450 | 1.3628 | — | Compression 14p |
| 4 | USDJPY | 15/19 | GOOD→**WAIT** | BULL | 161.88 | 162.90 | FVG H1 Bear | En vie (+8p) |
| 5 | AUDUSD | 15/19 | GOOD→**WAIT** | BULL | 0.6967 | 0.7091 | — | Kumo D1 ROUGE |

**Aucun SL touché.** US500 passé à 3.2 pts du SL (5.4% du range) puis rebondi à 14 pts (23%).

### 📊 Diamond Scan final (~16h30 Paris)

```
0 STRONG | 1 GOOD | 13 WAIT | BULL: 6 | BEAR: 3
```
Seul US30 reste GOOD (18/22). Tous les autres sont WAIT avec le scoring 22 critères.

---

### 🔍 USDJPY — Analyse détaillée

#### Setup
- Prix : 162.38
- SL : 161.88 (Kijun H4)
- TP : FVG H1 Bear ~162.22 (smart) ou 162.90 (fixe)

#### Trendline D1 (01/07 H=162.838 → 14/07 H=162.470)
- Pente : −0.12 pips/h (quasi plate, descendante)
- TL actuelle : 162.40
- **Rejet à 16:10 Paris** — prix a touché 162.40 puis redescendu à 162.36
- Prix bloqué sous la TL D1 tant que 162.40 n'est pas cassé

#### Niveaux Ichimoku
- TK H1 : 162.35 (support +3p)
- TK H4 : 162.38 (prix pile dessus)
- KJ H4 : 161.88 (SL)
- FVG H1 Bear : 162.10-162.34 (mitigé, support)
- TK H1/KJ H1 : BULL
- TK H4/KJ H4 : BULL
- Kumo H1/H4/D1 : ABOVE

---

### 🔍 EURUSD — Analyse détaillée

#### Setup
- Prix : 1.1451
- SL : 1.1430 (Kijun H4)
- TP : niveau réel (Kijun D1 1.1473 si cassure SSB MN)

#### Double niveau Kijun H4 = SSB H4
- **KJ H4 = SSB H4 = 1.14298** — alignement parfait
- C'est un plancher blindé, le SL est positionné dessus
- Si ça casse → plus aucun support technique

#### Zone de compression
- Résistance : SSB MN 1.1453 (−1p)
- Support : TK W1 1.1447 (+4p), TK H4 1.1449 (+2p), KJ MN 1.1440 (+11p)
- Prix coincé dans ~10 pips

#### Niveaux Ichimoku
- TK H1/KJ H1 : BULL
- TK H4/KJ H4 : BULL
- TK D1/KJ D1 : BEAR (conflit D1)
- Kumo H1/H4 : ABOVE
- Kumo D1 : BELOW (conflit)

---

### 🔍 DXY — Analyse détaillée

#### Niveaux clés
- **TK H4 = KJ H1 = 100.682** (confluence)
- KJ D1 = 100.588 (support)
- Prix : 100.666 (−1.6p sous TK H4)

#### Bougie H4 en cours (16h UTC)
- O=100.653, H=100.678, L=100.561, C=100.666
- Mèche haute à 100.678 — **0.4 pip du TK H4**
- Rejet toujours actif

#### Chaque test M15 du TK H4
| Heure UTC | High | Distance TK H4 |
|:---|:---|---:|
| 16:45 | 100.634 | −4.8p |
| 17:00 | 100.674 | −0.8p |
| 17:15 | 100.666 | −1.6p |
| 17:30 | 100.673 | −0.9p |

#### DXY comme verrou
- Tant que DXY < 100.682 → USD plafonné → supports EURUSD/GBPUSD tiennent
- Si DXY casse 100.682 → reversal baissier sur toutes les paires USD
- Si DXY perd 100.588 (KJ D1) → explosion haussière des paires

---

### 🐛 Bugs trouvés et corrigés

| Bug | Impact | Fix |
|:---|:---|:---|
| `_pips` DXY ×10000 | Distances 100× trop grandes, Tenkan/Kijun invisibles | ×100 |
| `tp_label` undefined direction=0 | Crash sur symboles FLAT | `tp_label = ""` dans else |
| `tkw1` uninitialized | Crash si W1 indisponible | `tkw1 = 0.0` init |
| Discord 403 sans User-Agent | Message non posté | Ajout `User-Agent: InelidaMarketScanner/1.0` |
| `.env` UTF-16 LE | Webhook non lu | Lecture binaire + strip null bytes |
| MT5 timestamp +3h | Heures fausses dans les analyses | Identifié (serveur UTC+3), pas corrigé |

---

### 💬 Discord

- Webhook configuré dans `.env`
- Message posté : synthèse Diamond avec 5 setups classés
- Leçon : toujours inclure `User-Agent` dans le header HTTP

---

### 📝 Leçons apprises

1. **Ne jamais greenlighter un trade sur le score seul.** US500 15/17 STRONG mais à 3 pts du SL = WAIT. Le SL safety net règle ça maintenant.
2. **La trendline D1 est plus fiable que la H1.** J'ai tracé la mauvaise trendline (H1), le user a corrigé avec la D1.
3. **Toujours vérifier les confluences de niveaux.** KJ H4 = SSB H4 sur EURUSD = plancher blindé. KJ H1 = TK H4 sur DXY = double résistance.
4. **Le scanner est un outil, pas un cerveau.** Il donne les données, c'est l'analyse humaine qui fait la synthèse.
5. **Présenter des faits, pas un récit.** "OK en vie" n'est pas une information. "3.2 pts du SL, 5.4% du range" l'est.
6. **TradingView ≠ MT5.** Les timestamps et les ticks diffèrent. Le user voit des choses que MT5 ne capture pas.

---

### 💻 Code commité aujourd'hui

| Commit | Description |
|:---|:---|
| `31ca3ed` | FVG H1 bear+bull + Kijun D1 |
| `ac454f1` | FVG H4 + D1 dans Diamond Scanner |
| `b417cc0` | Piège #10 User-Agent Discord |
| `5d4bc61` | TK/KJ H4/D1 S/R + _pips DXY + SL safety net |
| `3654bd1` | Smart TP basé sur niveaux réels |

---

> **Prochaine session :** à remplir avec la date, le contexte, les setups, les analyses, et les résultats.

