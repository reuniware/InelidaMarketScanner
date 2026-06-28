# ALGORITHME ICT FVG — Stratégie de Trading SMC/ICT en 5 Étapes

> **Version** : 2.0 — Juin 2026
> **Auteur** : Généré depuis backtest_ict_fvg.py
> **Langage** : Pseudo-code agnostique (implémentable en Python, MQL5, Pine Script, etc.)

---

## Résumé

Stratégie de trading basée sur les Smart Money Concepts (SMC) / Inner Circle Trader (ICT).
L'algorithme détecte des opportunités de trade en 5 étapes séquentielles :

1. Identifier un **Draw On Liquidity** (cible magnétique du prix)
2. Attendre un **raid de liquidité opposée** validé par macro et kill zone
3. Entrer sur le **1er FVG ou IFVG** après retracement dans la zone
4. Placer un **Stop Loss dur** au-delà de la bougie #1 du FVG
5. Sortir mécaniquement : **50% au milieu, 50% avant le DOL**, breakeven après TP1

---

## Données d'entrée

```
Input: OHLCV bars avec timeframe ≤ M5 (recommandé M1 ou M3)

Chaque barre = {
    time:   timestamp Unix (UTC)
    open:   float
    high:   float
    low:    float
    close:  float
    volume: int (optionnel)
}
```

---

## Configuration (paramètres ajustables)

```
USE_PDH_PDL        = true      // Utiliser Previous Day High/Low comme DOL
USE_ASIAN_HL        = true      // Utiliser Asian Session High/Low comme DOL
USE_NWOG            = true      // Utiliser New Week Opening Gap comme DOL

REQUIRE_MACRO       = true      // Exiger macro 10/50 sur le raid
REQUIRE_KILL_ZONE   = true      // Exiger kill zone ICT sur le raid
REQUIRE_EQUAL_HL    = false     // Exiger equal highs/lows sweep

MACRO_TOLERANCE_MIN = 5         // ± minutes autour de :10 et :50
FVG_MIN_SIZE_PCT    = 0.02      // Taille minimum du FVG en % du prix
MAX_FVG_LOOKFORWARD = 240       // Barres max pour trouver un FVG après le raid
MAX_RETRACE_LOOK    = 120       // Barres max pour attendre le retracement dans le FVG
MAX_RAID_LOOKBACK   = 480       // Barres max de lookback pour trouver un raid
MIN_DOL_DISTANCE_PCT = 0.15     // Distance minimum Entry→DOL en % du prix

BREAKEVEN_AFTER_TP1 = true      // Déplacer le SL au breakeven après TP1
```

---

## ÉTAPE 1 — Identifier le Draw On Liquidity (DOL)

### Principe ICT
Le prix cherche toujours à atteindre de la liquidité. Avant tout trade, déterminer où le prix se dirige :
- Si le prix est haussier, le DOL est **au-dessus** du range actuel
- Si le prix est baissier, le DOL est **en dessous**

### Sources de DOL

#### 1a. Previous Day High / Low (PDH/PDL)
```
FUNCTION compute_pdh_pdl(day_str, all_days):
    prev_day = jour_de_trading_précédent(day_str)
    IF prev_day existe:
        pdh = max(bar.high for bar in all_days[prev_day])
        pdl = min(bar.low  for bar in all_days[prev_day])
        
        // PDH comme cible haussière → liquidité opposée = PDL (SSL raid)
        DOL_PAIRS.add({ dol: pdh, direction: BULL, opposing: pdl, raid_type: SSL })
        
        // PDL comme cible baissière → liquidité opposée = PDH (BSL raid)
        DOL_PAIRS.add({ dol: pdl, direction: BEAR, opposing: pdh, raid_type: BSL })
```

#### 1b. Asian Session High / Low (00:00–08:00 UTC)
```
FUNCTION compute_asian_hl(bars_today):
    asian_bars = bars WHERE hour IN [0, 8[
    IF len(asian_bars) >= 2:
        ah = max(bar.high for bar in asian_bars)
        al = min(bar.low  for bar in asian_bars)
        
        DOL_PAIRS.add({ dol: ah, direction: BULL, opposing: al, raid_type: SSL })
        DOL_PAIRS.add({ dol: al, direction: BEAR, opposing: ah, raid_type: BSL })
```

