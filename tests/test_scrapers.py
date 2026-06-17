"""Tests for web scraper components.

Strategy:
- ATS detection is a pure function — tested directly, no mocks needed.
- Indeed RSS parsing mocks aiohttp to avoid network calls.
- BuiltIn job detail extraction mocks Playwright page objects.
- Deduplication is tested by patching _scrape_rss to return controlled data.
"""
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from job_agent.db.models import Job
from job_agent.db.store import JobStore
from job_agent.scrapers.builtin_nyc import BuiltInNYCScraper
from job_agent.scrapers.indeed import IndeedScraper


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmpdir:
        s = JobStore(Path(tmpdir) / "test.db")
        yield s
        s.close()


@pytest.fixture
def builtin_scraper(store):
    return BuiltInNYCScraper(store)


@pytest.fixture
def indeed_scraper(store):
    return IndeedScraper(store)


# ── ATS Detection ──────────────────────────────────────────────────


class TestATSDetection:
    """_detect_ats is a pure function — no mocking required."""

    def test_greenhouse_board_url(self, builtin_scraper):
        assert builtin_scraper._detect_ats("https://boards.greenhouse.io/acme/jobs/99") == "greenhouse"

    def test_greenhouse_dot_io(self, builtin_scraper):
        assert builtin_scraper._detect_ats("https://greenhouse.io/acme/apply") == "greenhouse"

    def test_lever_jobs(self, builtin_scraper):
        assert builtin_scraper._detect_ats("https://jobs.lever.co/company/abc-123") == "lever"

    def test_lever_apply_suffix(self, builtin_scraper):
        assert builtin_scraper._detect_ats("https://jobs.lever.co/stripe/pos/apply") == "lever"

    def test_workday(self, builtin_scraper):
        assert builtin_scraper._detect_ats("https://company.wd1.myworkdayjobs.com/en-US/jobs") == "workday"

    def test_icims(self, builtin_scraper):
        assert builtin_scraper._detect_ats("https://acme.icims.com/jobs/apply") == "icims"

    def test_taleo(self, builtin_scraper):
        assert builtin_scraper._detect_ats("https://acme.taleo.net/careersection/apply") == "taleo"

    def test_smartrecruiters(self, builtin_scraper):
        assert builtin_scraper._detect_ats("https://jobs.smartrecruiters.com/acme/role") == "smartrecruiters"

    def test_unknown_returns_none(self, builtin_scraper):
        assert builtin_scraper._detect_ats("https://hiring.somecompany.com/positions/123") is None

    def test_case_insensitive(self, builtin_scraper):
        # URL is lowercased before matching
        assert builtin_scraper._detect_ats("https://boards.GREENHOUSE.IO/company/123") == "greenhouse"

    def test_empty_url_returns_none(self, builtin_scraper):
        assert builtin_scraper._detect_ats("") is None

    def test_indeed_scraper_shares_same_detect_ats(self, indeed_scraper):
        # ATS detection is on BaseScraper — all scrapers share the same logic
        assert indeed_scraper._detect_ats("https://jobs.lever.co/a/b") == "lever"


# ── Indeed RSS feed parsing ────────────────────────────────────────

RSS_SAMPLE = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:indeed="https://www.indeed.com/about/rss">
  <channel>
    <title>Indeed Jobs</title>
    <item>
      <title>Senior C++ Engineer</title>
      <link>https://www.indeed.com/viewjob?jk=abc123</link>
      <description>Low-latency systems engineering role requiring C++17.</description>
      <indeed:location>New York, NY</indeed:location>
      <indeed:company>HFT Corp</indeed:company>
    </item>
    <item>
      <title>Systems Programmer</title>
      <link>https://www.indeed.com/viewjob?jk=def456</link>
      <description>Kernel-level programming, device drivers, embedded Linux.</description>
      <indeed:location>Remote</indeed:location>
      <indeed:company>Acme Systems</indeed:company>
    </item>
  </channel>
