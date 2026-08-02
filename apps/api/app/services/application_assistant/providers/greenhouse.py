"""Greenhouse ATS provider adapter."""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

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


def resolve_greenhouse_field_type(
    *,
    tag: str,
    input_type: str = "",
    role: str = "",
    aria_haspopup: str = "",
) -> str:
    """Infer fill strategy from DOM tag/attributes — not from scraped option counts."""
    tag = (tag or "").lower()
    input_type = (input_type or "").lower()
    role = (role or "").lower()
    if tag == "select":
        return "select-one"
    if tag == "textarea":
        return "textarea"
    if tag == "input":
        if input_type == "file":
            return "file"
        if input_type in ("checkbox", "radio"):
            return input_type
        if role == "combobox" or aria_haspopup in ("listbox", "true"):
            return "select-one"
        return input_type or "text"
    return tag or "text"


def _company_slug_from_host(hostname: str, company_name: str = "") -> str:
    host = (hostname or "").lower()
    if "datadog" in host:
        return "datadog"
    careers_match = re.match(r"careers\.([a-z0-9-]+)\.", host)
    if careers_match:
        slug = careers_match.group(1).replace("-", "")
        if slug.endswith("hq") and len(slug) > 2:
            slug = slug[:-2]
        if slug:
            return slug
    if company_name:
        return re.sub(r"[^a-z0-9]+", "", company_name.lower())
    return ""


def extract_greenhouse_job_ref(url: str, *, company_name: str = "") -> tuple[str, str] | None:
    """Return (company_slug, job_id) from Greenhouse-related URLs."""
    if not url:
        return None

    parsed = urlparse(url.strip())
    host = (parsed.netloc or "").lower()
    path = parsed.path or ""
    query = parse_qs(parsed.query)

    job_id = (query.get("gh_jid") or query.get("token") or [None])[0]
    if not job_id:
        for pattern in (r"/detail/(\d+)", r"/jobs/(\d+)", r"jobs/(\d+)"):
            match = re.search(pattern, path)
            if match:
                job_id = match.group(1)
                break
    if not job_id:
        return None

    slug = ""
    board_match = re.search(r"greenhouse\.io/([^/]+)/jobs/", url.lower())
    if board_match and board_match.group(1) not in ("embed", "job_app"):
        slug = board_match.group(1)
    embed_for = (query.get("for") or [None])[0]
    if embed_for:
        slug = embed_for
    if not slug:
        slug = _company_slug_from_host(host, company_name)
    if not slug:
        return None
    return slug, str(job_id)


def resolve_greenhouse_embed_apply_url(url: str, *, company_name: str = "") -> str:
    """Direct embed form URL — fallback when no custom careers wrapper exists."""
    ref = extract_greenhouse_job_ref(url, company_name=company_name)
    if not ref:
        return url
    slug, job_id = ref
    return f"https://boards.greenhouse.io/embed/job_app?for={slug}&token={job_id}"


def _ensure_gh_jid(url: str, job_id: str) -> str:
    if "gh_jid=" in url:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}gh_jid={job_id}"


def resolve_greenhouse_careers_form_url(
    url: str,
    *,
    company_name: str = "",
    source_url: str = "",
) -> str | None:
    """Full employer careers page with #app — form lives in an embedded Greenhouse iframe."""
    for candidate in (source_url, url):
        if not candidate:
            continue
        parsed = urlparse(candidate.strip())
        host = (parsed.netloc or "").lower()
        if "greenhouse.io" in host:
            continue
        ref = extract_greenhouse_job_ref(candidate, company_name=company_name)
        if not ref:
            continue
        _, job_id = ref
        base = _ensure_gh_jid(candidate.split("#")[0], job_id)
        if "#app" in candidate:
            return candidate
        return f"{base}#app"
    return None


