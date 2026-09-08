"""Application configuration via environment variables."""

import json
from functools import lru_cache

from pydantic import field_validator
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

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return json.loads(value)
        return value

    odds_api_key: str = ""
    odds_api_base_url: str = "https://api.the-odds-api.com/v4"

    football_data_api_key: str = ""

    supabase_url: str = ""
    supabase_service_key: str = ""

    cache_ttl_seconds: int = 120
    scrape_timeout_seconds: float = 15.0
    scrape_rate_limit_per_minute: int = 30
    use_live_scrapers: bool = False
    match_build_concurrency: int = 8
    matches_days_ahead: int = 7

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

    # --- API-Football per-90 stats (Phase 4 / Step 4) ---
    api_football_key: str = ""
    api_football_season: str = "2025"
    stats_cache_ttl_days: int = 7
    api_football_daily_limit: int = 95

    # --- Bet-memory embedding background job (Phase 1) ---
    bet_memory_embed_interval_minutes: int = 15
    bet_memory_batch_size: int = 50

    # --- Prediction settlement (Step 3) ---
    settlement_enabled: bool = True
    settlement_cron_hour: int = 3
    settlement_cron_minute: int = 0
    settlement_lookback_days: int = 14
    settlement_rollup_days: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    """Clear cached settings after .env changes (dev reload)."""
    get_settings.cache_clear()
    fresh = get_settings()
    import app.core.config as config_module

    config_module.settings = fresh
    return fresh


settings = get_settings()
