"""Query access for future analysis modules."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from .db import DEFAULT_DB_PATH, connect
from .models import EventRecord


class EventRepository:
    """SQLite-backed query interface for raw events."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)

    def query(
        self,
        start_time: int | datetime | None = None,
        end_time: int | datetime | None = None,
        event_type: str | None = None,
        module: str | None = None,
        parameter: str | None = None,
        limit: int | None = None,
    ) -> list[EventRecord]:
        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative or None")

        clauses: list[str] = []
        parameters: list[Any] = []
        if start_time is not None:
            clauses.append("event_time_ms >= ?")
            parameters.append(_to_epoch_ms(start_time))
        if end_time is not None:
            clauses.append("event_time_ms < ?")
            parameters.append(_to_epoch_ms(end_time))
        if event_type is not None:
            clauses.append("event_type = ?")
            parameters.append(event_type)
        if module is not None:
            clauses.append("module = ?")
            parameters.append(module)
        if parameter is not None:
            clauses.append("parameter = ?")
            parameters.append(parameter)

        sql = "SELECT * FROM events"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY event_time_ms, id"
        if limit is not None:
            sql += " LIMIT ?"
            parameters.append(limit)

        connection = connect(self.db_path, create=False)
        try:
            rows = connection.execute(sql, parameters).fetchall()
            return [_row_to_event(row) for row in rows]
        finally:
            connection.close()

    def count(self) -> int:
        connection = connect(self.db_path, create=False)
        try:
            return int(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0])
        finally:
            connection.close()


def _to_epoch_ms(value: int | datetime) -> int:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("datetime query values must include a timezone")
        return int(value.timestamp() * 1000)
    return int(value)


def _row_to_event(row: sqlite3.Row) -> EventRecord:
    return EventRecord(
        event_time_ms=int(row["event_time_ms"]),
        event_time_text=row["event_time_text"],
        event_type=row["event_type"],
        category=row["category"],
        area=row["area"],
        node=row["node"],
        unit_name=row["unit_name"],
        module=row["module"],
        module_description=row["module_description"],
        parameter=row["parameter"],
        status=row["status"],
        severity=row["severity"],
        description1=row["description1"],
        description2=row["description2"],
        source_record_no=row["source_record_no"],
        event_hash=row["event_hash"],
        id=row["id"],
    )
