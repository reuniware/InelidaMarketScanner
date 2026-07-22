"""
Configuration centralisee pour le scanner de marche temps reel InelidaMarketScanner.
"""

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from src.time_utils import now_datetime
from typing import List, Optional


# ─── Timezone Config ───────────────────────────────────────────────────────────
# Mode: "UTC", "BROKER" (temps serveur MT5, typiquement GMT+3 ete/+2 hiver),
#        "PARIS" (CEST/CET)
# Defini via --timezone CLI, ou variable d'env TIMEZONE_MODE, ou defaut BROKER
DEFAULT_TZ_MODE = "BROKER"
TZ_LABELS = {"UTC": "UTC", "BROKER": "BROKER", "PARIS": "Paris"}


def _dst_eu_summer(dt: Optional[datetime] = None) -> bool:
    """Detecte si l'heure d'ete europeenne est en vigueur.

    DST Europe : dernier dimanche de Mars → dernier dimanche d'Octobre.
    """
    if dt is None:
        dt = now_datetime()
    year = dt.year
    # Dernier dimanche de Mars
    mar_last = datetime(year, 3, 31).date()
    mar_dst = mar_last - timedelta(days=(mar_last.weekday() - 6) % 7)
    # Dernier dimanche d'Octobre
    oct_last = datetime(year, 10, 31).date()
    oct_dst = oct_last - timedelta(days=(oct_last.weekday() - 6) % 7)
    return mar_dst <= dt.date() < oct_dst


def tz_offset(mode: str = "") -> int:
    """Retourne le decalage en heures par rapport a UTC pour le mode donne.

    Args:
        mode: "UTC" (0), "BROKER" (serveur MT5, typiquement +3 ete/+2 hiver),
              "PARIS" (CEST +2 / CET +1). Chaine vide = defaut DEFAULT_TZ_MODE.
    """
    m = (mode or DEFAULT_TZ_MODE).upper()
    dst = _dst_eu_summer()
    if m == "UTC":
        return 0
    if m == "PARIS":
        return 2 if dst else 1
    if m == "BROKER":
        return 3 if dst else 2       # Serveur MT5 typique = +3 ete/+2 hiver (EEST/EET)
    return 0


def tz_label(mode: str = "") -> str:
    """Retourne le label lisible (ex: "BROKER", "Paris", "UTC")."""
    m = (mode or DEFAULT_TZ_MODE).upper()
    return TZ_LABELS.get(m, "UTC")


def format_epoch(epoch: float, fmt: str = "%d/%m %H:%M", mode: str = "") -> str:
    """Formate un timestamp epoch dans la timezone configuree avec le label.

    Exemples:
        format_epoch(ts, "%d/%m %Hh", "BROKER") -> "17/07 14h BROKER"
        format_epoch(ts, "%d/%m %H:%M", "PARIS") -> "17/07 13:30 Paris"
        format_epoch(ts, "%d/%m", "BROKER") -> "17/07 BROKER"   (label meme sans heure)
    """
    m = (mode or DEFAULT_TZ_MODE).upper()
    off = tz_offset(m)
    lbl = tz_label(m)
    dt = datetime.fromtimestamp(epoch, timezone.utc) + timedelta(hours=off)
    return f"{dt.strftime(fmt)} {lbl}"


