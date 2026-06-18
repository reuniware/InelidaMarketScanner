"""
InelidaMarketScanner - LIVE SWEEP DETECTOR (NO TRADE)
=====================================================
Surveille les symboles en temps reel, detecte les sweeps ICT
des qu'ils se produisent, et alerte avec un trade potentiel explicatif.

3 TYPES DE DETECTION :
  1. Asian Sweeps    : meche traverse AH/AL + close rejette (range asiatique)
  2. Fractal Sweeps  : Williams fractals N=2, BSL/SSL sur swing points M15
  3. Daily/Weekly    : PDH/PDL (Previous Day High/Low) + PWH/PWL (Previous Week High/Low)

NE TRADE JAMAIS. Aucun ordre n'est envoye au broker.
Alerte par ecran + son + log fichier.
"""

import os
import sys
import time
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set, Tuple

import MetaTrader5 as mt5

# ─── Configuration ──────────────────────────────────────────────────────────
WATCHLIST = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD",
    "XAUUSD", "XAGUSD", "BTCUSD", "ETHUSD",
    "US30", "NAS100", "SPX500",
    "GBPJPY", "EURJPY", "EURGBP", "AUDJPY", "NZDJPY", "CADJPY", "CHFJPY",
    "EURCAD", "GBPCAD", "AUDCAD", "NZDCAD",
    "EURCHF", "GBPCHF", "AUDCHF", "CADCHF",
    "EURAUD", "GBPAUD", "EURNZD", "GBPNZD",
    "USOIL.cash", "UKOIL.cash", "NATGAS.cash",
    "DXY.cash", "AUS200.cash", "US30.cash",
]

_env = os.environ.get("INELIDA_LIVE_WATCHLIST")
if _env:
    WATCHLIST = [s.strip().upper() for s in _env.split(",") if s.strip()]

POLL_INTERVAL_SEC = 30
LOOKBACK_BARS_M1 = 60
ASIAN_START_UTC = 0
ASIAN_END_UTC = 8
FRACTAL_N = 2              # Williams fractal N
FRACTAL_LOOKBACK = 50      # Bougies M15 pour les swings
FRACTAL_SENSITIVITY = 5    # Dernieres N bougies testees pour sweeps

# Daily/Weekly levels
DAILY_WEEKLY_CHECK_INTERVAL = 120  # secondes entre chaque recalcule des niveaux
DW_SCAN_TF = "H1"                  # timeframe de scan pour sweeps daily/weekly
DW_LOOKBACK = 48                   # bougies H1 a scanner

UTC = timezone.utc
PLATFORM_OFFSET = 2
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "live_sweeps.log")

# ─── ANSI ───────────────────────────────────────────────────────────────────
_IS_TTY = sys.stdout.isatty()
def _c(code): return code if _IS_TTY else ""
BOLD = _c("\033[1m"); RED = _c("\033[31m"); GREEN = _c("\033[32m")
YELLOW = _c("\033[33m"); CYAN = _c("\033[36m"); MAGENTA = _c("\033[35m")
WHITE = _c("\033[97m"); BG_RED = _c("\033[41m"); BG_GREEN = _c("\033[42m")
BG_YELLOW = _c("\033[43m"); RESET = _c("\033[0m"); BELL = "\a"


def _fmt(p):
    if p is None: return "--"
    if p >= 1000: return f"{p:.2f}"
    if p >= 10: return f"{p:.4f}"
    return f"{p:.5f}"


def _pt(epoch=None):
    if epoch is None: epoch = time.time()
    return datetime.fromtimestamp(epoch, UTC).strftime("%H:%M") + " plateforme"


def _pdt(epoch=None):
    if epoch is None: epoch = time.time()
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%d %H:%M") + " plateforme"


def _session():
    h = (datetime.now(UTC).hour + PLATFORM_OFFSET) % 24
    if 2 <= h < 10: return "ASIAN"
    if 10 <= h < 15: return "LONDON"
    if 15 <= h < 19: return "NY AM"
    if 19 <= h < 23: return "NY PM"
    return "ASIAN PRE"


def _log(symbol, sweep_type, level, price, trade_idea, sweep_source="asian"):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts_utc": datetime.now(UTC).isoformat(),
            "ts_platform": _pdt(),
            "symbol": symbol, "sweep_type": sweep_type, "level": level,
            "current_price": price, "session": _session(),
            "source": sweep_source, "trade": trade_idea,
        }, ensure_ascii=False) + "\n")


