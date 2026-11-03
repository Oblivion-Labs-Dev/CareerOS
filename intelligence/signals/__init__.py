"""Intelligence Layer — JobPilot features integrated into CareerOS."""

from intelligence.signals import auto_apply, night_shift, signals, tasks
from jobs.discovery import store as jobs

__all__ = ["jobs", "night_shift", "signals", "tasks", "auto_apply"]
