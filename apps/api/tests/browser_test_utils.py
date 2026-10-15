"""Shared browser test utilities using PlaywrightBrowserPool.

Reuses a single memory-optimized headless Chromium daemon across tests,
issuing isolated, ephemeral BrowserContexts (~10-30ms) instead of launching
and tearing down separate browser processes per test.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from app.services.application_assistant.browser_pool import PlaywrightBrowserPool
from app.services.application_assistant.browser_runner import run_playwright


def eval_in_pooled_page(
    html: str,
    action: Callable[[Any], Any],
    *,
    timeout: float = 30.0,
    viewport: dict[str, int] | None = None,
    abort_network: bool = False,
) -> Any:
    """Render HTML in an isolated pooled BrowserContext, run action(page), and return the result."""

    async def _go():
        pool = PlaywrightBrowserPool.get_instance()
        context_opts = {"viewport": viewport} if viewport else None
        context = await pool.acquire_context(context_opts=context_opts)
        try:
            page = await context.new_page()
            if abort_network:
                await page.route("**/*", lambda route: route.abort())
            await page.set_content(html)
            res = action(page)
            if asyncio.iscoroutine(res):
                return await res
            return res
        finally:
            await pool.release_context(context)

    return run_playwright(_go(), timeout=timeout)
