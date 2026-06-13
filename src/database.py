import sqlite3
import os

DB_PATH = "trailhead.db"

def init_db():
    """Initialize database and create tables if they do not exist."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS journal_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        lat REAL,
        lon REAL,
        ele REAL,
        cum_dist REAL,
        transcript TEXT
    );
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS custom_waypoints (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        lat REAL,
        lon REAL,
        ele REAL,
        type TEXT,
        name TEXT,
        description TEXT
    );
    """)
    conn.commit()
    conn.close()
    print(f"[database] SQLite database initialized at {DB_PATH}")

def add_journal_entry(lat, lon, ele, cum_dist, transcript):
    """Insert a voice journal log entry."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO journal_logs (lat, lon, ele, cum_dist, transcript)
    VALUES (?, ?, ?, ?, ?)
    """, (lat, lon, ele, cum_dist, transcript))
    conn.commit()
    conn.close()
    print(f"[database] Saved journal entry: '{transcript[:30]}...'")

def get_journal_entries():
    """Retrieve all journal entries sorted by timestamp descending."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT id, timestamp, lat, lon, ele, cum_dist, transcript FROM journal_logs ORDER BY timestamp DESC")
    rows = cursor.fetchall()
    entries = []
    for r in rows:
        entries.append({
            "id": r["id"],
            "timestamp": r["timestamp"],
            "lat": r["lat"],
            "lon": r["lon"],
            "ele": r["ele"],
            "cum_dist": r["cum_dist"],
            "transcript": r["transcript"]
        })
    conn.close()
    return entries

def clear_journal_logs():
    """Delete all journal entries."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM journal_logs")
    conn.commit()
    conn.close()
    print("[database] Cleared all journal logs.")

def add_custom_waypoint(lat, lon, ele, wp_type, name, description=""):
    """Insert a tagged custom waypoint."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO custom_waypoints (lat, lon, ele, type, name, description)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (lat, lon, ele, wp_type, name, description))
    conn.commit()
    conn.close()
    print(f"[database] Saved custom waypoint '{name}' of type '{wp_type}'")

def get_custom_waypoints():
    """Retrieve all custom waypoints sorted by timestamp descending."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT id, timestamp, lat, lon, ele, type, name, description FROM custom_waypoints ORDER BY timestamp DESC")
    rows = cursor.fetchall()
    wps = []
    for r in rows:
        wps.append({
            "id": r["id"],
            "timestamp": r["timestamp"],
            "lat": r["lat"],
            "lon": r["lon"],
            "ele": r["ele"],
            "type": r["type"],
            "name": r["name"],
            "description": r["description"]
        })
    conn.close()
    return wps

def clear_custom_waypoints():
    """Delete all custom waypoints."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM custom_waypoints")
    conn.commit()
    conn.close()
    print("[database] Cleared all custom waypoints.")
