"""Orchestrate the full application pipeline: resume → cover letter → submit."""
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright

from config.settings import settings
from job_agent.ai.client import AIClient
from job_agent.ai.cover_letter import generate_cover_letter
from job_agent.ai.resume_selector import select_resume
from job_agent.ai.resume_tailor import tailor
from job_agent.application.form_filler import GenericFormFiller
from job_agent.db.models import Application, Job
from job_agent.db.store import JobStore
from job_agent.export import export_csv
from job_agent.resumes.loader import list_resumes, load_resume
from job_agent.resumes.parser import parse_resume
from job_agent.resumes.renderer import render_pdf
from job_agent.scrapers.ats.greenhouse import GreenhouseSubmitter
from job_agent.scrapers.ats.lever import LeverSubmitter


class ApplicationResult:
    def __init__(
        self,
        success: bool,
        resume_path: Optional[Path] = None,
        cover_letter: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        self.success = success
        self.resume_path = resume_path
        self.cover_letter = cover_letter
        self.error = error


class Applicator:
    """End-to-end job application orchestrator."""

    def __init__(self, store: JobStore, client: AIClient) -> None:
        self.store = store
        self.client = client
        self.form_filler = GenericFormFiller(client)
        self._resume_caches = None  # Lazy-loaded

    def _get_resume_caches(self):
        if self._resume_caches is None:
            self._resume_caches = list_resumes(self.store)
        return self._resume_caches

    def prepare(self, job: Job) -> tuple[Path, str]:
        """
        Prepare application materials: select + tailor resume, generate cover letter.
        Returns (resume_path, cover_letter_text).
        The resume_path points to a freshly rendered tailored PDF when possible,
        or the original PDF as fallback.
        """
        resume_caches = self._get_resume_caches()
        if not resume_caches:
            raise ValueError(
                f"No resume PDFs found in {settings.resume_dir}. "
                "Please add at least one PDF file there."
            )

        # Select best base resume
        base_resume_path, _ = select_resume(job, resume_caches, self.client)

        # Load extracted text
        cache = load_resume(base_resume_path, self.store)
        resume_text = cache.extracted_text

        # Tailor skills + projects, render tailored PDF
        tailored_path = self._tailor_and_render(base_resume_path, resume_text, job)
        resume_path = tailored_path or base_resume_path

        # Generate cover letter from the base resume text
        cover_letter = generate_cover_letter(job, resume_text, self.client)

        return resume_path, cover_letter

    def _tailor_and_render(
        self, base_pdf: Path, resume_text: str, job: Job
    ) -> Optional[Path]:
        """
        Parse resume → tailor skills+projects for job → render tailored PDF.
        Returns path to tailored PDF, or None on any error (caller falls back to original).
        """
        try:
            resume_data = parse_resume(base_pdf, resume_text, self.client)
            tailored_skills, tailored_projects = tailor(resume_data, job, self.client)

            output_path = (
                settings.resume_dir / "tailored" / f"{job.id}_{base_pdf.stem}.pdf"
            )
            render_pdf(resume_data, tailored_skills, tailored_projects, output_path)
            return output_path
        except Exception as e:
            print(f"[applicator] Resume tailoring failed, using original: {e}")
            return None

    async def apply(
        self,
        job: Job,
        auto_mode: bool = False,
        dry_run: bool = False,
        pre_generated: Optional[tuple[Path, str]] = None,
    ) -> ApplicationResult:
        """
        Apply to a job. If pre_generated is (resume_path, cover_letter), skips
        the preparation step.
        """
        if pre_generated:
            resume_path, cover_letter = pre_generated
        else:
            try:
                resume_path, cover_letter = self.prepare(job)
            except Exception as e:
                return ApplicationResult(success=False, error=str(e))

        apply_url = job.apply_url or job.url
        ats_type = job.ats_type

        success = False
        error_msg = None

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )
            )
            page = await context.new_page()

            try:
                if ats_type == "greenhouse":
                    submitter = GreenhouseSubmitter()
                    success, error_msg = await submitter.apply(
                        page, apply_url, resume_path, cover_letter, dry_run=dry_run
                    )
                elif ats_type == "lever":
                    submitter = LeverSubmitter()
                    success, error_msg = await submitter.apply(
                        page, apply_url, resume_path, cover_letter, dry_run=dry_run
                    )
                else:
                    # Generic form filler for unknown ATS
                    success, error_msg = await self.form_filler.apply(
                        page, apply_url, resume_path, cover_letter, job, dry_run=dry_run
                    )
            except Exception as e:
                success = False
                error_msg = str(e)
            finally:
                await context.close()
                await browser.close()

        # Record result in DB
        if not dry_run:
            final_status = "applied" if success else "failed"
            self.store.update_job_status(job.id, final_status)

            app = Application(
                job_id=job.id,
                resume_path=str(resume_path),
                cover_letter=cover_letter,
                applied_at=datetime.now(timezone.utc).isoformat(),
                auto_mode=auto_mode,
                success=success,
                error_message=error_msg,
            )
            self.store.insert_application(app)

            # Keep CSV in sync after every application
            try:
                export_csv(self.store)
            except Exception:
                pass

        return ApplicationResult(
            success=success,
            resume_path=resume_path,
            cover_letter=cover_letter,
            error=error_msg,
        )

    def apply_sync(
        self,
        job: Job,
        auto_mode: bool = False,
        dry_run: bool = False,
        pre_generated: Optional[tuple[Path, str]] = None,
    ) -> ApplicationResult:
        """Synchronous wrapper around apply()."""
        return asyncio.run(self.apply(job, auto_mode, dry_run, pre_generated))
