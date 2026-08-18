"""Parse numeric values from raw DCS setpoint change descriptions."""

from __future__ import annotations

import re


OLD_VALUE_LABEL = "\u65e7\u503c"
NEW_VALUE_LABEL = "\u65b0\u503c"
_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_VALUE_PATTERN = re.compile(
    rf"(?P<label>{re.escape(OLD_VALUE_LABEL)}|{re.escape(NEW_VALUE_LABEL)})"
    rf"\s*[:=：]\s*(?P<value>{_NUMBER})"
)


def parse_numeric_values(
    description1: str | None,
    description2: str | None,
) -> tuple[float | None, float | None]:
    """Return ``(old_value, new_value)`` without changing raw descriptions."""

    values: dict[str, float] = {}
    for text in (description2 or "", description1 or ""):
        for match in _VALUE_PATTERN.finditer(text):
            values.setdefault(match.group("label"), float(match.group("value")))
    return values.get(OLD_VALUE_LABEL), values.get(NEW_VALUE_LABEL)
