"""
Trade Tracker — Suivi P&L automatisé des setups Diamond dans le temps.

Sauvegarde chaque scan Diamond, tracke l'évolution du prix par rapport au SL/TP,
calcule le P&L final (SL touché, TP touché, ou encore ouvert), et génère
des rapports de performance.

Tables dans la base SQLite :
  - diamond_trades    : chaque setup détecté = une ligne (mise à jour à chaque scan)
  - diamond_snapshots : historique des prix et distances (time-series)

Usage:
    from trade_tracker import TradeTracker
    tracker = TradeTracker()
    tracker.save_setups(results)       # après un scan Diamond
    tracker.update_all()               # avant chaque rapport
    report = tracker.get_report()      # résumé P&L
    history = tracker.get_history(...) # détail d'un trade
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .database import DatabaseManager, get_db
from .diamond_scanner import DiamondResult

logger = logging.getLogger("TradeTracker")

UTC = timezone.utc

# ─── Constants ────────────────────────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS diamond_trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT    NOT NULL,         -- UUID de la session de scan
    symbol          TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'OPEN',  -- 'OPEN' / 'CLOSED'

    -- Snapshot au moment du scan
    scan_time       REAL    NOT NULL,         -- epoch UTC
    price           REAL    NOT NULL,
    score           INTEGER NOT NULL,
    max_score       INTEGER NOT NULL,
    bias            TEXT    NOT NULL,
    quality         TEXT    NOT NULL,
    alignment       INTEGER NOT NULL DEFAULT 0,
    sl              REAL    NOT NULL,
    tp              REAL    NOT NULL,
    tp_label        TEXT,
    rr              REAL    NOT NULL,
    horizon         TEXT,
    asian_high      REAL,
    asian_low       REAL,
    kj_h4           REAL,
    kj_d1           REAL,
    d_kj4           REAL,
    d_kj_d1         REAL,

    -- Résultat P&L
    close_price     REAL,                      -- prix au moment de la fermeture
    close_reason    TEXT,                      -- 'SL_HIT' / 'TP_HIT' / 'MANUAL' / 'EXPIRED'
    close_time      REAL,
    pnl_pips        REAL,                      -- en pips (positif = gain)
    pnl_percent     REAL,                      -- en % du risque initial
    pnl_rr          REAL,                      -- RR réellement réalisé

    -- Métadonnées
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now')),

    UNIQUE(session_id, symbol)
);

CREATE TABLE IF NOT EXISTS diamond_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id        INTEGER NOT NULL,
    timestamp       REAL    NOT NULL,          -- epoch UTC de la mise à jour
    price           REAL    NOT NULL,
    dist_to_sl_pips REAL,                      -- distance au SL en pips
    dist_to_tp_pips REAL,                      -- distance au TP en pips
    dist_to_sl_pct  REAL,                      -- % du range SL-TP (0 = SL, 100 = TP)
    snapshot_type   TEXT    NOT NULL DEFAULT 'UPDATE',  -- 'SAVE' / 'UPDATE' / 'CLOSE'

    FOREIGN KEY (trade_id) REFERENCES diamond_trades(id)
);

CREATE INDEX IF NOT EXISTS idx_trades_status
    ON diamond_trades(status);

CREATE INDEX IF NOT EXISTS idx_trades_session
    ON diamond_trades(session_id);

CREATE INDEX IF NOT EXISTS idx_trades_symbol
    ON diamond_trades(symbol);

CREATE INDEX IF NOT EXISTS idx_snapshots_trade
    ON diamond_snapshots(trade_id, timestamp);

CREATE INDEX IF NOT EXISTS idx_snapshots_trade_latest
    ON diamond_snapshots(trade_id, timestamp DESC);
"""


# ─── Data classes ─────────────────────────────────────────────────────────

@dataclass
class TradeSnapshot:
    """Un instantané d'un trade à un moment T."""
    timestamp: float
    price: float
    dist_to_sl_pips: float
    dist_to_tp_pips: float
    dist_to_sl_pct: float
    snapshot_type: str = "UPDATE"


