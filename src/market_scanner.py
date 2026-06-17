"""
Scanner de ticks temps réel InelidaMarketScan.
Scan les symboles de la watchlist via MT5 et produit des TickSnapshot.
"""

import time
import csv
import os
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

import MetaTrader5 as mt5

from .config import SCAN, OUT
from .mt5_connector import MT5Connector

logger = logging.getLogger("MarketScanner")


@dataclass
class TickSnapshot:
    """Snapshot d'un tick pour un symbole donné."""
    symbol: str
    bid: float
    ask: float
    last: float
    spread: float
    spread_points: float
    time: float            # epoch seconds
    volume: int
    flags: int
    # Deltas vs tick précédent
    bid_delta: float = 0.0
    ask_delta: float = 0.0
    last_delta: float = 0.0
    bid_pct: float = 0.0
    ask_pct: float = 0.0
    last_pct: float = 0.0


class MarketScanner:
    """Scan temps réel d'une watchlist via MT5."""

    def __init__(self, symbols: Optional[List[str]] = None):
        self.mt5 = MT5Connector()
        self.symbols: List[str] = list(symbols or [])
        self._previous: Dict[str, TickSnapshot] = {}
        self._csv_file = None
        self._csv_writer = None

    def prepare(self) -> bool:
        """Initialise MT5 et active tous les symboles de la watchlist."""
        if not self.mt5.initialize():
            logger.error("Impossible d'initialiser MT5.")
            return False

        ti = self.mt5.get_terminal_info()
        if ti:
            logger.info(
                "Terminal MT5: %s | Build %s | Connected=%s | TradeAllowed=%s",
                ti.get("name"), ti.get("build"),
                ti.get("connected"), ti.get("trade_allowed"),
            )

        ai = self.mt5.get_account_info()
        if ai:
            logger.info(
                "Compte: %s @ %s | Balance=%.2f %s | Leverage=1:%s",
                ai.get("login"), ai.get("server"),
                ai.get("balance"), ai.get("currency"),
                ai.get("leverage"),
            )

        for sym in self.symbols:
            ok = self.mt5.select_symbol(sym)
            logger.info("Symbole %s: %s", sym, "OK" if ok else "INDISPONIBLE")

        if OUT.csv_log:
            self._open_csv()

        return True

    def shutdown(self):
        """Ferme proprement CSV + MT5."""
        self._close_csv()
        self.mt5.shutdown()

    def _snapshot_for(self, symbol: str) -> Optional[TickSnapshot]:
        info = mt5.symbol_info(symbol)
        if info is None:
            logger.debug("Symbol_info indisponible pour %s", symbol)
            return None
        point = info.point or 1e-5

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return None

        bid = float(tick.bid)
        ask = float(tick.ask)
        last = float(tick.last) if tick.last else (bid + ask) / 2.0
        spread = ask - bid
        spread_pts = spread / point if point else 0.0

        snap = TickSnapshot(
            symbol=symbol,
            bid=bid,
            ask=ask,
            last=last,
            spread=spread,
            spread_points=spread_pts,
            time=float(tick.time),
            volume=int(tick.volume),
            flags=int(tick.flags),
        )

        prev = self._previous.get(symbol)
        if prev is not None and SCAN.enable_diff:
            snap.bid_delta = bid - prev.bid
            snap.ask_delta = ask - prev.ask
            snap.last_delta = last - prev.last
            snap.bid_pct = (snap.bid_delta / prev.bid * 100.0) if prev.bid else 0.0
            snap.ask_pct = (snap.ask_delta / prev.ask * 100.0) if prev.ask else 0.0
            snap.last_pct = (snap.last_delta / prev.last * 100.0) if prev.last else 0.0

        self._previous[symbol] = snap
        return snap

    def scan_once(self) -> Dict[str, TickSnapshot]:
        """Récupère un tick pour chaque symbole de la watchlist."""
        if not self.mt5.ensure_connected():
            return {}

        results: Dict[str, TickSnapshot] = {}
        for sym in self.symbols:
            snap = self._snapshot_for(sym)
            if snap is not None:
                results[sym] = snap
                self._write_csv(snap)
        return results

    def watch(self, display_fn, max_iterations: Optional[int] = None):
        """
        Boucle de scan temps réel. Appelle display_fn(scanner, snapshot_dict) à chaque tick.
        Si max_iterations est None, boucle infinie (Ctrl+C pour stopper).
        """
        interval = max(SCAN.refresh_ms / 1000.0, 0.05)
        i = 0
        try:
            while True:
                snap = self.scan_once()
                if snap:
                    display_fn(self, snap)
                time.sleep(interval)
                i += 1
                if max_iterations is not None and i >= max_iterations:
                    break
        except KeyboardInterrupt:
            logger.info("Arrêt demandé par l'utilisateur (Ctrl+C).")

    def get_symbol_spec(self, symbol: str) -> Optional[dict]:
        """Renvoie les caractéristiques MT5 d'un symbole sous forme de dict."""
        if not self.mt5.ensure_connected():
            return None
        info = mt5.symbol_info(symbol)
        return info._asdict() if info else None

    def history(self, symbol: str) -> List[dict]:
        """Historique court des derniers ticks (vide si non implémenté dans cette version)."""
        return []

    def _open_csv(self):
        if self._csv_file is not None:
            return
        path = OUT.csv_path
        new_file = not os.path.exists(path)
        try:
            self._csv_file = open(path, "a", newline="", encoding="utf-8")
            self._csv_writer = csv.writer(self._csv_file)
            if new_file:
                self._csv_writer.writerow([
                    "time", "symbol", "bid", "ask", "last",
                    "spread", "spread_points",
                    "bid_delta", "ask_delta", "last_delta",
                    "bid_pct", "ask_pct", "last_pct",
                    "volume", "flags",
                ])
                if OUT.flush_each_tick:
                    self._csv_file.flush()
            logger.info("Journalisation CSV activée → %s", path)
        except Exception as e:
            logger.warning("Impossible d'ouvrir le CSV %s: %s", path, e)
            self._csv_file = None
            self._csv_writer = None

    def _write_csv(self, snap: TickSnapshot):
        if self._csv_writer is None:
            return
        try:
            self._csv_writer.writerow([
                time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(snap.time)),
                snap.symbol, snap.bid, snap.ask, snap.last,
                f"{snap.spread:.6f}", f"{snap.spread_points:.2f}",
                f"{snap.bid_delta:.6f}", f"{snap.ask_delta:.6f}", f"{snap.last_delta:.6f}",
                f"{snap.bid_pct:.4f}", f"{snap.ask_pct:.4f}", f"{snap.last_pct:.4f}",
                snap.volume, snap.flags,
            ])
            if OUT.flush_each_tick:
                self._csv_file.flush()
        except Exception as e:
            logger.debug("Écriture CSV échouée: %s", e)

    def _close_csv(self):
        if self._csv_file is not None:
            try:
                self._csv_file.close()
            except Exception:
                pass
            self._csv_file = None
            self._csv_writer = None
