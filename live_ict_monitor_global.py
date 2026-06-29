"""
live_ict_monitor_global.py — Surveillant live ICT FVG globalisé (tous actifs)
================================================================================
Version multi-actifs du live_ict_monitor.py. Scanne tous les symboles disponibles
chez le broker (ou un sous-ensemble) pour détecter en temps réel les setups ICT FVG.

Pour chaque symbole :
  1. DOL (Draw On Liquidity) : PDH/PDL du jour précédent + Asian High/Low
  2. Attend un raid de liquidité OPPOSÉE
  3. Détecte le 1er FVG après le raid
  4. Attend le retracement dans le FVG → ALERTE avec plan SL/TP complet

Usage :
    python live_ict_monitor_global.py
    python live_ict_monitor_global.py --scan-all
    python live_ict_monitor_global.py --symbols EURUSD GBPUSD XAUUSD
    python live_ict_monitor_global.py --market-watch --max-symbols 50
    python live_ict_monitor_global.py --filter-type FOREX,METAL --interval 60
    python live_ict_monitor_global.py --summary-interval 5

Ne trade PAS automatiquement — alerte uniquement.
Log dans new_analysis_02/live_ict_signals_global.jsonl
"""

import os
import sys
import time
import json
import argparse
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from typing import List, Dict, Optional, Tuple, Set

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import MetaTrader5 as mt5

# ─── Chemins ────────────────────────────────────────────────────────────────
PROJECT = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(PROJECT, "new_analysis_02")
os.makedirs(OUTPUT_DIR, exist_ok=True)
SIGNAL_LOG = os.path.join(OUTPUT_DIR, "live_ict_signals_global.jsonl")

# ─── Constantes ─────────────────────────────────────────────────────────────
UTC = timezone.utc
DEFAULT_INTERVAL = 60          # secondes entre chaque scan (plus long car multi-actifs)
HOURS_BACK = 48                # heures de barres M3 à garder en mémoire
LOOKBACK_RAID_BARS = 480       # barres max pour chercher un raid (48h en M3)
LOOKFORWARD_FVG_BARS = 240     # barres max après raid pour trouver un FVG
DEFAULT_MAX_SYMBOLS = 50       # limite par défaut (Market Watch)
SUMMARY_DEFAULT_INTERVAL = 5   # afficher un résumé tous les N scans

# Paramètres ajustables
FVG_MIN_SIZE_PCT = 0.02        # taille minimum du FVG en %
MIN_DOL_DISTANCE_PCT = 0.15    # distance minimum Entry→DOL en %

# ─── ANSI ───────────────────────────────────────────────────────────────────
_IS_TTY = sys.stdout.isatty()

def _c(c): return c if _IS_TTY else ""
BOLD = _c("\033[1m"); DIM = _c("\033[2m")
RED = _c("\033[31m"); GREEN = _c("\033[32m"); YELLOW = _c("\033[33m")
CYAN = _c("\033[36m"); MAGENTA = _c("\033[35m"); WHITE = _c("\033[97m")
GRAY = _c("\033[90m")
BG_RED = _c("\033[41m"); BG_GREEN = _c("\033[42m"); BG_YELLOW = _c("\033[43m")
RESET = _c("\033[0m")
BELL = "\a"


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _now_str() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S") + " UTC"


def _fmt(p: Optional[float]) -> str:
    if p is None or p == 0:
        return "--"
    p_abs = abs(p)
    if p_abs >= 1000:
        return f"{p:.2f}"
    if p_abs >= 10:
        return f"{p:.4f}"
    return f"{p:.5f}"


def _session() -> str:
    h = datetime.now(UTC).hour
    if 0 <= h < 8:   return "ASIAN"
    if 8 <= h < 13:  return "LONDON"
    if 13 <= h < 16: return "NY OPEN"
    if 16 <= h < 22: return "NY"
    return "ASIAN PRE"


def _paris_hour() -> str:
    n = datetime.now(UTC)
    h = (n.hour + 2) % 24
    return f"{h:02d}:{n.minute:02d}"


def _is_weekend_date(day_str: str) -> bool:
    """Vérifie si une date (string YYYY-MM-DD) est un samedi ou dimanche."""
    return datetime.strptime(day_str, "%Y-%m-%d").replace(tzinfo=UTC).weekday() >= 5


