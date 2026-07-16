# Diamond Analysis Skill — Analyse multi-TF complète ICT × Ichimoku

Ce fichier documente la méthodologie d'analyse développée pendant la session du 13 juillet 2026.
Il permet de reproduire le même niveau de profondeur d'analyse pour n'importe quel symbole.

---

## 📋 Pipeline d'analyse (ordre à suivre)

### Étape 0 : Diamond Scanner — Scan complet automatisé

```bash
cd InelidaMarketScan
python main.py diamond                     # tous les symboles de la watchlist
python main.py diamond --symbols DXY.cash EURUSD GBPUSD  # symboles spécifiques
```

**Ce que le Diamond Scanner automatise :**
- ✅ Ichimoku complet H1/H4/D1/W1/MN (Tenkan, Kijun, Kumo, T/K crosses)
- ✅ **FVG multi-TF** : H1 (72b, priorité 18h-20h Paris), H4 (48b), D1 (30b) — bearish + bullish
- ✅ Étape 3b : Tenkan/Kijun flat history TOUS TFs, SSB proximity, Kumo futur
- ✅ Scoring 19 critères (17 sans MN) : Kumo, T/K, flat bars, FVGs, Kijun D1, W1, MN
- ✅ Alignement multi-TF (0-5 TFs), qualités STRONG/GOOD/WAIT
- ✅ Trade setup : SL (Kijun H4), TP (RR 2.0), horizon (Intraday→Position)
- ✅ Détection compression multi-TF (Étape 7b)
- ✅ Warnings : confluent Kijun H1=H4, Kumo virage/flat, conflit MN

**Critères FVG (6 max) :**
| TF | Fenêtre scan | Priorité | Critère Bear | Critère Bull |
|:---|:---|:---|:---|:---|
| **H1** | 72 barres (~3j) | 18h-20h Paris=10, hier=5 | `FVG` | `FVGb` |
| **H4** | 48 barres (~8j) | Plus récent | `FVG4` | `FVGb4` |
| **D1** | 30 barres (~1mois) | Plus récent | `FVGD1` | `FVGbD1` |

**Scoring max :** 19 critères (17 sans MN)

---

### Étape 1 : Scan Asian Range (ICT)

```bash
cd InelidaMarketScan
python main.py asian --symbols GBPUSD,EURUSD,AUDUSD,USDJPY,XAUUSD,GBPJPY,EURJPY,USDCAD,USDCHF,NZDUSD --timeframe H1
```

**Ce qu'on cherche :**
- Trades avec **RR ≥ 1.0** (prioritaires)
- Trades avec **RR ≥ 0.8** (à surveiller)
- **Double sweep AH+AL** = signal plus fort qu'un sweep simple
- **Sweep simple uniquement** = signal plus faible

**⚠️ Piège :** Le scanner ne consulte que le range asiatique H1. Il ne regarde pas :
- Les TFs supérieurs (D1, W1)
- Le DXY
- L'Ichimoku
- Les flat lines / SSB

C'est un **détecteur**, pas un cerveau. Toujours croiser avec les étapes suivantes.

---

### Étape 2 : Analyse Ichimoku complète (InelidaMarketScan)

```bash
cd InelidaMarketScan
python main.py asian --symbols SYMBOLE --timeframe H1  # Déjà fait en étape 1
```

**Utiliser les données Ichimoku déjà présentes dans le scan (Tenkan, Kijun, Senkou A/B, fib).**

---

### Étape 3 : Flat Lines + SSB (IchimokuSword)

```bash
cd IchimokuSword
python analyze_flat_lines.py SYMBOLE1,SYMBOLE2,SYMBOLE3 --detail
```

**Ce qu'on obtient pour chaque symbole × chaque TF (H1, H4, D1, W1) :**
- Tenkan, Kijun, Senkou A, Senkou B (valeurs actuelles)
- Prix vs Kijun (% distance)
- **Flat lines actives** avec compteur de barres : `KIJUN PLAT 21B`, `TENKAN PLAT 6B`, etc.
- **SSB historiques** : supports/résistances détectés avec distance en pips
- Nuage futur plat/fin, Chikou passé plat (signal secondaire)

**Ce qu'on cherche en priorité :**
- Kijun plat ≥ 10B → zone d'équilibre majeure
- SSB dans les 5 pips du prix → niveau technique immédiat
- Kijun plat ET SSB proche → confluent fort
- **Ignorer Chikou passé plat** — peu de valeur prédictive (c'est juste le prix d'il y a 26 barres)

---

### Étape 3b : Détection SYSTÉMATIQUE des flat lines — TOUS TFs (passées, présentes, futures)

**⚠️ OBLIGATOIRE avant toute décision de trade.**

Le Diamond Analysis échoue si on ne cartographie pas TOUTES les flat lines. Une flat line
omise = un trade qui bute sur un obstacle invisible. Cette étape systématise la détection.

#### 🔍 Trois types de flat lines à vérifier

| Type | Définition | Exemple | Impact |
|:---|:---|:---|:---|
| **PASSÉES** | Flat lines historiques qui ne sont PLUS actives mais dont le niveau reste en mémoire | Tenkan D1 plat 2j en juin 2026 à 185.30 → résistance aujourd'hui | **Obstacle invisible** — le prix rebondit sur un niveau "fantôme" |
| **PRÉSENTES** | Flat lines actives EN CE MOMENT (Kijun/Tenkan/SSB plats) | Kijun H4 plat 16b à 161.991 | **Zone d'équilibre** — support/résistance immédiat |
| **FUTURES** | Flat lines en FORMATION (3-7 barres, pas encore qualifiées) | Kijun H1 stable depuis 5 barres → pourrait devenir un plat 10b | **Anticipation** — zone qui pourrait devenir un support/résistance majeur |

#### 📋 Matrice de détection (à exécuter pour CHAQUE paire)

