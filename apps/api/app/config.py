from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    career_os_database_url: str = "sqlite:///./data/career_os.db"
    career_os_dev_mode: bool = True
    career_os_api_key: str = ""
    career_os_cors_origins: str = "http://localhost:3000,chrome-extension://*"
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    career_os_api_public_url: str = "http://localhost:8000"
    career_os_chrome_web_store_url: str = ""
    career_os_edge_addons_url: str = ""
    career_os_firefox_addons_url: str = ""


settings = Settings()
