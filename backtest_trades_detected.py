#!/usr/bin/env python3
"""
🔬 Backtest M1 ultra-granulaire — Trades détectés par le Diamond Scanner

Analyse chaque trade barre par barre (M1) pour déterminer :
- Heure exacte du SL ou TP touché
- MFE (Maximum Favorable Excursion) — meilleur prix atteint
- MAE (Maximum Adverse Excursion) — pire prix atteint  
- Durée du trade (en barres M1 et en minutes)
- P&L en pips et en % du risque
- RR réellement réalisé
"""

import MetaTrader5 as mt5
import time
from datetime import datetime, timezone, timedelta
import sys
import io

# Fix encoding Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

UTC = timezone.utc

# ─── Trades détectés le 16/07/2026 (~12h00 UTC) ─────────────────────────────

TRADES_16JUL = [
    {
        "symbol": "US30.cash",
        "bias": "BULL",
        "quality": "STRONG",
        "scan_utc": "2026-07-16 12:00",
        "sl": 52426.0,
        "tp": 53495.0,
        "entry_approx": None,  # sera trouvé via MT5
        "score": 19,
        "max_score": 19,
    },
    {
        "symbol": "US500.cash",
        "bias": "BULL",
        "quality": "WAIT",
        "scan_utc": "2026-07-16 12:00",
        "sl": 7538.0,
        "tp": 7597.0,
        "entry_approx": None,
        "score": 15,
        "max_score": 17,
        "note": "SL à 3.2 pts (5% du range) — trade risqué",
    },
    {
        "symbol": "GBPUSD",
        "bias": "BULL",
        "quality": "GOOD",
        "scan_utc": "2026-07-16 12:00",
        "sl": 1.3450,
        "tp": 1.3628,
        "entry_approx": None,
        "score": 15,
        "max_score": 19,
    },
    {
        "symbol": "USDJPY",
        "bias": "BULL",
        "quality": "GOOD",
        "scan_utc": "2026-07-16 12:00",
        "sl": 161.88,
        "tp": 162.90,
        "entry_approx": None,
        "score": 15,
        "max_score": 19,
    },
    {
        "symbol": "AUDUSD",
        "bias": "BULL",
        "quality": "GOOD",
        "scan_utc": "2026-07-16 12:00",
        "sl": 0.6967,
        "tp": 0.7091,
        "entry_approx": None,
        "score": 15,
        "max_score": 19,
    },
]

# ─── Trades du 17/07 (top 3 WAIT) — vérification si un mouvement aurait pu être tradable ──

TRADES_17JUL = [
    {
        "symbol": "GBPUSD",
        "bias": "BULL",
        "quality": "WAIT",
        "scan_utc": "2026-07-17 03:47",
        "sl": None,  # Pas de SL calculé (WAIT)
        "tp": None,
        "entry_approx": None,
        "score": 42,
        "max_score": 109,
        "note": "3 FVG Bear M5/M15/M30 non mitigés — pression baissière court terme",
    },
    {
        "symbol": "GBPJPY",
        "bias": "BULL",
        "quality": "WAIT",
        "scan_utc": "2026-07-17 03:47",
        "sl": None,
        "tp": None,
        "entry_approx": None,
        "score": 38,
        "max_score": 109,
        "note": "D1 Bull + M5 Bull FVG ouverts, M30 Bear conflit",
    },
    {
        "symbol": "EURJPY",
        "bias": "BULL",
        "quality": "WAIT",
        "scan_utc": "2026-07-17 03:47",
        "sl": None,
        "tp": None,
        "entry_approx": None,
        "score": 37,
        "max_score": 109,
        "note": "Meilleur score global, Tenkan+Kijun H1 double obstacle",
    },
]


def pip_factor(symbol: str) -> float:
    if 'XAUUSD' in symbol:
        return 10.0
    elif 'JPY' in symbol or 'DXY' in symbol:
        return 100.0
    elif 'US30' in symbol or 'US100' in symbol or 'US500' in symbol or 'SPX' in symbol or 'NAS' in symbol:
        return 1.0   # Indices: 1 point = 1 pip
    else:
        return 10000.0


