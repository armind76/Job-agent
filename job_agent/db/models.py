from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Job:
    url: str
    title: str
    company: str
    source: str  # linkedin|indeed|glassdoor|builtin|greenhouse|lever
    id: str = ""  # SHA256(url+title+company)[:16] — set by store
    location: Optional[str] = None
    description: Optional[str] = None
    ats_type: Optional[str] = None   # greenhouse|lever|workday|None
    apply_url: Optional[str] = None
    priority_tier: Optional[int] = None   # 1–4
    priority_score: Optional[float] = None  # 0.0–1.0
    priority_reason: Optional[str] = None
    scraped_at: str = field(default_factory=lambda: _now())
    status: str = "pending"  # pending|skipped|applied|failed

    def __post_init__(self) -> None:
        if not self.id:
            import hashlib
            raw = f"{self.url}{self.title}{self.company}"
            self.id = hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class Application:
    job_id: str
    resume_path: str
    cover_letter: str
    applied_at: str = field(default_factory=lambda: _now())
    auto_mode: bool = False
    success: bool = False
    error_message: Optional[str] = None
    id: Optional[int] = None


@dataclass
class ResumeCache:
    resume_path: str
    resume_hash: str
    extracted_text: str
    summary: Optional[str] = None
    skills_json: Optional[str] = None  # JSON array string
    cached_at: str = field(default_factory=lambda: _now())
