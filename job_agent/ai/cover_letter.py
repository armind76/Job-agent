"""Generate tailored cover letters using Claude."""
from job_agent.ai.client import AIClient
from job_agent.db.models import Job


_SYSTEM = """You are a professional cover letter writer specializing in technical roles.
Write a concise, tailored cover letter for a software engineering job application.

Requirements:
- Keep it under 250 words
- Do NOT include a salutation or sign-off (the user will add their name)
- Start directly with a compelling opening sentence
- Highlight the most relevant technical skills from the resume that match the job
- Show genuine interest in the specific company/role
- Do NOT use generic filler phrases like "I am writing to apply for..."
- Use active voice and specific technical language
- Do NOT fabricate experience not in the resume
- Output plain text only — no markdown, no headers"""


def generate_cover_letter(
    job: Job,
    resume_text: str,
    client: AIClient,
) -> str:
    """Generate a tailored cover letter for a job application."""
    desc_snippet = (job.description or "")[:3000]
    resume_snippet = resume_text[:4000]

    prompt = f"""Job Title: {job.title}
Company: {job.company}
Location: {job.location or 'New York, NY'}

Job Description:
{desc_snippet}

Candidate Resume:
{resume_snippet}

Write the cover letter body (no salutation, no sign-off)."""

    return client.complete(prompt, system=_SYSTEM, max_tokens=400)
