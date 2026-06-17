"""Built In NYC scraper — least hostile, no login required."""
import asyncio
import re
from typing import Optional
from urllib.parse import urljoin

from playwright.async_api import async_playwright

from config.job_targets import SEARCH_QUERIES
from job_agent.db.models import Job
from job_agent.db.store import JobStore
from job_agent.scrapers.base import BaseScraper

BASE_URL = "https://www.builtinnyc.com"
SEARCH_URL = f"{BASE_URL}/jobs/dev-engineer"


class BuiltInNYCScraper(BaseScraper):
    source_name = "builtin"

    async def scrape(
        self,
        query: Optional[str] = None,
        limit: int = 50,
    ) -> list[Job]:
        jobs: list[Job] = []

        async with async_playwright() as p:
            browser, context = await self._new_browser_context(p, headless=True)
            page = await context.new_page()

            queries = [query] if query else SEARCH_QUERIES.get("builtin", ["c++"])

            for q in queries:
                if len(jobs) >= limit:
                    break
                try:
                    scraped = await self._scrape_query(page, q, limit - len(jobs))
                    jobs.extend(scraped)
                except Exception as e:
                    print(f"[builtin] Error scraping '{q}': {e}")

            await context.close()
            if browser:
                await browser.close()

        # Deduplicate by URL
        seen = set()
        unique = []
        for j in jobs:
            if j.url not in seen:
                seen.add(j.url)
                unique.append(j)
        return unique[:limit]

    async def _scrape_query(self, page, query: str, limit: int) -> list[Job]:
        """Scrape a single search query from Built In NYC."""
        search_url = f"{BASE_URL}/jobs?search={query.replace(' ', '+')}&city=NYC"
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)

        # Phase 1: collect job URLs by paginating the listing (no detail navigation yet)
        all_urls: list[str] = []
        while len(all_urls) < limit:
            links = await page.query_selector_all('a[href*="/job/"]')
            for link in links:
                href = await link.get_attribute("href")
                if href:
                    job_url = urljoin(BASE_URL, href)
                    if job_url not in all_urls:
                        all_urls.append(job_url)

            next_btn = await page.query_selector('[aria-label="Next page"], .pagination-next, a[rel="next"]')
            if not next_btn or len(all_urls) >= limit:
                break
            await next_btn.click()
            await asyncio.sleep(2)

        # Phase 2: visit each detail page individually
        jobs = []
        for job_url in all_urls[:limit]:
            if self.store.job_exists(job_url):
                continue
            job = await self._scrape_job_detail(page, job_url)
            if job:
                jobs.append(job)
            if len(jobs) >= limit:
                break

        return jobs

    async def _scrape_job_detail(self, page, url: str) -> Optional[Job]:
        """Navigate to a job detail page and extract structured data."""
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(1)

            title = await self._text(page, 'h1, [class*="title"]')

            # Company: try progressively wider selectors
            company = (
                await self._text(page, '[class*="company-name"]')
                or await self._text(page, '[data-testid*="company"]')
                or await self._text(page, '[class*="company"] a')
                or await self._text(page, '[class*="company"]')
                or await self._text(page, '[class*="employer"]')
                or await self._attr(page, 'meta[property="og:site_name"]', "content")
            )

            location = await self._text(page, '[class*="location"], [class*="Location"]')
            description = await self._text(
                page,
                '[class*="description"], [class*="Description"], .job-description, main',
            )

            if not title:
                return None

            # Apply URL: scan for known ATS links first, then any external apply href
            apply_url = None
            ats_type = None

            apply_selectors = [
                'a[href*="greenhouse.io"]',
                'a[href*="lever.co"]',
                'a[href*="myworkdayjobs"]',
                'a[href*="icims.com"]',
                'a[href*="taleo.net"]',
                'a[href*="smartrecruiters"]',
                'a[href*="jobvite"]',
                'a[href*="ashbyhq"]',
                'a[href*="rippling"]',
                # Generic "Apply" anchors — captures anything not caught above
                'a:has-text("Apply Now")',
                'a:has-text("Apply for Job")',
                'a:has-text("Apply for this job")',
                'a[class*="apply"]',
                '[data-apply-url]',
            ]
            for sel in apply_selectors:
                el = await page.query_selector(sel)
                if el:
                    href = await el.get_attribute("href") or await el.get_attribute("data-apply-url")
                    if href and href.startswith("http") and "builtinnyc.com" not in href:
                        apply_url = href
                        ats_type = self._detect_ats(apply_url)
                        break

            return Job(
                url=url,
                title=title.strip(),
                company=(company or "Unknown").strip(),
                location=(location or "New York, NY").strip(),
                description=(description or "").strip()[:10000],
                source=self.source_name,
                apply_url=apply_url,
                ats_type=ats_type,
            )
        except Exception as e:
            print(f"[builtin] Failed to scrape {url}: {e}")
            return None

    @staticmethod
    async def _text(page, selector: str) -> str:
        try:
            el = await page.query_selector(selector)
            if el:
                return (await el.inner_text()).strip()
        except Exception:
            pass
        return ""

    @staticmethod
    async def _attr(page, selector: str, attr: str) -> str:
        try:
            el = await page.query_selector(selector)
            if el:
                val = await el.get_attribute(attr)
                return (val or "").strip()
        except Exception:
            pass
        return ""