#### 1c. New Week Opening Gap (NWOG)
```
FUNCTION compute_nwog(day_str, all_days):
    IF day_str est un LUNDI:
        prev_friday = vendredi_précédent(day_str, all_days)
        IF prev_friday existe:
            friday_close = all_days[prev_friday].last.close
            monday_open  = all_days[day_str].first.open
            
            gap_top    = max(friday_close, monday_open)
            gap_bottom = min(friday_close, monday_open)
            
            IF gap_top > gap_bottom:  // gap existe
                DOL_PAIRS.add({ dol: gap_top,    direction: BULL, opposing: gap_bottom, raid_type: SSL })
                DOL_PAIRS.add({ dol: gap_bottom, direction: BEAR, opposing: gap_top,    raid_type: BSL })
```

---

## ÉTAPE 2 — Attendre un Raid de Liquidité Opposée

### Principe ICT
Ne pas chasser le prix vers le DOL. Attendre que le prix balaye la liquidité **opposée** d'abord (phase de manipulation / "judas swing"). Le raid doit survenir pendant ou immédiatement après une **fenêtre macro 10/50** ET dans une **kill zone**.

### 2a. Détection du raid

```
FUNCTION is_ssl_raid(bar, level):
    // SSL = Sell Side Liquidity : prix passe SOUS le niveau + close rejette AU-DESSUS
    RETURN bar.low < level AND bar.close > level

FUNCTION is_bsl_raid(bar, level):
    // BSL = Buy Side Liquidity : prix passe AU-DESSUS du niveau + close rejette EN-DESSOUS
    RETURN bar.high > level AND bar.close < level

FUNCTION find_raid(bars, ref_idx, level, raid_type, max_lookback):
    FOR i FROM ref_idx-1 DOWNTO ref_idx-max_lookback:
        IF raid_type == "SSL" AND is_ssl_raid(bars[i], level):
            RETURN (i, bars[i])
        IF raid_type == "BSL" AND is_bsl_raid(bars[i], level):
            RETURN (i, bars[i])
    RETURN null
```

### 2b. Validation macro 10/50

```
// Heures ET (Eastern Time) avec gestion DST
DST_START_2026 = 2026-03-08 07:00 UTC  // 2e dimanche de mars

FUNCTION et_offset(ts):
    IF ts >= DST_START_2026: RETURN 4  // EDT = UTC-4
    ELSE:                    RETURN 5  // EST = UTC-5

FUNCTION is_macro_time(ts):
    minute = timestamp_to_utc(ts).minute
    FOR target IN [10, 50]:
        diff = abs(minute - target)
        IF diff <= MACRO_TOLERANCE_MIN OR (60 - diff) <= MACRO_TOLERANCE_MIN:
            RETURN true
    RETURN false
```

### 2c. Validation kill zone

```
KILL_ZONES_ET = [
    ("London Open",    2, 0,  5, 0),   // 2:00-5:00 AM ET
    ("NY Open",        8, 30, 11, 0),   // 8:30-11:00 AM ET
    ("London Close",  10, 0,  12, 0),   // 10:00 AM-12:00 PM ET
]

FUNCTION is_in_kill_zone(ts):
    offset = et_offset(ts)
    utc_hour   = timestamp_to_utc(ts).hour
    utc_minute = timestamp_to_utc(ts).minute
    current_minutes = utc_hour * 60 + utc_minute
    
    FOR EACH (name, start_h, start_m, end_h, end_m) IN KILL_ZONES_ET:
        zone_start = (start_h + offset) * 60 + start_m
        zone_end   = (end_h   + offset) * 60 + end_m
        IF zone_start <= current_minutes < zone_end:
            RETURN (true, name)
    RETURN (false, "")
```

### 2d. Validation equal highs/lows (optionnelle)

```
FUNCTION has_equal_highs(bars, ref_idx, raid_level):
    swing_highs = find_swing_highs(bars, ref_idx, lookback=96)
    tolerance = raid_level * 0.08 / 100
    cluster = [h for h in swing_highs if abs(h - raid_level) < tolerance]
    RETURN len(cluster) >= 2

FUNCTION has_equal_lows(bars, ref_idx, raid_level):
    swing_lows = find_swing_lows(bars, ref_idx, lookback=96)
    tolerance = raid_level * 0.08 / 100
    cluster = [l for l in swing_lows if abs(l - raid_level) < tolerance]
    RETURN len(cluster) >= 2
```

### 2e. Validation complète du raid