def load_dotenv(env_path: Optional[str] = None) -> None:
    """Charge les variables d'environnement depuis un fichier .env.

    Supporte UTF-8 et UTF-16 (cree par PowerShell).
    Ne surcharge pas les variables deja definies.

    Args:
        env_path: Chemin vers le fichier .env (defaut: .env a la racine).
    """
    if env_path is None:
        env_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".env",
        )
    if not os.path.isfile(env_path):
        return

    # Essayer plusieurs encodages (PowerShell cree du UTF-16 LE)
    content = None
    for encoding in ("utf-8", "utf-16", "utf-16-le", "utf-16-be", "latin-1"):
        try:
            with open(env_path, encoding=encoding) as f:
                content = f.read()
            break
        except (UnicodeDecodeError, UnicodeError):
            continue

    if content is None:
        return

    # Enlever le BOM UTF-16 si present (\ufeff)
    content = content.lstrip("\ufeff")

    for line in content.split("\n"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            k = k.strip()
            if k and k not in os.environ:
                os.environ[k] = v.strip().strip('"').strip("'")


# ─── Watchlist par defaut ──────────────────────────────────────────────────────
# Symboles surveilles par defaut si l'utilisateur ne precise rien.
# Tu peux surcharger via la variable d'environnement INELIDA_WATCHLIST
# (separee par des virgules) ou via l'option --symbols du CLI.
DEFAULT_WATCHLIST: List[str] = [
    # ── Indice Dollar (filtre macro) ──
    "DXY.cash",           # INDICE USD — FILTRE MACRO ESSENTIEL (manquait!)

    # ── Forex majeurs (paires USD) ──
    "EURUSD",              # 1e paire mondiale, 57.6% du DXY
    "GBPUSD",              # 2e paire, forte volatilite London
    "USDJPY",              # 3e paire, proxy USD/JPY, indicateur avance
    "AUDUSD",              # Correlations matieres premieres
    "USDCAD",              # Correlation petrole
    "USDCHF",              # Safe haven CHF

    # ── Cross (contexte) ──
    "EURJPY",              # Contexte EUR/JPY (divergences DXY)
    "GBPJPY",              # Contexte GBP/JPY (forte volatilite)

    # ── Matieres premieres ──
    "XAUUSD",              # Or — safe haven, correlation inverse USD

    # ── Indices US ──
    "US30.cash",           # Dow Jones
    "US500.cash",          # S&P 500
    "US100.cash",          # Nasdaq
]


# ─── Connexion MT5 ─────────────────────────────────────────────────────────────
@dataclass
class MT5Config:
    terminal_path: Optional[str] = None    # Laisser None pour auto-detection par MT5
    login: Optional[int] = None            # MT5.LOGIN explicite (optionnel)
    password: Optional[str] = None
    server: Optional[str] = None
    timeout: int = 30                       # secondes pour initialize()
    retries: int = 3
    retry_delay: float = 2.0


# ─── Scanner ───────────────────────────────────────────────────────────────────
@dataclass
class ScanConfig:
    refresh_ms: int = 500                  # Temps minimum entre deux scans (ms)
    history_ticks: int = 20                # Nombre de ticks conserves par symbole
    enable_diff: bool = True               # Calculer deltas (variations depuis dernier tick)
    enable_alerts: bool = False            # Notifier sur franchissement de seuil


# ─── Sortie ────────────────────────────────────────────────────────────────────
@dataclass
class OutputConfig:
    csv_log: bool = False                  # Journaliser les ticks dans un CSV
    csv_path: str = "./inelida_ticks.csv"
    pretty: bool = True                    # Affichage console soigne (sinon brut)
    flush_each_tick: bool = True           # Flush immediat du CSV a chaque tick


# ─── Base de données ────────────────────────────────────────────────────────────
@dataclass
class DBConfig:
    """Configuration de la base de données SQLite."""
    path: str = "./inelida_market_data.db"   # Chemin du fichier SQLite
    auto_save_asian: bool = True               # Sauvegarder auto les ranges asiatiques
    auto_save_sweeps: bool = True              # Sauvegarder auto les sweeps détectés


# ─── Alertes ───────────────────────────────────────────────────────────────────
@dataclass
class AlertConfig:
    # L'alerte se declenche si le prix bouge de X % ou plus depuis le tick precedent.
    pct_change_threshold: float = 0.10     # 0.10 %
    # Ou si le spread depasse ce multiple du spread typique (en points).
    spread_spike_multiplier: float = 2.0


# ─── Liquidity Sweeps ──────────────────────────────────────────────────────────
@dataclass
class SweepConfig:
    """Parametres du detecteur de sweeps ICT (BSL / SSL)."""
    timeframe: str = "M15"             # Timeframe de travail (M1, M5, M15, M30, H1, H4, D1)
    fractal_n: int = 2                  # Williams fractals: N bougies avant/apres
    lookback: int = 50                  # Combien de bougies en arriere pour chercher les swings
    sensitivity: int = 5                # Dernieres N bougies scrutees pour les sweeps
    max_symbols: int = 50               # Garde-fou (Market Watch peut contenir 200+ symboles)
    min_distance_pct: float = 0.0       # Filtre distance min entre swing et prix actuel (0 = pas de filtre)
    sort_by_distance: bool = True      # Trier les sweeps du plus proche au plus loin du prix actuel


@dataclass
class AsianSessionConfig:
    """Parametres du detecteur de range asiatique + sweeps post-Asian."""
    start_utc: int = 0          # Heure de debut de la session asiatique (UTC), 0 = minuit
    end_utc: int = 8            # Heure de fin (UTC), 8 = 08:00 UTC
    timeframe: str = "H1"       # H1 par defaut, M15 possible
    max_symbols: int = 50       # garde-fou Market Watch
    max_bars_after_session: int = 240  # ~10 jours H1 post-Asian a scanner max
    fib_base: str = "AH"        # Base Fibonacci: "AH" (extensions depuis le haut, ICT agressif)
                                # ou "AL" (extensions depuis le swing low, fib standard)


@dataclass
class EliteFilterConfig:
    """Filtre ELITE v2 (actuel) : badge informatif sur les trades a haute probabilite.
    Backteste sur 438 trades (29 rapports) : 97.7-100% WR, +0.29-0.35R/trade.
    Regle : heure 09:00-13:00 UTC + type IN {FOREX_USD,INDEX,METAL}
            + aucun filtre RR + spread < 0.50%.

    Notes optimisation Juin 2026 :
    - Fenetre etendue de 10:30 a 13:00 : meme winrate, +3 trades
    - RR >= 0.5 retire : les trades avec SL large (RR bas) winrate + eleve
    - FOREX_CROSS retire : dilue le winrate (97.7% -> 100% sans cross)
    - Spread < 0.50% : le spread n'a quasiment pas d'impact"""
    enabled: bool = True
    start_hour_utc: int = 9
    start_minute_utc: int = 0
    end_hour_utc: int = 13
    end_minute_utc: int = 0
    min_rr: float = 0.0
    max_spread_pct: float = 0.50
    allowed_types: tuple = ("FOREX_USD", "INDEX", "METAL")


@dataclass
class EliteV1FilterConfig:
    """Filtre ELITE v1 original (backtest 128 trades, 5 jours, 29 rapports).
    Criteres originaux : fenetre 09:00-10:30 UTC, RR >= 0.5, spread < 0.10%,
    types autorises : FOREX_USD, INDEX, METAL, FOREX_CROSS.
    Winrate backteste v1 : 100% sur 6 trades clos (echantillon reduit).
    Garde pour comparaison avec v2."""
    enabled: bool = True
    start_hour_utc: int = 9
    start_minute_utc: int = 0
    end_hour_utc: int = 10
    end_minute_utc: int = 30
    min_rr: float = 0.5
    max_spread_pct: float = 0.10
    allowed_types: tuple = ("FOREX_USD", "INDEX", "METAL", "FOREX_CROSS")


# ─── Instances globales ────────────────────────────────────────────────────────
MT5 = MT5Config(
    # Exemple pour FTMO (adapte selon ton broker) :
    # terminal_path=r"C:\Program Files\FTMO Global Markets MT5 Terminal\terminal64.exe",
)
SCAN = ScanConfig()
OUT = OutputConfig()
ALERT = AlertConfig()
DB = DBConfig()
SWEEP = SweepConfig()
ASIAN = AsianSessionConfig()
ELITE = EliteFilterConfig()
ELITE_V1 = EliteV1FilterConfig()


def _normalize_symbol(s: str) -> str:
    """Normalise un symbole MT5 : uppercase sauf apres un point (.cash etc)."""
    s = s.strip()
    if not s:
        return ""
    if '.' in s:
        base, ext = s.split('.', 1)
        return f"{base.upper()}.{ext}"
    return s.upper()


def resolve_watchlist(cli_symbols: Optional[List[str]] = None) -> List[str]:
    """Resout la watchlist finale selon CLI > variable d'env > defaut."""
    if cli_symbols:
        return [ns for s in cli_symbols if (ns := _normalize_symbol(s))]
    env = os.environ.get("INELIDA_WATCHLIST")
    if env:
        return [ns for s in env.split(",") if (ns := _normalize_symbol(s))]
    return list(DEFAULT_WATCHLIST)