def _asian_alert(symbol, sweep_type, level, price, ah, al, trade):
    print(BELL)
    bar = "=" * 72
    print(f"\n{BG_RED}{WHITE}{BOLD}{bar}{RESET}")
    print(f"{BG_RED}{WHITE}{BOLD}  !!! ASIAN {sweep_type} SWEEP !!!  {_pdt()}  |  {_session()}{RESET}")
    print(f"{BG_RED}{WHITE}{BOLD}{bar}{RESET}")
    color = RED if sweep_type == "BSL" else GREEN
    print(f"\n  {BOLD}{color}>>> {sweep_type} sur {symbol} (Asian {level}) <<<{RESET}")
    print(f"  Niveau sweepe  : {_fmt(level)}")
    print(f"  Prix actuel    : {_fmt(price)}")
    print(f"  Range asiatique: AH={_fmt(ah)} AL={_fmt(al)} Range={_fmt(ah - al)} Mid={_fmt((ah + al) / 2)}")
    _print_trade(trade)
    print(f"\n{BG_RED}{WHITE}{BOLD}{bar}{RESET}\n")
    sys.stdout.flush()


def _fractal_alert(symbol, sweep_type, level, price, dist_pct, swept_at):
    print(BELL)
    bar = "=" * 72
    print(f"\n{BG_YELLOW}{WHITE}{BOLD}{bar}{RESET}")
    print(f"{BG_YELLOW}{WHITE}{BOLD}  !!! FRACTAL {sweep_type} SWEEP !!!  {_pdt()}  |  {_session()}{RESET}")
    print(f"{BG_YELLOW}{WHITE}{BOLD}{bar}{RESET}")
    color = RED if sweep_type == "BSL" else GREEN
    print(f"\n  {BOLD}{color}>>> {sweep_type} sur {symbol} (Fractal Williams N={FRACTAL_N}) <<<{RESET}")
    print(f"  Niveau sweepe  : {_fmt(level)}")
    print(f"  Prix actuel    : {_fmt(price)}")
    print(f"  Distance       : {dist_pct:.3f}%")
    print(f"  Sweepe a       : {_pdt(swept_at)}")
    dir_label = "REVERSAL DOWN (baissier attendu)" if sweep_type == "BSL" else "REVERSAL UP (haussier attendu)"
    print(f"  Direction ICT  : {dir_label}")
    print(f"{BG_YELLOW}{WHITE}{BOLD}{bar}{RESET}\n")
    sys.stdout.flush()


def _print_trade(trade):
    if trade.get("action") and trade["action"] != "-":
        action_color = RED if trade["action"] == "SELL" else GREEN
        print(f"\n  {BOLD}{action_color}[TRADE POTENTIEL] {trade['action']}{RESET}")
        print(f"  Entry   : {_fmt(trade['entry'])}")
        print(f"  SL      : {_fmt(trade['sl'])}")
        print(f"  TP1     : {_fmt(trade['tp1'])}")
        if trade.get("tp2"): print(f"  TP2     : {_fmt(trade['tp2'])}")
        if trade.get("rr"): print(f"  RR      : {trade['rr']:.1f}x")
        print(f"  Explication : {trade['explanation']}")
    else:
        print(f"\n  {YELLOW}[INFO] Sweep detecte mais trade pas encore confirmable{RESET}")
        print(f"  Raison : {trade.get('explanation', '')}")


# ═══════════════════════════════════════════════════════════════════════════════
# DETECTION FRACTALES WILLIAMS (BSL/SSL classiques)
# ═══════════════════════════════════════════════════════════════════════════════

def _detect_swing_points(bars, fractal_n):
    """Williams fractal standard: swing haut = bar[i].high > toutes les highs
    dans [i-N, i+N]; swing bas = bar[i].low < toutes les lows dans [i-N, i+N]."""
    if len(bars) < 2 * fractal_n + 1:
        return [], []
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    swings_high, swings_low = [], []
    for i in range(fractal_n, len(bars) - fractal_n):
        h = highs[i]
        if all(h > highs[j] for j in range(i - fractal_n, i + fractal_n + 1) if j != i):
            swings_high.append({"level": h, "time": bars[i]["time"], "index": i})
        l = lows[i]
        if all(l < lows[j] for j in range(i - fractal_n, i + fractal_n + 1) if j != i):
            swings_low.append({"level": l, "time": bars[i]["time"], "index": i})
    return swings_high, swings_low


