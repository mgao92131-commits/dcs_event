"""Explicit analysis component registration."""

from __future__ import annotations

from collections.abc import Iterable

from .base import AnalysisComponent


class AnalysisRegistry:
    def __init__(self) -> None:
        self._components: dict[str, AnalysisComponent] = {}

    def register(self, component: AnalysisComponent) -> None:
        component_id = component.id.strip()
        if not component_id:
            raise ValueError("Analysis component id cannot be empty")
        if component_id in self._components:
            raise ValueError(f"Analysis component already registered: {component_id}")
        self._components[component_id] = component

    def get(self, component_id: str) -> AnalysisComponent:
        try:
            return self._components[component_id]
        except KeyError as exc:
            available = ", ".join(self._components) or "none"
            raise KeyError(
                f"Unknown analysis component {component_id!r}; available: {available}"
            ) from exc

    def list(self) -> tuple[AnalysisComponent, ...]:
        return tuple(self._components[key] for key in sorted(self._components))


def create_default_registry() -> AnalysisRegistry:
    from .components.setpoint_changes.component import SetpointChangesComponent

    registry = AnalysisRegistry()
    registry.register(SetpointChangesComponent())
    return registry