```
Pour chaque TF (H1, H4, D1, W1, MN) :
  1. Tenkan : flats PASSÉS (historique), PRÉSENT (actif), FUTUR (en formation)
  2. Kijun  : flats PASSÉS, PRÉSENT, FUTUR
  3. SSB    : flats PASSÉS, PRÉSENT, FUTUR
```

**Priorité de vérification :**
1. **Kijun** (tous TFs) — le plus fiable, 100% de réussite aujourd'hui
2. **Tenkan** (D1, W1, MN) — mémoire institutionnelle la plus forte
3. **SSB** (H4, D1) — obstacles pour les TP

#### ⚙️ Seuils de détection (corrigés — 14/07/2026)

| Type de paire | Seuil Tenkan/Kijun plat | Seuil SSB |
|:---|---:|---:|
| **JPY** (USDJPY, EURJPY, GBPJPY) | `0.03` (3 pips) | `0.05` (5 pips) |
| **Non-JPY** (EURUSD, GBPUSD, AUDUSD...) | `0.0003` (3 pips) | `0.0005` (5 pips) |
| **XAUUSD** | `0.03` (3 pips) | `0.05` (5 pips) |

**⚠️ Piège corrigé :** Avant le 14/07/2026, le seuil était `0.03` pour TOUTES les paires.
Sur EURUSD (~1.10), `0.03` = 300 pips → tout était faussement détecté comme "plat".
Le seuil doit être SCALÉ par type d'instrument.

#### 🔧 Détection « FUTURES » — flat lines en formation

Une flat line est considérée "en formation" quand :
- **Kijun** : variation < 0.02% sur les 3-7 dernières barres (selon TF)
- **Tenkan** : variation < 0.02% sur les 2-5 dernières barres
- Le compteur est affiché comme `Kijun H4: 5b (en formation, seuil 10b)`

**⚠️ Ne pas trader sur une flat en formation.** Elle devient un niveau SEULEMENT
quand elle atteint le seuil critique (≥ 8b pour Kijun, ≥ 2j pour Tenkan D1).

#### 🖥️ Script de détection des Tenkan D1 plats historiques

```bash
cd InelidaMarketScan
python -c "
import MetaTrader5 as mt5
from datetime import datetime, timezone

mt5.initialize()
SYM = 'EURJPY'  # changer ici
mt5.symbol_select(SYM, True)
tick = mt5.symbol_info_tick(SYM)
price = float(tick.bid)

r = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_D1, 0, 200)
highs = [float(x[2]) for x in r]
lows = [float(x[3]) for x in r]
ts = [int(x[0]) for x in r]

UTC = timezone.utc
thresh = 0.03 if 'JPY' in SYM or SYM == 'XAUUSD' else 0.0003
prev_tk = None
current_flat = []
flats = []

for i in range(8, len(r)):
    tk_i = (max(highs[i-8:i+1]) + min(lows[i-8:i+1])) / 2.0
    dt = datetime.fromtimestamp(ts[i], UTC)
    if prev_tk is not None:
        if abs(tk_i - prev_tk) < thresh:
            current_flat.append((dt, tk_i))
        else:
            if len(current_flat) >= 2: flats.append(current_flat)
            current_flat = [(dt, tk_i)]
    else:
        current_flat = [(dt, tk_i)]
    prev_tk = tk_i
if len(current_flat) >= 2: flats.append(current_flat)

print(f'{SYM} prix={price:.5f}')
print('Tenkan D1 plats historiques proches (< 80 pips):')
factor = 100 if 'JPY' in SYM else 10000
for period in flats:
    vals = [p[1] for p in period]
    avg = sum(vals) / len(vals)
    dist = (price - avg) * factor
    if abs(dist) < 80:
        sd, ed = period[0][0], period[-1][0]
        direction = 'RESISTANCE' if dist > 0 else 'SUPPORT'
        print(f'  {sd.strftime(\"%d/%m\")}->{ed.strftime(\"%d/%m\")} ({len(period)}j) | {avg:.5f} | {dist:+.0f}p | {direction}')

mt5.shutdown()
"
```

**Intégration dans le scan Diamond :** La fonction `detect_tenkan_flat_history()`
doit être appelée sur D1 pour chaque symbole. Tout flat à moins de 10 pips du prix
déclenche un avertissement. Tout flat entre prix et TP réduit la probabilité du trade.

#### 📝 Exemple concret — EURJPY (14/07/2026, 17:30 UTC)

```
PASSÉES (mémoire) :
  Tenkan D1 plat 2j à 185.299 (19-22 juin 2026) → RÉSISTANCE immédiate
  Tenkan D1 plat 2j à 185.307 (02-03 juin 2026) → RÉSISTANCE immédiate
  → Le prix (185.296) est COINCÉ sous ces deux niveaux !

PRÉSENTES (actives) :
  Kijun H4 plat 12b à 185.039 → SUPPORT à +26 pips sous le prix
  → Setup BUY valide MAIS l'entrée est dans la résistance Tenkan D1

FUTURES (en formation) :
  Aucune en formation significative
```

**Sans cette étape :** on recommande EURJPY BUY à 185.30 → le trade entre dans une résistance.
**Avec cette étape :** on attend la cassure de 185.31 AVANT d'entrer.

---

### Étape 4 : DXY (toujours, pour les paires USD)

```bash
python main.py asian --symbols DXY.cash --timeframe H1
```

**Si DXY.cash indisponible (broker FTMO/Darwinex) :**
```bash
cd IchimokuSword
python -c "
import MetaTrader5 as mt5
mt5.initialize()
# Essayer les variantes
for sym in ['DXY.cash', 'DXY', 'USDX', 'USDOLLAR']:
    mt5.symbol_select(sym, True)
    tick = mt5.symbol_info_tick(sym)
    if tick: print(f'{sym}: {tick.bid}')
mt5.shutdown()
"
```

**Règle de corrélation :**
- DXY haussier = USD fort → paires USD devraient monter (BUY USDCAD, USDJPY, USDCHF)
- DXY haussier → EURUSD, GBPUSD, AUDUSD devraient baisser (SELL)
- Un SELL sur USDCAD avec DXY haussier = **contre-tendance macro** → signal rouge

