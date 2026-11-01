import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from dotenv import load_dotenv

# Key-gated job-discovery adapters (SerpApi, Google CSE) read os.environ at call
# time, and uvicorn is started without --env-file. pydantic's env_file only
# feeds this settings model, so export the same file into the process
# environment as well. Real env vars take precedence (override=False).
_API_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=_API_ROOT / ".env", override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    career_os_database_url: str = "sqlite:///./data/career_os.db"
    career_os_dev_mode: bool = True
    career_os_api_key: str = ""
    # Bearer token for POST /api/jobs/import/batch (external job ingestion). Empty
    # disables the endpoint. Set via CAREEROS_IMPORT_API_TOKEN, never in code.
    careeros_import_api_token: str = ""
    career_os_cors_origins: str = "http://localhost:3000,chrome-extension://*"
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    apify_token: str = ""
    career_os_api_public_url: str = "http://localhost:8000"
    career_os_chrome_web_store_url: str = ""
    career_os_edge_addons_url: str = ""
    career_os_firefox_addons_url: str = ""
    gmail_user: str = ""
    gmail_app_password: str = ""

    # Application Assistant
    application_assistant_enabled: bool = True
    gemini_api_key: str = ""


    # Lightweight single-user login gate (not multi-tenant auth — see docs/auth.md)
    career_os_admin_username: str = "admin"
    career_os_admin_password: str = ""
    career_os_session_secret: str = ""

    # Multi-tenant Auth & Cloud DB configuration (Option A: Supabase / PostgreSQL)
    careeros_multitenant_mode: bool = False
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""


settings = Settings()


def is_production_env() -> bool:
    """CAREEROS_ENV=production (or prod): a hosted instance, which fails closed
    where a local checkout stays permissive."""
    return os.environ.get("CAREEROS_ENV", "").strip().lower() in ("production", "prod")
