"""Backward-compatible exports — see mapping_pipeline.py for implementation."""

from app.services.application_assistant.mapping_pipeline import (
    default_field_mapping_settings,
    resolve_field_mapping_settings,
)
from app.services.application_assistant.mapping_pipeline import (
    run_mapping_pipeline as enrich_fields_with_agent,
)

__all__ = [
    "default_field_mapping_settings",
    "resolve_field_mapping_settings",
    "enrich_fields_with_agent",
]
