"""Prediction site scrapers with deterministic demo fallbacks."""

from __future__ import annotations

import hashlib
import logging
import math

from app.core.config import settings
from app.models.schemas import SourcePrediction
from app.scrapers.base import BasePredictionScraper, team_slug
from app.scrapers.errors import ScraperBlockedError, ScraperParseError

logger = logging.getLogger(__name__)


def _seeded_probs(source: str, home: str, away: str, league: str) -> tuple[float, float, float]:
    """
    Deterministic pseudo-predictions for demo / fallback mode.
    Stable across restarts so UI and tests remain consistent.
    """
    digest = hashlib.sha256(f"{source}|{league}|{home}|{away}".encode()).hexdigest()
    h_bias = int(digest[0:2], 16) / 255.0
    d_bias = int(digest[2:4], 16) / 255.0
    a_bias = int(digest[4:6], 16) / 255.0

    logits = [
        0.55 + 0.9 * (h_bias - 0.5),
        0.25 + 0.5 * (d_bias - 0.5),
        0.45 + 0.9 * (a_bias - 0.5),
    ]
    style = {
        "forebet": (0.05, -0.02, -0.03),
        "predictz": (0.0, 0.04, -0.04),
        "windrawwin": (-0.03, 0.06, -0.03),
        "betimate": (0.02, 0.0, -0.02),
        "footballwhispers": (-0.01, 0.02, -0.01),
    }.get(source, (0.0, 0.0, 0.0))
    logits = [l + s for l, s in zip(logits, style)]
    exps = [math.exp(x) for x in logits]
    total = sum(exps)
    return exps[0] / total, exps[1] / total, exps[2] / total


class DemoFallbackMixin:
    source_name: str

    def demo_prediction(self, home_team: str, away_team: str, league: str) -> SourcePrediction:
        h, d, a = _seeded_probs(self.source_name, home_team, away_team, league)
        return self.build_prediction(h, d, a, confidence=abs(h - a))  # type: ignore[attr-defined]


def _extract_three_nums(text: str) -> list[float] | None:
    nums = [
        float(x.replace("%", ""))
        for x in text.split()
        if x.replace("%", "").replace(".", "", 1).isdigit()
    ]
    return nums[:3] if len(nums) >= 3 else None


class ForebetScraper(BasePredictionScraper, DemoFallbackMixin):
    source_name = "forebet"
    base_url = "https://www.forebet.com"

    async def scrape_match(self, home_team: str, away_team: str, league: str) -> SourcePrediction | None:
        if settings.use_demo_data:
            return self.demo_prediction(home_team, away_team, league)

        slug = f"{team_slug(home_team)}-{team_slug(away_team)}"
        url = f"{self.base_url}/en/football/{slug}"
        try:
            html = await self.fetch_html(url)
            soup = self.parse_soup(html)
            cells = soup.select(".rcnt .fprc span, .predict_short span")
            nums = [
                float(c.get_text(strip=True).replace("%", ""))
                for c in cells
                if c.get_text(strip=True).replace("%", "").replace(".", "", 1).isdigit()
            ]
            if len(nums) >= 3:
                return self.build_prediction(nums[0], nums[1], nums[2])
            raise ScraperParseError("Forebet DOM missing prediction cells")
        except ScraperBlockedError:
            raise
        except ScraperParseError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.info("Forebet live scrape failed — skipping source: %s", exc)
            return None


class PredictZScraper(BasePredictionScraper, DemoFallbackMixin):
    source_name = "predictz"
    base_url = "https://www.predictz.com"

    async def scrape_match(self, home_team: str, away_team: str, league: str) -> SourcePrediction | None:
        if settings.use_demo_data:
            return self.demo_prediction(home_team, away_team, league)
        try:
            html = await self.fetch_html(f"{self.base_url}/predictions/")
            soup = self.parse_soup(html)
            for row in soup.select("tr, .ptable tr"):
                text = row.get_text(" ", strip=True).lower()
                if home_team.lower()[:6] in text and away_team.lower()[:6] in text:
                    nums = _extract_three_nums(row.get_text(" "))
                    if nums:
                        return self.build_prediction(nums[0], nums[1], nums[2])
            raise ScraperParseError("PredictZ row not found / DOM changed")
        except ScraperBlockedError:
            raise
        except ScraperParseError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.info("PredictZ live scrape failed — skipping source: %s", exc)
            return None


