from __future__ import annotations

import io
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from dcsdb.cli import main
from dcsdb.db import backup_database, database_status, quick_check
from dcsdb.hasher import compute_event_hash
from dcsdb.importer import EventImporter
from dcsdb.models import EventRecord
from dcsdb.parser import (
    DCSLogParser,
    HeaderValidationError,
    parse_event_time,
)
from dcsdb.repository import EventRepository


HEADER = (
    "\t日期/时间*\t事件类型\t类别\t厂区\t节点\t单元\t模块\t模块描述\t"
    "参数\t状态\t级别\t描述1\t描述2\r\n"
)


def event_line(
    number: int,
    event_time: str,
    *,
    event_type: str = "报警",
    module: str = "PICA-117024",
    parameter: str = "HI_HI_ALM",
    description2: str = "高高报警值 12.9181 门限值 10.5",
) -> str:
    values = [
        str(number),
        event_time,
        event_type,
        "过程",
        "AREA2-1",
        "IP02",
        "",
        module,
        "终缩聚反应器报警",
        parameter,
        "已报警/已确认",
        "15-危急",
        "高高报",
        description2,
    ]
    return "\t".join(values) + "\r\n"


def write_events(path: Path, rows: list[str], *, encoding: str = "gb18030") -> None:
    path.write_bytes((HEADER + "".join(rows)).encode(encoding))


