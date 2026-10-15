"""Playwright Headless Browser Context Pooling Service.

Provides a shared headless Browser singleton for autonomous batch applications,
allowing multiple concurrent workers or sequential jobs to acquire lightweight
isolated BrowserContext instances (~30-50MB RAM each) rather than launching a
heavy separate Chromium browser process (300-500MB RAM) per job.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any
from weakref import WeakSet

from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

logger = logging.getLogger("career_os.application_assistant.browser_pool")

# Default memory-saving flags for pooled headless Chromium instances
DEFAULT_POOLED_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-http2",
    "--disable-gpu",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-sync",
    "--disable-external-intent-requests",
    "--no-default-browser-check",
    "--mute-audio",
]


class PlaywrightBrowserPool:
    """Singleton managing a shared headless Chromium browser process and issuing isolated contexts."""

    _instance: PlaywrightBrowserPool | None = None

    def __init__(self, max_uses: int = 50) -> None:
        self._max_uses = max_uses
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._active_contexts: WeakSet[BrowserContext] = WeakSet()
        self._lock = asyncio.Lock()
        self._uses_count = 0
        self._is_closing = False

    @classmethod
    def get_instance(cls, max_uses: int = 50) -> PlaywrightBrowserPool:
        if cls._instance is None:
            cls._instance = cls(max_uses=max_uses)
        return cls._instance

    @classmethod
    def is_pool_enabled(cls) -> bool:
        """Check if pooling is enabled via environment variable (default True)."""
        val = os.environ.get("CAREEROS_DISABLE_BROWSER_POOL", "").strip().lower()
        return val not in ("1", "true", "yes", "on")

    async def _ensure_browser(self, launch_args: list[str] | None = None) -> Browser:
        """Ensure the shared headless browser process is running and connected."""
        if self._browser is not None and self._browser.is_connected():
            return self._browser

        async with self._lock:
            # Re-check under lock
            if self._browser is not None and self._browser.is_connected():
                return self._browser

            # Tear down stale playwright if needed
            if self._browser is not None:
                try:
                    await self._browser.close()
                except Exception as e:
                    logger.debug("Error closing stale browser: %s", e)
                self._browser = None

            if self._playwright is None:
                logger.info("Starting shared Playwright instance for browser pool")
                self._playwright = await async_playwright().start()

            args = launch_args if launch_args is not None else DEFAULT_POOLED_LAUNCH_ARGS
            logger.info("Launching shared headless Chromium browser with args: %s", args)
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=args,
            )
            self._uses_count = 0
            logger.info("Shared headless Chromium browser started successfully")
            return self._browser

    async def acquire_context(
        self,
        context_opts: dict[str, Any] | None = None,
        launch_args: list[str] | None = None,
    ) -> BrowserContext:
        """Acquire a fresh, isolated BrowserContext from the shared headless browser."""
        if self._is_closing:
            raise RuntimeError("Cannot acquire context: PlaywrightBrowserPool is closing")

        browser = await self._ensure_browser(launch_args)
        opts = context_opts or {}

        # Create isolated context
        context = await browser.new_context(**opts)
        self._active_contexts.add(context)
        self._uses_count += 1

        logger.debug(
            "Acquired pooled BrowserContext (active: %d, total uses: %d)",
            len(self._active_contexts),
            self._uses_count,
        )
        return context

    async def release_context(self, context: BrowserContext | None) -> None:
        """Cleanly close an acquired context and evaluate pool recycling."""
        if context is None:
            return

        try:
            await context.close()
        except Exception as e:
            logger.debug("Error closing pooled BrowserContext: %s", e)
        finally:
            self._active_contexts.discard(context)

        logger.debug(
            "Released pooled BrowserContext (remaining active: %d, uses: %d/%d)",
            len(self._active_contexts),
            self._uses_count,
            self._max_uses,
        )

        # Auto-recycle check: if max uses reached and no other active contexts, recycle browser
        if self._uses_count >= self._max_uses and len(self._active_contexts) == 0:
            asyncio.create_task(self._recycle_browser())

    async def _recycle_browser(self) -> None:
        """Recycle the shared browser process to reclaim memory after max_uses."""
        async with self._lock:
            if len(self._active_contexts) > 0 or self._uses_count < self._max_uses:
                return
            logger.info(
                "Recycling shared headless browser after %d applications to maintain low memory profile",
                self._uses_count,
            )
            if self._browser is not None:
                try:
                    await self._browser.close()
                except Exception as e:
                    logger.debug("Error during browser recycling: %s", e)
                self._browser = None
            self._uses_count = 0

    async def close(self) -> None:
        """Gracefully shut down all active contexts and the shared browser process."""
        self._is_closing = True
        async with self._lock:
            logger.info("Closing PlaywrightBrowserPool and all active contexts (%d active)", len(self._active_contexts))
            for ctx in list(self._active_contexts):
                try:
                    await ctx.close()
                except Exception as e:
                    logger.debug("Error closing context during pool shutdown: %s", e)
            self._active_contexts.clear()

            if self._browser is not None:
                try:
                    await self._browser.close()
                except Exception as e:
                    logger.debug("Error closing shared browser: %s", e)
                self._browser = None

            if self._playwright is not None:
                try:
                    await self._playwright.stop()
                except Exception as e:
                    logger.debug("Error stopping shared Playwright: %s", e)
                self._playwright = None

            self._uses_count = 0
            self._is_closing = False
            logger.info("PlaywrightBrowserPool shut down completely")
