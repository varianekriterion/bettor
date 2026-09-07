"""BetConsensus Engine — FastAPI application entrypoint."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import admin, calculator, chat, matches, performance, predictions
from app.core.cache import init_cache
from app.core.config import settings
from app.core.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s:%(message)s",
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_cache()
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
app.include_router(admin.router, prefix="/api/v1")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "betconsensus-engine"}
