"""Glassdoor scraper — uses Playwright with persistent login session."""
import asyncio
import re
from typing import Optional
from urllib.parse import quote_plus, urljoin

from playwright.async_api import async_playwright

from config.job_targets import SEARCH_QUERIES
from config.settings import settings
from job_agent.db.models import Job
from job_agent.db.store import JobStore
from job_agent.scrapers.base import BaseScraper

BASE_URL = "https://www.glassdoor.com"


class GlassdoorScraper(BaseScraper):
    source_name = "glassdoor"

    async def scrape(
        self,
        query: Optional[str] = None,
        limit: int = 50,
    ) -> list[Job]:
        queries = [query] if query else SEARCH_QUERIES.get("glassdoor", ["C++ engineer New York"])
        jobs: list[Job] = []

        async with async_playwright() as p:
            # Use persistent context to preserve login cookies
            browser, context = await self._new_browser_context(
                p, headless=True, persistent=True
            )
            page = await context.new_page()

            # Check if login is needed
            await self._ensure_logged_in(page)

            for q in queries:
                if len(jobs) >= limit:
                    break
                try:
                    scraped = await self._scrape_query(page, q, limit - len(jobs))
                    jobs.extend(scraped)
                except Exception as e:
                    print(f"[glassdoor] Error scraping '{q}': {e}")

            await context.close()
            if browser:
                await browser.close()

        seen = set()
        unique = []
        for j in jobs:
            if j.url not in seen:
                seen.add(j.url)
                unique.append(j)
        return unique[:limit]

    async def _ensure_logged_in(self, page) -> None:
        """Check login state; attempt login if credentials are available."""
        await page.goto(f"{BASE_URL}/index.htm", wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(1)

        # Check if already logged in
        profile_link = await page.query_selector('[href*="/member/"], [data-test="header-username"]')
        if profile_link:
            return  # Already logged in

        if not settings.glassdoor_email or not settings.glassdoor_password:
            print("[glassdoor] No credentials configured; proceeding without login")
            return

        try:
            await page.goto(f"{BASE_URL}/profile/login_input.htm", wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)
            await page.fill('input[name="username"], input[type="email"]', settings.glassdoor_email)
            await page.fill('input[name="password"], input[type="password"]', settings.glassdoor_password)
            await page.keyboard.press("Enter")
            await asyncio.sleep(3)
            print("[glassdoor] Login attempted")
        except Exception as e:
            print(f"[glassdoor] Login error: {e}")

    async def _scrape_query(self, page, query: str, limit: int) -> list[Job]:
        search_url = (
            f"{BASE_URL}/Job/new-york-city-new-york-jobs-SRCH_IL.0,21_IC1132348_KO22,"
            f"{22 + len(query)}.htm?keyword={quote_plus(query)}"
        )
        # Use simpler search URL
        search_url = f"{BASE_URL}/Jobs/Jobs.htm?suggestCount=0&suggestChosen=false&clickSource=searchBtn&typedKeyword={quote_plus(query)}&locT=C&locId=1132348&jobType="

        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        jobs = []
        cards = await page.query_selector_all('[class*="jobCard"], [data-test="job-list-item"], li[class*="react-job-listing"]')

        for card in cards[:limit]:
            try:
                title_el = await card.query_selector('a[class*="jobTitle"], [data-test="job-link"]')
                if not title_el:
                    continue

                title = await title_el.inner_text()
                href = await title_el.get_attribute("href")
                if not href:
                    continue

                job_url = urljoin(BASE_URL, href.split("?")[0])
                if self.store.job_exists(job_url):
                    continue

                company = await self._text(card, '[class*="employer"], [data-test="employer-name"]')
                location = await self._text(card, '[class*="location"], [data-test="emp-location"]')

                jobs.append(Job(
                    url=job_url,
                    title=title.strip(),
                    company=(company or "Unknown").strip(),
                    location=(location or "New York, NY").strip(),
                    source=self.source_name,
                ))
            except Exception as e:
                print(f"[glassdoor] Card error: {e}")

        return jobs

    @staticmethod
    async def _text(el, selector: str) -> str:
        try:
            child = await el.query_selector(selector)
            if child:
                return (await child.inner_text()).strip()
        except Exception:
            pass
        return ""
