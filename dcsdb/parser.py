"""Parser for the tab-separated DCS EVENTS.txt export."""

from __future__ import annotations

import codecs
import csv
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import EventRecord


FIELD_MAPPING = {
    "日期/时间*": "event_time",
    "事件类型": "event_type",
    "类别": "category",
    "厂区": "area",
    "节点": "node",
    "单元": "unit_name",
    "模块": "module",
    "模块描述": "module_description",
    "参数": "parameter",
    "状态": "status",
    "级别": "severity",
    "描述1": "description1",
    "描述2": "description2",
}

REQUIRED_HEADERS = tuple(FIELD_MAPPING)
try:
    DEFAULT_TIMEZONE: tzinfo = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:
    # Windows installations may not ship the IANA tzdata package. Mainland
    # China has used a fixed UTC+08:00 offset since the DCS timestamps here
    # are relevant, so this fallback is equivalent for this storage layer.
    DEFAULT_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")


class ParserError(Exception):
    """Base class for fatal parser errors."""


class EncodingDetectionError(ParserError):
    pass


class HeaderValidationError(ParserError):
    pass


@dataclass(frozen=True, slots=True)
class ParseIssue:
    line_no: int
    message: str
    raw: str


@dataclass(frozen=True, slots=True)
class ParseResult:
    line_no: int
    record: EventRecord | None = None
    issue: ParseIssue | None = None


_EVENT_TIME_RE = re.compile(
    r"^(?P<date>\d{4}/\d{1,2}/\d{1,2}) "
    r"(?:"
    r"(?P<time>\d{1,2}:\d{2}:\d{2})(?:\.(?P<fraction>\d{1,6}))?"
    r"|\(\.(?P<midnight_fraction>\d{1,6})\)"
    r")$"
)


def normalize_text(value: str | None) -> str:
    """Remove physical line breaks while preserving all other characters."""

    if value is None:
        return ""
    return value.replace("\r", "").replace("\n", "")


def parse_event_time(
    value: str,
    *,
    time_zone: tzinfo = DEFAULT_TIMEZONE,
) -> int:
    """Convert a DCS local timestamp to Unix milliseconds.

    DCS exports contain local plant time without an offset. V1 treats that
    local time as Asia/Shanghai by default, while allowing tests or callers to
    supply another explicit timezone.
    """

    match = _EVENT_TIME_RE.fullmatch(value)
    if not match:
        raise ValueError(f"Invalid datetime: {value!r}")

    # DCS emits a compact zero-point form at midnight, for example
    # ``2026/8/9 (.813)``. It means 00:00:00.813; preserve the original text
    # in event_time_text while converting this value for event_time_ms.
    clock_time = match.group("time") or "00:00:00"
    fraction = match.group("fraction") or match.group("midnight_fraction") or "0"
    fraction = (fraction + "000000")[:6]
    try:
        parsed = datetime.strptime(
            f"{match.group('date')} {clock_time}.{fraction}",
            "%Y/%m/%d %H:%M:%S.%f",
        )
    except ValueError as exc:
        raise ValueError(f"Invalid datetime: {value!r}") from exc

    aware = parsed.replace(tzinfo=time_zone).astimezone(timezone.utc)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = aware - epoch
    return (
        delta.days * 86_400_000
        + delta.seconds * 1_000
        + delta.microseconds // 1_000
    )


def format_event_time_ms(value: int, *, time_zone: tzinfo = DEFAULT_TIMEZONE) -> str:
    """Format Unix milliseconds for CLI output in the plant timezone."""

    seconds, milliseconds = divmod(int(value), 1000)
    moment = datetime.fromtimestamp(seconds, tz=timezone.utc).astimezone(time_zone)
    return moment.strftime("%Y-%m-%d %H:%M:%S") + f".{milliseconds:03d}"


def detect_encoding(path: str | Path) -> str:
    """Validate the complete file against the supported encodings."""

    path = Path(path)
    for encoding in ("utf-8-sig", "gb18030"):
        decoder = codecs.getincrementaldecoder(encoding)(errors="strict")
        try:
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    decoder.decode(chunk)
                decoder.decode(b"", final=True)
            return encoding
        except UnicodeDecodeError:
            continue
    raise EncodingDetectionError(
        f"Unable to decode {path} as UTF-8 BOM/UTF-8 or GB18030"
    )


