"""
monitor_dol_live.py -- Surveillance DOL (Draw On Liquidity) en temps reel.

Surveille les zones de liquidite ICT identifiees par le Diamond Scanner
et alerte quand le prix entre dans une zone DOL ou la balaye.

Zones surveillees:
  - DOL support: zone de liquidite basse (stops en dessous)
  - DOL resistance: zone de liquidite haute (stops au-dessus)
  - Opposite liquidity: la zone inverse pas encore balayee

Usage:
    python monitor_dol_live.py                     # surveillance complete
    python monitor_dol_live.py --symbols EURUSD    # un seul actif
    python monitor_dol_live.py --poll 10           # polling 10s
    python monitor_dol_live.py --console           # console seulement
"""
import argparse
import os
import sys
import time
from datetime import datetime, timezone
from typing import List, Optional

import MetaTrader5 as mt5

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scheduled_scan_diamond import _load_webhook, send_discord_webhook
from scheduled_scan_diamond import COLOR_GREEN, COLOR_RED, COLOR_BLUE, COLOR_ORANGE, COLOR_PURPLE

UTC = timezone.utc

# ── Configuration des zones DOL (issues du scan 13:14 UTC) ──────────────────
# Chaque zone = (symbole, prix_ref, dol_support_level, dol_resistance_level, 
#                opposite_support_target, opposite_resistance_target, note)

DOL_ZONES = [
    # USDJPY - deja en cassure vers le haut
    ("USDJPY", 162.230,
     162.183,     # Kijun H4 memoire (7b) - DOL support
     162.232,     # Kijun H1 memoire (3b) - DOL resistance (deja sweepe)
     162.007,     # Kijun H1 - opposite support
     162.442,     # TL haute daily - opposite resistance
     "DOL HAUT sweepe vers 162.442 | DOL BAS 162.183 non sweepe"),
    # EURUSD - compression dans la zone
    ("EURUSD", 1.14275,
     1.14233,     # Kijun H1 memoire (7b) - DOL support
     1.14282,     # Tenkan H4 memoire (6b) - DOL resistance
     1.14172,     # Tenkan D1 (3j) - opposite support
     1.14402,     # Kijun MN (5mois) - opposite resistance
     "4 KUMO FLAT = magnet bas | 20+ tests dans la zone"),
    # GBPUSD - double DOL W1 vs D1
    ("GBPUSD", 1.34274,
     1.34227,     # Tenkan D1 memoire (4j) - DOL support
     1.34391,     # Kijun W1 (14sem) - DOL resistance
     1.33967,     # Kijun H4 - opposite support
     1.34600,     # Satelys resistance - opposite resistance
     "Virage Kumo W1 ROUGE | DOL haut 14sem massif"),
    # USDCAD - DOL massif pre-BoC
    ("USDCAD", 1.40565,
     1.40510,     # Tenkan D1 memoire (5j) - DOL support
     1.40628,     # Tenkan D1 memoire (3j) - DOL resistance
     1.40413,     # Kijun W1 (4sem) - opposite support
     1.41061,     # Double memoire MN - opposite resistance
     "Tenkan H1 13b plat | BoC 15:45 catalyseur"),
    # USDCHF - compression 5p extreme
    ("USDCHF", 0.80909,
     0.80893,     # Confluence Kijun H1=H4 - DOL support
     0.80946,     # Tenkan H1 memoire (3b) - DOL resistance
     0.80800,     # Zone sous Kumo H1 - opposite support
     0.81050,     # Zone Kijun H4 large - opposite resistance
     "Compression 5p | Kijun H4 12b plat"),
    # AUDUSD - range DOL symetrique
    ("AUDUSD", 0.69936,
     0.69853,     # Tenkan D1 memoire (2j) - DOL support
     0.69971,     # Tenkan D1 memoire (4j) - DOL resistance
     0.69709,     # Kijun W1 (4sem) - opposite support
     0.70102,     # Tenkan W1 (2sem) - opposite resistance
     "Virage Kumo MN ROUGE | Mur W1/MN"),
]

# Cache pour les alertes (evite les doublons)
_alerted_sweep: dict = {}  # {symbol: "ABOVE"|"BELOW"|None}


def _fmt(v, sym: str = "") -> str:
    """Format price selon l'instrument."""
    if v is None or v == 0:
        return "?"
    if 'JPY' in sym:
        return f"{v:.3f}"
    if v >= 1000:
        return f"{v:.2f}"
    if v >= 10:
        return f"{v:.4f}"
    return f"{v:.5f}"


def _pct_dist(sym: str, price: float, level: float) -> float:
    """Distance en pips."""
    if price == 0:
        return 0
    if 'JPY' in sym:
        return (price - level) * 100
    if sym == 'XAUUSD':
        return (price - level)
    return (price - level) * 10000


