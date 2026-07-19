"""
stochastic_analytics.py — Calcul stochastique pour le Diamond Scanner.

Six fonctions principales :
  1. ornstein_uhlenbeck_fit(price_series) — Ajuste un processus OU et retourne
     (theta, mu, sigma, overextension_score).
  2. hurst_exponent(price_series) — Calcule l'exposant de Hurst H.
     H < 0.5 → range (mean-reverting), H > 0.5 → trending.
  3. monte_carlo_sweep_probability(current_price, sl, tp, sigma, n_paths)
     — Simule N chemins browniens et retourne (p_sl, p_tp).
  4. kelly_criterion(win_rate, rr) — Calcule le critere de Kelly
     pour le dimensionnement optimal des positions.
  5. ftmo_ruin_probability(win_rate, rr, kelly_fraction) — Probabilite de
     ruine FTMO par Monte Carlo (drawdown max 10%).
  6. garch_11_fit(returns) — Estimation GARCH(1,1) par MLE (grille + raffinement)
     et garch_11_forecast() — Prediction de volatilite future.

Usage:
    from src.stochastic_analytics import (
        ornstein_uhlenbeck_fit, hurst_exponent, monte_carlo_sweep_probability,
        kelly_criterion, ftmo_ruin_probability,
        garch_11_fit, garch_11_forecast,
    )
"""

import math
import logging
from typing import Tuple, List, Optional

# Lazy import numpy (avec fallback silencieux)
try:
    import numpy as np
    _NUMPY_AVAILABLE = True
except ImportError:
    np = None
    _NUMPY_AVAILABLE = False

logger = logging.getLogger("StochasticAnalytics")

# ── Constantes ──────────────────────────────────────────────────────────
_OU_MIN_OBS = 30
_OU_SCORE_Z_MAX = 3.0
_HURST_MIN_OBS = 50
_MC_DEFAULT_PATHS = 5000
_FTMO_INITIAL_CAPITAL = 100000.0
_FTMO_MAX_DRAWDOWN = 0.10        # 10% (regle FTMO challenge)
_FTMO_MAX_DAILY_DRAWDOWN = 0.05 # 5% (regle FTMO, non implementee ici)
_FTMO_DEFAULT_SIMULATIONS = 5000
_FTMO_DEFAULT_MAX_TRADES = 1000
_GARCH_MIN_OBS = 30              # observations minimales pour GARCH(1,1)
_GARCH_ALPHA_GRID = (0.01, 0.03, 0.05, 0.07, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50)
_GARCH_BETA_GRID  = (0.50, 0.60, 0.70, 0.80, 0.85, 0.90, 0.93, 0.95, 0.97, 0.98)
_GARCH_STABILITY  = 0.999         # alpha + beta < 0.999 pour stationnarite


# ═══════════════════════════════════════════════════════════════════════════
# 1. Ornstein-Uhlenbeck Process
# ═══════════════════════════════════════════════════════════════════════════

def ornstein_uhlenbeck_fit(
    prices: List[float],
    dt: float = 1.0,
) -> Tuple[float, float, float, float]:
    """Ajuste un processus d'Ornstein-Uhlenbeck aux prix observés.

    Modèle : dX(t) = theta(mu - X(t))dt + sigma dW(t)

    Estimation par OLS : X(t+1) - X(t) = alpha + beta * X(t) + epsilon
        beta = -theta * dt  -> theta = -beta / dt
        alpha = theta * mu * dt -> mu = alpha / (-beta)
        sigma = std(epsilon) / sqrt(dt)

    Args:
        prices: Liste de prix ordonnée du plus ancien au plus récent.
        dt: Pas de temps (1.0 = 1 barre).

    Returns:
        (theta, mu, sigma, overextension_score)
    """
    if not _NUMPY_AVAILABLE:
        return (0.0, 0.0, 0.0, 0.0)

    n = len(prices)
    if n < _OU_MIN_OBS:
        logger.debug("OU fit: besoin de %d observations, reçu %d", _OU_MIN_OBS, n)
        return (0.0, 0.0, 0.0, 0.0)

    arr = np.array(prices, dtype=np.float64)
    X_t = arr[:-1]
    X_t1 = arr[1:]
    dX = X_t1 - X_t

    n_obs = len(X_t)
    mean_X = np.mean(X_t)
    mean_dX = np.mean(dX)

    cov = np.sum((X_t - mean_X) * (dX - mean_dX)) / (n_obs - 1)
    var_X = np.var(X_t, ddof=1)

    if var_X < 1e-15 or abs(cov) < 1e-15:
        return (0.0, 0.0, 0.0, 0.0)

    beta = cov / var_X
    alpha = mean_dX - beta * mean_X

    theta = -beta / dt
    if theta <= 0:
        return (0.0, 0.0, 0.0, 0.0)

    mu = alpha / (-beta) if abs(beta) > 1e-15 else mean_X
    residuals = dX - (alpha + beta * X_t)
    sigma = np.std(residuals, ddof=2) / math.sqrt(dt) if n_obs > 2 else 0.0

    if theta > 1e-10:
        var_stationary = (sigma ** 2) / (2.0 * theta)
        std_stationary = math.sqrt(var_stationary) if var_stationary > 0 else 0.0
    else:
        std_stationary = 0.0

    last_price = arr[-1]
    if std_stationary > 1e-10:
        z = abs(last_price - mu) / std_stationary
    else:
        z = 0.0

    score = min(100.0, z / _OU_SCORE_Z_MAX * 100.0)
    return (float(theta), float(mu), float(sigma), float(score))


