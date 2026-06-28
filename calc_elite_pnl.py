"""
calc_elite_pnl.py
=================
Calcule le P&L reel en EUR si tous les trades ELITE v2 avaient ete
ouverts a 0.01 lot, en utilisant les donnees MT5 (contract size,
currency profit, taux de change).

Usage:
    python calc_elite_pnl.py
"""

import json
import sys
import os

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

RESULTS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "reports", "backtest_all_results.json"
)

LOTS = 0.01
ELITE_ALLOWED_TYPES = {"FOREX_USD", "INDEX", "METAL"}


def passes_v2(t):
    hour = t.get("scan_hour")
    if hour is not None:
        if not (hour >= 9 and hour < 13):
            return False
    sym_type = t.get("sym_type", "")
    if sym_type not in ELITE_ALLOWED_TYPES:
        return False
    spread = t.get("spread_pct")
    if spread is not None and spread >= 0.50:
        return False
    return True


def get_eur_rate(mt5) -> float:
    tick = mt5.symbol_info_tick("EURUSD")
    if tick and tick.bid > 0:
        return tick.bid
    return 1.14  # fallback


def risk_to_eur(mt5, symbol: str, risk_quote: float, currency_profit: str, eurusd: float) -> float:
    """Convertit un montant en devise de cotation vers EUR."""
    if currency_profit == "EUR":
        return risk_quote
    elif currency_profit == "USD":
        return risk_quote / eurusd
    elif currency_profit == "JPY":
        tick = mt5.symbol_info_tick("USDJPY")
        usdjpy = tick.bid if tick else 114.0
        return risk_quote / usdjpy / eurusd
    elif currency_profit == "GBP":
        tick = mt5.symbol_info_tick("GBPUSD")
        gbpusd = tick.bid if tick else 1.26
        return risk_quote * gbpusd / eurusd
    else:
        # Devise exotique: essayer de trouver un taux
        try:
            tick = mt5.symbol_info_tick(currency_profit + "USD")
            if tick:
                return risk_quote * tick.bid / eurusd
        except Exception:
            pass
        try:
            tick = mt5.symbol_info_tick("USD" + currency_profit)
            if tick:
                return risk_quote / tick.bid / eurusd
        except Exception:
            pass
        return risk_quote  # fallback brut


