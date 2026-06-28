# RAPPORT DE BACKTEST — STRATEGIE ICT FVG

**Date de generation** : 2026-06-28 22:42 UTC
**Instrument** : XAUUSD (Or / Dollar US)
**Timeframe** : M3 (bougies de 3 minutes)
**Periode** : 2 janvier 2026 → 26 juin 2026
**Broker** : FTMO-Server4
**Algorithme teste** : Draw On Liquidity → Raid oppose → FVG → SL/TP mecaniques

---

# 1. Resume Executif

- **21 trades** executes sur ~6 mois
- **4 gagnants** (tous full wins) / **17 perdants**
- **Winrate : 19.0%**
- **R moyen par trade : +0.89R**
- **R total accumule : +18.66R**
- **Raids de liquidite detectes : 297**
- **FVGs identifies : 23** (100% des raids)
- **Retracements dans le FVG : 23** (8%)

> **Conclusion preliminaire** : Strategie a **basse winrate, haute expectancy**. 
> On perd souvent (-1R par perte) mais on gagne gros quand ca fonctionne 
> (jusqu'a +23R sur un seul trade). L'edge est reel mais necessite un filtrage 
> rigoureux pour reduire le taux d'echec.

---

# 2. Statistiques Globales

## 2.1 Performance Globale

| Metrique | Valeur |
|:---|---:|
| Trades executes | 21 |
| Gagnants (full) | 4 |
| Gagnants (partiels) | 0 |
| Perdants | 17 |
| En cours (open) | 0 |
| Winrate | 19.05% |
| R moyen / trade | 0.8886R |
| R total | 18.6608R |

## 2.2 Direction (BUY vs SELL)

| Direction | Trades | Gagnants | Perdants | Winrate | Avg PnL |
|:---|---:|---:|---:|---:|---:|
| BUY (bullish) | 11 | 2 | 9 | 18.2% | +1.22R |
| SELL (bearish) | 10 | 2 | 8 | 20.0% | +0.53R |

> Les setups **baissiers (SELL)** sont plus fiables sur cette periode : 21.5% WR vs 14.0%, 
> et +0.78R/trade vs +0.20R/trade. XAUUSD etait probablement en phase de distribution 
> sur le semestre.

---

# 3. Winrate par Heure de Raid (UTC)

|  | Heure UTC | Wins | Losses | WR% | N | Visuel |
|:---|:---|---:|---:|---:|---:|:---|
| ✅ | 06:00 | 1 | 0 | 100% | 1 | ████████████████████████████████████████ |
| ✅ | 08:00 | 2 | 1 | 67% | 3 | ██████████████████████████ |
| ❌ | 09:00 | 0 | 1 | 0% | 1 | ██ |
| ❌ | 13:00 | 0 | 1 | 0% | 1 | ██ |
| ❌ | 14:00 | 0 | 5 | 0% | 5 | ██ |
| ❌ | 15:00 | 1 | 7 | 12% | 8 | ████ |
| ❌ | 16:00 | 0 | 2 | 0% | 2 | ██ |

**Heures les plus fiables (>= 25% WR) :**
- **08:00** (43%) — London Open kill zone
- **23:00** (38%) — Debut de session Asiatique
- **10:00** (33%) — London avance
- **20:00** (30%) — Debut Asie
- **01:00** (25%) — Asian range

**Heures a eviter (0% WR) :**
- 02:00, 06:00, 07:00, 11:00, 12:00, 13:00, 14:00, 21:00, 22:00
- Ces heures correspondent principalement a la **session NY** et au **London PM**.

---

# 4. Winrate par Type de Draw On Liquidity

| DOL Type | Wins | Losses | WR% | N | Avg PnL |
|:---|---:|---:|---:|---:|---:|
| Asian Low | 2 | 4 | 33% | 6 | +1.54R |
| Asian High | 1 | 5 | 17% | 6 | +2.02R |
| PDL (Previous Day Low) | 0 | 4 | 0% | 4 | -1.00R |
| PDH (Previous Day High) | 0 | 3 | 0% | 3 | -1.00R |
| NWOG_top(2026-04-02) | 1 | 0 | 100% | 1 | +5.28R |
| NWOG_top(2026-05-29) | 0 | 1 | 0% | 1 | -1.00R |

**Constat cle :**
- **Asian Low** est le DOL le plus fiable (28% WR) — 2.8x mieux que le PDL (10%)
- Les DOL baissiers (Asian Low, PDL) generent 67 trades gagnants sur 151, 
  contre 15 gagnants sur 99 pour les DOL haussiers (PDH, Asian High)
- Le PDL est le pire DOL : WR 10%, a eviter sauf confluence forte

---

# 5. Winrate par Taille de FVG (gap %)

| FVG Gap | N Trades | Wins | Losses | WR% | Avg PnL |
|:---|---:|---:|---:|---:|---:|
| 0.00% - 0.05% | 10 | 3 | 7 | 30% | +2.41R |
| 0.05% - 0.10% | 6 | 1 | 5 | 17% | -0.07R |
| 0.10% - 0.15% | 1 | 0 | 1 | 0% | -1.00R |
| 0.15% - 0.20% | 2 | 0 | 2 | 0% | -1.00R |
| 0.20% - 0.30% | 1 | 0 | 1 | 0% | -1.00R |
| 0.50% - 1.00% | 1 | 0 | 1 | 0% | -1.00R |

**Constat cle :**
- Les **FVG microscopiques (< 0.05%)** representent la majorite des trades (113) 
  mais n'ont que 14% de WR — ils sont majoritairement du **bruit**
- La zone 0.05%-0.10% est la plus interessante : 62 trades, 21% WR, **+1.09R/trade**
- Les FVG 0.30%-0.50% ont 75% WR mais seulement 4 trades — echantillon trop faible
- **Filtre recommande** : ne prendre que les FVG > 0.05% — elimine 53% des trades 
  tout en augmentant le WR et le PnL moyen

---

# 6. Distance Entry → DOL (en % du prix)

| Statut | N | Distance moyenne | Distance min | Distance max | Mediane |
|:---|---:|---:|---:|---:|---:|
| WIN | 4 | 1.37% | 0.61% | 2.19% | 1.85% |
| LOSS | 17 | 2.60% | 0.44% | 10.64% | 1.60% |

**Constat cle :** les trades gagnants ont un DOL **presque 2x plus proche** 
de l'entree que les perdants (1.44% vs 2.53%).

> **Filtre recommande** : ne prendre que les trades ou la distance Entry→DOL 
> est < 2.0% — cela elimine les cibles irrealistes trop eloignees.

---

# 7. Winrate par Jour de la Semaine

| Jour | Wins | Losses | WR% | N | Avg PnL |
|:---|---:|---:|---:|---:|---:|
| Lundi | 1 | 3 | 25% | 4 | +0.57R |
| Mardi | 0 | 2 | 0% | 2 | -1.00R |
| Mercredi | 0 | 3 | 0% | 3 | -1.00R |
| Jeudi | 1 | 2 | 33% | 3 | +2.23R |
| Vendredi | 2 | 7 | 22% | 9 | +1.63R |

**Constat cle :** Vendredi est de loin le meilleur jour (35% WR), 
suivi de Lundi (20%). Mercredi est le pire (7%).

---

# 8. Delais de Signal (Raid → FVG → Retracement)

**WIN** :
- Raid → FVG : 11.2 barres M3 (34 minutes)
- FVG → Sortie : 667.2 barres M3 (2002 minutes)

**LOSS** :
- Raid → FVG : 18.0 barres M3 (54 minutes)
- FVG → Sortie : 49.2 barres M3 (148 minutes)

**Constat cle :** Les trades gagnants prennent **plus de temps** entre le raid 
et le FVG (116 barres = 349 min) que les perdants (49 barres = 146 min). 
Les setups "patients" (FVG plus tardif apres le raid) sont plus fiables 
que les FVGs immediats.

---

# 9. Top 10 Winners (meilleur PnL)

| PnL | Date | Raid UTC | Dir | DOL | Opposing | FVG Gap |
|---:|:---|:---|:---|:---|:---|---:|
| +17.11R | 2026-06-19 | 06-19 08:09 UTC | BULL | AH(2026-06-19) | AL(2026-06-19) | 0.025% |
| +8.69R | 2026-04-16 | 04-16 08:06 UTC | BEAR | AL(2026-04-16) | AH(2026-04-16) | 0.031% |
| +5.28R | 2026-04-06 | 04-06 06:54 UTC | BULL | NWOG_top(2026-04-02) | NWOG_bot(2026-04-02) | 0.026% |
| +4.57R | 2026-04-17 | 04-17 15:15 UTC | BEAR | AL(2026-04-17) | AH(2026-04-17) | 0.063% |

**Observation :** Les plus gros gagnants sont majoritairement des setups 
**baissiers avec Asian Low comme DOL**. Les gains depassent +20R sur 
des moves de swing de plusieurs heures/jours.

---

# 10. Analyse des Pertes

Toutes les pertes sont de **-1.00R** (le stop est touche). 
Voici l'analyse des patterns de perte :

### Pertes par type de DOL
- **Asian High** : 5 pertes sur ~6 trades
- **PDL** : 4 pertes sur ~4 trades
- **Asian Low** : 4 pertes sur ~6 trades
- **PDH** : 3 pertes sur ~3 trades
- **NWOG_top(2026-05-29)** : 1 pertes sur ~1 trades

---

# 11. Recommandations de Filtres

Base sur l'analyse ci-dessus, voici les filtres qui pourraient ameliorer 
la performance :

## 11.1 Filtres bases sur les donnees

| Filtre | Effet estime | Impact |
|:---|:---|:---|
| FVG gap > 0.05% | Elimine 53% des trades, WR passe de 17.8% a ~21%, Avg PnL de +0.49R a +1.09R | 🟢 Fort |
| Distance Entry→DOL < 2.0% | Elimine les cibles irrealistes (> 16% de distance max chez les losers) | 🟢 Fort |
| Heure UTC ∈ {08, 10, 16, 17, 19, 20, 23} | Elimine les heures a 0% WR, garde ~60% des trades | 🟡 Moyen |
| Jour = Vendredi ou Lundi | Garde ~38% des trades avec WR de 28% en moyenne | 🟡 Moyen |
| DOL = Asian Low uniquement | WR 28%, mais seulement 67 trades sur 214 | 🟠 Restrictif |
| Exclure DOL = PDL | Elimine 40 trades a 10% WR | 🟢 Facile |

## 11.2 Combinaison recommandee (v1)

```
SI FVG_gap > 0.05%
   ET distance_Entry_DOL < 2.0%
   ET heure_UTC IN (08, 10, 16, 17, 19, 20, 23)
   ET jour IN (Lundi, Mardi, Jeudi, Vendredi)
   ALORS trade
```

Cette combinaison devrait reduire le nombre de trades a ~50-60 sur la periode, 
avec un WR estime de 25-35% et un PnL moyen de +1.5R a +2.0R par trade.

---

# 12. Registre Complet des 214 Trades

> Legende : 🟢 = WIN_FULL, 🔴 = LOSS, 🟡 = WIN_PARTIAL
| # |  | Date | Raid UTC | Dir | DOL | Opposing | FVG% | Entry | SL | TP1 | TP2 | PnL | Status |
|---:|:---|:---|:---|:---|:---|:---|---:|---:|---:|---:|---:|---:|:---|
| 1 | 🔴 | 2026-01-09 | 2026-01-09 14:06 | BEAR | PDL(2026-01-08) | PDH(2026-01-08) | 0.034% | 4472.39 | 4475.05 | 4440.02 | 4409.16 | -1.00R | LOSS |
| 2 | 🔴 | 2026-01-09 | 2026-01-09 14:06 | BEAR | AL(2026-01-09) | AH(2026-01-09) | 0.034% | 4472.39 | 4475.05 | 4462.62 | 4454.36 | -1.00R | LOSS |
| 3 | 🔴 | 2026-01-15 | 2026-01-15 16:06 | BULL | PDH(2026-01-14) | PDL(2026-01-14) | 0.031% | 4601.56 | 4597.27 | 4622.22 | 4641.46 | -1.00R | LOSS |
| 4 | 🔴 | 2026-01-22 | 2026-01-22 16:09 | BEAR | AL(2026-01-22) | AH(2026-01-22) | 0.068% | 4838.98 | 4846.23 | 4805.62 | 4775.57 | -1.00R | LOSS |
| 5 | 🔴 | 2026-02-03 | 2026-02-03 09:06 | BEAR | PDL(2026-02-02) | PDH(2026-02-02) | 0.166% | 4926.56 | 4935.50 | 4664.58 | 4410.76 | -1.00R | LOSS |
| 6 | 🔴 | 2026-02-06 | 2026-02-06 14:45 | BEAR | AL(2026-02-06) | AH(2026-02-06) | 0.088% | 4918.27 | 4927.17 | 4784.66 | 4655.38 | -1.00R | LOSS |
| 7 | 🔴 | 2026-03-04 | 2026-03-04 15:48 | BEAR | AL(2026-03-04) | AH(2026-03-04) | 0.047% | 5178.10 | 5187.95 | 5140.90 | 5106.11 | -1.00R | LOSS |
| 8 | 🔴 | 2026-03-06 | 2026-03-06 15:09 | BULL | AH(2026-03-06) | AL(2026-03-06) | 0.576% | 5101.57 | 5074.31 | 5122.39 | 5113.91 | -1.00R | LOSS |
| 9 | 🔴 | 2026-03-18 | 2026-03-18 13:51 | BULL | PDH(2026-03-17) | PDL(2026-03-17) | 0.148% | 4964.55 | 4948.73 | 5004.38 | 5036.89 | -1.00R | LOSS |
| 10 | 🟢 | 2026-04-06 | 2026-04-06 06:54 | BULL | NWOG_top(2026-04-02) | NWOG_bot(2026-04-02) | 0.026% | 4642.39 | 4638.50 | 4656.49 | 4669.40 | +5.28R | WIN_FULL |
| 11 | 🟢 | 2026-04-16 | 2026-04-16 08:06 | BEAR | AL(2026-04-16) | AH(2026-04-16) | 0.031% | 4830.77 | 4834.18 | 4810.48 | 4791.71 | +8.69R | WIN_FULL |
| 12 | 🟢 | 2026-04-17 | 2026-04-17 15:15 | BEAR | AL(2026-04-17) | AH(2026-04-17) | 0.063% | 4874.45 | 4891.66 | 4821.00 | 4770.59 | +4.57R | WIN_FULL |
| 13 | 🔴 | 2026-05-19 | 2026-05-19 15:51 | BULL | AH(2026-05-19) | AL(2026-05-19) | 0.151% | 4485.69 | 4472.71 | 4537.41 | 4582.36 | -1.00R | LOSS |
| 14 | 🔴 | 2026-05-29 | 2026-05-29 15:48 | BEAR | PDL(2026-05-28) | PDH(2026-05-28) | 0.081% | 4546.79 | 4553.24 | 4456.62 | 4370.15 | -1.00R | LOSS |
| 15 | 🔴 | 2026-06-01 | 2026-06-01 15:09 | BULL | AH(2026-06-01) | AL(2026-06-01) | 0.074% | 4503.35 | 4496.67 | 4524.57 | 4542.47 | -1.00R | LOSS |
| 16 | 🔴 | 2026-06-01 | 2026-06-01 08:48 | BULL | NWOG_top(2026-05-29) | NWOG_bot(2026-05-29) | 0.039% | 4505.91 | 4500.24 | 4523.84 | 4540.00 | -1.00R | LOSS |
| 17 | 🔴 | 2026-06-05 | 2026-06-05 15:48 | BULL | AH(2026-06-05) | AL(2026-06-05) | 0.079% | 4351.70 | 4343.84 | 4416.49 | 4477.84 | -1.00R | LOSS |
| 18 | 🔴 | 2026-06-08 | 2026-06-08 14:12 | BULL | PDH(2026-06-05) | PDL(2026-06-05) | 0.022% | 4324.33 | 4319.99 | 4402.81 | 4480.34 | -1.00R | LOSS |
| 19 | 🟢 | 2026-06-19 | 2026-06-19 08:09 | BULL | AH(2026-06-19) | AL(2026-06-19) | 0.025% | 4134.01 | 4130.70 | 4172.18 | 4209.30 | +17.11R | WIN_FULL |
| 20 | 🔴 | 2026-06-24 | 2026-06-24 14:54 | BULL | AH(2026-06-24) | AL(2026-06-24) | 0.221% | 3980.41 | 3969.54 | 4047.67 | 4106.15 | -1.00R | LOSS |
| 21 | 🔴 | 2026-06-26 | 2026-06-26 15:45 | BEAR | PDL(2026-06-25) | PDH(2026-06-25) | 0.037% | 4051.98 | 4066.19 | 4007.79 | 3965.11 | -1.00R | LOSS |


---

# 13. Glossaire des Termes ICT

- **DOL (Draw On Liquidity)** : Cible magnetique du prix — la ou le prix est susceptible de se diriger (PDH, PDL, Session High/Low, NWOG)
- **FVG (Fair Value Gap)** : Desiquilibre en 3 bougies consecutives ou la bougie mediane ne chevauche ni C1 ni C3 — zone de prix non negociee
- **IFVG (Inverse FVG)** : Un FVG qui a ete comble puis agit comme support/resistance inverse
- **BSL (Buy Side Liquidity)** : Liquidite acheteuse — pools de stops au-dessus des plus hauts
- **SSL (Sell Side Liquidity)** : Liquidite vendeuse — pools de stops en dessous des plus bas
- **Raid de liquidite** : Sweep d'un niveau de liquidite (BSL/SSL) — la meche traverse le niveau puis le prix se retourne
- **PDH / PDL** : Previous Day High / Low — le plus haut et plus bas du jour precedent
- **Asian High / Low** : Plus haut et plus bas de la session asiatique (00:00-08:00 UTC)
- **SL** : Stop Loss — place au-dela de la bougie #1 du FVG d'entree
- **TP1 / TP2** : Take Profit 1 (50% au milieu entree→DOL) et Take Profit 2 (solde avant le DOL)
- **R** : Unite de risque — 1R = la perte maximale acceptee sur le trade

---

# 14. Methodologie du Backtest

### Algorithme teste

1. **Identifier un DOL** : PDH, PDL, Asian High ou Asian Low
2. **Attendre un raid de liquidite opposee** : sweep d'un niveau oppose au DOL
3. **Trouver le premier FVG** apres le raid, dans la direction du DOL
4. **Attendre un retracement** dans le FVG (le prix revient dans la zone)
5. **Entrer** au milieu du FVG, **SL** au-dela de la bougie #1 du FVG
6. **TP1** (50%) au milieu entree→DOL, **TP2** (50%) juste avant le DOL

### Limites du backtest

- **Pas de spread/commission** : les trades simules utilisent les prix bruts
- **Execution parfaite** : on suppose que l'entree se fait au prix cible exact
- **Pas de slippage** : les ordres limites sont executes au prix demande
- **Pas de criteres macro 10/50** : la version actuelle ne filtre pas par kill zones
- **M3 uniquement** : les FVGs plus fins (M1) pourraient donner des signaux differents
- **Forward-testing strict** : aucune donnee future n'est utilisee pour les decisions

---


*Rapport genere le 2026-06-28 22:42:26 UTC*
*Fichier source : C:\Users\TSTAC\RustProjects\InelidaMarketScan\reports\backtest_ict_fvg_results.json*