# ═══════════════════════════════════════════════════════════════════════════
# 2. Hurst Exponent (R/S Analysis)
# ═══════════════════════════════════════════════════════════════════════════

def hurst_exponent(prices: List[float]) -> float:
    """Calcule l'exposant de Hurst par l'analyse R/S (Rescaled Range).

    H < 0.5 -> Anti-persistant (mean-reverting, range-bound market)
    H = 0.5 -> Random walk (efficient market)
    H > 0.5 -> Persistent (trending market)

    Args:
        prices: Liste de prix ordonnée du plus ancien au plus récent.

    Returns:
        H : Exposant de Hurst (0.0 - 1.0), 0.0 si pas assez de données.
    """
    if not _NUMPY_AVAILABLE:
        return 0.0

    n = len(prices)
    if n < _HURST_MIN_OBS:
        logger.debug("Hurst: besoin de %d observations, reçu %d", _HURST_MIN_OBS, n)
        return 0.0

    arr = np.array(prices, dtype=np.float64)
    log_returns = np.diff(np.log(arr))

    if len(log_returns) < _HURST_MIN_OBS:
        return 0.0

    max_lag = len(log_returns) // 2
    lags = np.unique(np.logspace(
        math.log10(10), math.log10(max_lag), num=20, dtype=int
    ))
    lags = lags[lags >= 10]

    if len(lags) < 3:
        return 0.0

    rs_values = []
    for lag in lags:
        n_segments = len(log_returns) // lag
        if n_segments < 1:
            continue
        rs_list = []
        for i in range(n_segments):
            segment = log_returns[i * lag:(i + 1) * lag]
            mean_seg = np.mean(segment)
            deviate = segment - mean_seg
            cumulative = np.cumsum(deviate)
            R = np.max(cumulative) - np.min(cumulative)
            S = np.std(segment, ddof=1)
            if S > 1e-15:
                rs_list.append(R / S)
        if rs_list:
            rs_values.append(np.mean(rs_list))
        else:
            rs_values.append(0.0)

    if len(rs_values) < 3:
        return 0.0

    log_lags = np.log(lags[:len(rs_values)])
    log_rs = np.log(np.array(rs_values) + 1e-15)

    finite_mask = np.isfinite(log_lags) & np.isfinite(log_rs)
    if np.sum(finite_mask) < 3:
        return 0.0

    log_lags_f = log_lags[finite_mask]
    log_rs_f = log_rs[finite_mask]

    n_pts = len(log_lags_f)
    mean_lag = np.mean(log_lags_f)
    mean_rs = np.mean(log_rs_f)
    cov_lr = np.sum((log_lags_f - mean_lag) * (log_rs_f - mean_rs)) / (n_pts - 1)
    var_lag = np.var(log_lags_f, ddof=1)

    if var_lag < 1e-15:
        return 0.0

    H = cov_lr / var_lag
    return float(np.clip(H, 0.0, 1.0))


# ═══════════════════════════════════════════════════════════════════════════
# 3. Monte Carlo Sweep Probability
# ═══════════════════════════════════════════════════════════════════════════

