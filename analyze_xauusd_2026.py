"""
XAUUSD 2026 ICT Pattern Analyzer + BACKTEST
============================================
Récupère l'historique M15 du XAUUSD depuis le 1er janvier 2026,
détecte les sweeps ICT, simule des trades réalistes (entrée au close
de la bougie de sweep, SL/TP basés sur la range asiatique + Fib),
et calcule le PROFIT FACTOR, win rate, drawdown, Sharpe, expectancy.
"""
import sys
import time
import math
import os
from datetime import datetime, timezone
from collections import defaultdict, Counter
from dataclasses import dataclass
from typing import List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.logger_config import setup_logging

logger = setup_logging("analyze_xauusd", level="ERROR")

import MetaTrader5 as mt5

UTC = timezone.utc

SYMBOL = "XAUUSD"
ASIAN_START_UTC = 0
ASIAN_END_UTC = 8
START_DATE = "2026-01-01"

TIMEFRAME_MAP = {
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "H1":  mt5.TIMEFRAME_H1,
}

POST_ASIAN_MAX_BARS_M15 = 500  # ~5 jours post-Asian M15

# ─── Config backtest ────────────────────────────────────────────────────────
RISK_PER_TRADE_PCT = 1.0          # % du capital risqué par trade
INITIAL_CAPITAL = 10000.0         # Capital de départ ($)
MIN_RANGE_PCT = 0.3               # Range asiatique min (% du spot) pour trader
MIN_RR = 0.5                      # RR minimum pour prendre le trade
SL_BUFFER_PCT = 0.10              # Buffer SL au-delà du côté opposé (10% range)

# ─── Helpers ────────────────────────────────────────────────────────────────

def bars_to_dicts(rates_raw) -> List[dict]:
    out = []
    for r in rates_raw:
        out.append({
            "time":  int(r[0]),
            "open":  float(r[1]),
            "high":  float(r[2]),
            "low":   float(r[3]),
            "close": float(r[4]),
        })
    return out

def utc_hour(epoch):
    return (epoch % 86400) // 3600

def utc_day(epoch):
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%d")

def is_asian(epoch):
    h = utc_hour(epoch)
    return ASIAN_START_UTC <= h < ASIAN_END_UTC

SESSION_DEFS = {
    "Asian":      (0, 8),
    "London":     (8, 13),
    "NY_Open":    (13, 16),
    "NY_PM":      (16, 21),
    "Asian_pre":  (22, 24),
}

def session_for_epoch(epoch):
    h = utc_hour(epoch)
    for key, (start, end) in SESSION_DEFS.items():
        if start <= h < end:
            return key
    return "Off"

def bar_sweeps_high(bar, level):
    return bar["high"] > level and bar["close"] < level

def bar_sweeps_low(bar, level):
    return bar["low"] < level and bar["close"] > level

# ─── Analyse journalière (détection sweep) ──────────────────────────────────

def analyze_day_for_sweep(bars, day_str, max_post_bars):
    """Détecte la range asiatique et le premier sweep AH/AL."""
    asian_bars = [b for b in bars if utc_day(b["time"]) == day_str and is_asian(b["time"])]
    if len(asian_bars) < 2:
        return None

    ah = max(b["high"] for b in asian_bars)
    al = min(b["low"] for b in asian_bars)
    last_asian_time = max(b["time"] for b in asian_bars)
    range_size = ah - al
    midpoint = (ah + al) / 2
    range_pct = (range_size / midpoint * 100) if midpoint > 0 else 0

    post_bars = [b for b in bars if b["time"] > last_asian_time]
    post_bars = post_bars[:max_post_bars]
    if not post_bars:
        return None

    ah_swept = False; al_swept = False
    ah_sweep_bar = None; al_sweep_bar = None
    ah_sweep_session = None; al_sweep_session = None

    for b in post_bars:
        if not ah_swept and bar_sweeps_high(b, ah):
            ah_swept = True
            ah_sweep_bar = b
            ah_sweep_session = session_for_epoch(b["time"])
        if not al_swept and bar_sweeps_low(b, al):
            al_swept = True
            al_sweep_bar = b
            al_sweep_session = session_for_epoch(b["time"])
        if ah_swept and al_swept:
            break

    return {
        "date": day_str,
        "wday": datetime.strptime(day_str, "%Y-%m-%d").weekday(),
        "ah": ah, "al": al,
        "range": range_size,
        "range_pct": range_pct,
        "midpoint": midpoint,
        "ah_swept": ah_swept,
        "al_swept": al_swept,
        "ah_sweep_bar": ah_sweep_bar,
        "al_sweep_bar": al_sweep_bar,
        "ah_sweep_session": ah_sweep_session,
        "al_sweep_session": al_sweep_session,
        "post_bars": post_bars,
    }