def _is_market_closed() -> bool:
    """Le marché forex est fermé du vendredi 22h UTC au dimanche 22h UTC."""
    now = datetime.now(UTC)
    wd = now.weekday()
    h = now.hour

    if wd == 5:                          # Samedi — toujours fermé
        return True
    if wd == 6 and h < 22:               # Dimanche avant 22h UTC — fermé
        return True
    if wd == 4 and h >= 22:              # Vendredi après 22h UTC — fermé
        return True
    return False


def _classify_symbol(sym: str) -> str:
    """Classifie un symbole par type d'instrument pour le filtrage."""
    sym_u = sym.upper()
    if sym in ('XAUUSD', 'XAGUSD', 'XAUAUD', 'XAGAUD'):
        return 'METAL'
    if sym_u.endswith('USD') and sym not in ('XAUUSD', 'XAGUSD'):
        return 'FOREX'
    if sym_u.startswith('USD'):
        return 'FOREX'
    if any(c in sym_u for c in ('EUR', 'GBP', 'CAD', 'AUD', 'NZD', 'CHF',
                                 'NOK', 'SEK', 'PLN', 'CZK', 'MXN', 'SGD', 'ZAR', 'HUF', 'JPY')):
        return 'FOREX'
    if '.cash' in sym_u or sym_u in ('DXY.cash', 'GDAXI'):
        return 'INDEX'
    if any(c in sym_u for c in ('BTC', 'ETH', 'BNB', 'SOL', 'XRP', 'ADA', 'DOT',
                                 'LINK', 'MANA', 'NEO', 'DASH', 'ETC', 'LTC', 'AVAX',
                                 'UNI', 'GRT', 'ICP', 'GALA', 'ATOM')):
        return 'CRYPTO'
    if sym_u.endswith('.c') or sym_u in ('CORN.c', 'COTTON.c', 'SUGAR.c', 'WHEAT.c',
                                          'COFFEE.c', 'COCOA.c', 'SOYBEAN.c'):
        return 'COMMODITY'
    if len(sym) <= 6 and sym.isalpha() and sym_u not in ('US30', 'NAS100', 'SPX500',
                                                           'US500', 'GER30', 'UK100',
                                                           'FRA40', 'AUS200', 'JP225',
                                                           'HK50', 'EU50'):
        return 'FOREX'
    return 'STOCK'


# ═══════════════════════════════════════════════════════════════════════════════
#  DÉCOUVERTE DES SYMBOLES
# ═══════════════════════════════════════════════════════════════════════════════

def discover_symbols(
    scan_all: bool = False,
    market_watch: bool = False,
    explicit: Optional[List[str]] = None,
    max_symbols: Optional[int] = None,
    filter_types: Optional[Set[str]] = None,
) -> List[str]:
    """Découvre la liste des symboles à scanner selon les options CLI."""
    if explicit:
        symbols = [s.strip().upper() for s in explicit if s.strip()]
    elif scan_all:
        all_syms = mt5.symbols_get()
        if not all_syms:
            return []
        symbols = sorted({s.name for s in all_syms})
    else:
        # Market Watch (visible) par défaut
        all_syms = mt5.symbols_get()
        if not all_syms:
            return []
        symbols = sorted({s.name for s in all_syms if getattr(s, "visible", False)})

    # Filtrage par type d'instrument
    if filter_types:
        symbols = [s for s in symbols if _classify_symbol(s) in filter_types]

    # Limite
    if max_symbols and len(symbols) > max_symbols:
        symbols = symbols[:max_symbols]

    return symbols


def select_symbols(symbols: List[str]) -> Tuple[List[str], int]:
    """Active les symboles dans Market Watch. Retourne (actifs, nb_échoués)."""
    ok_list = []
    failed = 0
    for sym in symbols:
        info = mt5.symbol_info(sym)
        if info is None:
            failed += 1
            continue
        if not info.visible:
            if not mt5.symbol_select(sym, True):
                failed += 1
                continue
        ok_list.append(sym)
    return ok_list, failed


# ═══════════════════════════════════════════════════════════════════════════════
#  DONNÉES MT5
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_bars(symbol: str, hours_back: int = HOURS_BACK) -> List[dict]:
    """Récupère les barres M3 récentes depuis MT5."""
    now = datetime.now(UTC)
    start = now.timestamp() - hours_back * 3600

    rates = mt5.copy_rates_from(symbol, mt5.TIMEFRAME_M3, start, 10000)
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
            "tick_volume": int(r[5]),
            "spread": int(r[6]) if len(r) > 6 else 0,
        })
    return bars


