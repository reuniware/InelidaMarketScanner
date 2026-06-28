"""
Analyse ICT/SMC XAUUSD — Récupère les bougies des sessions Asian/London/NY
depuis MT5 et produit une analyse détaillée de ce qu'il s'est passé.
"""

import sys
import time
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple

# Forcer l'encodage UTF-8 sur stdout
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Ajouter le répertoire du projet au path
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

# ─── Configuration ──────────────────────────────────────────────────────────
SYMBOL = "XAUUSD"
UTC = timezone.utc
PLATFORM_OFFSET = 2  # UTC+2 (EEST/CEST)

# Sessions ICT (heures UTC)
ASIAN_START = 0
ASIAN_END = 8
LONDON_START = 8
LONDON_END = 13
NY_START = 13
NY_END = 21

# ─── ANSI ───────────────────────────────────────────────────────────────────
_IS_TTY = sys.stdout.isatty()

def _c(code): return code if _IS_TTY else ""
BOLD = _c("\033[1m"); DIM = _c("\033[2m")
RED = _c("\033[31m"); GREEN = _c("\033[32m"); YELLOW = _c("\033[33m")
CYAN = _c("\033[36m"); MAGENTA = _c("\033[35m"); WHITE = _c("\033[97m")
BG_RED = _c("\033[41m"); BG_GREEN = _c("\033[42m"); BG_YELLOW = _c("\033[43m")
GRAY = _c("\033[90m"); RESET = _c("\033[0m")

# ─── Helpers ────────────────────────────────────────────────────────────────
def _fmt(p: Optional[float]) -> str:
    if p is None:
        return "-"
    return f"{p:.2f}"

def _fmt_small(p: Optional[float]) -> str:
    if p is None:
        return "-"
    return f"{p:.5f}"

def _pt(epoch: float) -> str:
    """Epoch UTC -> heure plateforme lisible."""
    platform = datetime.fromtimestamp(epoch, UTC) + timedelta(hours=PLATFORM_OFFSET)
    return platform.strftime("%H:%M")

def _pdt(epoch: float) -> str:
    """Epoch UTC -> datetime plateforme lisible."""
    platform = datetime.fromtimestamp(epoch, UTC) + timedelta(hours=PLATFORM_OFFSET)
    return platform.strftime("%Y-%m-%d %H:%M")

def _to_utc_hour(epoch: float) -> int:
    return datetime.fromtimestamp(epoch, UTC).hour

def _session_for_hour(h_utc: int) -> str:
    if ASIAN_START <= h_utc < ASIAN_END:
        return "Asian"
    if LONDON_START <= h_utc < LONDON_END:
        return "London"
    if NY_START <= h_utc < NY_END:
        return "NY"
    return "Off"

def _bars_to_dicts(rates_raw) -> List[dict]:
    out = []
    for r in rates_raw:
        out.append({
            "time": int(r[0]),
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
            "tick_volume": int(r[5]) if len(r) > 5 else 0,
        })
    return out

def _bar_body(b: dict) -> float:
    return b["close"] - b["open"]

def _bar_range(b: dict) -> float:
    return b["high"] - b["low"]

def _bar_upper_wick(b: dict) -> float:
    return b["high"] - max(b["open"], b["close"])

def _bar_lower_wick(b: dict) -> float:
    return min(b["open"], b["close"]) - b["low"]

def _bar_direction(b: dict) -> str:
    body = _bar_body(b)
    if body > 0:
        return "BULL"
    if body < 0:
        return "BEAR"
    return "DOJI"


# ═══════════════════════════════════════════════════════════════════════════════
# FONCTIONS D'EXTRACTION MT5
# ═══════════════════════════════════════════════════════════════════════════════

def connect_mt5() -> bool:
    if not mt5.initialize():
        return False
    ti = mt5.terminal_info()
    if ti:
        print(f"{DIM}Terminal MT5 : {ti.name} (build {ti.build}){RESET}")
    info = mt5.symbol_info(SYMBOL)
    if info is None:
        print(f"{RED}XAUUSD non trouvé chez ce broker.{RESET}")
        return False
    if not info.visible:
        mt5.symbol_select(SYMBOL, True)
    return True


def fetch_bars(tf, n_bars: int = 300) -> List[dict]:
    """Récupère les N dernières bougies pour le timeframe donné."""
    rates = mt5.copy_rates_from_pos(SYMBOL, tf, 0, n_bars)
    if rates is None or len(rates) == 0:
        return []
    bars = _bars_to_dicts(rates)
    bars.sort(key=lambda b: b["time"])
    return bars


