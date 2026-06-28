"""
download_historical.py — Telechargeur universel de donnees M3 depuis MT5

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
CHUNK_DAYS = 30


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

    # --- Telechargement par chunks ---
    print(f"\n[2/3] Telechargement {timeframe_str} par chunks de {CHUNK_DAYS} jours...")
    all_bars = []
    chunk_start = start_dt
    chunk_num = 0
    total_bars = 0

    while chunk_start < end_dt:
        chunk_end_ts = chunk_start.timestamp() + CHUNK_DAYS * 86400
        chunk_end_dt = datetime.fromtimestamp(chunk_end_ts, tz=UTC) if chunk_end_ts < end_dt.timestamp() else end_dt

        chunk_num += 1
        print(f"  Chunk {chunk_num:02d} : {chunk_start.strftime('%Y-%m-%d')} --> "
              f"{chunk_end_dt.strftime('%Y-%m-%d')} ...", end=" ", flush=True)

        rates = mt5.copy_rates_range(symbol, tf, chunk_start, chunk_end_dt)
        if rates is None or len(rates) == 0:
            print("0 barres")
            chunk_start = chunk_end_dt
            continue

        chunk_bars = []
        for r in rates:
            chunk_bars.append({
                "time": int(r[0]),
                "open": float(r[1]),
                "high": float(r[2]),
                "low": float(r[3]),
                "close": float(r[4]),
                "tick_volume": int(r[5]),
                "spread": int(r[6]) if len(r) > 6 else 0,
                "real_volume": int(r[7]) if len(r) > 7 else 0,
            })

        all_bars.extend(chunk_bars)
        n = len(chunk_bars)
        total_bars += n
        first_dt = datetime.fromtimestamp(chunk_bars[0]["time"], tz=UTC).strftime("%Y-%m-%d %H:%M")
        last_dt = datetime.fromtimestamp(chunk_bars[-1]["time"], tz=UTC).strftime("%Y-%m-%d %H:%M")
        print(f"{n} barres ({first_dt} --> {last_dt})")
        chunk_start = chunk_end_dt

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
        print(f"  Periode : {first.strftime('%Y-%m-%d %H:%M')} --> {last.strftime('%Y-%m-%d %H:%M')} UTC")
        high = max(b["high"] for b in all_bars)
        low = min(b["low"] for b in all_bars)
        print(f"  Range   : {low:.2f} --> {high:.2f} ({high - low:.2f})")

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