def monte_carlo_sweep_probability(
    current_price: float,
    sl: float,
    tp: float,
    sigma: float,
    n_paths: int = _MC_DEFAULT_PATHS,
    n_steps: int = 24,
    drift: float = 0.0,
) -> Tuple[float, float]:
    """Simule des chemins browniens GBM et estime la probabilité d'atteindre
    SL vs TP en premier.

    Modele : dS = mu * S * dt + sigma * S * dW

    Args:
        current_price: Prix d'entree.
        sl: Niveau du stop loss.
        tp: Niveau du take profit.
        sigma: Volatilite (doit correspondre a l'echelle de temps).
        n_paths: Nombre de chemins Monte Carlo.
        n_steps: Nombre de pas de temps par chemin.
        drift: Derive (mu, en fraction par pas, 0 = neutre).

    Returns:
        (p_sl, p_tp) : Probabilites que SL ou TP soit touche en premier.
    """
    if not _NUMPY_AVAILABLE:
        return (0.0, 0.0)

    if sigma <= 0 or sl <= 0 or tp <= 0 or current_price <= 0:
        return (0.0, 0.0)

    is_long = tp > current_price
    if not is_long:
        _sl, _tp = tp, sl
        _price = current_price
    else:
        _sl, _tp = sl, tp
        _price = current_price

    if _sl >= _price or _tp <= _price:
        return (1.0, 0.0) if is_long else (0.0, 1.0)

    try:
        rng = np.random.default_rng()
        rand = rng.normal(0, 1, (n_paths, n_steps))

        drift_comp = (drift - 0.5 * sigma ** 2) * 1.0
        vol_comp = sigma * math.sqrt(1.0)
        increments = drift_comp + vol_comp * rand
        log_returns = np.cumsum(increments, axis=1)
        paths = _price * np.exp(log_returns)

        hit_sl = np.zeros(n_paths, dtype=bool)
        hit_tp = np.zeros(n_paths, dtype=bool)

        for t in range(n_steps):
            step_prices = paths[:, t]
            not_hit_yet = ~(hit_sl | hit_tp)
            if not np.any(not_hit_yet):
                break
            hit_sl |= not_hit_yet & (step_prices <= _sl)
            hit_tp |= not_hit_yet & (step_prices >= _tp)

        p_sl = float(np.sum(hit_sl)) / float(n_paths)
        p_tp = float(np.sum(hit_tp)) / float(n_paths)

    except Exception as e:
        logger.warning("Monte Carlo simulation error: %s", e)
        return (0.0, 0.0)

    if not is_long:
        return (p_tp, p_sl)
    return (p_sl, p_tp)


# ═══════════════════════════════════════════════════════════════════════════
# 4. Kelly Criterion — Position Sizing
# ═══════════════════════════════════════════════════════════════════════════

def kelly_criterion(
    win_rate: float,
    rr: float,
) -> dict:
    """Calcule le critere de Kelly pour le dimensionnement optimal des positions.

    Formule : f* = (b * p - q) / b
        ou b = RR (risk/reward), p = win_rate, q = 1 - p

    Args:
        win_rate: Taux de reussite (0.0 - 1.0), ex: 0.55 = 55%.
        rr: Ratio risk/reward, ex: 2.0 = risque 1 pour gagner 2.

    Returns:
        dict avec :
            full_kelly : Fraction de Kelly complete (f*) — souvent trop agressive.
            half_kelly : Moitie de Kelly (f* / 2) — recommandee pour trading.
            quarter_kelly : Quart de Kelly (f* / 4) — prudente pour challenges FTMO.
            expected_value : Esperance mathematique (b*p - q).
            warning : Avertissement si f* <= 0 (strategie perdante).
    """
    if not (0 < win_rate < 1):
        return {
            "full_kelly": 0.0, "half_kelly": 0.0, "quarter_kelly": 0.0,
            "expected_value": 0.0,
            "warning": "win_rate doit etre entre 0 et 1",
        }
    if rr <= 0:
        return {
            "full_kelly": 0.0, "half_kelly": 0.0, "quarter_kelly": 0.0,
            "expected_value": 0.0,
            "warning": "RR doit etre > 0",
        }

    q = 1.0 - win_rate
    ev = rr * win_rate - q  # esperance = b*p - q

    if ev <= 0:
        return {
            "full_kelly": 0.0, "half_kelly": 0.0, "quarter_kelly": 0.0,
            "expected_value": ev,
            "warning": f"Esperance negative ({ev:.3f}) — strategie perdante a long terme",
        }

    full = ev / rr  # f* = (b*p - q) / b
    full = max(0.0, min(full, 0.5))  # plafond a 50% (securite)

    return {
        "full_kelly": round(full, 4),
        "half_kelly": round(full / 2.0, 4),
        "quarter_kelly": round(full / 4.0, 4),
        "expected_value": round(ev, 4),
        "warning": "",
    }


# ═══════════════════════════════════════════════════════════════════════════
# 5. FTMO Ruin Probability — Monte Carlo Simulation
# ═══════════════════════════════════════════════════════════════════════════

