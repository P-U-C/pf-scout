"""Database connection utilities."""

import sqlite3
from pathlib import Path


def get_connection(db_path: str) -> sqlite3.Connection:
    """Get a configured SQLite connection.

    Enables:
    - foreign_keys=ON
    - WAL journal mode
    - synchronous=NORMAL
    - Row factory for dict-like access
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn
