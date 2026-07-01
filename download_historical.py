"""
download_historical.py — Telechargeur universel de donnees M3 depuis MT5
========================================================================
Corrigé : utilise copy_rates_from_pos (pas de bug timezone serveur FTMO GMT+3)

Usage:
    python download_historical.py XAUUSD
    python download_historical.py EURUSD 2026-01-01 2026-06-27
    python download_historical.py --list              # lister symboles dispo
    python download_historical.py XAUUSD --tf M5      # timeframe different

Par defaut : M3, du 01/01/2026 au 27/06/2026 (exclusif = jusqu'au 26 inclus).
Sauvegarde dans reports/{symbol}_m3_{start}_to_{end}.json
"""

import json
import os
import sys
import argparse
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import MetaTrader5 as mt5

UTC = timezone.utc

TIMEFRAME_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M3": mt5.TIMEFRAME_M3,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")


def list_symbols():
    """Affiche tous les symboles disponibles dans MT5."""
    symbols = mt5.symbols_get()
    if symbols is None:
        print("[ERREUR] Impossible de recuperer la liste des symboles.")
        return
    print(f"Symboles disponibles ({len(symbols)}) :")
    for s in sorted(symbols, key=lambda x: x.name):
        print(f"  {s.name:<20} digits={s.digits} spread={s.spread}")