def ftmo_ruin_probability(
    win_rate: float,
    rr: float,
    kelly_fraction: float = 0.25,
    max_drawdown: float = _FTMO_MAX_DRAWDOWN,
    initial_capital: float = _FTMO_INITIAL_CAPITAL,
    n_simulations: int = _FTMO_DEFAULT_SIMULATIONS,
    max_trades: int = _FTMO_DEFAULT_MAX_TRADES,
) -> dict:
    """Simule la probabilite de ruine FTMO (drawdown > 10%) par Monte Carlo.

    Simule n_simulations traders independants. Chaque trader execute des trades
    jusqu'a max_trades ou jusqu'a ce que le drawdown depasse max_drawdown.

    La taille de position est basee sur le critere de Kelly :
        position_size = kelly_fraction * f* * equity_courante
    ou f* = (b * p - q) / b est le Kelly complet.

    Args:
        win_rate: Taux de reussite (0.0 - 1.0).
        rr: Ratio risk/reward.
        kelly_fraction: Fraction de Kelly a utiliser (0.25 = quarter Kelly).
        max_drawdown: Drawdown max avant ruine (0.10 = 10% pour FTMO).
        initial_capital: Capital initial (100000 pour FTMO standard).
        n_simulations: Nombre de simulations Monte Carlo.
        max_trades: Nombre max de trades par simulation.

    Returns:
        dict avec :
            ruin_prob : Probabilite de ruine (0.0 - 1.0).
            survival_rate : Taux de survie apres max_trades trades.
            avg_trades_to_ruin : Nombre moyen de trades avant ruine (si ruine).
            avg_final_equity : Equity finale moyenne (survivants uniquement).
            median_final_equity : Equity finale mediane (survivants).
            best_equity : Meilleure equity finale.
            worst_equity : Pire equity finale (survivants).
            kelly_summary : Resultat du calcul de Kelly associe.
            error : Message d'erreur si necessaire.
    """
    # Kelly check prealable (pure Python, pas besoin de numpy)
    kelly = kelly_criterion(win_rate, rr)
    if kelly["warning"]:
        return {
            "ruin_prob": 1.0, "survival_rate": 0.0,
            "avg_trades_to_ruin": 0.0, "avg_final_equity": 0.0,
            "median_final_equity": 0.0, "best_equity": 0.0,
            "worst_equity": 0.0,
            "kelly_summary": kelly,
            "error": f"Strategie perdante: {kelly['warning']}",
        }

    if not _NUMPY_AVAILABLE:
        return {
            "ruin_prob": 0.0, "survival_rate": 0.0,
            "avg_trades_to_ruin": 0.0, "avg_final_equity": 0.0,
            "median_final_equity": 0.0, "best_equity": 0.0,
            "worst_equity": 0.0,
            "kelly_summary": kelly,
            "error": "numpy necessaire pour la simulation Monte Carlo",
        }

    full_kelly = kelly["full_kelly"]
    if full_kelly <= 0:
        return {
            "ruin_prob": 1.0, "survival_rate": 0.0,
            "avg_trades_to_ruin": 0.0, "avg_final_equity": 0.0,
            "median_final_equity": 0.0, "best_equity": 0.0,
            "worst_equity": 0.0,
            "kelly_summary": kelly,
            "error": "Kelly nul — pas de taille de position possible",
        }

    try:
        rng = np.random.default_rng()
        position_pct = full_kelly * kelly_fraction  # ex: 0.25 * 0.25 = 6.25%
        # Taille max de position (securite : pas plus de 20% du capital)
        position_pct = min(position_pct, 0.20)

        n_ruin = 0
        trades_to_ruin_list = []
        final_equities = []
        min_balance = initial_capital * (1.0 - max_drawdown)  # ex: 100k * 0.90 = 90k

        for _ in range(n_simulations):
            equity = initial_capital
            trades_done = 0
            ruined = False

            for t in range(max_trades):
                # Taille de la position = % du capital courant
                risk_amount = equity * position_pct
                if risk_amount <= 0:
                    break

                # Tirage au sort : win ou loss
                if rng.random() < win_rate:
                    # Gain : RR * risk_amount
                    equity += risk_amount * rr
                else:
                    # Perte : -risk_amount
                    equity -= risk_amount

                trades_done = t + 1

                # Test ruine FTMO : equity < 90% du capital initial
                if equity < min_balance:
                    n_ruin += 1
                    trades_to_ruin_list.append(trades_done)
                    ruined = True
                    break

            if not ruined:
                final_equities.append(equity)

        ruin_prob = float(n_ruin) / float(n_simulations)
        survival_rate = 1.0 - ruin_prob

        avg_trades_to_ruin = float(np.mean(trades_to_ruin_list)) if trades_to_ruin_list else 0.0
        avg_final_eq = float(np.mean(final_equities)) if final_equities else 0.0
        median_final_eq = float(np.median(final_equities)) if final_equities else 0.0
        best_eq = float(np.max(final_equities)) if final_equities else 0.0
        worst_eq = float(np.min(final_equities)) if final_equities else 0.0

        # Stats supplementaires
        pnl_avg = avg_final_eq - initial_capital if final_equities else 0.0
        roi_avg = (pnl_avg / initial_capital) * 100.0 if final_equities else 0.0

        return {
            "ruin_prob": round(ruin_prob, 4),
            "survival_rate": round(survival_rate, 4),
            "avg_trades_to_ruin": round(avg_trades_to_ruin, 1),
            "avg_final_equity": round(avg_final_eq, 2),
            "median_final_equity": round(median_final_eq, 2),
            "best_equity": round(best_eq, 2),
            "worst_equity": round(worst_eq, 2),
            "avg_pnl": round(pnl_avg, 2),
            "avg_roi_pct": round(roi_avg, 2),
            "position_pct": round(position_pct * 100, 2),
            "kelly_summary": kelly,
            "error": "",
        }

    except Exception as e:
        logger.warning("FTMO ruin simulation error: %s", e)
        return {
            "ruin_prob": 0.0, "survival_rate": 0.0,
            "avg_trades_to_ruin": 0.0, "avg_final_equity": 0.0,
            "median_final_equity": 0.0, "best_equity": 0.0,
            "worst_equity": 0.0,
            "kelly_summary": kelly,
            "error": f"Erreur simulation: {e}",
        }