def _poll_all(symbols: List[str]) -> dict:
    """Recupere les prix live de tous les symboles en une connexion MT5."""
    if not mt5.initialize():
        return {}

    result = {}
    for sym in symbols:
        mt5.symbol_select(sym, True)
        t = mt5.symbol_info_tick(sym)
        if t:
            result[sym] = float(t.bid)
    mt5.shutdown()
    return result


def check_sweeps(price: float, sym: str, dol_sup: float, dol_res: float) -> Optional[str]:
    """Detecte si le prix a sweepe une zone DOL.
    Returns "ABOVE" (sweep resistance), "BELOW" (sweep support), ou None."""
    if price > dol_res:
        return "ABOVE"
    if price < dol_sup:
        return "BELOW"
    return None


def build_dol_embed(sym: str, price: float, zone: tuple, sweep: Optional[str],
                    opp_target: float, pips_to_opp: float, note: str):
    """Construit un embed Discord pour l'alerte DOL."""
    now_str = datetime.now(UTC).strftime("%H:%M UTC")
    _, _, dol_sup, dol_res, opp_sup, opp_res, _ = zone

    if sweep == "ABOVE":
        color = COLOR_GREEN
        title = f"DOL SWEEP HAUT -- {sym}"
        direction = "HAUSSIER"
        opp = opp_res
        icon = "🟢"
    elif sweep == "BELOW":
        color = COLOR_RED
        title = f"DOL SWEEP BAS -- {sym}"
        direction = "BEAR"
        opp = opp_sup
        icon = "🔴"
    else:
        color = COLOR_BLUE
        title = f"DOL ZONE -- {sym}"
        direction = "DANS LA ZONE"
        opp = 0
        icon = "🔵"

    # Position dans la zone
    if sym in ('XAUUSD', 'XAGUSD'):
        range_size = abs(dol_res - dol_sup)
    elif 'JPY' in sym:
        range_size = abs(dol_res - dol_sup) * 100
    else:
        range_size = abs(dol_res - dol_sup) * 10000
    pos_in_range = ((price - dol_sup) / (dol_res - dol_sup) * 100) if (dol_res - dol_sup) > 0 else 50

    def _fmt_pips(v):
        if sym == 'XAUUSD' or sym == 'XAGUSD':
            return f"{v:.1f}$"
        return f"{v:.1f}p"

    sup_dist = _pct_dist(sym, price, dol_sup)
    res_dist = _pct_dist(sym, price, dol_res)

    desc = (
        f"**{sym}** {_fmt(price, sym)} -- **{direction}** {icon}\n"
        f"Zone DOL: {_fmt(dol_sup, sym)} | {_fmt(price, sym)} | {_fmt(dol_res, sym)}\n"
        f"Position dans la zone: **{pos_in_range:.0f}%**\n"
        f"Distance DOL support: {_fmt_pips(abs(sup_dist))} {'⚠️ SWEEP' if price <= dol_sup else ''}\n"
        f"Distance DOL resistance: {_fmt_pips(abs(res_dist))} {'⚠️ SWEEP' if price >= dol_res else ''}"
    )

    if sweep:
        desc += (
            f"\n\n**DOL {sweep} SWEEPE !**"
            f"\nLiquidite au-dessus de {_fmt(dol_res, sym) if sweep == 'ABOVE' else _fmt(dol_sup, sym)} prise !"
            f"\nProchaine cible: **{_fmt(opp, sym)}** ({_fmt_pips(abs(pips_to_opp))})"
        )

    fields = [
        {
            "name": "Niveaux DOL",
            "value": (
                f"Resistance: **{_fmt(dol_res, sym)}** ({_fmt_pips(abs(res_dist))})\n"
                f"Support: **{_fmt(dol_sup, sym)}** ({_fmt_pips(abs(sup_dist))})\n"
                f"Range: {_fmt_pips(range_size)}"
            ),
            "inline": True,
        },
        {
            "name": "Opposite Liquidity",
            "value": (
                f"Opposite HAUT: {_fmt(opp_res, sym)} ({_fmt_pips(abs(_pct_dist(sym, price, opp_res)))}\n"
                f"Opposite BAS: {_fmt(opp_sup, sym)} ({_fmt_pips(abs(_pct_dist(sym, price, opp_sup)))}\n"
                f"Note: {note[:80]}"
            ),
            "inline": True,
        },
    ]

    embed = {
        "title": title,
        "description": desc,
        "color": color,
        "fields": fields,
        "footer": {"text": f"DOL Monitor -- {now_str}"},
        "timestamp": datetime.now(UTC).isoformat(),
    }
    return embed