def get_today_bars(tf, tf_mt5, n_bars: int = 100) -> List[dict]:
    """Récupère toutes les bougies d'aujourd'hui."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    bars = fetch_bars(tf_mt5, n_bars)
    return [b for b in bars if datetime.fromtimestamp(b["time"], UTC).strftime("%Y-%m-%d") == today]


# ═══════════════════════════════════════════════════════════════════════════════
# DÉTECTION ICT
# ═══════════════════════════════════════════════════════════════════════════════

def compute_asian_range(h1_bars_today: List[dict]) -> Optional[Dict]:
    """Extrait le range asiatique (UTC 00:00-08:00) des barres H1 d'aujourd'hui."""
    asian_bars = [b for b in h1_bars_today if ASIAN_START <= _to_utc_hour(b["time"]) < ASIAN_END]
    if len(asian_bars) < 2:
        return None

    ah = max(b["high"] for b in asian_bars)
    al = min(b["low"] for b in asian_bars)
    mid = (ah + al) / 2
    range_size = ah - al
    last_asian_time = max(b["time"] for b in asian_bars)

    return {
        "ah": ah, "al": al, "mid": mid, "range": range_size,
        "bars": asian_bars,
        "first_bar": min(b["time"] for b in asian_bars),
        "last_bar": last_asian_time,
    }


def detect_asian_sweeps(asian_range: Dict, h1_bars: List[dict]) -> Dict:
    """Détecte les sweeps ICT du range asiatique dans les bougies post-Asian."""
    ah = asian_range["ah"]
    al = asian_range["al"]
    last_asian = asian_range["last_bar"]

    # Bougies post-Asian
    post_bars = [b for b in h1_bars if b["time"] > last_asian]

    ah_swept = False
    al_swept = False
    ah_swept_at = None
    al_swept_at = None
    ah_swept_session = None
    al_swept_session = None
    ah_breached = False
    al_breached = False

    for b in post_bars:
        # Sweep AH : mèche au-dessus + close en-dessous (ICT)
        if not ah_swept and b["high"] > ah and b["close"] < ah:
            ah_swept = True
            ah_swept_at = b["time"]
            ah_swept_session = _session_for_hour(_to_utc_hour(b["time"]))
        # Sweep AL : mèche en-dessous + close au-dessus (ICT)
        if not al_swept and b["low"] < al and b["close"] > al:
            al_swept = True
            al_swept_at = b["time"]
            al_swept_session = _session_for_hour(_to_utc_hour(b["time"]))
        # Breach AH (mèche uniquement)
        if not ah_breached and b["high"] > ah:
            ah_breached = True
        # Breach AL (mèche uniquement)
        if not al_breached and b["low"] < al:
            al_breached = True

    return {
        "ah_swept": ah_swept, "al_swept": al_swept,
        "ah_swept_at": ah_swept_at, "al_swept_at": al_swept_at,
        "ah_swept_session": ah_swept_session, "al_swept_session": al_swept_session,
        "ah_breached": ah_breached, "al_breached": al_breached,
        "post_bars": post_bars,
    }


def detect_fib_levels(asian_range: Dict, sweeps: Dict, current_price: float) -> Dict:
    """Calcule les extensions Fibonacci et détecte les sweeps de niveaux Fib."""
    ah = asian_range["ah"]
    al = asian_range["al"]
    range_size = asian_range["range"]

    fib_levels = {}
    for n in [1.618, 2.0, 2.618, 3.0, 3.618, 4.0]:
        fib_levels[f"+{n}"] = ah + n * range_size
        fib_levels[f"-{n}"] = al - n * range_size

    # Quelle est la prochaine cible Fib non atteinte ?
    fib_target = ""
    if sweeps["al_swept"] and current_price > ah:
        # Bull : AL sweepé, prix au-dessus du AH → on vise les Fib+
        for n in [1.618, 2.0, 2.618, 3.0, 3.618, 4.0]:
            if current_price < ah + n * range_size:
                fib_target = f"+{n}"
                break
        if not fib_target:
            fib_target = "+4.0 ✓"
    elif sweeps["ah_swept"] and current_price < al:
        # Bear : AH sweepé, prix sous le AL → on vise les Fib-
        for n in [-1.618, -2.0, -2.618, -3.0, -3.618, -4.0]:
            if current_price > al - abs(n) * range_size:
                fib_target = f"{n}"
                break
        if not fib_target:
            fib_target = "-4.0 ✓"

    return {"levels": fib_levels, "target": fib_target}


def detect_daily_levels(all_h1: List[dict]) -> Optional[Dict]:
    """Récupère le PDH/PDL (Previous Day High/Low)."""
    # On prend les D1
    d1_rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_D1, 0, 4)
    if d1_rates is None or len(d1_rates) < 2:
        return None

    d1_bars = _bars_to_dicts(d1_rates)
    d1_bars.sort(key=lambda b: b["time"])
    yesterday = d1_bars[-2]
    today_d1 = d1_bars[-1]

    pdh = yesterday["high"]
    pdl = yesterday["low"]
    yesterday_date = datetime.fromtimestamp(yesterday["time"], UTC).strftime("%Y-%m-%d")

    # Vérifier si PDH/PDL ont été sweepés aujourd'hui
    today_open = today_d1["time"]
    today_bars = [b for b in all_h1 if b["time"] >= today_open]

    pdh_swept = False
    pdl_swept = False
    pdh_swept_at = None
    pdl_swept_at = None

    for b in today_bars:
        if not pdh_swept and b["high"] > pdh and b["close"] < pdh:
            pdh_swept = True
            pdh_swept_at = b["time"]
        if not pdl_swept and b["low"] < pdl and b["close"] > pdl:
            pdl_swept = True
            pdl_swept_at = b["time"]

    return {
        "pdh": pdh, "pdl": pdl, "date": yesterday_date,
        "pdh_swept": pdh_swept, "pdl_swept": pdl_swept,
        "pdh_swept_at": pdh_swept_at, "pdl_swept_at": pdl_swept_at,
    }


def detect_weekly_levels(all_h1: List[dict]) -> Optional[Dict]:
    """Récupère le PWH/PWL (Previous Week High/Low)."""
    w1_rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_W1, 0, 3)
    if w1_rates is None or len(w1_rates) < 2:
        return None

    w1_bars = _bars_to_dicts(w1_rates)
    w1_bars.sort(key=lambda b: b["time"])
    last_week = w1_bars[-2]
    this_week = w1_bars[-1]

    pwh = last_week["high"]
    pwl = last_week["low"]
    week_label = datetime.fromtimestamp(last_week["time"], UTC).strftime("%Y-W%W")

    this_week_start = this_week["time"]
    this_week_bars = [b for b in all_h1 if b["time"] >= this_week_start]

    pwh_swept = False
    pwl_swept = False

    for b in this_week_bars:
        if not pwh_swept and b["high"] > pwh and b["close"] < pwh:
            pwh_swept = True
        if not pwl_swept and b["low"] < pwl and b["close"] > pwl:
            pwl_swept = True

    return {
        "pwh": pwh, "pwl": pwl, "week": week_label,
        "pwh_swept": pwh_swept, "pwl_swept": pwl_swept,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# AFFICHAGE
# ═══════════════════════════════════════════════════════════════════════════════

def print_bar_details(bar: dict, label: str = ""):
    """Affiche une bougie avec ses caractéristiques."""
    d = _bar_direction(bar)
    color = GREEN if d == "BULL" else (RED if d == "BEAR" else YELLOW)
    body = _bar_body(bar)
    wick_up = _bar_upper_wick(bar)
    wick_down = _bar_lower_wick(bar)
    range_val = _bar_range(bar)

    arrow = "▲" if d == "BULL" else ("▼" if d == "BEAR" else "─")
    prefix = f"  {label}: " if label else "  "

    print(f"{prefix}{color}{arrow} {d:5}{RESET} | "
          f"O={_fmt(bar['open'])} H={_fmt(bar['high'])} "
          f"L={_fmt(bar['low'])} C={_fmt(bar['close'])} | "
          f"Body={_fmt(body)} Range={_fmt(range_val)} | "
          f"Wick↑={_fmt(wick_up)} Wick↓={_fmt(wick_down)} | "
          f"{_pt(bar['time'])}")


def print_session_bars(bars: List[dict], session_name: str, compact: bool = False):
    """Affiche les bougies d'une session."""
    if not bars:
        print(f"  {DIM}Aucune bougie pour cette session.{RESET}")
        return

    if compact:
        # Affichage compact : une ligne par bougie
        for b in bars:
            d = _bar_direction(b)
            color = GREEN if d == "BULL" else (RED if d == "BEAR" else YELLOW)
            print(f"  {color}{d[0]}{RESET} {_pt(b['time'])} "
                  f"O={_fmt(b['open'])} H={_fmt(b['high'])} "
                  f"L={_fmt(b['low'])} C={_fmt(b['close'])}")
    else:
        for b in bars:
            print_bar_details(b, _pt(b['time']))


