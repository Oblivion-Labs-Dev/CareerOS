"""Detect job application submission in Playwright review browsers."""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Any

from app.db.store import session_scope, now_iso
from app.services.application_assistant.persistence import get_application_draft, update_application_draft
from app.services.application_assistant.qwen_activity import log_activity_event

if TYPE_CHECKING:
    from app.services.application_assistant.browser_runner import BrowserSession

CONFIRMATION_URL_PATTERN = re.compile(
    r"(thank.?you|thanks for applying|application (?:has been )?(?:received|submitted|sent|complete)"
    r"|successfully applied|submission (?:received|complete|confirmed)|confirmation"
    r"|you.?ve applied|application submitted)",
    re.I,
)

GREENHOUSE_CONFIRMATION_URL = re.compile(r"greenhouse\.io/.*/confirmation", re.I)
GREENHOUSE_APPLICATION_SUBMITTED_URL = re.compile(
    r"greenhouse\.io/.+/jobs/\d+.*(?:application_id=|[?&]applied=)",
    re.I,
)
GREENHOUSE_EMBED_HOST = re.compile(r"(?:boards|job-boards)\.greenhouse\.io", re.I)
CAREERS_EMBED_HOST = re.compile(r"^https?://careers\.", re.I)
THANK_YOU_TEXT = re.compile(
    r"thank you for applying|thanks for applying|thank you for your interest"
    r"|application (?:has been )?(?:received|submitted)|your application has been submitted"
    r"|successfully applied|we (?:have )?received your application|you.?ve applied"
    r"|application submitted",
    re.I,
)
WORKDAY_CONFIRMATION_URL = re.compile(
    r"myworkdaysite\.com|myworkdayjobs\.com", re.I,
)