def resolve_greenhouse_apply_url(url: str, *, company_name: str = "") -> str:
    """Normalize Greenhouse job URLs while keeping custom careers pages intact."""
    if not url:
        return url

    parsed = urlparse(url.strip())
    host = (parsed.netloc or "").lower()
    if "greenhouse.io" in host and "/jobs/" in parsed.path:
        return url

    ref = extract_greenhouse_job_ref(url, company_name=company_name)
    if not ref:
        return url
    slug, job_id = ref

    if "greenhouse.io" not in host:
        return _ensure_gh_jid(url.split("#")[0], job_id)

    return f"https://job-boards.greenhouse.io/{slug}/jobs/{job_id}?gh_jid={job_id}"


GREENHOUSE_FORM_SELECTOR = (
    "input[name='job_application[first_name]'], "
    "input[name*='first_name'], "
    "#first_name, "
    "form#application_form, "
    "form[action*='applications']"
)

GREENHOUSE_APPLY_SELECTORS = (
    "#apply_button",
    "a#apply_button",
    "[data-testid='apply-button']",
    "a[href*='#app']",
    "a[href*='applications/new']",
)


def resolve_greenhouse_form_nav_url(
    url: str,
    *,
    company_name: str = "",
    source_url: str = "",
) -> str:
    """Best-effort URL for quick apply — prefer full careers pages over bare embed forms."""
    if not url:
        return url

    parsed = urlparse(url.strip())
    path = (parsed.path or "").rstrip("/")

    if "applications/new" in path:
        return url

    careers = resolve_greenhouse_careers_form_url(
        url,
        company_name=company_name,
        source_url=source_url,
    )
    if careers:
        return careers

    if "/embed/job_app" in path:
        embed = resolve_greenhouse_embed_apply_url(url, company_name=company_name)
        return embed

    host = (parsed.netloc or "").lower()
    if "job-boards.greenhouse.io" in host and re.search(r"/jobs/\d+", path):
        return url.split("#")[0] + "#app"

    return url


async def page_has_application_form(page: Any) -> bool:
    try:
        return bool(await page.query_selector(GREENHOUSE_FORM_SELECTOR))
    except Exception:
        return False


async def _greenhouse_form_present(page: Any) -> bool:
    if await page_has_application_form(page):
        return True
    try:
        iframe_el = await page.query_selector("iframe[src*='greenhouse.io']")
        if iframe_el:
            frame = await iframe_el.content_frame()
            if frame and await page_has_application_form(frame):
                return True
    except Exception:
        pass
    return False


