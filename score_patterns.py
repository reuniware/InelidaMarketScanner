"""
ICT Pattern Quality Scorer - Scan tous les actifs et classe les setups
par proprete du pattern ICT (Asian session).
"""

import sys
import time
from datetime import datetime, timezone, timedelta

# Forcer l'encodage UTF-8 sur stdout
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, "C:/Users/TSTAC/RustProjects/InelidaMarketScan")
from src.sweep_detector import scan_market_watch_asian_ranges
from src.mt5_connector import MT5Connector

UTC = timezone.utc
PLATFORM_OFFSET = 2  # UTC+2
NOW = datetime.now(UTC)


def score_pattern(r):
    """Score un AsianRangeResult sur la qualite du pattern ICT.
    Score max = 10. Plus c'est haut, plus le pattern est propre.
    """
    score = 0

    # 1. Sweep detecte (max 2 pts)
    if r.asian_high_swept:
        score += 1
    if r.asian_low_swept:
        score += 1

    # 2. Direction target claire (->AH ou ->AL, pas . ni - ni Both) (max 2 pts)
    dr = r.direction_target_label or ""
    if r.direction_target == "AH" and "->" in dr and "AH" in dr:
        score += 2
    elif r.direction_target == "AL" and "->" in dr and "AL" in dr:
        score += 2
    elif r.direction_target == "BOTH":
        score += 1

    # 3. Fib state actif (expansion en cours) (max 2 pts)
    if r.fib_state and r.fib_state != "" and "_DONE" not in r.fib_state:
        score += 2
    elif r.fib_state and "_DONE" in r.fib_state:
        score += 1

    # 4. Trade genere (max 2 pts)
    if r.trade_action in ("BUY", "SELL") and r.trade_status == "Active":
        score += 1
        if r.trade_rr1 and r.trade_rr1 >= 1.0:
            score += 1

    # 5. Prix hors range (cassure confirmee) (max 2 pts)
    if r.current_price and r.asian_high and r.asian_low:
        midpoint = (r.asian_high + r.asian_low) / 2
        range_size = r.asian_high - r.asian_low
        if range_size > 0:
            if r.current_price > r.asian_high:
                score += 2
            elif r.current_price < r.asian_low:
                score += 2
            elif r.current_price > midpoint and r.low_swept_at:
                score += 1
            elif r.current_price < midpoint and r.high_swept_at:
                score += 1

    # 6. Breach sans sweep = penalite legere
    if (r.asian_high_breached and not r.asian_high_swept) or \
       (r.asian_low_breached and not r.asian_low_swept):
        score -= 1

    return max(0, score)


def describe_pattern(r):
    """Description textuelle du pattern ICT."""
    parts = []

    sweeps = []
    if r.asian_high_swept:
        sweeps.append("AH SWEPT (%s)" % (r.high_swept_session_label or '?'))
    elif r.asian_high_breached:
        sweeps.append("AH BREACH (%s)" % (r.high_swept_session_label or '?'))
    if r.asian_low_swept:
        sweeps.append("AL SWEPT (%s)" % (r.low_swept_session_label or '?'))
    elif r.asian_low_breached:
        sweeps.append("AL BREACH (%s)" % (r.low_swept_session_label or '?'))
    if sweeps:
        parts.append(" | ".join(sweeps))
    else:
        parts.append("No sweep")

    parts.append("Target: %s" % r.direction_target_label)

    if r.fib_label and r.fib_label != "\u2014":
        parts.append("Fib: %s" % r.fib_label)

    if r.trade_action in ("BUY", "SELL"):
        rr_str = " (RR %.1fx)" % r.trade_rr1 if r.trade_rr1 else ""
        parts.append("Trade: %s%s" % (r.trade_action, rr_str))

    if r.current_price and r.asian_high and r.asian_low:
        midpoint = (r.asian_high + r.asian_low) / 2
        if r.current_price > r.asian_high:
            parts.append("Price > AH (bull breakout)")
        elif r.current_price < r.asian_low:
            parts.append("Price < AL (bear breakout)")
        elif r.current_price > midpoint:
            parts.append("Price > midpoint")
        else:
            parts.append("Price < midpoint")

    return " | ".join(parts)


def asian_time_to_platform(epoch):
    """Convertit un epoch UTC en heure plateforme (UTC+2)."""
    if epoch is None:
        return "--"
    return datetime.fromtimestamp(epoch, UTC).strftime("%H:%M") + " plateforme"


