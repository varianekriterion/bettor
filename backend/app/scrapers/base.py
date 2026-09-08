"""Base scraper interface with rate limiting and graceful failure handling."""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.models.schemas import Outcome, SourcePrediction
from app.scrapers.errors import ScraperBlockedError, ScraperError

logger = logging.getLogger(__name__)


def strict_no_demo_mode() -> bool:
    """When True, scrapers must never synthesize fallback predictions."""
    return not settings.use_demo_data


_CAPTCHA_MARKERS = (
    "captcha",
    "cf-challenge",
    "cf-browser-verification",
    "attention required",
    "access denied",
    "verify you are human",
    "g-recaptcha",
    "hcaptcha",
    "bot detection",
)


class RateLimiter:
    """Simple sliding-window rate limiter shared across scrapers."""

    def __init__(self, max_per_minute: int) -> None:
        self.max_per_minute = max_per_minute
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            self._timestamps = [t for t in self._timestamps if now - t < 60.0]
            if len(self._timestamps) >= self.max_per_minute:
                sleep_for = 60.0 - (now - self._timestamps[0])
                await asyncio.sleep(max(sleep_for, 0.05))
            self._timestamps.append(time.monotonic())


_rate_limiter = RateLimiter(settings.scrape_rate_limit_per_minute)


class BasePredictionScraper(ABC):
    source_name: str
    base_url: str

    def __init__(self) -> None:
        self.timeout = settings.scrape_timeout_seconds

    @abstractmethod
    async def scrape_match(self, home_team: str, away_team: str, league: str) -> SourcePrediction | None:
        """Scrape a single match prediction. Return None on failure."""

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
        reraise=True,
    )
    async def fetch_html(self, url: str, headers: dict[str, str] | None = None) -> str:
        await _rate_limiter.acquire()
        default_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
        if headers:
            default_headers.update(headers)

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.get(url, headers=default_headers)
            body_lower = response.text[:4000].lower() if response.text else ""

            if response.status_code in {401, 403, 429, 503}:
                raise ScraperBlockedError(
                    self.source_name,
                    status_code=response.status_code,
                    detail=url,
                )
            if any(marker in body_lower for marker in _CAPTCHA_MARKERS):
                raise ScraperBlockedError(
                    self.source_name,
                    status_code=response.status_code,
                    detail="CAPTCHA / bot challenge detected",
                )

            response.raise_for_status()
            return response.text

    def parse_soup(self, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "lxml")

    @staticmethod
    def normalize_probs(home: float, draw: float, away: float) -> tuple[float, float, float]:
        total = home + draw + away
        if total <= 0:
            return (1 / 3, 1 / 3, 1 / 3)
        # Accept percentage inputs (e.g. 45) as well as fractions
        if total > 1.5:
            home, draw, away = home / 100.0, draw / 100.0, away / 100.0
            total = home + draw + away
        return home / total, draw / total, away / total

    @staticmethod
    def pick_from_probs(home: float, draw: float, away: float) -> Outcome:
        mapping: list[tuple[Outcome, float]] = [
            ("home", home),
            ("draw", draw),
            ("away", away),
        ]
        return max(mapping, key=lambda x: x[1])[0]

    def build_prediction(
        self,
        home: float,
        draw: float,
        away: float,
        confidence: float | None = None,
    ) -> SourcePrediction:
        h, d, a = self.normalize_probs(home, draw, away)
        pick = self.pick_from_probs(h, d, a)
        return SourcePrediction(
            source=self.source_name,  # type: ignore[arg-type]
            home_prob=h,
            draw_prob=d,
            away_prob=a,
            pick=pick,
            confidence=confidence,
            scraped_at=datetime.now(timezone.utc),
        )

    async def safe_scrape(
        self,
        home_team: str,
        away_team: str,
        league: str,
    ) -> SourcePrediction | None:
        """Never raise — log and skip this source so consensus can continue.

        In strict no-demo mode (`USE_DEMO_DATA=false`), blocked/failed scrapes
        always return None — never seeded demo predictions.
        """
        try:
            return await self.scrape_match(home_team, away_team, league)
        except ScraperBlockedError as exc:
            logger.warning(
                "Skipping %s for %s vs %s (%s): %s%s",
                self.source_name,
                home_team,
                away_team,
                league,
                exc,
                " (strict no-demo — no synthetic fallback)" if strict_no_demo_mode() else "",
            )
            return None
        except ScraperError as exc:
            logger.warning(
                "Skipping %s for %s vs %s (%s): %s",
                self.source_name,
                home_team,
                away_team,
                league,
                exc,
            )
            return None
        except Exception as exc:  # noqa: BLE001 — scrapers must never crash the pipeline
            logger.warning(
                "%s scrape failed for %s vs %s (%s): %s",
                self.source_name,
                home_team,
                away_team,
                league,
                exc,
            )
            return None


def team_slug(name: str) -> str:
    return (
        name.lower()
        .replace(" ", "-")
        .replace(".", "")
        .replace("'", "")
        .replace("fc-", "")
        .replace("-fc", "")
    )