def print_console(sym: str, price: float, dol_sup: float, dol_res: float,
                  sweep: Optional[str], opp_target: float, note: str):
    """Affichage console compact."""
    now = datetime.now(UTC).strftime("%H:%M:%S")

    sup_dist = _pct_dist(sym, price, dol_sup)
    res_dist = _pct_dist(sym, price, dol_res)
    range_size = abs(_pct_dist(sym, dol_res, dol_sup))

    if sweep == "ABOVE":
        state = "SWEEP HAUT"
    elif sweep == "BELOW":
        state = "SWEEP BAS"
    elif price > (dol_sup + dol_res) / 2:
        state = "HAUT"
    else:
        state = "BAS"

    bar_count = max(0, min(20, int(abs(sup_dist)) if abs(sup_dist) < 20 else 20)) if sweep != "ABOVE" else 0
    bar_count = max(bar_count, max(0, min(20, int(abs(res_dist))))) if sweep != "BELOW" else bar_count

    bar = "|" * min(bar_count, 10)

    # Affichage sans emoji (cp1252)
    print(
        f"[{now}] {sym:<8} {_fmt(price, sym):>10} | "
        f"Sup {_fmt(dol_sup, sym):>10} Res {_fmt(dol_res, sym):>10} | "
        f"Range {abs(range_size):>6.1f}p | {state:<15} {bar}"
    )


def main():
    parser = argparse.ArgumentParser(description="DOL Live Monitor")
    parser.add_argument("--symbols", nargs="*", default=None,
                        help="Symboles a surveiller (defaut: tous)")
    parser.add_argument("--poll", type=int, default=15,
                        help="Polling interval (secondes)")
    parser.add_argument("--console", action="store_true",
                        help="Console output only")
    args = parser.parse_args()

    webhook = None if args.console else _load_webhook()

    # Filtrer les zones DOL
    zones = DOL_ZONES
    if args.symbols:
        zones = [z for z in zones if z[0] in args.symbols]

    poll_sec = max(5, min(args.poll, 120))

    print("=" * 60)
    print("  DOL LIVE MONITOR -- Draw On Liquidity")
    print(f"  Symboles: {len(zones)} -- {' '.join(z[0] for z in zones)}")
    print(f"  Polling: {poll_sec}s | Discord: {'OK' if webhook else 'console'}")
    print("=" * 60)

    for z in zones:
        sym, price_ref, dol_sup, dol_res, opp_sup, opp_res, note = z
        range_p = abs(_pct_dist(sym, dol_res, dol_sup))
        print(f"  {sym:<8} DOL [{_fmt(dol_sup, sym)} - {_fmt(dol_res, sym)}] "
              f"range {range_p:.1f}p | Note: {note[:60]}")
    print("=" * 60)

    try:
        while True:
            now = datetime.now(UTC)

            # Recuperer tous les prix
            symbols_to_poll = [z[0] for z in zones]
            prices = _poll_all(symbols_to_poll)

            if not prices:
                print(f"[{now.strftime('%H:%M:%S')}] ERREUR: MT5 indisponible")
                time.sleep(poll_sec)
                continue

            alerts_to_send = []

            for z in zones:
                sym, price_ref, dol_sup, dol_res, opp_sup, opp_res, note = z
                price = prices.get(sym)
                if price is None:
                    continue

                # Detection sweep
                sweep = check_sweeps(price, sym, dol_sup, dol_res)

                # Opposite liquidity target
                if sweep == "ABOVE":
                    opp_target = opp_res
                    pips_to_opp = _pct_dist(sym, opp_res, price)
                elif sweep == "BELOW":
                    opp_target = opp_sup
                    pips_to_opp = _pct_dist(sym, opp_sup, price)  # negative
                else:
                    opp_target = 0
                    pips_to_opp = 0

                # Alerte si changement d'etat
                prev_sweep = _alerted_sweep.get(sym)
                is_new = (sweep != prev_sweep)
                if is_new:
                    _alerted_sweep[sym] = sweep
                    if sweep is not None:
                        alerts_to_send.append((z, price, sweep, opp_target, pips_to_opp))
                    elif prev_sweep is not None:
                        # Retour dans la zone
                        alerts_to_send.append((z, price, None, 0, 0))

                # Affichage console
                print_console(sym, price, dol_sup, dol_res, sweep, opp_target, note)

            # Envoyer les alertes Discord
            if webhook and alerts_to_send:
                embeds = []
                for z, price, sweep, opp_target, pips_to_opp in alerts_to_send:
                    embed = build_dol_embed(z[0], price, z, sweep, opp_target, pips_to_opp, z[6])
                    embeds.append(embed)
                if embeds:
                    ok = send_discord_webhook(webhook, embeds)
                    print(f"  [Discord] {'OK' if ok else 'ECHEC'} -- {len(embeds)} alerte(s)")

            # Separateur visuel
            print(f"  [{datetime.now(UTC).strftime('%H:%M:%S')}] {'-' * 50}")

            time.sleep(poll_sec)

    except KeyboardInterrupt:
        print(f"\n[{datetime.now(UTC).strftime('%H:%M:%S')}] DOL Monitor arrete.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
