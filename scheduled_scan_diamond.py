"""
scheduled_scan_diamond.py — Scan automatise Diamond + Asian + envoi Discord.

Execute un scan Diamond Analysis complet (Ichimoku multi-TF + Etape 3b + W1/MN)
ET un scan Asian ICT, puis envoie un embed Discord combinant les deux.

Usage:
    python scheduled_scan_diamond.py
    python scheduled_scan_diamond.py --no-discord  # affichage console seulement
    python scheduled_scan_diamond.py --symbols EURUSD GBPUSD XAUUSD
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import List, Dict, Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.diamond_scanner import DiamondScanner, get_dxy_price, get_dxy_kijun_h1
from src.sweep_detector import detect_asian_range_for_symbol
from src.config import resolve_watchlist

UTC = timezone.utc
DEFAULT_SYMBOLS = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD",
    "XAUUSD", "GBPJPY", "EURJPY",
    "US30.cash", "US100.cash", "US500.cash",
]

# Discord colors
COLOR_GREEN = 0x2ECC71
COLOR_ORANGE = 0xE67E22
COLOR_PURPLE = 0x9B59B6
COLOR_BLUE = 0x3498DB
COLOR_RED = 0xE74C3C


def _fmt(v):
    if v is None or v == 0:
        return "?"
    if isinstance(v, float):
        if abs(v) >= 1000:
            return f"{v:.2f}"
        if abs(v) >= 10:
            return f"{v:.4f}"
        return f"{v:.5f}"
    return str(v)


def _load_webhook() -> Optional[str]:
    """Load Discord webhook URL from .env (UTF-16 LE aware)."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.isfile(env_path):
        return os.environ.get("DISCORD_WEBHOOK_URL")

    raw = None
    with open(env_path, "rb") as f:
        raw = f.read()

    # Handle UTF-16 LE (with or without BOM). Detected by:
    #  - BOM bytes \xff\xfe at start, OR
    #  - null bytes at odd positions (ASCII in UTF-16 LE without BOM)
    if raw[:2] == b'\xff\xfe' or (len(raw) >= 6 and raw[1:6:2] == b'\x00\x00\x00'):
        text = raw.decode("utf-16-le", errors="ignore")
    else:
        text = raw.decode("utf-8", errors="ignore")

    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("DISCORD_WEBHOOK_URL="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")

    return os.environ.get("DISCORD_WEBHOOK_URL")


def send_discord_webhook(webhook_url: str, embeds: List[dict]) -> bool:
    """Send embed(s) to Discord webhook directly (per Piege #10)."""
    payload = json.dumps({"embeds": embeds}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "InelidaDiamondScanner/1.0",
        },
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.status == 204
    except Exception as e:
        print(f"[Discord] Error: {e}", file=sys.stderr)
        return False


def run_diamond_scan(symbols: List[str]) -> List:
    """Run DiamondAnalysis scan and return results sorted by quality."""
    scanner = DiamondScanner(symbols)
    if not scanner.initialize():
        print("[ERROR] MT5 init failed for Diamond scan.", file=sys.stderr)
        return []
    try:
        results = scanner.scan_all()
        return results
    finally:
        scanner.shutdown()


def run_asian_scan(symbols: List[str]) -> List:
    """Run Asian session scan and return results with trades."""
    import MetaTrader5 as mt5
    mt5.initialize()
    results = []
    for sym in symbols:
        r = detect_asian_range_for_symbol(sym, timeframe="H1")
        if r is not None:
            results.append(r)
    mt5.shutdown()
    return results


def build_diamond_embed(results, symbols_count: int) -> dict:
    """Build Discord embed for Diamond Analysis scan."""
    now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    active = [r for r in results if r.bias != "FLAT" and r.quality != "WAIT"]
    n_strong = sum(1 for r in results if r.quality == "STRONG")
    n_good = sum(1 for r in results if r.quality == "GOOD")
    n_bull = sum(1 for r in results if r.bias == "BULL")
    n_bear = sum(1 for r in results if r.bias == "BEAR")

    # DXY
    dxy_price = get_dxy_price()
    dxy_kj = get_dxy_kijun_h1()
    dxy_line = ""
    if dxy_price:
        dxy_line = f"DXY: **{dxy_price:.3f}**"
        if dxy_kj:
            vs = "AU-DESSUS 🔼" if dxy_price > dxy_kj else "EN-DESSOUS 🔽"
            dxy_line += f" | Kijun H1: {dxy_kj:.3f} | **{vs}**"

    # Top setups
    top_setups = []
    for r in results[:10]:
        align_str = f" A{r.alignment}/5" if r.alignment > 0 else ""
        warn_str = " ⚠️" if r.warnings else ""
        d_kj = f" Δ{_fmt(r.d_kj4)}p" if r.d_kj4 != 0 else ""
        top_setups.append(
            f"`{r.symbol:<10} {r.score:>2}/{r.max_score} {r.bias:<5} {r.quality:<7}{align_str} "
            f"Kj4:{_fmt(r.kj_h4)}{d_kj}{warn_str}`"
        )

    # Active setups detail
    active_detail = []
    for r in active:
        cloud_info = ""
        if r.cloud_w1_color != "N/A":
            cloud_info += f" | Nuage W1: {r.cloud_w1_color}"
        if r.cloud_mn_color != "N/A":
            cloud_info += f" | MN: {r.cloud_mn_color}"

        detail = (
            f"**{r.symbol}** 🔺 BULL | Score: {r.score}/{r.max_score} | Align: {r.alignment}/5\n"
            f"> Kijun H4: {_fmt(r.kj_h4)} | SL: {_fmt(r.sl)} | TP: {_fmt(r.tp)} | RR: {r.rr:.1f}x\n"
            f"> Critères: {' '.join(r.criteria)}{cloud_info}"
        )

        # Warnings
        if r.warnings:
            detail += f"\n> ⚠️ {' | '.join(r.warnings[:3])}"
        if r.compression_zone:
            detail += f"\n> 🔒 {r.compression_zone[:100]}"
        if r.double_memory:
            detail += f"\n> 🔁 DOUBLE MÉMOIRE: Tenkan MN = Kijun MN {_fmt(r.kj_mn)}"

        active_detail.append(detail)

    if not active_detail:
        active_detail.append("Aucun setup actif détecté.")

    # Warnings section
    warned = [r for r in results if r.warnings]
    warn_lines = []
    for r in warned[:5]:
        warn_lines.append(f"**{r.symbol}**: {' | '.join(r.warnings[:2])}")
    if not warn_lines:
        warn_lines.append("Aucun avertissement.")

    color = COLOR_GREEN if n_strong + n_good > 0 else (COLOR_ORANGE if n_bull + n_bear > 0 else COLOR_BLUE)

    embed = {
        "title": f"💎 Diamond Analysis — {now_str}",
        "description": f"Scan Ichimoku multi-TF (H1→MN) sur {symbols_count} symboles\n{dxy_line}",
        "color": color,
        "fields": [
            {"name": "📊 Tous les symboles", "value": "\n".join(top_setups) or "—", "inline": False},
            {"name": "🎯 Setups actifs", "value": "\n\n".join(active_detail[:3]) or "—", "inline": False},
            {"name": "⚠️ Avertissements (Etape 3b)", "value": "\n".join(warn_lines[:8]) or "—", "inline": False},
            {"name": "📋 Résumé", "value": (
                f"🟢 **{n_strong}** STRONG | 🟡 **{n_good}** GOOD | ⚪ **{symbols_count - n_strong - n_good}** WAIT\n"
                f"🔺 **{n_bull}** BULL | 🔻 **{n_bear}** BEAR"
            ), "inline": False},
        ],
        "footer": {"text": "Inelida Diamond Scanner v2 — W1/MN inclus"},
    }
    return embed


def build_asian_embed(results, symbols_count: int) -> dict:
    """Build Discord embed for Asian scan results."""
    now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    trades = [r for r in results if r.trade_action != "-" and r.trade_rr1 and r.trade_rr1 > 0]
    n_trades = len(trades)
    n_rr1 = sum(1 for t in trades if t.trade_rr1 and t.trade_rr1 >= 1.0)

    top_trades = []
    for t in sorted(trades, key=lambda x: x.trade_rr1 or 0, reverse=True)[:5]:
        top_trades.append(
            f"**{t.symbol}** {t.trade_action} | RR {t.trade_rr1:.1f}x | "
            f"Spread {t.spread_pct:.3f}%\n"
            f"> Entry {_fmt(t.trade_entry)} → SL {_fmt(t.trade_sl)} → TP1 {_fmt(t.trade_tp1)}"
        )
    if not top_trades:
        top_trades.append("Aucun trade actif avec RR positif.")

    color = COLOR_GREEN if n_rr1 > 0 else COLOR_ORANGE

    embed = {
        "title": f"🌏 Asian Session Scan — {now_str}",
        "description": f"Scan Asian Range ICT sur {symbols_count} symboles | **{n_trades}** trades, **{n_rr1}** avec RR >= 1.0",
        "color": color,
        "fields": [
            {"name": "🏆 Top Trades (par RR)", "value": "\n".join(top_trades) or "—", "inline": False},
        ],
        "footer": {"text": "InelidaMarketScanner — Asian ICT"},
    }
    return embed


def main():
    parser = argparse.ArgumentParser(description="Scheduled Diamond + Asian scan with Discord notification")
    parser.add_argument("--no-discord", action="store_true", help="Skip Discord, console output only")
    parser.add_argument("--symbols", nargs="*", default=None, help="Symbols to scan (space-separated)")
    args = parser.parse_args()

    symbols = resolve_watchlist(args.symbols) if args.symbols else DEFAULT_SYMBOLS
    webhook_url = _load_webhook() if not args.no_discord else None

    print(f"[SCAN] Scheduled Diamond Scan — {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"   Symboles: {len(symbols)} — {' '.join(symbols)}")
    if webhook_url:
        print(f"   Discord: [OK] webhook configure")
    else:
        print(f"   Discord: [!] desactive (--no-discord ou pas de webhook)")

    # Run Diamond scan
    print(f"\n[Diamond] Diamond Analysis...")
    diamond_results = run_diamond_scan(symbols)
    print(f"   {len(diamond_results)} symboles scannés")

    # Run Asian scan
    print(f"\n[Asian] Asian ICT Scan...")
    asian_results = run_asian_scan(symbols)
    print(f"   {len(asian_results)} symboles scannés")

    # Console summary
    active_diamond = [r for r in diamond_results if r.bias != "FLAT" and r.quality != "WAIT"]
    trades_asian = [r for r in asian_results if r.trade_action != "-" and r.trade_rr1 and r.trade_rr1 >= 1.0]

    print(f"\n[Resume]")
    print(f"   Diamond: {len(active_diamond)} setup(s) actif(s) ({sum(1 for r in active_diamond if r.quality == 'STRONG')} STRONG, {sum(1 for r in active_diamond if r.quality == 'GOOD')} GOOD)")
    for r in active_diamond:
        print(f"     {r.symbol}: {r.bias} Score {r.score}/{r.max_score} Align {r.alignment}/5 RR {r.rr:.1f}x {'[WARN]' if r.warnings else ''}")
    print(f"   Asian:   {len(trades_asian)} trade(s) avec RR >= 1.0")
    for t in trades_asian[:5]:
        print(f"     {t.symbol}: {t.trade_action} RR {t.trade_rr1:.1f}x")

    # Send to Discord
    if webhook_url:
        diamond_embed = build_diamond_embed(diamond_results, len(symbols))
        asian_embed = build_asian_embed(asian_results, len(symbols))
        ok = send_discord_webhook(webhook_url, [diamond_embed, asian_embed])
        print(f"\n[Discord] {'OK envoye' if ok else 'ECHEC'}")
    else:
        print(f"\n[Discord] saute (--no-discord)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