def download(symbol: str, timeframe_str: str, start_dt: datetime, end_dt: datetime) -> str:
    """Telecharge les donnees et retourne le chemin du fichier JSON."""
    tf = TIMEFRAME_MAP.get(timeframe_str.upper(), mt5.TIMEFRAME_M3)

    # --- Connexion MT5 ---
    print(f"[1/3] Connexion MT5 pour {symbol}...")
    if not mt5.initialize():
        print(f"[ERREUR] Connexion MT5 : {mt5.last_error()}")
        sys.exit(1)

    ai = mt5.account_info()
    if ai:
        print(f"  Compte : {ai.login} @ {ai.server}")

    info = mt5.symbol_info(symbol)
    if info is None:
        print(f"[ERREUR] Symbole '{symbol}' indisponible.")
        mt5.shutdown()
        sys.exit(1)
    if not info.visible:
        mt5.symbol_select(symbol, True)

    print(f"  Symbole : {symbol} (digits={info.digits}, spread={info.spread}, "
          f"timeframe={timeframe_str})")

    # --- Telechargement (corrige: copy_rates_from_pos au lieu de copy_rates_range) ---
    print(f"\n[2/3] Telechargement {timeframe_str}...")
    all_bars = []

    # 80 000 barres = ~166 jours en M3 (~5.5 mois), suffisant pour la periode demande
    # Au-dela de 80k, MT5 retourne None (limite du broker FTMO)
    max_bars = 80000
    start_ts = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())

    print(f"  Telechargement des {max_bars} dernieres barres depuis position 0...")
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, max_bars)

    if rates is None or len(rates) == 0:
        print(f"  [ERREUR] Aucune donnee retournee par MT5")
        print(f"  Verifiez que MT5 est connecte et que le symbole '{symbol}' est disponible.")
        mt5.shutdown()
        return ""

    n_raw = len(rates)
    first_ts = int(rates[0][0])

    for r in rates:
        t = int(r[0])
        if t < start_ts or t >= end_ts:
            continue
        all_bars.append({
            "time": t,
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
            "tick_volume": int(r[5]),
            "spread": int(r[6]) if len(r) > 6 else 0,
            "real_volume": int(r[7]) if len(r) > 7 else 0,
        })

    all_bars.sort(key=lambda b: b["time"])
    total_bars = len(all_bars)

    print(f"  {n_raw} barres brutes MT5 → {total_bars} barres dans [{start_dt.strftime('%Y-%m-%d')} → {end_dt.strftime('%Y-%m-%d')}[")
    if first_ts > start_ts:
        oldest = datetime.fromtimestamp(first_ts, tz=UTC)
        print(f"  ⚠️  Donnees les plus anciennes : {oldest.strftime('%Y-%m-%d %H:%M')} UTC")
        print(f"      (plus recent que {start_dt.strftime('%Y-%m-%d')} — periode partielle)")

    if all_bars:
        first_dt = datetime.fromtimestamp(all_bars[0]["time"], tz=UTC)
        last_dt = datetime.fromtimestamp(all_bars[-1]["time"], tz=UTC)
        print(f"  Periode reelle : {first_dt.strftime('%Y-%m-%d %H:%M')} → {last_dt.strftime('%Y-%m-%d %H:%M')} UTC")

    mt5.shutdown()

    # --- Nom du fichier ---
    fname = f"{symbol.lower()}_{timeframe_str.lower()}_{start_dt.strftime('%Y%m%d')}_to_{end_dt.strftime('%Y%m%d')}.json"
    output_path = os.path.join(OUTPUT_DIR, fname)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # --- Sauvegarde ---
    print(f"\n[3/3] Sauvegarde de {total_bars} barres...")
    data = {
        "symbol": symbol,
        "timeframe": timeframe_str.upper(),
        "start_date": start_dt.strftime("%Y-%m-%d"),
        "end_date": end_dt.strftime("%Y-%m-%d"),
        "total_bars": total_bars,
        "broker": ai.server if ai else "unknown",
        "downloaded_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "bars": all_bars,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    file_size_kb = os.path.getsize(output_path) / 1024
    print(f"  Fichier : {output_path}")
    print(f"  Taille  : {file_size_kb:.0f} Ko")
    print(f"  Barres  : {total_bars}")

    if all_bars:
        first = datetime.fromtimestamp(all_bars[0]["time"], tz=UTC)
        last = datetime.fromtimestamp(all_bars[-1]["time"], tz=UTC)
        print(f"  Periode : {first.strftime('%Y-%m-%d %H:%M')} → {last.strftime('%Y-%m-%d %H:%M')} UTC")
        high = max(b["high"] for b in all_bars)
        low = min(b["low"] for b in all_bars)
        print(f"  Range   : {low:.2f} → {high:.2f} ({high - low:.2f})")

    print("\n[OK] Termine.")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Telechargeur universel de donnees depuis MT5")
    parser.add_argument("symbol", nargs="?", default=None,
                        help="Symbole MT5 (ex: XAUUSD, EURUSD, US30.cash)")
    parser.add_argument("start", nargs="?", default="2026-01-01",
                        help="Date debut YYYY-MM-DD (defaut: 2026-01-01)")
    parser.add_argument("end", nargs="?", default="2026-06-27",
                        help="Date fin YYYY-MM-DD (defaut: 2026-06-27, exclusif)")
    parser.add_argument("--tf", default="M3",
                        help="Timeframe: M1, M3, M5, M15, M30, H1, H4, D1 (defaut: M3)")
    parser.add_argument("--list", action="store_true",
                        help="Lister les symboles disponibles et quitter")

    args = parser.parse_args()

    # Lister les symboles ?
    if args.list:
        if not mt5.initialize():
            print("[ERREUR] Connexion MT5")
            return 1
        list_symbols()
        mt5.shutdown()
        return 0

    if args.tf.upper() not in TIMEFRAME_MAP:
        print(f"[ERREUR] Timeframe inconnu: {args.tf}. Options: {list(TIMEFRAME_MAP)}")
        return 1

    if args.symbol is None:
        parser.print_help()
        print("\nExemples:")
        print("  python download_historical.py XAUUSD")
        print("  python download_historical.py EURUSD 2025-06-01 2026-06-01")
        print("  python download_historical.py US30.cash --tf M5")
        print("  python download_historical.py --list")
        return 1

    start_dt = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=UTC)
    end_dt = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=UTC)

    try:
        download(args.symbol, args.tf, start_dt, end_dt)
    except KeyboardInterrupt:
        print("\n[INTERROMPU]")
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
