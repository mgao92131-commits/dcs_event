"""Read-only analysis platform built on top of the raw event database."""

from .base import AnalysisComponent, AnalysisContext, AnalysisRequest
from .database import ReadOnlyDatabase, ReadOnlyViolation
from .engine import AnalysisEngine
from .registry import AnalysisRegistry, create_default_registry

__all__ = [
    "AnalysisComponent",
    "AnalysisContext",
    "AnalysisEngine",
    "AnalysisRegistry",
    "AnalysisRequest",
    "ReadOnlyDatabase",
    "ReadOnlyViolation",
    "create_default_registry",
]