def group_by_day(bars: List[dict]) -> Dict[str, List[dict]]:
    days = defaultdict(list)
    for b in bars:
        dt = datetime.fromtimestamp(b["time"], tz=UTC)
        days[dt.strftime("%Y-%m-%d")].append(b)
    return dict(days)


def get_session_bars(bars: List[dict], start_h: int, end_h: int) -> List[dict]:
    return [b for b in bars
            if start_h <= datetime.fromtimestamp(b["time"], tz=UTC).hour < end_h]


def _previous_trading_day(day_str: str, all_days: Dict) -> Optional[str]:
    dt = datetime.strptime(day_str, "%Y-%m-%d").replace(tzinfo=UTC)
    for _ in range(5):
        dt = dt - timedelta(days=1)
        candidate = dt.strftime("%Y-%m-%d")
        if candidate in all_days and not _is_weekend_date(candidate):
            return candidate
    return None


# ═══════════════════════════════════════════════════════════════════════════════
#  ÉTAPE 1 — DOL
# ═══════════════════════════════════════════════════════════════════════════════

def compute_dol_pairs(day_str: str, all_days: Dict,
                      bars_today: List[dict]) -> List[dict]:
    """Calcule les 4 paires DOL/opposé pour un jour donné."""
    pairs = []
    prev_day = _previous_trading_day(day_str, all_days)
    prev_bars = all_days.get(prev_day) if prev_day else None

    pdh = max(b["high"] for b in prev_bars) if prev_bars else None
    pdl = min(b["low"] for b in prev_bars) if prev_bars else None

    now = datetime.now(UTC)
    asian_done = now.hour >= 8
    asian_bars = get_session_bars(bars_today, 0, 8) if asian_done else []
    ah = max(b["high"] for b in asian_bars) if len(asian_bars) >= 2 else None
    al = min(b["low"] for b in asian_bars) if len(asian_bars) >= 2 else None

    if pdh is not None and pdl is not None:
        pairs.append({"dol": pdh, "label": f"PDH({prev_day})", "dir": "bull",
                       "opposing": pdl, "opp_label": f"PDL({prev_day})",
                       "raid_type": "ssl"})
        pairs.append({"dol": pdl, "label": f"PDL({prev_day})", "dir": "bear",
                       "opposing": pdh, "opp_label": f"PDH({prev_day})",
                       "raid_type": "bsl"})

    if ah is not None and al is not None:
        pairs.append({"dol": ah, "label": f"AH({day_str})", "dir": "bull",
                       "opposing": al, "opp_label": f"AL({day_str})",
                       "raid_type": "ssl"})
        pairs.append({"dol": al, "label": f"AL({day_str})", "dir": "bear",
                       "opposing": ah, "opp_label": f"AH({day_str})",
                       "raid_type": "bsl"})

    return pairs


# ═══════════════════════════════════════════════════════════════════════════════
#  ÉTAPE 2 — RAID DE LIQUIDITÉ OPPOSÉE
# ═══════════════════════════════════════════════════════════════════════════════

def is_ssl_raid(bar: dict, level: float) -> bool:
    return bar["low"] < level and bar["close"] > level


def is_bsl_raid(bar: dict, level: float) -> bool:
    return bar["high"] > level and bar["close"] < level


def find_recent_raid(bars: List[dict], level: float,
                     raid_type: str) -> Optional[Tuple[int, dict]]:
    """Cherche le raid le plus récent (en partant de la fin)."""
    check_fn = is_ssl_raid if raid_type == "ssl" else is_bsl_raid
    search_start = max(0, len(bars) - LOOKBACK_RAID_BARS)
    for i in range(len(bars) - 1, search_start - 1, -1):
        if check_fn(bars[i], level):
            return (i, bars[i])
    return None


# ═══════════════════════════════════════════════════════════════════════════════
#  ÉTAPE 3 — FVG + RETRACEMENT
# ═══════════════════════════════════════════════════════════════════════════════

