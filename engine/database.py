"""
InfraWatch Nexus — SQLite Persistence Layer
=============================================
WAL-mode SQLite for event persistence and history.
Replaces ephemeral JSON files with queryable storage.
"""

import json
import os
import sqlite3
from datetime import datetime


DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "infrawatch.db"
)


def get_connection():
    """Get SQLite connection with WAL mode for concurrent reads."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT UNIQUE NOT NULL,
            event_type TEXT NOT NULL,
            dustbin_id TEXT,
            ward_id TEXT,
            data TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_events_type_ts
            ON events(event_type, timestamp);
        CREATE INDEX IF NOT EXISTS idx_events_dustbin
            ON events(dustbin_id, timestamp);
        CREATE INDEX IF NOT EXISTS idx_events_ward
            ON events(ward_id, event_type);

        CREATE TABLE IF NOT EXISTS daily_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            snapshot TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_snapshots_date
            ON daily_snapshots(date);
    """)
    conn.commit()
    conn.close()


def insert_event(event_type, event_data):
    """Insert a new event. Returns event_id."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO events "
            "(event_id, event_type, dustbin_id, ward_id, data, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                event_data["event_id"],
                event_type,
                event_data.get("dustbin_id"),
                event_data.get("ward_id"),
                json.dumps(event_data),
                event_data.get("timestamp", datetime.now().isoformat()),
            )
        )
        conn.commit()
    finally:
        conn.close()
    return event_data["event_id"]


def get_events_in_window(event_type, window_start_iso):
    """Get events within a time window."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT data FROM events "
            "WHERE event_type = ? AND timestamp >= ? "
            "ORDER BY timestamp",
            (event_type, window_start_iso)
        ).fetchall()
    finally:
        conn.close()
    return [json.loads(r["data"]) for r in rows]


def get_event_count(event_type, window_start_iso=None):
    """Get count of events, optionally within a window."""
    conn = get_connection()
    try:
        if window_start_iso:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM events "
                "WHERE event_type = ? AND timestamp >= ?",
                (event_type, window_start_iso)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM events WHERE event_type = ?",
                (event_type,)
            ).fetchone()
    finally:
        conn.close()
    return row["cnt"] if row else 0


def save_daily_snapshot(snapshot_data):
    """Save a daily snapshot for historical analytics."""
    conn = get_connection()
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        conn.execute(
            "INSERT OR REPLACE INTO daily_snapshots (date, snapshot) VALUES (?, ?)",
            (today, json.dumps(snapshot_data))
        )
        conn.commit()
    finally:
        conn.close()


def get_historical_snapshots(days=7):
    """Get the last N days of snapshots."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT date, snapshot FROM daily_snapshots "
            "ORDER BY date DESC LIMIT ?",
            (days,)
        ).fetchall()
    finally:
        conn.close()
    return [{"date": r["date"], "snapshot": json.loads(r["snapshot"])} for r in rows]


# ═══════════════════════════════════════════════════════════════════════════
# HYSTERESIS STATE PERSISTENCE (Fix #7)
# ═══════════════════════════════════════════════════════════════════════════

def save_hysteresis_states(states_dict):
    """Persist dustbin FSM states to SQLite for restart recovery."""
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS hysteresis_states (
                dustbin_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        for dustbin_id, state in states_dict.items():
            conn.execute(
                "INSERT OR REPLACE INTO hysteresis_states "
                "(dustbin_id, state) VALUES (?, ?)",
                (dustbin_id, state)
            )
        conn.commit()
    finally:
        conn.close()


def load_hysteresis_states():
    """Load persisted hysteresis states on startup."""
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS hysteresis_states (
                dustbin_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        rows = conn.execute(
            "SELECT dustbin_id, state FROM hysteresis_states"
        ).fetchall()
    finally:
        conn.close()
    return {r["dustbin_id"]: r["state"] for r in rows}


# ═══════════════════════════════════════════════════════════════════════════
# EVENT CLEANUP (Fix #6)
# ═══════════════════════════════════════════════════════════════════════════

def cleanup_old_events(hours=48):
    """Delete events older than N hours from the database."""
    from datetime import timedelta
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
    conn = get_connection()
    try:
        cursor = conn.execute(
            "DELETE FROM events WHERE timestamp < ?",
            (cutoff,)
        )
        deleted = cursor.rowcount
        conn.commit()
    finally:
        conn.close()
    return deleted