---

### Étape 5 : Analyse W1 (nuage visible, pas la valeur future)

**⚠️ CRITIQUE :** Le Senkou Span B (SSB) calculé sur la bougie actuelle est projeté **26 périodes dans le futur**. Ce n'est pas celui qui est affiché sur le graphique !

```bash
cd IchimokuSword
python -c "
import MetaTrader5 as mt5, numpy as np
from datetime import datetime, timezone

mt5.initialize()
mt5.symbol_select('SYMBOLE', True)
tick = mt5.symbol_info_tick('SYMBOLE')
rates = mt5.copy_rates_from_pos('SYMBOLE', mt5.TIMEFRAME_W1, 0, 80)

highs = [float(r[2]) for r in rates]
lows = [float(r[3]) for r in rates]
closes = [float(r[4]) for r in rates]
timestamps = [int(r[0]) for r in rates]
last = len(rates) - 1
UTC = timezone.utc

# Nuage VISIBLE = Senkou calcule il y a 26 semaines
sb_visible = (max(highs[-78:-26]) + min(lows[-78:-26])) / 2.0  # il y a 26 barres
kj_26 = (max(highs[-52:-26]) + min(lows[-52:-26])) / 2.0
tk_26 = (max(highs[-35:-26]) + min(lows[-35:-26])) / 2.0
sa_visible = (tk_26 + kj_26) / 2.0

cloud_top = max(sa_visible, sb_visible)
cloud_bot = min(sa_visible, sb_visible)
color = 'VERT' if sa_visible > sb_visible else 'ROUGE'

print(f'Nuage W1 visible: {cloud_bot:.5f} - {cloud_top:.5f} ({color})')
print(f'Prix {tick.bid:.5f}: ', end='')
if tick.bid > cloud_top: print('AU-DESSUS')
elif tick.bid < cloud_bot: print('EN-DESSOUS')
else: print('DANS le nuage')

# Dernieres bougies W1 vs nuage
for i in range(max(0, last-15), last+1):
    dt = datetime.fromtimestamp(timestamps[i], UTC)
    c = closes[i]
    vs = 'AU-DESSUS' if c > cloud_top else ('EN-DESSOUS' if c < cloud_bot else 'DANS')
    print(f'{dt.strftime(\"%Y-%m-%d\")}: O={highs[i]:.5f} H={highs[i]:.5f} L={lows[i]:.5f} C={c:.5f} {vs}')

mt5.shutdown()
"
```

**Ce qu'on cherche :**
- Fausse cassure : prix passé AU-DESSUS du nuage puis revenu DANS/EN-DESSOUS
- Doji dans le nuage après une fausse cassure = signal de retournement
- Bougie en cours : ne PAS qualifier de doji tant qu'elle n'est pas fermée

---

### Étape 4b : DXY Tenkan W1 — Niveaux plats historiques

**⚠️ NOUVEAU :** La Tenkan W1 peut former des plats qui agissent comme résistance/support
des mois plus tard. Ces niveaux ont une **mémoire institutionnelle**.

```bash
cd IchimokuSword
python -c "
import MetaTrader5 as mt5, numpy as np
from datetime import datetime, timezone

mt5.initialize()
mt5.symbol_select('DXY.cash', True)
tick = mt5.symbol_info_tick('DXY.cash')
rates = mt5.copy_rates_from_pos('DXY.cash', mt5.TIMEFRAME_W1, 0, 80)
highs = np.array([float(r[2]) for r in rates])
lows = np.array([float(r[3]) for r in rates])
timestamps = [int(r[0]) for r in rates]

UTC = timezone.utc
prev_tk = None
print(f'DXY: {tick.bid:.3f}')
print('Niveaux Tenkan W1 plats proches du prix:')
for i in range(8, len(rates)):
    tk = (np.max(highs[i-8:i+1]) + np.min(lows[i-8:i+1])) / 2.0
    dt = datetime.fromtimestamp(timestamps[i], UTC)
    dist = (tick.bid - tk) / tk * 100
    if prev_tk is not None and abs(tk - prev_tk) < 0.01 and abs(dist) < 2.0:
        marker = 'PLAT' if abs(tk - prev_tk) < 0.005 else 'quasi-plat'
        print(f'  {dt.strftime(\"%d/%m/%Y\")}: Tenkan={tk:.3f} | ecart={dist:+.2f}% ({marker})')
    prev_tk = tk
mt5.shutdown()
"
```

**Règle :** Un Tenkan W1 resté figé ≥ 2 semaines à un niveau X crée une résistance/support
structurel qui reste actif pendant des mois. Si le prix actuel est à moins de 0.1% de ce
niveau, c'est un **confluent majeur** à prendre en compte.

---

### Étape 5b : Nuage H4 — Risque de pullback

Le nuage Ichimoku est une zone d'attraction/répulsion. Quand le prix est proche du nuage,
il faut évaluer le risque de pullback AVANT que le prix n'atteigne TP1.

