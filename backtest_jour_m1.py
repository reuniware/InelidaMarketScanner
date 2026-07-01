#!/usr/bin/env python
"""
backtest_jour_m1.py — Backtest UNIFIÉ du jour, granularité M1 maximale
=====================================================================
Parse TOUS les signaux du jour (live_alerts.txt + JSONL ICT FVG),
télécharge les données M1 pour chaque symbole unique depuis MT5,
et backteste chaque signal pour déterminer si TP1 ou SL a été touché.

Sources :
  1. live_alerts/{date}_*.txt  → signaux du scanner Inelida live
  2. new_analysis_02/live_ict_signals*.jsonl → signaux ICT FVG

Usage :
    python backtest_jour_m1.py
    python backtest_jour_m1.py --date 2026-06-30
    python backtest_jour_m1.py --limit 50
"""

import os
import re
import sys
import json
import time
import argparse
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from typing import List, Dict, Optional, Tuple, Set

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import MetaTrader5 as mt5

# ─── Configuration ──────────────────────────────────────────────────────────
UTC = timezone.utc
PROJECT = os.path.dirname(os.path.abspath(__file__))
LIVE_ALERTS_DIR = os.path.join(PROJECT, "live_alerts")
JSONL_DIR = os.path.join(PROJECT, "new_analysis_02")
REPORTS_DIR = os.path.join(PROJECT, "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

# ─── ANSI ───────────────────────────────────────────────────────────────────
_IS_TTY = sys.stdout.isatty()
def _c(c): return c if _IS_TTY else ""
BOLD = _c("\033[1m"); DIM = _c("\033[2m")
RED = _c("\033[31m"); GREEN = _c("\033[32m"); YELLOW = _c("\033[33m")
CYAN = _c("\033[36m"); MAGENTA = _c("\033[35m")
BG_RED = _c("\033[41m"); BG_GREEN = _c("\033[42m")
RESET = _c("\033[0m")


# ═══════════════════════════════════════════════════════════════════════════════
#  PARSING — Live Alerts (.txt)
# ═══════════════════════════════════════════════════════════════════════════════

def parse_live_alerts_txt(filepath: str, target_date: str) -> List[dict]:
    """Parse le fichier live_alerts texte et extrait tous les signaux du jour visé.

    Format attendu par bloc :
    ==========================================================================
      !!! NOUVEAU SIGNAL SELL !!!  2026-06-30 10:15:53 UTC  |  LONDON
      AAVUSD
    ==========================================================================
      ...
      [TRADE] SELL 89.3800
      Entry             : 89.3800
      SL                : 92.6600
      TP1               : 85.0496
      ...
      RR1               : 1.32x
      ...
    """
    if not os.path.exists(filepath):
        return []

    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    signals = []
    # Découper par occurrence de "!!! NOUVEAU SIGNAL" (chaque bloc = 1 signal complet)
    # On trouve toutes les positions, puis on extrait de chaque header au suivant (ou fin)
    header_positions = [m.start() for m in re.finditer(r'!!! NOUVEAU SIGNAL', content)]
    if not header_positions:
        return []

    for idx, pos in enumerate(header_positions):
        next_pos = header_positions[idx + 1] if idx + 1 < len(header_positions) else len(content)
        # Extraire du header actuel jusqu'au prochain header (ou fin de fichier)
        block = content[pos:next_pos]

        # ── Horodatage ──
        ts_match = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+UTC', block)
        if not ts_match:
            continue
        ts_str = ts_match.group(1)
        if target_date not in ts_str:
            continue

        # ── Symbole ── (3ème ligne du bloc: header → symbole)
        lines = [l.strip() for l in block.split("\n") if l.strip()]
        symbol = None
        for i, line in enumerate(lines):
            if line.startswith("!!! NOUVEAU SIGNAL") and i + 1 < len(lines):
                candidate = lines[i + 1]
                # Vérifier que c'est bien un symbole (pas une ligne ELITE ou autre)
                if (not candidate.startswith("!") and
                    not candidate.startswith("ELITE") and
                    not candidate.startswith("=") and
                    not candidate.startswith("Range") and
                    not candidate.startswith("[TRADE]") and
                    len(candidate) >= 3 and len(candidate) <= 15):
                    symbol = candidate
                break
        if not symbol:
            continue

        # ── Action ──
        action_match = re.search(r'\[TRADE\]\s+(BUY|SELL)', block)
        if not action_match:
            continue
        action = action_match.group(1)

        # ── Entry ──
        entry_match = re.search(r'Entry\s+:\s+([\d.]+)', block)
        entry = float(entry_match.group(1)) if entry_match else None

        # ── SL ──
        sl_match = re.search(r'SL\s+:\s+([\d.]+)', block)
        sl = float(sl_match.group(1)) if sl_match else None

        # ── TPs ──
        tp1_match = re.search(r'TP1\s+:\s+([\d.]+)', block)
        tp1 = float(tp1_match.group(1)) if tp1_match else None

        tp2_match = re.search(r'TP2\s+:\s+([\d.]+)', block)
        tp2 = float(tp2_match.group(1)) if tp2_match else None

        tp3_match = re.search(r'TP3\s+:\s+([\d.]+)', block)
        tp3 = float(tp3_match.group(1)) if tp3_match else None

        # ── RRs ──
        rr1_match = re.search(r'RR1\s+:\s+([\d.]+)x', block)
        rr1 = float(rr1_match.group(1)) if rr1_match else None

        rr2_match = re.search(r'RR2\s+:\s+([\d.]+)x', block)
        rr2 = float(rr2_match.group(1)) if rr2_match else None

        # ── Prix actuel ──
        px_match = re.search(r'Prix actuel\s+:\s+([\d.]+)', block)
        current_price = float(px_match.group(1)) if px_match else None

        # ── Session / Elite badge ──
        session_match = re.search(r'Session\s+:\s+(\w+)', block)
        session = session_match.group(1) if session_match else "?"

        elite_badges = []
        if "ELITE V1" in block:
            elite_badges.append("ELITE_V1")
        if "ELITE V2" in block:
            elite_badges.append("ELITE_V2")

        if entry and sl and tp1 and action:
            try:
                sig_dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                sig_epoch = int(sig_dt.replace(tzinfo=UTC).timestamp())
            except ValueError:
                sig_epoch = 0

            signals.append({
                "source": "live_alerts",
                "file": os.path.basename(filepath),
                "ts_utc": ts_str,
                "epoch": sig_epoch,
                "symbol": symbol,
                "action": action,
                "entry": entry,
                "sl": sl,
                "tp1": tp1,
                "tp2": tp2,
                "tp3": tp3,
                "rr1": rr1,
                "rr2": rr2,
                "current_price": current_price,
                "session": session,
                "elite": elite_badges,
            })

    return signals


# ═══════════════════════════════════════════════════════════════════════════════
#  PARSING — JSONL ICT FVG
# ═══════════════════════════════════════════════════════════════════════════════

def parse_jsonl_signals(filepath: str, target_date: str) -> List[dict]:
    """Parse un fichier JSONL de signaux ICT FVG pour le jour visé."""
    if not os.path.exists(filepath):
        return []

    signals = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                sig = json.loads(line)
                ts = sig.get("ts_utc", "")
                if target_date not in ts:
                    continue

                plan = sig.get("trade_plan", {})
                entry = sig.get("entry")
                sl = plan.get("sl")
                tp1 = plan.get("tp1")
                tp2 = plan.get("tp2")
                rr1 = plan.get("rr1")
                rr2 = plan.get("rr2")
                action = sig.get("action", "?")

                if not all([entry, sl, tp1, action]):
                    continue

                try:
                    sig_dt = datetime.fromisoformat(ts)
                    sig_epoch = int(sig_dt.timestamp())
                except (ValueError, TypeError):
                    sig_epoch = 0

                signals.append({
                    "source": "ict_fvg_jsonl",
                    "file": os.path.basename(filepath),
                    "ts_utc": ts,
                    "epoch": sig_epoch,
                    "symbol": sig.get("symbol", "?"),
                    "action": action,
                    "entry": entry,
                    "sl": sl,
                    "tp1": tp1,
                    "tp2": tp2,
                    "tp3": None,
                    "rr1": rr1,
                    "rr2": rr2,
                    "current_price": sig.get("current_bid"),
                    "session": "?",
                    "elite": [],
                    "dol_label": sig.get("dol_label", ""),
                    "fvg_gap_pct": sig.get("fvg_gap_pct", 0),
                })
            except (json.JSONDecodeError, KeyError):
                continue

    return signals


# ═══════════════════════════════════════════════════════════════════════════════
#  DÉDUPLICATION
# ═══════════════════════════════════════════════════════════════════════════════

def deduplicate_signals(signals: List[dict]) -> List[dict]:
    """Déduplique les signaux similaires (même symbole, même direction, entrée proche).

    Pour les signaux live_alerts, il y a des rafraîchissements toutes les ~30s
    avec des entrées légèrement différentes. On garde le premier signal par
    (symbole, direction, jour).
    """
    seen: Set[str] = set()
    unique = []

    # Trier par timestamp croissant
    sorted_sigs = sorted(signals, key=lambda s: s.get("epoch", 0))

    for sig in sorted_sigs:
        sym = sig["symbol"]
        action = sig["action"]
        ts = sig.get("ts_utc", "")[:10]  # date seulement

        # Pour les signaux ICT FVG, clé plus fine (inclut le label DOL)
        if sig["source"] == "ict_fvg_jsonl":
            key = f"{sym}_{action}_{sig.get('dol_label', '')}_{ts}"
        else:
            # Pour live_alerts, clé par symbole + direction + jour
            key = f"{sym}_{action}_{ts}"

        if key not in seen:
            seen.add(key)
            unique.append(sig)

    return unique


# ═══════════════════════════════════════════════════════════════════════════════
#  TÉLÉCHARGEMENT M1
# ═══════════════════════════════════════════════════════════════════════════════

def download_m1(symbol: str, start_dt: datetime, end_dt: datetime) -> List[dict]:
    """Télécharge les barres M1 pour un symbole entre deux dates.

    Utilise copy_rates_from_pos (fiable, indifférent au fuseau horaire du serveur)
    plutôt que copy_rates_range qui interprète les datetimes UTC comme heure serveur
    (ex: GMT+3 → décalage de 3h, données du mauvais jour).

    On récupère assez de barres (~2 jours en M1 = 2880) puis on filtre par timestamp.
    """
    # 5000 barres M1 = ~3.5 jours, large marge pour couvrir tout le jour + buffer
    max_bars = 5000
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, max_bars)
    if rates is None:
        return []

    try:
        n_rates = len(rates)
    except Exception:
        return []

    if n_rates == 0:
        return []

    start_ts = start_dt.timestamp()
    end_ts = end_dt.timestamp()

    all_bars = []
    for r in rates:
        t = int(r[0])
        if start_ts <= t <= end_ts:
            all_bars.append({
                "time": t,
                "open": float(r[1]),
                "high": float(r[2]),
                "low": float(r[3]),
                "close": float(r[4]),
            })

    all_bars.sort(key=lambda b: b["time"])
    return all_bars


