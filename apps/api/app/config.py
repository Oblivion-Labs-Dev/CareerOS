from pydantic_settings import BaseSettings, SettingsConfigDict


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

    career_os_repair_enabled: bool = False
    career_os_repair_orchestrator_url: str = "http://127.0.0.1:8090"
    career_os_repair_demo_enabled: bool = False
    career_os_repair_agent_adapter: str = "mock"

    # Where the health probes look for Ollama. The inference calls themselves
    # already resolve their own base URL from OLLAMA_BASE_URL /
    # application_assistant_llm_base_url, but the liveness checks in main.py,
    # routers/diagnostic.py and services/observability.py had 127.0.0.1 written
    # into them. Inside a container that is the container itself, so Ollama
    # always read as down even when the host was serving it happily. Same
    # default as before, so a local run is unaffected.
    careeros_ollama_health_url: str = "http://127.0.0.1:11434"

    # Application Assistant
    application_assistant_enabled: bool = True
    application_assistant_llm_base_url: str = "http://localhost:11434/v1"
    application_assistant_llm_model: str = "mistral-small3.2:24b"
    application_assistant_llm_api_key: str = ""
    gemini_api_key: str = ""


    # Lightweight single-user login gate (not multi-tenant auth — see docs/auth.md)
    career_os_admin_username: str = "admin"
    career_os_admin_password: str = ""
    career_os_session_secret: str = ""


settings = Settings()
