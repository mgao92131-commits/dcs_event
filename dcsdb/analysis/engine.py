"""Analysis component dispatch."""

from __future__ import annotations

from typing import Any

from .base import AnalysisContext, AnalysisRequest
from .database import ReadOnlyDatabase
from .registry import AnalysisRegistry


class AnalysisEngine:
    def __init__(self, database: ReadOnlyDatabase, registry: AnalysisRegistry) -> None:
        self.database = database
        self.registry = registry

    def run(self, component_id: str, request: AnalysisRequest) -> Any:
        component = self.registry.get(component_id)
        context = AnalysisContext(db=self.database)
        return component.run(context, request)
