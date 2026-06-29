"""
backtest_live_signals.py — Backtest des signaux ICT FVG détectés en live
=========================================================================
Lit le fichier JSONL produit par live_ict_monitor(_global).py, rejoue les
barres M3 suivantes depuis MT5, et simule chaque trade pour calculer :
  - Win rate
  - R moyen par trade
  - Total R
  - Détail trade par trade

Usage :
    python backtest_live_signals.py
    python backtest_live_signals.py --jsonl new_analysis_02/live_ict_signals_global.jsonl
    python backtest_live_signals.py --jsonl new_analysis_02/live_ict_signals.jsonl --today
    python backtest_live_signals.py --jsonl ... --csv results.csv
"""

import os
import sys
import json
import argparse
from datetime import datetime, timezone
from collections import defaultdict
from typing import List, Dict, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import MetaTrader5 as mt5

# ─── Constantes ─────────────────────────────────────────────────────────────
PROJECT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_JSONL = os.path.join(PROJECT, "new_analysis_02", "live_ict_signals_global.jsonl")
UTC = timezone.utc
DEFAULT_HOURS_FORWARD = 96   # 96h de barres après le signal
BREAKEVEN_AFTER_TP1 = False  # Par défaut, pas de BE (comme le live)

# ─── ANSI ───────────────────────────────────────────────────────────────────
_IS_TTY = sys.stdout.isatty()


def _c(c):
    return c if _IS_TTY else ""


BOLD = _c("\033[1m")
DIM = _c("\033[2m")
RED = _c("\033[31m")
GREEN = _c("\033[32m")
YELLOW = _c("\033[33m")
CYAN = _c("\033[36m")
MAGENTA = _c("\033[35m")
RESET = _c("\033[0m")


def _fmt(p: Optional[float]) -> str:
    if p is None or p == 0:
        return "--"
    p_abs = abs(p)
    if p_abs >= 1000:
        return f"{p:.2f}"
    if p_abs >= 10:
        return f"{p:.4f}"
    return f"{p:.5f}"


# ═══════════════════════════════════════════════════════════════════════════════
#  LOADING
# ═══════════════════════════════════════════════════════════════════════════════


def load_signals(path: str, today_only: bool = False) -> List[dict]:
    """Charge les signaux depuis un fichier JSONL."""
    signals = []
    today_str = datetime.now(UTC).strftime("%Y-%m-%d") if today_only else ""

    if not os.path.exists(path):
        print(f"  {RED}[ERREUR] Fichier introuvable : {path}{RESET}")
        return []

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                sig = json.loads(line)
                if today_only and today_str not in sig.get("ts_utc", ""):
                    continue
                signals.append(sig)
            except json.JSONDecodeError:
                continue

    return signals


def fetch_bars_after(symbol: str, signal_ts: str, hours: int) -> List[dict]:
    """Récupère les barres M3 à partir de la date du signal.

    Utilise copy_rates_from_pos pour contourner le bug weekend,
    puis filtre pour ne garder que les barres postérieures au signal.
    """
    # ~20 barres/heure en M3 + buffer
    max_bars = hours * 20 + 200
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M3, 0, max_bars)
    if rates is None or len(rates) == 0:
        return []

    # Convertir le timestamp du signal
    try:
        sig_dt = datetime.fromisoformat(signal_ts)
        sig_ts_unix = int(sig_dt.timestamp())
    except (ValueError, TypeError):
        # Impossible de parser la date du signal → on skip
        print(f"\n  {YELLOW}[!] Date signal invalide pour {symbol}: {signal_ts} — signal ignoré{RESET}")
        return []

    bars = []
    for r in rates:
        bar_time = int(r[0])
        # Ne garder que les barres après le signal
        if bar_time > sig_ts_unix:
            bars.append({
                "time": bar_time,
                "open": float(r[1]),
                "high": float(r[2]),
                "low": float(r[3]),
                "close": float(r[4]),
            })

    return bars


# ═══════════════════════════════════════════════════════════════════════════════
#  TRADE SIMULATION
# ═══════════════════════════════════════════════════════════════════════════════


