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
- Ajouté APRÈS l'erreur US500 (trade greenlighté à 3 pts du SL)
- Si prix < 10% du range SL→TP côté SL → forcé WAIT
- Si 10-20% → STRONG dégradé en GOOD
- Aurait forcé US500 en WAIT au moment critique

#### Smart TP (basé sur niveaux réels)
- Remplace le RR=2.0 fixe
- Collecte Kijun, Tenkan, FVG, SSB, Nuages
- Filtre par direction, prend le plus proche avec RR ≥ 1.5
- Affiche la source du TP (ex : "FVG H1 Bear")
- Plus de TP arbitraire sans ancrage technique

#### --discord flag
- `python main.py diamond --discord` poste les résultats sur Discord
- Webhook lu depuis `.env` (DISCORD_WEBHOOK_URL) ou variable d'env
- Embed inclut : DXY, tous symboles, setups actifs, warnings, résumé
- Dégradation gracieuse si webhook absent

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

### 📊 Diamond Scan (~16h30 Paris)

```
0 STRONG | 1 GOOD | 13 WAIT | BULL: 6 | BEAR: 3
```
Seul US30 reste GOOD (18/22). Tous les autres WAIT avec scoring 22 critères.

---

### 🔍 USDJPY — Analyse détaillée

#### Setup
- Prix : 162.38 | SL : 161.88 (Kijun H4) | TP : ~162.22 (FVG H1 Bear)
- Dist. SL : +50p (31% du range)

#### Trendline D1 (01/07 H=162.838 → 14/07 H=162.470)
- Pente : −0.12 pips/h (quasi plate, descendante)
- TL actuelle : 162.40
- **Rejet à 16:10 Paris** — prix a touché 162.40 puis redescendu
- Puis **cassure confirmée en fin de session** — prix à 162.43, au-dessus

#### Niveaux Ichimoku
- TK H1 : 162.21 (+22p) — BULL
- TK H4 : 162.16 (+27p) — BULL, bien au-dessus
- KJ H4 : 161.88 — SL | Kumo H4 : ABOVE
- TK D1 : 161.98 (+45p) — BULL | KJ D1 : 161.19 — support lointain

---

### 🔍 EURUSD — Analyse détaillée

#### Setup (BULL compromis en fin de session)
- Prix : 1.1451 → 1.1445 | SL : 1.1430 (Kijun H4)
- TK H4 cassée à la baisse : prix sous 1.14442 (−1.2p)
- Dist. SL : +15p (34% du range)

#### Double niveau Kijun H4 = SSB H4 = 1.14298
- Alignement parfait : plancher blindé
- SL positionné dessus
- **DXY TK H4 cassée = pression baissière sur EURUSD**

#### Zone de compression (~10p)
- Résistance : SSB MN 1.14526 | Prix : 1.14450
- Support : TK W1 1.1447, KJ MN 1.1440, KJ H4 1.14298

#### Niveaux Ichimoku
- H1 : TK 1.14581 → prix −13p en-dessous (BEAR)
- H4 : TK 1.14442 → prix +1p au-dessus (test par le haut)
- D1 : TK=KJ H4 1.14298 → conflit D1 BEAR

---

### 🔍 DXY — Évolution complète

#### 16h30 : Sous TK H4 (100.682), rejets multiples
- Prix : 100.666 (−1.6p)
- Chaque test M15 rejeté (mèches à 100.674, 100.678)
- Verrou technique : TK H4 = KJ H1 confluence

#### 17h30-18h : Cassure de la TK H4
- Prix : 100.699 (+1.7p au-dessus)
- 4 bougies H1 UP consécutives depuis 08h UTC
- Cassure confirmée, pas un fake-out

#### Niveaux post-cassure
- TK H4 : 100.681 (maintenant support)
- Prochain objectif : Kumo H4 100.755-100.829
- Kijun H4 : 100.829 (résistance lointaine)

---

### 🐛 Bugs trouvés et corrigés

| Bug | Impact | Fix |
|:---|:---|:---|
| `_pips` DXY ×10000 | Distances 100× trop grandes | ×100 |
| `tp_label` undefined direction=0 | Crash sur FLAT | `tp_label = ""` dans else |
| `tkw1` uninitialized | Crash si W1 indisponible | `tkw1 = 0.0` init |
| Discord 403 sans User-Agent | Message non posté | `User-Agent: InelidaMarketScanner/1.0` |
| `.env` UTF-16 LE | Webhook non lu | Lecture binaire + strip null bytes |
| `_fmt()` undefined Discord | Crash sur `_build_diamond_discord_embed` | Ajout `_fmt()` locale |
| `_utc = timezone` (classe) | TypeError sur `_dt.now(_utc)` | `_tz.utc` |

---

### 💬 Discord — flag --discord

- `python main.py diamond --discord` poste directement sur Discord
- Pas besoin de `discord_notifier.py` intermédiaire
- Embed formaté : DXY + tous symboles + setups actifs + warnings
- Webhook via `.env` (DISCORD_WEBHOOK_URL) ou variable d'env
- **Piège : ne pas oublier le User-Agent → 403 sinon**

