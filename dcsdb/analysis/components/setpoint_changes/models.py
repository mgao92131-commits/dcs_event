"""Results returned by the setpoint changes component."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SetpointChange:
    event_id: int
    event_time_ms: int
    event_time_text: str

    module: str
    module_description: str
    parameter: str

    old_value: float | None
    new_value: float | None

    description1: str
    description2: str