def simulate_trade(
    bars: List[dict],
    signal: dict,
) -> dict:
    """Simule un trade en forward-test sur les barres suivant le signal."""
    plan = signal.get("trade_plan", {})
    entry_price = signal.get("entry", 0)
    sl_price = plan.get("sl", 0)
    tp1_price = plan.get("tp1", 0)
    tp2_price = plan.get("tp2", 0)
    direction = signal.get("direction", "bull")

    result = {
        "status": "OPEN",
        "pnl_r": 0.0,
        "tp1_hit": False,
        "tp2_hit": False,
        "sl_hit": False,
        "breakeven_activated": False,
        "exit_time": None,
        "bars_played": len(bars),
    }

    risk = abs(entry_price - sl_price)
    if risk <= 0:
        result["status"] = "INVALID"
        result["reason"] = "risk_zero"
        return result

    if not bars:
        result["status"] = "OPEN"
        result["reason"] = "no_bars"
        return result

    current_sl = sl_price

    for bar in bars:
        if direction == "bull":
            if bar["low"] <= current_sl:
                result.update(status="LOSS", sl_hit=True,
                              exit_time=bar["time"], pnl_r=-1.0)
                break
            if not result["tp1_hit"] and bar["high"] >= tp1_price:
                result["tp1_hit"] = True
                result["exit_time"] = bar["time"]
                if BREAKEVEN_AFTER_TP1:
                    current_sl = entry_price
                    result["breakeven_activated"] = True
            if result["tp1_hit"] and bar["high"] >= tp2_price:
                r1 = (tp1_price - entry_price) / risk
                r2 = (tp2_price - entry_price) / risk
                result.update(status="WIN_FULL", tp2_hit=True,
                              exit_time=bar["time"],
                              pnl_r=0.5 * r1 + 0.5 * r2)
                break
        else:  # bear
            if bar["high"] >= current_sl:
                result.update(status="LOSS", sl_hit=True,
                              exit_time=bar["time"], pnl_r=-1.0)
                break
            if not result["tp1_hit"] and bar["low"] <= tp1_price:
                result["tp1_hit"] = True
                result["exit_time"] = bar["time"]
                if BREAKEVEN_AFTER_TP1:
                    current_sl = entry_price
                    result["breakeven_activated"] = True
            if result["tp1_hit"] and bar["low"] <= tp2_price:
                r1 = (entry_price - tp1_price) / risk
                r2 = (entry_price - tp2_price) / risk
                result.update(status="WIN_FULL", tp2_hit=True,
                              exit_time=bar["time"],
                              pnl_r=0.5 * r1 + 0.5 * r2)
                break

    if result["status"] == "OPEN":
        if result["tp1_hit"]:
            result["status"] = "WIN_PARTIAL"
            if direction == "bull":
                result["pnl_r"] = 0.5 * (tp1_price - entry_price) / risk
            else:
                result["pnl_r"] = 0.5 * (entry_price - tp1_price) / risk

    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN BACKTEST
# ═══════════════════════════════════════════════════════════════════════════════


def run_backtest(signals: List[dict], hours_forward: int) -> dict:
    """Exécute le backtest sur tous les signaux."""
    trades = []

    for i, sig in enumerate(signals):
        symbol = sig.get("symbol", "?")
        ts_utc = sig.get("ts_utc", "")

        sys.stdout.write(
            f"\r  {DIM}Simulation {i + 1}/{len(signals)} : {symbol} ...{RESET}")
        sys.stdout.flush()

        bars = fetch_bars_after(symbol, ts_utc, hours_forward)
        sim = simulate_trade(bars, sig)

        trades.append({
            "signal_ts": ts_utc,
            "symbol": symbol,
            "symbol_type": sig.get("symbol_type", "?"),
            "direction": sig.get("direction", "?"),
            "action": sig.get("action", "?"),
            "dol_label": sig.get("dol_label", "?"),
            "dol_level": sig.get("dol_level", 0),
            "entry": sig.get("entry", 0),
            "sl": sig.get("trade_plan", {}).get("sl", 0),
            "tp1": sig.get("trade_plan", {}).get("tp1", 0),
            "tp2": sig.get("trade_plan", {}).get("tp2", 0),
            "rr1": sig.get("trade_plan", {}).get("rr1", 0),
            "rr2": sig.get("trade_plan", {}).get("rr2", 0),
            "risk": sig.get("trade_plan", {}).get("risk", 0),
            "fvg_gap_pct": sig.get("fvg_gap_pct", 0),
            **sim,
        })

    print(f"\r  {' ' * 60}\r", end="")
    return _compute_stats(trades)


