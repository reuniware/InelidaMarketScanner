#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Analyse des signaux JSONL avec granularite optimale."""
import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from collections import defaultdict, Counter

JSONL_PATH = "new_analysis_02/live_ict_signals_global.jsonl"

def check_outcome(sig):
    plan = sig.get("trade_plan", {})
    tp1 = plan.get("tp1")
    sl = plan.get("sl")
    if tp1 is None or sl is None:
        return "unknown"
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

def load(path):
    sigs = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line: sigs.append(json.loads(line))
    return sigs

def classify_rr(rr):
    if rr >= 10: return "10+R"
    if rr >= 5: return "5-10R"
    if rr >= 3: return "3-5R"
    if rr >= 2: return "2-3R"
    if rr >= 1: return "1-2R"
    return "<1R"

def classify_fvg(gap):
    if gap >= 0.5: return ">=0.5%"
    if gap >= 0.2: return "0.2-0.5%"
    if gap >= 0.1: return "0.1-0.2%"
    if gap >= 0.05: return "0.05-0.1%"
    return "<0.05%"

def classify_dol(pct):
    if pct >= 5: return ">=5%"
    if pct >= 3: return "3-5%"
    if pct >= 1: return "1-3%"
    return "<1%"

def hr(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")

def show(rows, fmt):
    """Show table with f-string formatting.
    fmt is a dict {header: (just, width)} where just='L'|'R'|'C' and width is int.
    """
    if not rows:
        return
    headers_list = list(fmt.keys())
    widths_list = [v[1] for v in fmt.values()]
    justs_list = [v[0] for v in fmt.values()]
    # header
    hdr = " ".join(h.center(w) for h, w in zip(headers_list, widths_list))
    print(f"  {hdr}")
    print(f"  {'-'*(len(hdr))}")
    for r in rows:
        parts = []
        for i in range(len(headers_list)):
            val = str(r[i]) if i < len(r) else ""
            w = widths_list[i]
            just = justs_list[i]
            if just == "L":
                parts.append(val.ljust(w))
            elif just == "R":
                parts.append(val.rjust(w))
            else:
                parts.append(val.center(w))
        print("  " + " ".join(parts))
    print(f"  {'-'*(len(hdr))}")

def main():
    sigs = load(JSONL_PATH)
    total = len(sigs)
    ts_min = min(s["ts_utc"] for s in sigs)[:19]
    ts_max = max(s["ts_utc"] for s in sigs)[:19]

    print(f"ANALYSE DE {total} SIGNAUX  |  {sigs[0]['ts_utc'][:10]}")
    print(f"Plage: {ts_min[11:19]} -> {ts_max[11:19]} UTC\n")

    outcomes = Counter(check_outcome(s) for s in sigs)
    resolved = outcomes["tp1"] + outcomes["sl"]
    win_rate = outcomes["tp1"] / resolved * 100 if resolved > 0 else 0

    hr("VUE D'ENSEMBLE GLOBALE")
    print(f"  TP1 atteint   : {outcomes['tp1']:>4} / {total} ({outcomes['tp1']/total*100:5.1f}%)")
    print(f"  SL touche     : {outcomes['sl']:>4} / {total} ({outcomes['sl']/total*100:5.1f}%)")
    print(f"  Encore actif  : {outcomes['active']:>4} / {total} ({outcomes['active']/total*100:5.1f}%)")
    print(f"  Resolus       : {resolved:>4} / {total}")
    print(f"  TAUX REUSSITE : {win_rate:.1f}% ({outcomes['tp1']}/{resolved})")

    def agg(sigs, key_fn):
        d = {}
        for s in sigs:
            k = key_fn(s)
            if k not in d:
                d[k] = {"t":0,"tp1":0,"sl":0,"act":0,"rr_sum":0.0,"rr_n":0}
            o = check_outcome(s)
            d[k]["t"] += 1
            # Use get in case outcome is not a key (e.g., "unknown")
            if o == "tp1": d[k]["tp1"] += 1
            elif o == "sl": d[k]["sl"] += 1
            else: d[k]["act"] += 1
            rr = s.get("trade_plan",{}).get("rr1",0)
            if rr > 0:
                d[k]["rr_sum"] += rr
                d[k]["rr_n"] += 1
        return d

    def tab(agg_data, order, headers, widths):
        rows = []
        for k in order:
            if k not in agg_data: continue
            st = agg_data[k]
            res = st["tp1"] + st["sl"]
            wr = st["tp1"]/res*100 if res > 0 else 0
            avg = st["rr_sum"]/st["rr_n"] if st["rr_n"] > 0 else 0
            rows.append([k, st["tp1"], st["sl"], st["act"], st["t"],
                         f"{wr:.1f}%", f"{avg:.2f}R"])
        show(rows, dict(zip(headers, widths)))

    FMT7 = [("L",12),("R",5),("R",5),("R",7),("R",7),("R",8),("R",8)]

    # DIRECTION
    hr("PAR DIRECTION")
    d = agg(sigs, lambda s: s.get("direction","?"))
    tab(d, ["bull","bear"],
        ["Direction","TP1","SL","Actif","Total","WinRate","AvgRR1"], FMT7)

    # SYMBOL TYPE
    hr("PAR TYPE DE SYMBOLE")
    d = agg(sigs, lambda s: s.get("symbol_type","?"))
    tab(d, ["FOREX","STOCK","METAL"],
        ["Type","TP1","SL","Actif","Total","WinRate","AvgRR1"], FMT7)

    # RAID TYPE
    hr("PAR TYPE DE RAID")
    d = agg(sigs, lambda s: s.get("raid_type","?"))
    tab(d, ["ssl","bsl"],
        ["Raid","TP1","SL","Actif","Total","WinRate","AvgRR1"], FMT7)

    # RR1 RANGE
    hr("PAR GAMME DE RR1")
    d = agg(sigs, lambda s: classify_rr(s.get("trade_plan",{}).get("rr1",0)))
    rows_rr = []
    for rc in ["<1R","1-2R","2-3R","3-5R","5-10R","10+R"]:
        if rc not in d: continue
        st = d[rc]
        res = st["tp1"]+st["sl"]
        wr = st["tp1"]/res*100 if res > 0 else 0
        rows_rr.append([rc, st["tp1"], st["sl"], st["act"], st["t"], f"{wr:.1f}%"])
    show(rows_rr, dict(zip(["Gamme RR1","TP1","SL","Actif","Total","WinRate"],
                           [("L",12),("R",5),("R",5),("R",7),("R",7),("R",8)])))

    # FVG GAP
    hr("PAR TAILLE DE FVG GAP")
    d = agg(sigs, lambda s: classify_fvg(s.get("fvg_gap_pct",0)))
    rows_fg = []
    for fc in ["<0.05%","0.05-0.1%","0.1-0.2%","0.2-0.5%",">=0.5%"]:
        if fc not in d: continue
        st = d[fc]
        res = st["tp1"]+st["sl"]
        wr = st["tp1"]/res*100 if res > 0 else 0
        rows_fg.append([fc, st["tp1"], st["sl"], st["act"], st["t"], f"{wr:.1f}%"])
    show(rows_fg, dict(zip(["FVG Gap","TP1","SL","Actif","Total","WinRate"],
                           [("L",12),("R",5),("R",5),("R",7),("R",7),("R",8)])))

    # DOL DISTANCE
    hr("PAR DISTANCE AU DOL")
    d = agg(sigs, lambda s: classify_dol(s.get("trade_plan",{}).get("dol_distance_pct",0)))
    tab(d, ["<1%","1-3%","3-5%",">=5%"],
        ["Dist DOL","TP1","SL","Actif","Total","WinRate","AvgRR1"], FMT7)

    # DOL LABEL TYPE
    hr("PAR TYPE DE DOL LABEL")
    def dol_lbl(s):
        l = s.get("dol_label","")
        if l.startswith("AH"): return "AH (Today High)"
        if l.startswith("AL"): return "AL (Today Low)"
        if l.startswith("PDH"): return "PDH (Prev High)"
        if l.startswith("PDL"): return "PDL (Prev Low)"
        return "Other"
    d = agg(sigs, dol_lbl)
    rows_dl = []
    for dc in ["AH (Today High)","AL (Today Low)","PDH (Prev High)","PDL (Prev Low)"]:
        if dc not in d: continue
        st = d[dc]
        res = st["tp1"]+st["sl"]
        wr = st["tp1"]/res*100 if res > 0 else 0
        rows_dl.append([dc, st["tp1"], st["sl"], st["act"], st["t"],
                        f"{wr:.1f}%", f"{st['tp1']/st['t']*100:.1f}%"])
    show(rows_dl, dict(zip(["DOL Label","TP1","SL","Actif","Total","WinRate","%Total"],
                           [("L",18),("R",5),("R",5),("R",7),("R",7),("R",8),("R",8)])))

    # COMBO MATRIX
    hr("MATRICE DIRECTION x RAID x TYPE")
    combo = {}
    for s in sigs:
        k = f"{s.get('direction','?')}|{s.get('raid_type','?')}|{s.get('symbol_type','?')}"
        if k not in combo:
            combo[k] = {"t":0,"tp1":0,"sl":0,"act":0,"rr_sum":0.0,"rr_n":0}
        o = check_outcome(s)
        combo[k]["t"] += 1
        if o == "tp1": combo[k]["tp1"] += 1
        elif o == "sl": combo[k]["sl"] += 1
        else: combo[k]["act"] += 1
        rr = s.get("trade_plan",{}).get("rr1",0)
        if rr > 0:
            combo[k]["rr_sum"] += rr
            combo[k]["rr_n"] += 1
    rows_c = []
    for k, st in sorted(combo.items(), key=lambda x: x[1]["t"], reverse=True):
        res = st["tp1"]+st["sl"]
        wr = st["tp1"]/res*100 if res > 0 else 0
        avg = st["rr_sum"]/st["rr_n"] if st["rr_n"] > 0 else 0
        rows_c.append([k, st["tp1"], st["sl"], st["act"], st["t"], f"{wr:.1f}%", f"{avg:.2f}R"])
    show(rows_c, dict(zip(["Combo","TP1","SL","Actif","Total","WinRate","AvgRR1"],
                          [("L",30),("R",5),("R",5),("R",7),("R",7),("R",8),("R",8)])))

    # EXPECTANCY
    hr("ESPERANCE MATHEMATIQUE")
    rows_e = []
    for k, st in sorted(combo.items(), key=lambda x: x[1]["t"], reverse=True):
        res = st["tp1"]+st["sl"]
        if res == 0: continue
        wr = st["tp1"]/res
        avg = st["rr_sum"]/st["rr_n"] if st["rr_n"] > 0 else 0
        exp = (wr*avg) - ((1-wr)*1)
        rows_e.append([k, st["t"], f"{wr*100:.1f}%", f"{avg:.2f}R", f"{exp:+.3f}R"])
    rows_e.sort(key=lambda x: float(x[4].rstrip("R")), reverse=True)
    show(rows_e, dict(zip(["Combo","N","WinRate","AvgRR1","Esperance"],
                          [("L",30),("R",5),("R",8),("R",8),("R",10)])))

    # TOP 10
    hr("TOP 10 SIGNALES PAR RR1")
    scored = []
    for s in sigs:
        scored.append((s["symbol"], s["direction"], s["dol_label"],
                       s.get("trade_plan",{}).get("rr1",0),
                       s.get("fvg_gap_pct",0),
                       s.get("trade_plan",{}).get("dol_distance_pct",0),
                       check_outcome(s), s["ts_utc"][11:19]))
    scored.sort(key=lambda x: x[3], reverse=True)
    rows_t = []
    for item in scored[:10]:
        st_lbl = {"tp1":"TP1","sl":"SL","active":"ACTIF"}.get(item[6],"?")
        rows_t.append([item[0], item[1], item[2], f"{item[3]:.1f}R",
                       f"{item[4]:.3f}%", f"{item[5]:.1f}%", st_lbl, item[7]])
    show(rows_t, dict(zip(["Symbol","Dir","DOL","RR1","FVG%","Dist%","Status","Time"],
                          [("L",10),("L",6),("L",16),("R",8),("R",8),("R",8),("L",8),("L",8)])))

    # BY HOUR
    hr("PAR TRANCHE HORAIRE (UTC)")
    hour = {}
    for s in sigs:
        h = s["ts_utc"][11:13]
        if h not in hour:
            hour[h] = {"t":0,"tp1":0,"sl":0,"act":0}
        o = check_outcome(s)
        hour[h]["t"] += 1
        if o == "tp1": hour[h]["tp1"] += 1
        elif o == "sl": hour[h]["sl"] += 1
        else: hour[h]["act"] += 1
    rows_h = []
    for h in sorted(hour.keys()):
        st = hour[h]
        res = st["tp1"]+st["sl"]
        wr = st["tp1"]/res*100 if res > 0 else 0
        rows_h.append([f"{h}:00", st["tp1"], st["sl"], st["act"], st["t"], f"{wr:.1f}%"])
    show(rows_h, dict(zip(["Heure","TP1","SL","Actif","Total","WinRate"],
                          [("L",8),("R",5),("R",5),("R",7),("R",7),("R",8)])))

    # BY SYMBOL
    hr("PAR SYMBOLE (top 20)")
    d = agg(sigs, lambda s: s["symbol"])
    rows_s = []
    for sym, st in sorted(d.items(), key=lambda x: x[1]["t"], reverse=True)[:20]:
        res = st["tp1"]+st["sl"]
        wr = st["tp1"]/res*100 if res > 0 else 0
        avg = st["rr_sum"]/st["rr_n"] if st["rr_n"] > 0 else 0
        rows_s.append([sym, st["tp1"], st["sl"], st["act"], st["t"], f"{wr:.1f}%", f"{avg:.2f}R"])
    show(rows_s, dict(zip(["Symbol","TP1","SL","Actif","Total","WinRate","AvgRR1"],
                          [("L",12),("R",5),("R",5),("R",7),("R",7),("R",8),("R",8)])))

    # SUMMARY
    hr("SCORECARD")
    avg_rr = sum(s.get("trade_plan",{}).get("rr1",0) for s in sigs)/total
    best_rr = max(s.get("trade_plan",{}).get("rr1",0) for s in sigs)
    tp1_s = [s for s in sigs if check_outcome(s)=="tp1"]
    avg_win = sum(s.get("trade_plan",{}).get("rr1",0) for s in tp1_s)/len(tp1_s) if tp1_s else 0

    print(f"  {'Indicator':<35} {'Value':>10}")
    print(f"  {'-'*45}")
    print(f"  {'Total signals':<35} {total:>10}")
    print(f"  {'Resolved (TP1+SL)':<35} {resolved:>10}")
    print(f"  {'Win rate (TP1/Resolved)':<35} {f'{win_rate:.1f}%':>10}")
    print(f"  {'Avg RR1 (all signals)':<35} {f'{avg_rr:.2f}R':>10}")
    print(f"  {'Best RR1 found':<35} {f'{best_rr:.1f}R':>10}")
    if tp1_s:
        print(f"  {'Avg RR1 on TP1 winners':<35} {f'{avg_win:.2f}R':>10}")
    print(f"  {'Signals still active':<35} {outcomes['active']:>10}")

    if rows_e:
        print(f"\n  BEST EXPECTANCY : {rows_e[0][0]} -> {rows_e[0][4]}")
        print(f"  WORST EXPECTANCY: {rows_e[-1][0]} -> {rows_e[-1][4]}")

    print(f"\n  NOTA: {outcomes['active']}/{total} signaux encore actifs au log.")
    print(f"  Le vrai taux sera connu apres expiration de tous les signaux.")

if __name__ == "__main__":
    main()
