"""
Gestionnaire de base de données SQLite pour InelidaMarketScanner.

Enregistre les ranges de session asiatique (high/low + dates/heures) ainsi que
les sweeps détectés (date/heure de sweep), dans l'objectif de pouvoir faire
des statistiques ultérieures.

Tables :
  - asian_sessions : range asiatique + sweep des niveaux AH/AL
  - sweep_events   : sweeps BSL/SSL génériques (ICT)
"""

import logging
import os
import sqlite3
import time
from typing import List, Optional

from .config import DB
from .sweep_detector import AsianRangeResult, SweepEvent, LevelSweepResult

logger = logging.getLogger("DatabaseManager")

# ─── Requêtes DDL ─────────────────────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS asian_sessions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol              TEXT    NOT NULL,
    session_date        TEXT    NOT NULL,   -- YYYY-MM-DD
    timeframe           TEXT    NOT NULL,
    -- Range asiatique
    asian_high          REAL    NOT NULL,
    asian_low           REAL    NOT NULL,
    -- Sweep du Asian High (avec rejet)
    asian_high_swept    INTEGER NOT NULL DEFAULT 0,   -- bool
    high_swept_at       REAL,                -- epoch UTC
    high_swept_close    REAL,
    high_swept_session  TEXT,                -- "Asian"/"London"/"NY"/...
    -- Breach du Asian High (mèche traverse, sans close condition)
    asian_high_breached INTEGER NOT NULL DEFAULT 0,   -- bool
    -- Sweep du Asian Low (avec rejet)
    asian_low_swept     INTEGER NOT NULL DEFAULT 0,   -- bool
    low_swept_at        REAL,                -- epoch UTC
    low_swept_close     REAL,
    low_swept_session   TEXT,
    -- Breach du Asian Low (mèche traverse, sans close condition)
    asian_low_breached  INTEGER NOT NULL DEFAULT 0,   -- bool
    -- Prix courant au moment du scan
    current_price       REAL,
    -- Sweeps Fibonacci (bull/bear)
    bull_fib_swept_label   TEXT,
    bull_fib_swept_at      REAL,
    bull_fib_swept_close   REAL,
    bull_fib_swept_session TEXT,
    bear_fib_swept_label   TEXT,
    bear_fib_swept_at      REAL,
    bear_fib_swept_close   REAL,
    bear_fib_swept_session TEXT,
    -- Métadonnées
    created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    -- Une seule ligne par (symbol, session_date, timeframe)
    UNIQUE(symbol, session_date, timeframe)
);

CREATE TABLE IF NOT EXISTS sweep_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT    NOT NULL,
    timeframe       TEXT    NOT NULL,
    kind            TEXT    NOT NULL,   -- 'high_sweep' / 'low_sweep'
    sweep_label     TEXT    NOT NULL,   -- 'BSL' / 'SSL'
    level           REAL    NOT NULL,   -- prix du swing point swept
    sweep_time      REAL,               -- epoch de la bougie qui a swept
    sweep_close     REAL,
    current_price   REAL,
    distance_pct    REAL,
    direction       TEXT,               -- 'reversal_down' / 'reversal_up'
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_asian_symbol_date
    ON asian_sessions(symbol, session_date);

CREATE INDEX IF NOT EXISTS idx_sweep_symbol
    ON sweep_events(symbol, sweep_label);

CREATE INDEX IF NOT EXISTS idx_asian_swept
    ON asian_sessions(asian_high_swept, asian_low_swept);

CREATE TABLE IF NOT EXISTS level_sweeps (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT    NOT NULL,
    level_type      TEXT    NOT NULL,   -- 'daily' / 'weekly'
    level_date      TEXT    NOT NULL,   -- YYYY-MM-DD ou YYYY-WW
    level_high      REAL    NOT NULL,
    level_low       REAL    NOT NULL,
    high_swept      INTEGER NOT NULL DEFAULT 0,
    low_swept       INTEGER NOT NULL DEFAULT 0,
    high_breached   INTEGER NOT NULL DEFAULT 0,
    low_breached    INTEGER NOT NULL DEFAULT 0,
    high_swept_at   REAL,
    high_swept_close REAL,
    low_swept_at    REAL,
    low_swept_close REAL,
    current_price   REAL,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(symbol, level_type, level_date)
);

CREATE INDEX IF NOT EXISTS idx_level_symbol
    ON level_sweeps(symbol, level_type);
