from pathlib import Path
import sqlite3

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "app.sqlite3"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

con = sqlite3.connect(str(DB_PATH))
cur = con.cursor()

cur.executescript(
    """
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    username TEXT,
    text TEXT NOT NULL,
    sentiment TEXT,
    tags TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id INTEGER PRIMARY KEY,
    chat_id INTEGER,
    username TEXT,
    language TEXT DEFAULT 'pt-BR',
    notify_alerts INTEGER DEFAULT 1,
    notify_daily_report INTEGER DEFAULT 1,
    notify_opportunities INTEGER DEFAULT 1,
    muted INTEGER DEFAULT 0,
    extra TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS trend_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    source TEXT,
    region TEXT,
    signal TEXT,
    collected_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    status TEXT,
    amount REAL,
    gateway TEXT,
    reference TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS agenda (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    description TEXT,
    owner TEXT,
    when_date TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS groups (
    group_id INTEGER PRIMARY KEY,
    status TEXT,
    reason TEXT,
    updated_by TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);
"""
)

con.commit()
con.close()
print("DB initialized at", DB_PATH)
