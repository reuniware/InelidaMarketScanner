"""
post_dxy_analysis.py — Poste l'analyse de direction DXY sur Discord.
Format synthétique et orienté décisionnel basé sur le scan des 8 paires USD.

Usage:
    python post_dxy_analysis.py
    python post_dxy_analysis.py --no-send  # preview only
"""

import json
import os
import sys
from datetime import datetime, timezone

# Reuse proven webhook loading + sending from scheduled_scan_diamond
from scheduled_scan_diamond import _load_webhook, send_discord_webhook

# ── Config ────────────────────────────────────────────────────────────────────
COLOR_BLUE = 0x3498DB

UTC = timezone.utc


def build_dxy_embed() -> dict:
    """Build the DXY directional analysis embed."""
    now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    embed = {
        "title": f"🧭 Direction DXY — Analyse Pré-Asian {now_str}",
        "description": (
            "**DXY: 100.931** | Kijun H1: 100.883 | **AU-DESSUS** 🔼\n"
            "Triangulation du DXY via les 8 paires USD* et *USD"
        ),
        "color": COLOR_BLUE,
        "fields": [
            {
                "name": "📊 Score de Force USD (Basket 8 Paires)",
                "value": (
                    "```\n"
                    "USDJPY  : 🟢🟢 STRONG BULL  11/12 A4/5  ← seul bras armé\n"
                    "USDCAD  : 🔴   BEAR          4/12        ← tire DXY vers le bas\n"
                    "USDCHF  : 🟡   FLAT          6/12        ← neutre\n"
                    "EURUSD  : 🟡   FLAT coincé   4/12        ← Tenkan D1 à +0p\n"
                    "GBPUSD  : 🟡   FLAT coincé   6/12        ← W1 bear / D1 bull\n"
                    "AUDUSD  : 🔴🔴 BULL          7/12        ← anti-USD, SSB multiples\n"
                    "NZDUSD  : 🔴   FLAT (⚠️MN)   7/12        ← CONFLIT MN, RR asian 1.0\n"
                    "XAUUSD  : 🔴   FLAT          4/12        ← sous Kumo D1\n"
                    "```"
                ),
                "inline": False,
            },
            {
                "name": "🔬 Structure Ichimoku Consolidée",
                "value": (
                    "**H1**: 4/8 bearish USD 🔴 — momentum court-terme anti-dollar\n"
                    "**H4**: 5/8 bearish USD 🔴 — swing anti-dollar\n"
                    "**D1**: 4/8 vs 4/8 🟡 — split parfait, indécision\n"
                    "**Kumo D1**: 5/8 bullish USD 🟢 — structure HAUSSIÈRE\n\n"
                    "> Le DXY est en **pullback court-terme dans une structure haussière**. "
                    "Le Kumo D1 — indicateur le plus fiable — donne l'avantage au dollar."
                ),
                "inline": False,
            },
            {
                "name": "⚡ Le Baromètre : USDJPY",
                "value": (
                    "**Seule paire USD propre** — 0 avertissement, 0 piège\n"
                    "```\n"
                    "  161.948  ← KIJUN H4 (SL structurel, plat 20 bougies)\n"
                    "  162.117  ← PRIX ACTUEL   (+17p au-dessus)\n"
                    "  162.470  ← AH Asian (première résistance)\n"
                    "```\n"
                    "✅ **Tant que USDJPY > 161.948 → DXY HAUSSIER**\n"
                    "❌ **Si USDJPY < 161.948 → DXY s'effondre**"
                ),
                "inline": False,
            },
            {
                "name": "⚠️ Alertes Clés",
                "value": (
                    "• **EURUSD** coincé Tenkan D1 1.14172 (+0p) ↔ Kijun H1 1.14199 — cassure imminente\n"
                    "• **AUDUSD** compression entre 2 SSB + Tenkan D1 support/résistance — breakout garanti\n"
                    "• **NZDUSD** CONFLIT MN (juge de paix BEAR) vs Asian BUY RR 1.0 — ne pas shorter sans confirmation\n"
                    "• **USDCAD** Double Mémoire Tenkan MN = Kijun MN 1.41061 — plancher fantôme"
                ),
                "inline": False,
            },
            {
                "name": "🎯 Verdict & Plan d'Action",
                "value": (
                    "```\n"
                    "DXY UP    40%  ← structurel (Kumo D1, MN), USDJPY tient\n"
                    "DXY RANGE 30%  ← compression pré-Asian, attente breakout\n"
                    "DXY DOWN  30%  ← momentum H1/H4 anti-USD + Asian sweeps\n"
                    "```\n"
                    "**🔺 Action #1 : Surveiller USDJPY 161.948**\n"
                    "   → BUY si le prix rebondit sur le Kijun H4 avec confirmation\n"
                    "   → SL 161.890 | TP1 162.470 | TP2 162.740 | RR 2.0x\n\n"
                    "**🔺 Action #2 : Attendre la cassure EURUSD**\n"
                    "   → SHORT si EURUSD casse 1.14170 (confirme DXY haussier)\n"
                    "   → BUY si EURUSD passe 1.14200 (DXY baissier confirmé)\n\n"
                    "**⏸️  Skip**: GBPUSD, NZDUSD, USDCAD — signaux contradictoires\n"
                    "**⏸️  Skip**: XAUUSD — dynamique propre décorrélée du DXY"
                ),
                "inline": False,
            },
            {
                "name": "🏁 Résumé Décisionnel",
                "value": (
                    "✅ **Biais DXY : HAUSSIER structurel, NEUTRE court-terme**\n"
                    "✅ **Trade du moment : USDJPY BUY sur pullback 161.95-162.04**\n"
                    "⚠️ **Condition : USDJPY doit tenir au-dessus de 161.948**\n"
                    "⏱️  **Timing : Ouverture Asian 00:00 UTC — la compression se résout**"
                ),
                "inline": False,
            },
        ],
        "footer": {"text": "Inelida DXY Triangulation — Diamond Analysis v2"},
        "timestamp": datetime.now(UTC).isoformat(),
    }

    return embed


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Post DXY directional analysis to Discord")
    parser.add_argument("--no-send", action="store_true", help="Preview embed only, don't send")
    args = parser.parse_args()

    embed = build_dxy_embed()

    if args.no_send:
        print(json.dumps({"embeds": [embed]}, ensure_ascii=False, indent=2))
        return 0

    webhook_url = _load_webhook()
    if not webhook_url:
        print("[ERREUR] Aucun webhook Discord trouve (.env ou DISCORD_WEBHOOK_URL)", file=sys.stderr)
        return 1

    ok = send_discord_webhook(webhook_url, [embed])
    print(f"Discord: {'OK envoye' if ok else 'ECHEC'}")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
