"""
monitor_dxy_pivot.py — Surveillance DXY vs pivot Kijun H1=H4.

Surveille en temps reel la position du DXY par rapport a son pivot Kijun
H1=H4 confluent. Le pivot est calcule automatiquement au demarrage comme
la moyenne des Kijun H1 et H4 actuels. Envoie une alerte Discord en cas
de cassure du pivot.

Usage:
    python monitor_dxy_pivot.py              # demarre la surveillance
    python monitor_dxy_pivot.py --poll 15    # polling toutes les 15s
    python monitor_dxy_pivot.py --console    # sortie console uniquement
"""
import argparse
import sys
import os
import time
from datetime import datetime, timezone
from typing import Optional, Tuple

import MetaTrader5 as mt5

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scheduled_scan_diamond import _load_webhook, send_discord_webhook

UTC = timezone.utc

# Couleurs Discord
COLOR_GREEN  = 0x2ECC71
COLOR_RED    = 0xE74C3C
COLOR_ORANGE = 0xE67E22
COLOR_BLUE   = 0x3498DB

LAST_STATE = None  # "ABOVE" ou "BELOW"
ALERTED = False
PIVOT_KJ = 0.0     # calcule au demarrage


def _poll_dxy() -> Tuple[Optional[float], float, float, float]:
    """Recupere tous les indicateurs DXY en une seule initialisation MT5.

    Returns:
        (price, kj_h1, kj_h4, tk_h1) ou (None, 0, 0, 0) si erreur.
    """
    if not mt5.initialize():
        return (None, 0.0, 0.0, 0.0)

    price = None
    kj_h1 = 0.0
    kj_h4 = 0.0
    tk_h1 = 0.0

    for sym in ['DXY.cash', 'DXY', 'USDX']:
        mt5.symbol_select(sym, True)
        t = mt5.symbol_info_tick(sym)
        if t:
            price = float(t.bid)
            # H1
            r1 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 60)
            if r1 is not None and len(r1) >= 27:
                h1 = [float(x[2]) for x in r1]
                l1 = [float(x[3]) for x in r1]
                kj_h1 = (max(h1[-26:]) + min(l1[-26:])) / 2.0
                if len(h1) >= 10:
                    tk_h1 = (max(h1[-9:]) + min(l1[-9:])) / 2.0
            # H4
            r4 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H4, 0, 60)
            if r4 is not None and len(r4) >= 27:
                h4 = [float(x[2]) for x in r4]
                l4 = [float(x[3]) for x in r4]
                kj_h4 = (max(h4[-26:]) + min(l4[-26:])) / 2.0
            break  # premier symbole trouve

    mt5.shutdown()
    return (price, kj_h1, kj_h4, tk_h1)


def _calc_pivot(kj_h1: float, kj_h4: float) -> float:
    """Calcule le pivot = moyenne des Kijun H1 et H4."""
    if kj_h1 > 0 and kj_h4 > 0:
        return (kj_h1 + kj_h4) / 2.0
    return 100.883  # fallback sur la valeur empirique


def build_status_embed(price, kj_h1, kj_h4, tk_h1, pivot, above, changed=None):
    """Construit un embed de statut DXY."""
    state_str = "AU-DESSUS" if above else "EN-DESSOUS"
    color = COLOR_GREEN if above else COLOR_RED
    state_icon = "🟢" if above else "🔴"

    desc = (
        f"DXY **{price:.3f}** est **{state_str}** du pivot Kijun "
        f"{pivot:.3f} → {'haussier' if above else 'baissier'}"
    )
    if changed:
        desc += (
            f"\n\n**CHANGEMENT D'ETAT — Cassure du pivot !**"
            f"\nDXY {'repasse AU-DESSUS' if changed == 'ABOVE' else 'passe EN-DESSOUS'}"
            f"\n→ EURUSD {'peut etre rejete du mur 1.14402' if changed == 'ABOVE' else 'peut poursuivre vers 1.148+'}"
        )

    fields = [
        {
            "name": f"{state_icon} DXY — Ichimoku H1",
            "value": (
                f"Prix: **{price:.3f}**\n"
                f"Tenkan H1: {tk_h1:.3f}\n"
                f"Kijun H1: {kj_h1:.3f}\n"
                f"Kijun H4: {kj_h4:.3f}\n"
                f"Pivot H1=H4: **{pivot:.3f}**"
            ),
            "inline": True,
        },
        {
            "name": "Impact EURUSD",
            "value": (
                f"DXY {state_str} {state_icon}\n"
                f"EURUSD {'vers TP 1.148' if not above else 'rejet possible'}\n"
                f"Mur 1.14402: {'FRAGILE' if not above else 'SOLIDE'}"
            ),
            "inline": True,
        },
        {
            "name": "Contexte",
            "value": (
                f"Distance pivot: {abs(price - pivot):.3f}\n"
                f"Heure: {datetime.now(UTC).strftime('%H:%M:%S')} UTC\n"
                f"Polling: en cours..."
            ),
            "inline": False,
        },
    ]

    embed = {
        "title": f"DXY Pivot Monitor — {datetime.now(UTC).strftime('%H:%M')} UTC",
        "description": desc,
        "color": color,
        "fields": fields,
        "footer": {"text": "DXY Kijun H1=H4 Confluent Monitor — Inelida"},
        "timestamp": datetime.now(UTC).isoformat(),
    }
    return embed


