"""Greenhouse ATS form submitter."""
import asyncio
from pathlib import Path
from typing import Optional

from playwright.async_api import Page

from config.settings import settings


class GreenhouseSubmitter:
    """Fills and submits Greenhouse job application forms."""

    async def apply(
        self,
        page: Page,
        apply_url: str,
        resume_path: Path,
        cover_letter: str,
        dry_run: bool = False,
    ) -> tuple[bool, Optional[str]]:
        """
        Navigate to a Greenhouse apply URL and submit the application.
        Returns (success, error_message).
        """
        try:
            await page.goto(apply_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            # Fill standard fields
            await self._fill_field(page, 'input[id*="first_name"], input[name*="first_name"]',
                                   settings.user_full_name.split()[0])
            await self._fill_field(page, 'input[id*="last_name"], input[name*="last_name"]',
                                   settings.user_full_name.split()[-1])
            await self._fill_field(page, 'input[id*="email"], input[type="email"]', settings.user_email)
            await self._fill_field(page, 'input[id*="phone"], input[type="tel"]', settings.user_phone)

            # LinkedIn URL
            await self._fill_field(page, 'input[id*="linkedin"], input[placeholder*="LinkedIn"]',
                                   settings.user_linkedin_url)

            # Resume upload
            resume_input = await page.query_selector('input[type="file"][id*="resume"], input[type="file"][name*="resume"]')
            if resume_input:
                await resume_input.set_input_files(str(resume_path))
                await asyncio.sleep(1)

            # Cover letter — try text area first, then file upload
            cl_textarea = await page.query_selector(
                'textarea[id*="cover_letter"], textarea[name*="cover_letter"], '
                'textarea[placeholder*="cover letter"]'
            )
            if cl_textarea:
                await cl_textarea.fill(cover_letter)
            else:
                cl_file_input = await page.query_selector('input[type="file"][id*="cover_letter"]')
                if cl_file_input:
                    # Save cover letter to temp file
                    import tempfile
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                        f.write(cover_letter)
                        tmp_path = f.name
                    await cl_file_input.set_input_files(tmp_path)

            # Fill any remaining required fields that are empty
            await self._fill_optional_fields(page)

            if dry_run:
                fields = await self._log_form_fields(page)
                print("[greenhouse][dry-run] Form fields:")
                for name, value in fields.items():
                    print(f"  {name}: {value[:80] if value else '(empty)'}")
                return True, None

            # Submit
            submit_btn = await page.query_selector(
                'button[type="submit"], input[type="submit"], button[id*="submit"]'
            )
            if submit_btn:
                await submit_btn.click()
                await asyncio.sleep(3)

                # Check for success
                success_el = await page.query_selector(
                    '[class*="success"], [class*="confirmation"], h1:has-text("Thank you")'
                )
                if success_el:
                    return True, None

                # Check for errors
                error_el = await page.query_selector('[class*="error"], [role="alert"]')
                if error_el:
                    error_text = await error_el.inner_text()
                    return False, error_text.strip()

                return True, None  # Assume success if no explicit confirmation
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
                await asyncio.sleep(0.3)
        except Exception:
            pass

    @staticmethod
    async def _fill_optional_fields(page: Page) -> None:
        """Fill location, website, and other common optional fields."""
        optional_map = {
            'input[id*="location"], input[placeholder*="Location"]': settings.user_location,
            'input[id*="website"], input[placeholder*="Website"], input[id*="portfolio"]': settings.user_portfolio_url,
            'input[id*="github"]': settings.user_github_url,
        }
        for selector, value in optional_map.items():
            if value:
                try:
                    el = await page.query_selector(selector)
                    if el:
                        await el.fill(value)
                        await asyncio.sleep(0.2)
                except Exception:
                    pass

    @staticmethod
    async def _log_form_fields(page: Page) -> dict:
        """Extract all form field names and current values for dry-run logging."""
        fields = {}
        try:
            inputs = await page.query_selector_all('input:not([type="hidden"]):not([type="submit"]), textarea, select')
            for inp in inputs:
                name = await inp.get_attribute("name") or await inp.get_attribute("id") or "?"
                value = await inp.input_value() if await inp.get_attribute("type") != "file" else "(file)"
                fields[name] = value
        except Exception:
            pass
        return fields
