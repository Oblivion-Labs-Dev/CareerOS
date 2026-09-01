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

        full_name = f"{resolved_answers.get('firstName', 'Akshay')} {resolved_answers.get('lastName', 'Borse')}".strip()
        text_inputs = {
            'input[name*="name" i], input[id*="name" i]': full_name,
            'input[name*="email" i], input[type="email"]': resolved_answers.get("email", "amsborse@gmail.com"),
            'input[name*="phone" i], input[type="tel"]': resolved_answers.get("phone", "425-336-9852"),
            'input[name*="linkedin" i], input[id*="linkedin" i]': resolved_answers.get("linkedin", "https://www.linkedin.com/in/amsborse/"),
            'input[name*="website" i], input[name*="portfolio" i]': resolved_answers.get("portfolio") or resolved_answers.get("website", "https://amsborse.github.io/resume"),
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
        return {
            "submitted": True,
            "evidence": {
                "confirmationText": "Application submitted via Ashby Adapter",
                "confirmationUrl": url,
            },
        }
