"""Diagnose Datadog quick apply fill results."""
import asyncio
import time

from playwright.async_api import async_playwright

from app.db.store import get_kv, session_scope
from app.services.application_assistant.browser_replay import (
    ensure_document_upload_actions,
    merge_plan_actions_with_fields,
)
from app.services.application_assistant.field_fill_engine import fill_page_fast_replay
from app.services.application_assistant.persistence import get_application_draft

APP_ID = "app_241292ce-ea40-4dac-afcd-8bd2ee355dd9"
URL = "https://careers.datadoghq.com/detail/8088589/?gh_jid=8088589#app"


from app.services.application_assistant.css_selectors import normalize_css_selector


async def probe_field_types(frame) -> None:
    probes = [
        "#resume",
        "#question_68268068",
        '[id="question_68268070[]"]',
        '[id="question_68268071[]"]',
        "#1757",
    ]
    for sel in probes:
        norm = normalize_css_selector(sel)
        info = await frame.evaluate(
            """(selector) => {
                const el = document.querySelector(selector);
                if (!el) return { selector, found: false };
                const tag = el.tagName.toLowerCase();
                const type = (el.type || '').toLowerCase();
                const role = el.getAttribute('role') || '';
                return { selector, found: true, tag, type, role };
            }""",
            norm,
        )
        print("DOM", info)


async def main() -> None:
    with session_scope() as db:
        draft = get_application_draft(db, APP_ID)
        plan = draft.get("browserPlan") or {}
        fields = draft.get("fields") or []
        ctx = {
            "documents": get_kv(db, "documents") or {},
            "profile": get_kv(db, "profile") or {},
        }
    actions = ensure_document_upload_actions(
        merge_plan_actions_with_fields(plan.get("fillActions") or [], fields),
        fields,
        ctx,
    )
    print("actions:", len(actions))

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(8000)
        iframe = await page.query_selector("iframe[src*='greenhouse.io']")
        frame = await iframe.content_frame() if iframe else page
        await probe_field_types(frame)
        started = time.perf_counter()
        result = await fill_page_fast_replay(frame, actions, profile=ctx.get("profile"))
        elapsed = time.perf_counter() - started
        print(f"\nfill elapsed: {elapsed:.1f}s")
        print("filled:", len(result.get("filled") or []))
        for item in result.get("filled") or []:
            if isinstance(item, dict):
                print("  OK", (item.get("fieldLabel") or item.get("selector") or "")[:50])
        print("skipped:", len(result.get("skipped") or []))
        for item in result.get("skipped") or []:
            action = item.get("action") or {}
            print("  SKIP", (action.get("fieldLabel") or action.get("selector") or "")[:50], "|", item.get("reason"))
        print("errors:", result.get("errors"))
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