SUBMIT_INIT_SCRIPT = """
(() => {
  if (window.__careerosSubmitTrackerInstalled) return;
  window.__careerosSubmitTrackerInstalled = true;

  function isConfirmationUrl(href) {
    return /thank.?you|thanks for applying|application (?:has been )?(?:received|submitted|sent|complete)|successfully applied|submission (?:received|complete|confirmed)|confirmation|you.?ve applied|application submitted/i.test(href)
      || /greenhouse\\.io\\/.*\\/confirmation/i.test(href)
      || (/greenhouse\\.io\\/.*\\/jobs\\/\\d+/i.test(href) && /(?:application_id=|[?&]applied=)/i.test(href))
      || ((/myworkdaysite\\.com|myworkdayjobs\\.com/i.test(href)) && /(confirmation|success|complete)/i.test(href));
  }

  function isGreenhouseSuccess(doc) {
    const href = doc.location.href;
    if (!/greenhouse\\.io/i.test(href)) return false;
    if (isConfirmationUrl(href)) return true;
    if (/(?:application_id=|[?&]applied=)/i.test(href) && /\\/jobs\\/\\d+/i.test(href)) return true;
    if (doc.querySelector('[data-qa="application-success"], [data-qa="confirmation"], #application_confirmation, .application-confirmation, [class*="ApplicationConfirmation"], [class*="confirmation"]')) {
      return true;
    }
    const text = (doc.body?.innerText || '').slice(0, 12000);
    const hasThankYou = /thank you for applying|thanks for applying|thank you for your interest|application (?:has been )?(?:received|submitted)|your application has been submitted|successfully applied|we (?:have )?received your application|you.?ve applied/i.test(text);
    if (!hasThankYou) return false;
    if (/\\/jobs\\/\\d+\\/confirmation/i.test(href)) return true;
    if (/(?:application_id=|[?&]applied=)/i.test(href)) return true;
    if (/\\/jobs\\/\\d+/i.test(href)) {
      const fillable = doc.querySelectorAll('input:not([type="hidden"]):not([type="submit"]):not([type="button"]), select, textarea').length;
      return fillable < 10;
    }
    if (/boards\\.greenhouse\\.io\\/embed/i.test(href)) {
      const fillable = doc.querySelectorAll('input:not([type="hidden"]):not([type="submit"]):not([type="button"]), select, textarea').length;
      return fillable < 8;
    }
    return false;
  }

  function isWorkdaySuccess(doc) {
    if (!/myworkdaysite\\.com|myworkdayjobs\\.com/i.test(doc.location.href)) return false;
    const text = (doc.body?.innerText || '').slice(0, 8000);
    if (/thank you for applying|application (?:has been )?submitted|successfully applied/i.test(text)) return true;
    return !!doc.querySelector('[data-automation-id="applicationConfirmation"], [data-automation-id="successMessage"], [data-automation-id="confirmationPage"]');
  }

  function isEmbeddedCareersSuccess(doc) {
    const href = doc.location.href;
    if (!/^https?:\\/\\/careers\\./i.test(href)) return false;
    if (isConfirmationUrl(href)) return true;
    const text = (doc.body?.innerText || '').slice(0, 12000);
    if (!/thank you for applying|thanks for applying|application (?:has been )?(?:received|submitted)|successfully applied|you.?ve applied/i.test(text)) {
      return false;
    }
    const fillable = doc.querySelectorAll('input:not([type="hidden"]):not([type="submit"]):not([type="button"]), select, textarea').length;
    return fillable < 12;
  }

  function detectSubmission(doc) {
    if (isConfirmationUrl(doc.location.href)) return { success: true, trigger: 'confirmation_url' };
    if (isWorkdaySuccess(doc)) return { success: true, trigger: 'workday_confirmation' };
    if (isGreenhouseSuccess(doc)) return { success: true, trigger: 'greenhouse_confirmation' };
    if (isEmbeddedCareersSuccess(doc)) return { success: true, trigger: 'careers_embed_confirmation' };
    return { success: false, trigger: '' };
  }

  function detectSubmissionDeep(rootDoc) {
    const direct = detectSubmission(rootDoc);
    if (direct.success) return direct;
    for (const iframe of rootDoc.querySelectorAll('iframe')) {
      try {
        const doc = iframe.contentDocument;
        if (!doc) continue;
        const nested = detectSubmission(doc);
        if (nested.success) return nested;
      } catch (err) {
        /* cross-origin iframe — Playwright frame polling handles these */
      }
    }
    return { success: false, trigger: '' };
  }

  window.__careerosDetectSubmission = detectSubmissionDeep;

  function reportIfSubmitted(trigger) {
    const detected = detectSubmissionDeep(document);
    if (detected.success && typeof window.__careerosReportSubmission === 'function') {
      window.__careerosReportSubmission(trigger || detected.trigger, location.href);
    }
  }

  const submitPatterns = [/\\bsubmit\\b/i, /send application/i, /submit application/i, /apply for (this )?job/i, /confirm application/i, /finish application/i];

  function matchesSubmit(text) {
    const t = (text || '').replace(/\\s+/g, ' ').trim();
    if (!t) return false;
    return submitPatterns.some((p) => p.test(t));
  }

  document.addEventListener('click', (e) => {
    const el = e.target && e.target.closest ? e.target.closest('button, input[type="submit"], a[role="button"], [role="button"]') : null;
    if (!el) return;
    const text = (el.innerText || el.getAttribute('aria-label') || el.value || '').trim();
    if (!matchesSubmit(text)) return;
    setTimeout(() => reportIfSubmitted('button_click'), 2500);
    setTimeout(() => reportIfSubmitted('button_click_delayed'), 8000);
  }, true);

  reportIfSubmitted('page_load');
  window.addEventListener('load', () => reportIfSubmitted('page_load'));
  window.addEventListener('hashchange', () => reportIfSubmitted('hashchange'));
  const pushState = history.pushState;
  history.pushState = function() {
    pushState.apply(history, arguments);
    setTimeout(() => reportIfSubmitted('spa_navigation'), 500);
  };
  window.addEventListener('popstate', () => setTimeout(() => reportIfSubmitted('spa_navigation'), 500));
})();
"""

