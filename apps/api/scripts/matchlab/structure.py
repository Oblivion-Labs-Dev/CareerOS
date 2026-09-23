"""Deterministic JD and resume parsing into role shape.

The implementation moved to ``app.services.application_assistant.role_shape_match``
so the queue and this benchmark run the same code (#50). Re-exported here so
the bench scripts keep their imports.
"""

from app.services.application_assistant.role_shape_match import (  # noqa: F401
    DEFAULT_SENIORITY,
    DEFAULT_TIERS,
    FAMILY_AFFINITY,
    ROLE_FAMILIES,
    SENIORITY_LEVELS,
    Evidence,
    JobShape,
    ResumeShape,
    build_resume_shape,
    detect_role_family,
    detect_seniority,
    extract_requirements,
    family_affinity,
    parse_job,
)
