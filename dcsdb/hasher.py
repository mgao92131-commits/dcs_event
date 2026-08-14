"""Stable event-level SHA-256 hashing."""

from __future__ import annotations

import hashlib

from .models import EventRecord


HASH_SEPARATOR = "\x1f"
HASH_FIELDS = (
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
)


def normalize_hash_field(value: str | None) -> str:
    """Apply only the V1 hash normalization rules."""

    if value is None:
        return ""
    return value.replace("\r", "").replace("\n", "")


def compute_event_hash(record: EventRecord) -> str:
    """Return the SHA-256 hash for the raw event fields.

    The source record number is deliberately excluded because it is local to
    an individual EVENTS.txt export.
    """

    payload = HASH_SEPARATOR.join(
        normalize_hash_field(getattr(record, field)) for field in HASH_FIELDS
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
