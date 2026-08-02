"""Local Playwright browser runner for Application Assistant."""

from __future__ import annotations

import asyncio
import atexit
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.services.application_assistant.answer_classification import (
    infer_phone_country,
    is_phone_country_field,
    should_skip_autofill_field,
)
from app.services.application_assistant.browser_replay import (
    build_browser_plan,
    build_replay_actions_from_fields,
    ensure_document_upload_actions,
    merge_plan_actions_with_fields,
    normalize_replay_actions,
    plan_is_usable,
    resolve_review_replay_plan,
    sort_fill_actions,
)
from app.services.application_assistant.log_redaction import sanitize_url
from app.services.application_assistant.mapping_pipeline import (
    apply_document_fields,
    attach_field_ids,
    build_and_validate_actions,
    resolve_field_mapping_settings,
    run_mapping_pipeline,
    verify_filled_fields,
)
from app.services.application_assistant.qwen_activity import log_activity_event

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "application_assistant"
SCREENSHOTS_DIR = DATA_DIR / "screenshots"
TRACES_DIR = DATA_DIR / "traces"
BROWSER_PROFILE_DIR = Path(os.environ.get("AA_BROWSER_PROFILE_DIR") or (DATA_DIR / "browser_profile"))
BROWSER_SESSIONS_DIR = BROWSER_PROFILE_DIR / "sessions"
PREP_TIMEOUT_SEC = float(os.environ.get("AA_PREP_TIMEOUT", "600"))

for d in (DATA_DIR, SCREENSHOTS_DIR, TRACES_DIR, BROWSER_PROFILE_DIR, BROWSER_SESSIONS_DIR):
    d.mkdir(parents=True, exist_ok=True)

_active_sessions: dict[str, BrowserSession] = {}


def profile_dir_for_app(app_id: str) -> str:
    """Isolated Chromium profile so multiple review windows can run in parallel."""
    safe_id = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in app_id) or "default"
    path = BROWSER_SESSIONS_DIR / safe_id
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


_playwright_loop: asyncio.AbstractEventLoop | None = None
_playwright_thread: threading.Thread | None = None
_playwright_lock = threading.Lock()


def _ensure_playwright_loop() -> asyncio.AbstractEventLoop:
    """Keep one Proactor loop alive on Windows so headed browsers stay open."""
    global _playwright_loop, _playwright_thread
    with _playwright_lock:
        if _playwright_loop is not None and _playwright_thread and _playwright_thread.is_alive():
            return _playwright_loop

        ready = threading.Event()

        def _runner() -> None:
            global _playwright_loop
            if sys.platform == "win32":
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            _playwright_loop = loop
            ready.set()
            loop.run_forever()

        _playwright_thread = threading.Thread(target=_runner, name="aa-playwright", daemon=True)
        _playwright_thread.start()
        if not ready.wait(timeout=15):
            raise RuntimeError("Playwright worker thread failed to start")
        if _playwright_loop is None:
            raise RuntimeError("Playwright worker loop missing after thread start")
        return _playwright_loop


def run_playwright(coro: Any, *, timeout: float = 180) -> Any:
    loop = _ensure_playwright_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)


async def run_playwright_async(coro: Any, *, timeout: float = 180) -> Any:
    loop = _ensure_playwright_loop()
    return await asyncio.wait_for(asyncio.wrap_future(asyncio.run_coroutine_threadsafe(coro, loop)), timeout=timeout)


