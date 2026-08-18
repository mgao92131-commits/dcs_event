"""Minimal contracts shared by analysis components."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Protocol

from .database import ReadOnlyDatabase


@dataclass(frozen=True, slots=True)
class AnalysisRequest:
    """A time range plus component-specific optional values."""

    start_time_ms: int | None = None
    end_time_ms: int | None = None
    options: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (
            self.start_time_ms is not None
            and self.end_time_ms is not None
            and self.start_time_ms >= self.end_time_ms
        ):
            raise ValueError("start_time_ms must be earlier than end_time_ms")


@dataclass(frozen=True, slots=True)
class AnalysisContext:
    db: ReadOnlyDatabase


class AnalysisComponent(Protocol):
    id: str
    name: str

    def run(
        self,
        context: AnalysisContext,
        request: AnalysisRequest,
    ) -> Iterable[Any]:
        """Run the component and return an iterable of component results."""
