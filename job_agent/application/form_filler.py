"""Claude-driven generic form filler for unknown ATS systems."""
import asyncio
import json
import re
from pathlib import Path
from typing import Optional

from playwright.async_api import Page

from config.settings import settings
from job_agent.ai.client import AIClient
from job_agent.db.models import Job


_SYSTEM = """You are a form-filling assistant. Given a description of form fields on a job application page,
return a JSON object mapping field name/id to the value that should be entered.

User profile available:
- full_name: {full_name}
- email: {email}
- phone: {phone}
- location: {location}
- linkedin: {linkedin}
- github: {github}
- portfolio: {portfolio}

Rules:
- Only fill fields that have a clear mapping to the user's information
- For fields you cannot determine, return null
- For select dropdowns, use the most appropriate option value
- Do NOT invent information not in the profile
- Return ONLY the JSON object, no extra text

Example output:
{{"first_name": "Jane", "email": "jane@example.com", "location": "New York, NY"}}"""


class GenericFormFiller:
    """Uses Claude to intelligently fill job application forms for unknown ATS."""

    def __init__(self, client: AIClient) -> None:
        self.client = client

    async def apply(
        self,
        page: Page,
        apply_url: str,
        resume_path: Path,
        cover_letter: str,
        job: Job,
        dry_run: bool = False,
    ) -> tuple[bool, Optional[str]]:
        """
        Navigate to an apply URL and use Claude to fill the form.
        Returns (success, error_message).
        """
        try:
            await page.goto(apply_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            # Extract form structure
            form_fields = await self._extract_form_fields(page)
            if not form_fields:
                return False, "No form fields found on page"

            # Ask Claude how to fill them
            fill_map = await self._get_fill_map(form_fields, job)

            # Fill the fields
            filled_count = 0
            for field_id, value in fill_map.items():
                if value is None:
                    continue
                success = await self._fill_field_by_id(page, field_id, value)
                if success:
                    filled_count += 1

            # Upload resume
            await self._upload_resume(page, resume_path)

            # Fill cover letter
            await self._fill_cover_letter(page, cover_letter)

            if dry_run:
                print(f"[generic-form][dry-run] Filled {filled_count}/{len(fill_map)} fields")
                print(f"[generic-form][dry-run] Fill map: {json.dumps(fill_map, indent=2)}")
                return True, None

            # Submit
            submit_btn = await page.query_selector(
                'button[type="submit"], input[type="submit"], '
                'button:has-text("Submit"), button:has-text("Apply")'
            )
            if submit_btn:
                await submit_btn.click()
                await asyncio.sleep(3)
                return True, None
            else:
                return False, "Could not find submit button"

        except Exception as e:
            return False, str(e)

    async def _extract_form_fields(self, page: Page) -> list[dict]:
        """Extract all visible form fields from the page."""
        fields = []
        try:
            inputs = await page.query_selector_all(
                'input:not([type="hidden"]):not([type="submit"]):not([type="button"]), '
                'textarea, select'
            )
            for inp in inputs:
                field_id = await inp.get_attribute("id") or ""
                field_name = await inp.get_attribute("name") or ""
                field_type = await inp.get_attribute("type") or "text"
                placeholder = await inp.get_attribute("placeholder") or ""
                label_text = ""

                # Try to find associated label
                if field_id:
                    label = await page.query_selector(f'label[for="{field_id}"]')
                    if label:
                        label_text = await label.inner_text()

                fields.append({
                    "id": field_id,
                    "name": field_name,
                    "type": field_type,
                    "placeholder": placeholder,
                    "label": label_text.strip(),
                })
        except Exception as e:
            print(f"[generic-form] Field extraction error: {e}")

        return fields

    async def _get_fill_map(self, form_fields: list[dict], job: Job) -> dict:
        """Ask Claude to map form fields to user profile values."""
        system = _SYSTEM.format(
            full_name=settings.user_full_name,
            email=settings.user_email,
            phone=settings.user_phone,
            location=settings.user_location,
            linkedin=settings.user_linkedin_url,
            github=settings.user_github_url,
            portfolio=settings.user_portfolio_url,
        )

        fields_desc = json.dumps(form_fields, indent=2)
        prompt = f"""Application form for: {job.title} at {job.company}

Form fields found on the page:
{fields_desc}

Return a JSON object mapping field id (or name if no id) to the value to enter.
Use the user profile information provided in the system prompt."""

        try:
            response = self.client.complete(prompt, system=system, max_tokens=512)
            match = re.search(r'\{[^{}]+\}', response, re.DOTALL)
            return json.loads(match.group() if match else response)
        except (json.JSONDecodeError, AttributeError):
            return {}

    @staticmethod
    async def _fill_field_by_id(page: Page, field_id: str, value: str) -> bool:
        """Fill a field by id or name attribute."""
        try:
            el = await page.query_selector(f'#{field_id}') or await page.query_selector(f'[name="{field_id}"]')
            if el:
                tag = await el.evaluate("el => el.tagName.toLowerCase()")
                if tag == "select":
                    await el.select_option(label=value)
                else:
                    await el.fill(str(value))
                await asyncio.sleep(0.1)
                return True
        except Exception:
            pass
        return False

    @staticmethod
    async def _upload_resume(page: Page, resume_path: Path) -> None:
        try:
            file_input = await page.query_selector('input[type="file"]')
            if file_input:
                await file_input.set_input_files(str(resume_path))
                await asyncio.sleep(1)
        except Exception as e:
            print(f"[generic-form] Resume upload error: {e}")

    @staticmethod
    async def _fill_cover_letter(page: Page, cover_letter: str) -> None:
        try:
            cl_area = await page.query_selector(
                'textarea[name*="cover"], textarea[id*="cover"], '
                'textarea[placeholder*="cover"], textarea[placeholder*="letter"]'
            )
            if cl_area:
                await cl_area.fill(cover_letter)
        except Exception as e:
            print(f"[generic-form] Cover letter fill error: {e}")
