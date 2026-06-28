"""
find_optimal_elite.py
=====================
Trouve les criteres ELITE optimaux en testant des milliers de combinaisons
de parametres (fenetre horaire, seuil RR, seuil spread, types autorises).

Utilise les resultats du backtest (backtest_all_results.json) pour evaluer
chaque combinaison sur:
  - Winrate
  - P&L moyen par trade (en R)
  - Score composite: winrate * sqrt(n_trades)
  - Nombre de trades max avec winrate >= 80%

Usage:
    python find_optimal_elite.py
"""

import os
import sys
import json
from datetime import datetime, timezone
from collections import defaultdict

RESULTS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "reports", "backtest_all_results.json"
)
OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "reports", "elite_optimization.json"
)

# Forcer UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# ==================== Classification des symboles ====================
def classify_symbol(sym: str) -> str:
    sym_u = sym.upper()
    if sym in ('XAUUSD', 'XAGUSD', 'XAUAUD', 'XAGAUD'):
        return 'METAL'
    if sym_u.endswith('USD') and sym not in ('XAUUSD', 'XAGUSD'):
        return 'FOREX_USD'
    if 'JPY' in sym_u:
        return 'FOREX_JPY'
    if sym_u.startswith('USD'):
        return 'FOREX_USD'
    if any(c in sym for c in ('EUR', 'GBP', 'CAD', 'AUD', 'NZD', 'CHF',
                                'NOK', 'SEK', 'PLN', 'CZK', 'MXN', 'SGD', 'ZAR', 'HUF')):
        return 'FOREX_CROSS'
    if '.cash' in sym or sym in ('DXY.cash', 'GDAXI'):
        return 'INDEX'
    return 'OTHER'


# ==================== Fonctions d'evaluation ====================
def passes_filter(trade: dict, params: dict) -> bool:
    """Verifie si un trade passe un jeu de criteres donne."""
    # Fenetre horaire
    hour = trade["scan_hour"]
    if hour is not None:
        window_start = params.get("window_start", 9)
        window_end = params.get("window_end", 10.5)
        if not (window_start <= hour < window_end):
            return False

    # Type d'instrument
    sym_type = trade.get("sym_type") or classify_symbol(trade["symbol"])
    allowed_types = params.get("allowed_types", {"FOREX_USD", "INDEX", "METAL", "FOREX_CROSS"})
    if sym_type not in allowed_types:
        return False

    # RR
    min_rr = params.get("min_rr", 0.5)
    if (trade["rr"] or 0) < min_rr:
        return False

    # Spread
    max_spread = params.get("max_spread_pct", 0.10)
    if trade["spread_pct"] is not None and trade["spread_pct"] >= max_spread:
        return False

    return True


def evaluate_params(trades: list, params: dict) -> dict:
    """Evalue un jeu de parametres sur la liste des trades."""
    filtered = [t for t in trades if passes_filter(t, params)]
    if not filtered:
        return {"n_trades": 0, "n_closed": 0, "winrate": 0, "avg_pnl": 0,
                "total_pnl": 0, "score": 0, "n_won": 0, "n_lost": 0}

    closed = [t for t in filtered if t["outcome"] in ("GAGNE", "PERDU")]
    n_closed = len(closed)
    if n_closed == 0:
        return {"n_trades": len(filtered), "n_closed": 0, "winrate": 0,
                "avg_pnl": 0, "total_pnl": 0, "score": 0, "n_won": 0, "n_lost": 0}

    n_won = sum(1 for t in closed if t["outcome"] == "GAGNE")
    n_lost = n_closed - n_won
    winrate = n_won / n_closed

    total_pnl = sum(t.get("pnl_pct", 0) for t in closed)
    avg_pnl = total_pnl / n_closed if n_closed > 0 else 0

    # Score composite: favorise winrate eleve + nb trades significatif
    # Formule: winrate^2 * sqrt(n_closed) * (avg_pnl + 1)
    # Cela penalise les echantillons trop petits et favorise les P&L positifs
    min_trades = 3  # au moins 3 trades pour etre valide
    if n_closed >= min_trades:
        penalty = max(1, n_closed / 10)  # proportionnel au nb de trades
        score = (winrate ** 2) * (n_closed ** 0.6) * max(0, avg_pnl + 0.5) * 100
    else:
        score = 0

    return {
        "n_trades": len(filtered),
        "n_closed": n_closed,
        "n_won": n_won,
        "n_lost": n_lost,
        "winrate": round(winrate * 100, 1),
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(avg_pnl, 3),
        "score": round(score, 1),
    }


