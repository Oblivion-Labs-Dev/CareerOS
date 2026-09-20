"""Stealth Browser Profile & Anti-Fingerprinting Engine.

Injects evasive scripts and humanized interaction patterns into Playwright sessions
to bypass bot-detection systems (Cloudflare Turnstile, DataDome, Arkose, reCAPTCHA).
"""

from __future__ import annotations

import asyncio
import math
import random
from typing import Any

from playwright.async_api import Page, BrowserContext

STEALTH_EVASION_JS = """
(() => {
    // 1. Hide automation controller
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
    });

    // 2. Mock plugins & mimeTypes
    Object.defineProperty(navigator, 'plugins', {
        get: () => [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
            { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' }
        ],
    });

    // 3. Mock languages
    Object.defineProperty(navigator, 'languages', {
        get: () => ['en-US', 'en'],
    });

    // 4. Mock window.chrome
    if (!window.chrome) {
        window.chrome = {
            runtime: {},
            loadTimes: function() {},
            csi: function() {},
            app: {}
        };
    }

    // 5. Spoof WebGL vendor and renderer to look like real desktop GPU
    const getParameterProto = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) { // UNMASKED_VENDOR_WEBGL
            return 'Intel Inc.';
        }
        if (parameter === 37446) { // UNMASKED_RENDERER_WEBGL
            return 'Intel Iris OpenGL Engine';
        }
        return getParameterProto.apply(this, arguments);
    };

    // 6. Permissions query mock
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
            Promise.resolve({ state: Notification.permission }) :
            originalQuery(parameters)
    );
})();
"""


async def apply_stealth_profile(
    context: BrowserContext,
    page: Page,
    *,
    host: str = "",
) -> Any:
    """Apply the evasion script under a fingerprint drawn for this session.

    `STEALTH_EVASION_JS` above is kept as the fixed fallback, but the normal
    path now parameterises the same protections with a per-session identity
    from `browser_fingerprint`. Every session previously reported identical
    WebGL/plugin/language values, which is its own detectable signature; see
    that module and NIGHT_BATCH_DECISIONS.md.

    Returns the fingerprint in use so the caller can retire it via
    `fingerprint_pool.report_blocked(host, fp)` if the page turns out to be a
    bot wall. Returns None if fingerprint generation failed, in which case the
    fixed script was applied instead — a working fixed profile beats no
    stealth at all.
    """
    from app.services.application_assistant.browser_fingerprint import (
        build_evasion_script,
        fingerprint_pool,
    )

    try:
        fingerprint = fingerprint_pool.acquire(host or "default")
        script = build_evasion_script(fingerprint)
    except Exception:
        await context.add_init_script(STEALTH_EVASION_JS)
        await page.evaluate(STEALTH_EVASION_JS)
        return None

    await context.add_init_script(script)
    await page.evaluate(script)
    # Keep the HTTP-level identity agreeing with the JS-level one: a header UA
    # that contradicts navigator.platform is worse than no spoofing.
    try:
        await context.set_extra_http_headers({"User-Agent": fingerprint.user_agent})
    except Exception:
        pass
    return fingerprint


async def humanized_type(element: Any, text: str, min_delay_ms: int = 35, max_delay_ms: int = 85) -> None:
    """Simulate human typing cadence with randomized Gaussian latency per keystroke."""
    for char in text:
        delay = random.uniform(min_delay_ms, max_delay_ms) / 1000.0
        # Occasional micro-pause between words (space or punctuation)
        if char in " ,.-_":
            delay += random.uniform(0.04, 0.12)
        await element.type(char)
        await asyncio.sleep(delay)


async def humanized_scroll(page: Page, target_y: int, steps: int = 10) -> None:
    """Smooth scroll with natural deceleration curve to mimic human mousewheel."""
    current_y = await page.evaluate("window.scrollY")
    distance = target_y - current_y
    if abs(distance) < 20:
        return

    for i in range(1, steps + 1):
        # Ease-out cubic curve
        t = i / steps
        ease = 1 - math.pow(1 - t, 3)
        y = current_y + distance * ease
        await page.evaluate(f"window.scrollTo(0, {y})")
        await asyncio.sleep(random.uniform(0.015, 0.035))