```
FUNCTION validate_raid(bars, raid_idx, raid_bar, level, raid_type):
    IF REQUIRE_MACRO AND NOT is_macro_time(raid_bar.time):
        RETURN (false, "hors_macro")
    
    IF REQUIRE_KILL_ZONE:
        (in_kz, kz_name) = is_in_kill_zone(raid_bar.time)
        IF NOT in_kz:
            RETURN (false, "hors_kill_zone")
    
    IF REQUIRE_EQUAL_HL:
        IF raid_type == "BSL" AND NOT has_equal_highs(bars, raid_idx, level):
            RETURN (false, "pas_equal_highs")
        IF raid_type == "SSL" AND NOT has_equal_lows(bars, raid_idx, level):
            RETURN (false, "pas_equal_lows")
    
    RETURN (true, "ok")
```

---

## ÉTAPE 3 — Entrée sur le 1er FVG ou l'IFVG

### Principe ICT
Après le raid, le prix crée un **déplacement** (displacement). Deux options d'entrée :

### 3a. Option A — Premier FVG (Fair Value Gap)

```
// FVG = déséquilibre en 3 bougies consécutives
// La bougie médiane (C2) ne chevauche ni C1 ni C3

FUNCTION find_fvg(bars, idx, direction):
    IF idx < 2: RETURN null
    
    c1 = bars[idx - 2]
    c3 = bars[idx]
    
    IF direction == BULL:
        // FVG haussier : C1.high < C3.low
        IF c1.high >= c3.low: RETURN null
        zone_top    = c3.low
        zone_bottom = c1.high
    ELSE:
        // FVG baissier : C1.low > C3.high
        IF c1.low <= c3.high: RETURN null
        zone_top    = c1.low
        zone_bottom = c3.high
    
    gap_size = zone_top - zone_bottom
    gap_pct  = gap_size / zone_bottom * 100
    
    IF gap_pct < FVG_MIN_SIZE_PCT: RETURN null
    
    RETURN {
        type:        direction == BULL ? "bullish" : "bearish",
        zone_top:    zone_top,
        zone_bottom: zone_bottom,
        c1_bar:      c1,
        gap_size:    gap_size,
        gap_pct:     gap_pct,
    }

FUNCTION scan_first_fvg_after(bars, start_idx, direction, max_look):
    FOR i FROM start_idx+3 TO start_idx+max_look:
        fvg = find_fvg(bars, i, direction)
        IF fvg != null: RETURN (i, fvg)
    RETURN null
```

### 3b. Option B — IFVG (Inverse Fair Value Gap)

```
// IFVG = FVG formé dans la direction OPPOSÉE au DOL
// (sur la jambe de manipulation), qui a été traversé par le prix
// (donc "inversé"), et dont le prix est revenu dans la zone

FUNCTION find_ifvg(bars, start_idx, end_idx, dol_direction):
    opposite_dir = (dol_direction == BULL) ? BEAR : BULL
    
    FOR i FROM start_idx+3 TO end_idx:
        fvg = find_fvg(bars, i, opposite_dir)
        IF fvg == null: CONTINUE
        
        // Vérifier que le prix a traversé le FVG dans la direction du DOL
        inverted   = false
        inv_bar_idx = null
        FOR j FROM i+1 TO end_idx:
            IF dol_direction == BULL AND bars[j].high > fvg.zone_top:
                inverted = true; inv_bar_idx = j; BREAK
            IF dol_direction == BEAR AND bars[j].low < fvg.zone_bottom:
                inverted = true; inv_bar_idx = j; BREAK
        
        IF NOT inverted: CONTINUE
        
        // Chercher retracement dans la zone APRES l'inversion
        FOR j FROM inv_bar_idx+1 TO end_idx:
            bar = bars[j]
            IF bar.low <= fvg.zone_top AND bar.high >= fvg.zone_bottom:
                entry_price = (fvg.zone_top + fvg.zone_bottom) / 2
                IF bar.low <= entry_price <= bar.high:
                    RETURN (j, fvg)  // entrée au midpoint de la zone IFVG
    
    RETURN null
```

### 3c. Retracement dans le FVG (trigger d'entrée)

```
FUNCTION wait_for_fvg_retrace(bars, fvg_idx, fvg, max_look):
    entry_target = (fvg.zone_top + fvg.zone_bottom) / 2
    
    FOR i FROM fvg_idx+1 TO fvg_idx+max_look:
        bar = bars[i]
        IF bar.low <= entry_target <= bar.high:
            RETURN (i, entry_target)
    
    RETURN null  // pas de retracement → pas d'entrée
```