# ═══════════════════════════════════════════════════════════════════════════
# 6. GARCH(1,1) — Volatility Forecasting
# ═══════════════════════════════════════════════════════════════════════════

def garch_11_fit(
    returns: List[float],
    n_grid_alpha: int = 20,
    n_grid_beta: int = 20,
) -> dict:
    """Estime les parametres GARCH(1,1) par Maximum de Vraisemblance.

    Modele : sigma2(t) = omega + alpha * eps(t-1)^2 + beta * sigma2(t-1)
        ou eps(t) = r(t) - mu  (rendement centree)

    Algorithme :
      1. Centrer les rendements (soustraire la moyenne)
      2. Grille de recherche (alpha, beta) avec variance targeting pour omega
      3. Raffinement local autour du meilleur point de la grille
      4. Log-vraisemblance sous l'hypothese normale

    Args:
        returns: Liste de rendements (pas de prix, pas de log-rendements).
        n_grid_alpha: Nombre de points dans la grille alpha (default 20).
        n_grid_beta: Nombre de points dans la grille beta (default 20).

    Returns:
        dict avec :
            omega : Constante GARCH.
            alpha : Coefficient ARCH (impact des chocs recents).
            beta : Coefficient GARCH (persistance de la volatilite).
            log_likelihood : Log-vraisemblance maximisee.
            last_sigma2 : Variance estimee de la derniere observation.
            last_eps2 : Carre du residu de la derniere observation.
            long_run_var : Variance long terme = omega / (1 - alpha - beta).
            long_run_vol : Volatilite long terme (sqrt).
            sigma2_series : Liste des variances estimees (serie temporelle).
            n_obs : Nombre d'observations utilisees.
            error : Message d'erreur si necessaire.
    """
    n = len(returns)
    if not _NUMPY_AVAILABLE:
        return {"omega": 0.0, "alpha": 0.0, "beta": 0.0,
                "log_likelihood": 0.0, "last_sigma2": 0.0, "last_eps2": 0.0,
                "long_run_var": 0.0, "long_run_vol": 0.0,
                "sigma2_series": [], "n_obs": n,
                "error": "numpy necessaire pour GARCH"}

    if n < _GARCH_MIN_OBS:
        return {"omega": 0.0, "alpha": 0.0, "beta": 0.0,
                "log_likelihood": 0.0, "last_sigma2": 0.0, "last_eps2": 0.0,
                "long_run_var": 0.0, "long_run_vol": 0.0,
                "sigma2_series": [], "n_obs": n,
                "error": f"besoin de {_GARCH_MIN_OBS} observations, recu {n}"}

    try:
        arr = np.array(returns, dtype=np.float64)
        mu = np.mean(arr)
        eps = arr - mu          # residus centrees
        eps2 = eps ** 2
        sample_var = np.var(eps, ddof=0)  # variance non-corrigee

        if sample_var <= 0:
            return {"omega": 0.0, "alpha": 0.0, "beta": 0.0,
                    "log_likelihood": 0.0, "last_sigma2": 0.0, "last_eps2": 0.0,
                    "long_run_var": 0.0, "long_run_vol": 0.0,
                    "sigma2_series": [], "n_obs": n,
                    "error": "variance nulle — donnees constantes"}

        # ── Etape 1 : grille de recherche (alpha, beta) ──
        # Alphas log-spaced pour plus de resolution aux petites valeurs
        alphas = np.logspace(
            math.log10(0.01), math.log10(0.50), num=n_grid_alpha
        )
        # Betas lineairement espaces
        betas = np.linspace(0.50, 0.98, n_grid_beta)

        best_ll = -np.inf
        best_params = (0.10, 0.85, sample_var * 0.05)

        for alpha in alphas:
            for beta in betas:
                if alpha + beta >= _GARCH_STABILITY:
                    continue
                omega = sample_var * (1.0 - alpha - beta)
                if omega <= 0:
                    continue

                # Filtre de Kalman : recursion GARCH
                sigma2 = np.full(n, sample_var, dtype=np.float64)
                for t in range(1, n):
                    sigma2[t] = omega + alpha * eps2[t-1] + beta * sigma2[t-1]

                # Log-vraisemblance (normale)
                sigma2_clip = np.maximum(sigma2[1:], 1e-15)
                ll = -0.5 * np.sum(
                    np.log(2.0 * math.pi) + np.log(sigma2_clip) + eps2[1:] / sigma2_clip
                )

                if ll > best_ll:
                    best_ll = ll
                    best_params = (float(alpha), float(beta), float(omega))

        # Verifier qu'au moins une paire valide a ete trouvee
        if best_ll <= -1e100:
            return {"omega": 0.0, "alpha": 0.0, "beta": 0.0,
                    "log_likelihood": 0.0, "last_sigma2": 0.0, "last_eps2": 0.0,
                    "long_run_var": 0.0, "long_run_vol": 0.0,
                    "sigma2_series": [], "n_obs": n,
                    "error": "aucune paire (alpha,beta) stable trouvee dans la grille"}

        # ── Etape 2 : raffinement local (sub-grille fine) ──
        alpha0, beta0, omega0 = best_params
        fine_alphas = np.linspace(max(0.005, alpha0 - 0.05), min(0.55, alpha0 + 0.05), 10)
        fine_betas = np.linspace(max(0.45, beta0 - 0.05), min(0.99, beta0 + 0.05), 10)

        for alpha in fine_alphas:
            for beta in fine_betas:
                if alpha + beta >= _GARCH_STABILITY or alpha <= 0 or beta <= 0:
                    continue
                omega = sample_var * (1.0 - alpha - beta)
                if omega <= 0:
                    continue

                sigma2 = np.full(n, sample_var, dtype=np.float64)
                for t in range(1, n):
                    sigma2[t] = omega + alpha * eps2[t-1] + beta * sigma2[t-1]

                sigma2_clip = np.maximum(sigma2[1:], 1e-15)
                ll = -0.5 * np.sum(
                    np.log(2.0 * math.pi) + np.log(sigma2_clip) + eps2[1:] / sigma2_clip
                )

                if ll > best_ll:
                    best_ll = ll
                    best_params = (float(alpha), float(beta), float(omega))

        # ── Reconstruction finale ──
        alpha_opt, beta_opt, omega_opt = best_params
        sigma2 = np.full(n, sample_var, dtype=np.float64)
        for t in range(1, n):
            sigma2[t] = omega_opt + alpha_opt * float(eps2[t-1]) + beta_opt * float(sigma2[t-1])

        persistence = alpha_opt + beta_opt
        lr_var = omega_opt / (1.0 - persistence) if persistence < 1 else sample_var * 100

        return {
            "omega": round(omega_opt, 10),
            "alpha": round(alpha_opt, 6),
            "beta": round(beta_opt, 6),
            "persistence": round(persistence, 6),
            "log_likelihood": round(float(best_ll), 2),
            "last_sigma2": float(sigma2[-1]),
            "last_eps2": float(eps2[-1]),
            "long_run_var": round(float(lr_var), 10),
            "long_run_vol": round(math.sqrt(lr_var), 8),
            "sigma2_series": [float(v) for v in sigma2],
            "n_obs": n,
            "error": "",
        }

    except Exception as e:
        logger.warning("GARCH(1,1) fit error: %s", e)
        return {"omega": 0.0, "alpha": 0.0, "beta": 0.0,
                "log_likelihood": 0.0, "last_sigma2": 0.0, "last_eps2": 0.0,
                "long_run_var": 0.0, "long_run_vol": 0.0,
                "sigma2_series": [], "n_obs": n,
                "error": f"Erreur GARCH: {e}"}


