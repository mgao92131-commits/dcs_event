"""Transactional, batched import of EVENTS.txt into SQLite."""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from .db import DEFAULT_DB_PATH, DEFAULT_LOG_PATH, connect
from .hasher import compute_event_hash
from .models import EventRecord, ImportStats
from .parser import DCSLogParser, ParserError, ParseIssue
from .schema import initialize_schema


INSERT_SQL = """
INSERT OR IGNORE INTO events (
    event_time_ms,
    event_time_text,
    event_type,
    category,
    area,
    node,
    unit_name,
    module,
    module_description,
    parameter,
    status,
    severity,
    description1,
    description2,
    source_record_no,
    event_hash
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _event_values(record: EventRecord, event_hash: str) -> tuple[object, ...]:
    return (
        record.event_time_ms,
        record.event_time_text,
        record.event_type,
        record.category,
        record.area,
        record.node,
        record.unit_name,
        record.module,
        record.module_description,
        record.parameter,
        record.status,
        record.severity,
        record.description1,
        record.description2,
        record.source_record_no,
        event_hash,
    )


def _write_parse_issue(log_path: Path, issue: ParseIssue) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    raw = issue.raw.replace("\r", "\\r").replace("\n", "\\n")
    with log_path.open("a", encoding="utf-8", newline="") as handle:
        handle.write(
            f"{timestamp} ERROR line={issue.line_no} "
            f"{issue.message} raw={raw}\n"
        )


class EventImporter:
    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB_PATH,
        log_path: str | Path = DEFAULT_LOG_PATH,
        *,
        batch_size: int = 5000,
        parser: DCSLogParser | None = None,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self.db_path = Path(db_path)
        self.log_path = Path(log_path)
        self.batch_size = batch_size
        self.parser = parser or DCSLogParser()

    def import_file(self, file_path: str | Path) -> ImportStats:
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Input file does not exist: {file_path}")

        stats = ImportStats(file_path=file_path)
        connection = connect(self.db_path)
        try:
            initialize_schema(connection)
            connection.execute("BEGIN")
            batch: list[tuple[object, ...]] = []

            try:
                for result in self.parser.parse(file_path):
                    stats.total_data_rows += 1
                    if result.issue is not None:
                        stats.error_rows += 1
                        _write_parse_issue(self.log_path, result.issue)
                        print(
                            f"ERROR line={result.issue.line_no} {result.issue.message}",
                            file=sys.stderr,
                        )
                        continue

                    assert result.record is not None
                    stats.parsed_rows += 1
                    event_hash = compute_event_hash(result.record)
                    batch.append(_event_values(result.record, event_hash))
                    if len(batch) >= self.batch_size:
                        stats.inserted_rows += self._insert_batch(connection, batch)
                        batch.clear()

                if batch:
                    stats.inserted_rows += self._insert_batch(connection, batch)
                    batch.clear()

                stats.duplicate_rows = stats.parsed_rows - stats.inserted_rows
                connection.commit()
            except Exception:
                connection.rollback()
                raise

            row = connection.execute(
                "SELECT COUNT(*) AS total, MIN(event_time_ms) AS min_time, "
                "MAX(event_time_ms) AS max_time FROM events"
            ).fetchone()
            stats.database_total_records = int(row["total"])
            stats.database_min_time_ms = row["min_time"]
            stats.database_max_time_ms = row["max_time"]
            return stats
        finally:
            connection.close()

    @staticmethod
    def _insert_batch(
        connection: sqlite3.Connection,
        batch: list[tuple[object, ...]],
    ) -> int:
        before = connection.total_changes
        connection.executemany(INSERT_SQL, batch)
        return connection.total_changes - before