class DCSLogParser:
    """Stream valid records and row-level issues from one export file."""

    def __init__(self, *, time_zone: tzinfo = DEFAULT_TIMEZONE) -> None:
        self.time_zone = time_zone

    def parse(self, path: str | Path):
        path = Path(path)
        encoding = detect_encoding(path)
        with path.open("r", encoding=encoding, newline="") as handle:
            reader = csv.reader(handle, delimiter="\t", strict=True)
            try:
                header = next(reader)
            except StopIteration as exc:
                raise HeaderValidationError("EVENTS.txt is empty") from exc
            except csv.Error as exc:
                raise HeaderValidationError(f"Unable to read header: {exc}") from exc

            indexes = self._validate_header(header)
            expected_columns = len(header)

            while True:
                try:
                    row = next(reader)
                except StopIteration:
                    break
                except csv.Error as exc:
                    line_no = reader.line_num
                    yield ParseResult(
                        line_no=line_no,
                        issue=ParseIssue(
                            line_no=line_no,
                            message=f"CSV parse error: {exc}",
                            raw="",
                        ),
                    )
                    continue

                line_no = reader.line_num
                raw = "\t".join(normalize_text(value) for value in row)
                if len(row) != expected_columns:
                    yield ParseResult(
                        line_no=line_no,
                        issue=ParseIssue(
                            line_no=line_no,
                            message=(
                                f"Invalid column count: expected {expected_columns}, "
                                f"got {len(row)}"
                            ),
                            raw=raw,
                        ),
                    )
                    continue

                try:
                    record = self._parse_row(row, indexes)
                except ValueError as exc:
                    yield ParseResult(
                        line_no=line_no,
                        issue=ParseIssue(
                            line_no=line_no,
                            message=str(exc),
                            raw=raw,
                        ),
                    )
                    continue
                yield ParseResult(line_no=line_no, record=record)

    @staticmethod
    def _validate_header(header: list[str]) -> dict[str, int | None]:
        normalized = [normalize_text(cell).strip() for cell in header]
        indexes: dict[str, int | None] = {}
        missing: list[str] = []
        duplicates: list[str] = []

        for display_name, field_name in FIELD_MAPPING.items():
            matches = [
                index for index, cell in enumerate(normalized) if cell == display_name
            ]
            if not matches:
                missing.append(display_name)
            elif len(matches) > 1:
                duplicates.append(display_name)
            else:
                indexes[field_name] = matches[0]

        if missing or duplicates:
            problems: list[str] = []
            if missing:
                problems.append("missing fields: " + ", ".join(missing))
            if duplicates:
                problems.append("duplicate fields: " + ", ".join(duplicates))
            raise HeaderValidationError("Invalid header; " + "; ".join(problems))

        event_time_index = indexes["event_time"]
        assert event_time_index is not None
        # The current export has an empty header cell before 日期/时间* and
        # stores the file-local source record number in that column.
        indexes["source_record_no"] = event_time_index - 1 if event_time_index > 0 else None
        return indexes

    def _parse_row(
        self,
        row: list[str],
        indexes: dict[str, int | None],
    ) -> EventRecord:
        def value(field_name: str) -> str:
            index = indexes[field_name]
            assert index is not None
            # Preserve the parsed DCS field exactly. Newline removal belongs
            # to hash normalization, not to the stored raw event.
            return row[index]

        event_time_text = value("event_time")
        if not event_time_text:
            raise ValueError("Invalid datetime: empty value")
        event_time_ms = parse_event_time(event_time_text, time_zone=self.time_zone)

        source_index = indexes["source_record_no"]
        source_record_no: int | None = None
        if source_index is not None:
            source_text = row[source_index]
            if source_text:
                try:
                    source_record_no = int(source_text)
                except ValueError as exc:
                    raise ValueError(
                        f"Invalid source record number: {source_text!r}"
                    ) from exc

        return EventRecord(
            event_time_ms=event_time_ms,
            event_time_text=event_time_text,
            event_type=value("event_type"),
            category=value("category"),
            area=value("area"),
            node=value("node"),
            unit_name=value("unit_name"),
            module=value("module"),
            module_description=value("module_description"),
            parameter=value("parameter"),
            status=value("status"),
            severity=value("severity"),
            description1=value("description1"),
            description2=value("description2"),
            source_record_no=source_record_no,
        )