def _check_fractal_sweeps_for_symbol(symbol, detected_fractal_set):
    """Verifie les sweeps BSL/SSL par fractales Williams sur M15.
    Retourne la liste des nouveaux sweeps detectes."""
    tf = mt5.TIMEFRAME_M15
    total_bars = FRACTAL_LOOKBACK + FRACTAL_SENSITIVITY + 2 * FRACTAL_N + 5
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, total_bars)
    if rates is None or len(rates) < total_bars:
        return []

    bars = []
    for r in rates:
        bars.append({"time": int(r[0]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4])})

    if len(bars) < FRACTAL_LOOKBACK + FRACTAL_SENSITIVITY + 2 * FRACTAL_N:
        return []

    swings_high, swings_low = _detect_swing_points(bars, FRACTAL_N)
    recent_window = bars[-FRACTAL_SENSITIVITY:]

    tick = mt5.symbol_info_tick(symbol)
    current_price = float(tick.bid) if tick else bars[-1]["close"]

    found = []
    for sw in swings_high:
        key = f"FRACTAL_{symbol}_BSL_{sw['level']:.5f}"
        if key in detected_fractal_set:
            continue
        age = (len(bars) - 1) - sw["index"]
        if age > FRACTAL_LOOKBACK or age < 1:
            continue
        for bar in recent_window:
            if bar["high"] > sw["level"] and bar["close"] < sw["level"]:
                detected_fractal_set.add(key)
                dist = abs((current_price - sw["level"]) / sw["level"] * 100.0)
                found.append({"type": "BSL", "level": sw["level"], "price": current_price,
                              "dist_pct": dist, "swept_at": bar["time"],
                              "key": key, "source": "fractal"})
                break

    for sw in swings_low:
        key = f"FRACTAL_{symbol}_SSL_{sw['level']:.5f}"
        if key in detected_fractal_set:
            continue
        age = (len(bars) - 1) - sw["index"]
        if age > FRACTAL_LOOKBACK or age < 1:
            continue
        for bar in recent_window:
            if bar["low"] < sw["level"] and bar["close"] > sw["level"]:
                detected_fractal_set.add(key)
                dist = abs((current_price - sw["level"]) / sw["level"] * 100.0)
                found.append({"type": "SSL", "level": sw["level"], "price": current_price,
                              "dist_pct": dist, "swept_at": bar["time"],
                              "key": key, "source": "fractal"})
                break

    return found


# ═══════════════════════════════════════════════════════════════════════════════
# DETECTION PDH/PDL & PWH/PWL (Daily & Weekly Levels)
# ═══════════════════════════════════════════════════════════════════════════════

def _bar_sweeps_high(bar, level):
    """BSL : meche traverse le haut + close rejette en-dessous."""
    return bar["high"] > level and bar["close"] < level


def _bar_sweeps_low(bar, level):
    """SSL : meche traverse le bas + close rejette au-dessus."""
    return bar["low"] < level and bar["close"] > level


def _get_daily_levels(symbol):
    """Retourne (pdh, pdl, date_label) ou None si pas assez de D1."""
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, 5)
    if rates is None or len(rates) < 2:
        return None
    bars = []
    for r in rates:
        bars.append({"time": int(r[0]), "high": float(r[2]), "low": float(r[3])})
    bars.sort(key=lambda b: b["time"])
    yesterday = bars[-2]
    date_label = datetime.fromtimestamp(yesterday["time"], UTC).strftime("%Y-%m-%d")
    return (yesterday["high"], yesterday["low"], date_label)


def _get_weekly_levels(symbol):
    """Retourne (pwh, pwl, week_label) ou None si pas assez de W1."""
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_W1, 0, 4)
    if rates is None or len(rates) < 2:
        return None
    bars = []
    for r in rates:
        bars.append({"time": int(r[0]), "high": float(r[2]), "low": float(r[3])})
    bars.sort(key=lambda b: b["time"])
    last_week = bars[-2]
    this_week = bars[-1]
    week_label = datetime.fromtimestamp(last_week["time"], UTC).strftime("%Y-W%W")
    return (last_week["high"], last_week["low"], week_label, this_week["time"])


