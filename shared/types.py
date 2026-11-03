"""Primitive shared types used across service boundaries.

These are intentionally thin aliases rather than classes: they document intent
at interface boundaries (what a string actually represents) without coupling
services to a shared model. Business models stay inside each service.
"""

from typing import Any, TypeAlias

# An opaque identifier for a service-owned entity (job id, application id, …).
ServiceId: TypeAlias = str

# An ISO-8601 timestamp string, as produced by ``shared.db.now_iso``.
IsoTimestamp: TypeAlias = str

# A JSON-serialisable mapping, the lingua franca of the cross-service contracts.
JsonDict: TypeAlias = dict[str, Any]