# ─── Simulation de trade ────────────────────────────────────────────────────

@dataclass
class TradeResult:
    symbol: str
    date: str
    direction: str           # "BUY" / "SELL"
    session: str             # session du sweep
    entry_price: float
    entry_time: float
    sl: float
    tp1: float
    tp2: float
    exit_price: float
    exit_time: float
    outcome: str             # "TP1", "TP2", "SL", "OPEN" (pas encore clôturé)
    pnl_r: float             # P&L en R multiples
    pnl_dollars: float
    bars_held: int
    ah: float
    al: float
    range_pct: float
    wday: int


def simulate_trade(direction, entry_bar, post_bars_after_entry, ah, al, range_size, session):
    """
    Simule un trade ICT : entre au close de la bougie de sweep,
    sort au premier hit de SL, TP1 ou TP2 sur les barres suivantes.
    Retourne un TradeResult.
    """
    entry_price = entry_bar["close"]
    entry_time = entry_bar["time"]

    if direction == "BUY":
        sl = al - SL_BUFFER_PCT * range_size
        tp1 = ah + 1.618 * range_size
        tp2 = ah + 2.618 * range_size
    else:  # SELL
        sl = ah + SL_BUFFER_PCT * range_size
        tp1 = al - 1.618 * range_size
        tp2 = al - 2.618 * range_size

    # Vérifier RR minimum
    risk = abs(entry_price - sl)
    reward1 = abs(tp1 - entry_price)
    reward2 = abs(tp2 - entry_price)
    rr1 = reward1 / risk if risk > 0 else 0
    rr2 = reward2 / risk if risk > 0 else 0

    bars_held = 0
    exit_price = entry_price
    exit_time = entry_time
    outcome = None  # None = rien touché encore

    # Passe 1 : SL et TP1 (ordre chronologique)
    for b in post_bars_after_entry:
        bars_held += 1
        if direction == "BUY":
            if b["low"] <= sl:
                exit_price = sl
                exit_time = b["time"]
                outcome = "SL"
                break
            if b["high"] >= tp1:
                exit_price = tp1
                exit_time = b["time"]
                outcome = "TP1"
                break
        else:  # SELL
            if b["high"] >= sl:
                exit_price = sl
                exit_time = b["time"]
                outcome = "SL"
                break
            if b["low"] <= tp1:
                exit_price = tp1
                exit_time = b["time"]
                outcome = "TP1"
                break

    # Si ni SL ni TP1 touché dans les barres disponibles → "OPEN"
    # (TP2 ne peut pas être atteint sans TP1, car il est plus éloigné)
    if outcome is None:
        outcome = "OPEN"

    pnl_r = 0
    if outcome == "TP1":
        pnl_r = rr1
    elif outcome == "TP2":
        pnl_r = rr2
    elif outcome == "SL":
        pnl_r = -1.0
    # OPEN → P&L 0 mais non clôturé

    return TradeResult(
        symbol=SYMBOL,
        date=datetime.fromtimestamp(entry_time, UTC).strftime("%Y-%m-%d"),
        direction=direction,
        session=session,
        entry_price=entry_price,
        entry_time=entry_time,
        sl=sl,
        tp1=tp1,
        tp2=tp2,
        exit_price=exit_price,
        exit_time=exit_time,
        outcome=outcome,
        pnl_r=pnl_r,
        pnl_dollars=0,  # rempli plus tard
        bars_held=bars_held,
        ah=ah,
        al=al,
        range_pct=(range_size / ((ah + al) / 2) * 100) if (ah + al) > 0 else 0,
        wday=datetime.fromtimestamp(entry_time, UTC).weekday(),
    )

