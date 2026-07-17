#!/usr/bin/env python3
"""
Backtest exhaustif M1 - TOUS les setups Diamond 17/07/2026
Entre a l'open de la premiere barre apres le scan de 03:47 UTC
"""
import MetaTrader5 as mt5
import sys
from datetime import datetime, timezone, timedelta

UTC = timezone.utc

TRADES = [
    ("EURUSD",   "BULL", "2026-07-17 03:47", 1.14345, 1.14742, "Score 40, conflit TK H1 BEAR"),
    ("GBPUSD",   "BULL", "2026-07-17 03:47", 1.34570, 1.34995, "Score 42, 3 FVG Bear M5/M15/M30"),
    ("USDJPY",   "BULL", "2026-07-17 03:47", 162.307, 162.472, "Score 38, AL sweep a 11:00"),
    ("AUDUSD",   "BULL", "2026-07-17 03:47", 0.69760, 0.70009, "Score 47, meilleur score"),
    ("EURJPY",   "BULL", "2026-07-17 03:47", 185.679, 185.949, "Score 51, meilleur score 17/07"),
    ("GBPJPY",   "BULL", "2026-07-17 03:47", 218.553, 218.938, "Score 38, AL sweep a 09:00"),
    ("DXY.cash", "BEAR", "2026-07-17 03:47", 100.797, 100.694, "Score 38, AL sweep a 10:00"),
    ("USDCAD",   "BEAR", "2026-07-17 03:47", 1.4043,  1.4029,  "Score 42"),
    ("US500.cash","BEAR", "2026-07-17 03:47", 7531,    7467,    "Score 42"),
    ("US100.cash","BEAR", "2026-07-17 03:47", 29018,   28560,   "Score 40"),
]

def pf(sym):
    if 'XAU' in sym: return 10.0
    if 'JPY' in sym or 'DXY' in sym: return 100.0
    if '.cash' in sym: return 1.0
    return 10000.0

def pips(sym, p, l):
    return (p - l) * pf(sym)

def unit(sym):
    return "pts" if ".cash" in sym else "p"

