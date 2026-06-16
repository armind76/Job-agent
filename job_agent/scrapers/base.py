"""Base scraper abstract class."""
from abc import ABC, abstractmethod
from typing import Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from config.settings import settings
from job_agent.db.models import Job
from job_agent.db.store import JobStore


class BaseScraper(ABC):
    """Abstract base class for all job board scrapers."""

    source_name: str = "unknown"

    def __init__(self, store: JobStore) -> None:
        self.store = store

    @abstractmethod
    async def scrape(
        self,
        query: Optional[str] = None,
        limit: int = 50,
    ) -> list[Job]:
        """
        Scrape job listings and return a list of Job objects.
        Jobs should be inserted into the store by the caller.
        """
        ...

    async def _new_browser_context(
        self, playwright, headless: bool = True, persistent: bool = False
    ) -> tuple[Browser | None, BrowserContext]:
        """Launch a browser context, optionally with a persistent session."""
        sessions_dir = settings.sessions_dir
        sessions_dir.mkdir(parents=True, exist_ok=True)

        if persistent:
            profile_path = sessions_dir / self.source_name
            context = await playwright.chromium.launch_persistent_context(
                str(profile_path),
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"],
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            return None, context

        browser = await playwright.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        )
        return browser, context

    def _detect_ats(self, url: str) -> Optional[str]:
        """Detect the ATS from an apply URL."""
        from config.job_targets import ATS_PATTERNS
        url_lower = url.lower()
        for ats, domains in ATS_PATTERNS.items():
            if any(d in url_lower for d in domains):
                return ats
        return None
