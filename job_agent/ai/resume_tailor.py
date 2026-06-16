"""
Tailor the Projects and Skills sections of a resume to a specific job.
Only selects/reorders from what exists — never invents new content.
"""
import json
import re
from dataclasses import asdict

from job_agent.ai.client import AIClient
from job_agent.db.models import Job
from job_agent.resumes.schema import ProjectItem, ResumeData

_MAX_PROJECTS = 4   # max projects to show on tailored resume


_SYSTEM = """You are a resume tailoring assistant. Your job is to select and reorder existing resume
content to best match a job posting. You must ONLY use content that already exists — never add,
invent, or rewrite anything.

Return ONLY a valid JSON object (no markdown):
{
  "skills": ["skill1", "skill2", ...],
  "project_names": ["ProjectA", "ProjectB", ...]
}

Rules:
- "skills": return ALL skills from the candidate's list, but reordered so the most relevant to this
  job appear first. Keep the full list — do not drop skills.
- "project_names": choose up to """ + str(_MAX_PROJECTS) + """ project names from the candidate's
  project list that best match the job. Use the exact project names provided. Order by relevance
  (most relevant first)."""


def tailor(
    resume: ResumeData,
    job: Job,
    client: AIClient,
) -> tuple[list[str], list[ProjectItem]]:
    """
    Returns (tailored_skills, tailored_projects) selected from the resume's pool.
    Falls back to original order if Claude fails.
    """
    if not resume.skills and not resume.projects:
        return resume.skills, resume.projects

    # Build project index for quick lookup
    project_index = {p.name: p for p in resume.projects}

    projects_desc = json.dumps(
        [{"name": p.name, "description": p.description, "technologies": p.technologies}
         for p in resume.projects],
        indent=2,
    )

    prompt = f"""Job Title: {job.title}
Company: {job.company}

Job Description (excerpt):
{(job.description or '')[:2500]}

Candidate's current skills (full list):
{json.dumps(resume.skills)}

Candidate's projects (full pool):
{projects_desc}

Select and reorder skills + pick the best projects for this job."""

    try:
        raw = client.complete(prompt, system=_SYSTEM, max_tokens=512)
        raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)

        tailored_skills: list[str] = data.get("skills", resume.skills)
        chosen_names: list[str] = data.get("project_names", [p.name for p in resume.projects])

        # Preserve full ProjectItem objects in chosen order
        tailored_projects = [
            project_index[name]
            for name in chosen_names
            if name in project_index
        ]
        # Fallback: if Claude returned names we don't recognise, keep originals
        if not tailored_projects:
            tailored_projects = resume.projects[:_MAX_PROJECTS]

        return tailored_skills, tailored_projects

    except (json.JSONDecodeError, KeyError):
        # Safe fallback: original order, capped projects
        return resume.skills, resume.projects[:_MAX_PROJECTS]