async def ensure_application_form_ready(page: Any, *, wait_ms: int = 8000) -> bool:
    """Open the apply form on job-boards SPAs and wait until fields are present."""
    if await _greenhouse_form_present(page):
        return True

    url = page.url or ""
    if "job-boards.greenhouse.io" in url and "/jobs/" in url and "#app" not in url:
        try:
            await page.goto(url.split("#")[0] + "#app", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(500)
            if await _greenhouse_form_present(page):
                return True
        except Exception:
            pass

    for selector in GREENHOUSE_APPLY_SELECTORS:
        try:
            locator = page.locator(selector).first
            if await locator.count() == 0:
                continue
            await locator.click(timeout=5000)
            await page.wait_for_timeout(800)
            if await _greenhouse_form_present(page):
                return True
        except Exception:
            continue

    for name in ("Apply", "Apply for this job", "Apply now"):
        try:
            for role in ("button", "link"):
                locator = page.get_by_role(role, name=name).first
                if await locator.count() == 0:
                    continue
                await locator.click(timeout=5000)
                await page.wait_for_timeout(800)
                if await _greenhouse_form_present(page):
                    return True
        except Exception:
            continue

    attempts = max(1, wait_ms // 250)
    for _ in range(attempts):
        if await _greenhouse_form_present(page):
            return True
        await asyncio.sleep(0.25)
    return False


class GreenhouseAdapter(ProviderAdapter):
    name = "greenhouse"
    supported = True

    DETECTION_PATTERNS = [
        r"greenhouse\.io",
        r"boards\.greenhouse\.io",
        r"job-boards\.greenhouse\.io",
        r"gh_jid=",
    ]

    def detect(self, url: str, page_content: str = "") -> ProviderDetection:
        text = f"{url} {page_content}".lower()
        for pattern in self.DETECTION_PATTERNS:
            if re.search(pattern, text):
                return ProviderDetection(provider=self.name, confidence=0.95, supported=True)
        return ProviderDetection(provider="unknown", confidence=0.0, supported=False)

    async def discover_jobs(self, page: Any, options: dict[str, Any] | None = None) -> list[JobListing]:
        """Discover jobs from a Greenhouse careers/board page."""
        jobs: list[JobListing] = []

        # Greenhouse board listing selectors
        job_links = await page.query_selector_all(
            "a[href*='/jobs/'], .opening a, .job-post a, tr.job-post td a"
        )

        seen_urls: set[str] = set()
        for link in job_links:
            href = await link.get_attribute("href") or ""
            if not href or "/jobs/" not in href:
                continue

            full_url = href if href.startswith("http") else f"{page.url.rsplit('/', 1)[0]}{href}"
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            title = (await link.inner_text() or "").strip()
            if not title:
                continue

            # Try to get location from sibling/parent
            location = ""
            parent = await link.evaluate_handle("el => el.closest('tr, .opening, .job-post')")
            if parent:
                loc_el = await parent.query_selector(".location, .job-location, td:nth-child(2)")
                if loc_el:
                    location = (await loc_el.inner_text() or "").strip()

            job_id_match = re.search(r"/jobs/(\d+)", full_url)
            external_id = job_id_match.group(1) if job_id_match else ""

            company = self._parse_company_from_url(page.url)

            jobs.append(JobListing(
                company=company,
                title=title,
                location=location,
                application_url=full_url,
                listing_url=full_url,
                external_job_id=external_id,
            ))

        return jobs

    async def extract_job(self, page: Any) -> JobListing | None:
        """Extract job details from a Greenhouse job page."""
        title_el = await page.query_selector("h1.app-title, .job-title, h1")
        title = (await title_el.inner_text() if title_el else "") or ""
        title = title.strip()

        location_el = await page.query_selector(".location, .job-location")
        location = (await location_el.inner_text() if location_el else "") or ""
        location = location.strip()

        desc_el = await page.query_selector("#content, .job-description, .content")
        description = (await desc_el.inner_text() if desc_el else "") or ""

        company = self._parse_company_from_url(page.url)

        job_id_match = re.search(r"/jobs/(\d+)", page.url)
        external_id = job_id_match.group(1) if job_id_match else ""

        return JobListing(
            company=company,
            title=title or "Unknown",
            location=location,
            description=description[:5000],
            application_url=page.url,
            listing_url=page.url,
            external_job_id=external_id,
        )

    async def open_application_form(self, page: Any) -> bool:
        """Navigate from a job listing page to the application form when needed."""
        already_open = await page_has_application_form(page)
        if already_open:
            return False
        return await ensure_application_form_ready(page)

    async def inspect_application(self, page: Any) -> list[FormField]:
        """Inspect Greenhouse application form fields."""
        from app.services.application_assistant.greenhouse_schema import (
            enrich_field_from_schema,
            fetch_greenhouse_schema,
        )

        schema = await fetch_greenhouse_schema(page.url)
        fields: list[FormField] = []

        # Standard Greenhouse form fields
        inputs = await page.query_selector_all(
            "input:not([type='hidden']):not([type='submit']), "
            "textarea, select, "
            ".field:not(.hidden)"
        )

        for _i, el in enumerate(inputs):
            tag = await el.evaluate("el => el.tagName.toLowerCase()")
            await el.get_attribute("type") or tag
            name = await el.get_attribute("name") or ""
            el_id = await el.get_attribute("id") or ""

            if "iti" in el_id.lower() and "search" in el_id.lower():
                continue
            is_iti_search = await el.evaluate(
                "el => el.classList.contains('iti__search-input') || "
                "(el.closest('.iti') && el.type === 'search' && el.id.includes('search'))"
            )
            if is_iti_search:
                continue

            # Get label
            label = await self._get_field_label(page, el, el_id, name)
            if not label:
                continue

            required = await el.get_attribute("required") is not None
            help_text = await self._get_help_text(page, el)

            input_type = (await el.get_attribute("type") or "").lower()
            role = (await el.get_attribute("role") or "").lower()
            aria_haspopup = (await el.get_attribute("aria-haspopup") or "").lower()
            selector = normalize_css_selector(f"#{el_id}") if el_id else f"[name='{name}']"

            options: list[str] = []
            resolved_type = resolve_greenhouse_field_type(
                tag=tag,
                input_type=input_type,
                role=role,
                aria_haspopup=aria_haspopup,
            )
            if tag == "select":
                option_els = await el.query_selector_all("option")
                for opt in option_els:
                    text = (await opt.inner_text() or "").strip()
                    if text:
                        options.append(text)
            elif resolved_type == "select-one":
                from app.services.application_assistant.field_evidence import extract_dom_field_options

                options = await extract_dom_field_options(page, selector)
                if len(options) <= 1:
                    resolved_type = input_type or "text"

            readonly = await el.get_attribute("readonly")
            from app.services.application_assistant.field_fill_engine import (
                is_custom_select_element,
                resolve_custom_select_selector,
            )

            is_custom_select = await is_custom_select_element(el)
            if is_custom_select or readonly is not None:
                resolved_type = "select-one"
                custom_selector = await resolve_custom_select_selector(page, el)
                if custom_selector:
                    selector = custom_selector

            options = merge_field_options(options)

            label, resolved_type, options, _ = enrich_field_from_schema(
                field_id=el_id,
                label=label,
                field_type=resolved_type,
                options=options,
                schema=schema,
            )

            section = await self._get_section(page, el)

            norm_key = normalize_field_key(label)
            if is_phone_country_field(label, name=name, field_id=el_id, selector_hint=selector):
                norm_key = "phone_country"

            fields.append(FormField(
                label=label,
                normalized_key=norm_key,
                field_type=resolved_type,
                required=required,
                options=options,
                help_text=help_text,
                section=section,
                name=name,
                id=el_id,
                selector_hint=selector,
            ))

        return fields

    def map_fields(self, fields: list[FormField], context: dict[str, Any]) -> list[dict[str, Any]]:
        """Map Greenhouse fields to profile/answer-library data."""
        profile = context.get("profile", {})
        answer_library = context.get("answerLibrary", [])
        allow_inferred = context.get("allowInferred", False)

        mapped = []
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
        """Fill Greenhouse form using the generic DOM-aware fill engine."""
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
                    if action_type == "upload_document":
                        value = action.get("filePath", "")
                    else:
                        value = action.get("value", "")
                    ok, fill_reason = await fill_field(page, action, value, profile=profile)
                    if ok:
                        results["filled"].append(action)
                    else:
                        results["skipped"].append({"action": action, "reason": fill_reason})

                elif action_type == "click_safe_nav":
                    text = action.get("buttonText", "")
                    if is_prohibited_action(text, provider=self.name):
                        results["skipped"].append({"action": action, "reason": "Prohibited submit button"})
                        continue
                    btn = await page.get_by_role("button", name=text).first
                    if await btn.count() > 0:
                        await btn.click()
                        results["filled"].append(action)

            except Exception as exc:
                results["errors"].append({"action": action, "error": str(exc)})

        return results

    async def get_progress(self, page: Any) -> dict[str, Any]:
        """Get Greenhouse application progress."""
        current_url = page.url
        section = ""
        section_el = await page.query_selector(".section-header, h2.current-section")
        if section_el:
            section = (await section_el.inner_text() or "").strip()

        return {
            "currentUrl": current_url,
            "currentSection": section,
            "isFinalStep": await self.is_final_step(page),
        }

    async def is_final_step(self, page: Any) -> bool:
        """Check if on final submission step (all prior sections complete)."""
        # Greenhouse often shows submit on the same page as fields;
        # treat as final only when no unfilled required fields remain visible.
        required_empty = await page.query_selector_all(
            "input[required]:not([type='hidden']):not([value]), "
            "select[required]:not([value]), textarea[required]:empty"
        )
        submit_buttons = await page.query_selector_all(
            "input[type='submit'], button[type='submit'], button.submit"
        )
        has_submit = False
        for btn in submit_buttons:
            text = (await btn.get_attribute("value") or await btn.inner_text() or "").strip()
            if is_prohibited_action(text, provider=self.name):
                has_submit = True
                break
        return has_submit and len(required_empty) == 0

    async def detect_blocker(self, page: Any) -> dict[str, Any] | None:
        """Detect CAPTCHA, auth, or other blockers."""
        # Only block on interactive CAPTCHA widgets — ignore passive reCAPTCHA badges on listings.
        captcha = await page.query_selector(
            "iframe[src*='recaptcha/api2/anchor'], iframe[src*='recaptcha/api2/bframe'], "
            ".g-recaptcha:not([data-size='invisible']), #captcha"
        )
        if captcha:
            visible = await captcha.is_visible()
            if visible:
                return {"type": "captcha", "message": "CAPTCHA verification required"}

        # Auth/login detection
        login = await page.query_selector(
            "input[type='password'], form[action*='login'], form[action*='signin']"
        )
        if login:
            return {"type": "authentication", "message": "Login required — please sign in manually"}

        return None

    async def capture_state(self, page: Any) -> dict[str, Any]:
        """Capture current page state."""
        fields = await self.inspect_application(page)
        progress = await self.get_progress(page)
        return {
            "url": page.url,
            "fields": [
                {
                    "label": f.label,
                    "normalizedKey": f.normalized_key,
                    "fieldType": f.field_type,
                    "required": f.required,
                    "section": f.section,
                }
                for f in fields
            ],
            "progress": progress,
        }

    def _parse_company_from_url(self, url: str) -> str:
        match = re.search(r"boards\.greenhouse\.io/([^/]+)", url)
        if match:
            slug = match.group(1).replace("-", " ").replace("_", " ")
            return " ".join(w.capitalize() for w in slug.split())
        match = re.search(r"/([^/]+)/jobs/\d+", url)
        if match and match.group(1) not in ("embed", "job_app"):
            slug = match.group(1).replace("-", " ").replace("_", " ")
            return " ".join(w.capitalize() for w in slug.split())
        return "Unknown Company"

    async def _get_field_label(self, page: Any, el: Any, el_id: str, name: str) -> str:
        if el_id:
            label_el = await page.query_selector(f"label[for='{el_id}']")
            if label_el:
                return (await label_el.inner_text() or "").strip()

        # Check aria-label
        aria = await el.get_attribute("aria-label")
        if aria:
            return aria.strip()

        # Check placeholder
        placeholder = await el.get_attribute("placeholder")
        if placeholder:
            return placeholder.strip()

        # Check parent label
        parent_label = await el.evaluate(
            "el => { const l = el.closest('label'); return l ? l.textContent.trim() : ''; }"
        )
        if parent_label:
            return parent_label

        return name or el_id or ""

    async def _get_help_text(self, page: Any, el: Any) -> str:
        el_id = await el.get_attribute("id") or ""
        if el_id:
            desc = await page.query_selector(f"[aria-describedby*='{el_id}'], .field-description")
            if desc:
                return (await desc.inner_text() or "").strip()
        return ""

    async def _get_section(self, page: Any, el: Any) -> str:
        section = await el.evaluate(
            "el => { const s = el.closest('.section, fieldset, [data-section]'); "
            "return s ? (s.querySelector('legend, h2, h3, .section-header')?.textContent?.trim() || '') : ''; }"
        )
        return section or ""
