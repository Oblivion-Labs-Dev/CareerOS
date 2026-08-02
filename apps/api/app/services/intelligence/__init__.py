"""Intelligence Layer — JobPilot features integrated into CareerOS."""

from app.services.intelligence import auto_apply, night_shift, signals, tasks
from app.services.job_discover import store as jobs

__all__ = ["jobs", "night_shift", "signals", "tasks", "auto_apply"]
