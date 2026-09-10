"""Ashby ATS Application Adapter with Industry-Grade DOM Control."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.services.application_assistant.adapters.base_adapter import ApplicationAdapter

logger = logging.getLogger("career_os.ashby_adapter")


class AshbyAdapter(ApplicationAdapter):
    @property
    def name(self) -> str:
        return "ashby"

    async def can_handle(self, url: str, html_content: str = "") -> bool:
        u_low = url.lower()
        return "ashbyhq.com" in u_low or "ashby" in html_content.lower() or "jobs.ashbyhq.com" in u_low

    async def inspect_fields(self, url: str, html_content: str = "") -> list[dict[str, Any]]:
        return [
            {"id": "name", "label": "Full Name", "type": "text", "required": True, "canonicalKey": "fullName"},
            {"id": "email", "label": "Email Address", "type": "text", "required": True, "canonicalKey": "email"},
            {"id": "phone", "label": "Phone Number", "type": "text", "required": True, "canonicalKey": "phone"},
            {"id": "resume", "label": "Resume", "type": "file", "required": True, "canonicalKey": "resume"},
            {"id": "linkedin", "label": "LinkedIn Profile", "type": "text", "required": False, "canonicalKey": "linkedin"},
        ]

    async def fill_fields(self, page_context: Any, resolved_answers: dict[str, Any]) -> dict[str, Any]:
        filled: dict[str, str] = {}
        page = page_context

        # No hardcoded identity fallbacks: an unresolved field must stay empty so
        # the pre-submit check catches it, never be quietly filled with a name
        # and contact details baked into the source.
        full_name = f"{resolved_answers.get('firstName') or ''} {resolved_answers.get('lastName') or ''}".strip()
        text_inputs = {
            'input[name*="name" i], input[id*="name" i]': full_name,
            'input[name*="email" i], input[type="email"]': resolved_answers.get("email") or "",
            'input[name*="phone" i], input[type="tel"]': resolved_answers.get("phone") or "",
            'input[name*="linkedin" i], input[id*="linkedin" i]': resolved_answers.get("linkedin") or "",
            'input[name*="website" i], input[name*="portfolio" i]': resolved_answers.get("portfolio") or resolved_answers.get("website") or resolved_answers.get("github") or resolved_answers.get("linkedin") or "",
        }

        for sel, val in text_inputs.items():
            if not val:
                continue
            try:
                elem = page.locator(sel).first
                if await elem.count() > 0 and await elem.is_visible():
                    await elem.fill(str(val))
                    filled[sel] = str(val)
            except Exception:
                pass

        return {"filledCount": len(filled), "filled": filled}

    async def verify_pre_submit(self, page_context: Any, fields: list[dict[str, Any]] | None = None) -> tuple[bool, str]:
        page = page_context
        try:
            errors = await page.locator('[class*="errorMessage"], [role="alert"], .error').all_inner_texts()
            active_errors = [e.strip() for e in errors if e.strip() and "cookie" not in e.lower()]
            if active_errors:
                return False, f"Validation errors on Ashby form: {', '.join(active_errors[:3])}"
            return True, ""
        except Exception:
            return True, ""

    async def submit_application(self, page_context: Any) -> dict[str, Any]:
        page = page_context
        submit_selectors = ["button[type='submit']", "button:has-text('Submit Application')", "button:has-text('Submit')"]
        for sel in submit_selectors:
            btn = page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible():
                await btn.scroll_into_view_if_needed()
                await btn.click()
                await asyncio.sleep(5.0)
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                break

        url = page.url if hasattr(page, "url") else ""
        # Clicking submit is not evidence that the submission was accepted.
        # Ashby keeps the form mounted and shows inline errors when it refuses,
        # so re-check for those and for a confirmation state before claiming
        # success — reporting `submitted: True` off the click alone is how a job
        # gets recorded SUBMITTED with nothing behind it.
        accepted, why = await self.verify_pre_submit(page, None)
        confirmed = False
        try:
            confirmed = await page.locator(
                'text=/application (has been )?(submitted|received)/i, '
                '[class*="confirmation" i], [data-testid*="confirmation" i]'
            ).count() > 0
        except Exception:
            confirmed = False
        if not accepted:
            return {"submitted": False, "error": why, "evidence": {"confirmationUrl": url}}
        if not confirmed:
            return {
                "submitted": False,
                "error": "Submit was clicked but Ashby showed no confirmation",
                "evidence": {"confirmationUrl": url},
            }
        return {
            "submitted": True,
            "evidence": {
                "confirmationText": "Ashby confirmation shown after submit",
                "confirmationUrl": url,
            },
        }