def analyze_direction(asian_range: Dict, sweeps: Dict, current_price: float) -> str:
    """Détermine le biais directionnel ICT."""
    ah = asian_range["ah"]
    al = asian_range["al"]
    mid = asian_range["mid"]

    if sweeps["ah_swept"] and sweeps["al_swept"]:
        return "BOTH (range invalidee → chercher les deux cotes)"
    if sweeps["ah_swept"]:
        if current_price < al:
            return "BEAR (AH sweepe, prix sous AL → reversal baissier confirme)"
        if current_price < mid:
            return "BEAR probable (AH sweepe, prix < midpoint → attente cassure AL)"
        return "NEUTRE (AH sweepe mais prix > midpoint → attente)"
    if sweeps["al_swept"]:
        if current_price > ah:
            return "BULL (AL sweepe, prix au-dessus AH → reversal haussier confirme)"
        if current_price > mid:
            return "BULL probable (AL sweepe, prix > midpoint → attente cassure AH)"
        return "NEUTRE (AL sweepe mais prix < midpoint → attente)"
    return "NEUTRE (aucun sweep → range intact)"


def compute_trade_idea(asian_range: Dict, sweeps: Dict, fib: Dict, current_price: float) -> Dict:
    """Génère une idée de trade ICT."""
    ah = asian_range["ah"]
    al = asian_range["al"]
    range_size = asian_range["range"]
    mid = asian_range["mid"]

    trade = {"action": "-", "entry": None, "sl": None, "tp1": None, "tp2": None, "rr": None, "status": "-"}

    # BUY setup : AL sweepé + prix au-dessus du AH
    if sweeps["al_swept"] and current_price > ah and not sweeps["ah_swept"]:
        trade["action"] = "BUY"
        trade["entry"] = current_price
        trade["sl"] = al - 0.10 * range_size
        trade["tp1"] = ah + 1.618 * range_size
        trade["tp2"] = ah + 2.618 * range_size
        risk = trade["entry"] - trade["sl"]
        if risk > 0:
            trade["rr"] = (trade["tp1"] - trade["entry"]) / risk
        trade["status"] = "Active"

    # SELL setup : AH sweepé + prix sous le AL
    elif sweeps["ah_swept"] and current_price < al and not sweeps["al_swept"]:
        trade["action"] = "SELL"
        trade["entry"] = current_price
        trade["sl"] = ah + 0.10 * range_size
        trade["tp1"] = al - 1.618 * range_size
        trade["tp2"] = al - 2.618 * range_size
        risk = trade["sl"] - trade["entry"]
        if risk > 0:
            trade["rr"] = (trade["entry"] - trade["tp1"]) / risk
        trade["status"] = "Active"

    return trade


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    now = datetime.now(UTC)
    today_str = now.strftime("%Y-%m-%d")
    platform_now = now + timedelta(hours=PLATFORM_OFFSET)

    print()
    print(f"{BOLD}{CYAN}{'═'*80}{RESET}")
    print(f"{BOLD}{CYAN}  ANALYSE ICT/SMC — {SYMBOL} — {today_str} UTC{RESET}")
    print(f"{BOLD}{CYAN}  Heure plateforme : {platform_now.strftime('%Y-%m-%d %H:%M')} (UTC+{PLATFORM_OFFSET}){RESET}")
    print(f"{BOLD}{CYAN}{'═'*80}{RESET}")
    print()

    # ── Connexion MT5 ──────────────────────────────────────────────────────
    if not connect_mt5():
        print(f"{RED}[ERREUR] Connexion MT5 impossible.{RESET}")
        return 1

    print(f"{GREEN}[OK] MT5 connecté.{RESET}")
    print()

    # ── Récupération des données ───────────────────────────────────────────
    print(f"{BOLD}[1] Récupération des bougies H1 pour {SYMBOL}...{RESET}")
    h1_bars = fetch_bars(mt5.TIMEFRAME_H1, 100)
    if not h1_bars:
        print(f"{RED}Aucune bougie H1 trouvée.{RESET}")
        return 1

    today_h1 = [b for b in h1_bars if datetime.fromtimestamp(b["time"], UTC).strftime("%Y-%m-%d") == today_str]
    print(f"  {GRAY}{len(h1_bars)} bougies H1 chargées, dont {len(today_h1)} aujourd'hui.{RESET}")

    # M15 pour plus de granularité
    m15_bars = fetch_bars(mt5.TIMEFRAME_M15, 200)
    today_m15 = [b for b in m15_bars if datetime.fromtimestamp(b["time"], UTC).strftime("%Y-%m-%d") == today_str]
    print(f"  {GRAY}{len(m15_bars)} bougies M15 chargées, dont {len(today_m15)} aujourd'hui.{RESET}")

    # M5 pour le détail
    m5_bars = fetch_bars(mt5.TIMEFRAME_M5, 300)
    today_m5 = [b for b in m5_bars if datetime.fromtimestamp(b["time"], UTC).strftime("%Y-%m-%d") == today_str]
    print(f"  {GRAY}{len(m5_bars)} bougies M5 chargées, dont {len(today_m5)} aujourd'hui.{RESET}")

    # Tick actuel
    tick = mt5.symbol_info_tick(SYMBOL)
    current_bid = float(tick.bid) if tick else (today_h1[-1]["close"] if today_h1 else 0)
    current_ask = float(tick.ask) if tick else current_bid
    print(f"  {GRAY}Spread actuel : {current_ask - current_bid:.2f} ({((current_ask - current_bid) / current_bid * 100):.4f}%){RESET}")
    print()

    # ══════════════════════════════════════════════════════════════════════════
    # ANALYSE ASIAN
    # ══════════════════════════════════════════════════════════════════════════
    print(f"{BOLD}{BG_YELLOW}{WHITE} ═══ SESSION ASIATIQUE (UTC 00:00-08:00) ═══ {RESET}")
    print()

    asian_range = compute_asian_range(today_h1)
    if asian_range is None:
        # Fallback M15
        asian_m15 = [b for b in today_m15 if ASIAN_START <= _to_utc_hour(b["time"]) < ASIAN_END]
        if len(asian_m15) >= 2:
            asian_range = {
                "ah": max(b["high"] for b in asian_m15),
                "al": min(b["low"] for b in asian_m15),
                "mid": (max(b["high"] for b in asian_m15) + min(b["low"] for b in asian_m15)) / 2,
                "range": max(b["high"] for b in asian_m15) - min(b["low"] for b in asian_m15),
                "bars": [],
                "first_bar": min(b["time"] for b in asian_m15),
                "last_bar": max(b["time"] for b in asian_m15),
            }
            print(f"  {YELLOW}Range calculé sur {len(asian_m15)} bougies M15 (pas assez de H1).{RESET}")
        else:
            print(f"{RED}Impossible de calculer le range asiatique.{RESET}")
            return 1

    ah = asian_range["ah"]
    al = asian_range["al"]
    mid = asian_range["mid"]
    range_size = asian_range["range"]

    print(f"  {BOLD}Asian High   :{RESET} {RED}{_fmt(ah)}{RESET}")
    print(f"  {BOLD}Asian Low    :{RESET} {GREEN}{_fmt(al)}{RESET}")
    print(f"  {BOLD}Range         :{RESET} {_fmt(range_size)} ({range_size / mid * 100:.3f}% du spot)")
    print(f"  {BOLD}Midpoint      :{RESET} {_fmt(mid)}")
    print(f"  {BOLD}Heure fin     :{RESET} {_pt(asian_range['last_bar'])}")
    print()

    # Bougies H1 de la session asiatique
    asian_h1 = [b for b in today_h1 if ASIAN_START <= _to_utc_hour(b["time"]) < ASIAN_END]
    if asian_h1:
        print(f"  {BOLD}Bougies H1 asiatiques ({len(asian_h1)}):{RESET}")
        for b in asian_h1:
            h = _to_utc_hour(b["time"])
            d = _bar_direction(b)
            color = GREEN if d == "BULL" else (RED if d == "BEAR" else YELLOW)
            print(f"    {_pt(b['time'])} | {color}{d:4}{RESET} | "
                  f"O={_fmt(b['open'])} H={_fmt(b['high'])} L={_fmt(b['low'])} C={_fmt(b['close'])}")

    print()

    # ══════════════════════════════════════════════════════════════════════════
    # DÉTECTION SWEEPS POST-ASIAN
    # ══════════════════════════════════════════════════════════════════════════
    sweeps = detect_asian_sweeps(asian_range, h1_bars)

    print(f"{BOLD}  Détection sweeps post-Asian :{RESET}")
    if sweeps["ah_swept"]:
        at = _pdt(sweeps["ah_swept_at"])
        print(f"    {RED}AH SWEPT{RESET} — {at} (session {sweeps['ah_swept_session']})")
    elif sweeps["ah_breached"]:
        print(f"    {DIM}AH touché (breach, pas de rejet){RESET}")
    else:
        print(f"    {DIM}AH intact{RESET}")

    if sweeps["al_swept"]:
        at = _pdt(sweeps["al_swept_at"])
        print(f"    {GREEN}AL SWEPT{RESET} — {at} (session {sweeps['al_swept_session']})")
    elif sweeps["al_breached"]:
        print(f"    {DIM}AL touché (breach, pas de rejet){RESET}")
    else:
        print(f"    {DIM}AL intact{RESET}")

    print()

    # ══════════════════════════════════════════════════════════════════════════
    # SESSION LONDON
    # ══════════════════════════════════════════════════════════════════════════
    print(f"{BOLD}{BG_RED}{WHITE} ═══ SESSION LONDON (UTC 08:00-13:00) ═══ {RESET}")
    print()

    london_h1 = [b for b in today_h1 if LONDON_START <= _to_utc_hour(b["time"]) < LONDON_END]
    london_m15 = [b for b in today_m15 if LONDON_START <= _to_utc_hour(b["time"]) < LONDON_END]
    london_m5 = [b for b in today_m5 if LONDON_START <= _to_utc_hour(b["time"]) < LONDON_END]

    if london_h1:
        london_high = max(b["high"] for b in london_h1)
        london_low = min(b["low"] for b in london_h1)
        london_open = london_h1[0]["open"]
        london_close = london_h1[-1]["close"]
        london_dir = "HAUSSIER" if london_close > london_open else "BAISSIER"

        print(f"  {BOLD}London Open  :{RESET} {_fmt(london_open)}")
        print(f"  {BOLD}London High  :{RESET} {_fmt(london_high)}")
        print(f"  {BOLD}London Low   :{RESET} {_fmt(london_low)}")
        print(f"  {BOLD}London Close :{RESET} {_fmt(london_close)} ({london_dir})")
        print(f"  {BOLD}Range London :{RESET} {_fmt(london_high - london_low)}")
        print()

        # Détails des bougies H1 London
        print(f"  {BOLD}Bougies H1 London ({len(london_h1)}):{RESET}")
        for b in london_h1:
            print_bar_details(b, _pt(b["time"]))

        # Comparaison London vs Asian
        print()
        print(f"  {BOLD}Analyse London vs Asian :{RESET}")
        if london_high > ah:
            print(f"    {GREEN}London a cassé l'Asian High ({_fmt(ah)}) → force haussière{RESET}")
        if london_low < al:
            print(f"    {RED}London a cassé l'Asian Low ({_fmt(al)}) → force baissière{RESET}")
        if london_low > al and london_high < ah:
            print(f"    {YELLOW}London est resté DANS le range asiatique → consolidation{RESET}")

        # Analyse du sweep dans London
        if sweeps["ah_swept"] and sweeps["ah_swept_session"] == "London":
            print(f"    {RED}!! AH SWEEP pendant London → raid stops acheteurs → reversal down{RESET}")
        if sweeps["al_swept"] and sweeps["al_swept_session"] == "London":
            print(f"    {GREEN}!! AL SWEEP pendant London → raid stops vendeurs → reversal up{RESET}")

    else:
        print(f"  {DIM}Session London pas encore commencée ou pas de données.{RESET}")

    print()

    # ══════════════════════════════════════════════════════════════════════════
    # SESSION NEW YORK
    # ══════════════════════════════════════════════════════════════════════════
    print(f"{BOLD}{BG_GREEN}{WHITE} ═══ SESSION NEW YORK (UTC 13:00-21:00) ═══ {RESET}")
    print()

    ny_h1 = [b for b in today_h1 if NY_START <= _to_utc_hour(b["time"]) < NY_END]
    ny_m15 = [b for b in today_m15 if NY_START <= _to_utc_hour(b["time"]) < NY_END]
    ny_m5 = [b for b in today_m5 if NY_START <= _to_utc_hour(b["time"]) < NY_END]

    if ny_h1:
        ny_high = max(b["high"] for b in ny_h1)
        ny_low = min(b["low"] for b in ny_h1)
        ny_open = ny_h1[0]["open"]
        ny_close = ny_h1[-1]["close"]
        ny_dir = "HAUSSIER" if ny_close > ny_open else "BAISSIER"

        print(f"  {BOLD}NY Open      :{RESET} {_fmt(ny_open)}")
        print(f"  {BOLD}NY High      :{RESET} {_fmt(ny_high)}")
        print(f"  {BOLD}NY Low       :{RESET} {_fmt(ny_low)}")
        print(f"  {BOLD}NY Close     :{RESET} {_fmt(ny_close)} ({ny_dir})")
        print(f"  {BOLD}Range NY     :{RESET} {_fmt(ny_high - ny_low)}")
        print()

        print(f"  {BOLD}Bougies H1 NY ({len(ny_h1)}):{RESET}")
        for b in ny_h1:
            print_bar_details(b, _pt(b["time"]))

        # Analyse NY
        print()
        print(f"  {BOLD}Analyse NY :{RESET}")

        # London sweep
        london_high_val = max(b["high"] for b in london_h1) if london_h1 else None
        london_low_val = min(b["low"] for b in london_h1) if london_h1 else None

        if london_high_val and ny_low < london_high_val * 0.999:
            print(f"    {GREEN}NY a sweepé le London High → continuation haussière{RESET}")
        if london_low_val and ny_high > london_low_val * 1.001:
            print(f"    {RED}NY a sweepé le London Low → continuation baissière{RESET}")

        # NY vs Asian
        if ny_low < al:
            print(f"    {RED}NY a cassé l'Asian Low ({_fmt(al)}) → liquidity grab + possible reversal up{RESET}")
        if ny_high > ah:
            print(f"    {GREEN}NY a cassé l'Asian High ({_fmt(ah)}) → liquidity grab + possible reversal down{RESET}")

        # Sweep dans NY
        if sweeps["ah_swept"] and sweeps["ah_swept_session"] == "New_York":
            print(f"    {RED}!! AH SWEEP pendant NY → raid stops acheteurs{RESET}")
        if sweeps["al_swept"] and sweeps["al_swept_session"] == "New_York":
            print(f"    {GREEN}!! AL SWEEP pendant NY → raid stops vendeurs{RESET}")

    else:
        print(f"  {DIM}Session NY pas encore commencée ou pas de données.{RESET}")

    print()

    # ══════════════════════════════════════════════════════════════════════════
    # NIVEAUX DAILY & WEEKLY
    # ══════════════════════════════════════════════════════════════════════════
    print(f"{BOLD}{CYAN} ═══ NIVEAUX STRUCTURELS (PDH/PDL, PWH/PWL) ═══ {RESET}")
    print()

    daily = detect_daily_levels(h1_bars)
    if daily:
        pdh = daily["pdh"]
        pdl = daily["pdl"]
        print(f"  {BOLD}PDH ({daily['date']})  :{RESET} {_fmt(pdh)} "
              f"{f'{RED}SWEPT{RESET}' if daily['pdh_swept'] else f'{DIM}intact{RESET}'}")
        print(f"  {BOLD}PDL ({daily['date']})  :{RESET} {_fmt(pdl)} "
              f"{f'{GREEN}SWEPT{RESET}' if daily['pdl_swept'] else f'{DIM}intact{RESET}'}")

        # Prix vs PDH/PDL
        if current_bid > pdh:
            print(f"    {GREEN}→ Prix au-dessus du PDH → bull bias daily{RESET}")
        elif current_bid < pdl:
            print(f"    {RED}→ Prix sous le PDL → bear bias daily{RESET}")
        else:
            mid_daily = (pdh + pdl) / 2
            if current_bid > mid_daily:
                print(f"    {GREEN}→ Prix > midpoint daily → légèrement haussier{RESET}")
            else:
                print(f"    {RED}→ Prix < midpoint daily → légèrement baissier{RESET}")

    weekly = detect_weekly_levels(h1_bars)
    if weekly:
        pwh = weekly["pwh"]
        pwl = weekly["pwl"]
        print(f"  {BOLD}PWH ({weekly['week']})   :{RESET} {_fmt(pwh)} "
              f"{f'{RED}SWEPT{RESET}' if weekly['pwh_swept'] else f'{DIM}intact{RESET}'}")
        print(f"  {BOLD}PWL ({weekly['week']})   :{RESET} {_fmt(pwl)} "
              f"{f'{GREEN}SWEPT{RESET}' if weekly['pwl_swept'] else f'{DIM}intact{RESET}'}")

        if current_bid > pwh:
            print(f"    {GREEN}→ Prix au-dessus du PWH → bull bias weekly fort{RESET}")
        elif current_bid < pwl:
            print(f"    {RED}→ Prix sous le PWL → bear bias weekly fort{RESET}")
        else:
            mid_weekly = (pwh + pwl) / 2
            if current_bid > mid_weekly:
                print(f"    {GREEN}→ Prix > midpoint weekly → haussier{RESET}")
            else:
                print(f"    {RED}→ Prix < midpoint weekly → baissier{RESET}")

    print()

    # ══════════════════════════════════════════════════════════════════════════
    # FIBONACCI
    # ══════════════════════════════════════════════════════════════════════════
    print(f"{BOLD}{MAGENTA} ═══ EXTENSIONS FIBONACCI (sur range Asian) ═══ {RESET}")
    print()

    fib = detect_fib_levels(asian_range, sweeps, current_bid)
    range_pct = range_size / current_bid * 100

    print(f"  {BOLD}Range Asian :{RESET} {_fmt(range_size)} ({range_pct:.3f}% du spot)")
    print()

    # Bulls
    print(f"  {GREEN}Extensions haussières (si AL sweep → cibles au-dessus) :{RESET}")
    for n in [1.618, 2.0, 2.618, 3.0, 3.618, 4.0]:
        lvl = fib["levels"][f"+{n}"]
        reached = " ✓ dépassé" if current_bid > lvl else ""
        print(f"    +{n:<7} {_fmt(lvl):>10}{reached}")

    # Bears
    print(f"  {RED}Extensions baissières (si AH sweep → cibles en-dessous) :{RESET}")
    for n in [-1.618, -2.0, -2.618, -3.0, -3.618, -4.0]:
        lvl = fib["levels"][f"{n}"]
        reached = " ✓ dépassé" if current_bid < lvl else ""
        print(f"    {n:<7} {_fmt(lvl):>10}{reached}")

    if fib["target"]:
        print(f"\n  {BOLD}Prochaine cible Fib :{RESET} {YELLOW}{fib['target']}{RESET}")

    print()

    # ══════════════════════════════════════════════════════════════════════════
    # SYNTHÈSE ICT/SMC
    # ══════════════════════════════════════════════════════════════════════════
    print(f"{BOLD}{WHITE}{'═'*80}{RESET}")
    print(f"{BOLD}{WHITE}  ANALYSE ICT/SMC — {SYMBOL}{RESET}")
    print(f"{BOLD}{WHITE}{'═'*80}{RESET}")
    print()

    direction = analyze_direction(asian_range, sweeps, current_bid)
    trade = compute_trade_idea(asian_range, sweeps, fib, current_bid)

    print(f"  {BOLD}Prix actuel (Bid) :{RESET} {_fmt(current_bid)}")
    print(f"  {BOLD}Biais directionnel :{RESET} ", end="")
    if "BULL" in direction:
        print(f"{GREEN}{direction}{RESET}")
    elif "BEAR" in direction:
        print(f"{RED}{direction}{RESET}")
    else:
        print(f"{YELLOW}{direction}{RESET}")

    print()
    print(f"  {BOLD}Analyse narrative :{RESET}")
    print(f"  ──────────────────────────────────────────────────────")

    # Narratif ICT
    narratives = []
    ah = asian_range["ah"]
    al = asian_range["al"]

    # 1. Range asiatique
    narratives.append(f"• La session asiatique a formé un range entre "
                      f"{_fmt(al)} et {_fmt(ah)} (range = {_fmt(range_size)}, "
                      f"{range_pct:.2f}% du spot).")

    # 2. Sweeps
    if sweeps["ah_swept"] and sweeps["al_swept"]:
        narratives.append(f"• Les DEUX extrémités ont été sweepées — c'est un "
                          f"scénario de range invalidation. Le marché a pris "
                          f"la liquidité des deux côtés et a défini des ranges "
                          f"d'expansion plus larges.")
    elif sweeps["ah_swept"]:
        narratives.append(f"• L'Asian High ({_fmt(ah)}) a été sweepé en session "
                          f"{sweeps['ah_swept_session']} → raid des stops acheteurs "
                          f"(BSL). Selon la logique ICT, on attend un reversal DOWN "
                          f"vers l'autre liquidité (AL).")
    elif sweeps["al_swept"]:
        narratives.append(f"• L'Asian Low ({_fmt(al)}) a été sweepé en session "
                          f"{sweeps['al_swept_session']} → raid des stops vendeurs "
                          f"(SSL). Selon la logique ICT, on attend un reversal UP "
                          f"vers l'autre liquidité (AH).")
    else:
        narratives.append(f"• Aucun sweep du range asiatique — le range est "
                          f"toujours intact. Le prix évolue entre AH et AL.")

    # 3. Position vs midpoint
    if current_bid > ah:
        narratives.append(f"• Le prix est AU-DESSUS de l'Asian High ({_fmt(ah)}) "
                          f"— cassure haussière confirmée.")
    elif current_bid < al:
        narratives.append(f"• Le prix est EN-DESSOUS de l'Asian Low ({_fmt(al)}) "
                          f"— cassure baissière confirmée.")
    elif current_bid > mid:
        narratives.append(f"• Le prix est au-dessus du midpoint ({_fmt(mid)}) "
                          f"— légèrement haussier mais toujours dans le range.")
    else:
        narratives.append(f"• Le prix est sous le midpoint ({_fmt(mid)}) "
                          f"— légèrement baissier mais toujours dans le range.")

    # 4. Sessions
    if london_h1:
        london_high = max(b["high"] for b in london_h1)
        london_low = min(b["low"] for b in london_h1)
        london_range = london_high - london_low
        london_dir = "HAUSSIER" if london_h1[-1]["close"] > london_h1[0]["open"] else "BAISSIER"
        narratives.append(f"• London a été {london_dir} (range {_fmt(london_range)}). "
                          f"Open={_fmt(london_h1[0]['open'])}, "
                          f"Close={_fmt(london_h1[-1]['close'])}.")

        # London vs Asian
        if london_high > ah:
            narratives.append(f"• London a CASSÉ l'Asian High → le marché a cherché "
                              f"la liquidité au-dessus avant de potentiellement "
                              f"revenir (liquidity grab).")
        if london_low < al:
            narratives.append(f"• London a CASSÉ l'Asian Low → le marché a cherché "
                              f"la liquidité en-dessous (SSL grab).")

    if ny_h1:
        ny_high = max(b["high"] for b in ny_h1)
        ny_low = min(b["low"] for b in ny_h1)
        ny_range = ny_high - ny_low
        ny_dir = "HAUSSIER" if ny_h1[-1]["close"] > ny_h1[0]["open"] else "BAISSIER"
        narratives.append(f"• New York a été {ny_dir} (range {_fmt(ny_range)}). "
                          f"Open={_fmt(ny_h1[0]['open'])}, "
                          f"Close={_fmt(ny_h1[-1]['close'])}.")

        if london_h1:
            london_high_val = max(b["high"] for b in london_h1)
            london_low_val = min(b["low"] for b in london_h1)
            if ny_low < london_low_val:
                narratives.append(f"• NY a sweepé le London Low → prise de liquidité "
                                  f"SSL en dessous de London.")
            if ny_high > london_high_val:
                narratives.append(f"• NY a sweepé le London High → prise de liquidité "
                                  f"BSL au-dessus de London.")

    # 5. Contexte Daily/Weekly
    if daily:
        if current_bid > daily["pdh"]:
            narratives.append(f"• Contexte DAILY : prix au-dessus du PDH ({_fmt(pdh)}) → bull.")
        elif current_bid < daily["pdl"]:
            narratives.append(f"• Contexte DAILY : prix sous le PDL ({_fmt(pdl)}) → bear.")
        else:
            narratives.append(f"• Contexte DAILY : prix entre PDH ({_fmt(pdh)}) et PDL ({_fmt(pdl)}) → neutre.")

    if weekly:
        if current_bid > weekly["pwh"]:
            narratives.append(f"• Contexte WEEKLY : prix au-dessus du PWH ({_fmt(pwh)}) → bull fort.")
        elif current_bid < weekly["pwl"]:
            narratives.append(f"• Contexte WEEKLY : prix sous le PWL ({_fmt(pwl)}) → bear fort.")
        else:
            narratives.append(f"• Contexte WEEKLY : prix entre PWH ({_fmt(pwh)}) et PWL ({_fmt(pwl)}) → neutre.")

    # 6. Fib target
    if fib["target"]:
        narratives.append(f"• Cible Fibonacci ICT : {fib['target']} — prochaine "
                          f"pocket de liquidité à surveiller.")

    for n in narratives:
        print(f"  {n}")

    print()

    # Trade idea
    if trade["action"] != "-":
        action_color = GREEN if trade["action"] == "BUY" else RED
        print(f"  {BOLD}{action_color}[TRADE IDEA ICT] {trade['action']}{RESET}")
        print(f"  ──────────────────────────────────────────────────────")
        print(f"  Entry   : {_fmt(trade['entry'])}")
        print(f"  SL      : {_fmt(trade['sl'])}")
        print(f"  TP1     : {_fmt(trade['tp1'])}")
        print(f"  TP2     : {_fmt(trade['tp2'])}")
        if trade["rr"]:
            rr_color = GREEN if trade["rr"] >= 1.5 else YELLOW
            print(f"  RR      : {rr_color}{trade['rr']:.1f}x{RESET}")
        print()
        print(f"  {DIM}Logique : SL = 0.10×range past opposite side, TP1 = 1.618 fib, TP2 = 2.618 fib.{RESET}")
    else:
        print(f"  {YELLOW}[PAS DE TRADE] Aucun setup ICT valide pour le moment.{RESET}")
        if sweeps["ah_swept"] and current_bid > mid:
            print(f"  {DIM}→ AH sweepé mais le prix n'est pas encore sous le AL. Attendre.{RESET}")
        elif sweeps["al_swept"] and current_bid < mid:
            print(f"  {DIM}→ AL sweepé mais le prix n'est pas encore au-dessus du AH. Attendre.{RESET}")
        elif sweeps["ah_swept"] and sweeps["al_swept"]:
            print(f"  {DIM}→ Les deux sweepés = range invalide. Chercher les setups sur les nouveaux ranges.{RESET}")
        elif not sweeps["ah_swept"] and not sweeps["al_swept"]:
            print(f"  {DIM}→ Pas de sweep = pas de setup directionnel. Attendre la prise de liquidité.{RESET}")

    print()
    print(f"{BOLD}{WHITE}{'═'*80}{RESET}")
    print(f"{DIM}Analyse générée le {platform_now.strftime('%Y-%m-%d %H:%M')} (UTC+{PLATFORM_OFFSET})")
    print(f"Disclaimer : analyse éducative ICT — pas un conseil financier.{RESET}")
    print(f"{BOLD}{WHITE}{'═'*80}{RESET}")

    mt5.shutdown()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(f"\n\n{YELLOW}[STOP] Interrompu.{RESET}")
        sys.exit(130)
    except Exception as e:
        print(f"\n{RED}[ERREUR] {e}{RESET}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
