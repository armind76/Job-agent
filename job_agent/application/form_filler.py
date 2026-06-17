"""Claude-driven generic form filler for unknown ATS systems with multi-page support."""
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
    """Uses Claude to fill job application forms for unknown ATS, page by page."""

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
        try:
            await page.goto(apply_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            # If we land on a listing page with no form, click through to the apply page
            form_fields = await self._extract_form_fields(page)
            if not form_fields:
                form_fields = await self._click_through_to_form(page)
            if not form_fields:
                return False, "No form fields found on page"

            resume_uploaded = False
            cover_letter_filled = False

            # ── Multi-page loop ──────────────────────────────────────────────
            for page_num in range(1, 11):
                print(f"[generic-form] Page {page_num} — {page.url[:80]}")

                # Extract and fill fields on this page
                form_fields = await self._extract_form_fields(page)
                if form_fields:
                    fill_map = await self._get_fill_map(form_fields, job)
                    filled = 0
                    for field_id, value in fill_map.items():
                        if value is None:
                            continue
                        if await self._fill_field_by_id(page, field_id, value):
                            filled += 1
                    if dry_run:
                        print(f"[generic-form][dry-run] Page {page_num}: "
                              f"filled {filled}/{len(fill_map)} fields")
                        print(f"[generic-form][dry-run] Fill map: {json.dumps(fill_map, indent=2)}")

                # Upload resume once
                if not resume_uploaded:
                    resume_uploaded = await self._upload_resume(page, resume_path)

                # Fill cover letter once
                if not cover_letter_filled:
                    cover_letter_filled = await self._fill_cover_letter(page, cover_letter)

                # Check for Next/Continue button
                next_btn = await self._find_next_button(page)
                if next_btn:
                    print(f"[generic-form] Page {page_num} → Next")
                    if dry_run:
                        print(f"[generic-form][dry-run] Would click Next on page {page_num}")
                        return True, None
                    await next_btn.scroll_into_view_if_needed()
                    await asyncio.sleep(0.3)
                    try:
                        await next_btn.click(timeout=8000)
                    except Exception:
                        await page.evaluate("el => el.click()", next_btn)
                    await asyncio.sleep(2)
                    continue

                # No Next — try Submit
                if dry_run:
                    print(f"[generic-form][dry-run] Page {page_num} → would click Submit")
                    return True, None

                clicked, err = await self._click_submit(page)
                if clicked:
                    await asyncio.sleep(3)
                    return True, None
                return False, err

            return False, "Exceeded maximum page count (10)"

        except Exception as e:
            return False, str(e)

    # ── Navigation helpers ───────────────────────────────────────────────────

    @staticmethod
    async def _find_next_button(page: Page):
        """Return a Next/Continue button (not Submit)."""
        selectors = [
            'button:has-text("Next")',
            'button:has-text("Continue")',
            'button:has-text("Next Step")',
            'button:has-text("Next Page")',
            'button:has-text("Proceed")',
            'a:has-text("Next")',
            'a:has-text("Continue")',
            '[data-testid*="next-btn"]',
            '[aria-label="Next step"]',
        ]
        for selector in selectors:
            try:
                el = await page.query_selector(selector)
                if el:
                    text = (await el.inner_text()).lower().strip()
                    if not any(w in text for w in ["submit", "send application", "apply"]):
                        return el
            except Exception:
                continue
        return None

    @staticmethod
    async def _click_submit(page: Page) -> tuple[bool, str | None]:
        selectors = [
            'button[type="submit"]',
            'input[type="submit"]',
            'button:has-text("Submit Application")',
            'button:has-text("Submit application")',
            'button:has-text("Submit")',
            'button:has-text("Apply Now")',
            'button:has-text("Apply")',
            'button:has-text("Send Application")',
            '[data-qa="btn-submit"]',
            '[data-testid*="submit"]',
        ]
        for selector in selectors:
            try:
                el = await page.query_selector(selector)
                if el:
                    await el.scroll_into_view_if_needed()
                    await asyncio.sleep(0.4)
                    try:
                        await el.click(timeout=8000)
                    except Exception:
                        await page.evaluate("el => el.click()", el)
                    return True, None
            except Exception:
                continue
        return False, "Could not find submit button"

    async def _click_through_to_form(self, page: Page) -> list[dict]:
        """When on a listing page with no form, click through to the apply page."""
        cta_selectors = [
            'a:has-text("Apply Now")',
            'a:has-text("Apply for Job")',
            'a:has-text("Apply for this job")',
            'button:has-text("Apply Now")',
            'a[class*="apply"]',
            '[data-testid*="apply"]',
        ]
        for selector in cta_selectors:
            try:
                btn = await page.query_selector(selector)
                if not btn:
                    continue
                try:
                    async with page.context.expect_page(timeout=5000) as new_page_info:
                        await btn.click()
                    new_page = await new_page_info.value
                    await new_page.wait_for_load_state("domcontentloaded", timeout=15000)
                    await asyncio.sleep(2)
                    fields = await self._extract_form_fields(new_page)
                    if fields:
                        await page.goto(new_page.url, wait_until="domcontentloaded", timeout=20000)
                        await asyncio.sleep(1)
                        return await self._extract_form_fields(page)
                except Exception:
                    await page.wait_for_load_state("domcontentloaded", timeout=15000)
                    await asyncio.sleep(2)
                    fields = await self._extract_form_fields(page)
                    if fields:
                        return fields
            except Exception:
                continue
        return []

    # ── Form field helpers ───────────────────────────────────────────────────

    async def _extract_form_fields(self, page: Page) -> list[dict]:
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
        prompt = (
            f"Application form for: {job.title} at {job.company}\n\n"
            f"Form fields found on the page:\n{fields_desc}\n\n"
            "Return a JSON object mapping field id (or name if no id) to the value to enter."
        )
        try:
            response = self.client.complete(prompt, system=system, max_tokens=512)
            match = re.search(r'\{[^{}]+\}', response, re.DOTALL)
            return json.loads(match.group() if match else response)
        except (json.JSONDecodeError, AttributeError):
            return {}

    @staticmethod
    async def _fill_field_by_id(page: Page, field_id: str, value: str) -> bool:
        try:
            el = (
                await page.query_selector(f'#{field_id}')
                or await page.query_selector(f'[name="{field_id}"]')
            )
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
    async def _upload_resume(page: Page, resume_path: Path) -> bool:
        try:
            file_input = await page.query_selector('input[type="file"]')
            if file_input:
                await file_input.set_input_files(str(resume_path))
                await asyncio.sleep(1)
                return True
        except Exception as e:
            print(f"[generic-form] Resume upload error: {e}")
        return False

    @staticmethod
    async def _fill_cover_letter(page: Page, cover_letter: str) -> bool:
        try:
            cl_area = await page.query_selector(
                'textarea[name*="cover"], textarea[id*="cover"], '
                'textarea[placeholder*="cover"], textarea[placeholder*="letter"]'
            )
            if cl_area:
                await cl_area.fill(cover_letter)
                return True
        except Exception as e:
            print(f"[generic-form] Cover letter fill error: {e}")
        return False