class DCSDatabaseTests(unittest.TestCase):
    def test_parser_preserves_fields_and_milliseconds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "EVENTS.txt"
            write_events(
                path,
                [
                    event_line(1, "2026/8/13 14:24:53.001"),
                    event_line(2, "2026/8/13 14:24:53.002"),
                ],
            )

            results = list(DCSLogParser().parse(path))
            self.assertEqual(len(results), 2)
            first = results[0].record
            second = results[1].record
            assert first is not None and second is not None
            self.assertEqual(second.event_time_ms - first.event_time_ms, 1)
            self.assertEqual(first.event_time_text, "2026/8/13 14:24:53.001")
            self.assertEqual(first.description2, "高高报警值 12.9181 门限值 10.5")
            self.assertEqual(first.source_record_no, 1)

    def test_parser_accepts_utf8_and_utf8_bom(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for encoding in ("utf-8", "utf-8-sig"):
                path = Path(directory) / f"EVENTS-{encoding}.txt"
                write_events(
                    path,
                    [event_line(1, "2026/8/13 14:24:53.001")],
                    encoding=encoding,
                )
                results = list(DCSLogParser().parse(path))
                self.assertEqual(len(results), 1)
                self.assertIsNotNone(results[0].record)

    def test_parser_accepts_dcs_midnight_compact_time(self) -> None:
        compact = parse_event_time("2026/8/9 (.813)")
        expanded = parse_event_time("2026/8/9 00:00:00.813")
        self.assertEqual(compact, expanded)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "EVENTS.txt"
            write_events(path, [event_line(1, "2026/8/9 (.813)")])
            result = list(DCSLogParser().parse(path))[0]
            self.assertIsNotNone(result.record)
            assert result.record is not None
            self.assertEqual(result.record.event_time_text, "2026/8/9 (.813)")
            self.assertEqual(result.record.event_time_ms, expanded)

    def test_hash_uses_raw_event_fields_but_not_source_number(self) -> None:
        common = dict(
            event_time_ms=parse_event_time("2026/8/13 14:24:53.001"),
            event_time_text="2026/8/13 14:24:53.001",
            event_type="报警",
            category="过程",
            area="AREA2-1",
            node="IP02",
            unit_name="",
            module="PICA-117024",
            module_description="终缩聚反应器报警",
            parameter="HI_HI_ALM",
            status="已报警/已确认",
            severity="15-危急",
            description1="高高报",
            description2="高高报警值 12.9181 门限值 10.5",
        )
        first = EventRecord(**common, source_record_no=1)
        same_event = EventRecord(**common, source_record_no=999)
        changed_values = {**common, "description1": "高报"}
        changed = EventRecord(**changed_values)
        self.assertEqual(compute_event_hash(first), compute_event_hash(same_event))
        self.assertNotEqual(compute_event_hash(first), compute_event_hash(changed))

    def test_import_deduplicates_repeated_and_overlapping_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / "data" / "dcs_events.db"
            log_path = root / "logs" / "import.log"
            file_a = root / "A.txt"
            file_b = root / "B.txt"
            write_events(
                file_a,
                [
                    event_line(1, "2026/8/13 14:24:53.001"),
                    event_line(2, "2026/8/13 14:24:53.002"),
                    event_line(3, "2026/8/13 14:24:53.003"),
                ],
            )
            write_events(
                file_b,
                [
                    event_line(101, "2026/8/13 14:24:53.002"),
                    event_line(102, "2026/8/13 14:24:53.003"),
                    event_line(103, "2026/8/13 14:24:53.004", parameter="LO_ALM"),
                ],
            )

            importer = EventImporter(db_path, log_path, batch_size=2)
            first = importer.import_file(file_a)
            second = importer.import_file(file_b)
            repeated = importer.import_file(file_a)

            self.assertEqual((first.parsed_rows, first.inserted_rows), (3, 3))
            self.assertEqual((second.parsed_rows, second.inserted_rows), (3, 1))
            self.assertEqual(second.duplicate_rows, 2)
            self.assertEqual((repeated.inserted_rows, repeated.duplicate_rows), (0, 3))
            self.assertEqual(EventRepository(db_path).count(), 4)

            queried = EventRepository(db_path).query(
                module="PICA-117024",
                event_type="报警",
                parameter="LO_ALM",
            )
            self.assertEqual(len(queried), 1)
            self.assertEqual(queried[0].event_time_text, "2026/8/13 14:24:53.004")

            connection = sqlite3.connect(db_path)
            try:
                tables = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall()
            finally:
                connection.close()
            self.assertEqual(tables, [("events",)])

    def test_bad_rows_are_reported_and_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "damaged.txt"
            db_path = root / "dcs_events.db"
            log_path = root / "import.log"
            bad_columns = "2\t2026/8/13 14:24:53.002\t报警\r\n"
            bad_time = event_line(3, "not-a-date")
            write_events(source, [event_line(1, "2026/8/13 14:24:53.001"), bad_columns, bad_time])

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                stats = EventImporter(db_path, log_path).import_file(source)

            self.assertEqual(stats.total_data_rows, 3)
            self.assertEqual(stats.parsed_rows, 1)
            self.assertEqual(stats.error_rows, 2)
            self.assertEqual(EventRepository(db_path).count(), 1)
            log_text = log_path.read_text(encoding="utf-8")
            self.assertIn("ERROR line=", log_text)
            self.assertIn("Invalid datetime", log_text)
            self.assertIn("ERROR line=3", stderr.getvalue())

    def test_header_error_is_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad-header.txt"
            path.write_bytes("\t日期/时间*\t模块\r\n".encode("gb18030"))
            with self.assertRaises(HeaderValidationError):
                list(DCSLogParser().parse(path))

    def test_status_check_and_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "EVENTS.txt"
            db_path = root / "data" / "dcs_events.db"
            backup_path = root / "backup" / "copy.db"
            write_events(source, [event_line(1, "2026/8/13 14:24:53.001")])
            EventImporter(db_path, root / "import.log").import_file(source)

            status = database_status(db_path)
            self.assertEqual(status.total_records, 1)
            self.assertEqual(quick_check(db_path), ["ok"])
            self.assertEqual(backup_database(db_path, backup_path), backup_path)
            self.assertEqual(database_status(backup_path).total_records, 1)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["--db", str(db_path), "status"])
            self.assertEqual(exit_code, 0)
            self.assertIn("事件总数：1", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