</rss>
"""

RSS_GREENHOUSE_LINK = RSS_SAMPLE.replace(
    "https://www.indeed.com/viewjob?jk=abc123",
    "https://boards.greenhouse.io/acme/jobs/123",
)


def _mock_aiohttp_session(rss_content: str, status: int = 200):
    """Build a fully mocked aiohttp ClientSession context manager."""
    mock_resp = AsyncMock()
    mock_resp.status = status
    mock_resp.text = AsyncMock(return_value=rss_content)

    mock_get_ctx = AsyncMock()
    mock_get_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_get_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.get = MagicMock(return_value=mock_get_ctx)

    return mock_session


@pytest.mark.asyncio
class TestIndeedRSSParsing:
    async def test_parses_two_jobs(self, indeed_scraper):
        session = _mock_aiohttp_session(RSS_SAMPLE)
        with patch("job_agent.scrapers.indeed.aiohttp.ClientSession", return_value=session):
            jobs = await indeed_scraper._scrape_rss("c++ engineer", limit=10)

        assert len(jobs) == 2

    async def test_correct_fields_on_first_job(self, indeed_scraper):
        session = _mock_aiohttp_session(RSS_SAMPLE)
        with patch("job_agent.scrapers.indeed.aiohttp.ClientSession", return_value=session):
            jobs = await indeed_scraper._scrape_rss("c++ engineer", limit=10)

        j = jobs[0]
        assert j.title == "Senior C++ Engineer"
        assert j.company == "HFT Corp"
        assert j.location == "New York, NY"
        assert j.source == "indeed"
        assert "indeed.com" in j.url

    async def test_respects_limit(self, indeed_scraper):
        session = _mock_aiohttp_session(RSS_SAMPLE)
        with patch("job_agent.scrapers.indeed.aiohttp.ClientSession", return_value=session):
            jobs = await indeed_scraper._scrape_rss("c++ engineer", limit=1)

        assert len(jobs) == 1

    async def test_returns_empty_on_http_error(self, indeed_scraper):
        session = _mock_aiohttp_session("", status=429)
        with patch("job_agent.scrapers.indeed.aiohttp.ClientSession", return_value=session):
            jobs = await indeed_scraper._scrape_rss("c++ engineer", limit=10)

        assert jobs == []

    async def test_skips_jobs_already_in_store(self, indeed_scraper, store):
        existing = Job(
            url="https://www.indeed.com/viewjob?jk=abc123",
            title="Senior C++ Engineer",
            company="HFT Corp",
            source="indeed",
        )
        store.upsert_job(existing)

        session = _mock_aiohttp_session(RSS_SAMPLE)
        with patch("job_agent.scrapers.indeed.aiohttp.ClientSession", return_value=session):
            jobs = await indeed_scraper._scrape_rss("c++ engineer", limit=10)

        urls = [j.url for j in jobs]
        assert "https://www.indeed.com/viewjob?jk=abc123" not in urls
        assert len(jobs) == 1  # only the second job

    async def test_detects_greenhouse_ats_from_job_link(self, indeed_scraper):
        session = _mock_aiohttp_session(RSS_GREENHOUSE_LINK)
        with patch("job_agent.scrapers.indeed.aiohttp.ClientSession", return_value=session):
            jobs = await indeed_scraper._scrape_rss("c++ engineer", limit=10)

        greenhouse_jobs = [j for j in jobs if j.ats_type == "greenhouse"]
        assert len(greenhouse_jobs) == 1

    async def test_deduplicates_across_two_scrape_calls(self, indeed_scraper):
        """scrape() deduplicates jobs returned by _scrape_rss across queries."""
        shared_job = Job(
            url="https://www.indeed.com/viewjob?jk=shared",
            title="C++ Dev",
            company="Corp",
            source="indeed",
        )
        with patch.object(indeed_scraper, "_scrape_rss", return_value=[shared_job]):
            jobs = await indeed_scraper.scrape(query="c++", limit=10)

        urls = [j.url for j in jobs]
        assert urls.count(shared_job.url) == 1


# ── BuiltIn NYC job detail extraction ─────────────────────────────


def _mock_text_element(text: str) -> AsyncMock:
    el = AsyncMock()
    el.inner_text = AsyncMock(return_value=text)
    return el


def _mock_apply_element(href: str) -> AsyncMock:
    el = AsyncMock()
    el.get_attribute = AsyncMock(return_value=href)
    return el


@pytest.mark.asyncio
class TestBuiltInJobDetail:
    async def _make_page(self, title="C++ Engineer", company="HFT Corp",
                          location="New York, NY", description="Low-latency role.",
                          apply_href=None):
        """Construct a mock page with predictable query_selector behavior."""
        page = AsyncMock()
        page.goto = AsyncMock()

        async def query_selector(selector):
            if "h1" in selector or "title" in selector:
                return _mock_text_element(title)
            if "company" in selector or "employer" in selector:
                return _mock_text_element(company)
            if "location" in selector or "Location" in selector:
                return _mock_text_element(location) if location else None
            if "description" in selector or "Description" in selector or "main" in selector:
                return _mock_text_element(description)
            if "greenhouse" in selector or "lever" in selector or "apply" in selector:
                return _mock_apply_element(apply_href) if apply_href else None
            return None

        page.query_selector = query_selector
        return page

    async def test_extracts_basic_fields(self, builtin_scraper):
        page = await self._make_page()
        with patch("asyncio.sleep", new_callable=AsyncMock):
            job = await builtin_scraper._scrape_job_detail(page, "https://builtinnyc.com/job/123")

        assert job is not None
        assert job.title == "C++ Engineer"
        assert job.company == "HFT Corp"
        assert job.location == "New York, NY"
        assert job.source == "builtin"
        assert job.url == "https://builtinnyc.com/job/123"

    async def test_returns_none_when_no_title(self, builtin_scraper):
        page = AsyncMock()
        page.goto = AsyncMock()
        page.query_selector = AsyncMock(return_value=None)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            job = await builtin_scraper._scrape_job_detail(page, "https://builtinnyc.com/job/404")

        assert job is None

    async def test_detects_greenhouse_apply_link(self, builtin_scraper):
        page = await self._make_page(apply_href="https://boards.greenhouse.io/company/jobs/99")

        with patch("asyncio.sleep", new_callable=AsyncMock):
            job = await builtin_scraper._scrape_job_detail(page, "https://builtinnyc.com/job/456")

        assert job is not None
        assert job.ats_type == "greenhouse"
        assert "greenhouse" in job.apply_url

    async def test_defaults_location_to_new_york(self, builtin_scraper):
        page = await self._make_page(location=None)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            job = await builtin_scraper._scrape_job_detail(page, "https://builtinnyc.com/job/789")

        assert job is not None
        assert job.location == "New York, NY"

    async def test_description_is_truncated_at_10000_chars(self, builtin_scraper):
        long_desc = "x" * 20000
        page = await self._make_page(description=long_desc)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            job = await builtin_scraper._scrape_job_detail(page, "https://builtinnyc.com/job/long")

        assert job is not None
        assert len(job.description) <= 10000

    async def test_skips_url_if_already_in_store(self, builtin_scraper, store):
        """_scrape_query should skip jobs whose URLs are already in the DB."""
        # urljoin(BASE_URL, "/job/existing") produces the www. form
        existing_url = "https://www.builtinnyc.com/job/existing"
        store.upsert_job(Job(url=existing_url, title="Old Job", company="Corp", source="builtin"))

        # _scrape_query calls store.job_exists before visiting the detail page
        page = AsyncMock()
        page.goto = AsyncMock()
        page.query_selector_all = AsyncMock(return_value=[])
        page.query_selector = AsyncMock(return_value=None)

        # If job_exists returns True for this URL, _scrape_job_detail should never be called
        with patch.object(builtin_scraper, "_scrape_job_detail") as mock_detail:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                # Simulate Phase 1 returning only the existing URL
                async def fake_query_all(selector):
                    if "/job/" in selector:
                        el = AsyncMock()
                        el.get_attribute = AsyncMock(return_value="/job/existing")
                        return [el]
                    return []

                page.query_selector_all = fake_query_all
                page.query_selector = AsyncMock(return_value=None)  # no next-page button
                await builtin_scraper._scrape_query(page, "c++", 10)

        mock_detail.assert_not_called()