@dataclass
class TrackedTrade:
    """Un trade suivi dans le temps (lecture depuis la DB)."""
    id: int
    session_id: str
    symbol: str
    status: str
    scan_time: float
    price: float
    score: int
    max_score: int
    bias: str
    quality: str
    alignment: int
    sl: float
    tp: float
    tp_label: str
    rr: float
    horizon: str
    asian_high: float
    asian_low: float
    kj_h4: float
    d_kj4: float
    close_price: Optional[float] = None
    close_reason: Optional[str] = None
    close_time: Optional[float] = None
    pnl_pips: Optional[float] = None
    pnl_percent: Optional[float] = None
    pnl_rr: Optional[float] = None
    snapshots: List[TradeSnapshot] = field(default_factory=list)


# ─── Helpers ──────────────────────────────────────────────────────────────

def _pips_from_price(sym: str, price: float, level: float) -> float:
    """Calcule la distance en pips entre price et level."""
    if 'XAUUSD' in sym: return (price - level) * 10
    elif 'JPY' in sym or 'DXY' in sym: return (price - level) * 100
    else: return (price - level) * 10000


def _pip_factor(sym: str) -> float:
    if 'XAUUSD' in sym: return 10.0
    elif 'JPY' in sym or 'DXY' in sym: return 100.0
    else: return 10000.0


def _sl_range_pct(price: float, sl: float, tp: float) -> float:
    """Calcule la position du prix en % du range SL→TP.
    0% = au SL, 100% = au TP."""
    total = abs(tp - sl)
    if total == 0: return 50.0
    return abs(price - sl) / total * 100.0


def _check_close(price: float, sl: float, tp: float, bias: str) -> Optional[Tuple[str, float]]:
    """Vérifie si le prix a touché SL ou TP.
    
    Returns:
        (reason, level) ou None si toujours en vie.
    """
    if bias == "BULL":
        if price <= sl: return ("SL_HIT", sl)
        if price >= tp: return ("TP_HIT", tp)
    elif bias == "BEAR":
        if price >= sl: return ("SL_HIT", sl)
        if price <= tp: return ("TP_HIT", tp)
    return None


# ─── Main Tracker ─────────────────────────────────────────────────────────

