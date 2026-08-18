from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from dcsdb.analysis import (
    AnalysisContext,
    AnalysisEngine,
    AnalysisRegistry,
    AnalysisRequest,
    ReadOnlyDatabase,
    ReadOnlyViolation,
    create_default_registry,
)
from dcsdb.analysis.components.setpoint_changes.component import (
    SetpointChangesComponent,
)
from dcsdb.cli import main
from dcsdb.importer import EventImporter
from dcsdb.parser import parse_event_time


HEADER = (
    "\t日期/时间*\t事件类型\t类别\t厂区\t节点\t单元\t模块\t模块描述\t"
    "参数\t状态\t级别\t描述1\t描述2\r\n"
)


def make_row(
    number: int,
    event_time: str,
    *,
    event_type: str = "改变",
    module: str = "TICA-117109",
    parameter: str = "PID1/SP.CV",
    description1: str = "SUPERVISOR",
    description2: str = "新值 = 2.5",
) -> str:
    values = [
        str(number),
        event_time,
        event_type,
        "用户",
        "AREA2-1",
        "IP02",
        "",
        module,
        "控制回路",
        parameter,
        "",
        "",
        description1,
        description2,
    ]
    return "\t".join(values) + "\r\n"


def create_database(root: Path) -> Path:
    source = root / "events.txt"
    source.write_bytes(
        (
            HEADER
            + make_row(
                1,
                "2026/8/18 01:02:03.004",
                description2="旧值 = 1.5 新值 = 2.5",
            )
            + make_row(
                2,
                "2026/8/18 02:00:00.000",
                module="PICA-117024",
            )
            + make_row(
                3,
                "2026/8/18 03:00:00.000",
                parameter="PID1/MODE.TARGET",
            )
            + make_row(
                4,
                "2026/8/18 04:00:00.000",
                event_type="报警",
            )
            + make_row(
                5,
                "2026/8/19 01:00:00.000",
            )
        ).encode("gb18030")
    )
    database = root / "events.db"
    EventImporter(database, root / "import.log").import_file(source)
    return database


class ReadOnlyDatabaseTests(unittest.TestCase):
    def test_read_queries_and_stream_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = create_database(Path(directory))
            read_only = ReadOnlyDatabase(database)
            rows = read_only.execute("SELECT COUNT(*) AS n FROM events")
            self.assertEqual(rows[0]["n"], 5)
            streamed = list(read_only.stream("SELECT id FROM events ORDER BY id"))
            self.assertEqual(len(streamed), 5)

    def test_write_operations_are_rejected_and_data_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = create_database(Path(directory))
            read_only = ReadOnlyDatabase(database)
            statements = (
                "INSERT INTO events(event_time_ms,event_time_text,event_hash) VALUES (1,'x','x')",
                "UPDATE events SET status = 'x'",
                "DELETE FROM events",
                "CREATE TABLE forbidden (id INTEGER)",
                "DROP TABLE events",
                "ALTER TABLE events ADD COLUMN forbidden TEXT",
                "ATTACH DATABASE ':memory:' AS other",
                "DETACH DATABASE other",
                "REINDEX",
                "VACUUM",
                "PRAGMA query_only = OFF",
                "WITH target AS (SELECT id FROM events LIMIT 1) DELETE FROM events WHERE id IN (SELECT id FROM target)",
            )
            for statement in statements:
                with self.subTest(statement=statement):
                    with self.assertRaises(ReadOnlyViolation):
                        read_only.execute(statement)
            rows = read_only.execute("SELECT COUNT(*) AS n FROM events")
            self.assertEqual(rows[0]["n"], 5)

    def test_missing_database_is_not_created(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.db"
            with self.assertRaises(FileNotFoundError):
                ReadOnlyDatabase(path)
            self.assertFalse(path.exists())


class AnalysisFrameworkTests(unittest.TestCase):
    def test_registry_engine_and_setpoint_component(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = create_database(Path(directory))
            registry = create_default_registry()
            self.assertEqual([item.id for item in registry.list()], ["setpoint_changes"])
            engine = AnalysisEngine(ReadOnlyDatabase(database), registry)
            request = AnalysisRequest(
                start_time_ms=parse_event_time("2026/8/18 00:00:00.000"),
                end_time_ms=parse_event_time("2026/8/19 00:00:00.000"),
            )
            results = list(engine.run("setpoint_changes", request))
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].module, "TICA-117109")
            self.assertEqual(results[0].parameter, "PID1/SP.CV")
            self.assertEqual(results[0].old_value, 1.5)
            self.assertEqual(results[0].new_value, 2.5)

    def test_component_cannot_write_through_context(self) -> None:
        class WriteComponent:
            id = "write-test"
            name = "Write Test"

            def run(self, context, request):
                context.db.execute("DELETE FROM events")
                return ()

        with tempfile.TemporaryDirectory() as directory:
            database = create_database(Path(directory))
            registry = AnalysisRegistry()
            registry.register(WriteComponent())
            engine = AnalysisEngine(ReadOnlyDatabase(database), registry)
            with self.assertRaises(ReadOnlyViolation):
                engine.run("write-test", AnalysisRequest())

    def test_analysis_cli_list_and_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = create_database(Path(directory))
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    main(["analysis", "list", "--db", str(database)]),
                    0,
                )
            self.assertIn("setpoint_changes", output.getvalue())

            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    main(
                        [
                            "analysis",
                            "run",
                            "setpoint_changes",
                            "--db",
                            str(database),
                            "--date",
                            "2026-08-18",
                            "--limit",
                            "10",
                        ]
                    ),
                    0,
                )
            self.assertIn("TICA-117109", output.getvalue())
            self.assertIn("returned=1", output.getvalue())


if __name__ == "__main__":
    unittest.main()
