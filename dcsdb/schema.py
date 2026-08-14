"""SQLite schema and the V1 schema version."""

from __future__ import annotations

import sqlite3


SCHEMA_VERSION = 1

EVENTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,

    event_time_ms INTEGER NOT NULL,
    event_time_text TEXT NOT NULL,

    event_type TEXT,
    category TEXT,

    area TEXT,
    node TEXT,
    unit_name TEXT,

    module TEXT,
    module_description TEXT,

    parameter TEXT,
    status TEXT,
    severity TEXT,

    description1 TEXT,
    description2 TEXT,

    source_record_no INTEGER,

    event_hash TEXT NOT NULL UNIQUE
);
"""

INDEX_SQL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_events_hash "
    "ON events(event_hash);",
    "CREATE INDEX IF NOT EXISTS idx_events_time "
    "ON events(event_time_ms);",
    "CREATE INDEX IF NOT EXISTS idx_events_module_time "
    "ON events(module, event_time_ms);",
    "CREATE INDEX IF NOT EXISTS idx_events_type_time "
    "ON events(event_type, event_time_ms);",
    "CREATE INDEX IF NOT EXISTS idx_events_parameter_time "
    "ON events(parameter, event_time_ms);",
    "CREATE INDEX IF NOT EXISTS idx_events_module_parameter_time "
    "ON events(module, parameter, event_time_ms);",
)


def initialize_schema(connection: sqlite3.Connection) -> None:
    """Create or validate the V1 schema without adding business tables."""

    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version not in (0, SCHEMA_VERSION):
        raise RuntimeError(
            f"Unsupported database schema version: {version}; expected {SCHEMA_VERSION}"
        )

    connection.execute(EVENTS_TABLE_SQL)
    for statement in INDEX_SQL:
        connection.execute(statement)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.commit()