def main():
    parser = argparse.ArgumentParser(description="DXY Pivot Monitor")
    parser.add_argument("--poll", type=int, default=30, help="Polling interval (seconds)")
    parser.add_argument("--pivot", type=float, default=0, help="Force pivot value (sinon automatique)")
    parser.add_argument("--console", action="store_true", help="Console output only, no Discord")
    args = parser.parse_args()

    webhook = None if args.console else _load_webhook()
    poll_sec = max(5, min(args.poll, 300))

    # Calcul du pivot au demarrage
    global PIVOT_KJ
    if args.pivot > 0:
        PIVOT_KJ = args.pivot
    else:
        _, kj_h1, kj_h4, _ = _poll_dxy()
        PIVOT_KJ = _calc_pivot(kj_h1, kj_h4)

    print("=" * 60)
    print(f"  DXY PIVOT MONITOR")
    print(f"  Pivot Kijun H1=H4: {PIVOT_KJ:.3f}")
    print(f"  Polling: {poll_sec}s | Discord: {'OK' if webhook else 'console only'}")
    print("=" * 60)

    global LAST_STATE, ALERTED

    try:
        while True:
            now = datetime.now(UTC)
            price, kj_h1, kj_h4, tk_h1 = _poll_dxy()
            if price is None:
                print(f"[{now.strftime('%H:%M:%S')}] ERREUR: DXY indisponible")
                time.sleep(poll_sec)
                continue

            # Recalculer le pivot a chaque cycle (au cas ou Kijun bouge)
            if args.pivot == 0:
                new_pivot = _calc_pivot(kj_h1, kj_h4)
                if new_pivot > 0:
                    PIVOT_KJ = new_pivot

            above = price > PIVOT_KJ
            changed = None

            current_state = "ABOVE" if above else "BELOW"
            if LAST_STATE is not None and LAST_STATE != current_state:
                changed = current_state
                ALERTED = False
            LAST_STATE = current_state

            # Affichage console (sans emoji pour compatibilite cp1252)
            state_text = "AU-DESSUS" if above else "EN-DESSOUS"
            changed_text = "  CASSURE!" if changed else ""
            print(
                f"[{now.strftime('%H:%M:%S')}] DXY {price:.3f} | "
                f"KjH1 {kj_h1:.3f} KjH4 {kj_h4:.3f} | "
                f"Pivot {PIVOT_KJ:.3f} | {state_text}{changed_text}"
            )

            # Envoi Discord sur changement ou 1ere detection
            if webhook and (changed or (not ALERTED)):
                embed = build_status_embed(
                    price, kj_h1, kj_h4, tk_h1, PIVOT_KJ, above, changed
                )
                ok = send_discord_webhook(webhook, [embed])
                if ok:
                    label = "ALERTE CASSURE" if changed else "Etat initial"
                    print(f"  Discord: {label} envoyee")
                    ALERTED = True

            time.sleep(poll_sec)

    except KeyboardInterrupt:
        print(f"\n[{datetime.now(UTC).strftime('%H:%M:%S')}] Monitor arrete.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