"""


class DatabaseManager:
    """Gestionnaire singleton de la base SQLite."""

    _instance: Optional["DatabaseManager"] = None
    _initialized: bool = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, db_path: Optional[str] = None):
        if not self._initialized:
            self.db_path = db_path or DB.path
            self._conn: Optional[sqlite3.Connection] = None
            self._initialized = True

    # ─── Cycle de vie ──────────────────────────────────────────────────────

    def connect(self) -> bool:
        """Ouvre la connexion SQLite et crée les tables si nécessaire."""
        if self._conn is not None:
            return True
        try:
            # Créer le répertoire parent si besoin
            parent = os.path.dirname(self.db_path)
            if parent and not os.path.exists(parent):
                os.makedirs(parent, exist_ok=True)

            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA_SQL)
            self._conn.commit()
            # Migration : ajouter les colonnes manquantes si la DB date d'avant les modifications
            self._migrate()
            logger.info("Base de données SQLite ouverte : %s", self.db_path)
            return True
        except sqlite3.Error as e:
            logger.error("Impossible d'ouvrir la base %s : %s", self.db_path, e)
            self._conn = None
            return False

    def close(self):
        """Ferme proprement la connexion."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
            logger.debug("Base de données fermée.")

    @property
    def conn(self) -> Optional[sqlite3.Connection]:
        """Retourne la connexion, en l'ouvrant si nécessaire."""
        if self._conn is None:
            self.connect()
        return self._conn

    # ─── Asian Sessions ────────────────────────────────────────────────────

    def save_asian_result(self, result: AsianRangeResult) -> bool:
        """Insère ou met à jour (UPSERT) un résultat de range asiatique."""
        if self.conn is None:
            return False
        try:
            self.conn.execute(
                """
                INSERT INTO asian_sessions (
                    symbol, session_date, timeframe,
                    asian_high, asian_low,
                    asian_high_swept, high_swept_at, high_swept_close, high_swept_session,
                    asian_high_breached,
                    asian_low_swept, low_swept_at, low_swept_close, low_swept_session,
                    asian_low_breached,
                    current_price,
                    bull_fib_swept_label, bull_fib_swept_at, bull_fib_swept_close, bull_fib_swept_session,
                    bear_fib_swept_label, bear_fib_swept_at, bear_fib_swept_close, bear_fib_swept_session
                ) VALUES (
                    ?, ?, ?,
                    ?, ?,
                    ?, ?, ?, ?,
                    ?,
                    ?, ?, ?, ?,
                    ?,
                    ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?
                )
                ON CONFLICT(symbol, session_date, timeframe) DO UPDATE SET
                    asian_high          = excluded.asian_high,
                    asian_low           = excluded.asian_low,
                    asian_high_swept    = excluded.asian_high_swept,
                    high_swept_at       = excluded.high_swept_at,
                    high_swept_close    = excluded.high_swept_close,
                    high_swept_session  = excluded.high_swept_session,
                    asian_high_breached = excluded.asian_high_breached,
                    asian_low_swept     = excluded.asian_low_swept,
                    low_swept_at        = excluded.low_swept_at,
                    low_swept_close     = excluded.low_swept_close,
                    low_swept_session   = excluded.low_swept_session,
                    asian_low_breached  = excluded.asian_low_breached,
                    current_price       = excluded.current_price,
                    bull_fib_swept_label  = excluded.bull_fib_swept_label,
                    bull_fib_swept_at     = excluded.bull_fib_swept_at,
                    bull_fib_swept_close  = excluded.bull_fib_swept_close,
                    bull_fib_swept_session = excluded.bull_fib_swept_session,
                    bear_fib_swept_label  = excluded.bear_fib_swept_label,
                    bear_fib_swept_at     = excluded.bear_fib_swept_at,
                    bear_fib_swept_close  = excluded.bear_fib_swept_close,
                    bear_fib_swept_session = excluded.bear_fib_swept_session
                """,
                (
                    result.symbol,
                    result.session_date,
                    result.timeframe,
                    result.asian_high,
                    result.asian_low,
                    int(result.asian_high_swept),
                    result.high_swept_at,
                    result.high_swept_close,
                    result.high_swept_session,
                    int(result.asian_high_breached),
                    int(result.asian_low_swept),
                    result.low_swept_at,
                    result.low_swept_close,
                    result.low_swept_session,
                    int(result.asian_low_breached),
                    result.current_price,
                    result.bull_fib_swept_label,
                    result.bull_fib_swept_at,
                    result.bull_fib_swept_close,
                    result.bull_fib_swept_session,
                    result.bear_fib_swept_label,
                    result.bear_fib_swept_at,
                    result.bear_fib_swept_close,
                    result.bear_fib_swept_session,
                ),
            )
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error("Erreur DB save_asian_result(%s) : %s", result.symbol, e)
            return False

    def save_asian_results_bulk(self, results: List[AsianRangeResult]) -> int:
        """Sauvegarde une liste de résultats asiatiques. Retourne le nombre de succès."""
        count = 0
        for r in results:
            if self.save_asian_result(r):
                count += 1
        if count > 0:
            logger.info("DB : %d range(s) asiatique(s) enregistré(s).", count)
        return count

    # ─── Sweep Events ──────────────────────────────────────────────────────

    def save_sweep_event(self, event: SweepEvent) -> bool:
        """Insère un événement de sweep BSL/SSL dans la base."""
        if self.conn is None:
            return False
        try:
            self.conn.execute(
                """
                INSERT INTO sweep_events (
                    symbol, timeframe, kind, sweep_label,
                    level, sweep_time, sweep_close,
                    current_price, distance_pct, direction
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.symbol,
                    event.timeframe,
                    event.kind,
                    event.sweep_label,
                    event.level,
                    event.sweep_time,
                    event.sweep_close,
                    event.current_price,
                    event.distance_pct,
                    event.direction,
                ),
            )
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error("Erreur DB save_sweep_event(%s) : %s", event.symbol, e)
            return False

    def save_sweep_events_bulk(self, events: List[SweepEvent]) -> int:
        """Sauvegarde une liste de sweep events. Retourne le nombre de succès."""
        count = 0
        for e in events:
            if self.save_sweep_event(e):
                count += 1
        if count > 0:
            logger.info("DB : %d sweep(s) enregistré(s).", count)
        return count

    # ─── Daily / Weekly Level Sweeps ───────────────────────────────────────

    def save_level_sweep(self, result: LevelSweepResult) -> bool:
        """Insère ou met à jour un résultat de sweep de niveau daily/weekly."""
        if self.conn is None:
            return False
        try:
            self.conn.execute(
                """
                INSERT INTO level_sweeps (
                    symbol, level_type, level_date,
                    level_high, level_low,
                    high_swept, low_swept,
                    high_breached, low_breached,
                    high_swept_at, high_swept_close,
                    low_swept_at, low_swept_close,
                    current_price
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, level_type, level_date) DO UPDATE SET
                    level_high       = excluded.level_high,
                    level_low        = excluded.level_low,
                    high_swept       = excluded.high_swept,
                    low_swept        = excluded.low_swept,
                    high_breached    = excluded.high_breached,
                    low_breached     = excluded.low_breached,
                    high_swept_at    = excluded.high_swept_at,
                    high_swept_close = excluded.high_swept_close,
                    low_swept_at     = excluded.low_swept_at,
                    low_swept_close  = excluded.low_swept_close,
                    current_price    = excluded.current_price
                """,
                (
                    result.symbol,
                    result.level_type,
                    result.level_date,
                    result.level_high,
                    result.level_low,
                    int(result.high_swept),
                    int(result.low_swept),
                    int(result.high_breached),
                    int(result.low_breached),
                    result.high_swept_at,
                    result.high_swept_close,
                    result.low_swept_at,
                    result.low_swept_close,
                    result.current_price,
                ),
            )
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error("Erreur DB save_level_sweep(%s) : %s", result.symbol, e)
            return False

    def save_level_sweeps_bulk(self, results: list) -> int:
        """Sauvegarde une liste de LevelSweepResult."""
        count = 0
        for r in results:
            if self.save_level_sweep(r):
                count += 1
        if count > 0:
            logger.info("DB : %d niveau(x) enregistré(s).", count)
        return count

    def get_level_sweeps(
        self,
        symbol: Optional[str] = None,
        level_type: Optional[str] = None,
        limit: int = 30,
    ) -> List[sqlite3.Row]:
        """Récupère les niveaux daily/weekly stockés."""
        if self.conn is None:
            return []
        query = "SELECT * FROM level_sweeps WHERE 1=1"
        params: list = []
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        if level_type:
            query += " AND level_type = ?"
            params.append(level_type)
        query += " ORDER BY created_at DESC"
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        try:
            cur = self.conn.execute(query, params)
            return cur.fetchall()
        except sqlite3.Error as e:
            logger.error("Erreur DB get_level_sweeps : %s", e)
            return []

    # ─── Requêtes de statistiques ──────────────────────────────────────────

    def get_asian_sessions(
        self,
        symbol: Optional[str] = None,
        session_date: Optional[str] = None,
        limit: int = 50,
    ) -> List[sqlite3.Row]:
        """Récupère les sessions asiatiques stockées, avec filtres optionnels."""
        if self.conn is None:
            return []
        query = "SELECT * FROM asian_sessions WHERE 1=1"
        params: list = []
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        if session_date:
            query += " AND session_date = ?"
            params.append(session_date)
        query += " ORDER BY session_date DESC, symbol ASC"
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        try:
            cur = self.conn.execute(query, params)
            return cur.fetchall()
        except sqlite3.Error as e:
            logger.error("Erreur DB get_asian_sessions : %s", e)
            return []

    def get_sweep_events(
        self,
        symbol: Optional[str] = None,
        sweep_label: Optional[str] = None,
        limit: int = 50,
    ) -> List[sqlite3.Row]:
        """Récupère les sweep events stockés, avec filtres optionnels."""
        if self.conn is None:
            return []
        query = "SELECT * FROM sweep_events WHERE 1=1"
        params: list = []
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        if sweep_label:
            query += " AND sweep_label = ?"
            params.append(sweep_label)
        query += " ORDER BY created_at DESC"
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        try:
            cur = self.conn.execute(query, params)
            return cur.fetchall()
        except sqlite3.Error as e:
            logger.error("Erreur DB get_sweep_events : %s", e)
            return []

    def get_statistics(self) -> dict:
        """Retourne des statistiques globales sur les données stockées."""
        if self.conn is None:
            return {}
        stats = {}
        try:
            cur = self.conn.execute("SELECT COUNT(*) FROM asian_sessions")
            stats["asian_total"] = cur.fetchone()[0]

            cur = self.conn.execute(
                "SELECT COUNT(*) FROM asian_sessions WHERE asian_high_swept = 1"
            )
            stats["asian_high_swept"] = cur.fetchone()[0]

            cur = self.conn.execute(
                "SELECT COUNT(*) FROM asian_sessions WHERE asian_low_swept = 1"
            )
            stats["asian_low_swept"] = cur.fetchone()[0]

            cur = self.conn.execute("SELECT COUNT(DISTINCT symbol) FROM asian_sessions")
            stats["symbols_tracked"] = cur.fetchone()[0]

            cur = self.conn.execute(
                "SELECT session_date, COUNT(*) as cnt "
                "FROM asian_sessions GROUP BY session_date "
                "ORDER BY session_date DESC LIMIT 10"
            )
            stats["last_dates"] = [dict(r) for r in cur.fetchall()]

            cur = self.conn.execute("SELECT COUNT(*) FROM sweep_events")
            stats["sweep_total"] = cur.fetchone()[0]

            cur = self.conn.execute("SELECT COUNT(*) FROM sweep_events WHERE sweep_label = 'BSL'")
            stats["bsl_total"] = cur.fetchone()[0]

            cur = self.conn.execute("SELECT COUNT(*) FROM sweep_events WHERE sweep_label = 'SSL'")
            stats["ssl_total"] = cur.fetchone()[0]

        except sqlite3.Error as e:
            logger.error("Erreur DB get_statistics : %s", e)
        return stats


    # ─── Migration ────────────────────────────────────────────────────────────

    def _migrate(self):
        """Ajoute les colonnes manquantes pour les bases créées avant les modifications."""
        migrations = [
            ("asian_sessions", "asian_high_breached", "INTEGER NOT NULL DEFAULT 0"),
            ("asian_sessions", "asian_low_breached", "INTEGER NOT NULL DEFAULT 0"),
            ("level_sweeps", "high_breached", "INTEGER NOT NULL DEFAULT 0"),
            ("level_sweeps", "low_breached", "INTEGER NOT NULL DEFAULT 0"),
        ]
        for table, column, col_type in migrations:
            try:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                self._conn.commit()
                logger.info("Migration : colonne %s.%s ajoutée.", table, column)
            except sqlite3.OperationalError:
                pass  # La colonne existe déjà


# ─── Module-level helpers ──────────────────────────────────────────────────────

_db_manager: Optional[DatabaseManager] = None


def get_db() -> DatabaseManager:
    """Retourne l'instance singleton du DatabaseManager."""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager
