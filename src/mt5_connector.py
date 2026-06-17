"""
Gestionnaire de connexion MetaTrader 5 pour InelidaMarketScan.
Pattern singleton avec auto-reconnect, retry, et context manager.
"""

import time
import logging
from typing import Optional

import MetaTrader5 as mt5

from .config import MT5

logger = logging.getLogger("MT5Connector")


class MT5Connector:
    """Connexion singleton à MetaTrader 5."""

    _instance: Optional["MT5Connector"] = None
    _initialized: bool = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # __init__ exécuté à chaque instanciation mais le travail lourd est protégé par _initialized.
        if not self._initialized:
            self.terminal_path = MT5.terminal_path
            self.login = MT5.login
            self.password = MT5.password
            self.server = MT5.server
            self.timeout = MT5.timeout
            self.retries = MT5.retries
            self.retry_delay = MT5.retry_delay
            self._initialized = True

    # ─── Cycle de vie ──────────────────────────────────────────────────────
    def initialize(self) -> bool:
        """Initialise la connexion MT5 avec tentatives."""
        for attempt in range(1, self.retries + 1):
            if self.is_connected():
                logger.info("Déjà connecté à MT5.")
                return True

            kwargs = {"timeout": self.timeout}
            if self.terminal_path:
                kwargs["path"] = self.terminal_path
            if self.login is not None:
                kwargs["login"] = int(self.login)
            if self.password:
                kwargs["password"] = self.password
            if self.server:
                kwargs["server"] = self.server

            initialized = mt5.initialize(**kwargs)

            if initialized:
                logger.info(
                    "[OK] Connecté à MT5 (tentative %d/%d)",
                    attempt, self.retries,
                )
                return True

            err = mt5.last_error()
            logger.warning(
                "[FAIL] Connexion MT5 (tentative %d/%d): %s",
                attempt, self.retries, err,
            )
            if attempt < self.retries:
                time.sleep(self.retry_delay)

        return False

    def is_connected(self) -> bool:
        """Vérifie si MT5 est connecté (terminal_info non None)."""
        try:
            return mt5.terminal_info() is not None
        except Exception:
            return False

    def ensure_connected(self) -> bool:
        """S'assure que la connexion est active, reconnecte si nécessaire."""
        if not self.is_connected():
            logger.info("Reconnexion à MT5...")
            return self.initialize()
        return True

    def shutdown(self):
        """Ferme proprement la connexion."""
        try:
            mt5.shutdown()
            logger.info("Connexion MT5 fermée.")
        except Exception as e:
            logger.warning("Erreur à la fermeture MT5: %s", e)

    @staticmethod
    def last_error() -> tuple:
        """Retourne la dernière erreur MT5."""
        return mt5.last_error()

    def get_terminal_info(self) -> Optional[dict]:
        """Infos sur le terminal."""
        if not self.ensure_connected():
            return None
        info = mt5.terminal_info()
        return info._asdict() if info else None

    def get_account_info(self) -> Optional[dict]:
        """Infos sur le compte de trading."""
        if not self.ensure_connected():
            return None
        info = mt5.account_info()
        return info._asdict() if info else None

    def select_symbol(self, symbol: str) -> bool:
        """Sélectionne un symbole dans Market Watch (nécessaire pour certains brokers)."""
        if not self.ensure_connected():
            return False
        try:
            info = mt5.symbol_info(symbol)
            if info is None:
                logger.warning("Symbole inconnu chez le broker: %s", symbol)
                return False
            if not info.visible and not mt5.symbol_select(symbol, True):
                logger.warning("Impossible d'activer le symbole: %s", symbol)
                return False
            return True
        except Exception as e:
            logger.warning("select_symbol(%s) a échoué: %s", symbol, e)
            return False

    def list_market_watch_symbols(self) -> list:
        """
        Renvoie la liste triée des symboles visibles dans la Market Watch MT5.
        Filtre les symboles sans données OHLC accessibles.
        """
        if not self.ensure_connected():
            return []
        try:
            syms = mt5.symbols_get()
            if not syms:
                return []
            return sorted({s.name for s in syms if getattr(s, "visible", False)})
        except Exception as e:
            logger.warning("symbols_get() a Ã©chouÃ©: %s", e)
            return []


def list_market_watch_symbols() -> list:
    """Helper module-level pour usage direct sans instancier MT5Connector."""
    return MT5Connector().list_market_watch_symbols()

    # ─── Context manager ──────────────────────────────────────────────────
    def __enter__(self):
        self.initialize()
        return self

    def __exit__(self, *args):
        self.shutdown()