def _merge_saved_fields(mapped: list[dict[str, Any]], saved_fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Overlay previously saved draft values onto freshly inspected fields."""
    by_key: dict[str, dict[str, Any]] = {}
    by_field_id: dict[str, dict[str, Any]] = {}
    for saved in saved_fields:
        field_id = saved.get("fieldId")
        if field_id:
            by_field_id[str(field_id)] = saved
        key = saved.get("normalizedKey") or saved.get("label")
        if key:
            by_key[str(key)] = saved

    for field in mapped:
        saved = by_field_id.get(str(field.get("fieldId") or ""))
        if not saved:
            key = str(field.get("normalizedKey") or field.get("label") or "")
            saved = by_key.get(key)
        if not saved:
            continue
        if should_skip_autofill_field(field) or should_skip_autofill_field(saved):
            field["classification"] = "manual_only"
            field["proposedValue"] = None
            field["requiresUserReview"] = False
            continue
        if saved.get("userEdited") and saved.get("proposedValue") is not None:
            field["proposedValue"] = saved["proposedValue"]
        elif saved.get("proposedValue") is not None:
            fresh_value = field.get("proposedValue")
            if field.get("classification") != "verified" or not fresh_value:
                field["proposedValue"] = saved["proposedValue"]
        saved_class = saved.get("classification")
        if saved_class:
            field["classification"] = saved_class
            if saved_class == "verified":
                field["requiresUserReview"] = False
                field["confidence"] = max(
                    float(saved.get("confidence") or 0),
                    float(field.get("confidence") or 0),
                    1.0,
                )
            elif saved_class == "inferred":
                field["confidence"] = max(
                    float(saved.get("confidence") or 0),
                    float(field.get("confidence") or 0),
                )
        if saved.get("filled"):
            field["filled"] = saved["filled"]
        if saved.get("source"):
            field["source"] = saved["source"]
        if saved.get("selectorHint") and not field.get("selectorHint"):
            field["selectorHint"] = saved["selectorHint"]
    return mapped


def _refresh_special_field_values(mapped: list[dict[str, Any]], context: dict[str, Any]) -> list[dict[str, Any]]:
    """Re-resolve values that saved drafts may have mapped incorrectly."""
    profile = context.get("profile") or {}
    for field in mapped:
        if should_skip_autofill_field(field):
            field["classification"] = "manual_only"
            field["requiresUserReview"] = False
            field["proposedValue"] = None
            continue
        if is_phone_country_field(
            str(field.get("label") or ""),
            name=str(field.get("name") or ""),
            field_id=str(field.get("id") or ""),
            selector_hint=str(field.get("selectorHint") or ""),
        ):
            field["normalizedKey"] = "phone_country"
            field["classification"] = "verified"
            field["proposedValue"] = infer_phone_country(profile)
            field["confidence"] = 1.0
            field["source"] = "profile.phoneCountry"
            field["requiresUserReview"] = False
    return mapped


def _field_fillable(field: dict[str, Any], *, review_mode: bool) -> bool:
    if should_skip_autofill_field(field):
        return False
    if field.get("classification") == "manual_only":
        return False
    field_type = str(field.get("fieldType", "")).lower()
    if field_type == "file":
        if field.get("classification") != "verified":
            return False
        path = field.get("proposedValue")
        return bool(path and Path(str(path)).is_file())
    value = field.get("proposedValue")
    if value is None or str(value).strip() == "":
        return False
    if field.get("classification") == "verified":
        return True
    if review_mode and (field.get("filled") or field.get("classification") == "inferred"):
        return True
    return False


async def _await_bounded(awaitable: Any, timeout: float) -> bool:
    """Wait for a Playwright operation without waiting forever for cancellation."""
    task = asyncio.ensure_future(awaitable)
    done, _pending = await asyncio.wait({task}, timeout=timeout)
    if task not in done:
        task.cancel()
        return False
    try:
        task.result()
    except BaseException:
        return False
    return True


async def _stop_playwright_instance(playwright: Any) -> None:
    try:
        await playwright.stop()
    except Exception:
        pass


class BrowserSession:
    """Managed Playwright browser session."""

    def __init__(self, *, headed: bool = True, profile_dir: str = "", background: bool = False):
        self.headed = headed
        self.background = background
        self.profile_dir = profile_dir or str(BROWSER_PROFILE_DIR)
        self._playwright = None
        self._browser = None
        self._context = None
        self._session_id = ""
        self._active_page = None

    async def start(self) -> None:
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                launch_args = ["--disable-blink-features=AutomationControlled"]
                if self.background:
                    launch_args.extend(["--window-position=-32000,-32000", "--window-size=1280,900"])
                else:
                    launch_args.append("--start-maximized")
                self._browser = await self._playwright.chromium.launch_persistent_context(
                    user_data_dir=self.profile_dir,
                    headless=not self.headed,
                    viewport={"width": 1280, "height": 900},
                    args=launch_args,
                )
                self._context = self._browser
                return
            except Exception as exc:
                last_error = exc
                if attempt == 0 and "already in use" in str(exc).lower():
                    await close_all_sessions()
                    _kill_chromium_using_profile(self.profile_dir)
                    await asyncio.sleep(1)
                    continue
                raise
        if last_error:
            raise last_error

    async def __aenter__(self) -> BrowserSession:
        await self.start()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    def set_active_page(self, page: Any) -> None:
        self._active_page = page

    async def close_other_pages(self, keep_page: Any) -> None:
        if not self._context:
            return
        for old_page in list(self._context.pages):
            if old_page is keep_page or old_page.is_closed():
                continue
            try:
                await old_page.close()
            except Exception:
                pass

    def _register_active(self, app_id: str) -> None:
        self._session_id = app_id
        _active_sessions[app_id] = self
        if self._context:
            try:
                self._context.on("close", self._on_context_closed)
            except Exception:
                pass

    def _on_context_closed(self) -> None:
        app_id = self._session_id
        if app_id:
            from app.services.application_assistant.submission_watcher import (
                finalize_submission_watch_sync,
                stop_submission_watcher,
            )

            finalize_submission_watch_sync(app_id, self)
            stop_submission_watcher(app_id)
            _active_sessions.pop(app_id, None)
            _sync_cleanup_closed_session(app_id)
        playwright = self._playwright
        self._session_id = ""
        self._context = None
        self._playwright = None
        if playwright is not None:
            asyncio.create_task(_stop_playwright_instance(playwright))

    async def focus(self, page: Any | None = None) -> None:
        target = page or self._active_page
        if target and not target.is_closed():
            try:
                await target.bring_to_front()
                return
            except Exception:
                pass
        if not self._context:
            return
        for pg in self._context.pages:
            if not pg.is_closed():
                try:
                    await pg.bring_to_front()
                except Exception:
                    pass

    def is_alive(self) -> bool:
        """Return False when the user closed the browser window."""
        if not self._context:
            return False
        try:
            pages = self._context.pages
            return any(not p.is_closed() for p in pages)
        except Exception:
            return False

    def detach(self) -> None:
        """Drop registry entry without throwing if the browser is already gone."""
        if self._session_id:
            _active_sessions.pop(self._session_id, None)
        self._session_id = ""
        self._context = None
        self._playwright = None

    async def new_page(self) -> Any:
        if not self._context:
            await self.start()
        return await self._context.new_page()

    async def close(self) -> None:
        app_id = self._session_id
        context = self._context
        playwright = self._playwright
        self._context = None
        self._playwright = None
        context_closed = context is None
        if context:
            context_closed = await _await_bounded(context.close(), timeout=10.0)
        if not context_closed:
            await asyncio.to_thread(_kill_chromium_using_profile, self.profile_dir)
        if playwright:
            await _await_bounded(playwright.stop(), timeout=5.0)
        if app_id:
            _active_sessions.pop(app_id, None)
        self._session_id = ""

    async def screenshot(self, page: Any, name: str) -> str:
        """Capture screenshot, return file path."""
        path = SCREENSHOTS_DIR / f"{name}.png"
        await page.screenshot(path=str(path), full_page=False)
        return str(path)

    async def start_trace(self) -> None:
        if self._context:
            await self._context.tracing.start(screenshots=True, snapshots=True)

    async def stop_trace(self, name: str) -> str:
        path = TRACES_DIR / f"{name}.zip"
        if self._context:
            await self._context.tracing.stop(path=str(path))
        return str(path)


async def prepare_application(
    *,
    application_url: str,
    adapter: Any,
    context: dict[str, Any],
    app_id: str = "",
    headed: bool = True,
) -> dict[str, Any]:
    """
    Open application in visible browser, inspect, map, and fill verified fields.
    Never clicks final submit.
    """
    from app.services.application_assistant.url_validation import validate_url

    valid, reason = validate_url(application_url)
    if not valid:
        return {"success": False, "error": reason}

    # Playwright subprocesses need Proactor on Windows — use a dedicated worker loop.
    if sys.platform == "win32":
        return await run_playwright_async(
            _prepare_application_impl(
                application_url=application_url,
                adapter=adapter,
                context=context,
                app_id=app_id,
                headed=headed,
            ),
            timeout=PREP_TIMEOUT_SEC,
        )

    return await _prepare_application_impl(
        application_url=application_url,
        adapter=adapter,
        context=context,
        app_id=app_id,
        headed=headed,
    )


_GREENHOUSE_FORM_SELECTOR = (
    "input[name='job_application[first_name]'], "
    "input[name*='first_name'], "
    "#first_name, "
    "form#application_form, "
    "form[action*='applications']"
)
_DEFAULT_IFRAME_SELECTOR = "iframe[src*='greenhouse.io']"


async def _page_has_application_form(target: Any) -> bool:
    try:
        return bool(await target.query_selector(_GREENHOUSE_FORM_SELECTOR))
    except Exception:
        return False


async def _detect_application_work_page(
    page: Any,
    *,
    iframe_selector: str = _DEFAULT_IFRAME_SELECTOR,
    wait_ms: int = 5000,
) -> tuple[Any, bool]:
    """Return the page/frame that contains the application form, waiting for SPA hydration."""
    selector = iframe_selector or _DEFAULT_IFRAME_SELECTOR
    attempts = max(1, wait_ms // 250)
    for _ in range(attempts):
        if await _page_has_application_form(page):
            return page, False

        iframe_el = await page.query_selector(selector)
        if iframe_el:
            frame = await iframe_el.content_frame()
            if frame and await _page_has_application_form(frame):
                return frame, True

        await asyncio.sleep(0.1)

    return page, False


def _defer_browser_focus(session: BrowserSession, page: Any) -> None:
    """Focus the review browser without blocking prep completion."""

    async def _focus_with_timeout() -> None:
        try:
            await asyncio.wait_for(session.focus(page), timeout=5.0)
        except Exception:
            pass

    asyncio.create_task(_focus_with_timeout())


async def _resolve_work_page(page: Any, *, use_iframe: bool, iframe_selector: str) -> Any:
    work_page, _ = await _detect_application_work_page(
        page,
        iframe_selector=iframe_selector or _DEFAULT_IFRAME_SELECTOR,
        wait_ms=5000 if use_iframe else 2500,
    )
    return work_page


async def _fast_review_from_plan(
    *,
    session: BrowserSession,
    page: Any,
    adapter: Any,
    context: dict[str, Any],
    app_id: str,
    headed: bool,
    nav_url: str,
    application_url: str,
    browser_plan: dict[str, Any],
    results: dict[str, Any],
    skip_navigation: bool = False,
) -> dict[str, Any]:
    """Replay saved navigation + fill actions — no inspect or LLM mapping."""
    saved_fields = context.get("savedFields") or []
    if saved_fields:
        saved_fields = apply_document_fields([dict(field) for field in saved_fields], context)
    provider = getattr(adapter, "name", "") or browser_plan.get("provider", "")

    log_activity_event(
        event_type="prep_step",
        summary=f"Quick apply — replaying {browser_plan.get('actionCount', 0)} saved steps",
        metadata={"applicationId": app_id, "step": "fast_replay", "actionCount": browser_plan.get("actionCount", 0)},
    )

    if not skip_navigation:
        replay_nav = str(browser_plan.get("formNavUrl") or nav_url)
        if provider == "greenhouse":
            from app.services.application_assistant.providers.greenhouse import resolve_greenhouse_form_nav_url

            replay_nav = resolve_greenhouse_form_nav_url(
                replay_nav,
                company_name=str(context.get("companyName") or ""),
                source_url=str(browser_plan.get("sourceUrl") or application_url or ""),
            )
        await page.goto(replay_nav, wait_until="domcontentloaded", timeout=45000)
        try:
            await page.bring_to_front()
        except Exception:
            pass

    if provider == "greenhouse":
        from app.services.application_assistant.providers.greenhouse import ensure_application_form_ready

        iframe_selector = str(browser_plan.get("iframeSelector") or _DEFAULT_IFRAME_SELECTOR)
        iframe_el = await page.query_selector(iframe_selector)
        frame = await iframe_el.content_frame() if iframe_el else None
        form_ready = await _page_has_application_form(page)
        if not form_ready and frame:
            form_ready = await _page_has_application_form(frame)
        if not form_ready:
            await ensure_application_form_ready(page, wait_ms=8000)
            if frame:
                form_ready = await _page_has_application_form(frame)
            if not form_ready:
                form_ready = await _page_has_application_form(page)

    work_page, use_iframe = await _detect_application_work_page(
        page,
        iframe_selector=str(browser_plan.get("iframeSelector") or _DEFAULT_IFRAME_SELECTOR),
        wait_ms=8000,
    )

    if not await _page_has_application_form(work_page):
        results["stoppedReason"] = "Application form not found — still on job listing page"
        results["errors"].append({"error": results["stoppedReason"]})
        log_activity_event(
            event_type="prep_step",
            summary=results["stoppedReason"],
            success=False,
            metadata={"applicationId": app_id, "step": "fast_replay_form_missing", "url": sanitize_url(page.url)},
        )
        return results

    if saved_fields:
        actions = merge_plan_actions_with_fields(browser_plan.get("fillActions") or [], saved_fields)
    else:
        actions = normalize_replay_actions(list(browser_plan.get("fillActions") or []))
    actions = ensure_document_upload_actions(actions, saved_fields, context)
    actions = sort_fill_actions(actions)
    if not actions:
        results["stoppedReason"] = "Saved replay plan has no fill actions"
        return results

    log_activity_event(
        event_type="prep_step",
        summary=f"Autofilling {len(actions)} saved fields (fast replay)",
        metadata={"applicationId": app_id, "step": "fast_fill", "fieldCount": len(actions)},
    )
    fill_result = await adapter.fill_page(work_page, actions, profile=context.get("profile"), fast_replay=True)
    results["filled"] = fill_result.get("filled", [])
    results["errors"].extend(fill_result.get("errors", []))
    results["skipped"] = fill_result.get("skipped", [])
    results["fields"] = saved_fields or []

    if not results["filled"]:
        results["success"] = False
        skipped_reasons = [
            str(item.get("reason") or "")
            for item in (fill_result.get("skipped") or [])
            if isinstance(item, dict)
        ]
        hint = skipped_reasons[0] if skipped_reasons else "selectors may not match the live form"
        results["stoppedReason"] = f"Quick apply opened the form but filled 0 fields — {hint}"
        log_activity_event(
            event_type="prep_step",
            summary=results["stoppedReason"],
            success=False,
            metadata={
                "applicationId": app_id,
                "step": "fast_replay_zero_fills",
                "skippedCount": len(fill_result.get("skipped") or []),
            },
        )
        if headed:
            results["browserOpen"] = True
            session._register_active(app_id)
            _defer_browser_focus(session, page)
        return results

    phone_country_field = next((f for f in (saved_fields or []) if f.get("normalizedKey") == "phone_country"), None)
    if phone_country_field and phone_country_field.get("proposedValue"):
        from app.services.application_assistant.field_fill_engine import fill_field

        country_action = {
            "selector": phone_country_field.get("selectorHint"),
            "selectorHint": phone_country_field.get("selectorHint"),
            "fieldLabel": phone_country_field.get("label"),
            "fieldId": phone_country_field.get("fieldId"),
            "normalizedKey": "phone_country",
        }
        try:
            ok, _reason = await fill_field(
                work_page,
                country_action,
                phone_country_field["proposedValue"],
                profile=context.get("profile"),
                fast_mode=True,
            )
            if ok:
                results["filled"] = [
                    action for action in results["filled"] if action.get("fieldId") != phone_country_field.get("fieldId")
                ]
                results["filled"].append(country_action)
        except Exception as exc:
            results["errors"].append({"action": country_action, "error": str(exc)})

    results["browserPlan"] = browser_plan
    filled_count = len(results["filled"])
    skipped_count = len(results.get("skipped") or [])
    error_count = len(results.get("errors") or [])
    if skipped_count or error_count:
        results["stoppedReason"] = (
            f"Filled {filled_count} of {len(actions)} saved fields — review remaining fields"
        )
    else:
        results["stoppedReason"] = "Verified fields filled — review remaining fields"
    results["success"] = True

    if headed:
        results["browserOpen"] = True
        session._register_active(app_id)
        from app.services.application_assistant.submission_watcher import start_submission_watcher

        start_submission_watcher(session, app_id)
        _defer_browser_focus(session, page)
        asyncio.create_task(session.screenshot(page, f"{app_id}_filled"))
    return results


async def _prepare_application_impl(
    *,
    application_url: str,
    adapter: Any,
    context: dict[str, Any],
    app_id: str = "",
    headed: bool = True,
) -> dict[str, Any]:
    profile_dir = profile_dir_for_app(app_id) if app_id else ""
    review_mode = bool(context.get("reviewMode"))
    background_browser = bool(context.get("backgroundBrowser", not review_mode))
    session = BrowserSession(headed=headed, profile_dir=profile_dir, background=background_browser)
    results: dict[str, Any] = {
        "success": False,
        "fields": [],
        "filled": [],
        "skipped": [],
        "screenshots": [],
        "errors": [],
        "stoppedReason": "",
    }

    try:
        nav_url = application_url
        if getattr(adapter, "name", "") == "greenhouse":
            from app.services.application_assistant.providers.greenhouse import (
                resolve_greenhouse_apply_url,
                resolve_greenhouse_form_nav_url,
            )

            nav_url = resolve_greenhouse_apply_url(
                application_url,
                company_name=str(context.get("companyName") or ""),
            )
            nav_url = resolve_greenhouse_form_nav_url(
                nav_url,
                company_name=str(context.get("companyName") or ""),
                source_url=application_url,
            )
        saved_fields = context.get("savedFields") or []
        browser_plan: dict[str, Any] | None = None
        fast_review = False
        if review_mode:
            browser_plan = resolve_review_replay_plan(
                context.get("browserPlan"),
                saved_fields,
                nav_url=nav_url,
                source_url=application_url,
                provider=getattr(adapter, "name", "") or "",
            )
            fast_review = plan_is_usable(browser_plan)
            if fast_review:
                bp = browser_plan or {}
                nav_url = str(bp.get("formNavUrl") or bp.get("navUrl") or nav_url)
                if getattr(adapter, "name", "") == "greenhouse":
                    from app.services.application_assistant.providers.greenhouse import resolve_greenhouse_form_nav_url

                    nav_url = resolve_greenhouse_form_nav_url(
                        nav_url,
                        company_name=str(context.get("companyName") or ""),
                        source_url=str(bp.get("sourceUrl") or application_url or ""),
                    )

        log_activity_event(
            event_type="prep_step",
            summary=f"Launching browser for {sanitize_url(nav_url)}",
            metadata={
                "applicationId": app_id,
                "step": "browser_start",
                "sourceUrl": sanitize_url(application_url),
                "fastReview": fast_review,
            },
        )
        await session.start()
        if not fast_review:
            await session.start_trace()
        page = await session.new_page()
        session.set_active_page(page)
        await session.close_other_pages(page)

        log_activity_event(
            event_type="prep_step",
            summary="Navigating to application page",
            metadata={"applicationId": app_id, "step": "navigate", "url": sanitize_url(nav_url)},
        )
        await page.goto(nav_url, wait_until="domcontentloaded", timeout=60000)
        expected_host = urlparse(nav_url).netloc.lower()
        actual_host = urlparse(page.url).netloc.lower()
        if expected_host and actual_host and expected_host not in actual_host and actual_host not in expected_host:
            log_activity_event(
                event_type="prep_step",
                summary=f"Unexpected page host after navigation: {actual_host}",
                success=False,
                metadata={"applicationId": app_id, "step": "navigate", "expectedHost": expected_host, "actualUrl": sanitize_url(page.url)},
            )
            await page.goto(nav_url, wait_until="networkidle", timeout=90000)
        await asyncio.sleep(0.2 if review_mode else 1)
        if not background_browser:
            try:
                await page.bring_to_front()
            except Exception:
                pass

        if review_mode and fast_review and plan_is_usable(browser_plan):
            return await _fast_review_from_plan(
                session=session,
                page=page,
                adapter=adapter,
                context={**context, "savedFields": saved_fields},
                app_id=app_id,
                headed=headed,
                nav_url=nav_url,
                application_url=application_url,
                browser_plan=browser_plan,
                results=results,
                skip_navigation=True,
            )

        if review_mode:
            log_activity_event(
                event_type="prep_step",
                summary="No saved replay plan — falling back to full form inspect",
                success=False,
                metadata={"applicationId": app_id, "step": "review_inspect_fallback"},
            )

        screenshot = await session.screenshot(page, f"{app_id}_initial")
        results["screenshots"].append(screenshot)

        if hasattr(adapter, "open_application_form"):
            log_activity_event(
                event_type="prep_step",
                summary="Opening Greenhouse apply form",
                metadata={"applicationId": app_id, "step": "click_apply"},
            )
            await adapter.open_application_form(page)
            await asyncio.sleep(1)

        work_page, use_iframe = await _detect_application_work_page(page, wait_ms=8000)
        if use_iframe:
            log_activity_event(
                event_type="prep_step",
                summary="Using embedded Greenhouse application frame",
                metadata={"applicationId": app_id, "step": "iframe"},
            )

        # Detect blockers
        blocker = await adapter.detect_blocker(work_page)
        if blocker:
            msg = blocker.get("message", "Blocker detected")
            log_activity_event(
                event_type="prep_step",
                summary=f"Blocker detected: {msg}",
                success=False,
                error=msg,
                metadata={"applicationId": app_id, "step": "blocker", "blocker": blocker.get("type")},
            )
            results["stoppedReason"] = msg
            results["blocker"] = blocker
            return results

        log_activity_event(
            event_type="prep_step",
            summary="Inspecting application form fields",
            metadata={"applicationId": app_id, "step": "inspect"},
        )
        form_fields = await adapter.inspect_application(work_page)
        mapped = adapter.map_fields(form_fields, context)
        mapped = attach_field_ids(mapped)

        if saved_fields:
            mapped = _merge_saved_fields(mapped, saved_fields)

        if review_mode:
            mapped = _refresh_special_field_values(mapped, context)
            mapped = apply_document_fields(mapped, context)
        else:
            mapped = await run_mapping_pipeline(
                mapped,
                context,
                page=work_page,
                page_url=work_page.url if hasattr(work_page, "url") else page.url,
                provider=getattr(adapter, "name", "unknown"),
                screenshot_refs=results.get("screenshots"),
                form_fields=form_fields,
            )
        mapping_settings = resolve_field_mapping_settings(context.get("assistantSettings") or {})

        approved_actions, validation_skipped, verify_fields = await build_and_validate_actions(
            work_page,
            mapped,
            mapping_settings=mapping_settings,
            review_mode=review_mode,
        )
        results["skipped"].extend(validation_skipped)

        def _fill_order(action: dict[str, Any]) -> tuple[int, str]:
            if action.get("normalizedKey") == "phone_country":
                return (2, str(action.get("fieldLabel") or ""))
            label = str(action.get("fieldLabel") or "").lower()
            if label.startswith("phone"):
                return (1, label)
            return (0, label)

        approved_actions.sort(key=_fill_order)

        for field in mapped:
            if not _field_fillable(field, review_mode=review_mode):
                if not any(s.get("field") == field.get("label") for s in validation_skipped):
                    results["skipped"].append({
                        "field": field.get("label"),
                        "reason": f"Classification: {field.get('classification')}",
                    })

        # Fill verified fields
        log_activity_event(
            event_type="prep_step",
            summary=f"Filling {len(approved_actions)} verified fields",
            metadata={"applicationId": app_id, "step": "fill", "fieldCount": len(approved_actions)},
        )
        fill_result = await adapter.fill_page(work_page, approved_actions, profile=context.get("profile"))
        results["filled"] = fill_result.get("filled", [])
        results["errors"].extend(fill_result.get("errors", []))

        # Greenhouse may reset the dial code when the phone number is typed — set country last.
        phone_country_field = next((f for f in mapped if f.get("normalizedKey") == "phone_country"), None)
        if phone_country_field and phone_country_field.get("proposedValue"):
            from app.services.application_assistant.field_fill_engine import fill_field

            country_action = {
                "selector": phone_country_field.get("selectorHint"),
                "selectorHint": phone_country_field.get("selectorHint"),
                "fieldLabel": phone_country_field.get("label"),
                "fieldId": phone_country_field.get("fieldId"),
                "normalizedKey": "phone_country",
            }
            try:
                ok, _reason = await fill_field(
                    work_page,
                    country_action,
                    phone_country_field["proposedValue"],
                    profile=context.get("profile"),
                )
                if ok:
                    results["filled"] = [
                        a for a in results["filled"] if a.get("fieldId") != phone_country_field.get("fieldId")
                    ]
                    results["filled"].append(country_action)
                    results["errors"] = [
                        e
                        for e in results["errors"]
                        if (e.get("action") or {}).get("fieldId") != phone_country_field.get("fieldId")
                    ]
            except Exception as exc:
                results["errors"] = [
                    e
                    for e in results["errors"]
                    if (e.get("action") or {}).get("fieldId") != phone_country_field.get("fieldId")
                ]
                results["errors"].append({"action": country_action, "error": str(exc)})

        results["fillCheckpoints"] = await verify_filled_fields(work_page, verify_fields)

        filled_labels = {a.get("fieldLabel") for a in results["filled"]}
        for field in mapped:
            if field.get("fieldId") in {c.get("fieldId") for c in results.get("fillCheckpoints", []) if c.get("verified")}:
                field["filled"] = True
            elif field.get("label") in filled_labels:
                field["filled"] = True

        results["fields"] = mapped

        plan_actions = approved_actions or build_replay_actions_from_fields(mapped)
        form_nav_url = page.url
        if not use_iframe:
            try:
                form_nav_url = work_page.url or page.url
            except Exception:
                form_nav_url = page.url
        results["browserPlan"] = build_browser_plan(
            nav_url=nav_url,
            source_url=application_url,
            provider=getattr(adapter, "name", "") or "",
            fill_actions=plan_actions,
            use_iframe=use_iframe,
            iframe_selector=_DEFAULT_IFRAME_SELECTOR,
            form_nav_url=form_nav_url,
        )

        # Capture state
        state = await adapter.capture_state(work_page)
        results["state"] = state

        # Final check — never proceed to submit
        if await adapter.is_final_step(work_page):
            results["stoppedReason"] = "Reached final step — stopping before submission"
        else:
            results["stoppedReason"] = "Verified fields filled — review remaining fields"

        screenshot = await session.screenshot(page, f"{app_id}_filled")
        results["screenshots"].append(screenshot)

        results["success"] = True
        log_activity_event(
            event_type="prep_step",
            summary=results["stoppedReason"] or "Prep step finished",
            metadata={
                "applicationId": app_id,
                "step": "done",
                "filledCount": len(results.get("filled", [])),
                "fieldCount": len(mapped),
            },
        )

        # Keep browser open only for user-driven quick apply — prep runs headless-ish and closes.
        if headed and review_mode:
            results["browserOpen"] = True
            session._register_active(app_id)
            from app.services.application_assistant.submission_watcher import start_submission_watcher

            start_submission_watcher(session, app_id)
            _defer_browser_focus(session, page)
            return results

        return results

    except Exception as exc:
        error = str(exc) or repr(exc)
        log_activity_event(
            event_type="prep_error",
            summary=f"Prep error: {error}",
            success=False,
            error=error,
            metadata={"applicationId": app_id, "step": "error", "errorType": type(exc).__name__},
        )
        results["errors"].append({"error": error, "type": type(exc).__name__})
        results["stoppedReason"] = f"Error: {error}"

    finally:
        if not headed or not results.get("browserOpen"):
            trace_path = await session.stop_trace(f"{app_id}_trace")
            results["tracePath"] = trace_path
            await session.close()

    return results


def get_active_session(app_id: str) -> BrowserSession | None:
    """Return a registered session; context close callbacks remove stale entries."""
    return _active_sessions.get(app_id)


def list_active_session_ids() -> list[str]:
    """Application ids with a live headed browser session."""
    alive: list[str] = []
    for app_id in list(_active_sessions.keys()):
        if get_active_session(app_id):
            alive.append(app_id)
    return sorted(alive)


def discard_session(app_id: str) -> None:
    from app.services.application_assistant.submission_watcher import stop_submission_watcher

    stop_submission_watcher(app_id)
    session = _active_sessions.pop(app_id, None)
    if session:
        session.detach()


async def focus_session(app_id: str) -> bool:
    session = _active_sessions.get(app_id)
    if not session:
        return False
    if sys.platform == "win32":
        await run_playwright_async(session.focus())
    else:
        await session.focus()
    return True


async def cleanup_stale_session(app_id: str, db: Any = None) -> bool:
    """Remove dead session registry entry and restore draft status if needed."""
    discard_session(app_id)
    if db is not None:
        _restore_draft_after_browser_closed(db, app_id)
    return True


def _restore_draft_after_browser_closed(db: Any, app_id: str) -> None:
    """Mark orphaned browser runs stopped and move in_progress drafts back to review."""
    from app.db.store import now_iso
    from app.services.application_assistant.browser_replay import has_persisted_autofill_plan
    from app.services.application_assistant.persistence import (
        get_active_browser_run_for_app,
        get_application_draft,
        update_application_draft,
        update_browser_run,
    )

    active_run = get_active_browser_run_for_app(db, app_id)
    if active_run and active_run.get("status") == "running":
        update_browser_run(
            db,
            str(active_run.get("id") or ""),
            {
                "status": "stopped",
                "endedAt": now_iso(),
                "error": "Browser closed",
            },
        )

    draft = get_application_draft(db, app_id)
    if draft and draft.get("status") == "in_progress":
        next_status = "needs_review" if has_persisted_autofill_plan(draft) else "ready_to_prepare"
        update_application_draft(db, app_id, {"status": next_status})


def _sync_cleanup_closed_session(app_id: str) -> None:
    """Best-effort DB cleanup when the user closes Chrome manually."""
    try:
        from app.db.store import session_scope

        with session_scope() as db:
            _restore_draft_after_browser_closed(db, app_id)
    except Exception:
        pass


async def close_session(app_id: str) -> bool:
    if sys.platform == "win32":
        running_loop = asyncio.get_running_loop()
        if running_loop is not _playwright_loop:
            return await run_playwright_async(close_session(app_id))

    from app.services.application_assistant.submission_watcher import finalize_submission_watch, stop_submission_watcher

    session = _active_sessions.get(app_id)
    if session:
        try:
            await _await_bounded(finalize_submission_watch(app_id, session), timeout=4.0)
        except Exception:
            pass
    stop_submission_watcher(app_id)
    session = _active_sessions.pop(app_id, None)
    if not session:
        return False
    try:
        await session.close()
    except Exception:
        session.detach()
    return True


def _kill_chromium_using_profile(profile_dir: str) -> int:
    """Best-effort kill of orphan Chromium processes holding the shared profile."""
    profile_key = str(profile_dir).replace("/", "\\")
    profile_pattern = profile_key.replace("\\", "\\\\")
    killed = 0
    if sys.platform == "win32":
        try:
            ps_cmd = (
                "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
                f"Where-Object {{ $_.CommandLine -like '*{profile_pattern}*' }} | "
                "ForEach-Object { $_.ProcessId }"
            )
            output = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                text=True,
                errors="ignore",
                timeout=20,
            )
            for pid_text in output.splitlines():
                pid_text = pid_text.strip()
                if not pid_text.isdigit():
                    continue
                subprocess.run(
                    ["taskkill", "/F", "/PID", pid_text],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                )
                killed += 1
        except Exception:
            pass
    return killed


async def close_all_sessions() -> int:
    """Close every registered browser session (e.g. stale test windows)."""
    closed = 0
    for app_id in list(_active_sessions.keys()):
        if await close_session(app_id):
            closed += 1
    if closed:
        await asyncio.sleep(0.5)
    return closed


def shutdown_playwright_worker(timeout: float = 10) -> None:
    """Close review sessions and stop the shared Playwright worker loop."""
    global _playwright_loop, _playwright_thread

    loop = _playwright_loop
    thread = _playwright_thread
    if loop is None or thread is None:
        return
    if threading.current_thread() is thread:
        loop.stop()
        return

    if loop.is_running():
        try:
            future = asyncio.run_coroutine_threadsafe(close_all_sessions(), loop)
            future.result(timeout=timeout)
        except Exception:
            pass
        try:
            loop.call_soon_threadsafe(loop.stop)
        except RuntimeError:
            pass
    thread.join(timeout=timeout)
    if not thread.is_alive() and not loop.is_closed():
        try:
            loop.close()
        except RuntimeError:
            pass
    with _playwright_lock:
        if _playwright_loop is loop:
            _playwright_loop = None
        if _playwright_thread is thread:
            _playwright_thread = None


atexit.register(shutdown_playwright_worker)