# ═══════════════════════════════════════════════════════════════════════════════
#  BACKTEST
# ═══════════════════════════════════════════════════════════════════════════════

def backtest_on_bars(signal: dict, bars: List[dict]) -> dict:
    """Backteste un signal sur les barres M1 fournies.

    Retourne un dict avec outcome, exit_time, exit_price, bars_played, etc.
    """
    entry = signal["entry"]
    sl = signal["sl"]
    tp1 = signal["tp1"]
    action = signal["action"]
    is_buy = action == "BUY"
    sig_epoch = signal.get("epoch", 0)

    result = {
        "outcome": "INDETERMINE",
        "detail": "",
        "exit_time": None,
        "exit_price": None,
        "bars_played": 0,
        "first_bar_time": None,
        "last_bar_time": None,
        "last_close": None,
    }

    if not bars:
        result["detail"] = "Pas de barres M1"
        return result

    # Filtrer les barres APRES le signal uniquement
    post_bars = [b for b in bars if b["time"] > sig_epoch]
    if not post_bars:
        result["detail"] = "Signal après la dernière barre disponible"
        return result

    result["bars_played"] = len(post_bars)
    if post_bars:
        result["first_bar_time"] = post_bars[0]["time"]
        result["last_bar_time"] = post_bars[-1]["time"]
        result["last_close"] = post_bars[-1]["close"]

    for b in post_bars:
        if is_buy:
            if b["low"] <= sl:
                result["outcome"] = "PERDU"
                result["detail"] = "SL touché"
                result["exit_time"] = b["time"]
                result["exit_price"] = sl
                return result
            if b["high"] >= tp1:
                result["outcome"] = "GAGNE"
                result["detail"] = "TP1 touché"
                result["exit_time"] = b["time"]
                result["exit_price"] = tp1
                return result
        else:  # SELL
            if b["high"] >= sl:
                result["outcome"] = "PERDU"
                result["detail"] = "SL touché"
                result["exit_time"] = b["time"]
                result["exit_price"] = sl
                return result
            if b["low"] <= tp1:
                result["outcome"] = "GAGNE"
                result["detail"] = "TP1 touché"
                result["exit_time"] = b["time"]
                result["exit_price"] = tp1
                return result

    # Ni SL ni TP touché → encore ouvert
    last = post_bars[-1]
    if is_buy:
        pnl_pct = (last["close"] - entry) / entry * 100
    else:
        pnl_pct = (entry - last["close"]) / entry * 100

    if pnl_pct > 0:
        result["outcome"] = "OUVERT"
        result["detail"] = f"En gain +{pnl_pct:.2f}%"
    else:
        result["outcome"] = "OUVERT"
        result["detail"] = f"En perte {pnl_pct:.2f}%"

    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  STATISTIQUES