```bash
cd IchimokuSword
python -c "
import MetaTrader5 as mt5, numpy as np
from datetime import datetime, timezone

mt5.initialize()
SYM = 'EURUSD'  # changer ici
mt5.symbol_select(SYM, True)
tick = mt5.symbol_info_tick(SYM)
price = float(tick.bid)

rates = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_H4, 0, 150)
highs = np.array([float(r[2]) for r in rates])
lows = np.array([float(r[3]) for r in rates])
timestamps = [int(r[0]) for r in rates]
last = len(rates) - 1
UTC = timezone.utc

# Nuage visible (26 barres en arriere)
idx_vis = last - 26
tk_vis = (np.max(highs[idx_vis-8:idx_vis+1]) + np.min(lows[idx_vis-8:idx_vis+1])) / 2.0
kj_vis = (np.max(highs[idx_vis-25:idx_vis+1]) + np.min(lows[idx_vis-25:idx_vis+1])) / 2.0
sa_vis = (tk_vis + kj_vis) / 2.0
sb_vis = (np.max(highs[idx_vis-51:idx_vis+1]) + np.min(lows[idx_vis-51:idx_vis+1])) / 2.0

vtop = max(sa_vis, sb_vis)
vbot = min(sa_vis, sb_vis)
vcolor = 'VERT' if sa_vis > sb_vis else 'ROUGE'

# Nuage futur (calcule maintenant)
tk_now = (np.max(highs[-9:]) + np.min(lows[-9:])) / 2.0
kj_now = (np.max(highs[-26:]) + np.min(lows[-26:])) / 2.0
sa_now = (tk_now + kj_now) / 2.0
sb_now = (np.max(highs[-52:]) + np.min(lows[-52:])) / 2.0
ftop = max(sa_now, sb_now)
fbot = min(sa_now, sb_now)
fcolor = 'VERT' if sa_now > sb_now else 'ROUGE'

print(f'{SYM} BID: {price:.5f}')
print(f'Nuage visible: {vbot:.5f}-{vtop:.5f} {vcolor} | Prix vs base: {(price-vbot)/vbot*100:+.3f}%')
print(f'Nuage futur:   {fbot:.5f}-{ftop:.5f} {fcolor} | Transition: {vcolor}->{fcolor}')
print()

# Risque de pullback
if price < vbot:
    dist = (vbot - price) / price * 100
    print(f'Prix SOUS le nuage de {dist:.3f}%')
    if dist < 0.2:
        print(f'RISQUE: Pullback possible vers la base du nuage ({vbot:.5f})')
    else:
        print(f'OK: Prix suffisamment eloigne du nuage')
elif price > vtop:
    dist = (price - vtop) / vtop * 100
    print(f'Prix SUR le nuage de {dist:.3f}%')
    if dist < 0.2:
        print(f'RISQUE: Pullback possible vers le top du nuage ({vtop:.5f})')
else:
    print(f'Prix DANS le nuage - pullback en cours ou cassure imminente')

# Comparaison SL vs nuage
print(f'Si SL est place dans le nuage: protection partielle')
print(f'Si SL est au-dessus du top du nuage: protection maximale')

mt5.shutdown()
"
```

**Ce qu'on cherche :**
- Prix sous nuage visible de < 0.2% → pullback probable, SL doit être au-dessus du top du nuage
- Transition vert→rouge du nuage = signal baissier qui se renforce
- SL placé dans le nuage (entre base et top) = protection partielle, risque de déclenchement
- SL placé au-dessus du top du nuage = protection maximale

**⚠️ Règle :** Pour un SELL, le SL idéal est au-dessus du **top** du nuage visible H4,
pas juste au-dessus de la base. Un pullback peut facilement traverser le nuage en 1-2 bougies.

---

### Étape 5c : TP partiels basés sur les SSB

**⚠️ NOUVEAU :** Le TP fib du scanner Asian est un niveau mathématique, pas un niveau
Ichimoku. Il peut se trouver dans le vide, sans aucun support structurel. Il faut
toujours cartographier les SSB entre le prix et le TP pour ajuster sa stratégie.

```bash
cd IchimokuSword
python -c "
import MetaTrader5 as mt5, numpy as np
from datetime import datetime, timezone

mt5.initialize()
SYM = 'AUDUSD'  # changer ici
mt5.symbol_select(SYM, True)
tick = mt5.symbol_info_tick(SYM)
price = float(tick.bid)
tp1 = 0.68876  # TP1 du scanner
tp2 = 0.0     # TP2 si applicable

rates = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_H4, 0, 150)
highs = np.array([float(r[2]) for r in rates])
lows = np.array([float(r[3]) for r in rates])
timestamps = [int(r[0]) for r in rates]

# Trouver TOUS les SSB H4 entre prix et TP1
print(f'{SYM}: prix={price:.5f} TP1={tp1:.5f}')
print('SSB H4 entre prix et TP1:')
seen = set()
levels = []
for i in range(52, len(rates)):
    sb = (np.max(highs[i-51:i+1]) + np.min(lows[i-51:i+1])) / 2.0
    if tp1 < sb < price:
        key = round(sb, 5)
        if key not in seen:
            seen.add(key)
            dt = datetime.fromtimestamp(timestamps[i], timezone.utc)
            pips = (price - sb) * 10000
            levels.append((sb, pips, dt))

levels.sort(key=lambda x: x[0], reverse=True)
for sb, pips, dt in levels:
    print(f'  {sb:.5f} (-{pips:.1f} pips) [{dt.strftime(\"%d/%m\")}]')

if not levels:
    print('  AUNCUN SSB entre prix et TP1 - TP1 est dans le vide !')
    print('  -> Le prix peut accelerer une fois les obstacles H1 franchis')
else:
    print(f'  {len(levels)} obstacles a franchir avant TP1')
    print(f'  -> Recommandation: TP partiels sur les SSB les plus proches')

mt5.shutdown()
"
```

**Règles de décision :**

| Situation | Stratégie |
|:---|:---|
| **0 SSB entre prix et TP1** | TP unique fib — pas d'obstacle |
| **1-2 SSB entre prix et TP1** | TP partiel 50% sur le 1er SSB, 50% sur le fib |
| **3-5 SSB entre prix et TP1** | 3 TP : 30% SSB cluster, 30% dernier SSB, 40% fib runner |
| **6+ SSB entre prix et TP1** | TP unique sur le cluster SSB le plus proche — le fib est trop loin |

**🎯 Exemple AUDUSD (30 pips, 6 SSB) :**
```
TP1 (30%) : 0.69125 (-5.1p)  cluster SSB 12h  → RR partiel 0.16x
TP2 (30%) : 0.69073 (-10.3p) dernier obstacle → RR partiel 0.33x
TP3 (40%) : 0.68876 (-30.0p) fib runner       → RR partiel 1.0x
```

**SL trailing recommandé :**
1. Prix casse le 1er TP partiel → SL descend au-dessus du cluster franchi
2. Prix casse le dernier SSB → SL descend juste au-dessus
3. Laisser le runner courir vers le fib avec SL protégé

