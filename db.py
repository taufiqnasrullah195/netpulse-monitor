"""
NetPulse persistence layer.

Schema:
  host_status  — one row per poll per host (ip, alive, latency, timestamp)
  event_log    — human-readable audit trail ("EMP-47 offline at 21:32")

WAL mode: safe for a single-user desktop tool with concurrent reads.
All writes are parameterized — no string interpolation near SQL.

Override _DB_PATH for tests:
    import db; db._DB_PATH_OVERRIDE = tmp_path / "test.db"
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

_DB_PATH_OVERRIDE: Optional[Path] = None

_DEFAULT_DB = Path.home() / "AppData" / "Local" / "NetPulse" / "netpulse.db"


def _db_path() -> Path:
    if _DB_PATH_OVERRIDE is not None:
        return _DB_PATH_OVERRIDE
    return _DEFAULT_DB


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS host_status (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ip          TEXT    NOT NULL,
                alive       INTEGER NOT NULL,
                latency_ms  INTEGER,
                mac         TEXT,
                hostname    TEXT,
                polled_at   TEXT    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_host_status_ip_time
                ON host_status (ip, polled_at DESC);

            CREATE TABLE IF NOT EXISTS event_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ip          TEXT    NOT NULL,
                hostname    TEXT,
                event       TEXT    NOT NULL,
                occurred_at TEXT    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_event_log_time
                ON event_log (occurred_at DESC);
        """)


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def record_poll(
    ip: str,
    alive: bool,
    latency_ms: Optional[int],
    mac: str,
    hostname: str,
    polled_at: Optional[datetime] = None,
) -> None:
    ts = (polled_at or datetime.utcnow()).isoformat()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO host_status (ip, alive, latency_ms, mac, hostname, polled_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (ip, int(alive), latency_ms, mac, hostname, ts),
        )


def record_event(
    ip: str,
    hostname: str,
    event: str,
    occurred_at: Optional[datetime] = None,
) -> None:
    ts = (occurred_at or datetime.utcnow()).isoformat()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO event_log (ip, hostname, event, occurred_at)
            VALUES (?, ?, ?, ?)
            """,
            (ip, hostname, event, ts),
        )


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

@dataclass
class StatusRow:
    ip: str
    alive: bool
    latency_ms: Optional[int]
    mac: str
    hostname: str
    polled_at: str


@dataclass
class EventRow:
    ip: str
    hostname: str
    event: str
    occurred_at: str


def latest_status_per_host() -> list[StatusRow]:
    """Most recent poll result for every distinct IP."""
    with _connect() as conn:
        rows = conn.execute("""
            SELECT ip, alive, latency_ms, mac, hostname, polled_at
            FROM host_status
            WHERE id IN (
                SELECT MAX(id) FROM host_status GROUP BY ip
            )
            ORDER BY ip
        """).fetchall()
    return [
        StatusRow(
            ip=r["ip"],
            alive=bool(r["alive"]),
            latency_ms=r["latency_ms"],
            mac=r["mac"] or "",
            hostname=r["hostname"] or "",
            polled_at=r["polled_at"],
        )
        for r in rows
    ]


def status_history(ip: str, limit: int = 500) -> list[StatusRow]:
    """Poll history for one host, newest first."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT ip, alive, latency_ms, mac, hostname, polled_at
            FROM host_status
            WHERE ip = ?
            ORDER BY polled_at DESC
            LIMIT ?
            """,
            (ip, limit),
        ).fetchall()
    return [
        StatusRow(
            ip=r["ip"],
            alive=bool(r["alive"]),
            latency_ms=r["latency_ms"],
            mac=r["mac"] or "",
            hostname=r["hostname"] or "",
            polled_at=r["polled_at"],
        )
        for r in rows
    ]


def uptime_percent(ip: str, since_iso: str) -> float:
    """Fraction of polls where alive=1 since `since_iso` timestamp."""
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(alive) AS up
            FROM host_status
            WHERE ip = ? AND polled_at >= ?
            """,
            (ip, since_iso),
        ).fetchone()
    total = row["total"] or 0
    if total == 0:
        return 0.0
    return round((row["up"] / total) * 100, 2)


def recent_events(limit: int = 200) -> list[EventRow]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT ip, hostname, event, occurred_at
            FROM event_log
            ORDER BY occurred_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        EventRow(
            ip=r["ip"],
            hostname=r["hostname"] or "",
            event=r["event"],
            occurred_at=r["occurred_at"],
        )
        for r in rows
    ]
