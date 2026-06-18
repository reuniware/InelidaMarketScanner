"""
Configuration centralisee pour le scanner de marche temps reel InelidaMarketScanner.
"""

import os
from dataclasses import dataclass
from typing import List, Optional


# ─── Watchlist par defaut ──────────────────────────────────────────────────────
# Symboles surveilles par defaut si l'utilisateur ne precise rien.
# Tu peux surcharger via la variable d'environnement INELIDA_WATCHLIST
# (separee par des virgules) ou via l'option --symbols du CLI.
DEFAULT_WATCHLIST: List[str] = [
    # Forex majeurs
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "AUDUSD",
    "USDCAD",
    "USDCHF",
    "NZDUSD",
    # Metaux
    "XAUUSD",
    "XAGUSD",
    # Indices
    "US30",
    "NAS100",
    "SPX500",
    # Crypto (selon broker)
    "BTCUSD",
    "ETHUSD",
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


def resolve_watchlist(cli_symbols: Optional[List[str]] = None) -> List[str]:
    """Resout la watchlist finale selon CLI > variable d'env > defaut."""
    if cli_symbols:
        return [s.strip().upper() for s in cli_symbols if s.strip()]
    env = os.environ.get("INELIDA_WATCHLIST")
    if env:
        return [s.strip().upper() for s in env.split(",") if s.strip()]
    return list(DEFAULT_WATCHLIST)