---

### Étape 6 : Vérification Kijun plat (deep dive)

Quand un Kijun plat > 15B est détecté, vérifier manuellement :

```bash
cd IchimokuSword
python -c "
import MetaTrader5 as mt5, numpy as np
from datetime import datetime, timezone

mt5.initialize()
mt5.symbol_select('SYMBOLE', True)
rates = mt5.copy_rates_from_pos('SYMBOLE', mt5.TIMEFRAME_H1, 0, 120)

highs = [float(r[2]) for r in rates]
lows = [float(r[3]) for r in rates]
timestamps = [int(r[0]) for r in rates]
UTC = timezone.utc

# Construire historique Kijun
kijun_hist = []
for i in range(26, len(rates)):
    k = (max(highs[i-25:i+1]) + min(lows[i-25:i+1])) / 2.0
    dt = datetime.fromtimestamp(timestamps[i], UTC)
    kijun_hist.append({'idx': i, 'kijun': k, 'dt': dt})

# Verification GLOBALE (pas fenetre glissante !)
base = kijun_hist[-1]['kijun']
vals = []
for i in range(len(kijun_hist)):
    idx = len(kijun_hist) - 1 - i
    v = kijun_hist[idx]['kijun']
    vals.append(v)
    if (max(vals) - min(vals)) / base * 100 > 0.05:
        break

count = len(vals) - 1
print(f'Bars plates (global): {count}')
print(f'Kijun range: {min(vals):.6f} - {max(vals):.6f} (var: {(max(vals)-min(vals))/base*100:.4f}%)')
print(f'VERDICT: {\"FLAT LINE REELLE\" if (max(vals)-min(vals))/base*100 <= 0.05 else \"PAS VRAIMENT PLATE\"}')
print(f'Debut: {kijun_hist[len(kijun_hist)-count][\"dt\"].strftime(\"%Y-%m-%d %H:%M UTC\")}')
print(f'Fin:   {kijun_hist[-1][\"dt\"].strftime(\"%Y-%m-%d %H:%M UTC\")}')
mt5.shutdown()
"
```

---

### Étape 7 : Analyse Mensuelle (MN) — Mémoire institutionnelle

Le timeframe mensuel est le plus structurel. Un Kijun MN ou un Tenkan MN plat historique
peut agir comme support/résistance pendant des **années**. C'est le timeframe de la
mémoire institutionnelle profonde.

```bash
cd IchimokuSword
python -c "
import MetaTrader5 as mt5, numpy as np
from datetime import datetime, timezone

mt5.initialize()
SYM = 'USDCAD'  # changer ici
mt5.symbol_select(SYM, True)
tick = mt5.symbol_info_tick(SYM)
price = float(tick.bid)

rates = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_MN1, 0, 100)
highs = np.array([float(r[2]) for r in rates])
lows = np.array([float(r[3]) for r in rates])
closes = np.array([float(r[4]) for r in rates])
timestamps = [int(r[0]) for r in rates]
last = len(rates) - 1
UTC = timezone.utc

# Ichimoku MN actuel
tk = (np.max(highs[-9:]) + np.min(lows[-9:])) / 2.0
kj = (np.max(highs[-26:]) + np.min(lows[-26:])) / 2.0
sa = (tk + kj) / 2.0
sb = (np.max(highs[-52:]) + np.min(lows[-52:])) / 2.0

# Nuage visible (26 mois en arrière)
if last >= 26:
    idx_vis = last - 26
    tk_vis = (np.max(highs[idx_vis-8:idx_vis+1]) + np.min(lows[idx_vis-8:idx_vis+1])) / 2.0
    kj_vis = (np.max(highs[idx_vis-25:idx_vis+1]) + np.min(lows[idx_vis-25:idx_vis+1])) / 2.0
    sa_vis = (tk_vis + kj_vis) / 2.0
    sb_vis = (np.max(highs[idx_vis-51:idx_vis+1]) + np.min(lows[idx_vis-51:idx_vis+1])) / 2.0
    vtop, vbot = max(sa_vis, sb_vis), min(sa_vis, sb_vis)
    vcolor = 'VERT' if sa_vis > sb_vis else 'ROUGE'

print(f'{SYM} BID: {price:.5f}')
print(f'MN: Tenkan={tk:.5f} Kijun={kj:.5f} SA={sa:.5f} SB={sb:.5f}')
print(f'Nuage visible: {vbot:.5f}-{vtop:.5f} {vcolor}')

for name, val in [('Tenkan', tk), ('Kijun', kj)]:
    dist_pct = (price - val) / val * 100
    print(f'Prix vs {name}: {dist_pct:+.3f}%')

# 12 derniers mois vs Kijun MN
print()
print('12 derniers mois vs Kijun MN:')
for i in range(max(0, last-11), last+1):
    c = closes[i]
    dt = datetime.fromtimestamp(timestamps[i], UTC)
    vs = 'AU-DESSUS' if c > kj else 'EN-DESSOUS'
    m = ' <-- EN COURS' if i == last else ''
    print(f'  {dt.strftime(\"%Y-%m\")}: {c:.5f} {vs}{m}')

# Tenkan MN historique - plats proches du prix
print()
print('Tenkan MN plats historiques proches du prix:')
prev_tk = None
for i in range(8, len(rates)):
    t = (np.max(highs[i-8:i+1]) + np.min(lows[i-8:i+1])) / 2.0
    dt = datetime.fromtimestamp(timestamps[i], UTC)
    dist = (price - t) / t * 100
    if prev_tk is not None and abs(t - prev_tk) < 0.01 and abs(dist) < 5.0:
        marker = 'PLAT' if abs(t - prev_tk) < 0.005 else 'quasi-plat'
        print(f'  {dt.strftime(\"%m/%Y\")}: Tenkan={t:.5f} | ecart={dist:+.2f}% ({marker})')
    prev_tk = t

# Transition nuage MN
if 'sa_vis' in dir() and 'sa' in dir():
    if (sa_vis > sb_vis) != (sa > sb):
        print()
        print('!!! TRANSITION NUAGE MN !!!')
        print(f'Visible: {vcolor} -> Futur: {\"VERT\" if sa > sb else \"ROUGE\"}')

# SSB MN proches
print()
print('SSB MN proches (< 1%):')
for i in range(52, len(rates)):
    ssb = (np.max(highs[i-51:i+1]) + np.min(lows[i-51:i+1])) / 2.0
    if abs(price - ssb) / price < 0.01:
        d = (price - ssb) / price * 100
        print(f'  SSB {ssb:.5f} | {d:+.3f}%')

mt5.shutdown()
"
```

