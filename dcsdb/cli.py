"""Command-line interface for the DCS SQLite storage layer."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

from .analysis import (
    AnalysisEngine,
    AnalysisRequest,
    ReadOnlyDatabase,
    create_default_registry,
)
from .db import (
    DEFAULT_BACKUP_DIR,
    DEFAULT_DB_PATH,
    DEFAULT_LOG_PATH,
    backup_database,
    database_status,
    quick_check,
)
from .importer import EventImporter
from .models import DatabaseStatus, EventRecord, ImportStats
from .parser import DEFAULT_TIMEZONE, format_event_time_ms, parse_event_time
from .repository import EventRepository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DCS EVENTS.txt SQLite storage")
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help=f"SQLite database path (default: {DEFAULT_DB_PATH})",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser("import", help="Import an EVENTS.txt file")
    _add_db_override(import_parser)
    import_parser.add_argument("file", type=Path)
    import_parser.add_argument(
        "--log",
        default=str(DEFAULT_LOG_PATH),
        help=f"Import error log path (default: {DEFAULT_LOG_PATH})",
    )
    import_parser.add_argument(
        "--batch-size",
        type=int,
        default=5000,
        help="Rows per SQLite batch (default: 5000)",
    )

    query_parser = subparsers.add_parser("query", help="Query raw events")
    _add_db_override(query_parser)
    query_parser.add_argument("--module")
    query_parser.add_argument("--event-type")
    query_parser.add_argument("--parameter")
    query_parser.add_argument(
        "--from",
        dest="from_time",
        help="Inclusive start; date-only values mean 00:00:00",
    )
    query_parser.add_argument(
        "--to",
        dest="to_time",
        help="Exclusive end; date-only values mean that date's 00:00:00",
    )
    query_parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum rows to print; 0 means no limit (default: 100)",
    )

    status_parser = subparsers.add_parser("status", help="Show database status")
    _add_db_override(status_parser)
    check_parser = subparsers.add_parser("check", help="Run SQLite integrity check")
    _add_db_override(check_parser)
    check_parser.add_argument(
        "--full",
        action="store_true",
        help="Use integrity_check instead of quick_check",
    )

    backup_parser = subparsers.add_parser("backup", help="Create a consistent backup")
    _add_db_override(backup_parser)
    backup_parser.add_argument(
        "--output",
        type=Path,
        help="Backup file; default is backup/dcs_events_YYYYMMDD_HHMMSS.db",
    )
    backup_parser.add_argument(
        "--dir",
        type=Path,
        default=DEFAULT_BACKUP_DIR,
        help=f"Backup directory (default: {DEFAULT_BACKUP_DIR})",
    )

    analysis_parser = subparsers.add_parser("analysis", help="Run read-only analysis")
    _add_db_override(analysis_parser)
    analysis_subparsers = analysis_parser.add_subparsers(
        dest="analysis_command",
        required=True,
    )
    analysis_list_parser = analysis_subparsers.add_parser(
        "list", help="List registered analysis components"
    )
    _add_db_override(analysis_list_parser)

    analysis_run_parser = analysis_subparsers.add_parser(
        "run", help="Run one analysis component"
    )
    _add_db_override(analysis_run_parser)
    analysis_run_parser.add_argument("component_id")
    analysis_run_parser.add_argument(
        "--date",
        help="Local plant date, for example 2026-08-18",
    )
    analysis_run_parser.add_argument(
        "--from",
        dest="from_time",
        help="Inclusive start timestamp",
    )
    analysis_run_parser.add_argument(
        "--to",
        dest="to_time",
        help="Exclusive end timestamp",
    )
    analysis_run_parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum rows to print; 0 means no limit (default: 100)",
    )
    return parser


def _add_db_override(parser: argparse.ArgumentParser) -> None:
    """Allow the common ``command ... --db path`` spelling as well."""

    parser.add_argument("--db", dest="db", default=argparse.SUPPRESS, help=argparse.SUPPRESS)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "import":
            stats = EventImporter(
                db_path=args.db,
                log_path=args.log,
                batch_size=args.batch_size,
            ).import_file(args.file)
            print_import_stats(stats)
        elif args.command == "query":
            if args.limit < 0:
                raise ValueError("--limit must be non-negative")
            repository = EventRepository(args.db)
            rows = repository.query(
                start_time=_parse_query_time(args.from_time),
                end_time=_parse_query_time(args.to_time),
                event_type=args.event_type,
                module=args.module,
                parameter=args.parameter,
                limit=None if args.limit == 0 else args.limit,
            )
            print_query_rows(rows)
        elif args.command == "status":
            print_status(database_status(args.db))
        elif args.command == "check":
            results = quick_check(args.db, full=args.full)
            if results == ["ok"]:
                print("Database OK")
            else:
                for result in results:
                    print(result)
                return 1
        elif args.command == "backup":
            output = args.output or _next_backup_path(args.dir)
            print(f"Backup: {backup_database(args.db, output)}")
        elif args.command == "analysis":
            _run_analysis(args)
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def _parse_query_time(value: str | None) -> int | None:
    if value is None:
        return None
    if len(value) == 10 and value[4] == "-" and value[7] == "-":
        parsed = datetime.strptime(value, "%Y-%m-%d")
        return parse_event_time(
            parsed.strftime("%Y/%m/%d 00:00:00.000"),
            time_zone=DEFAULT_TIMEZONE,
        )

    candidate = value.replace("T", " ").replace("/", "-")
    parsed = datetime.fromisoformat(candidate)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=DEFAULT_TIMEZONE)
    return int(parsed.timestamp() * 1000)


def _build_analysis_request(args: argparse.Namespace) -> AnalysisRequest:
    if args.date is not None and (args.from_time is not None or args.to_time is not None):
        raise ValueError("Use --date or --from/--to, not both")
    if args.to_time is not None and args.from_time is None:
        raise ValueError("--to requires --from")

    if args.date is not None:
        date_value = datetime.strptime(args.date, "%Y-%m-%d").date()
        start = datetime.combine(
            date_value,
            datetime.min.time(),
            tzinfo=DEFAULT_TIMEZONE,
        )
        end = start + timedelta(days=1)
        return AnalysisRequest(
            start_time_ms=int(start.timestamp() * 1000),
            end_time_ms=int(end.timestamp() * 1000),
        )

    return AnalysisRequest(
        start_time_ms=_parse_query_time(args.from_time),
        end_time_ms=_parse_query_time(args.to_time),
    )


def _run_analysis(args: argparse.Namespace) -> None:
    registry = create_default_registry()
    if args.analysis_command == "list":
        for component in registry.list():
            print(f"{component.id}\t{component.name}")
        return

    if args.limit < 0:
        raise ValueError("--limit must be non-negative")
    request = _build_analysis_request(args)
    engine = AnalysisEngine(ReadOnlyDatabase(args.db), registry)
    results = iter(engine.run(args.component_id, request))
    printed = 0
    print(
        "event_id\tevent_time_text\tmodule\tmodule_description\tparameter\t"
        "old_value\tnew_value\tdescription1\tdescription2"
    )
    try:
        for result in results:
            if args.limit and printed >= args.limit:
                break
            print(
                "\t".join(
                    _display_value(getattr(result, field))
                    for field in (
                        "event_id",
                        "event_time_text",
                        "module",
                        "module_description",
                        "parameter",
                        "old_value",
                        "new_value",
                        "description1",
                        "description2",
                    )
                )
            )
            printed += 1
    finally:
        close = getattr(results, "close", None)
        if close is not None:
            close()
    print(f"returned={printed}")


def _next_backup_path(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stem = datetime.now().strftime("dcs_events_%Y%m%d_%H%M%S")
    candidate = directory / f"{stem}.db"
    suffix = 1
    while candidate.exists():
        candidate = directory / f"{stem}_{suffix}.db"
        suffix += 1
    return candidate


def print_import_stats(stats: ImportStats) -> None:
    print(f"文件：{stats.file_path}")
    print(f"总数据行：{stats.total_data_rows:,}")
    print(f"成功解析：{stats.parsed_rows:,}")
    print(f"新增：{stats.inserted_rows:,}")
    print(f"重复：{stats.duplicate_rows:,}")
    print(f"错误：{stats.error_rows:,}")
    print(f"数据库当前总记录：{stats.database_total_records:,}")
    print("数据库时间范围：")
    print(
        f"{format_event_time_ms(stats.database_min_time_ms) if stats.database_min_time_ms is not None else '-'}"
    )
    print("～")
    print(
        f"{format_event_time_ms(stats.database_max_time_ms) if stats.database_max_time_ms is not None else '-'}"
    )


def print_status(status: DatabaseStatus) -> None:
    print(f"数据库：{status.path}")
    print(f"数据库大小：{_format_size(status.size_bytes)}")
    print(f"事件总数：{status.total_records:,}")
    print(
        "最早记录："
        + (
            format_event_time_ms(status.min_time_ms)
            if status.min_time_ms is not None
            else "-"
        )
    )
    print(
        "最新记录："
        + (
            format_event_time_ms(status.max_time_ms)
            if status.max_time_ms is not None
            else "-"
        )
    )


def print_query_rows(rows: list[EventRecord]) -> None:
    print(
        "id\tevent_time_text\tevent_type\tcategory\tarea\tnode\tunit_name\t"
        "module\tmodule_description\tparameter\tstatus\tseverity\tdescription1\t"
        "description2\tsource_record_no\tevent_hash"
    )
    for row in rows:
        print(
            "\t".join(
                _display_value(getattr(row, field))
                for field in (
                    "id",
                    "event_time_text",
                    "event_type",
                    "category",
                    "area",
                    "node",
                    "unit_name",
                    "module",
                    "module_description",
                    "parameter",
                    "status",
                    "severity",
                    "description1",
                    "description2",
                    "source_record_no",
                    "event_hash",
                )
            )
        )
    print(f"返回记录：{len(rows):,}")


def _display_value(value: object) -> str:
    return "" if value is None else str(value).replace("\r", "").replace("\n", "\\n")


def _format_size(size_bytes: int) -> str:
    value = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{size_bytes} B"