# ==================== Recherche optimale ====================
def optimize(trades: list):
    """Teste toutes les combinaisons de parametres et retourne les meilleures."""

    # Grille de recherche
    window_starts = [7, 8, 9, 10]  # heures de debut (en UTC)
    window_lengths = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0]  # duree en heures
    min_rr_values = [0.0, 0.3, 0.5, 0.8, 1.0, 1.2]
    max_spread_values = [0.05, 0.10, 0.15, 0.20, 0.30, 0.50, None]  # None = pas de filtre
    type_combos = [
        {"FOREX_USD", "INDEX", "METAL", "FOREX_CROSS"},  # ELITE actuel
        {"FOREX_USD", "INDEX", "METAL"},                  # sans cross
        {"FOREX_USD", "INDEX", "METAL", "FOREX_CROSS", "FOREX_JPY"},  # tout forex
        {"FOREX_USD", "METAL"},                           # que USD + metaux
        {"FOREX_USD", "INDEX", "METAL", "FOREX_CROSS", "FOREX_JPY", "OTHER"},  # tous
    ]

    results = []
    n_tests = 0

    bar = "=" * 90
    print(bar)
    print("  RECHERCHE DES CRITERES ELITE OPTIMAUX")
    print(bar)
    print(f"  Trades disponibles: {len(trades)}")
    print(f"  Trades clos: {len([t for t in trades if t['outcome'] in ('GAGNE', 'PERDU')])}")
    print()

    for ws in window_starts:
        for wl in window_lengths:
            we = ws + wl
            for min_rr in min_rr_values:
                for max_spread in max_spread_values:
                    for types in type_combos:
                        params = {
                            "window_start": ws,
                            "window_end": we,
                            "min_rr": min_rr,
                            "max_spread_pct": max_spread if max_spread is not None else 999.0,
                            "allowed_types": types,
                        }
                        eval_result = evaluate_params(trades, params)
                        n_tests += 1

                        if eval_result["score"] > 0:
                            results.append({
                                "params": {
                                    "window": f"{ws:02d}:00-{int(we):02d}:{int((we%1)*60):02d} UTC",
                                    "window_start": ws,
                                    "window_end": we,
                                    "min_rr": min_rr,
                                    "max_spread_pct": max_spread,
                                    "allowed_types": sorted(types),
                                },
                                "metrics": eval_result,
                            })

    print(f"  Combinaisons testees: {n_tests}")
    print(f"  Combinaisons valides: {len(results)}")
    print()

    # Trier par score decroissant
    results.sort(key=lambda r: r["metrics"]["score"], reverse=True)

    return results


