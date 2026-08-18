"""Find DCS controller/setpoint changes from raw events."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from ...base import AnalysisComponent, AnalysisContext, AnalysisRequest
from .models import SetpointChange
from .parser import parse_numeric_values


COMPONENT_ID = "setpoint_changes"
COMPONENT_NAME = "Setpoint Changes"
EVENT_TYPE_CHANGE = "\u6539\u53d8"
EXCLUDED_MODULES = ("PICA-117024", "PICA-217024")


class SetpointChangesComponent:
    id = COMPONENT_ID
    name = COMPONENT_NAME

    def run(
        self,
        context: AnalysisContext,
        request: AnalysisRequest,
    ) -> Iterator[SetpointChange]:
        sql = """
        SELECT
            id,
            event_time_ms,
            event_time_text,
            module,
            module_description,
            parameter,
            status,
            description1,
            description2
        FROM events
        WHERE event_type = ?
          AND substr(upper(trim(parameter)), -3) = '.CV'
          AND module NOT IN (?, ?)
        """
        params: list[Any] = [EVENT_TYPE_CHANGE, *EXCLUDED_MODULES]
        if request.start_time_ms is not None:
            sql += " AND event_time_ms >= ?"
            params.append(request.start_time_ms)
        if request.end_time_ms is not None:
            sql += " AND event_time_ms < ?"
            params.append(request.end_time_ms)
        sql += " ORDER BY event_time_ms, id"

        for row in context.db.stream(sql, params):
            old_value, new_value = parse_numeric_values(
                row["description1"], row["description2"]
            )
            yield SetpointChange(
                event_id=int(row["id"]),
                event_time_ms=int(row["event_time_ms"]),
                event_time_text=row["event_time_text"],
                module=row["module"] or "",
                module_description=row["module_description"] or "",
                parameter=row["parameter"] or "",
                old_value=old_value,
                new_value=new_value,
                description1=row["description1"] or "",
                description2=row["description2"] or "",
            )