# ═══════════════════════════════════════════════════════════════════════════
# 7. GARCH Forecast — Volatility Prediction
# ═══════════════════════════════════════════════════════════════════════════

def garch_11_forecast(
    omega: float,
    alpha: float,
    beta: float,
    last_sigma2: float,
    last_eps2: float,
    n_steps: int = 10,
) -> dict:
    """Prevoit la volatilite future avec le modele GARCH(1,1).

    Formule de prediction :
        E[sigma2(t+1)] = omega + alpha * eps(t)^2 + beta * sigma2(t)
        E[sigma2(t+k)] = omega + (alpha + beta) * E[sigma2(t+k-1)]  pour k > 1
        E[sigma2(inf)] = omega / (1 - alpha - beta)  (variance long terme)

    Args:
        omega: Constante GARCH.
        alpha: Coefficient ARCH.
        beta: Coefficient GARCH.
        last_sigma2: Variance estimee de la derniere observation.
        last_eps2: Carre du residu de la derniere observation.
        n_steps: Nombre de pas de prevision (default 10).

    Returns:
        dict avec :
            forecast_var : Liste des variances prevues (n_steps).
            forecast_vol : Liste des volatilites prevues (sqrt, n_steps).
            long_run_var : Variance long terme du processus.
            long_run_vol : Volatilite long terme.
            half_life : Demi-vie de la volatilite (periodes).
            n_steps : Nombre de pas demandes.
            error : Message d'erreur si necessaire.
    """
    persistence = alpha + beta

    if persistence >= 1 or last_sigma2 <= 0 or last_eps2 < 0:
        err_reason = "modele non-stationnaire" if persistence >= 1 else \
                     "last_sigma2 <= 0" if last_sigma2 <= 0 else \
                     "last_eps2 < 0"
        return {
            "forecast_var": [], "forecast_vol": [],
            "long_run_var": 0.0, "long_run_vol": 0.0,
            "half_life": float('inf'),
            "n_steps": n_steps,
            "error": f"{err_reason}",
        }

    lr_var = omega / (1.0 - persistence)

    if persistence > 0:
        half_life = math.log(0.5) / math.log(persistence)
    else:
        half_life = 1.0

    forecast = []
    prev_sigma2 = last_sigma2
    prev_eps2 = last_eps2

    for k in range(n_steps):
        if k == 0:
            # Pas 1 : utilisations des vrais eps2 et sigma2
            pred = omega + alpha * prev_eps2 + beta * prev_sigma2
        else:
            # Pas > 1 : E[eps^2] = E[sigma2] (bruit blanc)
            pred = omega + persistence * prev_sigma2

        forecast.append(pred)
        prev_sigma2 = pred
        prev_eps2 = pred  # E[eps^2] = sigma2 pour les pas > 0

    return {
        "forecast_var": forecast,
        "forecast_vol": [math.sqrt(max(v, 1e-15)) for v in forecast],
        "long_run_var": round(float(lr_var), 10),
        "long_run_vol": round(math.sqrt(lr_var), 8),
        "half_life": round(half_life, 2),
        "n_steps": n_steps,
        "error": "",
    }


