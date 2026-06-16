"""SQLite-backed job store using aiosqlite."""
import json
import sqlite3
from pathlib import Path
from typing import Optional

from job_agent.db.models import Application, Job, ResumeCache


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            TEXT PRIMARY KEY,
    url           TEXT NOT NULL UNIQUE,
    title         TEXT NOT NULL,
    company       TEXT NOT NULL,
    location      TEXT,
    description   TEXT,
    source        TEXT NOT NULL,
    ats_type      TEXT,
    apply_url     TEXT,
    priority_tier INTEGER,
    priority_score REAL,
    priority_reason TEXT,
    scraped_at    TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS applications (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id        TEXT NOT NULL REFERENCES jobs(id),
    resume_path   TEXT NOT NULL,
    cover_letter  TEXT NOT NULL,
    applied_at    TEXT NOT NULL,
    auto_mode     INTEGER NOT NULL,
    success       INTEGER NOT NULL,
    error_message TEXT,
    UNIQUE(job_id)
);

CREATE TABLE IF NOT EXISTS resume_cache (
    resume_path   TEXT NOT NULL,
    resume_hash   TEXT NOT NULL,
    extracted_text TEXT NOT NULL,
    summary       TEXT,
    skills_json   TEXT,
    cached_at     TEXT NOT NULL,
    PRIMARY KEY (resume_path, resume_hash)
);
"""


class JobStore:
    """Synchronous SQLite store (use in sync contexts; wrap with asyncio.to_thread if needed)."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ──────────────────────────── Jobs ────────────────────────────

    def upsert_job(self, job: Job) -> bool:
        """Insert or ignore a job. Returns True if newly inserted."""
        cur = self._conn.execute(
            """
            INSERT OR IGNORE INTO jobs
                (id, url, title, company, location, description, source,
                 ats_type, apply_url, priority_tier, priority_score, priority_reason,
                 scraped_at, status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                job.id, job.url, job.title, job.company, job.location,
                job.description, job.source, job.ats_type, job.apply_url,
                job.priority_tier, job.priority_score, job.priority_reason,
                job.scraped_at, job.status,
            ),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def update_job_classification(
        self,
        job_id: str,
        tier: int,
        score: float,
        reason: str,
        ats_type: Optional[str] = None,
        apply_url: Optional[str] = None,
    ) -> None:
        self._conn.execute(
            """
            UPDATE jobs
            SET priority_tier=?, priority_score=?, priority_reason=?,
                ats_type=COALESCE(?, ats_type),
                apply_url=COALESCE(?, apply_url)
            WHERE id=?
            """,
            (tier, score, reason, ats_type, apply_url, job_id),
        )
        self._conn.commit()

    def update_job_status(self, job_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE jobs SET status=? WHERE id=?", (status, job_id)
        )
        self._conn.commit()

    def get_job(self, job_id: str) -> Optional[Job]:
        row = self._conn.execute(
            "SELECT * FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
        return self._row_to_job(row) if row else None

    def get_pending_jobs(
        self,
        tier_filter: Optional[int] = None,
        limit: int = 100,
    ) -> list[Job]:
        query = "SELECT * FROM jobs WHERE status='pending'"
        params: list = []
        if tier_filter:
            query += " AND priority_tier=?"
            params.append(tier_filter)
        query += " ORDER BY priority_tier ASC, priority_score DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_job(r) for r in rows]

    def get_all_jobs(self, limit: int = 500) -> list[Job]:
        rows = self._conn.execute(
            "SELECT * FROM jobs ORDER BY scraped_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._row_to_job(r) for r in rows]

    def job_exists(self, url: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM jobs WHERE url=?", (url,)
        ).fetchone()
        return row is not None

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> Job:
        d = dict(row)
        return Job(
            id=d["id"],
            url=d["url"],
            title=d["title"],
            company=d["company"],
            location=d.get("location"),
            description=d.get("description"),
            source=d["source"],
            ats_type=d.get("ats_type"),
            apply_url=d.get("apply_url"),
            priority_tier=d.get("priority_tier"),
            priority_score=d.get("priority_score"),
            priority_reason=d.get("priority_reason"),
            scraped_at=d["scraped_at"],
            status=d["status"],
        )

    # ──────────────────────────── Applications ────────────────────────────

    def insert_application(self, app: Application) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO applications
                (job_id, resume_path, cover_letter, applied_at, auto_mode, success, error_message)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                app.job_id, app.resume_path, app.cover_letter,
                app.applied_at, int(app.auto_mode), int(app.success),
                app.error_message,
            ),
        )
        self._conn.commit()

    def get_application(self, job_id: str) -> Optional[Application]:
        row = self._conn.execute(
            "SELECT * FROM applications WHERE job_id=?", (job_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        return Application(
            id=d["id"],
            job_id=d["job_id"],
            resume_path=d["resume_path"],
            cover_letter=d["cover_letter"],
            applied_at=d["applied_at"],
            auto_mode=bool(d["auto_mode"]),
            success=bool(d["success"]),
            error_message=d.get("error_message"),
        )

    # ──────────────────────────── Resume Cache ────────────────────────────

    def get_cached_resume(
        self, resume_path: str, resume_hash: str
    ) -> Optional[ResumeCache]:
        row = self._conn.execute(
            "SELECT * FROM resume_cache WHERE resume_path=? AND resume_hash=?",
            (resume_path, resume_hash),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        return ResumeCache(
            resume_path=d["resume_path"],
            resume_hash=d["resume_hash"],
            extracted_text=d["extracted_text"],
            summary=d.get("summary"),
            skills_json=d.get("skills_json"),
            cached_at=d["cached_at"],
        )

    def upsert_resume_cache(self, cache: ResumeCache) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO resume_cache
                (resume_path, resume_hash, extracted_text, summary, skills_json, cached_at)
            VALUES (?,?,?,?,?,?)
            """,
            (
                cache.resume_path, cache.resume_hash, cache.extracted_text,
                cache.summary, cache.skills_json, cache.cached_at,
            ),
        )
        self._conn.commit()

    def get_all_resume_caches(self) -> list[ResumeCache]:
        rows = self._conn.execute("SELECT * FROM resume_cache").fetchall()
        result = []
        for row in rows:
            d = dict(row)
            result.append(ResumeCache(
                resume_path=d["resume_path"],
                resume_hash=d["resume_hash"],
                extracted_text=d["extracted_text"],
                summary=d.get("summary"),
                skills_json=d.get("skills_json"),
                cached_at=d["cached_at"],
            ))
        return result

    def get_applied_jobs_with_apps(self) -> list[dict]:
        """Return joined job + application rows for all successfully applied jobs (for CSV export)."""
        rows = self._conn.execute(
            """
            SELECT j.company, j.title, j.url, j.priority_tier, j.priority_score,
                   a.applied_at, a.auto_mode, a.resume_path
            FROM applications a
            JOIN jobs j ON j.id = a.job_id
            WHERE a.success = 1
            ORDER BY a.applied_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    # ──────────────────────────── Stats ────────────────────────────

    def stats(self) -> dict:
        row = self._conn.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN status='applied' THEN 1 ELSE 0 END) as applied,
                SUM(CASE WHEN status='skipped' THEN 1 ELSE 0 END) as skipped,
                SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed
            FROM jobs
            """
        ).fetchone()
        return dict(row)