def pips(symbol: str, price: float, level: float) -> float:
    return (price - level) * pip_factor(symbol)


def format_pnl(pips_val: float, symbol: str) -> str:
    if 'US30' in symbol or 'US100' in symbol or 'US500' in symbol:
        return f"{pips_val:+.1f} pts"
    else:
        return f"{pips_val:+.1f} pips"


def backtest_trade(trade: dict, rates_m1: list) -> dict:
    """
    Backteste un trade barre par barre sur des données M1.
    
    Args:
        trade: dict avec symbol, bias, sl, tp, scan_utc
        rates_m1: liste de tuples (timestamp, open, high, low, close)
    
    Returns:
        dict avec les résultats détaillés
    """
    sym = trade["symbol"]
    bias = trade["bias"]
    sl = trade["sl"]
    tp = trade["tp"]
    scan_dt = datetime.strptime(trade["scan_utc"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
    scan_epoch = scan_dt.timestamp()
    
    # Trouver la barre M1 la plus proche après le scan
    post_scan_bars = [(ts, o, h, l, c) for ts, o, h, l, c in rates_m1 if ts >= scan_epoch]
    
    if not post_scan_bars:
        return {"error": "Aucune barre M1 après le scan", "symbol": sym}
    
    # Entry = open de la première barre après le scan (simule entrée au marché)
    entry_ts, entry_o, entry_h, entry_l, entry_c = post_scan_bars[0]
    entry_price = entry_o
    
    # Initialiser le tracking
    mfe_pips = 0.0   # Maximum Favorable Excursion
    mae_pips = 0.0   # Maximum Adverse Excursion
    hit_sl = False
    hit_tp = False
    hit_bar_idx = -1
    hit_bar_ts = None
    hit_price = 0.0
    
    total_range = abs(tp - sl)
    
    for idx, (ts, o, h, l, c) in enumerate(post_scan_bars):
        if bias == "BULL":
            # Vérifier SL d'abord (low touche SL)
            if l <= sl:
                hit_sl = True
                hit_bar_idx = idx
                hit_bar_ts = ts
                hit_price = sl
                # Calculer MFE avant SL
                mfe_pips = pips(sym, max(h, entry_price), entry_price) if idx > 0 else 0
                mae_pips = pips(sym, min(l, entry_price), entry_price)
                break
            # Vérifier TP (high touche TP)
            if h >= tp:
                hit_tp = True
                hit_bar_idx = idx
                hit_bar_ts = ts
                hit_price = tp
                mfe_pips = pips(sym, tp, entry_price)
                mae_pips = pips(sym, min(l, entry_price), entry_price) if idx > 0 else 0
                break
            # Mettre à jour MFE/MAE
            mfe_pips = max(mfe_pips, pips(sym, h, entry_price))
            mae_pips = min(mae_pips, pips(sym, l, entry_price))
        else:  # BEAR
            if h >= sl:
                hit_sl = True
                hit_bar_idx = idx
                hit_bar_ts = ts
                hit_price = sl
                mae_pips = pips(sym, max(h, entry_price), entry_price) if idx > 0 else 0
                mfe_pips = pips(sym, min(l, entry_price), entry_price)
                break
            if l <= tp:
                hit_tp = True
                hit_bar_idx = idx
                hit_bar_ts = ts
                hit_price = tp
                mfe_pips = pips(sym, tp, entry_price)
                mae_pips = pips(sym, max(h, entry_price), entry_price) if idx > 0 else 0
                break
            mfe_pips = max(mfe_pips, pips(sym, entry_price, l))  # Pour BEAR, MFE = combien c'est descendu
            mae_pips = max(mae_pips, pips(sym, h, entry_price))  # Pour BEAR, MAE = combien c'est monté
    
    # Si ni SL ni TP touché après toutes les barres
    if not hit_sl and not hit_tp:
        last_bar = post_scan_bars[-1]
        last_price = last_bar[4]  # close
        last_ts = last_bar[0]
        
        # Calculer MFE/MAE sur toutes les barres
        if bias == "BULL":
            mfe_pips = pips(sym, max(b[2] for b in post_scan_bars), entry_price)
            mae_pips = pips(sym, min(b[3] for b in post_scan_bars), entry_price)
        else:
            mfe_pips = pips(sym, entry_price, min(b[3] for b in post_scan_bars))
            mae_pips = pips(sym, max(b[2] for b in post_scan_bars), entry_price)
        
        pnl = pips(sym, last_price, entry_price)
        
        return {
            "symbol": sym,
            "bias": bias,
            "quality": trade["quality"],
            "entry_price": round(entry_price, 5),
            "entry_time": datetime.fromtimestamp(entry_ts, UTC).strftime("%Y-%m-%d %H:%M UTC"),
            "sl": sl,
            "tp": tp,
            "result": "OPEN",
            "pnl_pips": round(pnl, 1),
            "mfe_pips": round(mfe_pips, 1),
            "mae_pips": round(mae_pips, 1),
            "last_price": round(last_price, 5),
            "last_time": datetime.fromtimestamp(last_ts, UTC).strftime("%Y-%m-%d %H:%M UTC"),
            "duration_bars": len(post_scan_bars),
            "duration_minutes": len(post_scan_bars),
            "bars_tested": len(post_scan_bars),
        }
    
    # Calculer le P&L
    pnl = pips(sym, hit_price, entry_price)
    
    hit_dt = datetime.fromtimestamp(hit_bar_ts, UTC)
    
    return {
        "symbol": sym,
        "bias": bias,
        "quality": trade["quality"],
        "entry_price": round(entry_price, 5),
        "entry_time": datetime.fromtimestamp(entry_ts, UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "sl": sl,
        "tp": tp,
        "result": "SL_HIT" if hit_sl else "TP_HIT",
        "hit_price": round(hit_price, 5),
        "hit_time": hit_dt.strftime("%Y-%m-%d %H:%M UTC"),
        "hit_bar": hit_bar_idx,
        "pnl_pips": round(pnl, 1),
        "pnl_rr": round(abs(pnl / pips(sym, tp, sl)), 2) if not hit_sl else -1.0,
        "mfe_pips": round(mfe_pips, 1),
        "mae_pips": round(mae_pips, 1),
        "mfe_pct_of_range": round(abs(mfe_pips / abs(pips(sym, tp, sl))) * 100, 1) if pips(sym, tp, sl) != 0 else 0,
        "duration_bars": hit_bar_idx + 1,
        "duration_minutes": hit_bar_idx + 1,
        "bars_tested": hit_bar_idx + 1,
    }


def download_m1(symbol: str, start_utc: str, end_utc: str) -> list:
    """Télécharge les barres M1 entre deux dates UTC."""
    start_dt = datetime.strptime(start_utc, "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
    end_dt = datetime.strptime(end_utc, "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
    
    # Ajouter un buffer de 60 barres avant
    buffer_start = start_dt - timedelta(hours=1)
    
    rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M1, buffer_start, end_dt)
    
    if rates is None or len(rates) == 0:
        return []
    
    return [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])) for r in rates]


def analyze_no_sl_trade(trade: dict, rates_m1: list) -> dict:
    """
    Pour les trades WAIT sans SL/TP, analyse le mouvement du prix
    depuis le scan jusqu'à maintenant.
    """
    sym = trade["symbol"]
    scan_dt = datetime.strptime(trade["scan_utc"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
    scan_epoch = scan_dt.timestamp()
    
    post_scan_bars = [(ts, o, h, l, c) for ts, o, h, l, c in rates_m1 if ts >= scan_epoch]
    
    if not post_scan_bars:
        return {"error": "Aucune barre M1 après le scan", "symbol": sym}
    
    entry_ts, entry_o, entry_h, entry_l, entry_c = post_scan_bars[0]
    entry_price = entry_o
    last_bar = post_scan_bars[-1]
    last_price = last_bar[4]
    last_ts = last_bar[0]
    
    all_highs = [b[2] for b in post_scan_bars]
    all_lows = [b[3] for b in post_scan_bars]
    
    high_price = max(all_highs)
    low_price = min(all_lows)
    
    return {
        "symbol": sym,
        "bias": trade["bias"],
        "quality": trade["quality"],
        "entry_price": round(entry_price, 5),
        "entry_time": datetime.fromtimestamp(entry_ts, UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "result": "WAIT (pas de SL/TP)",
        "last_price": round(last_price, 5),
        "last_time": datetime.fromtimestamp(last_ts, UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "change_pips": round(pips(sym, last_price, entry_price), 1),
        "high_price": round(high_price, 5),
        "low_price": round(low_price, 5),
        "range_pips": round(pips(sym, high_price, low_price), 1),
        "duration_bars": len(post_scan_bars),
        "duration_hours": round(len(post_scan_bars) / 60, 1),
        "note": trade.get("note", ""),
    }


def main():
    print("=" * 100)
    print("  [!] BACKTEST M1 ULTRA-GRANULAIRE — Trades detectes Diamond Scanner")
    print("=" * 100)
    print()
    
    # Connexion MT5
    if not mt5.initialize():
        print("[X] Impossible de se connecter a MT5")
        return 1
    
    try:
        account_info = mt5.account_info()
        if account_info:
            print(f"[OK] MT5 connecte — Compte {account_info.login} @ {account_info.server}")
        print()
        
        # ═══════════════════════════════════════════════════════════════════
        # PARTIE 1 : Trades du 16/07 avec SL/TP
        # ═══════════════════════════════════════════════════════════════════
        
        print("╔" + "═" * 98 + "╗")
        print("  [16/07] PARTIE 1 : Trades detectes le 16/07/2026 (~12h00 UTC)")
        print("╔" + "═" * 98 + "╗")
        print()
        
        results_16jul = []
        
        for trade in TRADES_16JUL:
            sym = trade["symbol"]
            print(f"  [>] Telechargement M1 pour {sym} (16/07 11h00 -> 17/07 23h59 UTC)...")
            
            # Activer le symbole
            mt5.symbol_select(sym, True)
            
            # Télécharger M1 du 16/07 11:00 au 17/07 23:59
            rates = download_m1(sym, "2026-07-16 11:00", "2026-07-17 23:59")
            
            if not rates:
                print(f"     [!] Aucune donnee M1 disponible pour {sym}")
                results_16jul.append({"symbol": sym, "error": "Pas de données M1"})
                continue
            
            print(f"     [i] {len(rates)} barres M1 chargees ({len(rates)/60:.1f}h)")
            
            result = backtest_trade(trade, rates)
            results_16jul.append(result)
            
            # Affichage immédiat
            if "error" not in result:
                emoji = "[SL]" if result["result"] == "SL_HIT" else ("[TP]" if result["result"] == "TP_HIT" else "[--]")
                print(f"     {emoji} {result['result']} | Entry: {result['entry_price']} @ {result['entry_time']}")
                if result["result"] != "OPEN":
                    print(f"        Hit: {result['hit_price']} @ {result['hit_time']} (barre #{result['hit_bar']})")
                print(f"        P&L: {format_pnl(result['pnl_pips'], sym)} | MFE: {format_pnl(result['mfe_pips'], sym)} | MAE: {format_pnl(result['mae_pips'], sym)}")
                print(f"        Durée: {result['duration_bars']} barres M1 ({result['duration_minutes']} min)")
                if "mfe_pct_of_range" in result:
                    print(f"        MFE: {result['mfe_pct_of_range']}% du range SL→TP")
            print()
        
        # ═══════════════════════════════════════════════════════════════════
        # PARTIE 2 : Trades du 17/07 (WAIT, analyse du mouvement)
        # ═══════════════════════════════════════════════════════════════════
        
        print("╔" + "═" * 98 + "╗")
        print("  [17/07] PARTIE 2 : Top 3 du 17/07/2026 (~03h47 UTC) — Analyse du mouvement")
        print("╔" + "═" * 98 + "╗")
        print()
        
        results_17jul = []
        
        for trade in TRADES_17JUL:
            sym = trade["symbol"]
            print(f"  [>] Telechargement M1 pour {sym} (17/07 03h00 -> maintenant)...")
            
            mt5.symbol_select(sym, True)
            rates = download_m1(sym, "2026-07-17 03:00", datetime.now(UTC).strftime("%Y-%m-%d %H:%M"))
            
            if not rates:
                print(f"     [!] Aucune donnee M1 disponible pour {sym}")
                results_17jul.append({"symbol": sym, "error": "Pas de données M1"})
                continue
            
            print(f"     [i] {len(rates)} barres M1 chargees ({len(rates)/60:.1f}h)")
            
            result = analyze_no_sl_trade(trade, rates)
            results_17jul.append(result)
            
            if "error" not in result:
                direction = "UP" if result["change_pips"] > 0 else "DN"
                print(f"     {direction} Change: {format_pnl(result['change_pips'], sym)}")
                print(f"        Entry: {result['entry_price']} @ {result['entry_time']}")
                print(f"        Last:  {result['last_price']} @ {result['last_time']}")
                print(f"        Range: {result['range_pips']:.1f} pips (H={result['high_price']}, L={result['low_price']})")
                print(f"        Durée: {result['duration_hours']}h")
                print(f"        Note: {result['note']}")
            print()
        
        # ═══════════════════════════════════════════════════════════════════
        # SYNTHÈSE
        # ═══════════════════════════════════════════════════════════════════
        
        print("=" * 100)
        print("  [===] SYNTHESE FINALE")
        print("=" * 100)
        print()
        
        # 16/07
        print("  [16/07] 16/07/2026 — Trades avec SL/TP :")
        print(f"  {'Symbole':<12} {'Qualité':<10} {'Résultat':<10} {'P&L':>10} {'MFE':>10} {'MAE':>10} {'Durée':>8}")
        print(f"  {'─'*12} {'─'*10} {'─'*10} {'─'*10} {'─'*10} {'─'*10} {'─'*8}")
        
        total_pnl = 0.0
        wins = 0
        losses = 0
        
        for r in results_16jul:
            if "error" in r:
                print(f"  {r['symbol']:<12} {'─':<10} {'NO DATA':<10}")
                continue
            pnl = r["pnl_pips"]
            total_pnl += pnl
            if r["result"] == "TP_HIT":
                wins += 1
            elif r["result"] == "SL_HIT":
                losses += 1
            
            print(f"  {r['symbol']:<12} {r['quality']:<10} {r['result']:<10} "
                  f"{format_pnl(r['pnl_pips'], r['symbol']):>10} "
                  f"{format_pnl(r['mfe_pips'], r['symbol']):>10} "
                  f"{format_pnl(r['mae_pips'], r['symbol']):>10} "
                  f"{r['duration_minutes']}m")
        
        print(f"  {'─'*12} {'─'*10} {'─'*10} {'─'*10} {'─'*10} {'─'*10} {'─'*8}")
        print(f"  {'TOTAL':<12} {'':<10} {wins}W/{losses}L  {'':>4} {total_pnl:+.1f} pips")
        if wins + losses > 0:
            print(f"  Win rate: {wins}/{wins+losses} = {wins/(wins+losses)*100:.0f}%")
        print()
        
        # 17/07
        print("  [17/07] 17/07/2026 — Top 3 WAIT (mouvement depuis le scan) :")
        print(f"  {'Symbole':<12} {'Biais':<8} {'Change':>10} {'Range':>10} {'Durée':>8}")
        print(f"  {'─'*12} {'─'*8} {'─'*10} {'─'*10} {'─'*8}")
        
        for r in results_17jul:
            if "error" in r:
                print(f"  {r['symbol']:<12} {'─':<8} {'NO DATA':>10}")
                continue
            print(f"  {r['symbol']:<12} {r['bias']:<8} "
                  f"{format_pnl(r['change_pips'], r['symbol']):>10} "
                  f"{r['range_pips']:>8.1f}p  "
                  f"{r['duration_hours']}h")
        
        print()
        
    finally:
        mt5.shutdown()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
