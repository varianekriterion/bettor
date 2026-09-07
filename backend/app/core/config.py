"""Application configuration via environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    odds_api_key: str = ""
    odds_api_base_url: str = "https://api.the-odds-api.com/v4"

    supabase_url: str = ""
    supabase_service_key: str = ""

    cache_ttl_seconds: int = 120
    scrape_timeout_seconds: float = 15.0
    scrape_rate_limit_per_minute: int = 30

    default_kelly_fraction: float = 0.25
    use_demo_data: bool = True

    # Background sync (APScheduler)
    scheduler_enabled: bool = True
    sync_interval_minutes: int = 30
    sync_on_startup: bool = False
    admin_api_token: str = ""

    target_leagues: list[str] = [
        "soccer_uefa_champs_league",
        "soccer_epl",
        "soccer_spain_la_liga",
        "soccer_germany_bundesliga",
        "soccer_italy_serie_a",
        "soccer_uefa_europa_league",
    ]

    # --- AI / RAG (Phase 1 & 3) ---
    openai_api_key: str = ""
    openai_embedding_model: str = "text-embedding-3-small"
    openai_embedding_dims: int = 1536
    openai_chat_model: str = "gpt-4o-mini"

    # --- Understat xG/xGA (Phase 2) ---
    understat_season: str = "2025"

    # --- Bet-memory embedding background job (Phase 1) ---
    bet_memory_embed_interval_minutes: int = 15
    bet_memory_batch_size: int = 50


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