def _check_daily_weekly_for_symbol(symbol, detected_daily, detected_weekly,
                                   daily_cache, weekly_cache):
    """Verifie les sweeps PDH/PDL (H1) et PWH/PWL (D1).
    Retourne une liste de sweeps detectes."""
    found = []
    tick = mt5.symbol_info_tick(symbol)
    price = float(tick.bid) if tick else 0.0

    # ── Daily (PDH/PDL) ───────────────────────────────────────
    if symbol not in daily_cache or daily_cache[symbol] is None:
        daily_cache[symbol] = _get_daily_levels(symbol)
    dl = daily_cache.get(symbol)
    if dl is not None:
        pdh, pdl, date_label = dl
        # Fetch H1 bars once for both PDH and PDL checks
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, DW_LOOKBACK)
        if rates is not None and len(rates) > 0:
            abs_pdh = abs((price - pdh) / pdh * 100.0) if price and pdh else 0
            abs_pdl = abs((price - pdl) / pdl * 100.0) if price and pdl else 0
            mid = (pdh + pdl) / 2
            key_h = f"DAILY_{symbol}_PDH_{pdh:.5f}"
            key_l = f"DAILY_{symbol}_PDL_{pdl:.5f}"
            for r in rates:
                bar = {"time": int(r[0]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4])}
                if key_h not in detected_daily and _bar_sweeps_high(bar, pdh):
                    detected_daily.add(key_h)
                    found.append({"source": "daily", "level_type": "PDH",
                                  "sweep_type": "BSL", "level": pdh,
                                  "other_level": pdl, "level_label": date_label,
                                  "price": price, "dist_pct": abs_pdh,
                                  "swept_at": bar["time"], "key": key_h,
                                  "direction": "SELL" if price < mid else "-"})
                if key_l not in detected_daily and _bar_sweeps_low(bar, pdl):
                    detected_daily.add(key_l)
                    found.append({"source": "daily", "level_type": "PDL",
                                  "sweep_type": "SSL", "level": pdl,
                                  "other_level": pdh, "level_label": date_label,
                                  "price": price, "dist_pct": abs_pdl,
                                  "swept_at": bar["time"], "key": key_l,
                                  "direction": "BUY" if price > mid else "-"})
                if key_h in detected_daily and key_l in detected_daily:
                    break

    # ── Weekly (PWH/PWL) ──────────────────────────────────────
    if symbol not in weekly_cache or weekly_cache[symbol] is None:
        weekly_cache[symbol] = _get_weekly_levels(symbol)
    wl = weekly_cache.get(symbol)
    if wl is not None:
        pwh, pwl, week_label, this_week_start = wl
        # Fetch D1 bars once for both PWH and PWL checks
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, 14)
        if rates is not None and len(rates) > 0:
            abs_pwh = abs((price - pwh) / pwh * 100.0) if price and pwh else 0
            abs_pwl = abs((price - pwl) / pwl * 100.0) if price and pwl else 0
            mid = (pwh + pwl) / 2
            key_h = f"WEEKLY_{symbol}_PWH_{pwh:.5f}"
            key_l = f"WEEKLY_{symbol}_PWL_{pwl:.5f}"
            for r in rates:
                bar = {"time": int(r[0]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4])}
                if key_h not in detected_weekly and bar["time"] >= this_week_start and _bar_sweeps_high(bar, pwh):
                    detected_weekly.add(key_h)
                    found.append({"source": "weekly", "level_type": "PWH",
                                  "sweep_type": "BSL", "level": pwh,
                                  "other_level": pwl, "level_label": week_label,
                                  "price": price, "dist_pct": abs_pwh,
                                  "swept_at": bar["time"], "key": key_h,
                                  "direction": "SELL" if price < mid else "-"})
                if key_l not in detected_weekly and bar["time"] >= this_week_start and _bar_sweeps_low(bar, pwl):
                    detected_weekly.add(key_l)
                    found.append({"source": "weekly", "level_type": "PWL",
                                  "sweep_type": "SSL", "level": pwl,
                                  "other_level": pwh, "level_label": week_label,
                                  "price": price, "dist_pct": abs_pwl,
                                  "swept_at": bar["time"], "key": key_l,
                                  "direction": "BUY" if price > mid else "-"})
                if key_h in detected_weekly and key_l in detected_weekly:
                    break

    return found