class TradeTracker:
    """Suit les trades Diamond dans le temps avec snapshots et calcul P&L."""

    def __init__(self, db: Optional[DatabaseManager] = None):
        self.db = db or get_db()
        self._ensure_schema()

    # ── Private ────────────────────────────────────────────────────────────

    def _ensure_schema(self):
        """Crée les tables si elles n'existent pas."""
        conn = self.db.conn
        if conn is None:
            logger.error("Impossible d'ouvrir la DB pour TradeTracker")
            return
        try:
            conn.executescript(_SCHEMA_SQL)
            conn.commit()
            logger.debug("Schema diamond_trades ensure")
        except Exception as e:
            logger.error("Erreur creation schema trade_tracker: %s", e)

    def _pips(self, sym: str, price: float, level: float) -> float:
        return _pips_from_price(sym, price, level)

    def _pip_factor(self, sym: str) -> float:
        return _pip_factor(sym)

    def _session_id(self) -> str:
        return str(uuid.uuid4())[:8]  # court pour lisibilité

    # ── Save: enregistre les résultats d'un scan ──────────────────────────

    def save_setups(self, results: List[DiamondResult], session_id: Optional[str] = None) -> int:
        """Sauvegarde les setups actifs (BULL/BEAR non WAIT) d'un scan Diamond.
        
        Args:
            results: Liste des DiamondResult du scan.
            session_id: Optionnel, pour grouper plusieurs scans.
        
        Returns:
            Nombre de trades sauvegardés.
        """
        conn = self.db.conn
        if conn is None:
            logger.error("DB non disponible")
            return 0

        sid = session_id or self._session_id()
        now = time.time()
        saved = 0

        # Ne garder que les setups actifs (non FLAT, non WAIT)
        active = [r for r in results if r.bias != "FLAT" and r.quality != "WAIT"]

        if not active:
            logger.info("Aucun setup actif a sauvegarder")
            return 0

        for r in active:
            try:
                # UPSERT: si le trade existe déjà (même symbol + session), on met à jour
                conn.execute(
                    """
                    INSERT INTO diamond_trades (
                        session_id, symbol, status,
                        scan_time, price, score, max_score, bias, quality, alignment,
                        sl, tp, tp_label, rr, horizon,
                        asian_high, asian_low, kj_h4, kj_d1, d_kj4, d_kj_d1,
                        updated_at
                    ) VALUES (?, ?, 'OPEN',
                              ?, ?, ?, ?, ?, ?, ?,
                              ?, ?, ?, ?, ?,
                              ?, ?, ?, ?, ?, ?,
                              datetime('now'))
                    ON CONFLICT(session_id, symbol) DO UPDATE SET
                        status = 'OPEN',
                        scan_time = excluded.scan_time,
                        price = excluded.price,
                        score = excluded.score,
                        max_score = excluded.max_score,
                        bias = excluded.bias,
                        quality = excluded.quality,
                        alignment = excluded.alignment,
                        sl = excluded.sl,
                        tp = excluded.tp,
                        tp_label = excluded.tp_label,
                        rr = excluded.rr,
                        horizon = excluded.horizon,
                        asian_high = excluded.asian_high,
                        asian_low = excluded.asian_low,
                        kj_h4 = excluded.kj_h4,
                        kj_d1 = excluded.kj_d1,
                        d_kj4 = excluded.d_kj4,
                        d_kj_d1 = excluded.d_kj_d1,
                        updated_at = datetime('now')
                    """,
                    (
                        sid, r.symbol,
                        now, r.price, r.score, r.max_score, r.bias, r.quality, r.alignment,
                        r.sl, r.tp, r.tp_label, r.rr, r.horizon,
                        r.asian_high, r.asian_low, r.kj_h4, r.kj_d1, r.d_kj4, r.d_kj_d1,
                    ),
                )

                # Récupérer l'ID du trade fraîchement créé
                cur = conn.execute(
                    "SELECT id FROM diamond_trades WHERE session_id = ? AND symbol = ?",
                    (sid, r.symbol),
                )
                row = cur.fetchone()
                trade_id = row["id"] if row else 0

                # Premier snapshot (SAVE)
                dist_sl = self._pips(r.symbol, r.price, r.sl)
                dist_tp = self._pips(r.symbol, r.price, r.tp)
                pct = _sl_range_pct(r.price, r.sl, r.tp)

                conn.execute(
                    """
                    INSERT INTO diamond_snapshots (trade_id, timestamp, price,
                        dist_to_sl_pips, dist_to_tp_pips, dist_to_sl_pct, snapshot_type)
                    VALUES (?, ?, ?, ?, ?, ?, 'SAVE')
                    """,
                    (trade_id, now, r.price, abs(dist_sl), abs(dist_tp), pct),
                )
                saved += 1

            except Exception as e:
                logger.error("Erreur sauvegarde trade %s: %s", r.symbol, e)

        conn.commit()
        logger.info("TradeTracker: %d setup(s) sauvegarde(s) (session %s)", saved, sid)
        return saved

    # ── Update: met à jour les trades ouverts avec le prix actuel ─────────

    def update_all(self, prices: Optional[Dict[str, float]] = None) -> int:
        """Met à jour tous les trades OPEN avec les prix actuels.
        
        Args:
            prices: Dictionnaire {symbol: price} optionnel.
                    Si None, le tracker ne peut pas mettre à jour la distance
                    mais peut vérifier les SL/TP si price est fourni.
        
        Returns:
            Nombre de trades mis à jour ou fermés.
        """
        conn = self.db.conn
        if conn is None:
            return 0

        trades = self._get_open_trades()
        if not trades:
            return 0

        now = time.time()
        updated = 0

        for t in trades:
            symbol = t["symbol"]
            price = prices.get(symbol) if prices else t["price"]

            if price is None:
                continue

            sl = t["sl"]
            tp = t["tp"]
            bias = t["bias"]
            trade_id = t["id"]

            # Vérifier si SL ou TP touché
            close_result = _check_close(price, sl, tp, bias)

            if close_result:
                reason, _ = close_result
                risk_pips = abs(_pips_from_price(symbol, tp, sl)) if tp != sl else 1
                pnl_pips = risk_pips if reason == "TP_HIT" else -risk_pips
                pnl_pct = (pnl_pips / risk_pips * 100) if risk_pips != 0 else 0
                pnl_rr = abs(pnl_pips / risk_pips) if risk_pips != 0 else 0

                # Fermer le trade
                conn.execute(
                    """
                    UPDATE diamond_trades SET
                        status = 'CLOSED',
                        close_price = ?,
                        close_reason = ?,
                        close_time = ?,
                        pnl_pips = ?,
                        pnl_percent = ?,
                        pnl_rr = ?,
                        updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    (level, reason, now, pnl_pips, pnl_pct, pnl_rr, trade_id),
                )

                # Snapshot de fermeture
                dist_sl = _pips_from_price(symbol, price, sl)
                dist_tp = _pips_from_price(symbol, price, tp)
                pct = _sl_range_pct(price, sl, tp)
                conn.execute(
                    """
                    INSERT INTO diamond_snapshots (trade_id, timestamp, price,
                        dist_to_sl_pips, dist_to_tp_pips, dist_to_sl_pct, snapshot_type)
                    VALUES (?, ?, ?, ?, ?, ?, 'CLOSE')
                    """,
                    (trade_id, now, price, abs(dist_sl), abs(dist_tp), pct),
                )
                logger.info("Trade %s %s: %s (P&L: %.1fp, %.0f%% du risque)",
                           symbol, trade_id, reason, pnl_pips, pnl_pct)
            else:
                # Simple mise à jour de la position
                dist_sl = _pips_from_price(symbol, price, sl)
                dist_tp = _pips_from_price(symbol, price, tp)
                pct = _sl_range_pct(price, sl, tp)

                conn.execute(
                    """
                    UPDATE diamond_trades SET
                        price = ?,
                        updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    (price, trade_id),
                )

                conn.execute(
                    """
                    INSERT INTO diamond_snapshots (trade_id, timestamp, price,
                        dist_to_sl_pips, dist_to_tp_pips, dist_to_sl_pct, snapshot_type)
                    VALUES (?, ?, ?, ?, ?, ?, 'UPDATE')
                    """,
                    (trade_id, now, price, abs(dist_sl), abs(dist_tp), pct),
                )
            updated += 1

        conn.commit()
        return updated

    # ── Get open trades ────────────────────────────────────────────────────

    def _get_open_trades(self) -> List[dict]:
        """Récupère tous les trades OPEN."""
        conn = self.db.conn
        if conn is None:
            return []
        try:
            cur = conn.execute("SELECT * FROM diamond_trades WHERE status = 'OPEN'")
            return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.error("Erreur get_open_trades: %s", e)
            return []

    # ── Report: génère un rapport P&L ─────────────────────────────────────

    def get_report(self, limit: int = 20) -> Dict[str, Any]:
        """Génère un rapport complet P&L.
        
        Returns:
            Dictionnaire avec stats globales + liste des trades.
        """
        conn = self.db.conn
        if conn is None:
            return {"error": "DB non disponible"}

        report: Dict[str, Any] = {
            "total_trades": 0,
            "open_trades": 0,
            "closed_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "total_pnl_pips": 0.0,
            "avg_pnl_pips": 0.0,
            "best_trade": None,
            "worst_trade": None,
            "avg_rr": 0.0,
            "trades": [],
        }

        try:
            # Totaux
            cur = conn.execute("SELECT COUNT(*) FROM diamond_trades")
            report["total_trades"] = cur.fetchone()[0]

            cur = conn.execute("SELECT COUNT(*) FROM diamond_trades WHERE status = 'OPEN'")
            report["open_trades"] = cur.fetchone()[0]

            cur = conn.execute("SELECT COUNT(*) FROM diamond_trades WHERE status = 'CLOSED'")
            report["closed_trades"] = cur.fetchone()[0]

            # Trades fermés
            cur = conn.execute(
                "SELECT * FROM diamond_trades WHERE status = 'CLOSED' ORDER BY close_time DESC"
            )
            closed = cur.fetchall()

            wins = [t for t in closed if t["pnl_pips"] is not None and t["pnl_pips"] > 0]
            losses = [t for t in closed if t["pnl_pips"] is not None and t["pnl_pips"] <= 0]

            report["wins"] = len(wins)
            report["losses"] = len(losses)
            report["win_rate"] = round(len(wins) / len(closed) * 100, 1) if closed else 0.0

            if closed:
                pnls = [t["pnl_pips"] for t in closed if t["pnl_pips"] is not None]
                report["total_pnl_pips"] = round(sum(pnls), 1)
                report["avg_pnl_pips"] = round(sum(pnls) / len(pnls), 1) if pnls else 0.0

                rrs = [t["pnl_rr"] for t in closed if t["pnl_rr"] is not None]
                report["avg_rr"] = round(sum(rrs) / len(rrs), 2) if rrs else 0.0

                if wins:
                    best = max(wins, key=lambda t: t["pnl_pips"] or 0)
                    report["best_trade"] = {
                        "symbol": best["symbol"],
                        "pnl_pips": best["pnl_pips"],
                        "reason": best["close_reason"],
                    }

                if losses:
                    worst = min(losses, key=lambda t: t["pnl_pips"] or 0)
                    report["worst_trade"] = {
                        "symbol": worst["symbol"],
                        "pnl_pips": worst["pnl_pips"],
                        "reason": worst["close_reason"],
                    }

            # Derniers trades
            cur = conn.execute(
                """SELECT * FROM diamond_trades 
                   ORDER BY created_at DESC LIMIT ?""",
                (limit,),
            )
            report["trades"] = [dict(t) for t in cur.fetchall()]

        except Exception as e:
            logger.error("Erreur generation rapport: %s", e)
            report["error"] = str(e)

        return report

    # ── History: détail d'un trade ─────────────────────────────────────────

    def get_history(self, trade_id: int) -> Optional[Dict[str, Any]]:
        """Récupère l'historique complet d'un trade (infos + snapshots)."""
        conn = self.db.conn
        if conn is None:
            return None

        try:
            cur = conn.execute(
                "SELECT * FROM diamond_trades WHERE id = ?", (trade_id,)
            )
            trade = cur.fetchone()
            if trade is None:
                return None

            cur = conn.execute(
                """SELECT * FROM diamond_snapshots 
                   WHERE trade_id = ? ORDER BY timestamp ASC""",
                (trade_id,),
            )
            snapshots = [dict(s) for s in cur.fetchall()]

            result = dict(trade)
            result["snapshots"] = snapshots
            return result

        except Exception as e:
            logger.error("Erreur get_history(%d): %s", trade_id, e)
            return None

    # ── List all sessions ──────────────────────────────────────────────────

    def list_sessions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Liste les sessions de scan enregistrées."""
        conn = self.db.conn
        if conn is None:
            return []

        try:
            cur = conn.execute(
                """SELECT session_id, 
                          MIN(scan_time) as first_scan,
                          COUNT(*) as trades_count,
                          SUM(CASE WHEN status = 'OPEN' THEN 1 ELSE 0 END) as open_count,
                          SUM(CASE WHEN status = 'CLOSED' THEN 1 ELSE 0 END) as closed_count
                   FROM diamond_trades
                   GROUP BY session_id
                   ORDER BY first_scan DESC
                   LIMIT ?""",
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.error("Erreur list_sessions: %s", e)
            return []

    # ── Close specific trade manually ──────────────────────────────────────

    def close_trade(self, trade_id: int, reason: str = "MANUAL",
                    price: Optional[float] = None) -> bool:
        """Ferme manuellement un trade."""
        conn = self.db.conn
        if conn is None:
            return False

        try:
            cur = conn.execute(
                "SELECT * FROM diamond_trades WHERE id = ? AND status = 'OPEN'",
                (trade_id,),
            )
            trade = cur.fetchone()
            if trade is None:
                logger.warning("Trade %d introuvable ou deja ferme", trade_id)
                return False

            close_price = price or trade["price"]
            sl, tp, bias = trade["sl"], trade["tp"], trade["bias"]
            symbol = trade["symbol"]

            # Calcul P&L
            if bias == "BULL":
                pnl_pips = _pips_from_price(symbol, close_price, sl)
            else:
                pnl_pips = _pips_from_price(symbol, sl, close_price)

            risk_pips = abs(_pips_from_price(symbol, tp, sl)) if tp != sl else 1
            pnl_pct = (pnl_pips / risk_pips * 100) if risk_pips != 0 else 0
            pnl_rr = abs(pnl_pips / risk_pips) if risk_pips != 0 else 0

            conn.execute(
                """
                UPDATE diamond_trades SET
                    status = 'CLOSED',
                    close_price = ?,
                    close_reason = ?,
                    close_time = ?,
                    pnl_pips = ?,
                    pnl_percent = ?,
                    pnl_rr = ?,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (close_price, reason, time.time(), pnl_pips, pnl_pct, pnl_rr, trade_id),
            )
            conn.commit()
            logger.info("Trade %s (%s) ferme manuellement. P&L: %.1fp",
                       symbol, trade_id, pnl_pips)
            return True

        except Exception as e:
            logger.error("Erreur close_trade(%d): %s", trade_id, e)
            return False
