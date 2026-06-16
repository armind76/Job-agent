"""Select the best resume PDF for a given job description."""
import json
import re
from pathlib import Path

from job_agent.ai.client import AIClient
from job_agent.db.models import Job, ResumeCache


_SYSTEM = """You are a career advisor helping select the best resume for a job application.
Given a job posting and a list of candidate resumes (with summaries and skills), choose the ONE
resume that best matches the job requirements.

Return a JSON object with exactly:
{
  "filename": "<resume filename only, no path>",
  "reason": "<1 sentence explaining why this resume is the best match>"
}

Return ONLY the JSON, no extra text."""


def select_resume(
    job: Job,
    resume_caches: list[ResumeCache],
    client: AIClient,
) -> tuple[Path, str]:
    """
    Returns (resume_path, reason) for the best resume for this job.
    Falls back to the first resume if only one is available or Claude fails.
    """
    if not resume_caches:
        raise ValueError("No resumes available in data/resumes/")

    if len(resume_caches) == 1:
        return Path(resume_caches[0].resume_path), "Only resume available"

    # Build resume summaries for Claude
    resume_list = []
    for rc in resume_caches:
        filename = Path(rc.resume_path).name
        skills = json.loads(rc.skills_json) if rc.skills_json else []
        summary = rc.summary or "(no summary)"
        resume_list.append(
            f"Filename: {filename}\nSummary: {summary}\nSkills: {', '.join(skills[:20])}"
        )

    resumes_text = "\n\n---\n\n".join(resume_list)
    desc_snippet = (job.description or "")[:2000]

    prompt = f"""Job Title: {job.title}
Company: {job.company}
Location: {job.location or 'Not specified'}

Job Description:
{desc_snippet}

Available Resumes:
{resumes_text}

Select the single best resume for this application."""

    try:
        response = client.complete(prompt, system=_SYSTEM, max_tokens=200)
        match = re.search(r'\{[^{}]+\}', response, re.DOTALL)
        data = json.loads(match.group() if match else response)

        filename = data.get("filename", "")
        reason = data.get("reason", "Best match")

        # Find the matching cache entry
        for rc in resume_caches:
            if Path(rc.resume_path).name == filename:
                return Path(rc.resume_path), reason

        # Fallback if filename doesn't match
        return Path(resume_caches[0].resume_path), "Fallback: first resume"

    except (json.JSONDecodeError, AttributeError):
        return Path(resume_caches[0].resume_path), "Fallback: first resume"
