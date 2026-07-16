"""Script temporaire : analyse DXY Ichimoku complete."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mt5
from datetime import datetime, timezone
UTC = timezone.utc

SYM = "DXY"

def _get_rates(sym, tf, n=300):
    mt5.symbol_select(sym, True)
    r = mt5.copy_rates_from_pos(sym, tf, 0, n)
    if r is None or len(r) < 52:
        return None
    return [(int(x[0]), float(x[2]), float(x[3]), float(x[4])) for x in r]

def _tk(highs, lows):
    return (max(highs[-9:]) + min(lows[-9:])) / 2.0

def _kj(highs, lows):
    return (max(highs[-26:]) + min(lows[-26:])) / 2.0

def _ssb(highs, lows):
    return (max(highs[-52:]) + min(lows[-52:])) / 2.0

def _kumo_pos(price, highs, lows):
    n = len(highs)
    if n < 52: return "N/A"
    sa = (_tk(highs, lows) + _kj(highs, lows)) / 2.0
    sb = _ssb(highs, lows)
    ct, cb = max(sa, sb), min(sa, sb)
    return "ABOVE" if price > ct else ("BELOW" if price < cb else "INSIDE")

def _flat_detect(vals, thresh=0.02):
    """Detect flat segments in a value series."""
    flats = []
    cur = []
    for i, v in enumerate(vals):
        if not cur:
            cur = [(i, v)]
        elif abs(v - cur[-1][1]) < thresh:
            cur.append((i, v))
        else:
            if len(cur) >= 3:
                flats.append((cur[0][0], cur[-1][0], sum(x[1] for x in cur)/len(cur), len(cur)))
            cur = [(i, v)]
    if len(cur) >= 3:
        flats.append((cur[0][0], cur[-1][0], sum(x[1] for x in cur)/len(cur), len(cur)))
    return flats

def _pct_dist(price, level):
    return (price - level) * 100  # DXY = index, use direct difference

if not mt5.initialize():
    print("ERREUR: MT5 init failed")
    sys.exit(1)

print(f"\n{'='*80}")
print(f"  DXY ANALYSIS COMPLETE — {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')} UTC")
print(f"{'='*80}")

# Get price
mt5.symbol_select(SYM, True)
t = mt5.symbol_info_tick(SYM)
if not t:
    print("ERREUR: cannot get DXY tick")
    mt5.shutdown()
    sys.exit(1)
price = t.bid
print(f"\n  DXY Prix: {price:.3f}")

# Get rates for all TFs
TF_MAP = {
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
    "W1": mt5.TIMEFRAME_W1,
    "MN": mt5.TIMEFRAME_MN1,
}

print(f"\n{'─'*80}")
print(f"  NIVEAUX ICHIMOKU PAR TF")
print(f"{'─'*80}")
print(f"  {'TF':<6} {'Tenkan':>10} {'Kijun':>10} {'SSB':>10} {'TKx':>6} {'Kumo':>8} {'Dist KJ':>10}")
print(f"  {'─'*5} {'─'*10} {'─'*10} {'─'*10} {'─'*6} {'─'*8} {'─'*10}")

for tf_name, tf_val in TF_MAP.items():
    rates = _get_rates(SYM, tf_val, 300)
    if rates is None or len(rates) < 52:
        print(f"  {tf_name:<6} {'N/A':>10} {'N/A':>10} {'N/A':>10} {'N/A':>6} {'N/A':>8} {'N/A':>10}")
        continue
    highs = [r[2] for r in rates]
    lows = [r[3] for r in rates]
    tk_v = _tk(highs, lows)
    kj_v = _kj(highs, lows)
    sb_v = _ssb(highs, lows)
    tkx = "BULL" if tk_v > kj_v else ("BEAR" if tk_v < kj_v else "FLAT")
    kumo = _kumo_pos(price, highs, lows)
    dist = price - kj_v
    print(f"  {tf_name:<6} {tk_v:>10.3f} {kj_v:>10.3f} {sb_v:>10.3f} {tkx:>6} {kumo:>8} {dist:>+8.3f}")

# Detect flat levels on D1 and W1
print(f"\n{'─'*80}")
print(f"  DÉTECTION FLAT LEVELS MÉMOIRE")
print(f"{'─'*80}")

for tf_name, tf_val in [("D1", mt5.TIMEFRAME_D1), ("W1", mt5.TIMEFRAME_W1), ("MN", mt5.TIMEFRAME_MN1)]:
    rates = _get_rates(SYM, tf_val, 300)
    if rates is None or len(rates) < 52:
        continue
    highs = [r[2] for r in rates]
    lows = [r[3] for r in rates]
    timestamps = [r[0] for r in rates]
    
    # Tenkan values over time
    tk_vals = []
    for i in range(8, len(highs)):
        tk = (max(highs[i-8:i+1]) + min(lows[i-8:i+1])) / 2.0
        tk_vals.append(tk)
    
    # Kijun values over time
    kj_vals = []
    for i in range(25, len(highs)):
        kj = (max(highs[i-25:i+1]) + min(lows[i-25:i+1])) / 2.0
        kj_vals.append(kj)
    
    # Detect flats (threshold: 0.03 for DXY)
    tk_flats = _flat_detect(tk_vals, 0.03)
    kj_flats = _flat_detect(kj_vals, 0.03)
    
    if tk_flats:
        print(f"\n  {tf_name} — Tenkan FLATS (memoire):")
        for start, end, avg, count in tk_flats[:5]:
            dt_start = datetime.fromtimestamp(timestamps[start+8], UTC).strftime('%d/%m/%Y')
            dt_end = datetime.fromtimestamp(timestamps[end+8], UTC).strftime('%d/%m/%Y')
            dist = price - avg
            direction = "SUPPORT" if dist > 0 else "RESISTANCE"
            print(f"    {avg:>8.3f} ({dist:+.3f}p, {count} bars, {dt_start}-{dt_end}) {direction}")
    
    if kj_flats:
        print(f"\n  {tf_name} — Kijun FLATS (memoire):")
        for start, end, avg, count in kj_flats[:5]:
            dt_start = datetime.fromtimestamp(timestamps[start+25], UTC).strftime('%d/%m/%Y')
            dt_end = datetime.fromtimestamp(timestamps[end+25], UTC).strftime('%d/%m/%Y')
            dist = price - avg
            direction = "SUPPORT" if dist > 0 else "RESISTANCE"
            print(f"    {avg:>8.3f} ({dist:+.3f}p, {count} bars, {dt_start}-{dt_end}) {direction}")

# Analyse sweep
print(f"\n{'─'*80}")
print(f"  ANALYSE SWEEP — Niveaux clefs")
print(f"{'─'*80}")
print(f"  DXY actuel: {price:.3f}")
print(f"  Kijun H1: ... (see above)")
print(f"  Tenkan H1: ... (see above)")

# Identify key levels from earlier today
print(f"\n  Niveaux références aujourd'hui:")
print(f"    100.931 — DXY hier soir (23:33 UTC) — début de journée")
print(f"    101.27  — Tenkan W1 (testé/fake-out hier soir)")
print(f"    100.263 — Tenkan W1 actuel (hier)")
print(f"    100.681 — Kijun H1 actuel")
print(f"    100.501 — DXY MAINTENANT")

# Check if swept key levels
# From earlier scans: DXY Kijun H1 was 100.883 at 23:33 UTC
# Now Kijun H1 is 100.681
# DXY has dropped from 100.931 to 100.501 = -0.43 points

print(f"\n  Mouvement du jour: 100.931 → 100.501 = -0.430 points")
print(f"  Tenkan W1 (scope conversation): ~100.263")
print(f"  Distance au Tenkan W1: {price - 100.263:.3f} points")

mt5.shutdown()
print(f"\n{'='*80}\n")
