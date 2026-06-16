"""LinkedIn scraper — Playwright with persistent session + human-like delays."""
import asyncio
import random
from typing import Optional
from urllib.parse import quote_plus, urljoin

from playwright.async_api import async_playwright

from config.job_targets import SEARCH_QUERIES
from config.settings import settings
from job_agent.db.models import Job
from job_agent.db.store import JobStore
from job_agent.scrapers.base import BaseScraper

BASE_URL = "https://www.linkedin.com"
JOBS_URL = f"{BASE_URL}/jobs/search/"


class LinkedInScraper(BaseScraper):
    source_name = "linkedin"

    async def scrape(
        self,
        query: Optional[str] = None,
        limit: int = 50,
    ) -> list[Job]:
        queries = [query] if query else SEARCH_QUERIES.get("linkedin", ["C++ software engineer New York"])
        jobs: list[Job] = []

        async with async_playwright() as p:
            # Persistent context saves login session
            browser, context = await self._new_browser_context(
                p, headless=False, persistent=True  # headless=False for initial login
            )
            page = await context.new_page()
            await self._ensure_logged_in(page)

            for q in queries:
                if len(jobs) >= limit:
                    break
                try:
                    scraped = await self._scrape_query(page, q, limit - len(jobs))
                    jobs.extend(scraped)
                    await self._human_delay()
                except Exception as e:
                    print(f"[linkedin] Error scraping '{q}': {e}")

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
        """Navigate to LinkedIn; login if not already authenticated."""
        await page.goto(f"{BASE_URL}/feed/", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)

        # Check if redirected to login page
        if "login" in page.url or "checkpoint" in page.url:
            if not settings.linkedin_email or not settings.linkedin_password:
                print(
                    "[linkedin] Not logged in and no credentials set.\n"
                    "  1. Set LINKEDIN_EMAIL and LINKEDIN_PASSWORD in .env, OR\n"
                    "  2. Manually log in to the browser window and press Enter in the terminal."
                )
                input("Press Enter after logging in manually...")
                return

            try:
                await page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=20000)
                await asyncio.sleep(1)
                await page.fill('#username', settings.linkedin_email)
                await asyncio.sleep(random.uniform(0.5, 1.2))
                await page.fill('#password', settings.linkedin_password)
                await asyncio.sleep(random.uniform(0.3, 0.8))
                await page.click('[type="submit"]')
                await asyncio.sleep(5)

                if "checkpoint" in page.url or "challenge" in page.url:
                    print("[linkedin] CAPTCHA/checkpoint detected. Please solve it in the browser.")
                    input("Press Enter after completing the verification...")
                elif "feed" in page.url:
                    print("[linkedin] Logged in successfully")
            except Exception as e:
                print(f"[linkedin] Login error: {e}")

    async def _scrape_query(self, page, query: str, limit: int) -> list[Job]:
        """Search LinkedIn jobs for a query."""
        # geoId=90000070 is New York City area
        search_url = (
            f"{JOBS_URL}?keywords={quote_plus(query)}"
            f"&location=New+York+City+Metropolitan+Area"
            f"&geoId=90000070"
            f"&f_TPR=r86400"  # Past 24 hours — remove for broader results
            f"&sortBy=DD"
        )
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        jobs = []
        seen_urls: set[str] = set()

        for scroll_attempt in range(5):
            if len(jobs) >= limit:
                break

            cards = await page.query_selector_all(
                '.job-card-container, [class*="job-card-list__entity"], '
                '[data-job-id], li.jobs-search-results__list-item'
            )

            for card in cards:
                if len(jobs) >= limit:
                    break
                try:
                    link = await card.query_selector('a.job-card-list__title, a[href*="/jobs/view/"]')
                    if not link:
                        continue
                    href = await link.get_attribute("href")
                    if not href:
                        continue

                    # Normalise URL (remove tracking params)
                    clean_url = urljoin(BASE_URL, href.split("?")[0])
                    if clean_url in seen_urls or self.store.job_exists(clean_url):
                        continue
                    seen_urls.add(clean_url)

                    title_el = await link.query_selector('span[aria-hidden="true"]') or link
                    title = await title_el.inner_text()

                    company = await self._text(card, '.job-card-container__company-name, [class*="company-name"]')
                    location = await self._text(card, '.job-card-container__metadata-item, [class*="location"]')

                    jobs.append(Job(
                        url=clean_url,
                        title=title.strip(),
                        company=(company or "Unknown").strip(),
                        location=(location or "New York, NY").strip(),
                        source=self.source_name,
                    ))

                    await self._human_delay(0.5, 1.5)
                except Exception as e:
                    print(f"[linkedin] Card error: {e}")

            # Scroll to load more
            await page.evaluate("window.scrollBy(0, 800)")
            await asyncio.sleep(random.uniform(1.5, 3.0))

        # Now fetch full descriptions for each job
        for job in jobs:
            await self._fetch_description(page, job)
            await self._human_delay()

        return jobs

    async def _fetch_description(self, page, job: Job) -> None:
        """Visit job detail page to get full description and apply URL."""
        try:
            await page.goto(job.url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)

            # Expand "Show more" button
            show_more = await page.query_selector('[class*="show-more-less-html__button"], button[aria-label*="more"]')
            if show_more:
                await show_more.click()
                await asyncio.sleep(0.5)

            desc_el = await page.query_selector('.jobs-description__content, [class*="description__text"], .job-view-layout')
            if desc_el:
                job.description = (await desc_el.inner_text()).strip()[:10000]

            # Find apply URL
            apply_btn = await page.query_selector(
                'a[href*="greenhouse"], a[href*="lever"], '
                '.jobs-apply-button a, [class*="apply-button"] a'
            )
            if apply_btn:
                apply_href = await apply_btn.get_attribute("href")
                if apply_href:
                    job.apply_url = apply_href
                    job.ats_type = self._detect_ats(apply_href)

        except Exception as e:
            print(f"[linkedin] Description fetch error for {job.url}: {e}")

    @staticmethod
    async def _human_delay(
        min_s: float = None, max_s: float = None
    ) -> None:
        lo = min_s or settings.linkedin_delay_min
        hi = max_s or settings.linkedin_delay_max
        await asyncio.sleep(random.uniform(lo, hi))

    @staticmethod
    async def _text(el, selector: str) -> str:
        try:
            child = await el.query_selector(selector)
            if child:
                return (await child.inner_text()).strip()
        except Exception:
            pass
        return ""
