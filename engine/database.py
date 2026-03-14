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

        CREATE TABLE IF NOT EXISTS rewards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT UNIQUE NOT NULL,
            user_sub TEXT NOT NULL,
            reporter_name TEXT DEFAULT 'Anonymous',
            reporter_upi TEXT DEFAULT '',
            ward_id TEXT,
            dustbin_id TEXT,
            overflow_level INTEGER,
            points INTEGER NOT NULL,
            rupees REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            reported_at TEXT,
            resolved_at TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_rewards_user ON rewards(user_sub);
        CREATE INDEX IF NOT EXISTS idx_rewards_status ON rewards(status);
        CREATE INDEX IF NOT EXISTS idx_rewards_dustbin ON rewards(dustbin_id, status);
    """)
    conn.commit()

    # Safely add user_sub column to events — may already exist
    try:
        conn.execute("ALTER TABLE events ADD COLUMN user_sub TEXT DEFAULT ''")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists — safe to ignore

    conn.close()


def insert_event(event_type, event_data):
    """Insert a new event. Returns event_id."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO events "
            "(event_id, event_type, dustbin_id, ward_id, data, timestamp, user_sub) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                event_data["event_id"],
                event_type,
                event_data.get("dustbin_id"),
                event_data.get("ward_id"),
                json.dumps(event_data),
                event_data.get("timestamp", datetime.now().isoformat()),
                event_data.get("user_sub", ""),
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