def main():
    print("")
    print("=" * 90)
    print("  ICT PATTERN QUALITY SCAN - TOUS LES ACTIFS")
    print("  Heure plateforme : %s (UTC+%d)" % (NOW.strftime('%Y-%m-%d %H:%M'), PLATFORM_OFFSET))
    print("=" * 90)
    print("")

    mt5c = MT5Connector()
    if not mt5c.ensure_connected():
        print("[ERREUR] Connexion MT5 impossible.")
        return 1

    all_symbols = mt5c.list_all_symbols()
    print("Scan de %d symboles..." % len(all_symbols))
    print("")

    results, scanned = scan_market_watch_asian_ranges(
        timeframe="H1",
        symbols_override=all_symbols,
    )

    print("Resultats : %d ranges asiatiques calculees sur %d symboles." % (len(results), len(scanned)))
    print("")

    scored = []
    for r in results:
        s = score_pattern(r)
        if s >= 3:
            scored.append((s, r))

    scored.sort(key=lambda x: x[0], reverse=True)

    if not scored:
        print("[INFO] Aucun pattern ICT propre detecte (score >= 3).")
        return 0

    print("=" * 90)
    print("  TOP SETUPS ICT (tries par proprete du pattern)")
    print("=" * 90)
    print("")

    for rank, (score, r) in enumerate(scored[:25], 1):
        stars = "[%d]" % score

        print("  %2d. %s  %-14s  Score: %d/10" % (rank, stars, r.symbol, score))
        print("      AH=%.5f  AL=%.5f  Range=%.5f" % (r.asian_high, r.asian_low, r.asian_high - r.asian_low))
        print("      Now=%.5f  |  %s" % (r.current_price, describe_pattern(r)))

        if r.high_swept_at:
            print("      AH sweepe a %s - session %s" % (asian_time_to_platform(r.high_swept_at), r.high_swept_session_label))
        if r.low_swept_at:
            print("      AL sweepe a %s - session %s" % (asian_time_to_platform(r.low_swept_at), r.low_swept_session_label))

        if r.trade_action in ("BUY", "SELL") and r.trade_status == "Active":
            rr_part = " RR=%.1fx" % r.trade_rr1 if r.trade_rr1 else ""
            print("      >>> TRADE: %s | Entry=%.5f | SL=%.5f | TP1=%.5f%s" % (
                r.trade_action, r.trade_entry, r.trade_sl, r.trade_tp1, rr_part))
        print("")

    print("=" * 90)
    print("  RESUME")
    print("=" * 90)

    n_active = sum(1 for s, r in scored if r.trade_status == "Active")
    n_buy = sum(1 for s, r in scored if r.trade_action == "BUY" and r.trade_status == "Active")
    n_sell = sum(1 for s, r in scored if r.trade_action == "SELL" and r.trade_status == "Active")
    n_rr_ok = sum(1 for s, r in scored if r.trade_rr1 and r.trade_rr1 >= 1.0 and r.trade_status == "Active")
    n_ah_swept = sum(1 for s, r in scored if r.asian_high_swept)
    n_al_swept = sum(1 for s, r in scored if r.asian_low_swept)
    n_both = sum(1 for s, r in scored if r.asian_high_swept and r.asian_low_swept)

    print("  Setups analyses (score >= 3)  : %d" % len(scored))
    print("  Trades actifs                  : %d (%d BUY, %d SELL)" % (n_active, n_buy, n_sell))
    print("  Dont RR >= 1.0                : %d" % n_rr_ok)
    print("  AH sweepes                     : %d" % n_ah_swept)
    print("  AL sweepes                     : %d" % n_al_swept)
    print("  Les deux sweepes               : %d" % n_both)

    print("")
    print("  [PODIUM ICT] :")
    for rank, (score, r) in enumerate(scored[:3], 1):
        action_str = ""
        if r.trade_action in ("BUY", "SELL") and r.trade_rr1:
            action_str = " -> %s RR %.1fx" % (r.trade_action, r.trade_rr1)
        elif r.trade_action in ("BUY", "SELL"):
            action_str = " -> %s" % r.trade_action
        print("     %d. %s (score %d/10)%s" % (rank, r.symbol, score, action_str))

    return 0


if __name__ == "__main__":
    sys.exit(main())
