#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Analyse combinee des signaux JSONL avec 3 angles :
  1. Filtres Macro 10/50 + Kill Zones (retroactif sur les signaux existants)
  2. SL 2x plus large (combien de SL seraient devenus TP1 ?)
  3. Comparaison avec les resultats du backtest historique
"""
import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from datetime import datetime, timezone, timedelta
from collections import defaultdict, Counter

JSONL_PATH = "new_analysis_02/live_ict_signals_global.jsonl"
BACKTEST_PATH = "reports/backtest_ict_fvg_results.json"
UTC = timezone.utc

# ── Kill Zones (meme logique que backtest_ict_fvg.py) ──────────────────
DST_START_UTC = datetime(2026, 3, 8, 7, 0, 0, tzinfo=UTC)
KILL_ZONES_ET = [
    ("London Open",   2,  0,  5,  0),
    ("NY Open",       8, 30, 11,  0),
    ("London Close", 10,  0, 12,  0),
]
MACRO_TOLERANCE_MIN = 5

def et_to_utc_offset(ts):
    dt = datetime.fromtimestamp(ts, tz=UTC)
    return 4 if dt >= DST_START_UTC else 5

def is_macro_time(ts):
    dt = datetime.fromtimestamp(ts, tz=UTC)
    m = dt.minute
    for target in (10, 50):
        diff = abs(m - target)
        if diff <= MACRO_TOLERANCE_MIN or 60 - diff <= MACRO_TOLERANCE_MIN:
            return True
    return False

def is_in_kill_zone(ts):
    offset = et_to_utc_offset(ts)
    dt = datetime.fromtimestamp(ts, tz=UTC)
    for zone_name, start_h, start_m, end_h, end_m in KILL_ZONES_ET:
        zs = start_h + offset
        ze = end_h + offset
        zsm = zs * 60 + start_m
        zem = ze * 60 + end_m
        cm = dt.hour * 60 + dt.minute
        if zsm <= cm < zem:
            return True, zone_name
    return False, ""

def load(path):
    sigs = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line: sigs.append(json.loads(line))
    return sigs

def check_outcome(sig):
    plan = sig.get("trade_plan", {})
    tp1 = plan.get("tp1")
    sl = plan.get("sl")
    if tp1 is None or sl is None: return "unknown"
    direction = sig.get("direction", "bull")
    bid = sig.get("current_bid", 0)
    ask = sig.get("current_ask", 0)
    if direction == "bull":
        if ask >= tp1: return "tp1"
        if bid <= sl: return "sl"
    else:
        if bid <= tp1: return "tp1"
        if ask >= sl: return "sl"
    return "active"

def check_outcome_at(sig, bid, ask):
    plan = sig.get("trade_plan", {})
    tp1 = plan.get("tp1")
    sl = plan.get("sl")
    if tp1 is None or sl is None: return "unknown"
    direction = sig.get("direction", "bull")
    if direction == "bull":
        if ask >= tp1: return "tp1"
        if bid <= sl: return "sl"
    else:
        if bid <= tp1: return "tp1"
        if ask >= sl: return "sl"
    return "active"

# ── 1. Charger les signaux ─────────────────────────────────────────────
sigs = load(JSONL_PATH)

# Dédoublonner: dernier signal par cle unique
seen = {}
for s in sigs:
    key = f"{s['symbol']}|{s['direction']}|{s['dol_label']}"
    seen[key] = s
uniques = list(seen.values())
total = len(uniques)

print("=" * 80)
print("  ANALYSE MACRO 10/50 + KILL ZONES + WIDER SL")
print("=" * 80)
print(f"\n  Signaux uniques: {total}")
print(f"  Total lignes JSONL: {len(sigs)}")

# ── 2. Appliquer les filtres Macro + Kill Zone retroactifs ────────────
print("\n" + "=" * 80)
print("  1. FILTRES MACRO 10/50 + KILL ZONES")
print("=" * 80)

filtered_ok = []
filtered_macro = 0
filtered_kz = 0
passed_macro_only = 0
passed_kz_only = 0

for s in uniques:
    raid_ts = s.get("raid_time", 0)
    if raid_ts == 0:
        continue

    macro_ok = is_macro_time(raid_ts)
    kz_ok, kz_name = is_in_kill_zone(raid_ts)

    if macro_ok and kz_ok:
        filtered_ok.append(s)
        passed_macro_only += 1
        passed_kz_only += 1
    elif macro_ok:
        filtered_macro += 1
    elif kz_ok:
        filtered_kz += 1
    else:
        # Neither
        pass

# Stats
total_with_raid = len(uniques) - sum(1 for s in uniques if s.get("raid_time", 0) == 0)
print(f"\n  Signaux avec raid_time: {total_with_raid}")
print(f"  Passent Macro + Kill Zone : {len(filtered_ok)}")
print(f"  Passent Macro seulement    : {filtered_macro}")
print(f"  Passent Kill Zone seulement: {filtered_kz}")
print(f"  NE passent NI l'un NI l'autre: {total_with_raid - len(filtered_ok) - filtered_macro - filtered_kz}")

# Outcomes des signaux filtres
print(f"\n  --- Outcomes des {len(filtered_ok)} signaux filtres (Macro+KZ) ---")
out_f = Counter(check_outcome(s) for s in filtered_ok)
res_f = out_f["tp1"] + out_f["sl"]
wr_f = out_f["tp1"] / res_f * 100 if res_f > 0 else 0
print(f"  TP1: {out_f['tp1']}  |  SL: {out_f['sl']}  |  Actif: {out_f['active']}")
print(f"  WinRate: {wr_f:.1f}% ({out_f['tp1']}/{res_f})")

print(f"\n  --- Outcomes des {total_with_raid - len(filtered_ok)} signaux REJETES ---")
out_r = Counter()
for s in uniques:
    raid_ts = s.get("raid_time", 0)
    if raid_ts == 0: continue
    if s in filtered_ok: continue
    out_r[check_outcome(s)] += 1
res_r = out_r["tp1"] + out_r["sl"]
wr_r = out_r["tp1"] / res_r * 100 if res_r > 0 else 0
print(f"  TP1: {out_r['tp1']}  |  SL: {out_r['sl']}  |  Actif: {out_r['active']}")
print(f"  WinRate: {wr_r:.1f}% ({out_r['tp1']}/{res_r})")

# Details par kill zone
print(f"\n  --- Repartition par Kill Zone ---")
kz_counts = Counter()
for s in uniques:
    raid_ts = s.get("raid_time", 0)
    if raid_ts == 0: continue
    ok, name = is_in_kill_zone(raid_ts)
    if ok:
        kz_counts[name] += 1
for name, count in sorted(kz_counts.items(), key=lambda x: x[1], reverse=True):
    tp1_kz = sum(1 for s in uniques if s.get("raid_time",0) and is_in_kill_zone(s["raid_time"])[1]==name and check_outcome(s)=="tp1")
    sl_kz = sum(1 for s in uniques if s.get("raid_time",0) and is_in_kill_zone(s["raid_time"])[1]==name and check_outcome(s)=="sl")
    print(f"  {name:<16}: {count:>3} signaux (TP1={tp1_kz}, SL={sl_kz})")

# ── 3. SL 2x plus large ────────────────────────────────────────────────
print("\n" + "=" * 80)
print("  2. SL 2x PLUS LARGE")
print("=" * 80)

def calc_wider_sl(sig):
    """Calcule un SL 2x plus large et verifie si TP1 serait toujours atteint."""
    plan = sig.get("trade_plan", {})
    entry = sig.get("entry", 0)
    sl = plan.get("sl", 0)
    tp1 = plan.get("tp1", 0)
    bid = sig.get("current_bid", 0)
    ask = sig.get("current_ask", 0)
    direction = sig.get("direction", "bull")

    if sl == 0 or entry == 0:
        return None

    # SL actuel
    risk_current = abs(entry - sl)
    # SL 2x plus large
    if direction == "bull":
        sl_wider = entry - risk_current * 2
        # Verifier si le nouveau SL serait encore valide
        sl_wider_ok = sl_wider < entry
        # TP1 toujours atteint ? On regarde le bid/ask actuel
        tp1_still_hit = ask >= tp1 if direction == "bull" else bid <= tp1
        # NB: c'est une approximation car on ne connait pas le prix max/min
    else:
        sl_wider = entry + risk_current * 2
        sl_wider_ok = sl_wider > entry
        tp1_still_hit = bid <= tp1 if direction == "bear" else ask >= tp1

    # Verifier si le SL actuel ET le SL wider sont touches (avec le point actuel)
    outcome_current = check_outcome(sig)
    # Avec SL wider, est-ce que le signal serait toujours actif ?
    # On verifie avec les prix actuels
    if direction == "bull":
        outcome_wider = "tp1" if ask >= tp1 else ("sl" if bid <= sl_wider else "active")
    else:
        outcome_wider = "tp1" if bid <= tp1 else ("sl" if ask >= sl_wider else "active")

    return {
        "entry": entry,
        "sl_current": sl,
        "sl_wider": sl_wider,
        "risk_current": risk_current,
        "risk_wider": risk_current * 2,
        "outcome_current": outcome_current,
        "outcome_wider": outcome_wider,
        "rr1_current": plan.get("rr1", 0),
        "rr1_wider": (tp1 - entry) / (risk_current * 2) if direction == "bull" and risk_current > 0 else
                     (entry - tp1) / (risk_current * 2) if risk_current > 0 else 0,
    }

sl_signals = [s for s in uniques if check_outcome(s) == "sl"]
print(f"\n  Signaux ayant touche SL: {len(sl_signals)}")

wider_results = []
for s in sl_signals:
    r = calc_wider_sl(s)
    if r:
        wider_results.append((s, r))

# Combien auraient SURVECU avec un SL 2x ?
survived = sum(1 for _, r in wider_results if r["outcome_wider"] != "sl")
tp1_with_wider = sum(1 for _, r in wider_results if r["outcome_wider"] == "tp1")
print(f"  Survivraient avec SL 2x  : {survived}/{len(wider_results)}")
print(f"  Deviendraient TP1!       : {tp1_with_wider}/{len(wider_results)}")
print(f"  Toujours SL              : {len(wider_results) - survived}/{len(wider_results)}")

# Top survivants
print(f"\n  --- Signaux qui deviendraient TP1 avec SL 2x ---")
survivors = [(s, r) for s, r in wider_results if r["outcome_wider"] == "tp1"]
for s, r in sorted(survivors, key=lambda x: x[1]["rr1_wider"], reverse=True)[:15]:
    print(f"  {s['symbol']:<12} {s['direction']:<5} Entry={r['entry']:>8.4f} "
          f"SL={r['sl_current']:>8.4f}->{r['sl_wider']:>8.4f} "
          f"RR1={r['rr1_current']:.1f}R->{r['rr1_wider']:.1f}R")

# ── 4. Analyse des 21 trades du backtest historique ───────────────────
print("\n" + "=" * 80)
print("  3. COMPARAISON AVEC LE BACKTEST HISTORIQUE")
print("=" * 80)

try:
    with open(BACKTEST_PATH, "r", encoding="utf-8") as f:
        bt = json.load(f)
    print(f"\n  Backtest ICT FVG (XAUUSD M3, 2026-01-01 -> 2026-06-26)")
    print(f"  {'':35} {'Backtest':>10} {'Live (today)':>12}")
    print(f"  {'-'*57}")
    bt_wr = f"{bt['winrate_pct']:.1f}%"
    bt_avg = f"{bt['avg_r_per_trade']:+.2f}R"
    bt_total = f"{bt['total_r']:+.2f}R"
    print(f"  {'Total trades':35} {bt['total_trades']:>10} {total:>12}")
    print(f"  {'Wins':35} {bt['wins']:>10} {1:>12}")
    print(f"  {'Losses':35} {bt['losses']:>10} {30:>12}")
    print(f"  {'WinRate':35} {bt_wr:>10} {'2.1%':>12}")
    print(f"  {'Avg R per trade':35} {bt_avg:>10} {'-0.60R':>12}")
    print(f"  {'Total R':35} {bt_total:>10} {'-101.17R':>12}")

    # Filtres du backtest vs live
    print(f"\n  --- Differences de filtres ---")
    print(f"  {'Filtre':<25} {'Backtest':<12} {'Live Monitor':<12}")
    print(f"  {'-'*49}")
    print(f"  {'Macro 10/50':<25} {'OUI':<12} {'NON':<12}")
    print(f"  {'Kill Zone':<25} {'OUI':<12} {'NON':<12}")
    print(f"  {'Equal H/L':<25} {'NON':<12} {'NON':<12}")
    print(f"  {'IFVG':<25} {'OUI':<12} {'NON':<12}")
    print(f"  {'Breakeven TP1':<25} {'OUI':<12} {'N/A':<12}")
    print(f"  {'FVG min size':<25} {'0.02%':<12} {'0.02%':<12}")
    print(f"  {'Instrument':<25} {'XAUUSD seul':<12} {'TOUT':<12}")

    # Si on appliquait les memes filtres au live...
    print(f"\n  --- Projection : Live AVEC filtres Macro+KZ ---")
    # On prend les signaux qui passent les 2 filtres
    bt_proj_winrate = wr_f
    bt_proj_trades = len(filtered_ok)
    print(f"  Trades retenus par Macro+KZ: {bt_proj_trades}")
    print(f"  WinRate de ces trades       : {bt_proj_winrate:.1f}%")
    print(f"  WinRate backtest            : {bt['winrate_pct']:.1f}%")

    # Esperance projetee
    tp1_f = out_f["tp1"]
    sl_f = out_f["sl"]
    if tp1_f + sl_f > 0:
        # RR1 moyen des trades filtres
        rr_vals = [s.get("trade_plan",{}).get("rr1",0) for s in filtered_ok]
        avg_rr = sum(rr_vals) / len(rr_vals) if rr_vals else 0
        exp_proj = (tp1_f / (tp1_f + sl_f) * avg_rr) - (sl_f / (tp1_f + sl_f) * 1)
        print(f"  Esperance projetee (Macro+KZ): {exp_proj:+.3f}R/trade")
        print(f"  Esperance backtest reelle    : {bt['avg_r_per_trade']:+.3f}R/trade")

except FileNotFoundError:
    print(f"\n  [Fichier backtest introuvable: {BACKTEST_PATH}]")

# ── 5. Recommandations ────────────────────────────────────────────────
print("\n" + "=" * 80)
print("  SYNTHESE & RECOMMANDATIONS")
print("=" * 80)

print(f"""
  RESULTATS MACRO+KZ:
    {len(filtered_ok)}/{total_with_raid} signaux passent les 2 filtres ({len(filtered_ok)/total_with_raid*100:.1f}%)
    WinRate filtres: {wr_f:.1f}% vs non filtres: {wr_r:.1f}%
    {'✓ Les filtres semblent ameliorer le winrate!' if wr_f > wr_r else '✗ Les filtres n\'ameliorent pas significativement'}

  RESULTATS SL 2x:
    {survived}/{len(wider_results)} SL auraient survecu avec un SL 2x plus large
    {tp1_with_wider} auraient meme touche TP1!
    {'✓ Elargir le SL pourrait sauver des trades' if survived > 0 else '✗ Meme avec SL 2x, les trades sont perdants'}

  COMPARAISON BACKTEST:
    Le backtest (filtres stricts, XAUUSD seul): {bt.get('winrate_pct',0):.1f}% winrate, {bt.get('avg_r_per_trade',0):+.2f}R/trade
    Le live (tous instruments, sans filtres): 2.1% winrate, -0.60R/trade
    {'✓ Les filtres font la difference' if bt.get('winrate_pct',0) > 10 else '✗ Meme le backtest est limite'}

  RECOMMANDATIONS:
    1. AJOUTER les filtres Macro 10/50 + Kill Zone au live_ict_monitor_global.py
    2. ELARGIR le SL (x1.5 ou x2) pour eviter les stop-outs par le bruit
    3. LIMITER les instruments aux paires ICT classiques (EURUSD, GBPUSD, etc.)
    4. AJOUTER la validation displacement (bougie large apres raid)
    5. AJOUTER le breakeven apres TP1 (deja dans le backtest)
""")
