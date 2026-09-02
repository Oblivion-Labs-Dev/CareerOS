"""Generic re-export module for application assistant agent backward compatibility."""

import app.services.application_assistant.agent as _agent
from app.services.application_assistant.agent import *  # noqa: F401, F403

# Re-export private helpers for backwards compatibility
_rule_based_prep_failure_summary = getattr(_agent, "_rule_based_prep_failure_summary", None)
_get_agent_runs = getattr(_agent, "_get_agent_runs", None)
_save_agent_run = getattr(_agent, "_save_agent_run", None)
_started_age_sec = getattr(_agent, "_started_age_sec", None)
_log_agent = getattr(_agent, "_log_agent", None)
_clear_stale_browser_runs = getattr(_agent, "_clear_stale_browser_runs", None)
_review_draft_status = getattr(_agent, "_review_draft_status", None)
_build_diagnostics_bundle = getattr(_agent, "_build_diagnostics_bundle", None)
_autonomous_prepare_app = getattr(_agent, "_autonomous_prepare_app", None)
_open_review_background = getattr(_agent, "_open_review_background", None)
_run_open_review_prepare = getattr(_agent, "_run_open_review_prepare", None)

detect_provider = getattr(_agent, "detect_provider", None)
task_status = getattr(_agent, "task_status", None)
is_app_locked = getattr(_agent, "is_app_locked", None)
get_agent_run = getattr(_agent, "get_agent_run", None)
get_active_browser_run_for_app = getattr(_agent, "get_active_browser_run_for_app", None)
