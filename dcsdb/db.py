"""SQLite connection and database utility functions."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import DatabaseStatus
from .schema import initialize_schema


DEFAULT_DB_PATH = Path("data") / "dcs_events.db"
DEFAULT_LOG_PATH = Path("logs") / "import.log"
DEFAULT_BACKUP_DIR = Path("backup")


def connect(
    db_path: str | Path = DEFAULT_DB_PATH,
    *,
    create: bool = True,
) -> sqlite3.Connection:
    """Open a configured SQLite connection.

    ``create=False`` is used by read-only commands so a typo does not silently
    create an empty database.
    """

    path_text = str(db_path)
    if path_text != ":memory:":
        path = Path(db_path)
        if not create and not path.exists():
            raise FileNotFoundError(f"Database does not exist: {path}")
        if create:
            path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(
        path_text,
        timeout=5.0,
        isolation_level=None,
    )
    connection.row_factory = sqlite3.Row

    # WAL is ignored by SQLite for an in-memory database, which is fine for
    # tests. The remaining settings are valid for both in-memory and files.
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA temp_store = MEMORY")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def initialize_database(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    connection = connect(db_path)
    try:
        initialize_schema(connection)
    finally:
        connection.close()


def database_status(db_path: str | Path = DEFAULT_DB_PATH) -> DatabaseStatus:
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"Database does not exist: {path}")

    connection = connect(path, create=False)
    try:
        row = connection.execute(
            "SELECT COUNT(*) AS total, MIN(event_time_ms) AS min_time, "
            "MAX(event_time_ms) AS max_time FROM events"
        ).fetchone()
        return DatabaseStatus(
            path=path,
            size_bytes=path.stat().st_size,
            total_records=int(row["total"]),
            min_time_ms=row["min_time"],
            max_time_ms=row["max_time"],
        )
    finally:
        connection.close()


def quick_check(db_path: str | Path = DEFAULT_DB_PATH, *, full: bool = False) -> list[str]:
    """Run SQLite quick_check, or the more expensive integrity_check."""

    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"Database does not exist: {path}")

    # Do not create or mutate a database during a health check.
    uri = path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5.0)
    try:
        pragma = "integrity_check" if full else "quick_check"
        return [str(row[0]) for row in connection.execute(f"PRAGMA {pragma}")]
    finally:
        connection.close()


def backup_database(
    source_path: str | Path = DEFAULT_DB_PATH,
    destination_path: str | Path | None = None,
) -> Path:
    """Create a consistent SQLite backup using SQLite's backup API."""

    source = Path(source_path)
    if not source.exists():
        raise FileNotFoundError(f"Database does not exist: {source}")

    if destination_path is None:
        raise ValueError("A backup destination is required")
    destination = Path(destination_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() == destination.resolve():
        raise ValueError("Backup destination must differ from the source database")
    if destination.exists():
        raise FileExistsError(f"Backup destination already exists: {destination}")

    source_connection = connect(source, create=False)
    destination_connection = sqlite3.connect(str(destination), timeout=5.0)
    try:
        source_connection.backup(destination_connection)
        destination_connection.commit()
    finally:
        destination_connection.close()
        source_connection.close()
    return destination