def find_fvg_at(bars: List[dict], idx: int, direction: str) -> Optional[dict]:
    if idx < 2:
        return None
    c1 = bars[idx - 2]
    c3 = bars[idx]

    if direction == "bull":
        if c1["high"] >= c3["low"]:
            return None
        gap_top, gap_bottom = c3["low"], c1["high"]
    else:
        if c1["low"] <= c3["high"]:
            return None
        gap_top, gap_bottom = c1["low"], c3["high"]

    gap_size = gap_top - gap_bottom
    if gap_bottom <= 0 or gap_size <= 0:
        return None
    gap_pct = gap_size / gap_bottom * 100
    if gap_pct < FVG_MIN_SIZE_PCT:
        return None

    return {"type": "bullish" if direction == "bull" else "bearish",
            "zone_top": gap_top, "zone_bottom": gap_bottom,
            "c1_high": c1["high"], "c1_low": c1["low"],
            "c3_high": c3["high"], "c3_low": c3["low"],
            "gap_size": gap_size, "gap_pct": gap_pct}


def scan_first_fvg(bars: List[dict], start_idx: int,
                   direction: str) -> Optional[Tuple[int, dict]]:
    end_idx = min(start_idx + LOOKFORWARD_FVG_BARS + 1, len(bars))
    for i in range(start_idx + 3, end_idx):
        fvg = find_fvg_at(bars, i, direction)
        if fvg is not None:
            return (i, fvg)
    return None


def has_price_retraced_to_entry(bid: float, ask: float, entry: float) -> bool:
    """Vérifie si le prix live a atteint le point d'entrée."""
    return bid <= entry <= ask


def compute_entry(fvg: dict) -> float:
    """Point d'entrée = milieu du FVG."""
    return (fvg["zone_top"] + fvg["zone_bottom"]) / 2


# ═══════════════════════════════════════════════════════════════════════════════
#  ÉTAPE 4 & 5 — SL & TP
# ═══════════════════════════════════════════════════════════════════════════════

def compute_trade_plan(entry: float, dol_level: float, fvg: dict,
                       direction: str) -> dict:
    """Calcule SL, TP1, TP2."""
    gap_size = fvg["gap_size"]

    if direction == "bull":
        sl = fvg["c1_low"] - gap_size * 0.2
        tp1 = entry + (dol_level - entry) * 0.5
        tp2 = dol_level - gap_size
        risk = entry - sl
    else:
        sl = fvg["c1_high"] + gap_size * 0.2
        tp1 = entry - (entry - dol_level) * 0.5
        tp2 = dol_level + gap_size
        risk = sl - entry

    rr1 = (tp1 - entry) / risk if direction == "bull" and risk > 0 else \
          (entry - tp1) / risk if risk > 0 else 0
    rr2 = (tp2 - entry) / risk if direction == "bull" and risk > 0 else \
          (entry - tp2) / risk if risk > 0 else 0

    return {"sl": sl, "tp1": tp1, "tp2": tp2, "risk": risk,
            "rr1": rr1, "rr2": rr2, "dol_distance_pct": abs(dol_level - entry) / entry * 100}


# ═══════════════════════════════════════════════════════════════════════════════
#  ALERTE & LOG
# ═══════════════════════════════════════════════════════════════════════════════

