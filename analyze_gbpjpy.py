"""
GBPJPY Session Analyzer — Anatomie ICT des sessions Asian / London / NY.
Recupere les bougies H1 et M15 depuis MT5, partitionne par session UTC,
et produit une analyse narrative complete.
"""
import os, sys, time, json
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple

import MetaTrader5 as mt5

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.logger_config import setup_logging

logger = setup_logging("gbpjpy_analyzer", level="WARNING")

SYMBOL = "GBPJPY"
TIMEFRAMES = {
    "M15": mt5.TIMEFRAME_M15,
    "H1": mt5.TIMEFRAME_H1,
}

UTC = timezone.utc
NOW_UTC = datetime.now(UTC)
TODAY = NOW_UTC.strftime("%Y-%m-%d")
YESTERDAY = (NOW_UTC - timedelta(days=1)).strftime("%Y-%m-%d")
TWO_DAYS_AGO = (NOW_UTC - timedelta(days=2)).strftime("%Y-%m-%d")

SESSION_DEFS = {
    "Asian":      (0, 8),
    "London":     (8, 13),
    "NY_AM":      (13, 17),
    "NY_PM":      (17, 21),
    "Asian_pre":  (22, 24),
}


def init_mt5():
    if not mt5.initialize():
        print(f"[ERREUR] MT5 initialize failed: {mt5.last_error()}")
        return False
    return True


def get_bars(tf_name: str, count: int = 400) -> list:
    tf = TIMEFRAMES.get(tf_name)
    if tf is None:
        return []
    rates = mt5.copy_rates_from_pos(SYMBOL, tf, 0, count)
    if rates is None or len(rates) == 0:
        return []
    bars = []
    for r in rates:
        bars.append({
            "time": int(r[0]),
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
            "tick_vol": int(r[5]),
        })
    return bars


def session_for_bar(bar, day_str=None):
    """Retourne (session_key, session_label, day) pour une barre."""
    t = bar["time"]
    dt = datetime.fromtimestamp(t, UTC)
    h = dt.hour
    d = dt.strftime("%Y-%m-%d")
    for key, (start, end) in SESSION_DEFS.items():
        if start <= h < end:
            return key, key, d
    return "Off", "Off", d


def compute_asian_range(bars, day_str):
    """Calcule AH/AL pour un jour donne."""
    asian_bars = []
    for b in bars:
        dt = datetime.fromtimestamp(b["time"], UTC)
        d = dt.strftime("%Y-%m-%d")
        h = dt.hour
        if d == day_str and 0 <= h < 8:
            asian_bars.append(b)
    if not asian_bars:
        return None, None, None, None
    ah = max(b["high"] for b in asian_bars)
    al = min(b["low"] for b in asian_bars)
    first_t = min(b["time"] for b in asian_bars)
    last_t = max(b["time"] for b in asian_bars)
    return ah, al, first_t, last_t


def detect_sweeps(bars, level_high, level_low):
    """Detecte sweeps ICT et breaches sur une liste de barres."""
    high_swept = False; high_breached = False
    low_swept = False; low_breached = False
    high_swept_bar = None; low_swept_bar = None
    high_breach_bar = None; low_breach_bar = None

    for b in bars:
        # Sweep classique (meche traverse + close rejette)
        if not high_swept and b["high"] > level_high and b["close"] < level_high:
            high_swept = True
            high_swept_bar = b
        if not low_swept and b["low"] < level_low and b["close"] > level_low:
            low_swept = True
            low_swept_bar = b
        # Breach (meche traverse seulement)
        if not high_breached and b["high"] > level_high:
            high_breached = True
            high_breach_bar = b
        if not low_breached and b["low"] < level_low:
            low_breached = True
            low_breach_bar = b
        if high_swept and low_swept and high_breached and low_breached:
            break

    return {
        "high_swept": high_swept, "low_swept": low_swept,
        "high_breached": high_breached, "low_breached": low_breached,
        "high_swept_bar": high_swept_bar, "low_swept_bar": low_swept_bar,
        "high_breach_bar": high_breach_bar, "low_breach_bar": low_breach_bar,
    }


def partition_bars_by_session(bars, day_str=None):
    """Groupe les barres par session pour un jour."""
    sessions = {k: [] for k in SESSION_DEFS}
    sessions["Off"] = []
    for b in bars:
        dt = datetime.fromtimestamp(b["time"], UTC)
        d = dt.strftime("%Y-%m-%d")
        if day_str and d != day_str:
            continue
        h = dt.hour
        placed = False
        for key, (start, end) in SESSION_DEFS.items():
            if start <= h < end:
                sessions[key].append(b)
                placed = True
                break
        if not placed:
            sessions["Off"].append(b)
    return sessions


