"""BetConsensus Engine — FastAPI application entrypoint."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import admin, calculator, chat, journal, matches, performance, predictions
from app.core.cache import init_cache
from app.core.config import get_settings, reload_settings, settings
from app.core.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s:%(message)s",
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_cache()
    # Pick up latest .env (e.g. OPENAI_API_KEY) on uvicorn reload.
    import app.core.config as config_module

    fresh = reload_settings()
    config_module.settings = fresh

    log = logging.getLogger(__name__)
    if fresh.use_demo_data:
        log.info("Running in demo mode (USE_DEMO_DATA=true)")
    elif not fresh.odds_api_key:
        log.warning(
            "USE_DEMO_DATA=false but ODDS_API_KEY is empty — no live fixtures/odds until you "
            "add your key from https://the-odds-api.com to backend/.env"
        )
    else:
        log.info("Live data mode — fetching odds from The Odds API")
    if fresh.openai_api_key:
        log.info("OpenAI configured — slip OCR + chat enabled (%s)", fresh.openai_chat_model)
    else:
        log.warning("OPENAI_API_KEY is empty — slip OCR and chat are disabled")
    if not fresh.use_live_scrapers:
        log.info(
            "Tipster scrapers disabled (USE_LIVE_SCRAPERS=false) — consensus uses odds + xG only"
        )
    elif fresh.use_live_scrapers:
        log.info(
            "Tipster scrapers run on scheduled sync only — /matches API uses odds + xG for speed"
        )
    if fresh.matches_days_ahead > 0:
        log.info("Matches feed limited to next %d days (UTC)", fresh.matches_days_ahead)
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    title="BetConsensus Engine",
    description="Bayesian consensus probabilities, +EV detection, and Kelly staking for European football.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(matches.router, prefix="/api/v1", tags=["matches"])
app.include_router(predictions.router, prefix="/api/v1", tags=["predictions"])
app.include_router(calculator.router, prefix="/api/v1", tags=["calculator"])
app.include_router(performance.router, prefix="/api/v1", tags=["performance"])
app.include_router(chat.router, prefix="/api/v1", tags=["chat"])
app.include_router(journal.router, prefix="/api/v1", tags=["journal"])
app.include_router(admin.router, prefix="/api/v1")


@app.get("/health")
async def health() -> dict[str, str]:
    if settings.use_demo_data:
        data_mode = "demo"
    elif settings.odds_api_key:
        data_mode = "live"
    else:
        data_mode = "live_configured_no_odds_key"
    return {"status": "ok", "service": "betconsensus-engine", "data_mode": data_mode}
