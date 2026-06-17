"""Lever ATS form submitter."""
import asyncio
import tempfile
from pathlib import Path
from typing import Optional

from playwright.async_api import Page

from config.settings import settings


class LeverSubmitter:
    """Fills and submits Lever job application forms, handling multi-page flows."""

    async def apply(
        self,
        page: Page,
        apply_url: str,
        resume_path: Path,
        cover_letter: str,
        dry_run: bool = False,
    ) -> tuple[bool, Optional[str]]:
        try:
            if not apply_url.endswith("/apply"):
                apply_url = apply_url.rstrip("/") + "/apply"

            await page.goto(apply_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            # ── Page 1: fill all known standard fields ──────────────────────
            await self._fill_field(page, 'input[name="name"]', settings.user_full_name)
            await self._fill_field(page, 'input[name="email"]', settings.user_email)
            await self._fill_field(page, 'input[name="phone"]', settings.user_phone)
            await self._fill_field(page, 'input[name="org"]', "")
            await self._fill_field(page, 'input[name="linkedin"]', settings.user_linkedin_url)
            await self._fill_field(page, 'input[name="github"]', settings.user_github_url)
            await self._fill_field(page, 'input[name="portfolio"]', settings.user_portfolio_url)

            # Resume upload
            resume_input = await page.query_selector(
                'input[type="file"][name="resume"], input[type="file"][id*="resume"]'
            )
            if resume_input:
                await resume_input.set_input_files(str(resume_path))
                await asyncio.sleep(1)
            else:
                file_input = await page.query_selector('input[type="file"]')
                if file_input:
                    await file_input.set_input_files(str(resume_path))

            # Cover letter
            cl_textarea = await page.query_selector(
                'textarea[name="comments"], textarea[placeholder*="cover"]'
            )
            if cl_textarea:
                await cl_textarea.fill(cover_letter)
            else:
                cl_div = await page.query_selector(
                    '[contenteditable="true"][class*="cover"], '
                    '[class*="cover-letter"] [contenteditable]'
                )
                if cl_div:
                    await cl_div.click()
                    await page.keyboard.press("Control+a")
                    await page.keyboard.type(cover_letter)

            await self._fill_custom_questions(page)

            # ── Multi-page loop ──────────────────────────────────────────────
            for page_num in range(1, 11):
                if dry_run:
                    fields = await self._log_form_fields(page)
                    print(f"[lever][dry-run] Page {page_num} fields:")
                    for name, value in fields.items():
                        print(f"  {name}: {value[:80] if value else '(empty)'}")

                next_btn = await self._find_next_button(page)
                if next_btn:
                    print(f"[lever] Page {page_num} → Next")
                    if dry_run:
                        print(f"[lever][dry-run] Would click Next on page {page_num}")
                        return True, None
                    await next_btn.scroll_into_view_if_needed()
                    await asyncio.sleep(0.3)
                    try:
                        await next_btn.click(timeout=8000)
                    except Exception:
                        await page.evaluate("el => el.click()", next_btn)
                    await asyncio.sleep(2)
                    await self._fill_custom_questions(page)
                    continue

                # No Next — try Submit
                if dry_run:
                    return True, None

                clicked, click_err = await self._click_submit(page)
                if not clicked:
                    return False, click_err
                await asyncio.sleep(4)

                success_el = await page.query_selector(
                    '[class*="success"], [class*="confirmation"], '
                    'h2:has-text("Application submitted"), p:has-text("Thank you")'
                )
                if success_el:
                    return True, None
                error_el = await page.query_selector('[class*="error"], .field-error')
                if error_el:
                    return False, (await error_el.inner_text()).strip()
                return True, None

            return False, "Exceeded maximum page count (10)"

        except Exception as e:
            return False, str(e)

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    async def _find_next_button(page: Page):
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
        """Fill visible required text inputs that are still empty."""
        try:
            inputs = await page.query_selector_all(
                'input[required]:not([type="file"]), textarea[required]'
            )
            for inp in inputs:
                current_val = await inp.input_value()
                if not current_val:
                    placeholder = (await inp.get_attribute("placeholder") or "").lower()
                    if "location" in placeholder:
                        await inp.fill(settings.user_location)
        except Exception:
            pass

    @staticmethod
    async def _log_form_fields(page: Page) -> dict:
        fields = {}
        try:
            inputs = await page.query_selector_all(
                'input:not([type="hidden"]):not([type="submit"]), textarea, select'
            )
            for inp in inputs:
                name = await inp.get_attribute("name") or await inp.get_attribute("id") or "?"
                inp_type = await inp.get_attribute("type") or "text"
                value = await inp.input_value() if inp_type != "file" else "(file)"
                fields[name] = value
        except Exception:
            pass
        return fields