---

## ÉTAPE 4 — Stop Loss Dur

### Principe ICT
Le risque est mécanique, sans discrétion. Le SL est ancré sur la bougie #1 du FVG utilisé pour l'entrée.

```
FUNCTION compute_sl(fvg, direction):
    c1 = fvg.c1_bar
    buffer = fvg.gap_size * 0.2  // buffer anti-spread/slippage
    
    IF direction == BULL:
        sl = c1.low - buffer
        // Validation : SL doit être sous l'entrée
        IF sl >= entry_price: INVALID
    ELSE:
        sl = c1.high + buffer
        // Validation : SL doit être au-dessus de l'entrée
        IF sl <= entry_price: INVALID
    
    RETURN sl
```

### Taille de position (hors backtest — pour execution live)

```
risk_amount  = capital * 0.01           // 1% du compte
risk_per_unit = abs(entry - stop_loss)  // en valeur monétaire
position_size = risk_amount / risk_per_unit
```

---

## ÉTAPE 5 — Sorties Mécaniques

### Principe ICT
Deux sorties systématiques. Pas de trailing, pas d'espoir.

```
FUNCTION compute_take_profits(entry, dol, direction, gap_size):
    IF direction == BULL:
        tp1 = entry + (dol - entry) * 0.5       // 50% au milieu
        tp2 = dol - gap_size                     // juste avant le DOL
    ELSE:
        tp1 = entry - (entry - dol) * 0.5       // 50% au milieu
        tp2 = dol + gap_size                     // juste avant le DOL
    RETURN (tp1, tp2)
```

### Simulation du trade (forward-test)

```
FUNCTION simulate_trade(bars, entry_idx, entry, sl, tp1, tp2, direction):
    risk   = abs(entry - sl)
    current_sl = sl
    
    FOR i FROM entry_idx+1 TO len(bars)-1:
        bar = bars[i]
        
        IF direction == BULL:
            IF bar.low <= current_sl:
                RETURN { status: LOSS, pnl_r: -1.0 }
            
            IF NOT tp1_hit AND bar.high >= tp1:
                tp1_hit = true
                IF BREAKEVEN_AFTER_TP1:
                    current_sl = entry  // ← breakeven !
            
            IF tp1_hit AND bar.high >= tp2:
                r1 = (tp1 - entry) / risk
                r2 = (tp2 - entry) / risk
                RETURN { status: WIN_FULL, pnl_r: 0.5 * r1 + 0.5 * r2 }
        
        ELSE:  // BEAR
            IF bar.high >= current_sl:
                RETURN { status: LOSS, pnl_r: -1.0 }
            
            IF NOT tp1_hit AND bar.low <= tp1:
                tp1_hit = true
                IF BREAKEVEN_AFTER_TP1:
                    current_sl = entry  // ← breakeven !
            
            IF tp1_hit AND bar.low <= tp2:
                r1 = (entry - tp1) / risk
                r2 = (entry - tp2) / risk
                RETURN { status: WIN_FULL, pnl_r: 0.5 * r1 + 0.5 * r2 }
    
    // Fin des données sans SL ni TP2 touché
    IF tp1_hit:
        RETURN { status: WIN_PARTIAL, pnl_r: 0.5 * r1 }
    RETURN { status: OPEN, pnl_r: 0.0 }
```

---

## Algorithme Principal