def _dw_alert(symbol, sw):
    """Alerte ecran pour un sweep PDH/PDL/PWH/PWL."""
    print(BELL)
    bar = "=" * 72
    color_bg = BG_RED if sw["sweep_type"] == "BSL" else BG_GREEN
    print(f"\n{color_bg}{WHITE}{BOLD}{bar}{RESET}")
    print(f"{color_bg}{WHITE}{BOLD}  !!! {sw['source'].upper()} {sw['level_type']} {sw['sweep_type']} SWEEP !!!  {_pdt()}  |  {_session()}{RESET}")
    print(f"{color_bg}{WHITE}{BOLD}{bar}{RESET}")
    color = RED if sw["sweep_type"] == "BSL" else GREEN
    print(f"\n  {BOLD}{color}>>> {sw['sweep_type']} {sw['level_type']} sur {symbol} <<<{RESET}")
    print(f"  Source         : {sw['source'].upper()} ({sw['level_label']})")
    print(f"  Niveau sweepe  : {_fmt(sw['level'])}")
    print(f"  Niveau oppose  : {_fmt(sw['other_level'])}")
    print(f"  Midpoint       : {_fmt((sw['level'] + sw['other_level']) / 2)}")
    if sw.get("price") and sw.get("level"):
        print(f"  Prix actuel    : {_fmt(sw['price'])}")
    print(f"  Distance       : {sw['dist_pct']:.3f}%")
    print(f"  Sweepe a       : {_pdt(sw['swept_at'])}")
    _opposite = {"PDH": "PDL", "PDL": "PDH", "PWH": "PWL", "PWL": "PWH"}
    opp = _opposite.get(sw["level_type"], "?")
    if sw["sweep_type"] == "BSL":
        print(f"  Direction ICT  : REVERSAL DOWN (baissier) -> vise le bas ({opp})")
    else:
        print(f"  Direction ICT  : REVERSAL UP (haussier) -> vise le haut ({opp})")
    if sw.get("direction") and sw["direction"] != "-":
        action_color = RED if sw["direction"] == "SELL" else GREEN
        print(f"\n  {BOLD}{action_color}[TRADE IMPLICITE] {sw['direction']}{RESET}")
        print(f"  Explication : {sw['sweep_type']} sweep = raid stops {'acheteurs' if sw['sweep_type'] == 'BSL' else 'vendeurs'}. "
              f"Reversal {'down' if sw['direction'] == 'SELL' else 'up'} attendu.")
    print(f"{color_bg}{WHITE}{BOLD}{bar}{RESET}\n")
    sys.stdout.flush()


# ═══════════════════════════════════════════════════════════════════════════════
# LIVE MONITOR
# ═══════════════════════════════════════════════════════════════════════════════

