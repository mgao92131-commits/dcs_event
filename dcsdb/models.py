"""Data models used by the parser, importer, and repository."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class EventRecord:
    """One raw DCS event after parsing and timestamp conversion."""

    event_time_ms: int
    event_time_text: str
    event_type: str | None
    category: str | None
    area: str | None
    node: str | None
    unit_name: str | None
    module: str | None
    module_description: str | None
    parameter: str | None
    status: str | None
    severity: str | None
    description1: str | None
    description2: str | None
    source_record_no: int | None = None
    event_hash: str | None = None
    id: int | None = None


@dataclass(slots=True)
class ImportStats:
    """Counters and database state produced by one import run."""

    file_path: Path
    total_data_rows: int = 0
    parsed_rows: int = 0
    inserted_rows: int = 0
    duplicate_rows: int = 0
    error_rows: int = 0
    database_total_records: int = 0
    database_min_time_ms: int | None = None
    database_max_time_ms: int | None = None


@dataclass(frozen=True, slots=True)
class DatabaseStatus:
    path: Path
    size_bytes: int
    total_records: int
    min_time_ms: int | None
    max_time_ms: int | None
