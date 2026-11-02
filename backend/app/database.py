"""SQLite persistence for tributes. Uses the stdlib driver to keep deps minimal."""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(
    os.environ.get("MEMORIAL_DB_PATH", Path(__file__).resolve().parent.parent / "memorial.db")
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS tributes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    years TEXT,
    message TEXT NOT NULL,
    author TEXT NOT NULL,
    relationship TEXT,
    candles INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS victims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    model INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
"""

SEED_TRIBUTES = [
    (
        "Elena Marchetti",
        "1948–2020",
        "Nonna, your Sunday sauce and louder-than-life laugh filled every room. "
        "We still set a place for you at the table.",
        "Sofia",
        "Granddaughter",
        12,
    ),
    (
        "James 'Jim' Okafor",
        "1955–2021",
        "A nurse for 34 years, he worked the COVID ward until the very end. "
        "He gave everything so others could go home.",
        "The Okafor family",
        "His children",
        27,
    ),
    (
        "Rosa Delgado",
        "1962–2020",
        "Mom taught third grade for three decades. Half this town learned to "
        "read in her classroom. We love you forever.",
        "Miguel",
        "Son",
        18,
    ),
]


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)
        empty = conn.execute("SELECT COUNT(*) AS n FROM tributes").fetchone()["n"] == 0
        if empty:
            conn.executemany(
                "INSERT INTO tributes (name, years, message, author, relationship, candles)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                SEED_TRIBUTES,
            )
