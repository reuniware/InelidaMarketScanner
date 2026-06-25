import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from backtest_report_trades import extract_trades_from_pdf

trades = extract_trades_from_pdf('reports/inelida_report_2026-06-24.pdf')

print("=" * 100)
print("DETAILS COMPLETS DES 6 TRADES - RAPPORT 24 JUIN 2026")
print("=" * 100)

for i, t in enumerate(trades, 1):
    print(f"\n{'─' * 100}")
    print(f"TRADE #{i}  |  Source: {t.get('source', '?')}")
    print(f"{'─' * 100}")
    
    for key, val in t.items():
        print(f"  {key:<12}: {val}")
    
    # Analyse rapide
    try:
        e = float(t['entry'])
        tp = float(t['tp'])
        sl = float(t['sl'])
        d = t['dir']
        
        if d == 'BUY':
            risk = e - sl
            reward = tp - e
            rr = round(reward / risk, 2) if risk > 0 else 0
            dist_tp_pct = round((tp - e) / e * 100, 4)
            dist_sl_pct = round((e - sl) / e * 100, 4)
        else:
            risk = sl - e
            reward = e - tp
            rr = round(reward / risk, 2) if risk > 0 else 0
            dist_tp_pct = round((e - tp) / e * 100, 4)
            dist_sl_pct = round((sl - e) / e * 100, 4)
        
        print(f"\n  ── ANALYSE ──")
        print(f"  {'RR':<12}: 1:{rr}")
        print(f"  {'TP distance':<12}: {dist_tp_pct}%")
        print(f"  {'SL distance':<12}: {dist_sl_pct}%")
        print(f"  {'Ratio TP/SL':<12}: {round(dist_tp_pct/dist_sl_pct, 2) if dist_sl_pct else '∞'}x")
        
    except:
        pass

print(f"\n{'=' * 100}")
print(f"TOTAL: {len(trades)} trades")
print(f"{'=' * 100}")
