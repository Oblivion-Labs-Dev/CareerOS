"""Intelligence Layer — JobPilot features integrated into CareerOS."""

from app.services.intelligence import night_shift, signals, tasks, auto_apply
from app.services.job_discover import store as jobs

__all__ = ["jobs", "night_shift", "signals", "tasks", "auto_apply"]
