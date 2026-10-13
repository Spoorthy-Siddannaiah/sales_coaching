"""SQLite schema and short-lived connections; no ORM or background workers."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL CHECK (provider = 'notion'),
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    source_url TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (provider, source_id)
);
CREATE TABLE IF NOT EXISTS transcript_versions (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    content_hash TEXT NOT NULL,
    original_text TEXT NOT NULL,
    source_metadata TEXT NOT NULL DEFAULT '{}',
    turns TEXT NOT NULL DEFAULT '[]',
    warnings TEXT NOT NULL DEFAULT '[]',
    imported_at TEXT NOT NULL,
    UNIQUE (conversation_id, content_hash)
);
CREATE TABLE IF NOT EXISTS analyses (
    id TEXT PRIMARY KEY,
    transcript_version_id TEXT NOT NULL REFERENCES transcript_versions(id),
    customer_context TEXT NOT NULL,
    objective TEXT NOT NULL,
    salesperson TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'completed', 'failed')),
    model TEXT NOT NULL,
    report TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    CHECK (
        (status = 'pending' AND report IS NULL AND error_message IS NULL)
        OR (status = 'completed' AND report IS NOT NULL AND error_message IS NULL)
        OR (status = 'failed' AND report IS NULL AND error_message IS NOT NULL)
    )
);
"""

# One explicit migration is enough for this prototype; no migration framework.
LEGACY_SCHEMA = SCHEMA
SCHEMA = SCHEMA.replace("CHECK (provider = 'notion')", "CHECK (provider IN ('notion', 'offline_fixture'))")
SCHEMA = SCHEMA.replace("    created_at TEXT NOT NULL,\n    UNIQUE (provider", "    created_at TEXT NOT NULL,\n    customer_context TEXT,\n    context_updated_at TEXT,\n    UNIQUE (provider")
SCHEMA = SCHEMA.replace("salesperson TEXT NOT NULL", "salesperson TEXT")
SCHEMA = SCHEMA.replace("('pending', 'completed', 'failed')", "('pending', 'analyzing', 'completed', 'failed')")
SCHEMA = SCHEMA.replace("    created_at TEXT NOT NULL,\n    CHECK (", "    created_at TEXT NOT NULL,\n    request_id TEXT UNIQUE,\n    provider TEXT,\n    started_at TEXT,\n    finished_at TEXT,\n    latency_seconds REAL,\n    provider_metadata TEXT NOT NULL DEFAULT '{}',\n    CHECK (")
SCHEMA = SCHEMA.replace("status = 'pending' AND", "status IN ('pending', 'analyzing') AND")



@contextmanager
def connect_database(path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    try:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='conversations'").fetchone()
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version > 1:
            raise sqlite3.DatabaseError("Database schema is newer than this application.")
        if exists and version == 0:
            backup = path.with_name(path.stem + ".before-workflow.sqlite3")
            if not backup.exists():
                with sqlite3.connect(backup) as destination:
                    db.backup(destination)
            # Rebuild together because SQLite cannot alter CHECK constraints.
            db.execute("PRAGMA foreign_keys = OFF")
            db.execute("BEGIN IMMEDIATE")
            for name in ("analyses", "transcript_versions", "conversations"):
                db.execute(f"ALTER TABLE {name} RENAME TO {name}_legacy")
            for statement in SCHEMA.split(";"):
                if statement.strip():
                    db.execute(statement)
            for name in ("conversations", "transcript_versions", "analyses"):
                columns = [row[1] for row in db.execute(f"PRAGMA table_info({name}_legacy)")]
                joined = ",".join(columns)
                db.execute(f"INSERT INTO {name} ({joined}) SELECT {joined} FROM {name}_legacy")
            for name in ("analyses", "transcript_versions", "conversations"):
                db.execute(f"DROP TABLE {name}_legacy")
            if db.execute("PRAGMA foreign_key_check").fetchone():
                raise sqlite3.IntegrityError("Migration failed foreign-key verification.")
            db.execute("PRAGMA user_version = 1")
            db.commit()
        else:
            db.executescript(SCHEMA)
            db.execute("PRAGMA user_version = 1")
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def check_database(path: Path) -> None:
    # Read an application table so an empty/missing schema is not called healthy.
    with connect_database(path) as connection:
        connection.execute("SELECT id FROM conversations LIMIT 1").fetchone()