class LiveSweepMonitor:

    def __init__(self, symbols):
        self.symbols = [s for s in symbols if s]
        self.asian_ranges = {}
        self.detected_asian: Set[str] = set()
        self.detected_fractal: Set[str] = set()
        self.detected_daily: Set[str] = set()
        self.detected_weekly: Set[str] = set()
        self.daily_cache: Dict[str, Optional[tuple]] = {}
        self.weekly_cache: Dict[str, Optional[tuple]] = {}
        self._dw_last_check = 0.0
        self._running = False

    def _connect(self):
        if not mt5.initialize():
            return False
        for sym in self.symbols:
            info = mt5.symbol_info(sym)
            if info and not info.visible:
                mt5.symbol_select(sym, True)
        return True

    def _compute_asian(self, symbol):
        """Calcule le range asiatique du jour.
        - PENDANT la session (UTC 0-7) : range partiel, frozen=False.
        - APRES la session (UTC >= 8) : range final, frozen=True."""
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        now_h = datetime.now(UTC).hour
        inside = ASIAN_START_UTC <= now_h < ASIAN_END_UTC
        frozen = not inside  # Le range est verrouille seulement apres 08:00 UTC

        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 48)
        asian_bars = []
        if rates is not None and len(rates) > 0:
            for r in rates:
                dt = datetime.fromtimestamp(int(r[0]), UTC)
                if dt.strftime("%Y-%m-%d") == today and ASIAN_START_UTC <= dt.hour < ASIAN_END_UTC:
                    asian_bars.append({"high": float(r[2]), "low": float(r[3])})

        if len(asian_bars) < 2 and inside:
            m15 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 96)
            if m15 is not None and len(m15) > 0:
                asian_bars = []
                for r in m15:
                    dt = datetime.fromtimestamp(int(r[0]), UTC)
                    if dt.strftime("%Y-%m-%d") == today and ASIAN_START_UTC <= dt.hour < ASIAN_END_UTC:
                        asian_bars.append({"high": float(r[2]), "low": float(r[3])})

        if len(asian_bars) < 2:
            return None

        ah = max(b["high"] for b in asian_bars)
        al = min(b["low"] for b in asian_bars)
        self.asian_ranges[symbol] = {"ah": ah, "al": al, "mid": (ah + al) / 2,
                                     "day": today, "range": ah - al,
                                     "frozen": frozen, "bars": len(asian_bars)}

    def _ensure_asian(self, symbol):
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        r = self.asian_ranges.get(symbol)
        # Verrouillage : si le range est encore partiel mais que la session
        # vient de finir (UTC >= 8), on force un recalcul avec toutes les barres.
        if r is not None and r["day"] == today and not r["frozen"]:
            now_h = datetime.now(UTC).hour
            if now_h >= ASIAN_END_UTC:
                self._compute_asian(symbol)
        # Nouveau jour ou pas encore de range -> calculer
        if r is None or r["day"] != today:
            self._compute_asian(symbol)

    def _check_asian_sweeps(self, symbol):
        rng = self.asian_ranges.get(symbol)
        if rng is None:
            return []
        # Si le range n'est pas encore verrouille (session en cours),
        # on ne detecte PAS de sweep asiatique. Le range est encore partiel.
        if not rng.get("frozen", False):
            return []
        ah, al = rng["ah"], rng["al"]
        found = []

        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, LOOKBACK_BARS_M1)
        if rates is None or len(rates) == 0:
            return []

        recent = []
        for r in rates[-30:]:
            recent.append({"time": int(r[0]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4])})

        tick = mt5.symbol_info_tick(symbol)
        price = float(tick.bid) if tick else (recent[-1]["close"] if recent else 0)

        bsl_key = f"{symbol}_ASIAN_BSL"
        if bsl_key not in self.detected_asian:
            for bar in recent:
                if bar["high"] > ah and bar["close"] < ah:
                    self.detected_asian.add(bsl_key)
                    found.append({"type": "BSL", "level": ah, "price": price,
                                  "swept_at": bar["time"], "key": bsl_key, "source": "asian"})
                    break

        ssl_key = f"{symbol}_ASIAN_SSL"
        if ssl_key not in self.detected_asian:
            for bar in recent:
                if bar["low"] < al and bar["close"] > al:
                    self.detected_asian.add(ssl_key)
                    found.append({"type": "SSL", "level": al, "price": price,
                                  "swept_at": bar["time"], "key": ssl_key, "source": "asian"})
                    break

        return found

    @staticmethod
    def _build_trade(direction, price, ah, al, mid, range_size, other_swept):
        if direction == "SELL":
            sl = ah + 0.10 * range_size
            tp1 = al - 1.618 * range_size
            tp2 = al - 2.618 * range_size
            risk = sl - price if sl > price else 0.001
            rr = (price - tp1) / risk if risk > 0 else 0
            confirmed = price < mid
            sw_name, lvl_name, fib_dir, other = "BSL", "AH", "-1.618", "AL"
        else:
            sl = al - 0.10 * range_size
            tp1 = ah + 1.618 * range_size
            tp2 = ah + 2.618 * range_size
            risk = price - sl if price > sl else 0.001
            rr = (tp1 - price) / risk if risk > 0 else 0
            confirmed = price > mid
            sw_name, lvl_name, fib_dir, other = "SSL", "AL", "+1.618", "AH"

        if confirmed:
            status = "Active"
            expl = (f"{sw_name} sweep ({lvl_name} {_fmt(ah if direction == 'SELL' else al)}). "
                    f"Prix={_fmt(price)} {'<' if direction == 'SELL' else '>'} midpoint={_fmt(mid)}. "
                    f"Breakout {'baissier' if direction == 'SELL' else 'haussier'} confirme. "
                    f"Cible {fib_dir} Fib a {_fmt(tp1)}. "
                    f"{'L autre cote (' + other + ') aussi sweepe -> setup complet.' if other_swept else 'Attendre confirmation ' + other + '.'}")
        else:
            status = "Wait"
            expl = (f"{sw_name} sweep detecte mais prix={_fmt(price)} encore "
                    f"{'au-dessus' if direction == 'SELL' else 'sous'} le midpoint={_fmt(mid)}. "
                    f"Attendre la cassure du midpoint pour confirmer le {direction}.")
        return {"sl": sl, "tp1": tp1, "tp2": tp2, "rr": rr, "status": status, "explanation": expl}

    def _asian_trade(self, symbol, sweep):
        rng = self.asian_ranges.get(symbol)
        if rng is None:
            return {"action": "-", "entry": None, "sl": None, "tp1": None, "tp2": None,
                    "rr": None, "explanation": "Pas de range asiatique"}
        ah, al, mid = rng["ah"], rng["al"], rng["mid"]
        range_size = ah - al
        price = sweep["price"]
        other_key = f"{symbol}_ASIAN_SSL" if sweep["type"] == "BSL" else f"{symbol}_ASIAN_BSL"
        other_swept = other_key in self.detected_asian
        if sweep["type"] == "BSL" and price < ah:
            direction = "SELL"
        elif sweep["type"] == "SSL" and price > al:
            direction = "BUY"
        else:
            return {"action": "-", "entry": price, "sl": None, "tp1": None, "tp2": None,
                    "rr": None, "status": "Wait",
                    "explanation": "Sweep detecte mais prix pas encore du bon cote. Surveillance."}
        p = self._build_trade(direction, price, ah, al, mid, range_size, other_swept)
        return {"action": direction, "status": p["status"], "entry": price,
                "sl": p["sl"], "tp1": p["tp1"], "tp2": p["tp2"], "rr": p["rr"],
                "explanation": p["explanation"]}

    def run(self):
        print(f"\n{BOLD}{CYAN}{'='*72}{RESET}")
        print(f"{BOLD}{CYAN}  InelidaMarketScanner - LIVE SWEEP DETECTOR (NO TRADE){RESET}")
        print(f"{BOLD}{CYAN}  Heure plateforme : {_pdt()}{RESET}")
        print(f"{BOLD}{CYAN}  Session ICT      : {_session()}{RESET}")
        print(f"{BOLD}{CYAN}  Symboles          : {len(self.symbols)}{RESET}")
        print(f"{BOLD}{CYAN}  Detection         : Asian (AH/AL) + Fractal (Williams N={FRACTAL_N}) + Daily/Weekly (PDH/PDL PWH/PWL){RESET}")
        print(f"{BOLD}{CYAN}  Log               : {LOG_FILE}{RESET}")
        print(f"{BOLD}{CYAN}{'='*72}{RESET}\n")

        if not self._connect():
            print(f"{RED}[ERREUR] Connexion MT5 impossible.{RESET}")
            return

        print(f"  {GREEN}[OK] MT5 connecte.{RESET}")
        print(f"  Calcul des ranges asiatiques...")

        for sym in self.symbols:
            r = self._compute_asian(sym)
            if r:
                status = "[FORME]" if r.get("frozen") else f"[EN COURS - {r.get('bars', '?')} barres]"
                print(f"    {MAGENTA}{sym:<12}{RESET} AH={_fmt(r['ah'])} AL={_fmt(r['al'])} Range={_fmt(r['range'])} {YELLOW}{status}{RESET}")

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        n_ranges = sum(1 for r in self.asian_ranges.values() if r["day"] == today)
        n_frozen = sum(1 for r in self.asian_ranges.values() if r["day"] == today and r.get("frozen"))
        frozen_label = f"({n_frozen} verrouilles)" if n_frozen < n_ranges else "(tous verrouilles)"
        print(f"\n  {GREEN}{n_ranges}/{len(self.symbols)} ranges asiatiques {frozen_label}.{RESET}")

        # Pre-compute daily/weekly levels
        print(f"  Calcul des niveaux Daily/Weekly...")
        n_dw = 0
        for sym in self.symbols:
            dl = _get_daily_levels(sym)
            self.daily_cache[sym] = dl
            wl = _get_weekly_levels(sym)
            self.weekly_cache[sym] = wl
            if dl or wl:
                n_dw += 1
                dw_parts = []
                if dl: dw_parts.append(f"PDH={_fmt(dl[0])} PDL={_fmt(dl[1])}")
                if wl: dw_parts.append(f"PWH={_fmt(wl[0])} PWL={_fmt(wl[1])}")
                if dw_parts:
                    print(f"    {MAGENTA}{sym:<12}{RESET} {' | '.join(dw_parts)}")
        print(f"\n  {GREEN}{n_dw}/{len(self.symbols)} niveaux Daily/Weekly.{RESET}")
        print(f"  {YELLOW}En attente de sweeps (Asian=apres 10:00 / Fractal=live / Daily/Weekly=live)...{RESET}\n")

        self._running = True
        check_count = 0

        try:
            while self._running:
                check_count += 1
                session = _session()

                # ── Rafraichir niveaux Daily/Weekly (tous les 120s) ─
                if time.time() - self._dw_last_check >= DAILY_WEEKLY_CHECK_INTERVAL:
                    self._dw_last_check = time.time()
                    for sym in self.symbols:
                        self.daily_cache[sym] = _get_daily_levels(sym)
                        self.weekly_cache[sym] = _get_weekly_levels(sym)

                for sym in self.symbols:
                    # ── Asian sweeps ──────────────────────────────────
                    self._ensure_asian(sym)
                    asian_sweeps = self._check_asian_sweeps(sym)
                    for sw in asian_sweeps:
                        trade = self._asian_trade(sym, sw)
                        rng = self.asian_ranges[sym]
                        _asian_alert(sym, sw["type"], sw["level"], sw["price"],
                                     rng["ah"], rng["al"], trade)
                        _log(sym, sw["type"], sw["level"], sw["price"], trade, "asian")

                    # ── Fractal sweeps ────────────────────────────────
                    fractal_sweeps = _check_fractal_sweeps_for_symbol(
                        sym, self.detected_fractal)
                    for sw in fractal_sweeps:
                        _fractal_alert(sym, sw["type"], sw["level"], sw["price"],
                                       sw["dist_pct"], sw["swept_at"])
                        direction = "SELL" if sw["type"] == "BSL" else "BUY"
                        dir_label = "REVERSAL DOWN (baissier)" if sw["type"] == "BSL" else "REVERSAL UP (haussier)"
                        _log(sym, sw["type"], sw["level"], sw["price"],
                             {"action": direction, "status": "Active",
                              "entry": sw["price"], "sl": None, "tp1": None, "rr": None,
                              "explanation": f"Fractal {sw['type']} sweep a {_fmt(sw['level'])}. "
                              f"{dir_label}. Distance au prix: {sw['dist_pct']:.3f}%. "
                              f"Surveiller la direction implicite ICT."}, "fractal")

                    # ── Daily/Weekly sweeps ───────────────────────────
                    dw_sweeps = _check_daily_weekly_for_symbol(
                        sym, self.detected_daily, self.detected_weekly,
                        self.daily_cache, self.weekly_cache)
                    for sw in dw_sweeps:
                        _dw_alert(sym, sw)
                        _log(sym, sw["sweep_type"], sw["level"], sw.get("price", 0),
                             {"action": sw.get("direction", "-"),
                              "status": "Active",
                              "entry": sw.get("price"), "sl": None, "tp1": None, "rr": None,
                              "explanation": f"{sw['source'].upper()} {sw['level_type']} {sw['sweep_type']} sweep "
                              f"(niveau du {sw['level_label']}). "
                              f"{'Raid stops acheteurs -> reversal down attendu.' if sw['sweep_type'] == 'BSL' else 'Raid stops vendeurs -> reversal up attendu.'}"},
                             sw["source"])

                if check_count % 2 == 0:
                    n_a = len(self.detected_asian)
                    n_f = len(self.detected_fractal)
                    n_d = len(self.detected_daily)
                    n_w = len(self.detected_weekly)
                    print(f"  {_pt()} | {session} | Check #{check_count} | "
                          f"Asian: {n_a} | Fractal: {n_f} | Daily: {n_d} | Weekly: {n_w} | "
                          f"Ctrl+C pour quitter  ", end="\r")
                    sys.stdout.flush()

                time.sleep(POLL_INTERVAL_SEC)

        except KeyboardInterrupt:
            print(f"\n\n  {YELLOW}[STOP] Arret demande.{RESET}")

        finally:
            mt5.shutdown()
            n_a = len(self.detected_asian)
            n_f = len(self.detected_fractal)
            n_d = len(self.detected_daily)
            n_w = len(self.detected_weekly)
            print(f"  {GREEN}[OK] {n_a} Asian + {n_f} Fractal + {n_d} Daily + {n_w} Weekly = "
                  f"{n_a + n_f + n_d + n_w} total.{RESET}")
            print(f"  {GREEN}[OK] Log : {LOG_FILE}{RESET}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    LiveSweepMonitor(WATCHLIST).run()
