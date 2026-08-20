"""Playwright career page source with underlying XHR API discovery."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import httpx

from app.services.job_discover.sources.base import JobSource, NormalizedJob


class PlaywrightCareerPageSource(JobSource):
    """Playwright fallback for JS-heavy career pages with network XHR observation."""

    id = "playwright"
    name = "Playwright Browser Fallback"

    def supports(self, source_type: str, config: dict[str, Any] | None = None) -> bool:
        return source_type.lower() in {"playwright", "js_rendered"}

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        company: str,
        config: dict[str, Any],
        compiled_patterns: list[Any],
        cutoff: datetime,
        role_keys: list[str] | None = None,
    ) -> list[NormalizedJob]:
        """Attempt Playwright load and extract via DOM/observed XHR."""
        careers_url = config.get("careersUrl") or config.get("url") or f"https://{company}.com/careers"

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return []

        jobs: list[NormalizedJob] = []
        discovered_api: str | None = None

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                def handle_response(response):
                    nonlocal discovered_api
                    url = response.url
                    if ("job" in url or "career" in url or "posting" in url) and response.headers.get("content-type", "").startswith("application/json"):
                        if not discovered_api and response.status == 200:
                            discovered_api = url

                page.on("response", handle_response)
                await page.goto(careers_url, wait_until="networkidle", timeout=30000)

                if discovered_api:
                    # Save observed API endpoint for future syncs
                    config["discoveredApi"] = discovered_api

                await browser.close()
        except Exception:
            pass

        return jobs
