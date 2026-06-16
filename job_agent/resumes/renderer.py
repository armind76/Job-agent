"""Render a ResumeData (with tailored skills/projects) to a PDF via Jinja2 + weasyprint."""
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from job_agent.resumes.schema import ProjectItem, ResumeData

_TEMPLATE_DIR = Path(__file__).parent / "template"


def render_pdf(
    resume: ResumeData,
    tailored_skills: list[str],
    tailored_projects: list[ProjectItem],
    output_path: Path,
) -> Path:
    """
    Render a tailored resume PDF.

    Only `tailored_skills` and `tailored_projects` are substituted — every
    other section (header, summary, experience, education) comes from `resume`
    unchanged.

    Returns the output_path.
    """
    try:
        from weasyprint import HTML, CSS
    except ImportError:
        raise RuntimeError(
            "weasyprint is not installed. Run: pip install weasyprint\n"
            "Also requires system libs: pango, cairo, gdk-pixbuf2 (see weasyprint docs)."
        )

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=False,
    )
    template = env.get_template("resume.html.j2")

    css_path = (_TEMPLATE_DIR / "resume.css").as_uri()

    html_content = template.render(
        resume=resume,
        skills=tailored_skills,
        projects=tailored_projects,
        css_path=css_path,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html_content).write_pdf(
        str(output_path),
        stylesheets=[CSS(filename=str(_TEMPLATE_DIR / "resume.css"))],
    )
    return output_path
