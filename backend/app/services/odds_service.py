"""The-Odds-API client with live h2h + totals (O/U) and demo market fallback."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone

import httpx

from app.core.cache import cache_get, cache_set
from app.core.config import settings
from app.models.schemas import BookmakerOdds, LEAGUE_META, LeagueKey, MatchOdds, TotalsLine

logger = logging.getLogger(__name__)

# Prefer the classic 2.5 goals line when aggregating totals markets.
PREFERRED_TOTALS_LINE = 2.5
MARKETS = "h2h,totals"


def _demo_totals(home: str, away: str, league: str) -> TotalsLine:
    digest = hashlib.sha256(f"totals|{league}|{home}|{away}".encode()).hexdigest()
    over = 1.75 + (int(digest[0:2], 16) / 255.0) * 0.55
    under = 1.85 + (int(digest[2:4], 16) / 255.0) * 0.50
    return TotalsLine(line=PREFERRED_TOTALS_LINE, over=round(over, 2), under=round(under, 2))


def _demo_odds(home: str, away: str, league: str) -> MatchOdds:
    digest = hashlib.sha256(f"odds|{league}|{home}|{away}".encode()).hexdigest()
    h = 1.55 + (int(digest[0:2], 16) / 255.0) * 2.4
    d = 2.90 + (int(digest[2:4], 16) / 255.0) * 1.4
    a = 1.70 + (int(digest[4:6], 16) / 255.0) * 3.2
    base_totals = _demo_totals(home, away, league)
    books = [
        BookmakerOdds(
            bookmaker="Pinnacle",
            home=round(h * 1.01, 2),
            draw=round(d * 0.99, 2),
            away=round(a * 1.00, 2),
            last_update=datetime.now(timezone.utc),
            totals=TotalsLine(
                line=base_totals.line,
                over=round(base_totals.over * 1.01, 2),
                under=round(base_totals.under * 0.99, 2),
            ),
        ),
        BookmakerOdds(
            bookmaker="Bet365",
            home=round(h * 0.98, 2),
            draw=round(d * 1.02, 2),
            away=round(a * 0.97, 2),
            last_update=datetime.now(timezone.utc),
            totals=TotalsLine(
                line=base_totals.line,
                over=round(base_totals.over * 0.98, 2),
                under=round(base_totals.under * 1.02, 2),
            ),
        ),
        BookmakerOdds(
            bookmaker="Unibet",
            home=round(h * 1.00, 2),
            draw=round(d * 1.00, 2),
            away=round(a * 1.03, 2),
            last_update=datetime.now(timezone.utc),
            totals=TotalsLine(
                line=base_totals.line,
                over=round(base_totals.over * 1.00, 2),
                under=round(base_totals.under * 1.01, 2),
            ),
        ),
    ]
    overs = [b.totals.over for b in books if b.totals]
    unders = [b.totals.under for b in books if b.totals]
    return MatchOdds(
        best_home=max(b.home for b in books),
        best_draw=max(b.draw for b in books),
        best_away=max(b.away for b in books),
        bookmakers=books,
        totals_line=PREFERRED_TOTALS_LINE,
        best_over=max(overs) if overs else None,
        best_under=max(unders) if unders else None,
    )


def _parse_totals_market(market: dict | None) -> TotalsLine | None:
    """Extract Over/Under at the preferred (or closest) totals point."""
    if not market:
        return None
    by_point: dict[float, dict[str, float]] = {}
    for outcome in market.get("outcomes", []):
        name = (outcome.get("name") or "").lower()
        point = outcome.get("point")
        price = outcome.get("price")
        if point is None or price is None:
            continue
        point_f = float(point)
        bucket = by_point.setdefault(point_f, {})
        if name.startswith("over"):
            bucket["over"] = float(price)
        elif name.startswith("under"):
            bucket["under"] = float(price)

    complete = {
        pt: odds
        for pt, odds in by_point.items()
        if "over" in odds and "under" in odds
    }
    if not complete:
        return None

    if PREFERRED_TOTALS_LINE in complete:
        chosen = PREFERRED_TOTALS_LINE
    else:
        chosen = min(complete.keys(), key=lambda p: abs(p - PREFERRED_TOTALS_LINE))

    return TotalsLine(
        line=chosen,
        over=complete[chosen]["over"],
        under=complete[chosen]["under"],
    )


class OddsApiClient:
    def __init__(self) -> None:
        self.api_key = settings.odds_api_key
        self.base_url = settings.odds_api_base_url

    async def fetch_league_odds(self, league: LeagueKey) -> list[dict]:
        """Fetch live h2h (1X2) and totals (O/U) odds for an active target league."""
        cache_key = f"odds:{league}"
        cached = cache_get(cache_key)
        if cached is not None:
            return cached

        if settings.use_demo_data or not self.api_key:
            data = self._demo_fixtures(league)
            cache_set(cache_key, data)
            return data

        sport_key = LEAGUE_META[league]["odds_api_key"]
        url = f"{self.base_url}/sports/{sport_key}/odds"
        params = {
            "apiKey": self.api_key,
            "regions": "uk,eu",
            "markets": MARKETS,
            "oddsFormat": "decimal",
        }
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
                cache_set(cache_key, data)
                return data
        except Exception as exc:  # noqa: BLE001
            logger.warning("Odds API failed for %s: %s — using demo fixtures", league, exc)
            data = self._demo_fixtures(league)
            cache_set(cache_key, data)
            return data

    def parse_match_odds(self, event: dict) -> MatchOdds:
        bookmakers: list[BookmakerOdds] = []
        for bm in event.get("bookmakers", []):
            markets = {m["key"]: m for m in bm.get("markets", [])}
            h2h = markets.get("h2h")
            if not h2h:
                continue
            outcomes = {o["name"]: o["price"] for o in h2h.get("outcomes", [])}
            home_team = event["home_team"]
            away_team = event["away_team"]
            if home_team not in outcomes or away_team not in outcomes:
                continue
            draw_price = outcomes.get("Draw") or outcomes.get("Tie")
            if draw_price is None:
                continue
            totals = _parse_totals_market(markets.get("totals"))
            bookmakers.append(
                BookmakerOdds(
                    bookmaker=bm.get("title", bm.get("key", "unknown")),
                    home=float(outcomes[home_team]),
                    draw=float(draw_price),
                    away=float(outcomes[away_team]),
                    last_update=bm.get("last_update"),
                    totals=totals,
                )
            )

        if not bookmakers:
            return _demo_odds(event["home_team"], event["away_team"], event.get("sport_key", "demo"))

        totals_books = [b.totals for b in bookmakers if b.totals is not None]
        # Prefer books quoting the preferred line when computing best O/U.
        preferred = [t for t in totals_books if abs(t.line - PREFERRED_TOTALS_LINE) < 1e-9]
        line_pool = preferred or totals_books
        totals_line = line_pool[0].line if line_pool else None

        return MatchOdds(
            best_home=max(b.home for b in bookmakers),
            best_draw=max(b.draw for b in bookmakers),
            best_away=max(b.away for b in bookmakers),
            bookmakers=bookmakers,
            totals_line=totals_line,
            best_over=max((t.over for t in line_pool), default=None),
            best_under=max((t.under for t in line_pool), default=None),
        )

    def _demo_fixtures(self, league: LeagueKey) -> list[dict]:
        fixtures = DEMO_FIXTURES.get(league, [])
        now = datetime.now(timezone.utc)
        events: list[dict] = []
        for i, (home, away, hours) in enumerate(fixtures):
            odds = _demo_odds(home, away, league)
            events.append(
                {
                    "id": f"{league}-{i}-{hashlib.md5(f'{home}{away}'.encode()).hexdigest()[:8]}",
                    "sport_key": LEAGUE_META[league]["odds_api_key"],
                    "commence_time": (now + timedelta(hours=hours)).isoformat(),
                    "home_team": home,
                    "away_team": away,
                    "bookmakers": [
                        {
                            "key": b.bookmaker.lower(),
                            "title": b.bookmaker,
                            "last_update": b.last_update.isoformat() if b.last_update else None,
                            "markets": [
                                {
                                    "key": "h2h",
                                    "outcomes": [
                                        {"name": home, "price": b.home},
                                        {"name": "Draw", "price": b.draw},
                                        {"name": away, "price": b.away},
                                    ],
                                },
                                *(
                                    [
                                        {
                                            "key": "totals",
                                            "outcomes": [
                                                {
                                                    "name": "Over",
                                                    "price": b.totals.over,
                                                    "point": b.totals.line,
                                                },
                                                {
                                                    "name": "Under",
                                                    "price": b.totals.under,
                                                    "point": b.totals.line,
                                                },
                                            ],
                                        }
                                    ]
                                    if b.totals
                                    else []
                                ),
                            ],
                        }
                        for b in odds.bookmakers
                    ],
                }
            )
        return events


DEMO_FIXTURES: dict[str, list[tuple[str, str, int]]] = {
    "epl": [
        ("Arsenal", "Chelsea", 6),
        ("Manchester City", "Liverpool", 28),
        ("Tottenham", "Newcastle", 30),
        ("Manchester United", "Aston Villa", 52),
        ("Brighton", "West Ham", 54),
    ],
    "laliga": [
        ("Real Madrid", "Barcelona", 8),
        ("Atletico Madrid", "Sevilla", 26),
        ("Real Sociedad", "Athletic Bilbao", 50),
        ("Villarreal", "Girona", 72),
    ],
    "bundesliga": [
        ("Bayern Munich", "Borussia Dortmund", 10),
        ("RB Leipzig", "Bayer Leverkusen", 32),
        ("Eintracht Frankfurt", "Wolfsburg", 56),
        ("Stuttgart", "Hoffenheim", 74),
    ],
    "seriea": [
        ("Inter", "AC Milan", 12),
        ("Juventus", "Napoli", 34),
        ("Roma", "Lazio", 58),
        ("Atalanta", "Fiorentina", 76),
    ],
    "ucl": [
        ("Real Madrid", "Manchester City", 48),
        ("Bayern Munich", "Arsenal", 50),
        ("Inter", "Barcelona", 72),
        ("PSG", "Liverpool", 74),
    ],
    "uel": [
        ("Roma", "Tottenham", 46),
        ("Ajax", "Eintracht Frankfurt", 70),
        ("Porto", "West Ham", 94),
    ],
}


odds_client = OddsApiClient()
