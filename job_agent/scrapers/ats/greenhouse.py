"""Greenhouse ATS form submitter."""
import asyncio
import tempfile
from pathlib import Path
from typing import Optional

from playwright.async_api import Page

from config.settings import settings


class GreenhouseSubmitter:
    """Fills and submits Greenhouse job application forms, handling multi-page flows."""

    async def apply(
        self,
        page: Page,
        apply_url: str,
        resume_path: Path,
        cover_letter: str,
        dry_run: bool = False,
    ) -> tuple[bool, Optional[str]]:
        try:
            await page.goto(apply_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            # ── Page 1: fill all known standard fields ──────────────────────
            await self._fill_field(page, 'input[id*="first_name"], input[name*="first_name"]',
                                   settings.user_full_name.split()[0])
            await self._fill_field(page, 'input[id*="last_name"], input[name*="last_name"]',
                                   settings.user_full_name.split()[-1])
            await self._fill_field(page, 'input[id*="email"], input[type="email"]', settings.user_email)
            await self._fill_field(page, 'input[id*="phone"], input[type="tel"]', settings.user_phone)
            await self._fill_field(page, 'input[id*="linkedin"], input[placeholder*="LinkedIn"]',
                                   settings.user_linkedin_url)

            # Resume upload
            resume_input = await page.query_selector(
                'input[type="file"][id*="resume"], input[type="file"][name*="resume"]'
            )
            if resume_input:
                await resume_input.set_input_files(str(resume_path))
                await asyncio.sleep(1)

            # Cover letter — textarea or file upload
            cl_textarea = await page.query_selector(
                'textarea[id*="cover_letter"], textarea[name*="cover_letter"], '
                'textarea[placeholder*="cover letter"]'
            )
            if cl_textarea:
                await cl_textarea.fill(cover_letter)
            else:
                cl_file = await page.query_selector('input[type="file"][id*="cover_letter"]')
                if cl_file:
                    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
                        f.write(cover_letter)
                        tmp_path = f.name
                    await cl_file.set_input_files(tmp_path)

            await self._fill_optional_fields(page)

            # ── Multi-page loop ──────────────────────────────────────────────
            for page_num in range(1, 11):
                if dry_run:
                    fields = await self._log_form_fields(page)
                    print(f"[greenhouse][dry-run] Page {page_num} fields:")
                    for name, value in fields.items():
                        print(f"  {name}: {value[:80] if value else '(empty)'}")

                next_btn = await self._find_next_button(page)
                if next_btn:
                    print(f"[greenhouse] Page {page_num} → Next")
                    if dry_run:
                        print(f"[greenhouse][dry-run] Would click Next on page {page_num}")
                        return True, None
                    await next_btn.scroll_into_view_if_needed()
                    await asyncio.sleep(0.3)
                    try:
                        await next_btn.click(timeout=8000)
                    except Exception:
                        await page.evaluate("el => el.click()", next_btn)
                    await asyncio.sleep(2)
                    # Fill any new fields that appeared on this page
                    await self._fill_optional_fields(page)
                    continue

                # No Next — try Submit
                if dry_run:
                    return True, None

                clicked, click_err = await self._click_submit(page)
                if not clicked:
                    return False, click_err
                await asyncio.sleep(3)

                success_el = await page.query_selector(
                    '[class*="success"], [class*="confirmation"], h1:has-text("Thank you")'
                )
                if success_el:
                    return True, None
                error_el = await page.query_selector('[class*="error"], [role="alert"]')
                if error_el:
                    return False, (await error_el.inner_text()).strip()
                return True, None

            return False, "Exceeded maximum page count (10)"

        except Exception as e:
            return False, str(e)

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    async def _find_next_button(page: Page):
        """Return a Next/Continue button that advances to the next page (not Submit)."""
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
        """Find the submit button, scroll it into view, click it (JS fallback)."""
        selectors = [
            'button[type="submit"]',
            'input[type="submit"]',
            'button[id*="submit"]',
            'button:has-text("Submit Application")',
            'button:has-text("Submit application")',
            'button:has-text("Submit")',
            'button:has-text("Apply Now")',
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
                await asyncio.sleep(0.3)
        except Exception:
            pass

    @staticmethod
    async def _fill_optional_fields(page: Page) -> None:
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
        fields = {}
        try:
            inputs = await page.query_selector_all(
                'input:not([type="hidden"]):not([type="submit"]), textarea, select'
            )
            for inp in inputs:
                name = await inp.get_attribute("name") or await inp.get_attribute("id") or "?"
                value = await inp.input_value() if await inp.get_attribute("type") != "file" else "(file)"
                fields[name] = value
        except Exception:
            pass
        return fields
