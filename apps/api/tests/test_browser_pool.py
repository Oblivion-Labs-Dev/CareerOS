"""Tests for PlaywrightBrowserPool."""

import asyncio
import os
import pytest

from app.services.application_assistant.browser_pool import PlaywrightBrowserPool


def test_browser_pool_singleton():
    pool1 = PlaywrightBrowserPool.get_instance()
    pool2 = PlaywrightBrowserPool.get_instance()
    assert pool1 is pool2


def test_browser_pool_enabled_toggle(monkeypatch):
    monkeypatch.delenv("CAREEROS_DISABLE_BROWSER_POOL", raising=False)
    assert PlaywrightBrowserPool.is_pool_enabled() is True

    monkeypatch.setenv("CAREEROS_DISABLE_BROWSER_POOL", "1")
    assert PlaywrightBrowserPool.is_pool_enabled() is False

    monkeypatch.setenv("CAREEROS_DISABLE_BROWSER_POOL", "true")
    assert PlaywrightBrowserPool.is_pool_enabled() is False

    monkeypatch.setenv("CAREEROS_DISABLE_BROWSER_POOL", "0")
    assert PlaywrightBrowserPool.is_pool_enabled() is True


def test_browser_pool_context_isolation_and_lifecycle():
    async def _run():
        pool = PlaywrightBrowserPool(max_uses=10)

        try:
            # Acquire two concurrent contexts from the same shared browser
            ctx1 = await pool.acquire_context(context_opts={"user_agent": "Context1-Agent"})
            ctx2 = await pool.acquire_context(context_opts={"user_agent": "Context2-Agent"})

            assert ctx1 is not ctx2
            assert len(pool._active_contexts) == 2
            assert pool._browser is not None
            assert pool._browser.is_connected()

            # Check cookie isolation between contexts
            await ctx1.add_cookies([{
                "name": "test_cookie",
                "value": "ctx1_val",
                "domain": "example.com",
                "path": "/",
            }])

            cookies1 = await ctx1.cookies("https://example.com")
            cookies2 = await ctx2.cookies("https://example.com")

            assert any(c["name"] == "test_cookie" and c["value"] == "ctx1_val" for c in cookies1)
            assert not any(c["name"] == "test_cookie" for c in cookies2), "Context 2 must not see Context 1 cookies!"

            # Release ctx1
            await pool.release_context(ctx1)
            assert len(pool._active_contexts) == 1

            # Release ctx2
            await pool.release_context(ctx2)
            assert len(pool._active_contexts) == 0

            # Shared browser should remain connected for subsequent jobs
            assert pool._browser.is_connected()

        finally:
            await pool.close()
            assert pool._browser is None
            assert pool._playwright is None

    asyncio.run(_run())


def test_browser_pool_auto_recycle():
    async def _run():
        pool = PlaywrightBrowserPool(max_uses=2)

        try:
            ctx1 = await pool.acquire_context()
            await pool.release_context(ctx1)
            assert pool._uses_count == 1

            ctx2 = await pool.acquire_context()
            await pool.release_context(ctx2)
            # uses_count reached 2, give background task a moment
            await asyncio.sleep(0.1)

            assert pool._uses_count == 0 or pool._browser is None
        finally:
            await pool.close()

    asyncio.run(_run())
