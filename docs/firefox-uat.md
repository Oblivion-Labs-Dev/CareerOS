# Firefox acceptance testing

The core utility is `apps/api/app/services/uat/firefox.py`. It reuses the production `profile_answer_resolver.resolve_answer` and `field_fill_engine.fill_field`, with post-fill value checks. It is independent of the live scheduler and does not replace its authorization or submission guards. The repository's main working tree contains these changes; no branch switch or automatic commit is needed.

## Install and run

From `apps/api`, use the existing virtual environment:

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-uat.txt
.venv/Scripts/python.exe -m playwright install firefox
.venv/Scripts/python.exe -m camoufox fetch official/152.0.4-beta.30
$env:CAREEROS_FIREFOX_UAT = '1'
.venv/Scripts/python.exe -m pytest tests/test_firefox_uat.py tests/test_firefox_uat_browser.py -q
.venv/Scripts/python.exe scripts/firefox_uat.py --engines firefox camoufox
```

The default harness uses synthetic contacts and a temporary PDF on a loopback HTTP server. Greenhouse-shaped separate names, Lever-shaped full names, and Himalayas-shaped embedded forms exercise contact mapping, native dropdowns and PDF attachments. Additional browser tests cover custom comboboxes, typing pace, missing facts, verification challenges, expired sessions, HTTP locks and duplicate commit prevention. These are controlled contracts, **not certification against those vendors' current live websites**. CI runs the contracts on Windows when relevant files change and supports manual dispatch.

## Production data mapping

```powershell
.venv/Scripts/python.exe scripts/firefox_uat.py --review-db --limit 3 --engines firefox camoufox
```

CareerOS uses Python/FastAPI and SQLAlchemy; the active local database is SQLite, `apps/api/data/career_os.db`. `ReviewAdapter` reads the configured `CAREER_OS_DATABASE_URL`, including PostgreSQL with a read-only transaction and statement timeout. SQLite uses URI `mode=ro` and `query_only=ON`; it does not import the store's initialization or seeding functions.

There is one canonical profile in `kv_store`, not a separate profile row per application. The adapter selects at most ten `entities` with `entity_type=aa_autopilot_job` and status `NEEDS_REVIEW` or `MANUAL_REVIEW`, maps `jobId`/`applicationUrl`, and joins the canonical profile in memory. It projects only contact fields: names, email, phone, location, city, state, country and professional URLs. Sensitive screening answers are intentionally unresolved in this UAT layer. The existing resolver's contact-email tracking tag is preserved and checked. No profile, queue, review status or application history is written.

`--review-db` still runs **locally** by default, so real contact data is not sent to employer sites. Use `--document <approved.pdf>` to exercise a particular local PDF; otherwise the harness generates a test-only PDF. Attachments are limited to PDF files of at most 10 MB.

For an explicitly authorized live DOM preview, add `--live-preview` and repeat `--allow-origin https://...` for each exact permitted origin. Only sampled review URLs within that list open. Live UAT blocks network writes and does not click submit; uploads requiring server POSTs therefore cannot be verified in this mode. Unknown or incomplete fields are reported for review. This is not a substitute for a separately approved live application run.

## Engines and environment

Configuration A uses `AsyncCamoufox` with its correlated Windows environment, engine-managed UA/fonts, a 1366×768 window, and no independent JavaScript navigator overrides. Configuration B uses `playwright.firefox.launch` with `privacy.resistFingerprinting=true`, `dom.webdriver.enabled=false`, `marionette.enabled=false`, and telemetry disabled. Neither uses CDP. Both use a fresh disposable context, explicit locale/timezone, bounded waits and cleanup on exceptions. No persistent cookies or real account sessions are imported.

Browser preferences are requests, not proof. The tested vanilla Firefox still reported `navigator.webdriver=true` and RFP normalized timezone to `Atlantic/Reykjavik` despite the configured Los Angeles timezone. Logs record observed UA, platform, dimensions, timezone and webdriver so this mismatch is visible. Font probes indicate browser font availability checks, not an authoritative inventory of installed system fonts. Neither configuration is promised to be undetectable or “unflagged.” Verification challenges are observed and stopped, never solved or bypassed.

Set `CAREEROS_UAT_PROXY` to an HTTP(S) or SOCKS5 upstream URL, optionally with percent-encoded username/password. Residential endpoints use the same format; no provider, credentials, geolocation lookup or proxy rotation is bundled. Credentials are omitted from representations and logs. Authenticated SOCKS support depends on the browser transport; HTTP proxy authentication is supported by Playwright. No real proxy endpoint was supplied for this comparison.

`--paced` enables seeded quadratic cursor paths, 15–65 ms keystroke intervals and short randomized pauses. This is reproducible interaction variation for event-handler testing, not a claim to defeat verification. Deterministic direct filling remains the fast default.

## Consumer API and logs

Use `async with FirefoxUAT(BrowserConfig(...), TargetPolicy((origin,)))` then `open(url)`, `execute_form_fill(profile, document)`, or `attach_document(locator, path)`. `safely_commit_form(button, confirmation)` works only for loopback fixture policies after all required fields are verified. A second attempt is rejected even if the first confirmation was uncertain. Live submissions remain exclusively in CareerOS's existing guarded runner.

JSON reports contain domain, engine/browser version, DOM completion status, field indices/types/source keys, fixture confirmation status, signature, HTTP-lock/request-failure counts, challenge state and elapsed time. They contain no profile values, full job URLs, raw exceptions, screenshots, resume contents or proxy credentials. Each harness case has a 120-second deadline. Output uses atomic replacement at `apps/api/data/uat/latest.json`; pass `--output` to choose another private location. Exit codes: 0 all cases complete, 1 a case incomplete/blocked, 2 setup failure. Raw console diagnostics from third-party engine startup may still appear; do not publish arbitrary terminal captures.

## Measured comparison — September 15, 2026

Both engines completed three local contracts using one real manual-review snapshot, including fixture confirmations. Vanilla Firefox 151.0: median **3,700 ms**. Camoufox 152.0.4: median **7,238 ms**. Neither encountered a challenge in those controlled forms. Firefox is the core default because it was faster and requires fewer dependencies; Camoufox remains an explicit comparison option. This sample establishes local form compatibility, not live ATS success rates. PostgreSQL and upstream proxies are implemented but were not exercised against external services.

References: [Camoufox usage](https://camoufox.com/python/usage/), [Playwright browser launch options](https://playwright.dev/python/docs/api/class-browsertype).

Final local validation: **15/15** UAT unit/browser tests passed, with both engines exercised. The final CLI smoke run completed all three synthetic contracts and wrote its structured JSON report. The live preview of the three sampled employer URLs was **not executed**: automatic approval review requires explicit approval of those destinations before real contact details may be entered. No real applications were submitted.

## Authorized Himalayas preview — September 16, 2026

The user subsequently authorized one Himalayas manual-review job test. Camoufox opened the saved Lyric Senior Software Engineer – Fullstack posting through Playwright. The page returned “Just a moment...” and Cloudflare “Performing security verification”; no application links or form controls were available. Telemetry recorded one HTTP lock and three blocked requests. The restricted preview blocks network writes, so this observation does not isolate browser detection from the preview's network restrictions. No challenge was bypassed, no profile data was entered, and no application was submitted. The queue and profile were read-only and unchanged. Private evidence is in `apps/api/data/uat/himalayas-discovery.json` and `himalayas-landing.png`. Reaching the employer application form and verifying field filling remain unverified for this live job.