def main():
    if not mt5.initialize():
        print("[X] MT5 connection failed")
        return 1

    try:
        print("=" * 100)
        print("  BACKTEST EXHAUSTIF M1 -- TOUS les setups Diamond 17/07/2026 (entree 03:47 UTC)")
        print("=" * 100)
        print()

        now = datetime.now(UTC)
        end_str = now.strftime("%Y-%m-%d %H:%M UTC")

        results = []
        wins = losses = opens = 0
        total_pnl = 0.0

        for sym, bias, scan_utc, sl, tp, note in TRADES:
            mt5.symbol_select(sym, True)

            scan_dt = datetime.strptime(scan_utc, "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
            buffer_start = scan_dt - timedelta(hours=1)

            rates = mt5.copy_rates_range(sym, mt5.TIMEFRAME_M1, buffer_start, now)
            if rates is None or len(rates) == 0:
                print(f"  {sym:<14} NO DATA")
                continue

            bars = [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])) for r in rates]
            post = [(ts, o, h, l, c) for ts, o, h, l, c in bars if ts >= scan_dt.timestamp()]

            if not post:
                print(f"  {sym:<14} No bars after scan")
                continue

            entry = post[0][1]
            last_bar = post[-1]
            last = last_bar[4]

            all_h = [b[2] for b in post]
            all_l = [b[3] for b in post]

            hit_sl = hit_tp = False
            hit_time = 0
            hit_price = 0.0
            mfe_val = 0.0
            mae_val = 0.0

            if bias == "BULL":
                mfe_val = max(all_h)
                mae_val = min(all_l)
                for ts, o, h, l, c in post:
                    if l <= sl:
                        hit_sl = True; hit_time = ts; hit_price = sl; break
                    if h >= tp:
                        hit_tp = True; hit_time = ts; hit_price = tp; break
            else:
                mfe_val = min(all_l)
                mae_val = max(all_h)
                for ts, o, h, l, c in post:
                    if h >= sl:
                        hit_sl = True; hit_time = ts; hit_price = sl; break
                    if l <= tp:
                        hit_tp = True; hit_time = ts; hit_price = tp; break

            result = "TP" if hit_tp else ("SL" if hit_sl else "OPEN")
            ht_str = datetime.fromtimestamp(hit_time, UTC).strftime("%H:%M UTC") if hit_time else "-"

            if hit_sl or hit_tp:
                pnl = pips(sym, hit_price, entry)
                mfe = pips(sym, mfe_val, entry) if bias == "BULL" else pips(sym, entry, mfe_val)
                mae = pips(sym, mae_val, entry) if bias == "BULL" else pips(sym, mae_val, entry)
            else:
                pnl = pips(sym, last, entry)
                mfe = pips(sym, max(all_h), entry) if bias == "BULL" else pips(sym, entry, min(all_l))
                mae = pips(sym, min(all_l), entry) if bias == "BULL" else pips(sym, max(all_h), entry)

            u = unit(sym)
            range_pips = abs(pips(sym, tp, sl))
            mfe_pct = abs(mfe) / range_pips * 100 if range_pips > 0 else 0

            if result == "TP":
                wins += 1
            elif result == "SL":
                losses += 1
            else:
                opens += 1
            total_pnl += pnl

            results.append((sym, bias, result, pnl, mfe, mae, mfe_pct, ht_str, len(post), note))

            emoji = "[SL]" if result == "SL" else ("[TP]" if result == "TP" else "[--]")
            print(f"  {sym:<14} {bias:<6} {emoji} {result:<4} Entry={entry:.5f}  SL={sl:.5f}  TP={tp:.5f}")
            print(f"     PnL: {pnl:+.1f}{u}  |  MFE: {mfe:+.1f}{u}  |  MAE: {mae:+.1f}{u}  |  Hit: {ht_str}")
            print(f"     MFE: {mfe_pct:.0f}% du range  |  Duree: {len(post)} bars ({len(post)/60:.1f}h)")
            print(f"     Note: {note}")
            print()

        # SYNTHESE
        print("=" * 100)
        print("  SYNTHESE FINALE 17/07/2026")
        print("=" * 100)
        print()
        print(f"  Entree: 03:47 UTC  |  Fin: {end_str}  |  {wins+losses+opens} trades")
        print()
        print(f"  {'Symbole':<14} {'Biais':<6} {'Resultat':<6} {'P&L':>10} {'MFE':>10} {'MAE':>10} {'MFE%':>6} {'Hit':>8} {'Duree':>8}")
        print(f"  {'-'*14} {'-'*6} {'-'*6} {'-'*10} {'-'*10} {'-'*10} {'-'*6} {'-'*8} {'-'*8}")

        for sym, bias, result, pnl, mfe, mae, mfe_pct, ht_str, bars_n, note in results:
            u = unit(sym)
            print(f"  {sym:<14} {bias:<6} {result:<6} {pnl:>+9.1f}{u} {mfe:>+9.1f}{u} {mae:>+9.1f}{u} {mfe_pct:>5.0f}% {ht_str:>8} {bars_n:>4}m")

        resolved = wins + losses
        win_rate = wins / resolved * 100 if resolved > 0 else 0
        print(f"  {'-'*14} {'-'*6} {'-'*6} {'-'*10} {'-'*10} {'-'*10} {'-'*6} {'-'*8} {'-'*8}")
        print(f"  Win rate: {wins}/{resolved} = {win_rate:.0f}%  |  Opens: {opens}")
        print(f"  Total P&L (tous): {total_pnl:+.1f} pips")
        print()

        # Split BULL vs BEAR
        print("  --- Par biais ---")
        bull_results = [(s,b,r,pn,mf,ma,pct,ht,d,n) for s,b,r,pn,mf,ma,pct,ht,d,n in results if b=="BULL"]
        bear_results = [(s,b,r,pn,mf,ma,pct,ht,d,n) for s,b,r,pn,mf,ma,pct,ht,d,n in results if b=="BEAR"]

        if bull_results:
            bull_pnl = sum(r[3] for r in bull_results)
            bull_w = sum(1 for r in bull_results if r[2]=="TP")
            bull_l = sum(1 for r in bull_results if r[2]=="SL")
            print(f"  BULL: {bull_w}W/{bull_l}L  P&L total: {bull_pnl:+.1f} pips")

        if bear_results:
            bear_pnl = sum(r[3] for r in bear_results)
            bear_w = sum(1 for r in bear_results if r[2]=="TP")
            bear_l = sum(1 for r in bear_results if r[2]=="SL")
            print(f"  BEAR: {bear_w}W/{bear_l}L  P&L total: {bear_pnl:+.1f} pips")

        # MFE analysis
        print()
        print("  --- Analyse MFE ---")
        for sym, bias, result, pnl, mfe, mae, mfe_pct, ht_str, bars_n, note in results:
            mfe_indicator = ""
            if mfe_pct > 20:
                mfe_indicator = " [BON MFE > 20%]"
            elif mfe_pct < 5 and result != "TP":
                mfe_indicator = " [PAS DE RESPIRATION]"
            print(f"  {sym:<14} MFE={mfe_pct:>5.0f}% du range{mfe_indicator}")

    finally:
        mt5.shutdown()

if __name__ == "__main__":
    sys.exit(main())
