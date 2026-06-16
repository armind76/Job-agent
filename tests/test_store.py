"""Tests for the JobStore SQLite layer."""
import json
import tempfile
from pathlib import Path

import pytest

from job_agent.db.models import Application, Job, ResumeCache
from job_agent.db.store import JobStore


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        s = JobStore(db_path)
        yield s
        s.close()


@pytest.fixture
def sample_job():
    return Job(
        url="https://example.com/job/1",
        title="Senior C++ Engineer",
        company="Acme Corp",
        location="New York, NY",
        description="C++17, low-latency, trading systems",
        source="builtin",
        ats_type="greenhouse",
        apply_url="https://boards.greenhouse.io/acme/jobs/1",
    )


def test_upsert_job_new(store, sample_job):
    result = store.upsert_job(sample_job)
    assert result is True  # Newly inserted


def test_upsert_job_duplicate(store, sample_job):
    store.upsert_job(sample_job)
    result = store.upsert_job(sample_job)  # Same URL
    assert result is False  # Already exists


def test_get_job_by_id(store, sample_job):
    store.upsert_job(sample_job)
    retrieved = store.get_job(sample_job.id)
    assert retrieved is not None
    assert retrieved.title == "Senior C++ Engineer"
    assert retrieved.company == "Acme Corp"
    assert retrieved.url == sample_job.url


def test_job_exists(store, sample_job):
    assert store.job_exists(sample_job.url) is False
    store.upsert_job(sample_job)
    assert store.job_exists(sample_job.url) is True


def test_update_job_classification(store, sample_job):
    store.upsert_job(sample_job)
    store.update_job_classification(
        sample_job.id,
        tier=1,
        score=0.95,
        reason="C++ systems role",
        ats_type="greenhouse",
        apply_url="https://boards.greenhouse.io/acme/jobs/1",
    )
    job = store.get_job(sample_job.id)
    assert job.priority_tier == 1
    assert job.priority_score == 0.95
    assert job.priority_reason == "C++ systems role"


def test_update_job_status(store, sample_job):
    store.upsert_job(sample_job)
    store.update_job_status(sample_job.id, "applied")
    job = store.get_job(sample_job.id)
    assert job.status == "applied"


def test_get_pending_jobs_empty(store):
    jobs = store.get_pending_jobs()
    assert jobs == []


def test_get_pending_jobs(store):
    job1 = Job(url="https://example.com/1", title="C++ Dev", company="A", source="builtin")
    job2 = Job(url="https://example.com/2", title="Python Dev", company="B", source="indeed")
    store.upsert_job(job1)
    store.upsert_job(job2)
    store.update_job_classification(job1.id, tier=1, score=0.9, reason="C++")
    store.update_job_classification(job2.id, tier=4, score=0.3, reason="Python")

    pending = store.get_pending_jobs()
    assert len(pending) == 2

    pending_t1 = store.get_pending_jobs(tier_filter=1)
    assert len(pending_t1) == 1
    assert pending_t1[0].title == "C++ Dev"


def test_insert_application(store, sample_job):
    store.upsert_job(sample_job)
    app = Application(
        job_id=sample_job.id,
        resume_path="/path/to/resume.pdf",
        cover_letter="Dear Hiring Manager...",
        auto_mode=False,
        success=True,
    )
    store.insert_application(app)

    retrieved = store.get_application(sample_job.id)
    assert retrieved is not None
    assert retrieved.success is True
    assert retrieved.resume_path == "/path/to/resume.pdf"


def test_resume_cache(store):
    cache = ResumeCache(
        resume_path="/resumes/test.pdf",
        resume_hash="abc123",
        extracted_text="Experience with C++ and low-latency systems...",
        summary="Experienced systems engineer",
        skills_json=json.dumps(["C++", "Python", "Linux"]),
    )
    store.upsert_resume_cache(cache)

    retrieved = store.get_cached_resume("/resumes/test.pdf", "abc123")
    assert retrieved is not None
    assert retrieved.extracted_text == cache.extracted_text
    assert json.loads(retrieved.skills_json) == ["C++", "Python", "Linux"]

    # Wrong hash returns None
    assert store.get_cached_resume("/resumes/test.pdf", "wronghash") is None


def test_stats(store, sample_job):
    store.upsert_job(sample_job)
    stats = store.stats()
    assert stats["total"] == 1
    assert stats["pending"] == 1
    assert stats["applied"] == 0


def test_load_from_fixture():
    """Verify the sample fixture parses correctly."""
    import json
    from pathlib import Path

    fixture_path = Path(__file__).parent / "fixtures" / "sample_job.json"
    data = json.loads(fixture_path.read_text())

    job = Job(
        id=data["id"],
        url=data["url"],
        title=data["title"],
        company=data["company"],
        location=data["location"],
        description=data["description"],
        source=data["source"],
        ats_type=data["ats_type"],
        apply_url=data["apply_url"],
        priority_tier=data["priority_tier"],
        priority_score=data["priority_score"],
        priority_reason=data["priority_reason"],
        scraped_at=data["scraped_at"],
        status=data["status"],
    )
    assert job.title == "Senior C++ Systems Engineer"
    assert job.priority_tier == 1
    assert job.ats_type == "greenhouse"