# ═══════════════════════════════════════════════════════════════════════════════

def compute_pnl_r(signal: dict, outcome: str) -> float:
    """Calcule le P&L en R-multiples.

    Retourne 0.0 si le RR n'est pas disponible (GAGNÉ sans RR connu).
    """
    if outcome == "GAGNE":
        rr = signal.get("rr1")
        return rr if (rr and rr > 0) else 0.0
    elif outcome == "PERDU":
        return -1.0
    return 0.0


def compute_stats(trades: List[dict], label: str) -> dict:
    """Calcule les statistiques agrégées."""
    n_g = sum(1 for t in trades if t["outcome"] == "GAGNE")
    n_p = sum(1 for t in trades if t["outcome"] == "PERDU")
    n_o = sum(1 for t in trades if t["outcome"] == "OUVERT")
    n_indet = sum(1 for t in trades if t["outcome"] == "INDETERMINE")
    n_clos = n_g + n_p

    winrate = (n_g / n_clos * 100) if n_clos > 0 else 0

    total_r = sum(t.get("pnl_r", 0) for t in trades if t["outcome"] in ("GAGNE", "PERDU"))
    avg_r = total_r / n_clos if n_clos > 0 else 0

    # Par type de source
    by_source = defaultdict(lambda: {"gagnes": 0, "perdus": 0, "ouverts": 0, "pnl_r": 0.0})
    for t in trades:
        src = t.get("source", "?")
        if t["outcome"] == "GAGNE":
            by_source[src]["gagnes"] += 1
            by_source[src]["pnl_r"] += t.get("pnl_r", 0)
        elif t["outcome"] == "PERDU":
            by_source[src]["perdus"] += 1
            by_source[src]["pnl_r"] += t.get("pnl_r", 0)
        else:
            by_source[src]["ouverts"] += 1

    # Par direction
    by_dir = defaultdict(lambda: {"gagnes": 0, "perdus": 0, "ouverts": 0, "pnl_r": 0.0})
    for t in trades:
        d = t.get("action", "?")
        if t["outcome"] == "GAGNE":
            by_dir[d]["gagnes"] += 1
            by_dir[d]["pnl_r"] += t.get("pnl_r", 0)
        elif t["outcome"] == "PERDU":
            by_dir[d]["perdus"] += 1
            by_dir[d]["pnl_r"] += t.get("pnl_r", 0)
        else:
            by_dir[d]["ouverts"] += 1

    # Par symbole
    by_symbol = defaultdict(lambda: {"gagnes": 0, "perdus": 0, "ouverts": 0, "pnl_r": 0.0})
    for t in trades:
        s = t.get("symbol", "?")
        if t["outcome"] == "GAGNE":
            by_symbol[s]["gagnes"] += 1
            by_symbol[s]["pnl_r"] += t.get("pnl_r", 0)
        elif t["outcome"] == "PERDU":
            by_symbol[s]["perdus"] += 1
            by_symbol[s]["pnl_r"] += t.get("pnl_r", 0)
        else:
            by_symbol[s]["ouverts"] += 1

    return {
        "label": label,
        "total": len(trades),
        "gagnes": n_g, "perdus": n_p, "ouverts": n_o, "indetermines": n_indet,
        "winrate": round(winrate, 1),
        "pnl_total_r": round(total_r, 2),
        "pnl_avg_r": round(avg_r, 3),
        "by_source": dict(by_source),
        "by_dir": dict(by_dir),
        "by_symbol": dict(by_symbol),
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  DISPLAY
# ═══════════════════════════════════════════════════════════════════════════════

def _fmt(val, digits=None):
    if val is None:
        return "--"
    if isinstance(val, float):
        if abs(val) >= 1000:
            return f"{val:.2f}"
        if abs(val) >= 10:
            return f"{val:.4f}"
        return f"{val:.5f}"
    return str(val)


def print_results(stats: dict, trades: List[dict], date_str: str):
    """Affiche les résultats complets du backtest."""
    bar = "═" * 100
    print(f"\n{CYAN}{BOLD}{bar}{RESET}")
    print(f"{CYAN}{BOLD}  📊 BACKTEST UNIFIÉ M1 — {date_str} — {stats['total']} signaux{RESET}")
    print(f"{CYAN}{BOLD}{bar}{RESET}")

    # ── RÉSUMÉ ──
    print(f"\n  {BOLD}── RÉSUMÉ GLOBAL{RESET}")
    print(f"  {'Signaux extraits':25}: {stats['total']}")
    print(f"  {'Clôturés (TP/SL)':25}: {stats['gagnes'] + stats['perdus']}")
    print(f"  {GREEN}{'GAGNÉS':25}: {stats['gagnes']}{RESET}")
    print(f"  {RED}{'PERDUS':25}: {stats['perdus']}{RESET}")
    print(f"  {YELLOW}{'OUVERTS':25}: {stats['ouverts']}{RESET}")
    if stats['indetermines']:
        print(f"  {'INDÉTERMINÉS':25}: {stats['indetermines']}")

    n_clos = stats['gagnes'] + stats['perdus']
    wr_color = GREEN if stats['winrate'] >= 50 else YELLOW
    print(f"  {BOLD}{'WINRATE':25}: {wr_color}{stats['winrate']:.1f}%{RESET} ({stats['gagnes']}/{n_clos})")
    r_color = GREEN if stats['pnl_total_r'] >= 0 else RED
    print(f"  {BOLD}{'P&L TOTAL':25}: {r_color}{stats['pnl_total_r']:+.2f}R{RESET}")
    print(f"  {BOLD}{'P&L MOYEN/TRADE':25}: {r_color}{stats['pnl_avg_r']:+.3f}R{RESET}")

    # ── PAR SOURCE ──
    by_src = stats.get("by_source", {})
    if len(by_src) > 1:
        print(f"\n  {BOLD}── PAR SOURCE{RESET}")
        print(f"  {'Source':<25} {'Trades':>7} {'G':>4} {'P':>4} {'WR':>7} {'P&L':>9} {'P&L/T':>8}")
        print(f"  {'─' * 65}")
        for src in sorted(by_src.keys()):
            b = by_src[src]
            closed = b["gagnes"] + b["perdus"]
            wr = (b["gagnes"] / closed * 100) if closed > 0 else 0
            total = b["gagnes"] + b["perdus"] + b["ouverts"]
            avg_t = b["pnl_r"] / closed if closed > 0 else 0
            print(f"  {src:<25} {total:>7} {b['gagnes']:>4} {b['perdus']:>4} "
                  f"{wr:>6.1f}% {b['pnl_r']:>+8.2f}R {avg_t:>+7.3f}R")

    # ── PAR DIRECTION ──
    by_dir = stats.get("by_dir", {})
    if by_dir:
        print(f"\n  {BOLD}── PAR DIRECTION{RESET}")
        print(f"  {'Direction':<10} {'Trades':>7} {'G':>4} {'P':>4} {'WR':>7} {'P&L':>9} {'P&L/T':>8}")
        print(f"  {'─' * 55}")
        for d in sorted(by_dir.keys()):
            b = by_dir[d]
            closed = b["gagnes"] + b["perdus"]
            wr = (b["gagnes"] / closed * 100) if closed > 0 else 0
            total = b["gagnes"] + b["perdus"] + b["ouverts"]
            avg_t = b["pnl_r"] / closed if closed > 0 else 0
            print(f"  {d:<10} {total:>7} {b['gagnes']:>4} {b['perdus']:>4} "
                  f"{wr:>6.1f}% {b['pnl_r']:>+8.2f}R {avg_t:>+7.3f}R")

    # ── PAR SYMBOLE ──
    by_sym = stats.get("by_symbol", {})
    if len(by_sym) > 3:
        print(f"\n  {BOLD}── PAR SYMBOLE (top 20){RESET}")
        print(f"  {'Symbole':<16} {'Trades':>7} {'G':>4} {'P':>4} {'WR':>7} {'P&L':>9} {'P&L/T':>8}")
        print(f"  {'─' * 60}")
        sorted_syms = sorted(by_sym.items(),
                            key=lambda x: x[1]["gagnes"] + x[1]["perdus"],
                            reverse=True)[:20]
        for sym, b in sorted_syms:
            closed = b["gagnes"] + b["perdus"]
            wr = (b["gagnes"] / closed * 100) if closed > 0 else 0
            total = b["gagnes"] + b["perdus"] + b["ouverts"]
            avg_t = b["pnl_r"] / closed if closed > 0 else 0
            print(f"  {sym:<16} {total:>7} {b['gagnes']:>4} {b['perdus']:>4} "
                  f"{wr:>6.1f}% {b['pnl_r']:>+8.2f}R {avg_t:>+7.3f}R")

    # ── DÉTAIL DES TRADES ──
    print(f"\n  {BOLD}── DÉTAIL DES TRADES CLÔTURÉS{RESET}")
    closed_trades = [t for t in trades if t["outcome"] in ("GAGNE", "PERDU")]
    closed_trades.sort(key=lambda t: t.get("epoch", 0))

    print(f"  {'Symbole':<14} {'Action':>6} {'Source':<22} {'Entry':>12} {'SL':>12} "
          f"{'TP1':>12} {'RR1':>6} {'Outcome':>12} {'P&L':>8} {'TF'}")
    print(f"  {'─' * 13} {'─' * 6} {'─' * 22} {'─' * 12} {'─' * 12} "
          f"{'─' * 12} {'─' * 6} {'─' * 12} {'─' * 8} {'─' * 4}")

    for t in closed_trades:
        outcome = t["outcome"]
        oc = GREEN if outcome == "GAGNE" else RED
        pnl = t.get("pnl_r", 0)
        pc = GREEN if pnl >= 0 else RED

        print(f"  {MAGENTA}{t['symbol']:<14}{RESET} "
              f"{t['action']:>6} "
              f"{DIM}{t.get('source','?')[:22]:<22}{RESET} "
              f"{_fmt(t['entry']):>12} "
              f"{_fmt(t['sl']):>12} "
              f"{_fmt(t['tp1']):>12} "
              f"{t.get('rr1','-') or '-':>6} "
              f"{oc}{outcome:<12}{RESET} "
              f"{pc}{pnl:>+7.2f}R{RESET} "
              f"{t.get('tf_used','M1')}")

    # ── TRADES OUVERTS ──
    open_trades = [t for t in trades if t["outcome"] == "OUVERT"]
    if open_trades:
        print(f"\n  {BOLD}── TRADES ENCORE OUVERTS{RESET}")
        for t in open_trades:
            print(f"  {MAGENTA}{t['symbol']:<14}{RESET} {t['action']:>6} "
                  f"{DIM}{t.get('source','?')[:22]:<22}{RESET} "
                  f"{YELLOW}{t.get('detail',''):<30}{RESET}")

    print(f"\n{CYAN}{BOLD}{bar}{RESET}\n")


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Backtest UNIFIÉ du jour — M1 max granularité"
    )
    parser.add_argument("--date", default=None,
                        help="Date cible YYYY-MM-DD (défaut: aujourd'hui)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limiter le nombre de signaux (test rapide)")
    parser.add_argument("--no-download", action="store_true",
                        help="Utiliser les données M1 déjà en cache (ne pas retélécharger)")
    parser.add_argument("--elite-only", action="store_true",
                        help="Filtrer uniquement les signaux ELITE (V1 ou V2) — fenêtre 9:00-10:30 UTC")
    args = parser.parse_args()

    if args.date:
        target_date = args.date
    else:
        target_date = datetime.now(UTC).strftime("%Y-%m-%d")

    bar = "═" * 100
    print(f"\n[CYAN]{BOLD}{bar}{RESET}")
    print(f"{BOLD}{CYAN}  BACKTEST UNIFIÉ DU JOUR — M1 — {target_date}{' [ELITE ONLY]' if args.elite_only else ''}{RESET}")
    print(f"{BOLD}{CYAN}{bar}{RESET}")
    print()

    # ── 1. Collecte des signaux ──────────────────────────────────────────
    print(f"[1/5] Collecte des signaux du {target_date}...")

    all_signals = []

    # Live alerts .txt
    txt_files = sorted([
        f for f in os.listdir(LIVE_ALERTS_DIR)
        if target_date.replace("-", "") in f and f.endswith(".txt")
    ])
    for tf in txt_files:
        fp = os.path.join(LIVE_ALERTS_DIR, tf)
        sigs = parse_live_alerts_txt(fp, target_date)
        all_signals.extend(sigs)
        if sigs:
            print(f"  live_alerts/{tf:<50s} → {len(sigs):>3d} signaux")

    # JSONL ICT
    jsonl_files = [
        os.path.join(JSONL_DIR, "live_ict_signals.jsonl"),
        os.path.join(JSONL_DIR, "live_ict_signals_global.jsonl"),
    ]
    for jf in jsonl_files:
        sigs = parse_jsonl_signals(jf, target_date)
        all_signals.extend(sigs)
        if sigs:
            print(f"  {os.path.relpath(jf, PROJECT):<50s} → {len(sigs):>3d} signaux")

    if not all_signals:
        print(f"\n  {YELLOW}[!] Aucun signal trouvé pour le {target_date}.{RESET}")
        print(f"  Vérifiez que les fichiers live_alerts/{target_date.replace('-','')}_*.txt existent.")
        return 1

    print(f"\n  Total brut : {len(all_signals)} signaux")

    # Déduplication
    unique = deduplicate_signals(all_signals)
    print(f"  Après déduplication : {len(unique)} signaux uniques")

    if args.limit:
        unique = unique[:args.limit]
        print(f"  [LIMITE] {args.limit} premiers signaux uniquement.")

    # ── Filtre ELITE ──
    if args.elite_only:
        elite_signals = [s for s in unique if s.get("elite")]
        non_elite_signals = [s for s in unique if not s.get("elite")]
        print(f"  Dont ELITE (V1/V2)  : {len(elite_signals)} signaux (fenêtre 9:00-10:30 UTC)")
        print(f"  Dont NON-ELITE      : {len(non_elite_signals)} signaux")
        unique = elite_signals
        if not unique:
            print(f"\n  {YELLOW}[!] Aucun signal ELITE trouvé pour le {target_date}.{RESET}")
            return 1

    # ── 2. Connexion MT5 ────────────────────────────────────────────────
    print(f"\n[2/5] Connexion MetaTrader 5...")
    if not mt5.initialize():
        print(f"  {RED}[ERREUR] Connexion MT5 impossible.{RESET}")
        return 1

    ai = mt5.account_info()
    if ai:
        print(f"  Compte : {ai.login} @ {ai.server}")

    # ── 3. Téléchargement M1 ────────────────────────────────────────────
    unique_symbols = sorted({s["symbol"] for s in unique})
    print(f"\n[3/5] Téléchargement données M1 pour {len(unique_symbols)} symboles...")

    # Déterminer la plage de dates
    valid_epochs = [s["epoch"] for s in unique if s.get("epoch", 0) > 0]
    min_epoch = min(valid_epochs) if valid_epochs else int(
        datetime.strptime(target_date + " 00:00:00",
                         "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC).timestamp()
    )

    # Jusqu'à maintenant + 1 jour de marge
    end_dt = datetime.now(UTC) + timedelta(days=1)
    start_dt = datetime.fromtimestamp(min_epoch, tz=UTC) - timedelta(days=1)

    print(f"  Période : {start_dt.strftime('%Y-%m-%d %H:%M')} → {end_dt.strftime('%Y-%m-%d %H:%M')} UTC")
    print()

    m1_cache: Dict[str, List[dict]] = {}
    # Vérifier si un cache existe déjà
    cache_dir = os.path.join(REPORTS_DIR, "m1_cache")
    os.makedirs(cache_dir, exist_ok=True)

    for i, sym in enumerate(unique_symbols):
        cache_path = os.path.join(cache_dir, f"{sym}_m1_{target_date}.json")

        if args.no_download and os.path.exists(cache_path):
            with open(cache_path, "r") as f:
                data = json.load(f)
                m1_cache[sym] = data.get("bars", [])
            print(f"  [{i+1}/{len(unique_symbols)}] {sym:<16s} → {len(m1_cache[sym]):>6d} barres (cache)")
            continue

        # Activer le symbole
        info = mt5.symbol_info(sym)
        if info is None:
            print(f"  [{i+1}/{len(unique_symbols)}] {sym:<16s} → {RED}INDISPONIBLE{RESET}")
            m1_cache[sym] = []
            continue
        if not info.visible:
            mt5.symbol_select(sym, True)

        bars = download_m1(sym, start_dt, end_dt)
        m1_cache[sym] = bars

        # Sauvegarder en cache
        try:
            with open(cache_path, "w") as f:
                json.dump({"symbol": sym, "date": target_date,
                           "bars": bars}, f, default=str)
        except Exception:
            pass

        print(f"  [{i+1}/{len(unique_symbols)}] {sym:<16s} → {len(bars):>6d} barres M1")

    total_bars = sum(len(b) for b in m1_cache.values())
    print(f"\n  Total barres M1 téléchargées : {total_bars:,}")

    # ── 4. Backtest ─────────────────────────────────────────────────────
    print(f"\n[4/5] Backtest M1 de {len(unique)} signaux...")
    print()

    results = []
    n_won = 0
    n_lost = 0
    n_open = 0
    n_indet = 0

    for i, sig in enumerate(unique):
        sym = sig["symbol"]
        bars = m1_cache.get(sym, [])

        print(f"  [{i+1:>3d}/{len(unique)}] {sym:<14s} {sig['action']:>4s} "
              f"Entry={_fmt(sig['entry']):>12s} ... ", end="", flush=True)

        bt = backtest_on_bars(sig, bars)
        pnl_r = compute_pnl_r(sig, bt["outcome"])
        bt["pnl_r"] = pnl_r

        # Métadonnées
        bt["symbol"] = sym
        bt["action"] = sig["action"]
        bt["entry"] = sig["entry"]
        bt["sl"] = sig["sl"]
        bt["tp1"] = sig["tp1"]
        bt["tp2"] = sig.get("tp2")
        bt["rr1"] = sig.get("rr1")
        bt["rr2"] = sig.get("rr2")
        bt["source"] = sig["source"]
        bt["epoch"] = sig.get("epoch", 0)
        bt["tf_used"] = "M1"

        results.append(bt)

        if bt["outcome"] == "GAGNE":
            n_won += 1
            pnl_str = f"+{pnl_r:.2f}R" if pnl_r > 0 else "+?R"
            print(f"{GREEN}GAGNÉ! {pnl_str}{RESET}")
        elif bt["outcome"] == "PERDU":
            n_lost += 1
            print(f"{RED}PERDU! -1.00R{RESET}")
        elif bt["outcome"] == "OUVERT":
            n_open += 1
            print(f"{YELLOW}OUVERT{RESET}")
        else:
            n_indet += 1
            print(f"{DIM}INDÉT.{RESET}")

        sys.stdout.flush()

    # ── 5. Rapport ──────────────────────────────────────────────────────
    print(f"\n[5/5] Génération du rapport...")

    stats = compute_stats(results, f"Backtest M1 — {target_date}")
    # Forcer les compteurs calculés
    stats["gagnes"] = n_won
    stats["perdus"] = n_lost
    stats["ouverts"] = n_open
    stats["indetermines"] = n_indet
    if n_won + n_lost > 0:
        stats["winrate"] = round(n_won / (n_won + n_lost) * 100, 1)

    print_results(stats, results, target_date)

    # ── Comparaison ELITE vs NON-ELITE (si --elite-only) ──
    if args.elite_only and non_elite_signals:
        # Backtester aussi les non-ELITE pour comparaison
        print(f"\n  {BOLD}── COMPARAISON : BACKTEST NON-ELITE (mêmes données M1){RESET}")
        non_elite_results = []
        non_elite_won = 0
        non_elite_lost = 0
        non_elite_open = 0
        non_elite_indet = 0

        for sig in non_elite_signals:
            sym = sig["symbol"]
            bars = m1_cache.get(sym, [])
            bt = backtest_on_bars(sig, bars)
            pnl = compute_pnl_r(sig, bt["outcome"])
            bt["pnl_r"] = pnl
            bt["symbol"] = sym
            bt["action"] = sig["action"]
            bt["source"] = sig["source"]
            bt["epoch"] = sig.get("epoch", 0)
            bt["tf_used"] = "M1"
            bt["entry"] = sig["entry"]
            bt["sl"] = sig["sl"]
            bt["tp1"] = sig["tp1"]
            bt["rr1"] = sig.get("rr1")
            non_elite_results.append(bt)

            if bt["outcome"] == "GAGNE":
                non_elite_won += 1
            elif bt["outcome"] == "PERDU":
                non_elite_lost += 1
            elif bt["outcome"] == "OUVERT":
                non_elite_open += 1
            else:
                non_elite_indet += 1

        ne_closed = non_elite_won + non_elite_lost
        ne_wr = (non_elite_won / ne_closed * 100) if ne_closed > 0 else 0
        ne_total_r = sum(t.get("pnl_r", 0) for t in non_elite_results if t["outcome"] in ("GAGNE", "PERDU"))
        ne_avg_r = ne_total_r / ne_closed if ne_closed > 0 else 0

        # Tableau comparatif
        print(f"\n  {'─' * 80}")
        print(f"  {'':<20} {'ELITE':>25} {'NON-ELITE':>25}")
        print(f"  {'─' * 80}")
        print(f"  {'Signaux':<20} {len(unique):>25} {len(non_elite_signals):>25}")
        print(f"  {'Clôturés':<20} {n_won + n_lost:>25} {ne_closed:>25}")
        print(f"  {GREEN}{'GAGNÉS':<20}{RESET} {n_won:>25} {non_elite_won:>25}")
        print(f"  {RED}{'PERDUS':<20}{RESET} {n_lost:>25} {non_elite_lost:>25}")
        print(f"  {YELLOW}{'OUVERTS':<20}{RESET} {n_open:>25} {non_elite_open:>25}")

        wr_e_color = GREEN if (n_won + n_lost > 0 and n_won / (n_won + n_lost) >= 0.5) else YELLOW
        wr_ne_color = GREEN if (ne_closed > 0 and non_elite_won / ne_closed >= 0.5) else YELLOW
        print(f"  {'WINRATE':<20} {wr_e_color}{stats['winrate']:>24.1f}%{RESET} {wr_ne_color}{ne_wr:>24.1f}%{RESET}")

        r_e_color = GREEN if stats['pnl_total_r'] >= 0 else RED
        r_ne_color = GREEN if ne_total_r >= 0 else RED
        print(f"  {'P&L TOTAL':<20} {r_e_color}{stats['pnl_total_r']:>+24.2f}R{RESET} {r_ne_color}{ne_total_r:>+24.2f}R{RESET}")
        print(f"  {'P&L MOYEN':<20} {r_e_color}{stats['pnl_avg_r']:>+24.3f}R{RESET} {r_ne_color}{ne_avg_r:>+24.3f}R{RESET}")
        print(f"  {'─' * 80}")

    # Sauvegarde JSON
    output_path = os.path.join(REPORTS_DIR, f"backtest_jour_m1_{target_date}.json")
    output = {
        "meta": {
            "date": target_date,
            "total_signals_raw": len(all_signals),
            "total_signals_unique": len(unique),
            "backtested": len(results),
            "n_symbols": len(unique_symbols),
            "total_m1_bars": total_bars,
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
        },
        "stats": stats,
        "trades": results,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    print(f"  {GREEN}[OK] Rapport JSON : {output_path}{RESET}")
    print(f"  {GREEN}[OK] Cache M1     : {cache_dir}{RESET}")

    mt5.shutdown()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(f"\n{YELLOW}[STOP] Interrompu.{RESET}")
        mt5.shutdown()
        sys.exit(130)
    except Exception as e:
        print(f"\n{RED}[ERREUR] {e}{RESET}")
        import traceback
        traceback.print_exc()
        mt5.shutdown()
        sys.exit(1)
