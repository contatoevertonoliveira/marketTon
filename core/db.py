"""SQLite database layer for marketing-digital."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "app.sqlite3"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    statements = [
        """CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            user_id INTEGER,
            role TEXT NOT NULL DEFAULT 'viewer',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );""",
        """CREATE TABLE IF NOT EXISTS roles (
            user_id INTEGER PRIMARY KEY,
            role TEXT NOT NULL,
            granted_at TEXT NOT NULL DEFAULT (datetime('now'))
        );""",
        """CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT,
            text TEXT NOT NULL,
            sentiment TEXT,
            tags TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );""",
        """CREATE TABLE IF NOT EXISTS telegram_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            chat_id INTEGER,
            event_type TEXT NOT NULL,
            payload TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );""",
        """CREATE TABLE IF NOT EXISTS user_preferences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            chat_id INTEGER,
            username TEXT,
            language TEXT NOT NULL DEFAULT 'pt-BR',
            notify_alerts INTEGER NOT NULL DEFAULT 1,
            notify_daily_report INTEGER NOT NULL DEFAULT 1,
            notify_opportunities INTEGER NOT NULL DEFAULT 1,
            muted INTEGER NOT NULL DEFAULT 0,
            extra TEXT,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(user_id)
        );""",
        """CREATE TABLE IF NOT EXISTS marketplace_products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            marketplace TEXT NOT NULL,
            external_id TEXT,
            title TEXT,
            price REAL,
            stock INTEGER,
            category TEXT,
            raw TEXT,
            collected_at TEXT NOT NULL DEFAULT (datetime('now'))
        );""",
        """CREATE TABLE IF NOT EXISTS marketplace_sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            marketplace TEXT NOT NULL,
            product_id TEXT,
            sold_last INTEGER DEFAULT 0,
            collected_at TEXT NOT NULL DEFAULT (datetime('now'))
        );""",
        """CREATE TABLE IF NOT EXISTS trend_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT NOT NULL,
            geo TEXT NOT NULL,
            interest_last REAL,
            interest_mean REAL,
            interest_change REAL,
            alert TEXT,
            collected_at TEXT NOT NULL DEFAULT (datetime('now'))
        );""",
        """CREATE TABLE IF NOT EXISTS copy_variants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product TEXT,
            headline TEXT,
            body TEXT,
            style TEXT,
            version INTEGER,
            generated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );""",
        """CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            path TEXT,
            rows INTEGER,
            summary TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );""",
        """CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tx_id TEXT UNIQUE NOT NULL,
            gateway TEXT NOT NULL,
            amount_cents INTEGER NOT NULL,
            currency TEXT NOT NULL,
            status TEXT NOT NULL,
            metadata TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );""",
        """CREATE TABLE IF NOT EXISTS groups (
            group_id INTEGER PRIMARY KEY,
            title TEXT,
            status TEXT NOT NULL DEFAULT 'allowed',
            reason TEXT,
            updated_by INTEGER,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );""",
        """CREATE TABLE IF NOT EXISTS brands (
            tenant_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            primary_color TEXT,
            secondary_color TEXT,
            logo_url TEXT,
            favicon_url TEXT,
            custom_css TEXT,
            extra TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );""",
        """CREATE TABLE IF NOT EXISTS group_brand_mapping (
            group_id INTEGER PRIMARY KEY,
            tenant_id TEXT NOT NULL
        );""",
        """CREATE TABLE IF NOT EXISTS agenda (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            marketplace TEXT NOT NULL DEFAULT 'Todos',
            when_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pendente',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );""",
        """CREATE TABLE IF NOT EXISTS daily_tasks (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            owner TEXT NOT NULL,
            priority TEXT NOT NULL DEFAULT 'média',
            due_date TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            status TEXT NOT NULL DEFAULT 'aberta',
            approved_by_agent INTEGER NOT NULL DEFAULT 0
        );""",
        """CREATE TABLE IF NOT EXISTS approved_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_name TEXT NOT NULL,
            type TEXT NOT NULL,
            approved_at TEXT NOT NULL DEFAULT (datetime('now')),
            status TEXT NOT NULL DEFAULT 'approved'
        );""",
    ]
    conn = get_conn()
    try:
        for sql in statements:
            conn.execute(sql)
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print("DB initialized at", DB_PATH)