def session_summary(bars, label):
    """Resume d'une session : O/H/L/C, range, direction."""
    if not bars:
        return {"label": label, "bars": 0, "open": None, "high": None, "low": None,
                "close": None, "range": None, "direction": "-"}
    o = bars[0]["open"]
    c = bars[-1]["close"]
    h = max(b["high"] for b in bars)
    l = min(b["low"] for b in bars)
    rng = h - l
    direction = "HAUSSIER" if c > o else "BAISSIER" if c < o else "NEUTRE"
    return {"label": label, "bars": len(bars), "open": o, "high": h, "low": l,
            "close": c, "range": rng, "direction": direction,
            "first": bars[0]["time"], "last": bars[-1]["time"]}


def fmt_ts(epoch):
    if epoch is None: return "-"
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%d %H:%M UTC")


def fmt_price(p):
    if p is None: return "-"
    return f"{p:.3f}"


# ===========================================================================
# MAIN
# ===========================================================================
def main():
    print(f"\n{'='*80}")
    print(f"  GBPJPY — ANALYSE ICT PAR SESSION")
    print(f"  Date UTC : {TODAY} | Heure actuelle : {NOW_UTC.strftime('%H:%M UTC')}")
    print(f"{'='*80}\n")

    if not init_mt5():
        return 1

    # Tick actuel
    tick = mt5.symbol_info_tick(SYMBOL)
    current_price = float(tick.bid) if tick else None
    print(f"  Prix actuel GBPJPY : {current_price if current_price else 'N/A'}")

    # Recuperer H1 (14 jours) et M15 (3 jours)
    print(f"\n  Chargement des donnees...")
    h1_bars = get_bars("H1", 400)
    m15_bars = get_bars("M15", 400)

    if not h1_bars:
        print("[ERREUR] Pas de donnees H1 pour GBPJPY.")
        return 2

    print(f"  H1 : {len(h1_bars)} barres chargees (derniere: {fmt_ts(h1_bars[-1]['time'])})")
    if m15_bars:
        print(f"  M15: {len(m15_bars)} barres chargees (derniere: {fmt_ts(m15_bars[-1]['time'])})")

    # ===================================================================
    # ANALYSE JOURNALIERE
    # ===================================================================
    for day_offset in [2, 1, 0]:
        day_str = (NOW_UTC - timedelta(days=day_offset)).strftime("%Y-%m-%d")
        day_label = "AUJOURD'HUI" if day_offset == 0 else ("HIER" if day_offset == 1 else "AVANT-HIER")

        # Asian range
        ah, al, first_asian, last_asian = compute_asian_range(h1_bars, day_str)
        if ah is None:
            print(f"\n  [{day_label} {day_str}] Pas de range asiatique (marche ferme ?)")
            continue

        asian_range = ah - al
        midpoint = (ah + al) / 2

        # Barres post-Asian (H1)
        post_bars_h1 = [b for b in h1_bars if b["time"] > last_asian and
                        datetime.fromtimestamp(b["time"], UTC).strftime("%Y-%m-%d") >= day_str]
        post_bars_m15 = [b for b in m15_bars if b["time"] > last_asian and
                         datetime.fromtimestamp(b["time"], UTC).strftime("%Y-%m-%d") >= day_str] if m15_bars else []

        # Sweeps
        sweeps = detect_sweeps(post_bars_h1, ah, al)

        # Sessions
        sessions = partition_bars_by_session(h1_bars, day_str)
        session_summaries = {k: session_summary(v, k) for k, v in sessions.items()}

        # Direction target
        direction = "-"
        direction_label = "-"
        if sweeps["high_swept"] and sweeps["low_swept"]:
            direction = "BOTH"
            direction_label = "<-> Both (range cassee des deux cotes)"
        elif sweeps["high_swept"]:
            direction = "AL"
            if current_price and current_price < midpoint:
                direction_label = f"-> AL (BAISSIER confirme, prix={current_price:.3f} < midpoint={midpoint:.3f})"
            else:
                direction_label = f"-> AL (en attente, prix au-dessus du midpoint)"
        elif sweeps["low_swept"]:
            direction = "AH"
            if current_price and current_price > midpoint:
                direction_label = f"-> AH (HAUSSIER confirme, prix={current_price:.3f} > midpoint={midpoint:.3f})"
            else:
                direction_label = f"-> AH (en attente, prix sous le midpoint)"
        else:
            direction_label = "Aucun sweep -> pas de signal directionnel"

        # Fib
        fib_1618_plus = ah + 1.618 * asian_range
        fib_1618_minus = al - 1.618 * asian_range
        fib_2618_plus = ah + 2.618 * asian_range
        fib_2618_minus = al - 2.618 * asian_range

        # Trade idea
        trade_action = "-"
        trade_entry = current_price
        trade_sl = None
        trade_tp1 = None
        trade_rr = None

        if sweeps["high_swept"] and current_price and current_price < al:
            trade_action = "SELL"
            trade_sl = ah + 0.10 * asian_range
            trade_tp1 = al - 1.618 * asian_range
            if trade_sl - trade_entry > 0:
                trade_rr = (trade_entry - trade_tp1) / (trade_sl - trade_entry)
        elif sweeps["low_swept"] and current_price and current_price > ah:
            trade_action = "BUY"
            trade_sl = al - 0.10 * asian_range
            trade_tp1 = ah + 1.618 * asian_range
            if trade_entry - trade_sl > 0:
                trade_rr = (trade_tp1 - trade_entry) / (trade_entry - trade_sl)

        # ── AFFICHAGE ────────────────────────────────────────────────────
        print(f"\n  {'='*70}")
        print(f"  [{day_label}] {day_str}")
        print(f"  {'='*70}")

        print(f"\n  > RANGE ASIATIQUE (UTC 00:00-08:00)")
        print(f"    Asian High : {fmt_price(ah)}")
        print(f"    Asian Low  : {fmt_price(al)}")
        print(f"    Range      : {asian_range:.3f} pips")
        print(f"    Midpoint   : {midpoint:.3f}")
        print(f"    Bougies    : {fmt_ts(first_asian)} -> {fmt_ts(last_asian)}")

        print(f"\n  > SWEEPS / BREACHS POST-ASIAN")
        print(f"    AH Sweep   : {'OUI' if sweeps['high_swept'] else 'NON'}  "
              f"{'(barre ' + fmt_ts(sweeps['high_swept_bar']['time']) + ')' if sweeps['high_swept_bar'] else ''}")
        print(f"    AL Sweep   : {'OUI' if sweeps['low_swept'] else 'NON'}  "
              f"{'(barre ' + fmt_ts(sweeps['low_swept_bar']['time']) + ')' if sweeps['low_swept_bar'] else ''}")
        print(f"    AH Breach  : {'OUI' if sweeps['high_breached'] else 'NON'}  "
              f"{'(barre ' + fmt_ts(sweeps['high_breach_bar']['time']) + ')' if sweeps['high_breach_bar'] else ''}")
        print(f"    AL Breach  : {'OUI' if sweeps['low_breached'] else 'NON'}  "
              f"{'(barre ' + fmt_ts(sweeps['low_breach_bar']['time']) + ')' if sweeps['low_breach_bar'] else ''}")

        print(f"\n  > DIRECTION ICT")
        print(f"    {direction_label}")

        print(f"\n  > FIBONACCI EXTENSIONS")
        print(f"    +1.618 : {fmt_price(fib_1618_plus)}")
        print(f"    +2.618 : {fmt_price(fib_2618_plus)}")
        print(f"    -1.618 : {fmt_price(fib_1618_minus)}")
        print(f"    -2.618 : {fmt_price(fib_2618_minus)}")

        if trade_action != "-":
            print(f"\n  > TRADE IDEA")
            print(f"    Action : {trade_action}")
            print(f"    Entry  : {fmt_price(trade_entry)}")
            print(f"    SL     : {fmt_price(trade_sl)}")
            print(f"    TP1    : {fmt_price(trade_tp1)}")
            print(f"    RR     : {trade_rr:.2f}x" if trade_rr else "    RR     : -")

        print(f"\n  > SESSIONS H1 (Open->Close, Direction, Range)")
        for sk in ["Asian", "London", "NY_AM", "NY_PM", "Asian_pre"]:
            s = session_summaries.get(sk)
            if s and s["bars"] > 0:
                print(f"    {s['label']:<10} : O={fmt_price(s['open'])} C={fmt_price(s['close'])}  "
                      f"Range={s['range']:.3f}  Dir={s['direction']}  ({s['bars']} barres)")
            elif sk == "Asian":
                pass  # deja affiche
            else:
                print(f"    {sk:<10} : (pas encore commence ou pas de barres)")

    # ===================================================================
    # ANALYSE M15 GRANULAIRE (AUJOURD'HUI SEULEMENT)
    # ===================================================================
    if m15_bars:
        print(f"\n\n{'='*80}")
        print(f"  ANALYSE GRANULAIRE M15 — AUJOURD'HUI ({TODAY})")
        print(f"{'='*80}")

        today_m15 = [b for b in m15_bars
                     if datetime.fromtimestamp(b["time"], UTC).strftime("%Y-%m-%d") == TODAY]
        today_m15.sort(key=lambda x: x["time"])

        if today_m15:
            # Sequence de prix M15
            print(f"\n  Sequence M15 (dernieres 30 barres) :")
            recent = today_m15[-30:]
            for b in recent:
                dt = datetime.fromtimestamp(b["time"], UTC)
                direction = "GREEN" if b["close"] > b["open"] else "RED" if b["close"] < b["open"] else "DOJI"
                wick_high = b["high"] - max(b["open"], b["close"])
                wick_low = min(b["open"], b["close"]) - b["low"]
                body = abs(b["close"] - b["open"])
                print(f"    {dt.strftime('%H:%M')} | O={b['open']:.3f} H={b['high']:.3f} "
                      f"L={b['low']:.3f} C={b['close']:.3f} | {direction} "
                      f"body={body:.3f} wick_up={wick_high:.3f} wick_down={wick_low:.3f}")

            # Sweeps M15 sur les 3 derniers jours
            print(f"\n  Detection sweeps M15 (3 jours, barres recentes) :")
            recent_global = m15_bars[-96:]  # ~24h en M15
            if recent_global:
                highs = [b["high"] for b in recent_global]
                lows = [b["low"] for b in recent_global]
                max_h = max(highs)
                min_l = min(lows)
                # Fractal Williams simplifie (N=2)
                swings_high = []
                swings_low = []
                n = 2
                for i in range(n, len(recent_global) - n):
                    h = highs[i]
                    if all(h > highs[j] for j in range(i - n, i + n + 1) if j != i):
                        swings_high.append({"index": i, "level": h, "time": recent_global[i]["time"]})
                    l = lows[i]
                    if all(l < lows[j] for j in range(i - n, i + n + 1) if j != i):
                        swings_low.append({"index": i, "level": l, "time": recent_global[i]["time"]})

                # Chercher les sweeps recents
                last_bars = recent_global[-5:]
                swept_swings = []
                for sw in swings_high + swings_low:
                    for b in last_bars:
                        is_high = sw in swings_high
                        if is_high and b["high"] > sw["level"] and b["close"] < sw["level"]:
                            swept_swings.append({
                                "type": "BSL (high swept)",
                                "level": sw["level"],
                                "swept_by": fmt_ts(b["time"]),
                                "direction": "reversal_down"
                            })
                            break
                        if not is_high and b["low"] < sw["level"] and b["close"] > sw["level"]:
                            swept_swings.append({
                                "type": "SSL (low swept)",
                                "level": sw["level"],
                                "swept_by": fmt_ts(b["time"]),
                                "direction": "reversal_up"
                            })
                            break

                if swept_swings:
                    for ss in swept_swings:
                        print(f"    {ss['type']} @ {ss['level']:.3f} | swept a {ss['swept_by']} | {ss['direction']}")
                else:
                    print(f"    Aucun sweep recent detecte en M15.")

    # ===================================================================
    # RESUME DE TRADING
    # ===================================================================
    print(f"\n\n{'='*80}")
    print(f"  RESUME TRADING GBPJPY")
    print(f"{'='*80}")

    ah_today, al_today, _, _ = compute_asian_range(h1_bars, TODAY)
    if ah_today and al_today:
        asian_range_today = ah_today - al_today
        midpoint_today = (ah_today + al_today) / 2
        post_today = [b for b in h1_bars if b["time"] > (
            max(b["time"] for b in h1_bars
                if datetime.fromtimestamp(b["time"], UTC).strftime("%Y-%m-%d") == TODAY
                and 0 <= datetime.fromtimestamp(b["time"], UTC).hour < 8)
            if any(datetime.fromtimestamp(b["time"], UTC).strftime("%Y-%m-%d") == TODAY
                   and 0 <= datetime.fromtimestamp(b["time"], UTC).hour < 8 for b in h1_bars)
            else 0
        )]
        sweeps_today = detect_sweeps(post_today, ah_today, al_today)

        print(f"  Session asiatique aujourd'hui :")
        print(f"    AH={ah_today:.3f}  AL={al_today:.3f}  Range={asian_range_today:.3f}  Mid={midpoint_today:.3f}")
        print(f"    AH swept : {'OUI' if sweeps_today['high_swept'] else 'NON'}")
        print(f"    AL swept : {'OUI' if sweeps_today['low_swept'] else 'NON'}")
        print(f"    Prix actuel : {current_price:.3f}" if current_price else "")

        if sweeps_today["high_swept"] and current_price and current_price < al_today:
            print(f"\n  [SIGNAL] SELL — AH sweepe + prix sous AL -> continuation baissiere")
        elif sweeps_today["low_swept"] and current_price and current_price > ah_today:
            print(f"\n  [SIGNAL] BUY — AL sweepe + prix au-dessus AH -> continuation haussiere")
        elif sweeps_today["high_swept"] or sweeps_today["low_swept"]:
            print(f"\n  [ATTENTE] Sweep detecte mais breakout pas encore confirme")
        else:
            print(f"\n  [NEUTRE] Aucun sweep de la range asiatique aujourd'hui")
    else:
        print(f"  Pas encore de range asiatique pour aujourd'hui.")

    mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