---

### 📝 Bilan honnête — le juste et le faux

#### ❌ Ce qui était FAUX

| Ce que j'ai dit | Ce qui s'est passé | Pourquoi |
|:---|---|:---|
| US500 = 🟢 Trade en vie à 7 540 (SL 7 537) | **+3.2 pts = 5% du range** | J'ai ignoré la distance au SL à cause du score 15/17 STRONG |
| US500 rebondit → OK | Même erreur, 2ème fois | J'ai répété au lieu d'admettre |
| 5 trades Diamond = tous solides | US500 mort, EURUSD baissier | Narratif optimiste au lieu des faits |
| Trendline USDJPY avec highs H1 | Mauvaise TF. Corrigé : highs D1 | Pris les mauvais points |
| Rejet USDJPY à 17:10 | Il était 16:24 Paris (14:24 UTC) | Confusion timezone MT5 |
| TP mathématique 162.90 pour USDJPY | Arbitraire, pas de sens technique | Fixé après (smart TP) |

#### ✅ Ce qui était JUSTE

| Ce que j'ai dit | Ce qui s'est passé |
|:---|---|
| DXY TK H4 = 100.682 = le verrou | Testé 4× sans casser, puis cassé à 17h |
| EURUSD Kijun H4 = SSB H4 = 1.14298 double support | Prix toujours au-dessus |
| USDJPY TL D1 (01/07→14/07) à 162.40 résistance | Rejet confirmé, puis cassé |
| ICT macro = NY PM session (14-21h UTC) | Correct |
| Compression EURUSD entre SSB MN et Tenkan W1 | Prix dans cette zone de ~10p |
| FOMC Logan + Schmid = catalyseur PM session | Discours à 18h30/19h25 Paris |
| SL proximity safety net | Implémenté après US500 |
| TP intelligent = niveaux réels | Plus de TP arbitraire |
| DXY TK H4 cassé → EURUSD baissier | Juste arrivé |

#### 📊 Bilan comptable

| Métrique | Valeur |
|:---|---:|
| Analyses techniques correctes | ~80% |
| Jugement sur les trades | ~60% |
| Erreurs de data | 3 (timezone, trendline TF, distance SL) |
| Corrections apportées | +4 (TP smart, SL safety net, --discord, _fmt fix) |

---

### 🎯 5 nouvelles règles d'analyse

Après le bilan de la journée, voici les règles que j'applique désormais :

#### 1. Données brutes avant interprétation
```
AVANT : 🟢 US500 = Trade OK en vie
APRÈS : US500 = 7 540 | SL = 7 537 | +3 pts = 5% du range | Danger
```

#### 2. Distance au SL = métrique numéro 1
Pas le score, pas STRONG/GOOD. Le % du range SL→TP est la température du trade.

#### 3. Narratif interdit — faits seulement
Fini les "Trade en vie", "Stable", "Renforcé". À la place : chiffres, distances, risques factuels.

#### 4. Vérification croisée systématique
- Distance SL > 20% du range ?
- DXY cohérent avec le trade ?
- Trendline vérifiée sur toutes les TF ?
- Cotation MT5 = TradingView ?

#### 5. Incertitude = je le dis
Si doute sur une donnée, je le précise. Si MT5 et TradingView divergent, je demande.

---

### 💻 Code commité aujourd'hui

| Commit | Description |
|:---|:---|
| `31ca3ed` | FVG H1 bear+bull + Kijun D1 |
| `ac454f1` | FVG H4 + D1 dans Diamond Scanner |
| `b417cc0` | Piège #10 User-Agent Discord |
| `5d4bc61` | TK/KJ H4/D1 S/R + _pips DXY + SL safety net |
| `3654bd1` | Smart TP basé sur niveaux réels |
| `4954746` | --discord flag pour diamond command |

---

### ⏰ Fin de session (~18h Paris) — EURUSD stop sur Fib +2.618

**Observation clé (correctif) :** EURUSD a descendu et s'est arrêté exactement sur
l'**extension +2.618** avec **base sur l'Asian High** (ICT style), PAS sur un Fib -2.618
(bear extension depuis le bas).

**Ma première analyse était fausse :** j'ai calculé un `AL + (-2.618) × range` (= 1.14199)
au lieu de `AH − (2.618 × range)` (= 1.14350/1.14369).

```
AH = 1.14745
AL = 1.14594
Range = 15.1 pips

Extension +2.618 (base sur AH): 1.14350 (MT5) / 1.14369 (TradingView)
Low H1 18h UTC: 1.14364

=> Confluence parfaite: le prix a stoppé pile sur le Fib ICT +2.618
```

**Leçon :** Toujours préciser la méthode de calcul du Fib :
- **Extension** (base sur AH/AL, projetée dans la direction opposée)
- **Retracement** (base entre deux points)
- Ne pas confondre Fib -2.618 (bear extension depuis le bas) avec Ext +2.618 (base sur le haut)

---

> **Prochaine session :** à remplir avec la date, le contexte, les setups, les analyses, et les résultats.