```
FUNCTION run_backtest(bars):
    days = group_bars_by_day(bars)
    trading_days = sorted(days WHERE NOT is_weekend(day))
    
    trades = []
    
    FOR EACH day IN trading_days:
        day_bars = days[day]
        IF len(day_bars) < 20: CONTINUE
        
        pairs = compute_all_dol_pairs(day, days, day_bars)
        
        FOR EACH pair IN pairs:
            // ÉTAPE 1 : DOL déjà identifié dans la pair
            
            // ÉTAPE 2 : Chercher un raid de la liquidité OPPOSÉE
            raid = find_raid(bars, day_end_idx, pair.opposing_level, pair.raid_type)
            IF raid == null: CONTINUE
            
            // Valider le raid (macro, kill zone, equal H/L)
            (valid, reason) = validate_raid(bars, raid.idx, raid.bar, pair.opposing_level, pair.raid_type)
            IF NOT valid: CONTINUE
            
            // ÉTAPE 3 : Chercher le 1er FVG après le raid
            fvg_result = scan_first_fvg_after(bars, raid.idx, pair.direction)
            
            IF fvg_result != null:
                // Option A : FVG standard
                retrace = wait_for_fvg_retrace(bars, fvg_result.idx, fvg_result.fvg)
                IF retrace != null:
                    (entry_idx, entry_price) = retrace
                ELSE IF USE_IFVG:
                    // Option B : IFVG (fallback)
                    ifvg_result = find_ifvg(bars, raid.idx, day_end_idx, pair.direction)
                    IF ifvg_result != null:
                        (entry_idx, entry_fvg) = ifvg_result
                        entry_price = (entry_fvg.zone_top + entry_fvg.zone_bottom) / 2
                    ELSE:
                        CONTINUE
                ELSE:
                    CONTINUE
            ELSE IF USE_IFVG:
                ifvg_result = find_ifvg(bars, raid.idx, day_end_idx, pair.direction)
                IF ifvg_result != null:
                    (entry_idx, entry_fvg) = ifvg_result
                    entry_price = (entry_fvg.zone_top + entry_fvg.zone_bottom) / 2
                ELSE:
                    CONTINUE
            ELSE:
                CONTINUE
            
            // Vérifier distance minimum au DOL
            IF pair.direction == BULL AND (pair.dol - entry_price) / entry_price * 100 < MIN_DOL_DISTANCE_PCT:
                CONTINUE
            IF pair.direction == BEAR AND (entry_price - pair.dol) / entry_price * 100 < MIN_DOL_DISTANCE_PCT:
                CONTINUE
            
            // ÉTAPE 4 : Calculer le Stop Loss
            sl = compute_sl(entry_fvg, pair.direction)
            IF sl invalide: CONTINUE
            
            // ÉTAPE 5 : Calculer les Take Profits
            (tp1, tp2) = compute_take_profits(entry_price, pair.dol, pair.direction, entry_fvg.gap_size)
            
            // Simuler le trade
            result = simulate_trade(bars, entry_idx, entry_price, sl, tp1, tp2, pair.direction)
            trades.append({ day, pair, raid, fvg, entry_price, sl, tp1, tp2, ...result })
    
    RETURN compute_stats(trades)
```

---

## Résultats backtestés (XAUUSD M3, Jan–Juin 2026)

### Version sans filtre (v1)
| Métrique | Valeur |
|----------|--------|
| Trades | 214 |
| Winrate | 17.8% |
| R moyen | +0.49R |
| R total | +105.08R |

### Version avec filtres ICT complets (v2)
| Métrique | Valeur |
|----------|--------|
| Trades | 21 |
| Winrate | 19.0% |
| R moyen | +0.89R |
| R total | +18.66R |
| Raids filtrés | 276/297 (93%) |

### Recommandation
- **Production** : utiliser la v1 (sans filtres) pour maximiser le R total (+105R)
- **Qualité** : utiliser la v2 pour un meilleur winrate et R/trade, au prix de beaucoup moins d'opportunités
- **Hybride recommandé** : v1 + filtre FVG gap > 0.05% + distance Entry→DOL < 2.0% (meilleur compromis)

---

## Dépendances externes (pour implémentation live)

- **Données de prix OHLCV** : MetaTrader 5, Binance API, Yahoo Finance, etc.
- **Timezone** : UTC obligatoire pour les calculs de session et kill zones
- **Calendrier** : Détection des week-ends (samedi/dimanche) et jours fériés
- **Broker** : Pour l'exécution live, adapter la taille de position au contrat (lot size, tick value)

---

## Glossaire ICT

| Terme | Définition |
|-------|-----------|
| **DOL** | Draw On Liquidity — cible magnétique du prix |
| **FVG** | Fair Value Gap — déséquilibre 3 bougies sans chevauchement C1-C3 |
| **IFVG** | Inverse FVG — FVG traversé par le prix, devenu support/résistance |
| **BSL** | Buy Side Liquidity — stops au-dessus des plus hauts |
| **SSL** | Sell Side Liquidity — stops en dessous des plus bas |
| **PDH/PDL** | Previous Day High / Low |
| **NWOG** | New Week Opening Gap — gap vendredi close → lundi open |
| **Macro 10/50** | Fenêtre de 2-4 min autour de :10 et :50 de chaque heure |
| **Kill Zone** | London Open (2-5h ET), NY Open (8:30-11h ET), London Close (10h-12h ET) |
| **R** | Unité de risque — 1R = perte maximale acceptée sur le trade |