# ═══════════════════════════════════════════════════════════════════════════
# 8. Helper - run all six (convenience)
# ═══════════════════════════════════════════════════════════════════════════

def _check_numpy():
    """Verifie que numpy est disponible."""
    if not _NUMPY_AVAILABLE or np is None:
        logger.warning("numpy non disponible - analyse stochastique desactivee")
        return False
    return True


def analyze_stochastic(
    prices: List[float],
    current_price: float,
    sl: float,
    tp: float,
    win_rate: float = 0.0,
    rr: float = 0.0,
) -> dict:
    """Convenience wrapper qui execute les 6 analyses stochastiques.

    Args:
        prices: Serie de prix (OHLC closes) pour OU, Hurst et GARCH.
        current_price: Prix actuel pour Monte Carlo.
        sl: Stop loss pour Monte Carlo.
        tp: Take profit pour Monte Carlo.
        win_rate: Taux de reussite pour Kelly + FTMO (optionnel).
        rr: Risk/reward ratio pour Kelly + FTMO (optionnel).

    Returns:
        dict avec cles : ou_*, hurst_h, mc_p_*, garch_*,
                         kelly_*, ftmo_*
    """
    result = {
        "ou_theta": 0.0, "ou_mu": 0.0, "ou_sigma": 0.0,
        "ou_score": 0.0, "hurst_h": 0.0,
        "mc_p_sl": 0.0, "mc_p_tp": 0.0,
        "garch_alpha": 0.0, "garch_beta": 0.0,
        "garch_persistence": 0.0, "garch_long_run_vol": 0.0,
        "garch_half_life": 0.0, "garch_forecast_vol_1": 0.0,
        "kelly_full": 0.0, "kelly_half": 0.0, "kelly_quarter": 0.0,
        "kelly_ev": 0.0, "kelly_warning": "",
        "ftmo_ruin_prob": 0.0, "ftmo_survival_rate": 0.0,
        "ftmo_avg_pnl": 0.0, "ftmo_avg_roi_pct": 0.0,
        "ftmo_position_pct": 0.0,
    }

    if not _check_numpy():
        return result

    theta, mu, sigma, ou_score = ornstein_uhlenbeck_fit(prices)
    h = hurst_exponent(prices)

    if sigma > 0:
        vol_ou = sigma
    else:
        vol_ou = 0.0

    # Fallback : volatilite calculee depuis les log-rendements (toujours calcule)
    log_rets = [math.log(max(p, 1e-10)) for p in prices]
    diffs = [log_rets[i+1] - log_rets[i] for i in range(len(log_rets)-1)]
    mean_d = sum(diffs) / len(diffs) if diffs else 0.0
    vol_fallback = math.sqrt(sum((d - mean_d)**2 for d in diffs) / max(len(diffs)-1, 1)) if diffs else 0.0

    # Utiliser le meilleur sigma disponible (OU sinon fallback)
    vol_used = vol_ou if vol_ou > 0 else vol_fallback

    p_sl, p_tp = monte_carlo_sweep_probability(current_price, sl, tp, vol_used) if vol_used > 0 else (0.0, 0.0)

    # ── GARCH(1,1) — utilise les rendements log des prix ──
    if len(prices) >= _GARCH_MIN_OBS:
        log_prices = [math.log(max(p, 1e-15)) for p in prices]
        log_rets = [log_prices[i+1] - log_prices[i] for i in range(len(log_prices)-1)]
        g = garch_11_fit(log_rets)
        if not g["error"]:
            f = garch_11_forecast(
                g["omega"], g["alpha"], g["beta"],
                g["last_sigma2"], g["last_eps2"],
                n_steps=5,
            )
            result["garch_alpha"] = g["alpha"]
            result["garch_beta"] = g["beta"]
            result["garch_persistence"] = g["persistence"]
            result["garch_long_run_vol"] = g["long_run_vol"]
            result["garch_half_life"] = f["half_life"]
            result["garch_forecast_vol_1"] = f["forecast_vol"][0] if f["forecast_vol"] else 0.0

    # Kelly Criterion (si win_rate et rr fournis)
    kelly = {}
    if win_rate > 0 and rr > 0:
        kelly = kelly_criterion(win_rate, rr)
        result["kelly_full"] = kelly["full_kelly"]
        result["kelly_half"] = kelly["half_kelly"]
        result["kelly_quarter"] = kelly["quarter_kelly"]
        result["kelly_ev"] = kelly["expected_value"]
        result["kelly_warning"] = kelly["warning"]

        # FTMO Ruin Probability (si Kelly valide)
        if not kelly["warning"]:
            ftmo = ftmo_ruin_probability(win_rate, rr)
            result["ftmo_ruin_prob"] = ftmo["ruin_prob"]
            result["ftmo_survival_rate"] = ftmo["survival_rate"]
            result["ftmo_avg_pnl"] = ftmo["avg_pnl"]
            result["ftmo_avg_roi_pct"] = ftmo["avg_roi_pct"]
            result["ftmo_position_pct"] = ftmo["position_pct"]

    return {
        "ou_theta": theta or 0.0,
        "ou_mu": mu or 0.0,
        "ou_sigma": sigma or 0.0,
        "ou_score": ou_score or 0.0,
        "hurst_h": h or 0.0,
        "mc_p_sl": p_sl or 0.0,
        "mc_p_tp": p_tp or 0.0,
        **{k: v for k, v in result.items() if k.startswith(("garch", "kelly", "ftmo"))},
    }
