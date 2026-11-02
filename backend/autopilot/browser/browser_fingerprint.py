"""Per-session browser fingerprints, and retiring the ones a host has blocked.

`stealth_browser_profile.py` hides the automation markers well, but every
session it creates presents the *same* identity: the same `Intel Inc.` /
`Intel Iris OpenGL Engine` strings, the same three plugins, the same language
list. Thousands of byte-identical sessions are themselves a signature — a
detection vendor can fingerprint the evasion rather than the automation.

This generates a different identity per session. The important property is not
randomness but *coherence*: a macOS user-agent reporting a Win32 platform and an
NVIDIA GPU is more suspicious than no spoofing at all, so each profile is drawn
as a complete, self-consistent set. Values are only ever combined within a
single OS family.

Scope: this is fingerprint diversity only. IP address remains a strong signal
that this cannot touch — see NIGHT_BATCH_DECISIONS.md.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("career_os.browser_fingerprint")


@dataclass(frozen=True)
class BrowserFingerprint:
    """One coherent browser identity."""

    user_agent: str
    platform: str
    webgl_vendor: str
    webgl_renderer: str
    hardware_concurrency: int
    device_memory: int
    screen_width: int
    screen_height: int
    languages: tuple[str, ...]
    timezone: str

    @property
    def key(self) -> str:
        return f"{self.platform}:{self.webgl_renderer}:{self.screen_width}x{self.screen_height}"


# Each entry is a self-consistent family. Renderers are only paired with the OS
# they actually ship on: Apple GPUs never appear under Win32, and the ANGLE
# wrapper strings Chrome reports on Windows never appear under macOS.
_PROFILE_FAMILIES: tuple[dict[str, Any], ...] = (
    {
        "platform": "Win32",
        "ua_template": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
        ),
        "webgl": (
            ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
            ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
            ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
            ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon RX 6600 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
        ),
        "screens": ((1920, 1080), (2560, 1440), (1536, 864), (1366, 768)),
    },
    {
        "platform": "MacIntel",
        "ua_template": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
        ),
        "webgl": (
            ("Apple Inc.", "Apple M1 Pro"),
            ("Apple Inc.", "Apple M2"),
            ("Apple Inc.", "Apple M3"),
            ("Intel Inc.", "Intel Iris Pro OpenGL Engine"),
        ),
        "screens": ((1728, 1117), (1512, 982), (2560, 1440), (1920, 1080)),
    },
)

# Recent stable Chrome majors. Staying within a plausible window matters: a
# version far from what real traffic reports is its own tell.
_CHROME_MAJORS = (123, 124, 125, 126, 127, 128)

_CORES = (4, 8, 8, 12, 16)
_MEMORY = (8, 8, 16, 16, 32)

_US_TIMEZONES = (
    "America/Los_Angeles",
    "America/Denver",
    "America/Chicago",
    "America/New_York",
)


def generate_fingerprint(rng: random.Random | None = None) -> BrowserFingerprint:
    """Draw one coherent identity."""
    r = rng or random
    family = r.choice([f for f in _PROFILE_FAMILIES if "platform" in f])
    vendor, renderer = r.choice(family["webgl"])
    width, height = r.choice(family["screens"])
    return BrowserFingerprint(
        user_agent=family["ua_template"].format(major=r.choice(_CHROME_MAJORS)),
        platform=family["platform"],
        webgl_vendor=vendor,
        webgl_renderer=renderer,
        hardware_concurrency=r.choice(_CORES),
        device_memory=r.choice(_MEMORY),
        screen_width=width,
        screen_height=height,
        languages=("en-US", "en"),
        timezone=r.choice(_US_TIMEZONES),
    )


def build_evasion_script(fp: BrowserFingerprint) -> str:
    """The evasion script, parameterised by one generated identity.

    Same protections as the original fixed script — hidden webdriver flag,
    plugin and language mocks, `window.chrome`, permissions query — but the
    values that used to be constants now vary per session.
    """
    languages_js = "[" + ", ".join(f"'{lang}'" for lang in fp.languages) + "]"
    return f"""
(() => {{
    Object.defineProperty(navigator, 'webdriver', {{ get: () => undefined }});

    Object.defineProperty(navigator, 'plugins', {{
        get: () => [
            {{ name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' }},
            {{ name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' }},
            {{ name: 'Native Client', filename: 'internal-nacl-plugin', description: '' }}
        ],
    }});

    Object.defineProperty(navigator, 'languages', {{ get: () => {languages_js} }});
    Object.defineProperty(navigator, 'platform', {{ get: () => '{fp.platform}' }});
    Object.defineProperty(navigator, 'hardwareConcurrency', {{ get: () => {fp.hardware_concurrency} }});
    Object.defineProperty(navigator, 'deviceMemory', {{ get: () => {fp.device_memory} }});

    if (!window.chrome) {{
        window.chrome = {{ runtime: {{}}, loadTimes: function() {{}}, csi: function() {{}}, app: {{}} }};
    }}

    const getParameterProto = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {{
        if (parameter === 37445) {{ return '{fp.webgl_vendor}'; }}
        if (parameter === 37446) {{ return '{fp.webgl_renderer}'; }}
        return getParameterProto.apply(this, arguments);
    }};

    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications'
            ? Promise.resolve({{ state: Notification.permission }})
            : originalQuery(parameters)
    );
}})();
"""


@dataclass
class _HostState:
    blocked_keys: set[str] = field(default_factory=set)
    block_events: int = 0
    last_block_at: str | None = None


class FingerprintPool:
    """Hands out identities and stops reusing ones a host has already blocked.

    A block is per (host, fingerprint): being challenged by Ashby says nothing
    about Greenhouse, so the two are tracked separately. When every generated
    candidate for a host has been burned, the record is cleared rather than
    returning nothing — a stale ban list is worse than a fresh guess, and the
    host may have aged the old signals out anyway.
    """

    def __init__(self, *, max_attempts: int = 12) -> None:
        self._hosts: dict[str, _HostState] = {}
        self._max_attempts = max_attempts

    def acquire(self, host: str, rng: random.Random | None = None) -> BrowserFingerprint:
        state = self._hosts.setdefault(host, _HostState())
        for _ in range(self._max_attempts):
            candidate = generate_fingerprint(rng)
            if candidate.key not in state.blocked_keys:
                return candidate
        logger.info("Every known fingerprint is burned on %s; clearing its ban list", host)
        state.blocked_keys.clear()
        return generate_fingerprint(rng)

    def report_blocked(self, host: str, fp: BrowserFingerprint) -> None:
        state = self._hosts.setdefault(host, _HostState())
        state.blocked_keys.add(fp.key)
        state.block_events += 1
        state.last_block_at = datetime.now(UTC).isoformat()
        logger.info(
            "Retired fingerprint %s on %s (%d block events on this host)",
            fp.key, host, state.block_events,
        )

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {
            host: {
                "retiredFingerprints": len(s.blocked_keys),
                "blockEvents": s.block_events,
                "lastBlockAt": s.last_block_at,
            }
            for host, s in self._hosts.items()
        }


fingerprint_pool = FingerprintPool()
