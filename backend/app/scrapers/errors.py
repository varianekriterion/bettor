"""Scraper-specific exceptions for graceful pipeline degradation."""


class ScraperError(Exception):
    """Base scraper failure."""


class ScraperBlockedError(ScraperError):
    """Site returned 403, CAPTCHA, or other bot-blocking response."""

    def __init__(self, source: str, status_code: int | None = None, detail: str = "") -> None:
        self.source = source
        self.status_code = status_code
        self.detail = detail
        super().__init__(
            f"{source} blocked"
            + (f" (HTTP {status_code})" if status_code else "")
            + (f": {detail}" if detail else "")
        )


class ScraperParseError(ScraperError):
    """HTML/DOM changed or expected prediction fields missing."""
