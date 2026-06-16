"""Lever ATS form submitter."""
import asyncio
import tempfile
from pathlib import Path
from typing import Optional

from playwright.async_api import Page

from config.settings import settings


class LeverSubmitter:
    """Fills and submits Lever job application forms."""

    async def apply(
        self,
        page: Page,
        apply_url: str,
        resume_path: Path,
        cover_letter: str,
        dry_run: bool = False,
    ) -> tuple[bool, Optional[str]]:
        """
        Navigate to a Lever apply URL and submit the application.
        Returns (success, error_message).
        """
        try:
            # Lever's apply URL is typically /apply appended to the job URL
            if not apply_url.endswith("/apply"):
                apply_url = apply_url.rstrip("/") + "/apply"

            await page.goto(apply_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            # Lever standard fields
            await self._fill_field(page, 'input[name="name"]', settings.user_full_name)
            await self._fill_field(page, 'input[name="email"]', settings.user_email)
            await self._fill_field(page, 'input[name="phone"]', settings.user_phone)
            await self._fill_field(page, 'input[name="org"]', "")  # Current company (optional)
            await self._fill_field(page, 'input[name="linkedin"]', settings.user_linkedin_url)
            await self._fill_field(page, 'input[name="github"]', settings.user_github_url)
            await self._fill_field(page, 'input[name="portfolio"]', settings.user_portfolio_url)

            # Resume upload
            resume_input = await page.query_selector('input[type="file"][name="resume"], input[type="file"][id*="resume"]')
            if resume_input:
                await resume_input.set_input_files(str(resume_path))
                await asyncio.sleep(1)
            else:
                # Try drag-and-drop area
                upload_area = await page.query_selector('[class*="upload"], [class*="dropzone"]')
                if upload_area:
                    file_input = await page.query_selector('input[type="file"]')
                    if file_input:
                        await file_input.set_input_files(str(resume_path))

            # Cover letter
            cl_textarea = await page.query_selector('textarea[name="comments"], textarea[placeholder*="cover"]')
            if cl_textarea:
                await cl_textarea.fill(cover_letter)
            else:
                # Lever sometimes has a rich text editor
                cl_div = await page.query_selector('[contenteditable="true"][class*="cover"], [class*="cover-letter"] [contenteditable]')
                if cl_div:
                    await cl_div.click()
                    await page.keyboard.press("Control+a")
                    await page.keyboard.type(cover_letter)

            # Fill custom questions (best-effort)
            await self._fill_custom_questions(page)

            if dry_run:
                fields = await self._log_form_fields(page)
                print("[lever][dry-run] Form fields:")
                for name, value in fields.items():
                    print(f"  {name}: {value[:80] if value else '(empty)'}")
                return True, None

            # Submit
            submit_btn = await page.query_selector(
                'button[type="submit"], input[type="submit"], '
                'button:has-text("Submit application"), button:has-text("Apply")'
            )
            if submit_btn:
                await submit_btn.click()
                await asyncio.sleep(4)

                # Check for confirmation
                success_el = await page.query_selector(
                    '[class*="success"], [class*="confirmation"], '
                    'h2:has-text("Application submitted"), p:has-text("Thank you")'
                )
                if success_el:
                    return True, None

                # Check for errors
                error_el = await page.query_selector('[class*="error"], .field-error')
                if error_el:
                    error_text = await error_el.inner_text()
                    return False, error_text.strip()

                return True, None
            else:
                return False, "Could not find submit button"

        except Exception as e:
            return False, str(e)

    @staticmethod
    async def _fill_field(page: Page, selector: str, value: str) -> None:
        if not value:
            return
        try:
            el = await page.query_selector(selector)
            if el:
                await el.clear()
                await el.fill(value)
                await asyncio.sleep(0.2)
        except Exception:
            pass

    @staticmethod
    async def _fill_custom_questions(page: Page) -> None:
        """Attempt to fill visible required text inputs that are empty."""
        try:
            inputs = await page.query_selector_all('input[required]:not([type="file"]), textarea[required]')
            for inp in inputs:
                current_val = await inp.input_value()
                if not current_val:
                    placeholder = await inp.get_attribute("placeholder") or ""
                    if "location" in placeholder.lower():
                        await inp.fill(settings.user_location)
        except Exception:
            pass

    @staticmethod
    async def _log_form_fields(page: Page) -> dict:
        fields = {}
        try:
            inputs = await page.query_selector_all('input:not([type="hidden"]):not([type="submit"]), textarea, select')
            for inp in inputs:
                name = await inp.get_attribute("name") or await inp.get_attribute("id") or "?"
                inp_type = await inp.get_attribute("type") or "text"
                value = await inp.input_value() if inp_type != "file" else "(file)"
                fields[name] = value
        except Exception:
            pass
        return fields