class WinDrawWinScraper(BasePredictionScraper, DemoFallbackMixin):
    source_name = "windrawwin"
    base_url = "https://www.windrawwin.com"

    async def scrape_match(self, home_team: str, away_team: str, league: str) -> SourcePrediction | None:
        if settings.use_demo_data:
            return self.demo_prediction(home_team, away_team, league)
        try:
            html = await self.fetch_html(f"{self.base_url}/predictions")
            soup = self.parse_soup(html)
            for row in soup.select("table tr, .fixture"):
                text = row.get_text(" ", strip=True).lower()
                if home_team.lower()[:5] in text and away_team.lower()[:5] in text:
                    nums = _extract_three_nums(row.get_text(" "))
                    if nums:
                        return self.build_prediction(nums[0], nums[1], nums[2])
            raise ScraperParseError("WinDrawWin row not found / DOM changed")
        except ScraperBlockedError:
            raise
        except ScraperParseError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.info("WinDrawWin live scrape failed — skipping source: %s", exc)
            return None


class BetimateScraper(BasePredictionScraper, DemoFallbackMixin):
    source_name = "betimate"
    base_url = "https://betimate.com"

    async def scrape_match(self, home_team: str, away_team: str, league: str) -> SourcePrediction | None:
        if settings.use_demo_data:
            return self.demo_prediction(home_team, away_team, league)
        try:
            html = await self.fetch_html(f"{self.base_url}/football-predictions")
            soup = self.parse_soup(html)
            for card in soup.select(".prediction, .match-item, article"):
                text = card.get_text(" ", strip=True).lower()
                if home_team.lower()[:5] in text and away_team.lower()[:5] in text:
                    nums = _extract_three_nums(card.get_text(" "))
                    if nums:
                        return self.build_prediction(nums[0], nums[1], nums[2])
            raise ScraperParseError("Betimate card not found / DOM changed")
        except ScraperBlockedError:
            raise
        except ScraperParseError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.info("Betimate live scrape failed — skipping source: %s", exc)
            return None


class FootballWhispersScraper(BasePredictionScraper, DemoFallbackMixin):
    source_name = "footballwhispers"
    base_url = "https://www.footballwhispers.com"

    async def scrape_match(self, home_team: str, away_team: str, league: str) -> SourcePrediction | None:
        if settings.use_demo_data:
            return self.demo_prediction(home_team, away_team, league)
        try:
            html = await self.fetch_html(f"{self.base_url}/predictions")
            soup = self.parse_soup(html)
            for row in soup.select(".prediction-row, tr, .fixture-row"):
                text = row.get_text(" ", strip=True).lower()
                if home_team.lower()[:5] in text and away_team.lower()[:5] in text:
                    nums = _extract_three_nums(row.get_text(" "))
                    if nums:
                        return self.build_prediction(nums[0], nums[1], nums[2])
            raise ScraperParseError("FootballWhispers row not found / DOM changed")
        except ScraperBlockedError:
            raise
        except ScraperParseError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.info("FootballWhispers live scrape failed — skipping source: %s", exc)
            return None


SCRAPERS: list[BasePredictionScraper] = [
    ForebetScraper(),
    PredictZScraper(),
    WinDrawWinScraper(),
    BetimateScraper(),
    FootballWhispersScraper(),
]


async def scrape_all_sources(
    home_team: str,
    away_team: str,
    league: str,
) -> list[SourcePrediction]:
    """
    Run all scrapers concurrently.
    Failed / blocked sources are skipped so Bayesian consensus uses remaining active sources.
    """
    import asyncio

    results = await asyncio.gather(
        *[s.safe_scrape(home_team, away_team, league) for s in SCRAPERS],
        return_exceptions=False,
    )
    active = [r for r in results if r is not None]
    skipped = len(results) - len(active)
    if skipped:
        logger.info(
            "Scrapers for %s vs %s: %d active, %d skipped",
            home_team,
            away_team,
            len(active),
            skipped,
        )
    return active
