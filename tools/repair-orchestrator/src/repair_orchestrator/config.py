from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]
ORCHESTRATOR_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    repair_host: str = "127.0.0.1"
    repair_port: int = 8090
    repair_database_url: str = f"sqlite:///{ORCHESTRATOR_ROOT / 'data' / 'repair.db'}"
    repair_repo_root: str = str(REPO_ROOT)
    repair_environment: str = "local"
    repair_enabled: bool = True

    # Thresholds
    min_occurrences_for_task: int = 2
    severity_threshold: str = "error"
    incident_cooldown_seconds: int = 300

    # Guardrails
    max_changed_files: int = 20
    max_diff_bytes: int = 50_000
    max_execution_seconds: int = 900
    max_retries: int = 2
    agent_concurrency: int = 1

    # Agent adapter
    agent_adapter: str = "mock"
    agent_cli_command: str = ""

    # Validation commands (comma-separated)
    validation_commands: str = (
        "pnpm typecheck,"
        "cd apps/api && python -m pytest tests/test_health.py tests/test_error_fix_tracker.py -q"
    )

    # Protected paths (comma-separated globs relative to repo root)
    protected_directories: str = (
        ".env,.env.*,apps/api/.env,apps/extension/.env,"
        ".github,apps/api/app/db/migrations,"
        "apps/extension/manifest.json,"
        "apps/api/app/services/gmail_sender.py"
    )
    protected_file_patterns: str = "**/.env*,**/secrets*,**/*credentials*"

    # Human review categories
    required_human_review_categories: str = (
        "database,authentication,authorization,billing,privacy,"
        "infrastructure,extension-permissions,resume-processing,job-application"
    )

    # PR handoff
    allow_remote_pr: bool = False


settings = Settings()