# ==================== Analyse par critere individuel ====================
def analyze_single_criteria(trades: list):
    """Analyse l'impact de chaque critere individuel."""
    analysis = {}

    # 1. Impact de la fenetre horaire
    print("  [Analyse] Impact de la fenetre horaire...")
    window_results = []
    for start_hour in range(0, 23):
        for length in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]:
            end = start_hour + length
            if end > 24:
                continue
            params = {
                "window_start": start_hour,
                "window_end": end,
                "min_rr": 0.0,
                "max_spread_pct": 999.0,
                "allowed_types": {"FOREX_USD", "INDEX", "METAL", "FOREX_CROSS",
                                  "FOREX_JPY", "OTHER"},
            }
            r = evaluate_params(trades, params)
            if r["n_closed"] >= 3 and r["winrate"] >= 60:
                window_results.append({
                    "window": f"{start_hour:02d}:00-{int(end):02d}:{int((end%1)*60):02d}",
                    "winrate": r["winrate"],
                    "n_closed": r["n_closed"],
                    "avg_pnl": r["avg_pnl"],
                })

    window_results.sort(key=lambda x: (x["winrate"], x["n_closed"]), reverse=True)
    analysis["best_windows"] = window_results[:15]

    # 2. Impact du seuil RR
    print("  [Analyse] Impact du seuil RR...")
    rr_results = []
    for min_rr in [r/10 for r in range(0, 31, 1)]:  # 0.0 a 3.0 par pas de 0.1
        params = {
            "window_start": 0, "window_end": 24,
            "min_rr": min_rr,
            "max_spread_pct": 999.0,
            "allowed_types": {"FOREX_USD", "INDEX", "METAL", "FOREX_CROSS",
                              "FOREX_JPY", "OTHER"},
        }
        r = evaluate_params(trades, params)
        rr_results.append({
            "min_rr": min_rr,
            "n_trades": r["n_trades"],
            "n_closed": r["n_closed"],
            "winrate": r["winrate"],
            "avg_pnl": r["avg_pnl"],
        })
    analysis["rr_analysis"] = rr_results

    # 3. Impact du seuil spread
    print("  [Analyse] Impact du seuil spread...")
    spread_results = []
    for ms in [s/100 for s in range(1, 51, 1)]:  # 0.01% a 0.50%
        params = {
            "window_start": 0, "window_end": 24,
            "min_rr": 0.0,
            "max_spread_pct": ms,
            "allowed_types": {"FOREX_USD", "INDEX", "METAL", "FOREX_CROSS",
                              "FOREX_JPY", "OTHER"},
        }
        r = evaluate_params(trades, params)
        if r["n_closed"] >= 2:
            spread_results.append({
                "max_spread": round(ms, 2),
                "n_trades": r["n_trades"],
                "n_closed": r["n_closed"],
                "winrate": r["winrate"],
                "avg_pnl": r["avg_pnl"],
            })
    analysis["spread_analysis"] = spread_results

    return analysis


