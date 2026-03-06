"""Database schema creation and migrations."""

import sqlite3
from .db import get_connection

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS contacts (
    id              TEXT PRIMARY KEY,
    canonical_label TEXT NOT NULL,
    first_seen      TEXT NOT NULL,
    last_updated    TEXT NOT NULL,
    tags            TEXT NOT NULL DEFAULT '[]',
    notes_count     INTEGER NOT NULL DEFAULT 0,
    archived        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS identifiers (
    id                  TEXT PRIMARY KEY,
    contact_id          TEXT NOT NULL REFERENCES contacts(id) ON DELETE RESTRICT,
    platform            TEXT NOT NULL,
    identifier_value    TEXT NOT NULL,
    is_primary          INTEGER NOT NULL DEFAULT 0,
    first_seen          TEXT NOT NULL,
    last_seen           TEXT NOT NULL,
    link_confidence     REAL NOT NULL DEFAULT 1.0,
    link_source         TEXT,
    UNIQUE(platform, identifier_value)
);

CREATE TABLE IF NOT EXISTS signals (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id          TEXT NOT NULL REFERENCES contacts(id) ON DELETE RESTRICT,
    identifier_id       TEXT NOT NULL REFERENCES identifiers(id) ON DELETE RESTRICT,
    collected_at        TEXT NOT NULL,
    signal_ts           TEXT,
    source              TEXT NOT NULL,
    signal_type         TEXT NOT NULL,
    source_event_id     TEXT,
    event_fingerprint   TEXT NOT NULL,
    payload             TEXT NOT NULL,
    evidence_note       TEXT,
    UNIQUE(event_fingerprint)
);

CREATE TABLE IF NOT EXISTS snapshots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id          TEXT NOT NULL REFERENCES contacts(id) ON DELETE RESTRICT,
    snapshot_ts         TEXT NOT NULL,
    rubric_name         TEXT NOT NULL,
    rubric_version      TEXT NOT NULL,
    trigger             TEXT NOT NULL,
    dimension_scores    TEXT NOT NULL,
    total_score         REAL NOT NULL,
    weighted_score      REAL NOT NULL,
    tier                TEXT NOT NULL,
    signals_used        TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id  TEXT NOT NULL REFERENCES contacts(id) ON DELETE RESTRICT,
    note_ts     TEXT NOT NULL,
    author      TEXT NOT NULL DEFAULT 'system',
    body        TEXT NOT NULL,
    privacy_tier TEXT NOT NULL DEFAULT 'private'
);

CREATE INDEX IF NOT EXISTS idx_identifiers_contact    ON identifiers(contact_id);
CREATE INDEX IF NOT EXISTS idx_signals_contact        ON signals(contact_id);
CREATE INDEX IF NOT EXISTS idx_signals_identifier     ON signals(identifier_id);
CREATE INDEX IF NOT EXISTS idx_signals_collected      ON signals(collected_at);
CREATE INDEX IF NOT EXISTS idx_signals_source         ON signals(source, signal_type);
CREATE INDEX IF NOT EXISTS idx_snapshots_contact      ON snapshots(contact_id, rubric_name, snapshot_ts);
CREATE INDEX IF NOT EXISTS idx_notes_contact          ON notes(contact_id);
CREATE INDEX IF NOT EXISTS idx_signals_fingerprint    ON signals(event_fingerprint);
"""


def init_db(db_path: str) -> sqlite3.Connection:
    """Initialize the database with full schema.

    Creates all tables and indexes, sets user_version=1.
    Idempotent — safe to call multiple times.
    """
    conn = get_connection(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    return conn
