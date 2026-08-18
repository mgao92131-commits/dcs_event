"""A deliberately read-only SQLite boundary for analysis components."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import Any


class ReadOnlyViolation(PermissionError):
    """Raised when an analysis query attempts to mutate the database."""


_WRITE_KEYWORDS = frozenset(
    {
        "insert",
        "update",
        "delete",
        "replace",
        "create",
        "drop",
        "alter",
        "attach",
        "detach",
        "reindex",
        "vacuum",
        "pragma",
    }
)
_FIRST_KEYWORD_RE = re.compile(r"^\s*(?P<keyword>[A-Za-z]+)")


def _action_constants(*names: str) -> frozenset[int]:
    return frozenset(
        getattr(sqlite3, name)
        for name in names
        if hasattr(sqlite3, name)
    )


_DENIED_AUTHORIZE_ACTIONS = _action_constants(
    "SQLITE_INSERT",
    "SQLITE_UPDATE",
    "SQLITE_DELETE",
    "SQLITE_CREATE_INDEX",
    "SQLITE_CREATE_TABLE",
    "SQLITE_CREATE_TEMP_INDEX",
    "SQLITE_CREATE_TEMP_TABLE",
    "SQLITE_CREATE_TEMP_TRIGGER",
    "SQLITE_CREATE_TEMP_VIEW",
    "SQLITE_CREATE_TRIGGER",
    "SQLITE_CREATE_VIEW",
    "SQLITE_CREATE_VTABLE",
    "SQLITE_DROP_INDEX",
    "SQLITE_DROP_TABLE",
    "SQLITE_DROP_TEMP_INDEX",
    "SQLITE_DROP_TEMP_TABLE",
    "SQLITE_DROP_TEMP_TRIGGER",
    "SQLITE_DROP_TEMP_VIEW",
    "SQLITE_DROP_TRIGGER",
    "SQLITE_DROP_VIEW",
    "SQLITE_DROP_VTABLE",
    "SQLITE_ALTER_TABLE",
    "SQLITE_ATTACH",
    "SQLITE_DETACH",
    "SQLITE_REINDEX",
    "SQLITE_ANALYZE",
    "SQLITE_COPY",
    "SQLITE_SAVEPOINT",
)
_SQLITE_PRAGMA = getattr(sqlite3, "SQLITE_PRAGMA", -1)
_SQLITE_FUNCTION = getattr(sqlite3, "SQLITE_FUNCTION", -1)
_DENIED_FUNCTIONS = frozenset({"load_extension", "writefile"})


def _authorizer(
    action: int,
    arg1: str | None,
    arg2: str | None,
    _database_name: str | None,
    _source_name: str | None,
) -> int:
    if action in _DENIED_AUTHORIZE_ACTIONS or action == _SQLITE_PRAGMA:
        return sqlite3.SQLITE_DENY
    if action == _SQLITE_FUNCTION:
        function_name = (arg2 or arg1 or "").lower()
        if function_name in _DENIED_FUNCTIONS:
            return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


class ReadOnlyDatabase:
    """Open the database with SQLite's URI-level read-only mode.

    Connections are short-lived for ``execute`` and remain open only for the
    lifetime of a ``stream`` iterator. This keeps the component API small and
    prevents callers from retaining a writable connection accidentally.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.path = Path(db_path)
        if not self.path.exists():
            raise FileNotFoundError(f"Database does not exist: {self.path}")
        if not self.path.is_file():
            raise ValueError(f"Database path is not a file: {self.path}")

    def _connect(self) -> sqlite3.Connection:
        uri = self.path.resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.set_authorizer(_authorizer)
        return connection

    def execute(
        self,
        sql: str,
        params: Sequence[Any] | Iterable[Any] = (),
    ) -> list[sqlite3.Row]:
        """Execute one read query and return its rows."""

        self._reject_direct_write_statement(sql)
        connection = self._connect()
        try:
            try:
                return connection.execute(sql, params).fetchall()
            except sqlite3.DatabaseError as exc:
                raise _translate_database_error(exc) from exc
        finally:
            connection.close()

    def stream(
        self,
        sql: str,
        params: Sequence[Any] | Iterable[Any] = (),
        *,
        batch_size: int = 1000,
    ) -> Iterator[sqlite3.Row]:
        """Stream rows without materializing the complete result set."""

        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self._reject_direct_write_statement(sql)
        connection = self._connect()
        try:
            try:
                cursor = connection.execute(sql, params)
                while True:
                    rows = cursor.fetchmany(batch_size)
                    if not rows:
                        break
                    yield from rows
            except sqlite3.DatabaseError as exc:
                raise _translate_database_error(exc) from exc
        finally:
            connection.close()

    @staticmethod
    def _reject_direct_write_statement(sql: str) -> None:
        match = _FIRST_KEYWORD_RE.match(sql)
        if match and match.group("keyword").lower() in _WRITE_KEYWORDS:
            raise ReadOnlyViolation("ReadOnlyDatabase rejected a write statement")


def _translate_database_error(error: sqlite3.DatabaseError) -> Exception:
    message = str(error).lower()
    if any(
        phrase in message
        for phrase in (
            "not authorized",
            "readonly database",
            "read-only database",
            "attempt to write a readonly database",
            "cannot vacuum",
        )
    ):
        return ReadOnlyViolation(str(error))
    return error