# ─── Récupération des données ───────────────────────────────────────────────

def fetch_historical(symbol, tf_name, start_date_str):
    tf = TIMEFRAME_MAP.get(tf_name)
    if tf is None:
        return []

    start_dt = datetime.strptime(start_date_str, "%Y-%m-%d").replace(tzinfo=UTC)
    end_dt = datetime.now(UTC)
    start_epoch = int(start_dt.timestamp())
    end_epoch = int(end_dt.timestamp())

    print(f"  Chargement {tf_name} du {start_date_str} au {end_dt.strftime('%Y-%m-%d')}...")

    rates = mt5.copy_rates_range(symbol, tf, start_epoch, end_epoch)
    if rates is None or len(rates) == 0:
        # Fallback
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, 100000)
        if rates is not None and len(rates) > 0:
            bars = bars_to_dicts(rates)
            bars = [b for b in bars if b["time"] >= start_epoch]
        else:
            return []
    else:
        bars = bars_to_dicts(rates)

    print(f"  → {len(bars)} barres {tf_name}")
    return bars


# ─── STATISTIQUES DE PORTEFEUILLE ────────────────────────────────────────────

def compute_stats(trades: List[TradeResult], initial_capital: float):
    """Calcule profit factor, win rate, Sharpe, drawdown, expectancy."""
    closed = [t for t in trades if t.outcome != "OPEN"]

    n_total = len(closed)
    n_wins = sum(1 for t in closed if t.pnl_r > 0)
    n_loss = sum(1 for t in closed if t.pnl_r < 0)
    n_be = sum(1 for t in closed if t.pnl_r == 0)
    win_rate = n_wins / n_total * 100 if n_total else 0

    total_r_won = sum(t.pnl_r for t in closed if t.pnl_r > 0)
    total_r_lost = sum(abs(t.pnl_r) for t in closed if t.pnl_r < 0)

    profit_factor = total_r_won / total_r_lost if total_r_lost > 0 else float('inf')

    avg_win_r = total_r_won / n_wins if n_wins else 0
    avg_loss_r = total_r_lost / n_loss if n_loss else 0
    expectancy_r = (win_rate / 100 * avg_win_r) - ((1 - win_rate / 100) * avg_loss_r) if n_total else 0

    # Equity curve (risque 1% par trade, ou capital fixe)
    equity = initial_capital
    equity_curve = [initial_capital]
    peak = initial_capital
    max_dd_pct = 0

    for t in closed:
        # P&L en dollars basé sur le capital actuel × risque par trade
        risk_amount = equity * (RISK_PER_TRADE_PCT / 100)
        t.pnl_dollars = t.pnl_r * risk_amount
        equity += t.pnl_dollars
        equity_curve.append(equity)
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100 if peak > 0 else 0
        if dd > max_dd_pct:
            max_dd_pct = dd

    final_equity = equity_curve[-1] if equity_curve else initial_capital
    total_return_pct = (final_equity - initial_capital) / initial_capital * 100

    # Sharpe ratio (mensuel approximatif, basé sur les R par trade)
    returns_r = [t.pnl_r for t in closed]
    avg_r = sum(returns_r) / len(returns_r) if returns_r else 0
    var_r = sum((r - avg_r) ** 2 for r in returns_r) / len(returns_r) if returns_r else 0
    std_r = math.sqrt(var_r) if var_r > 0 else 0
    sharpe = (avg_r / std_r) if std_r > 0 else 0
    # Annualisé ~ √252 (1 trade/jour)
    sharpe_annual = sharpe * math.sqrt(len(closed)) if closed else 0

    # Consecutive losses
    max_cons_loss = 0; cons_loss = 0
    for t in closed:
        if t.pnl_r < 0:
            cons_loss += 1
            max_cons_loss = max(max_cons_loss, cons_loss)
        else:
            cons_loss = 0

    return {
        "n_total": n_total,
        "n_open": len(trades) - n_total,
        "n_wins": n_wins,
        "n_loss": n_loss,
        "n_be": n_be,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "avg_win_r": avg_win_r,
        "avg_loss_r": avg_loss_r,
        "expectancy_r": expectancy_r,
        "total_return_pct": total_return_pct,
        "final_equity": final_equity,
        "max_dd_pct": max_dd_pct,
        "sharpe": sharpe_annual,
        "max_cons_loss": max_cons_loss,
        "total_r_won": total_r_won,
        "total_r_lost": total_r_lost,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    print("=" * 95)
    print("  XAUUSD — BACKTEST ICT 2026 AVEC PROFIT FACTOR")
    print(f"  Date d'exécution : {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')} UTC")
    print("=" * 95)
    print()

    # ── Connexion MT5 ───────────────────────────────────────────────────
    print("[1] Connexion à MetaTrader 5...")
    if not mt5.initialize():
        print(f"[ERREUR] MT5 initialize failed: {mt5.last_error()}")
        sys.exit(1)

    ti = mt5.terminal_info()
    if ti:
        print(f"  Terminal : {ti.name} (build {ti.build})")

    info = mt5.symbol_info(SYMBOL)
    if not info:
        print(f"[ERREUR] Symbole {SYMBOL} non disponible.")
        mt5.shutdown()
        sys.exit(1)
    if not info.visible:
        mt5.symbol_select(SYMBOL, True)
    print(f"  Symbole  : {SYMBOL} | Digits={info.digits}")
    print()

    # ── Données ─────────────────────────────────────────────────────────
    print("[2] Récupération de l'historique...")
    m15_bars = fetch_historical(SYMBOL, "M15", START_DATE)
    if not m15_bars:
        print("[ERREUR] Pas de données M15.")
        mt5.shutdown()
        sys.exit(1)

    all_days = sorted(set(utc_day(b["time"]) for b in m15_bars))
    all_days = [d for d in all_days if d >= START_DATE]
    print(f"  Jours disponibles : {len(all_days)}")
    print()

    # ── Détection + Simulation ───────────────────────────────────────────
    print("[3] Détection des sweeps + simulation des trades...")

    all_trades: List[TradeResult] = []
    days_with_signal = 0
    days_filtered_range = 0
    days_filtered_rr = 0

    for d in all_days:
        sw = analyze_day_for_sweep(m15_bars, d, POST_ASIAN_MAX_BARS_M15)
        if sw is None:
            continue

        # Ne prendre que les jours avec UN SEUL côté sweepé (signal directionnel clair)
        if sw["ah_swept"] and sw["al_swept"]:
            continue  # BOTH = pas de direction claire
        if not sw["ah_swept"] and not sw["al_swept"]:
            continue  # pas de sweep

        # Filtrer range trop petite
        if sw["range_pct"] < MIN_RANGE_PCT:
            days_filtered_range += 1
            continue

        days_with_signal += 1

        # Déterminer quelle barre est la barre de sweep
        if sw["ah_swept"] and not sw["al_swept"]:
            sweep_bar = sw["ah_sweep_bar"]
            direction = "SELL"
            session = sw["ah_sweep_session"]
        else:
            sweep_bar = sw["al_sweep_bar"]
            direction = "BUY"
            session = sw["al_sweep_session"]

        # Barres après la barre de sweep
        post_entry = [b for b in sw["post_bars"] if b["time"] > sweep_bar["time"]]
        if len(post_entry) < 2:
            continue

        # Vérifier RR minimum
        risk = abs(sweep_bar["close"] - (sw["al"] - SL_BUFFER_PCT * sw["range"] if direction == "BUY" else sw["ah"] + SL_BUFFER_PCT * sw["range"]))
        reward = abs((sw["ah"] + 1.618 * sw["range"] if direction == "BUY" else sw["al"] - 1.618 * sw["range"]) - sweep_bar["close"])
        rr = reward / risk if risk > 0 else 0
        if rr < MIN_RR:
            days_filtered_rr += 1
            continue

        trade = simulate_trade(
            direction=direction,
            entry_bar=sweep_bar,
            post_bars_after_entry=post_entry,
            ah=sw["ah"],
            al=sw["al"],
            range_size=sw["range"],
            session=session,
        )
        all_trades.append(trade)

    print(f"  Signaux directionnels     : {days_with_signal}")
    print(f"  Filtrés (range < {MIN_RANGE_PCT}%)   : {days_filtered_range}")
    print(f"  Filtrés (RR < {MIN_RR})         : {days_filtered_rr}")
    print(f"  Trades simulés            : {len(all_trades)}")
    print()

    # ── Statistiques globales ────────────────────────────────────────────
    stats = compute_stats(all_trades, INITIAL_CAPITAL)

    print("=" * 95)
    print("[4] RÉSULTATS DU BACKTEST — TOUS LES TRADES")
    print("=" * 95)
    print(f"""
  ╔══════════════════════════════════════════════════╗
  ║  MÉTRIQUES DE PERFORMANCE                       ║
  ╠══════════════════════════════════════════════════╣
  ║  Capital initial       : {INITIAL_CAPITAL:>10.0f} $                 ║
  ║  Capital final         : {stats['final_equity']:>10.0f} $                 ║
  ║  Rendement total       : {stats['total_return_pct']:>+10.1f} %                 ║
  ║  Profit Factor         : {stats['profit_factor']:>10.2f}                     ║
  ║  Win Rate              : {stats['win_rate']:>10.1f} % ({stats['n_wins']}/{stats['n_total']})              ║
  ║  Avg Win (R)           : {stats['avg_win_r']:>+10.2f} R                     ║
  ║  Avg Loss (R)          : {stats['avg_loss_r']:>10.2f} R                     ║
  ║  Expectancy            : {stats['expectancy_r']:>+10.3f} R                     ║
  ║  Sharpe (annualisé)    : {stats['sharpe']:>10.2f}                       ║
  ║  Max Drawdown          : {stats['max_dd_pct']:>10.1f} %                     ║
  ║  Max Consec. Losses    : {stats['max_cons_loss']:>10}                         ║
  ║  Total R gagné         : {stats['total_r_won']:>+10.2f} R                     ║
  ║  Total R perdu         : {stats['total_r_lost']:>10.2f} R                     ║
  ║  Trades ouverts        : {stats['n_open']:>10}                         ║
  ║  Risque par trade      : {RISK_PER_TRADE_PCT:>10.1f} %                       ║
  ╚══════════════════════════════════════════════════╝
""")

    # ── Analyse par pattern (session de sweep) ───────────────────────────
    print("=" * 95)
    print("[5] BACKTEST PAR SESSION DE SWEEP")
    print("=" * 95)

    session_trades = defaultdict(list)
    for t in all_trades:
        if t.session:
            session_trades[t.session].append(t)
        else:
            session_trades["Off"].append(t)

    print(f"  {'Session':<12} {'Trades':>7} {'Win%':>7} {'PF':>7} {'AvgWin':>7} {'AvgLoss':>7} {'Expect':>7} {'TotalR':>8}")
    print(f"  {'─'*12} {'─'*7} {'─'*7} {'─'*7} {'─'*7} {'─'*7} {'─'*7} {'─'*8}")

    session_summary = []
    for sess in ["London", "NY_Open", "NY_PM", "Asian", "Asian_pre", "Off"]:
        trades = session_trades.get(sess, [])
        if not trades:
            continue
        st = compute_stats(trades, 10000)
        session_summary.append((sess, st, len(trades)))

    session_summary.sort(key=lambda x: x[1]["profit_factor"], reverse=True)

    for sess, st, n in session_summary:
        print(f"  {sess:<12} {n:>7} {st['win_rate']:>6.1f}% {st['profit_factor']:>6.2f} "
              f"{st['avg_win_r']:>+6.2f}R {st['avg_loss_r']:>6.2f}R "
              f"{st['expectancy_r']:>+6.3f}R {st['total_r_won'] - st['total_r_lost']:>+7.2f}R")

    # ── Analyse par pattern (BUY vs SELL) ────────────────────────────────
    print()
    print("=" * 95)
    print("[6] BACKTEST BUY vs SELL")
    print("=" * 95)

    for dir_label in ["BUY", "SELL"]:
        trades_dir = [t for t in all_trades if t.direction == dir_label]
        if not trades_dir:
            continue
        st = compute_stats(trades_dir, 10000)
        print(f"\n  {'─'*50}")
        print(f"  {dir_label} ({len(trades_dir)} trades)")
        print(f"  {'─'*50}")
        print(f"  Win Rate     : {st['win_rate']:.1f}% ({st['n_wins']}/{st['n_total']})")
        print(f"  Profit Factor: {st['profit_factor']:.2f}")
        print(f"  Expectancy   : {st['expectancy_r']:+.3f} R")
        print(f"  Avg Win      : {st['avg_win_r']:+.2f} R")
        print(f"  Avg Loss     : {st['avg_loss_r']:.2f} R")
        print(f"  Total R      : {st['total_r_won'] - st['total_r_lost']:+.2f} R")
        print(f"  Max DD       : {st['max_dd_pct']:.1f}%")

    # ── Analyse par jour de la semaine ───────────────────────────────────
    print()
    print("=" * 95)
    print("[7] BACKTEST PAR JOUR DE LA SEMAINE")
    print("=" * 95)

    wday_names = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"]
    wday_trades = defaultdict(list)
    for t in all_trades:
        wday_trades[t.wday].append(t)

    print(f"  {'Jour':<10} {'Trades':>7} {'Win%':>7} {'PF':>7} {'AvgWin':>7} {'AvgLoss':>7} {'Expect':>7} {'TotalR':>8}")
    print(f"  {'─'*10} {'─'*7} {'─'*7} {'─'*7} {'─'*7} {'─'*7} {'─'*7} {'─'*8}")

    for w in range(5):
        trades = wday_trades.get(w, [])
        if not trades:
            continue
        st = compute_stats(trades, 10000)
        print(f"  {wday_names[w]:<10} {len(trades):>7} {st['win_rate']:>6.1f}% {st['profit_factor']:>6.2f} "
              f"{st['avg_win_r']:>+6.2f}R {st['avg_loss_r']:>6.2f}R "
              f"{st['expectancy_r']:>+6.3f}R {st['total_r_won'] - st['total_r_lost']:>+7.2f}R")

    # ── Analyse détaillée des trades ─────────────────────────────────────
    print()
    print("=" * 95)
    print("[8] DÉTAIL DES 15 DERNIERS TRADES")
    print("=" * 95)

    print(f"  {'Date':<12} {'Dir':>5} {'Session':<10} {'Entry':>10} {'SL':>10} {'TP1':>10} {'Exit':>10} "
          f"{'Outcome':>8} {'P&L':>7} {'Bars':>5} {'Range%':>7}")
    print(f"  {'─'*12} {'─'*5} {'─'*10} {'─'*10} {'─'*10} {'─'*10} {'─'*10} {'─'*8} {'─'*7} {'─'*5} {'─'*7}")

    for t in all_trades[-15:]:
        outcome_color = "✓" if t.outcome.startswith("TP") else ("✗" if t.outcome == "SL" else "⋯")
        print(f"  {t.date:<12} {t.direction:>5} {t.session or '-':<10} "
              f"{t.entry_price:>10.2f} {t.sl:>10.2f} {t.tp1:>10.2f} {t.exit_price:>10.2f} "
              f"{outcome_color + ' ' + t.outcome:>8} {t.pnl_r:>+6.2f}R {t.bars_held:>5} {t.range_pct:>6.2f}%")

    # ── Distribution des outcomes ────────────────────────────────────────
    print()
    print("=" * 95)
    print("[9] DISTRIBUTION DES OUTCOMES")
    print("=" * 95)

    outcome_counts = Counter(t.outcome for t in all_trades)
    total = len(all_trades)
    for oc in ["TP1", "TP2", "SL", "OPEN"]:
        cnt = outcome_counts.get(oc, 0)
        bar = "█" * (cnt * 40 // total) if total else ""
        print(f"  {oc:<8} : {cnt:>3} ({cnt/total*100:>5.1f}%) {bar}")

    # ── Synthèse ────────────────────────────────────────────────────────
    print()
    print("=" * 95)
    print("[10] SYNTHÈSE — QUELLE STRATÉGIE ICT EXPLOITER SUR XAUUSD ?")
    print("=" * 95)

    best_session = sorted(session_summary, key=lambda x: x[1]["profit_factor"], reverse=True)[0] if session_summary else None

    pf_label = "🟢 EXCELLENT" if stats["profit_factor"] >= 2.0 else ("🟡 CORRECT" if stats["profit_factor"] >= 1.2 else "🔴 NÉGATIF")
    fire = "🔥" if stats["total_return_pct"] > 20 else ""

    lines = []
    lines.append(f"  📊 RÉSUMÉ DU BACKTEST ({len(all_trades)} trades, {all_days[0]} → {all_days[-1]})")
    lines.append("")
    lines.append(f"  • Profit Factor   : {stats['profit_factor']:.2f} {pf_label}")
    lines.append(f"  • Win Rate        : {stats['win_rate']:.1f}%")
    lines.append(f"  • Expectancy      : {stats['expectancy_r']:+.3f} R par trade")
    lines.append(f"  • Rendement total : {stats['total_return_pct']:+.1f}%{fire}")
    lines.append(f"  • Max Drawdown    : {stats['max_dd_pct']:.1f}%")
    lines.append(f"  • Sharpe annualisé: {stats['sharpe']:.2f}")
    lines.append("")
    lines.append("  🎯 MEILLEUR PATTERN :")
    if best_session:
        lines.append(f"  Session {best_session[0]} : PF={best_session[1]['profit_factor']:.2f}, Win%={best_session[1]['win_rate']:.1f}%")
        lines.append(f"  sur {best_session[2]} trades.")
    else:
        lines.append("  Pas assez de données.")
    lines.append("")
    lines.append("  📋 RÈGLE DE TRADING OPTIMALE :")
    lines.append("  ═══════════════════════════════════════════════════════════")
    lines.append("  1. Range asiatique UTC 00:00-08:00 → noter AH / AL")
    lines.append(f"  2. Filtrer : range > {MIN_RANGE_PCT}% du spot (~{MIN_RANGE_PCT*4500:.0f}$)")
    lines.append("  3. Attendre un SEUL sweep (pas les deux)")
    lines.append("  4. Entrer au close de la bougie de sweep")
    lines.append("  5. Direction opposée au sweep : SSL→BUY, BSL→SELL")
    lines.append(f"  6. SL : côté opposé + {SL_BUFFER_PCT*100:.0f}% de la range")
    lines.append("  7. TP1 : Fib +1.618 de la range")
    lines.append(f"  8. Risque : {RISK_PER_TRADE_PCT}% du capital par trade")
    lines.append("  ═══════════════════════════════════════════════════════════")
    if best_session:
        lines.append(f"  ✅ Stratégie à privilégier : sweeps en session {best_session[0]}")
        lines.append("     (meilleur profit factor)")
    print("\n".join(lines))
    print()

    # Cleanup
    mt5.shutdown()
    print("[OK] Backtest terminé.")
