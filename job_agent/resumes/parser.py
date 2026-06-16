"""
Parse raw PDF text into structured ResumeData using Claude.
Result is cached as JSON next to the PDF so it only runs once.
"""
import json
import re
from pathlib import Path

from job_agent.ai.client import AIClient
from job_agent.resumes.schema import (
    EducationItem,
    ExperienceItem,
    ProjectItem,
    ResumeData,
)

_SYSTEM = """You are a resume parser. Given the plain-text content of a resume, extract every piece of
information into the JSON schema below. Be thorough — capture ALL bullets, ALL projects, ALL skills.
Do not summarise or drop content.

Return ONLY a valid JSON object matching this exact schema (no markdown fences):
{
  "name": "",
  "email": "",
  "phone": "",
  "location": "",
  "linkedin": "",
  "github": "",
  "portfolio": "",
  "summary": "",
  "skills": ["skill1", "skill2", ...],
  "experience": [
    {
      "company": "",
      "title": "",
      "dates": "",
      "location": "",
      "bullets": ["...", "..."]
    }
  ],
  "projects": [
    {
      "name": "",
      "description": "one-line summary of what the project does",
      "technologies": ["tech1", "tech2"],
      "url": "",
      "bullets": ["...", "..."]
    }
  ],
  "education": [
    {
      "institution": "",
      "degree": "",
      "dates": "",
      "details": ["...", "..."]
    }
  ]
}"""


def _cache_path(pdf_path: Path) -> Path:
    return pdf_path.parent / "parsed" / f"{pdf_path.stem}.json"


def parse_resume(pdf_path: Path, extracted_text: str, client: AIClient) -> ResumeData:
    """
    Parse a resume PDF into ResumeData. Returns cached result if available.
    Cache is stored at data/resumes/parsed/<stem>.json.
    """
    cache = _cache_path(pdf_path)
    if cache.exists():
        return _from_json(json.loads(cache.read_text()))

    prompt = f"Parse this resume:\n\n{extracted_text[:12000]}"
    raw = client.complete(prompt, system=_SYSTEM, max_tokens=4096)

    # Strip markdown fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw)

    data = json.loads(raw)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data, indent=2))

    return _from_json(data)


def _from_json(d: dict) -> ResumeData:
    experience = [
        ExperienceItem(
            company=e.get("company", ""),
            title=e.get("title", ""),
            dates=e.get("dates", ""),
            location=e.get("location", ""),
            bullets=e.get("bullets", []),
        )
        for e in d.get("experience", [])
    ]
    projects = [
        ProjectItem(
            name=p.get("name", ""),
            description=p.get("description", ""),
            technologies=p.get("technologies", []),
            url=p.get("url", ""),
            bullets=p.get("bullets", []),
        )
        for p in d.get("projects", [])
    ]
    education = [
        EducationItem(
            institution=e.get("institution", ""),
            degree=e.get("degree", ""),
            dates=e.get("dates", ""),
            details=e.get("details", []),
        )
        for e in d.get("education", [])
    ]
    return ResumeData(
        name=d.get("name", ""),
        email=d.get("email", ""),
        phone=d.get("phone", ""),
        location=d.get("location", ""),
        linkedin=d.get("linkedin", ""),
        github=d.get("github", ""),
        portfolio=d.get("portfolio", ""),
        summary=d.get("summary", ""),
        skills=d.get("skills", []),
        experience=experience,
        projects=projects,
        education=education,
    )