DETECTION_EVAL = """
() => {
  if (typeof window.__careerosDetectSubmission === 'function') {
    const detected = window.__careerosDetectSubmission(document);
    return { ...detected, url: location.href };
  }
  const href = location.href;
  const urlHit = /thank.?you|thanks for applying|application (?:has been )?(?:received|submitted|sent|complete)|successfully applied|submission (?:received|complete|confirmed)|confirmation|you.?ve applied|application submitted/i.test(href)
    || /greenhouse\\.io\\/.*\\/confirmation/i.test(href)
    || (/greenhouse\\.io\\/.*\\/jobs\\/\\d+/i.test(href) && /(?:application_id=|[?&]applied=)/i.test(href));
  return { success: urlHit, trigger: urlHit ? 'confirmation_url' : '', url: href };
}
"""


def _page_frames(page: Any) -> list[Any]:
    try:
        return list(page.frames)
    except Exception:
        return []


def _is_embedded_careers_confirmation(url: str, body_text: str) -> bool:
    if not CAREERS_EMBED_HOST.search(url or ""):
        return False
    if CONFIRMATION_URL_PATTERN.search(url):
        return True
    if not THANK_YOU_TEXT.search(body_text or ""):
        return False
    return True

_watchers: dict[str, "SubmissionWatcher"] = {}


def is_submission_confirmation_url(url: str) -> bool:
    if CONFIRMATION_URL_PATTERN.search(url):
        return True
    if GREENHOUSE_CONFIRMATION_URL.search(url):
        return True
    if GREENHOUSE_APPLICATION_SUBMITTED_URL.search(url):
        return True
    if GREENHOUSE_EMBED_HOST.search(url) and re.search(
        r"(confirmation|application_id=|[?&]applied=|submitted)", url, re.I
    ):
        return True
    if WORKDAY_CONFIRMATION_URL.search(url) and re.search(r"(confirmation|success|complete)", url, re.I):
        return True
    return False


def record_application_submission(app_id: str, trigger: str, url: str) -> bool:
    """Mark an AA draft submitted after auto-detection from the review browser."""
    with session_scope() as db:
        draft = get_application_draft(db, app_id)
        if not draft:
            return False
        if draft.get("status") == "submitted_manually":
            return True

        previous = draft.get("status") or "needs_review"
        update_application_draft(
            db,
            app_id,
            {
                "status": "submitted_manually",
                "previousStatus": previous,
                "submittedAt": now_iso(),
                "submissionSource": "auto",
                "submissionTrigger": trigger or "unknown",
                "submissionUrl": url or draft.get("jobUrl", ""),
            },
        )
        log_activity_event(
            event_type="application_submitted",
            summary=f"Application auto-marked submitted ({trigger or 'detected'})",
            metadata={
                "applicationId": app_id,
                "trigger": trigger,
                "url": url,
                "source": "auto",
            },
        )
        db.commit()
    return True


