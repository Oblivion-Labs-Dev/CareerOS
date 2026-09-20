"""Firefox-only UAT with bounded interactions and no live submission capability.

No CDP, challenge solving, persistent browser profiles, or generative answers.
QA variation is seeded and reproducible; observed signatures are reported rather
than assumed to be indistinguishable from human browsers.
"""
from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
import random
import re
from urllib.parse import urlsplit, unquote


def proxy_from_url(value: str | None):
    if not value:
        return None
    try:
        u = urlsplit(value)
        if u.scheme not in ('http', 'https', 'socks5') or not u.hostname or not u.port or u.path not in ('', '/') or u.query or u.fragment:
            raise ValueError()
        host = f'[{u.hostname}]' if ':' in u.hostname else u.hostname
        result = {'server': f'{u.scheme}://{host}:{u.port}'}
        if u.username is not None:
            result.update(username=unquote(u.username), password=unquote(u.password or ''))
        return result
    except ValueError:
        raise ValueError('Proxy must be a valid HTTP(S) or SOCKS5 endpoint.') from None


def origin(value):
    try:
        u = urlsplit(value)
        if u.username or u.password or not u.hostname or u.scheme not in ('http', 'https'):
            return None
        return u.scheme, u.hostname.lower(), u.port or (443 if u.scheme == 'https' else 80)
    except ValueError:
        return None


@dataclass(frozen=True)
class TargetPolicy:
    origins: tuple[str, ...]
    fixture: bool = False

    def __post_init__(self):
        if not self.origins or any(origin(url) is None for url in self.origins):
            raise ValueError('Explicit target origins are required.')
        if self.fixture and any(origin(url)[1] not in ('127.0.0.1', 'localhost', '::1') for url in self.origins):
            raise ValueError('Fixture commits are restricted to loopback servers.')
        if not self.fixture and any(origin(url)[0] != 'https' for url in self.origins):
            raise ValueError('Live review requires HTTPS.')

    def allows(self, url):
        return origin(url) is not None and origin(url) in {origin(u) for u in self.origins}


@dataclass(frozen=True)
class BrowserConfig:
    engine: str = 'firefox'
    headless: bool = True
    proxy_url: str | None = field(default=None, repr=False)
    paced: bool = False
    seed: int = 17
    timeout_ms: int = 12000
    locale: str = 'en-US'
    timezone: str = 'America/Los_Angeles'

    def __post_init__(self):
        if self.engine not in ('firefox', 'camoufox'):
            raise ValueError('Engine must be firefox or camoufox.')
        if not 100 <= self.timeout_ms <= 60000:
            raise ValueError('Timeout must be 100–60000 ms.')
        proxy_from_url(self.proxy_url)


class InteractionPacing:
    def __init__(self, seed):
        self.random = random.Random(seed)
        self.position = (0., 0.)

    async def pause(self):
        await asyncio.sleep(self.random.uniform(.08, .22))

    async def point(self, page, locator):
        await locator.scroll_into_view_if_needed()
        box = await locator.bounding_box()
        if not box:
            raise ValueError('Control has no visible geometry.')
        x0, y0 = self.position
        x1, y1 = box['x'] + box['width']/2, box['y'] + box['height']/2
        cx, cy = (x0+x1)/2 + self.random.uniform(-24,24), (y0+y1)/2 + self.random.uniform(-24,24)
        for step in range(1, 13):
            t = step/12
            await page.mouse.move((1-t)**2*x0+2*(1-t)*t*cx+t*t*x1, (1-t)**2*y0+2*(1-t)*t*cy+t*t*y1)
        self.position = (x1, y1)

    async def type(self, page, locator, value):
        await self.point(page, locator)
        await locator.fill('')
        # Locator key events exercise application input handlers, never Enter.
        for character in value:
            await locator.press_sequentially(character, delay=self.random.uniform(15, 65))
        await self.pause()


CHALLENGE = re.compile(r'verify (?:that )?you are human|checking your browser|unusual traffic|access denied|session (?:has )?expired|verification required|complete the security check', re.I)


