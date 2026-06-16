"""Indeed scraper — tries RSS feed first, falls back to Playwright."""
import asyncio
import xml.etree.ElementTree as ET
from typing import Optional
from urllib.parse import quote_plus, urljoin

import aiohttp
from playwright.async_api import async_playwright

from config.job_targets import SEARCH_QUERIES
from job_agent.db.models import Job
from job_agent.db.store import JobStore
from job_agent.scrapers.base import BaseScraper

BASE_URL = "https://www.indeed.com"
RSS_TEMPLATE = "https://www.indeed.com/rss?q={query}&l=New+York%2C+NY&sort=date&limit=25"


class IndeedScraper(BaseScraper):
    source_name = "indeed"

    async def scrape(
        self,
        query: Optional[str] = None,
        limit: int = 50,
    ) -> list[Job]:
        queries = [query] if query else SEARCH_QUERIES.get("indeed", ["c++ engineer New York"])
        jobs: list[Job] = []

        for q in queries:
            if len(jobs) >= limit:
                break
            # Try RSS first
            rss_jobs = await self._scrape_rss(q, limit - len(jobs))
            if rss_jobs:
                jobs.extend(rss_jobs)
            else:
                # Fall back to Playwright
                pw_jobs = await self._scrape_playwright(q, limit - len(jobs))
                jobs.extend(pw_jobs)

        # Deduplicate
        seen = set()
        unique = []
        for j in jobs:
            if j.url not in seen:
                seen.add(j.url)
                unique.append(j)
        return unique[:limit]

    async def _scrape_rss(self, query: str, limit: int) -> list[Job]:
        """Attempt to scrape the Indeed RSS feed."""
        url = RSS_TEMPLATE.format(query=quote_plus(query))
        jobs = []

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        return []
                    content = await resp.text()

            root = ET.fromstring(content)
            channel = root.find("channel")
            if channel is None:
                return []

            items = channel.findall("item")
            for item in items[:limit]:
                title = item.findtext("title", "").strip()
                link = item.findtext("link", "").strip()
                description = item.findtext("description", "").strip()
                location_el = item.find("{https://www.indeed.com/about/rss}location")
                location = location_el.text.strip() if location_el is not None else "New York, NY"
                company_el = item.find("{https://www.indeed.com/about/rss}company")
                company = company_el.text.strip() if company_el is not None else "Unknown"

                if not title or not link:
                    continue
                if self.store.job_exists(link):
                    continue

                # Detect ATS from apply link if present
                ats_type = self._detect_ats(link)
                jobs.append(Job(
                    url=link,
                    title=title,
                    company=company,
                    location=location,
                    description=description[:10000],
                    source=self.source_name,
                    ats_type=ats_type,
                    apply_url=link,
                ))
        except Exception as e:
            print(f"[indeed] RSS error: {e}")
            return []

        return jobs

    async def _scrape_playwright(self, query: str, limit: int) -> list[Job]:
        """Fall back to Playwright-based scraping."""
        jobs = []
        async with async_playwright() as p:
            browser, context = await self._new_browser_context(p, headless=True)
            page = await context.new_page()

            search_url = f"{BASE_URL}/jobs?q={quote_plus(query)}&l=New+York%2C+NY&sort=date"
            try:
                await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)

                # Indeed frequently updates its DOM — use flexible selectors
                cards = await page.query_selector_all('[class*="jobCard"], [class*="result"], [data-jk]')

                for card in cards[:limit]:
                    try:
                        title_el = await card.query_selector('h2 a, [class*="jobtitle"] a, [class*="title"] a')
                        if not title_el:
                            continue
                        title = await title_el.inner_text()
                        href = await title_el.get_attribute("href")
                        if not href:
                            continue

                        job_url = urljoin(BASE_URL, href)
                        if self.store.job_exists(job_url):
                            continue

                        company = await self._text(card, '[class*="company"], [data-testid="company-name"]')
                        location = await self._text(card, '[class*="location"], [data-testid="text-location"]')

                        jobs.append(Job(
                            url=job_url,
                            title=title.strip(),
                            company=(company or "Unknown").strip(),
                            location=(location or "New York, NY").strip(),
                            source=self.source_name,
                        ))
                    except Exception as e:
                        print(f"[indeed] Card error: {e}")

            except Exception as e:
                print(f"[indeed] Playwright error: {e}")
            finally:
                await context.close()
                if browser:
                    await browser.close()

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
