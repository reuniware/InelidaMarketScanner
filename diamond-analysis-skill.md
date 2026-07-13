# Diamond Analysis Skill — Analyse multi-TF complète ICT × Ichimoku

Ce fichier documente la méthodologie d'analyse développée pendant la session du 13 juillet 2026.
Il permet de reproduire le même niveau de profondeur d'analyse pour n'importe quel symbole.

---

## 📋 Pipeline d'analyse (ordre à suivre)

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

## 🔬 Matrice d'alignement Ichimoku

Pour chaque trade, construire cette matrice :

| TF | Prix vs Kijun | Nuage | Flat Lines | SSB proches | Biais |
|----|:---:|:---:|:---|:---|:---:|
| H1 | ±X% | Vert/Rouge | Kijun XB, Tenkan XB | Support/Res à X pips | 🔼/🔽 |
| H4 | ±X% | Vert/Rouge | ... | ... | 🔼/🔽 |
| D1 | ±X% | Vert/Rouge | ... | ... | 🔼/🔽 |
| W1 | ±X% | Vert/Rouge | ... | ... | 🔼/🔽 |

- **4/4 TF aligné** = trade le plus fiable
- **3/4 TF aligné** = acceptable
- **2/4 TF aligné** = conflit, risque élevé

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

### 5. Discord — ne pas utiliser `discord_notifier.py` pour un embed personnalisé
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
- [ ] Flat lines analysées (Kijun, Tenkan, SA, SB, SSB)
- [ ] Kijun plat ≥ 10B vérifié manuellement (global max-min)
- [ ] SSB proches (< 5 pips) identifiées
- [ ] DXY consulté (pour les paires USD)
- [ ] W1 nuage VISIBLE vérifié (pas la valeur future)
- [ ] Bougies W1 récentes inspectées (fausse cassure ? doji confirmé ?)
- [ ] Alignement TF compté (X/4 baissier ou haussier)
- [ ] Deux scénarios présentés (aligné + alternatif)
- [ ] Aucun sensationnalisme (« cassure imminente », « DOJI PARFAIT », etc.)
- [ ] RR affiché avec comparaison au meilleur trade du jour
- [ ] Discord : embed direct HTTP, pas via discord_notifier.py pour du contenu personnalisé