class FirefoxUAT:
    def __init__(self, config: BrowserConfig, policy: TargetPolicy):
        self.config, self.policy = config, policy
        self.pacing = InteractionPacing(config.seed)
        self.stack = AsyncExitStack()
        self.events = {'httpLocks': 0, 'networkFailures': 0, 'blockedRequests': 0}
        self._committed = False
        self._filled = False

    async def __aenter__(self):
        from playwright.async_api import async_playwright
        try:
            proxy = proxy_from_url(self.config.proxy_url)
            if self.config.engine == 'camoufox':
                from camoufox.async_api import AsyncCamoufox
                from camoufox.addons import DefaultAddons
                # Generate a correlated Windows Firefox profile inside the engine;
                # do not independently spoof UA, fonts, or navigator properties.
                self.browser = await self.stack.enter_async_context(AsyncCamoufox(
                    headless=self.config.headless, os='windows', window=(1366, 768),
                    locale=self.config.locale, proxy=proxy, geoip=False,
                    exclude_addons=[DefaultAddons.UBO], humanize=False))
            else:
                playwright = await self.stack.enter_async_context(async_playwright())
                self.browser = await playwright.firefox.launch(headless=self.config.headless, proxy=proxy,
                    firefox_user_prefs={'privacy.resistFingerprinting': True, 'dom.webdriver.enabled': False,
                                        'marionette.enabled': False, 'toolkit.telemetry.enabled': False})
                self.stack.push_async_callback(self.browser.close)
            self.context = await self.browser.new_context(viewport={'width':1366,'height':768},
                locale=self.config.locale, timezone_id=self.config.timezone,
                accept_downloads=False, service_workers='block')
            self.stack.push_async_callback(self.context.close)
            self.context.set_default_timeout(self.config.timeout_ms)
            self.context.set_default_navigation_timeout(self.config.timeout_ms)
            await self.context.route('**/*', self._route)
            self.page = await self.context.new_page()
            self.page.on('response', lambda response: self._response(response.status))
            self.page.on('requestfailed', lambda _: self._increment('networkFailures'))
            return self
        except BaseException:
            await self.stack.aclose()
            raise

    async def __aexit__(self, *_):
        await self.stack.aclose()

    def _increment(self, key):
        self.events[key] += 1

    def _response(self, status):
        if status in (401,403,429):
            self._increment('httpLocks')

    async def _route(self, route):
        request = route.request
        # Fixture isolation also blocks subresources leaving the local server.
        # Live UAT only permits GET/HEAD: even autosave/upload cannot apply.
        blocked = (request.is_navigation_request() or self.policy.fixture) and not self.policy.allows(request.url)
        blocked |= not self.policy.fixture and request.method not in ('GET', 'HEAD', 'OPTIONS')
        if blocked:
            self._increment('blockedRequests')
            await route.abort()
        else:
            await route.continue_()

    async def open(self, url):
        if not self.policy.allows(url):
            raise ValueError('Target is outside the explicit origin allowlist.')
        self._filled = False
        await self.page.goto(url, wait_until='domcontentloaded')
        return await self.telemetry()

    async def telemetry(self):
        text = await self.page.locator('body').inner_text(timeout=self.config.timeout_ms)
        visible_challenge = False
        for frame in await self.page.locator('iframe[src*="captcha"],iframe[src*="challenges.cloudflare"], [data-uat-challenge]').all():
            visible_challenge |= await frame.is_visible()
        blocked = bool(CHALLENGE.search(text)) or visible_challenge or self.events['httpLocks'] > 0
        return {**self.events, 'verification': 'challenge_or_lock' if blocked else 'no_challenge_observed'}

    async def signature(self):
        return await self.page.evaluate('''() => ({userAgent:navigator.userAgent, platform:navigator.platform,
            language:navigator.language, webdriver:navigator.webdriver, timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,
            screen:{width:screen.width,height:screen.height}, viewport:{width:innerWidth,height:innerHeight},
            fonts:['Arial','Calibri','Times New Roman','Segoe UI'].filter(f=>document.fonts.check('12px "'+f+'"'))})''')

    async def _ready(self):
        if not self.policy.allows(self.page.url):
            raise ValueError('Page left the authorized target.')
        if (await self.telemetry())['verification'] != 'no_challenge_observed':
            raise ValueError('Verification challenge requires human review.')

    async def attach_document(self, locator, path: str | Path):
        await self._ready()
        if not self.policy.allows(await locator.evaluate('(el)=>el.ownerDocument.location.href')):
            raise ValueError('Attachment target is outside the allowed origins.')
        path = Path(path).resolve(strict=True)
        if path.suffix.lower() != '.pdf' or path.stat().st_size > 10 * 1024 * 1024 or not path.read_bytes().startswith(b'%PDF-'):
            raise ValueError('Attach a valid PDF of at most 10 MB.')
        await locator.set_input_files(str(path))
        return await locator.evaluate('(el) => el.files.length === 1')

    async def execute_form_fill(self, profile: dict, document: Path | None = None):
        from playwright.async_api import Error as BrowserError, TimeoutError as BrowserTimeout
        from app.services.application_assistant.profile_answer_resolver import resolve_answer
        from app.services.application_assistant.field_fill_engine import fill_field
        await self._ready()
        results = []
        truncated = False
        # Frame roots are scanned independently; accessible names drive the same
        # production answer resolver and fill engine used by the live service.
        for frame in self.page.frames:
            if not self.policy.allows(frame.url):
                continue
            controls = frame.locator('input:not([type=hidden]):not([type=submit]):not([type=button]), textarea, select, [role=combobox]:not(input)')
            control_count = await controls.count()
            truncated |= control_count > 100
            for index in range(min(control_count, 100)):
                locator = controls.nth(index)
                meta = await locator.evaluate('''el => ({label:el.getAttribute('aria-label') || [...(el.labels||[])].map(l=>l.innerText).join(' ') || el.getAttribute('placeholder') || el.name || '',
                    type:el.type || el.getAttribute('role') || el.tagName.toLowerCase(), custom:el.getAttribute('role')==='combobox', required:el.required || el.getAttribute('aria-required')==='true',
                    options:el.options ? [...el.options].filter(o=>o.value).map(o=>o.text) : []})''')
                if not await locator.is_enabled() or (meta['type'] != 'file' and not await locator.is_visible()):
                    continue
                # DOM labels and values are intentionally omitted from public logs.
                outcome = {'fieldIndex':len(results), 'type':meta['type'], 'required':bool(meta['required']), 'status':'unresolved'}
                await self._ready()
                try:
                    if meta['type'] == 'file':
                        if document and re.search(r'resume|cv', meta['label'], re.I):
                            outcome['status'] = 'filled' if await self.attach_document(locator, document) else 'mismatch'
                    else:
                        resolution = resolve_answer(meta['label'], profile, options=meta['options'])
                        answer = resolution.answer
                        # UAT reads a deliberately small contact-only snapshot.
                        # Never accept resolver defaults for sensitive facts.
                        key = resolution.profile_key or ''
                        allowed = key in profile and profile[key] not in ('',None)
                        allowed |= key == 'city+state' and bool(profile.get('city') and profile.get('state'))
                        if answer is not None and allowed and not resolution.blocking_errors:
                            token = f'uat-{len(results)}'
                            await locator.evaluate('(el,token)=>el.setAttribute("data-careeros-uat",token)',token)
                            if self.config.paced and not meta['custom'] and meta['type'] in ('text','email','tel','url','textarea','search'):
                                await self.pacing.type(self.page, locator, str(answer))
                                ok = True
                            else:
                                ok, _ = await asyncio.wait_for(fill_field(frame, {'selector':f'[data-careeros-uat="{token}"]','label':meta['label']}, answer, profile=profile), self.config.timeout_ms/1000)
                            actual = await locator.evaluate("el => el.tagName==='SELECT' ? el.selectedOptions[0]?.text : el.type==='checkbox' ? String(el.checked) : el.value ?? el.innerText")
                            outcome['status'] = 'filled' if ok and str(actual).strip() == str(answer).strip() else 'mismatch'
                            outcome['sourceKey'] = key
                except (ValueError, asyncio.TimeoutError, BrowserTimeout):
                    outcome['status'] = 'timeout_or_validation_error'
                except BrowserError:
                    outcome['status'] = 'control_error'
                results.append(outcome)
        self._filled = (bool(results) and not truncated and self.events['blockedRequests'] == 0
                        and all(r['status']=='filled' for r in results if r['required'])
                        and all(r['status'] in ('filled','unresolved') for r in results)
                        and any(r['status']=='filled' for r in results))
        return {'status':'complete' if self._filled else 'needs_review', 'fields':results,
                'truncated':truncated, 'telemetry':await self.telemetry()}

    async def safely_commit_form(self, button, confirmation):
        """Fixture-only terminal action. Live submissions remain in the guarded runner."""
        if not self.policy.fixture:
            raise PermissionError('UAT cannot submit live applications; use the existing approved runner.')
        await self._ready()
        if not self._filled or self._committed:
            raise ValueError('Commit requires a complete, uncommitted form.')
        if not self.policy.allows(await button.evaluate('(el)=>el.ownerDocument.location.href')):
            raise ValueError('Commit control is outside the fixture origin.')
        if await confirmation.is_visible() or not await button.evaluate('(el)=>Boolean(el.form && el.form.checkValidity())'):
            raise ValueError('Commit requires a valid form and a new confirmation.')
        self._committed = True  # An uncertain response cannot trigger a duplicate click.
        await button.click()
        await confirmation.wait_for(state='visible')
        return {'status':'confirmed', 'fixture':True}
