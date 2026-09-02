"""Lever ATS provider adapter for autonomous inspection and field filling."""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import urlparse

from app.services.application_assistant.answer_classification import (
    classify_answer,
    is_phone_country_field,
    normalize_field_key,
)
from app.services.application_assistant.css_selectors import normalize_css_selector
from app.services.application_assistant.field_options import merge_field_options
from app.services.application_assistant.providers.base import (
    FormField,
    JobListing,
    ProviderAdapter,
    ProviderDetection,
)
from app.services.application_assistant.submission_guard import (
    is_prohibited_action,
    validate_action_allowed,
)


class LeverAdapter(ProviderAdapter):
    """Adapter for jobs hosted on Lever (jobs.lever.co)."""

    name = "lever"
    supported = True

    DETECTION_PATTERNS = [
        r"jobs\.lever\.co",
        r"lever\.co/",
    ]

    def detect(self, url: str, page_content: str = "") -> ProviderDetection:
        text = f"{url} {page_content}".lower()
        for pattern in self.DETECTION_PATTERNS:
            if re.search(pattern, text):
                return ProviderDetection(provider=self.name, confidence=0.95, supported=True)
        return ProviderDetection(provider="unknown", confidence=0.0, supported=False)

    def _parse_company_from_url(self, url: str) -> str:
        match = re.search(r"jobs\.lever\.co/([^/]+)", url)
        if match:
            return match.group(1).replace("-", " ").title()
        return "Unknown"

    async def discover_jobs(self, page: Any, options: dict[str, Any] | None = None) -> list[JobListing]:
        """Discover jobs from a Lever board page."""
        jobs: list[JobListing] = []
        job_links = await page.query_selector_all("a.posting-title, .posting a")
        seen_urls: set[str] = set()

        for link in job_links:
            href = await link.get_attribute("href") or ""
            if not href or href in seen_urls:
                continue
            seen_urls.add(href)

            title_el = await link.query_selector("h5, .posting-title")
            title = (await title_el.inner_text() if title_el else await link.inner_text() or "").strip()
            if not title:
                continue

            loc_el = await link.query_selector(".sort-by-location, .posting-category")
            location = (await loc_el.inner_text() if loc_el else "").strip()

            jobs.append(
                JobListing(
                    company=self._parse_company_from_url(page.url),
                    title=title,
                    location=location,
                    application_url=href if href.endswith("/apply") else f"{href.rstrip('/')}/apply",
                    listing_url=href,
                )
            )
        return jobs

    async def extract_job(self, page: Any) -> JobListing | None:
        """Extract job details from a Lever posting or apply page."""
        title_el = await page.query_selector("div.posting-headline h2, .posting-headline, h2")
        title = (await title_el.inner_text() if title_el else "").strip()

        loc_el = await page.query_selector(".posting-categories .location, .location")
        location = (await loc_el.inner_text() if loc_el else "").strip()

        desc_el = await page.query_selector(".section-wrapper, .posting-page, .content")
        description = (await desc_el.inner_text() if desc_el else "").strip()

        apply_url = page.url
        if "/apply" not in apply_url:
            apply_url = f"{apply_url.rstrip('/')}/apply"

        return JobListing(
            company=self._parse_company_from_url(page.url),
            title=title,
            location=location,
            application_url=apply_url,
            listing_url=page.url,
            description=description,
        )

    async def open_application_form(self, page: Any) -> bool:
        """Ensure page is on the Lever /apply form."""
        url = page.url or ""
        if "/apply" in url:
            return True
        try:
            apply_btn = await page.query_selector("a[href*='/apply'], .postings-btn, .template-btn-submit")
            if apply_btn:
                await apply_btn.click()
                await page.wait_for_load_state("domcontentloaded")
                return True
        except Exception:
            pass
        return False

    async def inspect_application(self, page: Any) -> list[FormField]:
        """Inspect form fields on Lever application pages."""
        await self.open_application_form(page)

        fields: list[FormField] = []
        inputs = await page.query_selector_all(
            "input:not([type='hidden']):not([type='submit']), textarea, select, .custom-question"
        )

        for el in inputs:
            tag = (await el.evaluate("el => el.tagName.toLowerCase()")) or "input"
            name = await el.get_attribute("name") or ""
            el_id = await el.get_attribute("id") or ""
            input_type = (await el.get_attribute("type") or "").lower()

            # Retrieve label text
            label = ""
            label_el = await page.query_selector(f"label[for='{el_id}']") if el_id else None
            if label_el:
                label = (await label_el.inner_text() or "").strip()
            if not label:
                parent = await el.evaluate_handle("el => el.closest('.application-question, .form-group, label')")
                if parent:
                    p_text = await parent.evaluate("el => el.innerText || ''")
                    lines = [ln.strip() for ln in p_text.splitlines() if ln.strip()]
                    label = lines[0] if lines else ""

            if not label:
                label = (await el.get_attribute("placeholder") or name or el_id).strip()
            if not label:
                continue

            required = (
                await el.get_attribute("required") is not None
                or "*" in label
                or "required" in label.lower()
            )
            clean_label = re.sub(r"\s*[\*\(]required[\*\)]|\s*\*$", "", label, flags=re.IGNORECASE).strip()

            selector = normalize_css_selector(f"#{el_id}") if el_id else f"[name='{name}']"
            resolved_type = "text"
            if tag == "select":
                resolved_type = "select-one"
            elif tag == "textarea":
                resolved_type = "textarea"
            elif input_type in ("file", "checkbox", "radio"):
                resolved_type = input_type

            options: list[str] = []
            if tag == "select":
                for opt in await el.query_selector_all("option"):
                    txt = (await opt.inner_text() or "").strip()
                    if txt:
                        options.append(txt)

            norm_key = normalize_field_key(clean_label)
            if is_phone_country_field(clean_label, name=name, field_id=el_id, selector_hint=selector):
                norm_key = "phone_country"

            fields.append(
                FormField(
                    label=clean_label,
                    normalized_key=norm_key,
                    field_type=resolved_type,
                    required=required,
                    options=merge_field_options(options),
                    help_text="",
                    section="application",
                    name=name,
                    id=el_id,
                    selector_hint=selector,
                )
            )

        return fields

    def map_fields(self, fields: list[FormField], context: dict[str, Any]) -> list[dict[str, Any]]:
        """Map Lever fields to profile and answer library data."""
        profile = context.get("profile", {})
        answer_library = context.get("answerLibrary", [])
        allow_inferred = context.get("allowInferred", False)

        mapped: list[dict[str, Any]] = []
        for f in fields:
            classification, value, confidence, source, sensitivity = classify_answer(
                label=f.label,
                help_text=f.help_text,
                field_type=f.field_type,
                profile=profile,
                answer_library=answer_library,
                allow_inferred=allow_inferred,
                name=f.name,
                field_id=f.id,
                selector_hint=f.selector_hint,
            )
            mapped.append({
                "label": f.label,
                "normalizedKey": f.normalized_key,
                "fieldType": f.field_type,
                "required": f.required,
                "options": f.options,
                "helpText": f.help_text,
                "section": f.section,
                "selectorHint": f.selector_hint,
                "name": f.name,
                "classification": classification.value,
                "proposedValue": value,
                "confidence": confidence,
                "source": source,
                "sensitivityCategory": sensitivity.value,
                "filled": False,
            })
        return mapped

    async def fill_page(
        self,
        page: Any,
        approved_actions: list[dict[str, Any]],
        *,
        profile: dict[str, Any] | None = None,
        fast_replay: bool = False,
    ) -> dict[str, Any]:
        """Fill Lever form fields using the shared field fill engine."""
        if fast_replay:
            from app.services.application_assistant.field_fill_engine import fill_page_fast_replay
            return await fill_page_fast_replay(page, approved_actions, profile=profile)

        from app.services.application_assistant.field_fill_engine import fill_field

        results = {"filled": [], "skipped": [], "errors": []}
        for action in approved_actions:
            action_type = action.get("type", "")
            allowed, reason = validate_action_allowed(
                action_type,
                button_text=action.get("buttonText", ""),
                provider=self.name,
            )
            if not allowed:
                results["skipped"].append({"action": action, "reason": reason})
                continue

            try:
                if action_type in ("fill_text", "fill_field", "select_option", "upload_document"):
                    val = action.get("filePath", "") if action_type == "upload_document" else action.get("value", "")
                    ok, fill_reason = await fill_field(page, action, val, profile=profile)
                    if ok:
                        results["filled"].append(action)
                    else:
                        results["skipped"].append({"action": action, "reason": fill_reason})
                elif action_type == "click_safe_nav":
                    text = action.get("buttonText", "")
                    if is_prohibited_action(text, provider=self.name):
                        results["skipped"].append({"action": action, "reason": "Prohibited submit button"})
                        continue
                    btn = await page.query_selector(action.get("selectorHint", ""))
                    if btn:
                        await btn.click()
                        await page.wait_for_timeout(1000)
                        results["filled"].append(action)
            except Exception as exc:
                results["errors"].append({"action": action, "error": str(exc)})

        return results

    async def get_progress(self, page: Any) -> dict[str, Any]:
        return {"current_step": 1, "total_steps": 1, "percentage": 100}

    async def is_final_step(self, page: Any) -> bool:
        return True

    async def detect_blocker(self, page: Any) -> dict[str, Any] | None:
        captcha = await page.query_selector("iframe[src*='recaptcha'], iframe[src*='hcaptcha'], .g-recaptcha")
        if captcha:
            return {"type": "captcha", "message": "CAPTCHA detected on Lever page"}
        return None

    async def capture_state(self, page: Any) -> dict[str, Any]:
        return {"url": page.url, "fields": [], "progress": {"step": 1}}
