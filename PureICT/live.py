"""PureICT — Mode live : rafraichit les prix en continu avec distances AH/AL.

Dependances :
  - PureICT.models, PureICT.config, PureICT.scanner
  - MetaTrader5, src.mt5_connector, src.time_utils
"""

import logging
import os
import sys
import time
from datetime import timedelta
from typing import List

# Chemin projet
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    import MetaTrader5 as mt5
except ImportError:
    print("\n  !! MetaTrader5 n'est pas installe.")
    print("     Installe-le avec : pip install MetaTrader5")
    sys.exit(1)

from src.mt5_connector import MT5Connector
from src.time_utils import now_datetime

from .models import AsianLevels, fmt_price
from .config import (
    _tz_offset, _fmt_fvg_compact, format_epoch,
)

logger = logging.getLogger("PureICT.Live")


# ===============================================================================
# MODE LIVE
# ===============================================================================

def live_monitor(results: List[AsianLevels], tz_mode: str, interval: int,
                 show_ote: bool = False):
    """Mode live : rafraichit les prix en continu et affiche distances AH/AL."""
    if not results:
        return

    mt5c = MT5Connector()
    if not mt5c.ensure_connected():
        print("  !! MT5 non connecte - impossible de passer en mode live.")
        return

    offset = _tz_offset(tz_mode)
    n = len(results)

    print(f"\n  === MODE LIVE (Ctrl+C pour quitter) ===")
    print(f"  Symboles : {n}  |  Rafraichissement : {interval}s")
    print(f"  Niveaux fixes (session terminee) - Prix temps reel\n")

    # Detecter si FVG ou marge disponibles
    _has_fvg_live = any(r.fvg_ah or r.fvg_al for r in results)
    _has_margin_live = any(r.max_lots is not None for r in results)

    tick_count = 0
    try:
        while True:
            tick_count += 1
            local_now = now_datetime() + timedelta(hours=offset)

            # Effacer l'ecran
            if tick_count > 1:
                if os.name == 'nt':
                    os.system('cls')
                else:
                    os.system('clear')

            print(f"PureICT Live - {local_now.strftime('%H:%M:%S')} {tz_mode}  |  tick #{tick_count}")

            # Entete dynamique selon les colonnes disponibles
            if _has_fvg_live:
                if _has_margin_live:
                    hdr = (f"  {'Symbole':<12} {'Prix':>10} {'AH':>10} {'AL':>10} "
                           f"{'Dist AH':>9} {'Dist AL':>9} {'vs Mid':>8} "
                           f"{'FVG AH':>26} {'FVG AL':>26} {'AHS':>5} {'ALS':>5} {'Lots':>7}   {'Pos':<6}")
                    sep_len = 165
                else:
                    hdr = (f"  {'Symbole':<12} {'Prix':>10} {'AH':>10} {'AL':>10} "
                           f"{'Dist AH':>9} {'Dist AL':>9} {'vs Mid':>8} "
                           f"{'FVG AH':>26} {'FVG AL':>26} {'AHS':>5} {'ALS':>5}   {'Pos':<6}")
                    sep_len = 145
            else:
                if _has_margin_live:
                    hdr = (f"  {'Symbole':<12} {'Prix':>10} {'AH':>10} {'AL':>10} "
                           f"{'Dist AH':>9} {'Dist AL':>9} {'vs Mid':>8} "
                           f"{'AHS':>5} {'ALS':>5} {'Lots':>7}   {'Pos':<6}")
                    sep_len = 107
                else:
                    hdr = (f"  {'Symbole':<12} {'Prix':>10} {'AH':>10} {'AL':>10} "
                           f"{'Dist AH':>9} {'Dist AL':>9} {'vs Mid':>8} "
                           f"{'AHS':>5} {'ALS':>5}   {'Pos':<6}")
                    sep_len = 99

            print(hdr)
            print(f"  {'-' * sep_len}")

            for r in results:
                tick = mt5.symbol_info_tick(r.symbol)
                if tick is None:
                    continue
                price = float(tick.bid)

                dist_ah_pct = (price - r.asian_high) / r.asian_high * 100.0 if r.asian_high else 0.0
                dist_al_pct = (price - r.asian_low) / r.asian_low * 100.0 if r.asian_low else 0.0
                vs_mid = (price - r.midpoint) / r.midpoint * 100.0 if r.midpoint else 0.0

                mid_sign = ">" if vs_mid > 0 else ("<" if vs_mid < 0 else "=")

                ah_swept_str = "AH" if r.ah_swept else "-"
                al_swept_str = "AL" if r.al_swept else "-"

                if price > r.asian_high:
                    marker = "ABOVE "
                elif price < r.asian_low:
                    marker = "BELOW "
                else:
                    marker = "IN    "

                # OTE recalcule en live
                ote_marker = ""
                if show_ote:
                    in_ote_live_bear = r.ote_bear_low <= price <= r.ote_bear_high if r.range_pips > 0 else False
                    in_ote_live_bull = r.ote_bull_low <= price <= r.ote_bull_high if r.range_pips > 0 else False
                    if in_ote_live_bear or in_ote_live_bull:
                        ote_marker = " OTE"

                fvg_ah_str = _fmt_fvg_compact(r.fvg_ah)
                fvg_al_str = _fmt_fvg_compact(r.fvg_al)
                lots_col = f" {r.max_lots:.2f}" if _has_margin_live and r.max_lots is not None else ""

                if _has_fvg_live:
                    print(f"  {r.symbol:<12} {fmt_price(price):>10} {fmt_price(r.asian_high):>10} "
                          f"{fmt_price(r.asian_low):>10} "
                          f"{dist_ah_pct:+8.2f}% "
                          f"{dist_al_pct:+8.2f}% "
                          f"{mid_sign}{abs(vs_mid):>6.2f}% "
                          f"{fvg_ah_str:>26} {fvg_al_str:>26} {ah_swept_str:>5} {al_swept_str:>5} {lots_col:>8}   {marker}{ote_marker}")
                else:
                    print(f"  {r.symbol:<12} {fmt_price(price):>10} {fmt_price(r.asian_high):>10} "
                          f"{fmt_price(r.asian_low):>10} "
                          f"{dist_ah_pct:+8.2f}% "
                          f"{dist_al_pct:+8.2f}% "
                          f"{mid_sign}{abs(vs_mid):>6.2f}% "
                          f"{ah_swept_str:>5} {al_swept_str:>5} {lots_col:>8}   {marker}{ote_marker}")

            print(f"  {'-' * sep_len}")
            print(f"  Ctrl+C pour quitter  |  Intervalle: {interval}s")

            time.sleep(interval)
    except KeyboardInterrupt:
        print(f"\n\n  Mode live termine apres {tick_count} tick(s).")
