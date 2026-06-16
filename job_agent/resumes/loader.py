"""PDF resume loader with SQLite caching."""
import hashlib
import json
from pathlib import Path
from typing import Optional

import pdfplumber

from config.settings import settings
from job_agent.db.models import ResumeCache
from job_agent.db.store import JobStore


def _hash_file(path: Path) -> str:
    h = hashlib.md5()
    h.update(path.read_bytes())
    return h.hexdigest()


def extract_text(pdf_path: Path) -> str:
    """Extract plain text from a PDF using pdfplumber."""
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
    return "\n\n".join(pages)


def load_resume(
    pdf_path: Path,
    store: JobStore,
    ai_client=None,  # optional: job_agent.ai.client.AIClient
) -> ResumeCache:
    """
    Load resume PDF, returning cached ResumeCache if unchanged.
    If ai_client provided and no cache, generates summary + skills via Claude.
    """
    pdf_path = Path(pdf_path).resolve()
    file_hash = _hash_file(pdf_path)

    cached = store.get_cached_resume(str(pdf_path), file_hash)
    if cached:
        return cached

    text = extract_text(pdf_path)
    summary: Optional[str] = None
    skills_json: Optional[str] = None

    if ai_client:
        summary, skills = _analyze_resume(ai_client, text)
        skills_json = json.dumps(skills)

    cache = ResumeCache(
        resume_path=str(pdf_path),
        resume_hash=file_hash,
        extracted_text=text,
        summary=summary,
        skills_json=skills_json,
    )
    store.upsert_resume_cache(cache)
    return cache


def _analyze_resume(ai_client, text: str) -> tuple[str, list[str]]:
    """Use Claude to generate a brief summary and extract skills list."""
    prompt = f"""Analyze this resume and return a JSON object with exactly two keys:
- "summary": a 2-3 sentence professional summary emphasizing technical strengths
- "skills": a JSON array of technical skills (languages, frameworks, tools, domains)

Resume text:
{text[:8000]}

Return ONLY valid JSON, no markdown fences."""

    response = ai_client.complete(prompt, max_tokens=500)
    try:
        data = json.loads(response)
        return data.get("summary", ""), data.get("skills", [])
    except (json.JSONDecodeError, AttributeError):
        return "", []


def list_resumes(store: Optional[JobStore] = None) -> list[ResumeCache]:
    """Return all resumes from the resume directory, loading/caching as needed."""
    resume_dir = settings.resume_dir
    if not resume_dir.exists():
        return []

    pdfs = list(resume_dir.glob("*.pdf"))
    if not pdfs:
        return []

    if store is None:
        return []

    caches = []
    for pdf in pdfs:
        try:
            cache = load_resume(pdf, store)
            caches.append(cache)
        except Exception as e:
            print(f"Warning: could not load {pdf.name}: {e}")
    return caches