**Ce qu'on cherche :**
- **Kijun MN vs prix** : combien de mois consécutifs au-dessus ou en-dessous ?
  Une cassure du Kijun MN après 10 mois en-dessous = signal haussier structurel majeur
- **Tenkan MN plats historiques** : un Tenkan resté figé 3+ mois crée un niveau
  qui reste actif pendant des années. Si ce niveau = Kijun actuel = double mémoire
- **Transition nuage MN** : rouge→vert ou vert→rouge = changement de tendance séculaire
- **SSB MN** : extrêmement rares proches du prix, mais quand c'est le cas = niveau ultime

**⚠️ Règle :** Ne jamais trader contre le Kijun MN. Si le prix est AU-DESSUS du Kijun MN,
privilégier les BUYS. Si EN-DESSOUS, privilégier les SELLS. Le Kijun MN est le juge de paix
ultime.

---

### Étape 7b : Détection de compression multi-TF

Quand le prix est coincé entre un support MN (Kijun) et une résistance W1 (SSB/top nuage),
c'est une **zone de compression institutionnelle**. Le marché va trancher — souvent
violemment.

**Exemple USDCAD (13/07/2026) :**
```
Top nuage W1 + Tenkan MN plat : 1.41663 ← RESISTANCE
SSB W1 :                         1.41372 ← RESISTANCE
PRIX :                           1.41316 ← COMPRESSION (53 pips)
KIJUN MN + Tenkan MN plat :     1.41061 ← SUPPORT
```

**Comment lire une compression :**
1. Mesurer l'écart entre le support le plus proche et la résistance la plus proche
2. Si écart < 100 pips : cassure imminente (jours/semaines)
3. Si écart > 200 pips : range potentiel (semaines/mois)
4. Identifier le catalyseur : DXY pour les paires USD, données économiques, etc.
5. Préparer les DEUX scénarios (BUY si cassure hausse, SELL si cassure baisse)

---

## 🔬 Matrice d'alignement Ichimoku (5 TFs)

Pour chaque trade, construire cette matrice :

| TF | Prix vs Kijun | Nuage | Flat Lines (présent) | Mémoire (passé) | SSB proches | Biais |
|----|:---:|:---:|:---|:---|:---|:---:|
| H1 | ±X% | Vert/Rouge | Kijun XB, Tenkan XB | N/A (intraday) | Support/Res à X pips | 🔼/🔽 |
| H4 | ±X% | Vert/Rouge | ... | N/A (intraday) | ... | 🔼/🔽 |
| D1 | ±X% | Vert/Rouge | ... | **Tenkan plat ≥ 2j ?** | ... | 🔼/🔽 |
| W1 | ±X% | Vert/Rouge | ... | **Tenkan plat ≥ 2sem ?** | ... | 🔼/🔽 |
| MN | ±X% | Vert/Rouge | ... | **Tenkan plat ≥ 2mois ?** | ... | 🔼/🔽 |

- **5/5 TF aligné** = trade de conviction maximale
- **4/5 TF aligné** = très fiable
- **3/5 TF aligné** = acceptable
- **≤ 2/5 TF aligné** = conflit, éviter

---

## 🏗️ Structure des projets

### InelidaMarketScan (C:\Users\TSTAC\RustProjects\InelidaMarketScan)
```
main.py                 → CLI (asian, sweeps, setups, etc.)
live_monitor.py         → Monitoring live des sweeps
monitor_tenkan_d1.py    → Monitoring Tenkan D1 + alerte Discord
discord_notifier.py     → Notificateur Discord (⚠️ utilise build_scan_embed, pas d'embed brut)
src/
  sweep_detector.py     → Cœur ICT (sweeps, fib, niveaux)
  mt5_connector.py      → Connexion MT5
  config.py             → Configuration
```

### IchimokuSword (C:\Users\TSTAC\RustProjects\IchimokuSword)
```
analyze_flat_lines.py   → Analyse TOUTES les lignes plates (Kijun, Tenkan, SA, SB, SSB)
recommend_trade.py      → Scoring Ichimoku + recommandations
main.py                 → CLI (snapshot, watch, info, download)
src/
  ichimoku.py           → Calculs Ichimoku + detect_flat_bars/detect_flat_line + SSB
  display.py            → Affichage console
  scanner.py            → Scan multi-symboles
```

---

## 🐛 Bugs connus et pièges

### 1. `detect_flat_bars` — fenêtre glissante (CORRIGÉ le 13/07)
**Symptôme :** Rapportait faussement 39 barres plates alors que le drift total était de 0.19%.
**Cause :** Chaque itération utilisait `seg[0]` comme base (valeur différente à chaque fois).
**Fix :** Base fixe = valeur la plus récente. Contrôle GLOBAL max-min sur toute la fenêtre.
**Fichiers corrigés :** `IchimokuSword/src/ichimoku.py`, `IchimokuSword/recommend_trade.py`

### 2. Senkou B — confusion valeur actuelle vs valeur visible
**Piège :** `compute_senkou_span_b()` retourne la valeur PROJETÉE (+26 périodes).
La SSB affichée sur le graphique a été calculée il y a 26 périodes.
**Impact :** Analyser la mauvaise SSB peut faire rater une fausse cassure W1.