# ==================== Main ====================
def main():
    # Charger les resultats du backtest
    if not os.path.exists(RESULTS_PATH):
        print(f"[ERREUR] Fichier introuvable: {RESULTS_PATH}")
        print("  Lance d'abord: python backtest_all_trades.py")
        return 1

    with open(RESULTS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    trades = data["all_trades"]
    summary = data["summary"]

    print(f"  Trades charges: {summary['total']}")
    print(f"  Winrate global: {summary['winrate']}%")
    print()

    # ===== 1. Analyse par critere individuel =====
    print("=" * 90)
    print("  PARTIE 1: ANALYSE PAR CRITERE INDIVIDUEL")
    print("=" * 90)
    print()

    single_analysis = analyze_single_criteria(trades)

    # Affichage des meilleures fenetres
    print(f"\n  --- TOP 15 FENETRES HORAIRES (winrate >= 60%, >= 3 trades clos) ---")
    print(f"  {'Fenetre':<20s} {'Winrate':>8s} {'Trades clos':>12s} {'P&L moyen':>10s}")
    print("  " + "-" * 55)
    for r in single_analysis["best_windows"]:
        print(f"  {r['window']:<20s} {r['winrate']:>7.1f}% {r['n_closed']:>12d} {r['avg_pnl']:>+9.3f}R")
    print()

    # Analyse RR
    print(f"  --- ANALYSE RR - evolution du winrate selon le seuil ---")
    print(f"  {'Seuil RR':>10s} {'Trades':>8s} {'Winrate':>10s} {'P&L/trade':>12s}")
    print("  " + "-" * 45)
    # Echantillonnage tous les 0.2
    for r in single_analysis["rr_analysis"]:
        if r["min_rr"] * 10 % 2 == 0:  # tous les 0.2
            print(f"  {r['min_rr']:>8.1f}x {r['n_closed']:>8d} {r['winrate']:>9.1f}% {r['avg_pnl']:>+11.3f}R")
    print()

    # Analyse Spread
    if single_analysis["spread_analysis"]:
        print(f"  --- ANALYSE SPREAD - evolution du winrate selon le seuil ---")
        print(f"  {'Seuil spread':>15s} {'Trades':>8s} {'Winrate':>10s} {'P&L/trade':>12s}")
        print("  " + "-" * 50)
        for r in single_analysis["spread_analysis"][::5]:  # tous les 5
            print(f"  {r['max_spread']:>13.2f}% {r['n_closed']:>8d} {r['winrate']:>9.1f}% {r['avg_pnl']:>+11.3f}R")
    print()

    # ===== 2. Optimisation multi-criteres =====
    print("=" * 90)
    print("  PARTIE 2: RECHERCHE DES MEILLEURS PARAMETRES COMBINES")
    print("=" * 90)
    print()

    optimal_results = optimize(trades)

    # Sauvegarder
    output = {
        "single_analysis": {
            "best_windows": single_analysis["best_windows"],
            "rr_analysis": [{k: v for k, v in r.items() if k != "n_trades"} for r in single_analysis["rr_analysis"]],
            "spread_analysis": single_analysis["spread_analysis"],
        },
        "optimal_combinations": optimal_results[:50],
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "total_trades": summary["total"],
        "global_winrate": summary["winrate"],
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)

    print(f"  Resultats sauvegardes: {OUTPUT_PATH}")
    print()

    # ===== Affichage du TOP 20 =====
    print("=" * 90)
    print("  TOP 20 COMBINAISONS OPTIMALES")
    print("=" * 90)
    print(f"  {'#':>3s} {'Fenetre':<18s} {'Seuil RR':>9s} {'Spread max':>11s} "
          f"{'Types':<30s} {'Trades':>7s} {'Clos':>5s} {'WR':>6s} {'P&L/R':>7s} {'Score':>7s}")
    print("  " + "-" * 110)

    for i, r in enumerate(optimal_results[:20]):
        p = r["params"]
        m = r["metrics"]
        types_str = "+".join(sorted(p["allowed_types"]))[:28]
        spread_str = f"{p['max_spread_pct']:.2f}%" if p.get("max_spread_pct", 999) < 100 else "aucun"
        print(f"  {i+1:>3d} {p['window']:<18s} {p['min_rr']:>7.1f}x {spread_str:>10s} "
              f"{types_str:<30s} {m['n_trades']:>7d} {m['n_closed']:>5d} "
              f"{m['winrate']:>5.1f}% {m['avg_pnl']:>+6.3f}R {m['score']:>7.1f}")
    print()
    print("  Score = winrate^2 * sqrt(n_closed) * (avg_pnl + 0.5) * 100")
    print()

    # ===== Recommandations =====
    print("=" * 90)
    print("  RECOMMANDATIONS")
    print("=" * 90)
    print()

    # Meilleur compromis avec >= 10 trades clos
    viable = [r for r in optimal_results if r["metrics"]["n_closed"] >= 10]
    best_viable = viable[:5] if viable else optimal_results[:5]

    print(f"  Meilleur compromis (>= 10 trades clos):")
    for i, r in enumerate(best_viable):
        p = r["params"]
        m = r["metrics"]
        print(f"\n  [{i+1}] Fenetre: {p['window']}")
        print(f"      RR >= {p['min_rr']:.1f}x | Spread < {p['max_spread_pct']:.2f}% | Types: {', '.join(p['allowed_types'])}")
        print(f"      {m['n_trades']} trades ({m['n_closed']} clos) | WR: {m['winrate']}% | P&L: {m['avg_pnl']:.3f}R (score: {m['score']:.1f})")
    print()

    # Meilleur winrate pur (avec >= 5 trades)
    high_wr = [r for r in optimal_results if r["metrics"]["n_closed"] >= 5 and r["metrics"]["winrate"] >= 85]
    if high_wr:
        print(f"  Meilleurs winrates (>= 85%, >= 5 trades clos):")
        for r in high_wr[:5]:
            p = r["params"]
            m = r["metrics"]
            print(f"    - Fenetre: {p['window']} | RR >= {p['min_rr']:.1f}x | Spread < {p['max_spread_pct']:.2f}% | "
                  f"Types: {', '.join(p['allowed_types'])} -> {m['winrate']}% ({m['n_closed']} clos, {m['avg_pnl']:.3f}R)")
    print()

    print("=" * 90)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[STOP] Interrompu.")
        sys.exit(130)
    except Exception as e:
        print(f"\n[ERREUR] {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)