def _compute_stats(trades: List[dict]) -> dict:
    n = len(trades)
    wins = [t for t in trades if t["status"] in ("WIN_FULL", "WIN_PARTIAL")]
    losses = [t for t in trades if t["status"] == "LOSS"]
    opens = [t for t in trades if t["status"] == "OPEN"]
    invalids = [t for t in trades if t["status"] == "INVALID"]
    full_wins = [t for t in trades if t["status"] == "WIN_FULL"]
    partial_wins = [t for t in trades if t["status"] == "WIN_PARTIAL"]

    n_wins = len(wins)
    n_losses = len(losses)
    n_closed = n_wins + n_losses
    winrate = (n_wins / n_closed * 100) if n_closed > 0 else 0
    avg_r = (sum(t["pnl_r"] for t in trades if t["status"] not in ("OPEN", "INVALID"))
             / n_closed if n_closed > 0 else 0)
    total_r = sum(t["pnl_r"] for t in trades if t["status"] not in ("OPEN", "INVALID"))

    # Par direction
    bull = [t for t in trades if t["direction"] == "bull"]
    bear = [t for t in trades if t["direction"] == "bear"]
    bull_closed = [t for t in bull if t["status"] not in ("OPEN", "INVALID")]
    bear_closed = [t for t in bear if t["status"] not in ("OPEN", "INVALID")]
    bull_wr = (len([t for t in bull_closed if t["status"].startswith("WIN")])
               / len(bull_closed) * 100) if bull_closed else 0
    bear_wr = (len([t for t in bear_closed if t["status"].startswith("WIN")])
               / len(bear_closed) * 100) if bear_closed else 0

    # Par type de DOL
    dol_stats = defaultdict(lambda: {"wins": 0, "losses": 0})
    for t in trades:
        if t["status"] in ("OPEN", "INVALID"):
            continue
        dlabel = t.get("dol_label", "")
        if "PDH(" in dlabel:
            dol_type = "PDH"
        elif "PDL(" in dlabel:
            dol_type = "PDL"
        elif "AH(" in dlabel:
            dol_type = "AH"
        elif "AL(" in dlabel:
            dol_type = "AL"
        else:
            dol_type = "?"
        if t["status"].startswith("WIN"):
            dol_stats[dol_type]["wins"] += 1
        else:
            dol_stats[dol_type]["losses"] += 1

    return {
        "total_signals": n,
        "total_trades": n - len(invalids),
        "invalids": len(invalids),
        "wins": n_wins,
        "losses": n_losses,
        "open": len(opens),
        "full_wins": len(full_wins),
        "partial_wins": len(partial_wins),
        "winrate_pct": winrate,
        "avg_r_per_trade": avg_r,
        "total_r": total_r,
        "bull_trades": len(bull),
        "bull_winrate_pct": bull_wr,
        "bear_trades": len(bear),
        "bear_winrate_pct": bear_wr,
        "dol_stats": dict(dol_stats),
        "trades": trades,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  DISPLAY
# ═══════════════════════════════════════════════════════════════════════════════


def display_results(stats: dict, signals_file: str) -> None:
    """Affiche les résultats du backtest."""
    n = stats["total_trades"]
    if n == 0:
        print(f"\n  {YELLOW}[!] Aucun trade à analyser.{RESET}")
        return

    bar = "═" * 90
    print(f"\n{CYAN}{BOLD}{bar}{RESET}")
    print(f"{CYAN}{BOLD}  📊 BACKTEST LIVE ICT FVG — {n} trades{RESET}")
    print(f"{CYAN}{BOLD}{bar}{RESET}")

    print(f"\n  {BOLD}Source{RESET}  : {signals_file}")
    print(f"  {BOLD}Signaux{RESET} : {stats['total_signals']} "
          f"({stats['invalids']} invalides)")

    print(f"\n  {BOLD}── PIPELINE{RESET}")
    print(f"  {'Trades exécutés':20} : {stats['total_trades']}")
    print(f"  {'Ouverts (no bars)':20} : {stats['open']}")

    print(f"\n  {BOLD}── PERFORMANCE{RESET}")
    w = stats["wins"]
    l = stats["losses"]
    cl = w + l
    print(f"  {'GAGNÉS':20} : {GREEN}{w}{RESET} "
          f"({stats['full_wins']} full, {stats['partial_wins']} partial)")
    print(f"  {'PERDUS':20} : {RED}{l}{RESET}")
    wr_color = GREEN if stats['winrate_pct'] >= 50 else YELLOW
    print(f"  {'WINRATE':20} : {wr_color}{stats['winrate_pct']:.1f}%{RESET} ({w}/{cl} closed)")
    r_color = GREEN if stats['avg_r_per_trade'] >= 0 else RED
    print(f"  {'AVG R':20} : {r_color}{stats['avg_r_per_trade']:+.2f}R{RESET}")
    tr_color = GREEN if stats['total_r'] >= 0 else RED
    print(f"  {'TOTAL R':20} : {tr_color}{stats['total_r']:+.2f}R{RESET}")

    print(f"\n  {BOLD}── PAR DIRECTION{RESET}")
    print(f"  {'BUY':20} : {stats['bull_trades']} trades, "
          f"WR={stats['bull_winrate_pct']:.1f}%")
    print(f"  {'SELL':20} : {stats['bear_trades']} trades, "
          f"WR={stats['bear_winrate_pct']:.1f}%")

    # Par type de DOL
    print(f"\n  {BOLD}── PAR TYPE DE DOL{RESET}")
    dol_stats = stats.get("dol_stats", {})
    for dol_type in ["PDH", "PDL", "AH", "AL"]:
        ds = dol_stats.get(dol_type, {"wins": 0, "losses": 0})
        total = ds["wins"] + ds["losses"]
        if total > 0:
            wr = ds["wins"] / total * 100
            print(f"  {dol_type:>5} : {ds['wins']}/{total} ({wr:.0f}% WR)")

    # Détail des trades
    print(f"\n  {BOLD}── DÉTAIL DES TRADES{RESET}")
    print(f"  {'Symbole':<12} {'Action':>6} {'DOL':<22} {'Status':>12} "
          f"{'RR':>8} {'Entry':>10} {'TP1':>10} {'SL':>10}")
    print(f"  {'─' * 11} {'─' * 6} {'─' * 22} {'─' * 12} {'─' * 8} {'─' * 10} {'─' * 10} {'─' * 10}")

    for t in stats["trades"]:
        status = t["status"]
        if status == "WIN_FULL":
            s_color = GREEN
            s_label = "WIN FULL"
        elif status == "WIN_PARTIAL":
            s_color = GREEN
            s_label = "WIN PART"
        elif status == "LOSS":
            s_color = RED
            s_label = "LOSS"
        elif status == "OPEN":
            s_color = YELLOW
            s_label = "OPEN"
        else:
            s_color = DIM
            s_label = status

        be = " [BE]" if t.get("breakeven_activated") else ""
        print(
            f"  {MAGENTA}{t['symbol']:<12}{RESET} "
            f"{t['action']:>6} "
            f"{t['dol_label']:<22} "
            f"{s_color}{s_label + be:<12}{RESET} "
            f"{s_color}{t['pnl_r']:>+7.2f}R{RESET} "
            f"{_fmt(t['entry']):>10} "
            f"{GREEN}{_fmt(t['tp1']):>10}{RESET} "
            f"{RED}{_fmt(t['sl']):>10}{RESET}"
        )

    print(f"\n{CYAN}{BOLD}{bar}{RESET}\n")


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════


def main() -> int:
    parser = argparse.ArgumentParser(
        description="backtest_live_signals.py — Backtest des signaux ICT FVG du live")
    parser.add_argument("--jsonl", default=DEFAULT_JSONL,
                        help=f"Fichier JSONL des signaux (défaut: {DEFAULT_JSONL})")
    parser.add_argument("--today", action="store_true",
                        help="Backtester uniquement les signaux d'aujourd'hui")
    parser.add_argument("--hours", type=int, default=DEFAULT_HOURS_FORWARD,
                        help=f"Heures de barres après le signal (défaut: {DEFAULT_HOURS_FORWARD})")
    parser.add_argument("--csv", default=None,
                        help="Exporter les résultats en CSV")
    parser.add_argument("--json-out", default=None,
                        help="Exporter les résultats en JSON")

    args = parser.parse_args()
    hours_forward = args.hours

    jsonl_path = args.jsonl
    if not os.path.isabs(jsonl_path):
        jsonl_path = os.path.join(PROJECT, jsonl_path)

    print(f"{BOLD}{CYAN}{'═' * 90}{RESET}")
    print(f"{BOLD}{CYAN}  BACKTEST LIVE ICT FVG — Signaux détectés en live{RESET}")
    print(f"{BOLD}{CYAN}{'═' * 90}{RESET}")

    # Charger les signaux
    signals = load_signals(jsonl_path, args.today)
    if not signals:
        print(f"\n  {YELLOW}[!] Aucun signal trouvé dans : {jsonl_path}{RESET}")
        print(f"  {DIM}Lancez d'abord le live_monitor pour générer des signaux.{RESET}")
        return 1

    print(f"\n  Signaux chargés : {len(signals)}")
    print(f"  Source          : {jsonl_path}")
    if args.today:
        print(f"  Filtre          : aujourd'hui uniquement")

    # Connexion MT5
    print(f"\n  Connexion MT5...")
    if not mt5.initialize():
        print(f"  {RED}[ERREUR] MT5 : {mt5.last_error()}{RESET}")
        return 1

    ai = mt5.account_info()
    if ai:
        print(f"  Compte : {ai.login} @ {ai.server}")

    # Symboles uniques
    unique_symbols = sorted({s.get("symbol", "") for s in signals})
    print(f"  Symboles uniques : {len(unique_symbols)}")
    print(f"  Look-forward     : {hours_forward}h de barres M3\n")

    # Activer les symboles
    for sym in unique_symbols:
        info = mt5.symbol_info(sym)
        if info and not info.visible:
            mt5.symbol_select(sym, True)

    # Exécuter le backtest
    stats = run_backtest(signals, hours_forward)

    # Afficher les résultats
    display_results(stats, jsonl_path)

    # Export CSV
    if args.csv:
        csv_path = os.path.join(PROJECT, args.csv) if not os.path.isabs(args.csv) else args.csv
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write("symbol,action,direction,dol_label,entry,sl,tp1,tp2,rr1,rr2,status,pnl_r,"
                    "tp1_hit,tp2_hit,sl_hit,exit_time,bars_played\n")
            for t in stats["trades"]:
                f.write(
                    f"{t['symbol']},{t['action']},{t['direction']},{t['dol_label']},"
                    f"{t['entry']},{t['sl']},{t['tp1']},{t['tp2']},"
                    f"{t['rr1']:.2f},{t['rr2']:.2f},{t['status']},{t['pnl_r']:.4f},"
                    f"{t['tp1_hit']},{t['tp2_hit']},{t['sl_hit']},{t.get('exit_time','')},"
                    f"{t['bars_played']}\n"
                )
        print(f"  {GREEN}[OK] CSV exporté : {csv_path}{RESET}")

    # Export JSON
    if args.json_out:
        json_path = os.path.join(PROJECT, args.json_out) if not os.path.isabs(args.json_out) else args.json_out
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2, default=str)
        print(f"  {GREEN}[OK] JSON exporté : {json_path}{RESET}")

    mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