def log_signal(signal: dict):
    """Ajoute un signal au fichier JSONL."""
    try:
        with open(SIGNAL_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(signal, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def print_alert(signal: dict, no_sound: bool = False):
    """Affiche une alerte visuelle formatée."""
    if not no_sound:
        print(BELL, end="")

    bar = "=" * 74
    direction = signal["direction"]
    action_color = RED if direction == "bear" else GREEN
    action_bg = BG_RED if direction == "bear" else BG_GREEN
    action_label = "SELL" if direction == "bear" else "BUY"

    print(f"\n{action_bg}{WHITE}{BOLD}{bar}{RESET}")
    print(f"{action_bg}{WHITE}{BOLD}  !!! NOUVEAU SETUP ICT FVG — {action_label} !!!  {_now_str()}{RESET}")
    print(f"{action_bg}{WHITE}{BOLD}  {signal['symbol']}  |  {signal['dol_label']}{RESET}")
    print(f"{action_bg}{WHITE}{BOLD}{bar}{RESET}")

    print(f"\n  {BOLD}DOL (cible){RESET}    : {_fmt(signal['dol_level'])}  "
          f"({signal['dol_label']})")
    print(f"  {BOLD}Liquidité opposée{RESET}: {_fmt(signal['opposing_level'])}  "
          f"(raid {signal['raid_type'].upper()} à {signal['raid_time_str']})")
    print(f"  {BOLD}FVG{RESET}             : {signal['fvg_type']}, "
          f"gap={signal['fvg_gap_pct']:.3f}%  "
          f"(top={_fmt(signal['fvg_top'])} / bot={_fmt(signal['fvg_bottom'])})")

    plan = signal["trade_plan"]
    print(f"\n  {BOLD}{action_color}[ENTRÉE]{RESET} {_fmt(signal['entry'])}")
    print(f"  {'Entry':18}: {BOLD}{_fmt(signal['entry'])}{RESET}")
    print(f"  {'SL':18}: {RED}{_fmt(plan['sl'])}{RESET}  "
          f"({BOLD}risque={plan['risk']:.2f}{RESET})")
    print(f"  {'TP1 (50%)':18}: {GREEN}{_fmt(plan['tp1'])}{RESET}  (RR={plan['rr1']:.2f}x)")
    print(f"  {'TP2 (DOL)':18}: {GREEN}{_fmt(plan['tp2'])}{RESET}  (RR={plan['rr2']:.2f}x, "
          f"dist=DOL={plan['dol_distance_pct']:.2f}%)")

    print(f"\n  {BOLD}Session{RESET} : {_session()}  |  Paris : {_paris_hour()}")
    print(f"  {BOLD}Log{RESET}     : {SIGNAL_LOG}")
    print(f"  {BOLD}Type{RESET}    : {_classify_symbol(signal['symbol'])}")
    print(f"{action_bg}{WHITE}{BOLD}{bar}{RESET}\n")
    sys.stdout.flush()


# ═══════════════════════════════════════════════════════════════════════════════
#  SIGNAUX & RÉSUMÉ
# ═══════════════════════════════════════════════════════════════════════════════

def build_signal(symbol: str, pair: dict, raid_idx: int, raid_bar: dict,
                 fvg_idx: int, fvg: dict, bid: float, ask: float,
                 entry: float, plan: dict) -> dict:
    """Construit le dictionnaire signal complet."""
    raid_dt = datetime.fromtimestamp(raid_bar["time"], tz=UTC)

    return {
        "ts_utc": datetime.now(UTC).isoformat(),
        "symbol": symbol,
        "symbol_type": _classify_symbol(symbol),
        "direction": pair["dir"],
        "action": "SELL" if pair["dir"] == "bear" else "BUY",
        "dol_label": pair["label"],
        "dol_level": pair["dol"],
        "opposing_label": pair["opp_label"],
        "opposing_level": pair["opposing"],
        "raid_type": pair["raid_type"],
        "raid_time": raid_bar["time"],
        "raid_time_str": raid_dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "fvg_type": fvg["type"],
        "fvg_gap_pct": fvg["gap_pct"],
        "fvg_top": fvg["zone_top"],
        "fvg_bottom": fvg["zone_bottom"],
        "entry": entry,
        "trade_plan": plan,
        "current_bid": bid,
        "current_ask": ask,
    }


def print_summary_table(setups: List[dict], scan_num: int):
    """Affiche un tableau résumé de tous les setups détectés (pas seulement les alertes)."""
    if not setups:
        return

    bar = "─" * 80
    print(f"\n{CYAN}{BOLD}{'═' * 80}{RESET}")
    print(f"{CYAN}{BOLD}  📊 RÉSUMÉ — Scan #{scan_num}  |  {len(setups)} setup(s) actif(s)  |  {_now_str()}{RESET}")
    print(f"{CYAN}{BOLD}{'═' * 80}{RESET}")

    header = (
        f"  {BOLD}{'Symbole':<12} {'Type':>7} {'Action':>6}  "
        f"{'Entry':>12}  {'SL':>12}  {'TP1':>12}  {'RR1':>6}  "
        f"{'DOL':>12}  {'FVG%':>7}{RESET}"
    )
    print(header)
    print(f"  {GRAY}{bar}{RESET}")

    # Trier par RR décroissant
    sorted_setups = sorted(setups, key=lambda s: s.get("trade_plan", {}).get("rr1", 0), reverse=True)

    for s in sorted_setups:
        plan = s["trade_plan"]
        action = s["action"]
        sym_type = s.get("symbol_type", "?")
        act_color = GREEN if action == "BUY" else RED

        print(
            f"  {MAGENTA}{s['symbol']:<12}{RESET} "
            f"{CYAN}{sym_type:>7}{RESET} "
            f"{act_color}{action:>6}{RESET}  "
            f"{_fmt(s['entry']):>12}  "
            f"{RED}{_fmt(plan['sl']):>12}{RESET}  "
            f"{GREEN}{_fmt(plan['tp1']):>12}{RESET}  "
            f"{YELLOW}{plan['rr1']:>5.2f}x{RESET}  "
            f"{_fmt(s['dol_level']):>12}  "
            f"{plan.get('dol_distance_pct', 0):>6.2f}%"
        )

    print(f"  {GRAY}{bar}{RESET}")
    print(f"  {DIM}Tri par RR décroissant  |  Log: {SIGNAL_LOG}{RESET}\n")
    sys.stdout.flush()


def update_status_line(
    n_symbols: int, n_scanned: int, check_num: int,
    alerted_count: int, n_raids: int, n_fvgs: int, n_setups: int,
    elapsed: float,
):
    """Ligne de statut en bas du terminal."""
    print(
        f"  {_now_str()} | {_session()} | Paris {_paris_hour()} | "
        f"Check #{check_num} | "
        f"{n_scanned}/{n_symbols} symboles | "
        f"{elapsed:.1f}s | "
        f"Raids: {n_raids} | FVGs: {n_fvgs} | Setups: {n_setups} | "
        f"Signaux: {alerted_count} | "
        f"{DIM}Ctrl+C pour quitter{RESET}  ",
        end="\r",
    )
    sys.stdout.flush()


# ═══════════════════════════════════════════════════════════════════════════════
#  SCAN D'UN SYMBOLE
# ═══════════════════════════════════════════════════════════════════════════════

def scan_symbol(
    symbol: str,
    bars: List[dict],
    today_str: str,
    days: Dict[str, List[dict]],
    alerted: Set[str],
    fvg_min_pct: float,
    dol_min_pct: float,
) -> Tuple[List[dict], int, int, int]:
    """Scanne un symbole pour détecter les setups ICT FVG.

    Retourne (signaux, n_pairs, n_raids, n_fvgs).
    Plusieurs setups peuvent être détectés sur le même symbole (ex: PDH-bull + AH-bull).
    """
    today_bars = days.get(today_str, [])
    if not today_bars:
        return [], 0, 0, 0

    # Prix live
    tick = mt5.symbol_info_tick(symbol)
    bid, ask = (tick.bid, tick.ask) if tick else (0, 0)
    if bid == 0 and ask == 0:
        return [], 0, 0, 0

    # DOL pairs
    pairs = compute_dol_pairs(today_str, days, today_bars)
    n_pairs = len(pairs)
    n_raids = 0
    n_fvgs = 0
    signals: List[dict] = []

    for pair in pairs:
        setup_key = f"{symbol}_{pair['label']}_{pair['dir']}"

        # Déjà alerté aujourd'hui ?
        if setup_key in alerted:
            continue

        # Vérifier la direction DOL vs prix actuel
        if pair["dir"] == "bull" and pair["dol"] <= bid:
            continue
        if pair["dir"] == "bear" and pair["dol"] >= ask:
            continue

        # ÉTAPE 2 : Raid opposé
        raid = find_recent_raid(bars, pair["opposing"], pair["raid_type"])
        if raid is None:
            continue
        raid_idx, raid_bar = raid
        n_raids += 1

        # ÉTAPE 3a : FVG
        fvg_res = scan_first_fvg(bars, raid_idx, pair["dir"])
        if fvg_res is None:
            continue
        fvg_idx, fvg = fvg_res
        n_fvgs += 1

        # Filtre : raid asiatique avant 08:00 UTC ?
        if "AH(" in pair["label"] or "AL(" in pair["label"]:
            if datetime.fromtimestamp(raid_bar["time"], tz=UTC).hour < 8:
                continue

        # ÉTAPE 3b : Retracement jusqu'à l'entrée ?
        entry = compute_entry(fvg)
        if not has_price_retraced_to_entry(bid, ask, entry):
            continue

        # Vérifier distance DOL
        dol_dist = abs(pair["dol"] - entry) / entry * 100
        if dol_dist < dol_min_pct:
            continue

        # Vérifier validité SL
        plan = compute_trade_plan(entry, pair["dol"], fvg, pair["dir"])
        if pair["dir"] == "bull" and plan["sl"] >= entry:
            continue
        if pair["dir"] == "bear" and plan["sl"] <= entry:
            continue

        # SIGNAL !
        alerted.add(setup_key)
        signal = build_signal(symbol, pair, raid_idx, raid_bar,
                              fvg_idx, fvg, bid, ask, entry, plan)
        signals.append(signal)

    return signals, n_pairs, n_raids, n_fvgs


# ═══════════════════════════════════════════════════════════════════════════════
#  BOUCLE PRINCIPALE
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="live_ict_monitor_global.py — Surveillant live ICT FVG multi-actifs (alertes)")
    parser.add_argument("--symbols", nargs="*", default=None,
                        help="Liste de symboles explicites (surcharge la découverte auto).")
    parser.add_argument("--scan-all", action="store_true",
                        help="Scanner TOUS les symboles disponibles chez le broker.")
    parser.add_argument("--market-watch", action="store_true",
                        help="Scanner uniquement les symboles visibles dans Market Watch (défaut).")
    parser.add_argument("--max-symbols", type=int, default=DEFAULT_MAX_SYMBOLS,
                        help=f"Nombre maximum de symboles à scanner (défaut: {DEFAULT_MAX_SYMBOLS}). "
                             f"Utilisez 0 pour illimité avec --scan-all.")
    parser.add_argument("--filter-type", default=None,
                        help="Filtrer par type d'instrument: FOREX,METAL,INDEX,CRYPTO,STOCK,COMMODITY "
                             "(séparés par virgules).")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                        help=f"Secondes entre chaque scan (défaut: {DEFAULT_INTERVAL}).")
    parser.add_argument("--fvg-min", type=float, default=FVG_MIN_SIZE_PCT,
                        help=f"Taille minimum FVG en %% (défaut: {FVG_MIN_SIZE_PCT}).")
    parser.add_argument("--dol-min", type=float, default=MIN_DOL_DISTANCE_PCT,
                        help=f"Distance minimum Entry→DOL en %% (défaut: {MIN_DOL_DISTANCE_PCT}).")
    parser.add_argument("--summary-interval", type=int, default=SUMMARY_DEFAULT_INTERVAL,
                        help=f"Afficher un tableau résumé tous les N scans (défaut: {SUMMARY_DEFAULT_INTERVAL}). "
                             f"Mettre 0 pour désactiver.")
    parser.add_argument("--no-sound", action="store_true",
                        help="Désactiver le beep sonore.")

    args = parser.parse_args()

    # Surcharger les constantes du module
    mod = sys.modules[__name__]
    mod.FVG_MIN_SIZE_PCT = args.fvg_min
    mod.MIN_DOL_DISTANCE_PCT = args.dol_min

    interval = max(args.interval, 5)
    no_sound = args.no_sound

    # Filtrage par type
    filter_types = None
    if args.filter_type:
        filter_types = {t.strip().upper() for t in args.filter_type.split(",") if t.strip()}

    max_syms = args.max_symbols if args.max_symbols > 0 else None

    # ── Connexion MT5 ────────────────────────────────────────────────────
    print(f"{BOLD}{CYAN}{'='*74}{RESET}")
    print(f"{BOLD}{CYAN}  ICT FVG Monitor GLOBAL — Surveillance multi-actifs{RESET}")
    print(f"{BOLD}{CYAN}{'='*74}{RESET}")
    print(f"\n  Connexion MT5...")

    if not mt5.initialize():
        print(f"  {RED}[ERREUR] MT5 : {mt5.last_error()}{RESET}")
        return 1

    ai = mt5.account_info()
    if ai:
        print(f"  Compte : {ai.login} @ {ai.server}")
    else:
        print(f"  {YELLOW}[!] Pas d'info compte — MT5 connecté ?{RESET}")

    # ── Découverte des symboles ──────────────────────────────────────────
    print(f"\n  Découverte des symboles...")
    symbols = discover_symbols(
        scan_all=args.scan_all,
        market_watch=args.market_watch,
        explicit=args.symbols,
        max_symbols=max_syms,
        filter_types=filter_types,
    )

    if not symbols:
        print(f"  {RED}[ERREUR] Aucun symbole trouvé.{RESET}")
        mt5.shutdown()
        return 1

    print(f"  Symboles découverts : {len(symbols)}")
    if filter_types:
        print(f"  Filtre type         : {', '.join(sorted(filter_types))}")

    # Activer les symboles dans Market Watch
    print(f"  Activation Market Watch...")
    symbols, n_failed = select_symbols(symbols)
    if n_failed > 0:
        print(f"  {YELLOW}[!] {n_failed} symbole(s) n'ont pas pu être activés.{RESET}")
    print(f"  Symboles actifs     : {len(symbols)}")

    # Compter par type
    type_counts = defaultdict(int)
    for s in symbols:
        type_counts[_classify_symbol(s)] += 1
    type_str = "  ".join(f"{t}: {c}" for t, c in sorted(type_counts.items()))
    print(f"  Répartition         : {type_str}")

    print(f"  Intervalle          : {interval}s")
    print(f"  FVG min             : {FVG_MIN_SIZE_PCT}%")
    print(f"  DOL min             : {MIN_DOL_DISTANCE_PCT}%")
    print(f"  Résumé tous les     : {args.summary_interval} scan(s)" if args.summary_interval > 0 else "  Résumé           : désactivé")
    print(f"  Log signaux         : {SIGNAL_LOG}")
    print(f"\n  {YELLOW}Surveillance en cours... (Ctrl+C pour quitter){RESET}\n")

    # ── État ─────────────────────────────────────────────────────────────
    alerted: Set[str] = set()
    last_signals: Dict[str, dict] = {}   # setup_key -> dernier signal connu (pour le résumé)
    current_day = datetime.now(UTC).strftime("%Y-%m-%d")
    check_num = 0

    try:
        while True:
            check_num += 1
            now_dt = datetime.now(UTC)
            today_str = now_dt.strftime("%Y-%m-%d")

            # Nouveau jour → reset
            if today_str != current_day:
                print(f"\n  {CYAN}[NOUVEAU JOUR] {today_str} — reset{RESET}")
                current_day = today_str
                alerted.clear()
                last_signals.clear()

            # Skip marché fermé
            if _is_market_closed():
                print(f"  {_now_str()} | Marché fermé — en attente...", end="\r")
                sys.stdout.flush()
                time.sleep(60)
                continue

            # ── Scan de tous les symboles ───────────────────────────────
            scan_start = time.time()
            n_raids_total = 0
            n_fvgs_total = 0
            n_setups_total = 0
            n_scanned = 0
            new_signals: List[dict] = []
            pending_setups: List[dict] = []  # setups détectés mais pas encore alertés (pas de retracement)

            for sym in symbols:
                try:
                    bars = fetch_bars(sym, HOURS_BACK)
                    if len(bars) < 20:
                        continue
                    n_scanned += 1

                    days = group_by_day(bars)
                    sym_signals, n_pairs, n_raids, n_fvgs = scan_symbol(
                        sym, bars, today_str, days, alerted,
                        FVG_MIN_SIZE_PCT, MIN_DOL_DISTANCE_PCT,
                    )
                    n_raids_total += n_raids
                    n_fvgs_total += n_fvgs

                    if sym_signals:
                        new_signals.extend(sym_signals)
                        n_setups_total += len(sym_signals)

                except Exception as e:
                    # Erreur sur un symbole — on continue avec les autres
                    print(f"  {GRAY}[!] {sym}: {type(e).__name__}: {e}{RESET}")
                    sys.stdout.flush()

                # Throttle léger entre symboles pour éviter de saturer MT5
                time.sleep(0.05)

            scan_elapsed = time.time() - scan_start

            # ── Stocker les nouveaux signaux dans last_signals ──────────
            for signal in new_signals:
                # Clé = symbole_direction_dol-label (pour le résumé)
                sig_key = f"{signal['symbol']}_{signal['direction']}_{signal['dol_label']}"
                last_signals[sig_key] = signal

            # ── Afficher les nouvelles alertes ──────────────────────────
            for signal in new_signals:
                print_alert(signal, no_sound)

            # ── Tableau résumé périodique ───────────────────────────────
            if args.summary_interval > 0 and check_num % args.summary_interval == 0:
                # Afficher TOUS les setups actifs (nouveaux + déjà alertés)
                if last_signals:
                    print_summary_table(list(last_signals.values()), check_num)

            # ── Ligne de statut ─────────────────────────────────────────
            update_status_line(
                len(symbols), n_scanned, check_num,
                len(alerted), n_raids_total, n_fvgs_total,
                n_setups_total, scan_elapsed,
            )

            time.sleep(interval)

    except KeyboardInterrupt:
        print(f"\n\n  {YELLOW}[STOP] Arrêté par l'utilisateur.{RESET}")

    finally:
        n = len(alerted)
        print(f"\n  {GREEN}[OK] {n} signal(aux) unique(s) détecté(s).{RESET}")
        print(f"  {GREEN}[OK] Log : {SIGNAL_LOG}{RESET}")
        mt5.shutdown()


if __name__ == "__main__":
    sys.exit(main())
