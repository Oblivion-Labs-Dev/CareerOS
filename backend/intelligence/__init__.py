"""Intelligence Layer — JobPilot features integrated into CareerOS."""

from backend.intelligence import auto_apply, night_shift, signals, tasks
from backend.jobs.discovery import store as jobs

__all__ = ["jobs", "night_shift", "signals", "tasks", "auto_apply"]
