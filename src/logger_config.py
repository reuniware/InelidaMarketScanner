"""
Configuration centralisee du logging pour InelidaMarketScan.

Tous les scripts doivent utiliser setup_logging() pour obtenir :
  - Sortie console (stream)
  - Fichier dans logs/<script_name>_YYYY-MM-DD.log

Usage:
    from src.logger_config import setup_logging
    logger = setup_logging("mon_script")

    # Ou avec parametres avances :
    logger = setup_logging("mon_script", level="DEBUG", to_file=True)
"""

import logging
import os
import sys
from datetime import datetime


# ─── Constantes ──────────────────────────────────────────────────────────────
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(PROJECT_DIR, "logs")


def setup_logging(
    name: str,
    level: str = "INFO",
    to_file: bool = True,
    to_console: bool = True,
    fmt: str = "%(asctime)s | %(levelname)-7s | %(name)-18s | %(message)s",
    datefmt: str = "%H:%M:%S",
) -> logging.Logger:
    """Configure et retourne un logger avec sortie console + fichier.

    Args:
        name: Nom du logger (ex: "main", "live_alerts", "auto_scan")
        level: Niveau de log (DEBUG, INFO, WARNING, ERROR)
        to_file: Ecrire dans logs/<name>_YYYY-MM-DD.log
        to_console: Ecrire sur stdout
        fmt: Format des messages
        datefmt: Format de la date

    Returns:
        Logger configure.
    """
    # Creer le dossier logs/ si necessaire
    if to_file:
        os.makedirs(LOGS_DIR, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Configurer aussi le root logger pour capturer les logs des librairies tierces (MT5, etc.)
    root = logging.getLogger()
    if root.level == logging.WARNING and getattr(logging, level.upper(), logging.INFO) != logging.WARNING:
        root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Eviter les handlers dupliques
    if logger.handlers:
        return logger

    formatter = logging.Formatter(fmt, datefmt=datefmt)

    # ── Handler console ──
    if to_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # ── Handler fichier ──
    if to_file:
        today = datetime.now().strftime("%Y-%m-%d")
        log_filename = f"{name}_{today}.log"
        log_path = os.path.join(LOGS_DIR, log_filename)

        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_logs_dir() -> str:
    """Retourne le chemin absolu du dossier logs/."""
    return LOGS_DIR