### 3. Doji sur bougie non fermée
**Piège :** Une bougie en cours (W1 le lundi) peut avoir un corps de 7% aujourd'hui
et finir à 80% vendredi. Ne jamais qualifier un pattern sur une bougie non clôturée.
**Formulation correcte :** « Structure de doji pour l'instant (non confirmé) »

### 4. Chikou passé plat — faux signal
**Pourquoi :** Le Chikou = le prix shifté de −26 barres. Un Chikou plat signifie
juste que le prix était stable il y a 26 bougies. Pas de pouvoir prédictif.
**Action :** Ignorer dans l'analyse prioritaire. Le garder comme note secondaire.

### 5. Tenkan W1 historique — niveau fantôme actif
**Piège :** Un Tenkan W1 resté plat pendant 3 semaines il y a 14 mois (ex: mai 2025 à 101.268)
continue d'agir comme résistance/support aujourd'hui. Le marché a une mémoire institutionnelle.
**Action :** Vérifier systématiquement l'historique Tenkan W1 pour les paires USD + DXY.

### 6. Nuage H4 — pullback sous-estimé
**Piège :** Un prix à 20 pips sous le nuage H4 peut sembler en sécurité, mais une bougie H4
peut couvrir cette distance. Si le SL est placé dans le nuage (pas au-dessus du top),
il risque de sauter sur un pullback technique normal.
**Action :** Comparer SL vs top du nuage (pas juste vs base).

### 8. TP fib dans le vide — ignorer les SSB obstacles
**Piège :** Le TP du scanner Asian est basé sur le fib −1.618, pas sur l'Ichimoku.
Il peut se trouver 20 pips sous le dernier support SSB, sans aucun niveau technique.
**Action :** Cartographier TOUS les SSB entre prix et TP1. Adapter la stratégie :
TP partiels sur les SSB proches + runner vers le fib.

### 9. Fake-out Tenkan W1 — micro-cassure puis rejet
**Piège :** Le prix peut franchir un niveau historique (Tenkan W1 plat) de quelques centièmes
de pourcent (+0.04%), donnant l'illusion d'une cassure confirmée, puis être rejeté dans les
heures qui suivent. C'est un **fake-out** classique sur les niveaux à mémoire institutionnelle.

**Exemple DXY (13/07/2026) :**
- 22h55 UTC : DXY 101.31, AU-DESSUS du Tenkan W1 101.27 (+0.04%) → faux signal haussier
- 02h59 UTC : DXY 101.20, EN-DESSOUS du Tenkan W1 101.27 (−0.06%) → rejet confirmé
- Conséquence : toutes les paires USD ont pullback, invalidant les SELLS EURUSD/AUDUSD/GBPUSD

**Mécanisme :** Un niveau W1 historique attire le prix comme un aimant. Le franchir
en intraday ne suffit pas — il faut une **clôture W1** au-dessus pour confirmer.
Tant que la bougie W1 n'est pas fermée (dimanche), tout franchissement est provisoire.

**Action :**
1. Ne jamais valider un biais USD sur une micro-cassure DXY (< 0.1% au-dessus du niveau)
2. Attendre la clôture W1 pour confirmer un franchissement de niveau W1
3. Si DXY fake-out → toutes les paires USD vont corriger dans le sens inverse
4. En cas de doute, attendre London (08h UTC) pour laisser le marché trancher

### 11. Compression multi-TF — zone de décision imminente
**Piège :** Quand le prix est compressé entre un support MN (ex: Kijun MN) et une résistance
W1 (ex: SSB), le marché peut sembler « calme » alors qu'il accumule de l'énergie pour un
mouvement violent. Ne pas confondre range et absence de direction.

**Exemple USDCAD (13/07/2026) :**
- Support : Kijun MN 1.41061 (double mémoire : Tenkan MN plat 4 mois en 2025)
- Résistance : SSB W1 1.41372 + Top nuage W1 1.41663 (Tenkan MN plat 4 mois aussi !)
- Écart total : 53 pips seulement → cassure imminente

**Action :**
1. Cartographier TOUS les niveaux MN et W1 dans la zone
2. Mesurer l'écart support/résistance
3. Préparer les DEUX scénarios avec SL/TP des deux côtés
4. Ne pas prendre position tant que la compression n'est pas résolue

### 12. Double mémoire institutionnelle — Tenkan MN plat = Kijun actuel
**Piège :** Un niveau peut avoir un poids DOUBLE sans que ce soit visible sur un seul
indicateur. Exemple : le Kijun MN actuel à 1.41061 était aussi le Tenkan MN plat de
fév-mai 2025. Le marché « se souvient » de ce niveau DEUX FOIS.

**Comment le détecter :**
1. Calculer le Kijun MN actuel
2. Scanner l'historique Tenkan MN pour trouver des périodes où il était plat à ce même niveau
3. Si trouvé → le niveau a une double mémoire = résistance/support 2× plus fort

**Exemples documentés :**
- USDCAD Kijun MN 1.41061 = Tenkan MN plat fév-mai 2025 (4 mois !)
- USDCAD Top nuage W1 1.41663 = Tenkan MN plat jui-oct 2025 (4 mois !)
- DXY Tenkan W1 101.27 = plat mai 2025 (niveau fantôme rejeté le 13/07/2026)

### 13. Omission des Tenkan D1 historiques — flat lines passées ignorées (CORRIGÉ le 14/07/2026)
**Symptôme :** Un scan recommandait EURJPY BUY à 185.300 avec SL à 185.039 et TP à 185.822.
Aucun obstacle n'était signalé. En réalité, deux Tenkan D1 plats historiques (185.299 et
185.307, juin 2026) formaient une résistance IMMÉDIATE à moins de 2 pips de l'entrée.
Le trade serait entré DANS une résistance.

**Cause :** Le script de scan Diamond (v1) ne vérifiait QUE les Kijun plats actuels
et les Kumo. Les Tenkan D1 historiques (mémoire institutionnelle) n'étaient pas inclus.