def get_user_reports(user_sub, limit=20):
    """
    Get recent events for a specific authenticated user.
    Returns list of dicts with event data + parsed data field.
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT event_id, event_type, dustbin_id, ward_id, data, timestamp "
            "FROM events WHERE user_sub = ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (user_sub, limit)
        ).fetchall()
    finally:
        conn.close()

    result = []
    for r in rows:
        try:
            parsed = json.loads(r["data"])
        except Exception:
            parsed = {}
        result.append({
            "event_id": r["event_id"],
            "event_type": r["event_type"],
            "dustbin_id": r["dustbin_id"],
            "ward_id": r["ward_id"],
            "timestamp": r["timestamp"],
            **parsed,
        })
    return result


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
# HYSTERESIS STATE PERSISTENCE
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
# EVENT CLEANUP
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


# ═══════════════════════════════════════════════════════════════════════════
# REWARDS SYSTEM
# ═══════════════════════════════════════════════════════════════════════════

def _overflow_to_points_rupees(overflow_level):
    """Map overflow level to (points, rupees) tuple."""
    table = {1: (10, 5.0), 2: (10, 5.0), 3: (20, 10.0), 4: (35, 20.0), 5: (50, 50.0)}
    return table.get(overflow_level, (10, 5.0))


def insert_pending_reward(event_id, user_sub, reporter_name, reporter_upi,
                          ward_id, dustbin_id, overflow_level, reported_at):
    """
    Insert a pending reward entry when a citizen report is accepted.
    Reward is unlocked when van confirms collection.
    """
    points, rupees = _overflow_to_points_rupees(overflow_level)
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO rewards "
            "(event_id, user_sub, reporter_name, reporter_upi, ward_id, "
            "dustbin_id, overflow_level, points, rupees, status, reported_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
            (event_id, user_sub, reporter_name or "Anonymous", reporter_upi or "",
             ward_id, dustbin_id, overflow_level, points, rupees, reported_at)
        )
        conn.commit()
    finally:
        conn.close()
    return {"points": points, "rupees": rupees}


def resolve_rewards_for_dustbin(dustbin_id):
    """
    Mark all pending rewards for a dustbin as 'resolved' when van collects.
    Returns number of rewards resolved.
    """
    now = datetime.now().isoformat()
    conn = get_connection()
    try:
        cursor = conn.execute(
            "UPDATE rewards SET status='resolved', resolved_at=? "
            "WHERE dustbin_id=? AND status='pending'",
            (now, dustbin_id)
        )
        resolved = cursor.rowcount
        conn.commit()
    finally:
        conn.close()
    return resolved


def get_user_reward_summary(user_sub):
    """
    Get comprehensive reward summary for an authenticated user.
    Returns totals + recent resolved history.
    """
    conn = get_connection()
    try:
        totals = conn.execute(
            "SELECT "
            "  COALESCE(SUM(points), 0) as total_points, "
            "  COALESCE(SUM(CASE WHEN status='resolved' THEN rupees ELSE 0 END), 0) as pending_rupees, "
            "  COALESCE(SUM(CASE WHEN status='exported' THEN rupees ELSE 0 END), 0) as paid_rupees, "
            "  COUNT(*) as reports_submitted, "
            "  COALESCE(SUM(CASE WHEN status IN ('resolved','exported') THEN 1 ELSE 0 END), 0) as reports_resolved "
            "FROM rewards WHERE user_sub=?",
            (user_sub,)
        ).fetchone()

        history = conn.execute(
            "SELECT event_id, dustbin_id, ward_id, overflow_level, points, rupees, "
            "       status, reported_at, resolved_at "
            "FROM rewards WHERE user_sub=? AND status IN ('resolved','exported') "
            "ORDER BY resolved_at DESC LIMIT 10",
            (user_sub,)
        ).fetchall()
    finally:
        conn.close()

    return {
        "total_points": int(totals["total_points"]) if totals else 0,
        "pending_rupees": round(float(totals["pending_rupees"]), 2) if totals else 0.0,
        "paid_rupees": round(float(totals["paid_rupees"]), 2) if totals else 0.0,
        "reports_submitted": int(totals["reports_submitted"]) if totals else 0,
        "reports_resolved": int(totals["reports_resolved"]) if totals else 0,
        "reward_history": [dict(r) for r in history],
    }


def get_leaderboard(month_str=None):
    """
    Get top 10 reporters this month by total_points.
    month_str: 'YYYY-MM' format, defaults to current month.
    Never exposes reporter_upi or user_sub.
    """
    if not month_str:
        month_str = datetime.now().strftime("%Y-%m")

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT reporter_name, ward_id, "
            "  SUM(points) as total_points, "
            "  COUNT(CASE WHEN status IN ('resolved','exported') THEN 1 END) as reports_resolved "
            "FROM rewards "
            "WHERE status IN ('resolved','exported') "
            "  AND strftime('%Y-%m', resolved_at) = ? "
            "GROUP BY user_sub "
            "ORDER BY total_points DESC "
            "LIMIT 10",
            (month_str,)
        ).fetchall()
    finally:
        conn.close()

    result = []
    for i, r in enumerate(rows):
        result.append({
            "rank": i + 1,
            "reporter_name": r["reporter_name"] or "Anonymous",
            "total_points": int(r["total_points"]),
            "reports_resolved": int(r["reports_resolved"]),
            "ward_id": r["ward_id"],
        })
    return result


def export_pending_rewards():
    """
    Export all resolved-but-not-yet-exported rewards as a list of dicts.
    Marks returned rows as 'exported' (payment queue handed to government).
    """
    now = datetime.now().isoformat()
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT reporter_name, reporter_upi, SUM(rupees) as total_rupees, "
            "  COUNT(*) as report_count, ward_id, user_sub "
            "FROM rewards WHERE status='resolved' "
            "GROUP BY user_sub",
        ).fetchall()

        # Mark as exported
        conn.execute(
            "UPDATE rewards SET status='exported' WHERE status='resolved'"
        )
        conn.commit()
    finally:
        conn.close()

    return [
        {
            "reporter_name": r["reporter_name"] or "Anonymous",
            "reporter_upi": r["reporter_upi"] or "",
            "total_rupees": round(float(r["total_rupees"]), 2),
            "report_count": int(r["report_count"]),
            "ward_id": r["ward_id"] or "",
            "generated_at": now,
        }
        for r in rows
    ]