def main():
    bar = "=" * 110
    print(bar)
    print("  CALCUL P&L ELITE v2 - 0.01 LOT PAR TRADE")
    print(bar)
    print()

    # Charger les resultats
    with open(RESULTS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    all_trades = data["all_trades"]
    v2_trades = [t for t in all_trades if passes_v2(t)]
    print(f"  Trades ELITE v2: {len(v2_trades)} / {len(all_trades)} total")
    print()

    # Connexion MT5
    if not mt5.initialize():
        print("  [ERREUR] Connexion MT5 impossible")
        return 1

    eurusd = get_eur_rate(mt5)
    print(f"  EUR/USD: {eurusd:.5f}")
    print()

    total_pnl_eur = 0.0
    total_risk_eur = 0.0
    total_pnl_usd = 0.0
    n_ok = 0
    n_err = 0
    details = []

    # Header
    header = f"  {'#':>3s} {'Symbole':<16s} {'Act':>4s} {'Entry':>12s} {'SL':>12s} {'DistSL':>10s} {'Contr':>6s} {'Risk(EUR)':>10s} {'P&L(R)':>8s} {'P&L(EUR)':>10s} {'Outcome':<12s}"
    print(header)
    print("  " + "-" * 108)

    for i, t in enumerate(v2_trades):
        sym = t["symbol"]
        action = t["action"]
        entry = t["entry"]
        sl = t["sl"]
        pnl_r = t.get("pnl_pct", 0)
        outcome = t["outcome"]

        if outcome == "INDETERMINE":
            continue

        try:
            info = mt5.symbol_info(sym)
            if info is None:
                n_err += 1
                continue

            contract = info.trade_contract_size
            currency_profit = info.currency_profit

            sl_dist = abs(entry - sl)
            if sl_dist == 0:
                n_err += 1
                continue

            # Risk en devise de cotation
            risk_quote = LOTS * contract * sl_dist

            # Conversion vers EUR
            risk_eur = risk_to_eur(mt5, sym, risk_quote, currency_profit, eurusd)

            # P&L en USD puis EUR
            if currency_profit == "USD":
                pnl_usd = risk_quote * pnl_r
            elif currency_profit == "EUR":
                pnl_usd = risk_quote * pnl_r * eurusd
            elif currency_profit == "JPY":
                tick = mt5.symbol_info_tick("USDJPY")
                usdjpy = tick.bid if tick else 114.0
                pnl_usd = risk_quote * pnl_r / usdjpy
            else:
                pnl_usd = risk_quote * pnl_r

            pnl_eur = pnl_usd / eurusd

            total_pnl_eur += pnl_eur
            total_pnl_usd += pnl_usd
            total_risk_eur += risk_eur
            n_ok += 1

            details.append({
                "sym": sym, "action": action, "entry": entry, "sl": sl,
                "sl_dist": sl_dist, "contract": contract, "risk_eur": risk_eur,
                "pnl_r": pnl_r, "pnl_eur": pnl_eur, "outcome": outcome,
            })

            row = f"  {n_ok:>3d} {sym:<16s} {action:>4s} {entry:>12.5f} {sl:>12.5f} {sl_dist:>10.5f} {contract:>6d} {risk_eur:>8.2f}e {pnl_r:>+7.2f}R {pnl_eur:>+9.2f}e {outcome:<12s}"
            print(row)

        except Exception as e:
            n_err += 1
            continue

    mt5.shutdown()

    print("  " + "-" * 108)
    print()
    print(f"  Trades calcules: {n_ok}")
    print(f"  Trades ignores (erreur): {n_err}")
    print()

    closed = [d for d in details if d["outcome"] in ("GAGNE", "PERDU")]
    won = sum(1 for d in closed if d["outcome"] == "GAGNE")
    lost = sum(1 for d in closed if d["outcome"] == "PERDU")
    open_trades = [d for d in details if d["outcome"] == "OUVERT"]

    closed_pnl = sum(d["pnl_eur"] for d in closed)

    print(f"  {'=' * 55}")
    print(f"  {'RESULTATS':^55s}")
    print(f"  {'=' * 55}")
    print(f"  {'Trades total (ELITE v2)':<30s} {n_ok:>8d}")
    print(f"  {'Clos (GAGNE + PERDU)':<30s} {len(closed):>8d}")
    print(f"  {'  GAGNE':<30s} {won:>8d}")
    print(f"  {'  PERDU':<30s} {lost:>8d}")
    print(f"  {'Encore ouverts':<30s} {len(open_trades):>8d}")
    if closed:
        print(f"  {'Winrate':<30s} {won/len(closed)*100:>7.1f}%")
    print()
    print(f"  {'P&L TOTAL (tous clos)':<30s} {closed_pnl:>+9.2f} EUR")
    print(f"  {'Risque total engage':<30s} {total_risk_eur:>9.2f} EUR")
    if total_risk_eur > 0:
        print(f"  {'Return on Risk':<30s} {closed_pnl/total_risk_eur*100:>+7.1f}%")
    print()
    print(f"  {'MOYENNE PAR TRADE CLOS':<30s} {closed_pnl/len(closed):>+9.3f} EUR" if closed else "")
    print(f"  {'MOYENNE PAR TRADE GAGNE':<30s} {sum(d['pnl_eur'] for d in closed if d['outcome']=='GAGNE')/won:>+9.3f} EUR" if won > 0 else "")
    print(f"  {'MOYENNE PAR TRADE PERDU':<30s} {sum(d['pnl_eur'] for d in closed if d['outcome']=='PERDU')/lost:>+9.3f} EUR" if lost > 0 else "")
    print()
    print(f"  {'P&L si tout ouvert (incluant ouverts)':<30s} {total_pnl_eur:>+9.2f} EUR")
    print()
    print(f"  {'=' * 55}")
    print()

    # Estimation mensuelle
    n_days = len(set(t["report"] for t in v2_trades))
    trades_per_day = n_ok / n_days if n_days > 0 else 0
    pnl_per_day = closed_pnl / n_days if n_days > 0 else 0
    print(f"  {'ESTIMATION MENSUELLE (21 jours)':^55s}")
    print(f"  {'=' * 55}")
    print(f"  {'Jours de donnees':<30s} {n_days:>8d}")
    print(f"  {'Trades/jour (moy)':<30s} {trades_per_day:>8.1f}")
    print(f"  {'P&L/jour (EUR)':<30s} {pnl_per_day:>+9.3f}")
    print(f"  {'P&L/mois estime (EUR)':<30s} {pnl_per_day * 21:>+9.2f}")
    print()

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[STOP]")
        sys.exit(130)