class SubmissionWatcher:
    def __init__(self, app_id: str):
        self.app_id = app_id
        self.recorded = False
        self._pages: set[int] = set()
        self._tasks: list[asyncio.Task[Any]] = []
        self._context_exposed = False

    def cancel(self) -> None:
        for task in self._tasks:
            if not task.done():
                task.cancel()
        self._tasks.clear()
        self._pages.clear()

    def _report(self, trigger: str, url: str) -> None:
        if self.recorded:
            return
        self.recorded = True
        record_application_submission(self.app_id, trigger, url)
        stop_submission_watcher(self.app_id)

    async def attach(self, session: BrowserSession) -> None:
        context = session._context
        if not context:
            return

        if not self._context_exposed:
            try:
                await context.expose_function(
                    "__careerosReportSubmission",
                    lambda trigger, url: self._report(str(trigger or ""), str(url or "")),
                )
                self._context_exposed = True
            except Exception:
                pass

        try:
            await context.add_init_script(SUBMIT_INIT_SCRIPT)
        except Exception:
            pass

        for page in list(context.pages):
            await self._attach_page(page)

        def on_page(page: Any) -> None:
            self._tasks.append(asyncio.create_task(self._attach_page(page)))

        context.on("page", on_page)
        self._tasks.append(asyncio.create_task(self._poll_loop(session)))

    async def _attach_page(self, page: Any) -> None:
        page_id = id(page)
        if page_id in self._pages or page.is_closed():
            return
        self._pages.add(page_id)

        async def on_nav(frame: Any) -> None:
            if self.recorded:
                return
            await self._check_frame(frame, "navigation")

        page.on("framenavigated", lambda frame: self._tasks.append(asyncio.create_task(on_nav(frame))))

        try:
            await page.evaluate(SUBMIT_INIT_SCRIPT)
        except Exception:
            pass
        for frame in _page_frames(page):
            try:
                await frame.evaluate(SUBMIT_INIT_SCRIPT)
            except Exception:
                pass
        await self._check_page(page, "load")

    async def _check_frame(self, frame: Any, trigger: str) -> None:
        if self.recorded:
            return
        try:
            if frame.is_detached():
                return
        except Exception:
            return

        url = ""
        try:
            url = frame.url or ""
        except Exception:
            pass

        if url and is_submission_confirmation_url(url):
            self._report(f"{trigger}_url", url)
            return

        try:
            result = await frame.evaluate(DETECTION_EVAL)
            if result.get("success"):
                self._report(str(result.get("trigger") or trigger), str(result.get("url") or url))
                return
        except Exception:
            pass

        if url and CAREERS_EMBED_HOST.search(url):
            try:
                body_text = str(await frame.evaluate("() => (document.body?.innerText || '').slice(0, 12000)"))
                if _is_embedded_careers_confirmation(url, body_text):
                    self._report("careers_embed_confirmation", url)
            except Exception:
                pass

    async def _check_page(self, page: Any, trigger: str) -> None:
        if self.recorded or page.is_closed():
            return
        for frame in _page_frames(page):
            await self._check_frame(frame, trigger)

    async def _poll_loop(self, session: BrowserSession) -> None:
        while not self.recorded:
            if not session.is_alive():
                await self._final_check(session)
                break
            context = session._context
            if context:
                for page in list(context.pages):
                    if not page.is_closed():
                        await self._check_page(page, "poll")
            await asyncio.sleep(2.5)

    async def _final_check(self, session: BrowserSession) -> None:
        """One last pass before the browser session ends."""
        if self.recorded:
            return
        context = session._context
        if not context:
            return
        for page in list(context.pages):
            if not page.is_closed():
                await self._check_page(page, "final_check")


def start_submission_watcher(session: BrowserSession, app_id: str) -> None:
    """Begin watching an active headed browser for submission confirmation."""
    if app_id in _watchers:
        return

    from app.services.application_assistant.browser_runner import _ensure_playwright_loop

    watcher = SubmissionWatcher(app_id)
    _watchers[app_id] = watcher
    loop = _ensure_playwright_loop()
    asyncio.run_coroutine_threadsafe(watcher.attach(session), loop)


def finalize_submission_watch_sync(app_id: str, session: "BrowserSession") -> None:
    """Best-effort sync wrapper before the browser context is torn down."""
    watcher = _watchers.get(app_id)
    if not watcher or watcher.recorded:
        return
    from app.services.application_assistant.browser_runner import _ensure_playwright_loop

    loop = _ensure_playwright_loop()
    future = asyncio.run_coroutine_threadsafe(watcher._final_check(session), loop)
    try:
        future.result(timeout=4)
    except Exception:
        pass


async def finalize_submission_watch(app_id: str, session: "BrowserSession") -> None:
    """Run a last submission check before tearing down the review browser."""
    watcher = _watchers.get(app_id)
    if watcher and not watcher.recorded:
        await watcher._final_check(session)


def stop_submission_watcher(app_id: str) -> None:
    watcher = _watchers.pop(app_id, None)
    if watcher:
        watcher.cancel()