**Impact :** Tout trade peut buter sur un niveau fantôme invisible dans le scan.
Une flat line passée (même 2 jours seulement) garde une mémoire institutionnelle qui
agit comme aimant/répulsif.

**Fix (14/07/2026) :**
1. Ajout de l'Étape 3b — Détection SYSTÉMATIQUE des flat lines passées/présentes/futures
2. Le scan Diamond v2 inclut désormais `detect_tenkan_flat_history()` sur D1
3. Tout obstacle détecté entre prix et TP déclenche un avertissement
4. La pénalité de score (−1) s'applique si un flat est à moins de 10 pips du prix
5. Le seuil de détection est SCALÉ par type d'instrument (JPY vs non-JPY)

**Règle :** Ne JAMAIS recommander un trade sans avoir vérifié les Tenkan plats historiques
sur D1 (et W1/MN pour les niveaux structurels). Si le prix est à moins de 5 pips d'un
niveau historique, attendre la cassure confirmée avant d'entrer.

**Fichiers concernés :** `diamond-analysis-skill.md` (cette section), scripts de scan Diamond.

### 10. Discord — ne pas utiliser `discord_notifier.py` pour un embed personnalisé
**Problème :** `discord_notifier.py --json` appelle `build_scan_embed()` qui attend
des clés spécifiques (`scanned`, `trades`, `setups`...). Un embed brut sera ignoré.
**Solution :** Envoyer directement en HTTP :
```python
import json, urllib.request
# Lire webhook depuis .env (UTF-16 LE !)
with open('.env', 'rb') as f:
    raw = f.read()
text = raw.replace(b'\x00', b'').decode('ascii', errors='ignore')
url = [l.split('=',1)[1].strip() for l in text.split('\n') if l.startswith('DISCORD_WEBHOOK_URL=')][0]

payload = {"embeds": [{"title": "...", "description": "...", "color": 0x2ECC71}]}
data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
req = urllib.request.Request(url, data=data,
    headers={"Content-Type": "application/json; charset=utf-8"},
    method="POST")
urllib.request.urlopen(req, timeout=15)
```

---

## 🎨 Conventions d'affichage

### Couleurs Discord
| Contexte | Couleur | Code |
|----------|---------|------|
| Trade avec RR ≥ 1.0 | Vert | `0x2ECC71` |
| Alerte / attention | Orange | `0xE67E22` |
| Info / neutre | Bleu | `0x3498DB` |
| Analyse / setup | Violet | `0x9B59B6` |
| Erreur / danger | Rouge | `0xE74C3C` |

### Vocabulaire précis (pas de sensationnalisme)

| ❌ À éviter | ✅ À utiliser |
|-------------|---------------|
| « Cassure imminente » | « Compression détectée — le marché est en équilibre instable » |
| « DOJI PARFAIT » (bougie en cours) | « Structure de doji pour l'instant (non confirmé) » |
| « Trade explosif » | « Setup technique valide avec RR de X× » |
| « Va exploser » | « Le mouvement sera amplifié si la zone cède » |

### Formulation des scénarios
Toujours présenter **deux scénarios** :
1. Scénario aligné avec le trade (ex: cassure baissière)
2. Scénario alternatif (ex: rebond, invalidation)

Ne jamais présenter un trade comme une certitude.

---

## 🎯 Checklist finale avant de poster une analyse

- [ ] Scan Asian fait sur ≥ 8 symboles
- [ ] Ichimoku complet vérifié (Tenkan, Kijun, SA, SB, nuage)
- [ ] Flat lines analysées (Kijun, Tenkan, SA, SB, SSB) — PRÉSENTES
- [ ] **Flat lines PASSÉES vérifiées systématiquement (Étape 3b)** ⚠️
- [ ]   → Tenkan D1 historique (plats ≥ 2j proches du prix ou entre prix et TP ?)
- [ ]   → Tenkan W1 historique (plats ≥ 2sem proches du prix ?)
- [ ]   → Tenkan MN historique (plats ≥ 2mois proches du prix ? Double mémoire avec Kijun ?)
- [ ]   → Tenkan H4 historique (optionnel — intraday, vérifier si flat ≥ 10b proche)
- [ ] **Flat lines FUTURES surveillées** (Kijun/Tenkan en formation, 3-7 barres stables ?)
- [ ] Kijun plat ≥ 10B vérifié manuellement (global max-min)
- [ ] SSB proches (< 5 pips) identifiées
- [ ] DXY consulté (pour les paires USD)
- [ ] DXY Tenkan W1 historique vérifié (niveaux plats anciens proches du prix ?)
- [ ] DXY fake-out checké (micro-cassure < 0.1% au-dessus d'un niveau W1 historique = non confirmé)
- [ ] Kijun MN checké (position vs prix, combien de mois au-dessus ou en-dessous ?)
- [ ] Tenkan MN historique vérifié (plats ≥ 2 mois proches du prix ? Double mémoire avec Kijun ?)
- [ ] Nuage MN checké (transition de couleur ? prix dans/hors nuage ?)
- [ ] Compression multi-TF détectée (écart entre support MN et résistance W1 < 100 pips ?)
- [ ] Nuage H4 visible checké (risque de pullback ? SL positionné correctement vs top ?)
- [ ] SSB entre prix et TP1 cartographiées (combien d'obstacles ? TP partiels nécessaires ?)
- [ ] W1 nuage VISIBLE vérifié (pas la valeur future)
- [ ] Bougies W1 récentes inspectées (fausse cassure ? doji confirmé ?)
- [ ] Alignement TF compté (X/5 baissier ou haussier — MN inclus)
- [ ] Deux scénarios présentés (aligné + alternatif)
- [ ] Aucun sensationnalisme (« cassure imminente », « DOJI PARFAIT », etc.)
- [ ] RR affiché avec comparaison au meilleur trade du jour
- [ ] Discord : embed direct HTTP, pas via discord_notifier.py pour du contenu personnalisé
- [ ] **Aucun trade recommandé avec obstacle Tenkan/SSB non résolu entre prix et TP** ⚠️
