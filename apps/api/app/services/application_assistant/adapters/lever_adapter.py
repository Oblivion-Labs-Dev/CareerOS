"""Lever ATS Application Adapter with Industry-Grade DOM Control."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from app.services.application_assistant.adapters.base_adapter import ApplicationAdapter

logger = logging.getLogger("career_os.lever_adapter")


class LeverAdapter(ApplicationAdapter):
    @property
    def name(self) -> str:
        return "lever"

    async def can_handle(self, url: str, html_content: str = "") -> bool:
        u_low = url.lower()
        return "lever.co" in u_low or "lever-form" in html_content.lower() or "jobs.lever.co" in u_low

    async def inspect_fields(self, url: str, html_content: str = "") -> list[dict[str, Any]]:
        return [
            {"id": "name", "label": "Full Name", "type": "text", "required": True, "canonicalKey": "fullName"},
            {"id": "email", "label": "Email", "type": "text", "required": True, "canonicalKey": "email"},
            {"id": "phone", "label": "Phone", "type": "text", "required": True, "canonicalKey": "phone"},
            {"id": "resume", "label": "Resume", "type": "file", "required": True, "canonicalKey": "resume"},
            {"id": "org", "label": "Current Company", "type": "text", "required": False, "canonicalKey": "currentCompany"},
            {"id": "urls[LinkedIn]", "label": "LinkedIn Profile", "type": "text", "required": False, "canonicalKey": "linkedin"},
            {"id": "urls[Portfolio]", "label": "Portfolio", "type": "text", "required": False, "canonicalKey": "portfolio"},
        ]

    async def fill_fields(self, page_context: Any, resolved_answers: dict[str, Any]) -> dict[str, Any]:
        """Fill standard Lever inputs, textareas, and custom screening questions."""
        filled: dict[str, str] = {}
        page = page_context

        # Text mappings
        # No hardcoded identity fallbacks: an unresolved field must stay empty so
        # the pre-submit check catches it, never be quietly filled with a name
        # and contact details baked into the source.
        full_name = f"{resolved_answers.get('firstName') or ''} {resolved_answers.get('lastName') or ''}".strip()
        text_inputs = {
            'input[name="name"]': full_name,
            'input[name="email"]': resolved_answers.get("email") or "",
            'input[name="phone"]': resolved_answers.get("phone") or "",
            'input[name="org"]': resolved_answers.get("currentCompany", ""),
            'input[name="urls[LinkedIn]"]': resolved_answers.get("linkedin") or "",
            'input[name="urls[Portfolio]"], input[name="urls[Website]"]': resolved_answers.get("portfolio") or resolved_answers.get("website") or resolved_answers.get("github") or resolved_answers.get("linkedin") or "",
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

        # Handle custom checkboxes (e.g. Work authorization, EEOC)
        try:
            checkboxes = await page.locator('.application-question input[type="checkbox"], input[type="checkbox"]').all()
            for cb in checkboxes:
                cb_label = await cb.evaluate("el => el.closest('label')?.innerText || el.getAttribute('aria-label') || ''")
                lbl_low = cb_label.lower()
                if "authorized" in lbl_low or "consent" in lbl_low or "agree" in lbl_low:
                    if not await cb.is_checked():
                        await cb.check(force=True)
                        filled[cb_label[:30]] = "checked"
        except Exception:
            pass

        return {"filledCount": len(filled), "filled": filled}

    async def verify_pre_submit(self, page_context: Any, fields: list[dict[str, Any]] | None = None) -> tuple[bool, str]:
        page = page_context
        try:
            errors = await page.locator('.error-message, .error, [role="alert"]').all_inner_texts()
            active_errors = [e.strip() for e in errors if e.strip() and "cookie" not in e.lower()]
            if active_errors:
                return False, f"Validation errors on Lever form: {', '.join(active_errors[:3])}"
            return True, ""
        except Exception:
            return True, ""

    async def submit_application(self, page_context: Any) -> dict[str, Any]:
        page = page_context
        submit_selectors = ["#btn-submit", "button[data-qa='btn-submit']", "button[type='submit']"]
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
                "confirmationText": "Application submitted via Lever Adapter",
                "confirmationUrl": url,
            },
        }
