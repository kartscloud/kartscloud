from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS canvas_cache (
    key TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    fetched_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS food_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    raw TEXT NOT NULL,
    items_json TEXT,
    kcal REAL,
    protein REAL,
    carbs REAL,
    fat REAL
);

CREATE TABLE IF NOT EXISTS workouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    kind TEXT NOT NULL,
    raw TEXT NOT NULL,
    parsed_json TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    source TEXT,
    title TEXT,
    company TEXT,
    url TEXT,
    json TEXT,
    score REAL,
    seen_at INTEGER
);

CREATE TABLE IF NOT EXISTS applications (
    job_id TEXT PRIMARY KEY,
    status TEXT,
    applied_at INTEGER,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS chat_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    ts INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chat_session ON chat_history(session_id, ts);
CREATE INDEX IF NOT EXISTS idx_canvas_fetched ON canvas_cache(fetched_at);
"""


def get_conn(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def kv_get(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def kv_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO kv (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


def cache_get(conn: sqlite3.Connection, key: str, ttl_seconds: int) -> Optional[str]:
    row = conn.execute(
        "SELECT payload, fetched_at FROM canvas_cache WHERE key = ?", (key,)
    ).fetchone()
    if not row:
        return None
    if time.time() - row["fetched_at"] > ttl_seconds:
        return None
    return row["payload"]


def cache_set(conn: sqlite3.Connection, key: str, payload: str) -> None:
    conn.execute(
        "INSERT INTO canvas_cache (key, payload, fetched_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET payload = excluded.payload, fetched_at = excluded.fetched_at",
        (key, payload, int(time.time())),
    )
    conn.commit()


def append_chat(conn: sqlite3.Connection, session_id: str, role: str, content: str) -> None:
    conn.execute(
        "INSERT INTO chat_history (session_id, role, content, ts) VALUES (?, ?, ?, ?)",
        (session_id, role, content, int(time.time())),
    )
    conn.commit()


def load_chat(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT role, content FROM chat_history WHERE session_id = ? ORDER BY ts ASC, id ASC",
        (session_id,),
    ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]
