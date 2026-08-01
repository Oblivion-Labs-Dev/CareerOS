# Application Assistant

Local, human-supervised job application preparation for CareerOS.

## Purpose and safety model

The Application Assistant helps you discover jobs from employer career pages, prepare applications in a **visible Playwright browser**, and review every field before you submit manually.

**Automation never clicks final Submit, Apply, or equivalent buttons.** Declarations, signatures, CAPTCHA, and sensitive demographic questions require manual completion.

## Prerequisites

- Node.js ≥ 20, pnpm 9+
- Python 3.11+
- Playwright browsers (installed once)

```bash
cd CareerOS/apps/api
pip install -r requirements.txt
playwright install chromium
```

## Starting CareerOS

```bash
cd CareerOS
pnpm install
pnpm dev          # API (8001) + web (3000)
```

Navigate to **Application Assistant** in the sidebar (`/application-assistant`).

## Supported providers

| Provider   | Discovery | Application prep |
|-----------|-----------|------------------|
| Greenhouse | ✓        | ✓                |
| Workday    | Detected  | Not yet supported |
| Lever      | Detected  | Not yet supported |

Unsupported providers are detected and reported clearly — they do not fail silently.

## Workflow

1. Paste a Greenhouse careers URL (e.g. `https://boards.greenhouse.io/company`)
2. Click **Find Jobs** — jobs are extracted, matched, and ranked
3. Select a job and click **Prepare Application**
4. A visible browser opens and verified profile fields are filled
5. Review classified fields: verified, needs review, missing, manual-only
6. Click **Open for final review** — browser reopens for manual completion
7. Handle CAPTCHA, declarations, and signatures yourself
8. Click **Submit** in the browser manually
9. Mark the application as submitted in CareerOS

## Configuration

### SQLite

Uses the existing CareerOS database (`apps/api/data/career_os.db`). Application Assistant entities are stored in the `entities` table with types prefixed `aa_`.

### Local LLM (optional)

Configure in `.env` or via API settings:

```
APPLICATION_ASSISTANT_LLM_BASE_URL=http://localhost:1234/v1
APPLICATION_ASSISTANT_LLM_MODEL=your-model-name
```

Works with LM Studio, Ollama (OpenAI-compatible endpoint), and similar servers. The feature works without an LLM for standard Greenhouse field mappings.

### Browser profile

An isolated Playwright browser profile is stored at:

```
apps/api/data/application_assistant/browser_profile/
```

This is separate from your personal browser. Login manually when prompted — passwords are never stored.

## Data storage

| Data | Location |
|------|----------|
| Application drafts | SQLite `entities` table (`aa_application_draft`) |
| Discovered jobs | SQLite `entities` table (`aa_discovered_job`) |
| Answer library | SQLite `entities` table (`aa_answer_library`) |
| Screenshots | `apps/api/data/application_assistant/screenshots/` |
| Playwright traces | `apps/api/data/application_assistant/traces/` |
| Browser profile | `apps/api/data/application_assistant/browser_profile/` |

All browser storage paths are gitignored.

## Answer classification

Every form field is classified:

- **verified** — copied from profile or approved answer library entry
- **inferred** — derived but requires review (optional setting)
- **unknown** — cannot be answered safely
- **conflict** — inconsistent sources
- **manual_only** — declarations, signatures, consent

Sensitive fields (work authorization, salary, demographics) are never inferred.

## Resetting state

```bash
# Remove browser profile and cached data
rm -rf apps/api/data/application_assistant/

# Application drafts remain in SQLite until archived/deleted
```

## Running tests

```bash
# Unit + adapter tests (no Playwright required)
cd CareerOS/apps/api
python -m pytest tests/test_application_assistant_core.py tests/test_application_assistant_greenhouse.py -q

# Integration tests (requires Playwright)
playwright install chromium
python -m pytest tests/test_application_assistant_integration.py -q

# Full API test suite
pnpm test:api
```

## Troubleshooting

| Issue | Action |
|-------|--------|
| "Unsupported provider" | URL must be a Greenhouse careers page |
| "Login required" | Sign in manually in the visible browser |
| "CAPTCHA required" | Complete CAPTCHA manually, then resume |
| Browser doesn't open | Check `APPLICATION_ASSISTANT_ENABLED=true` |
| LLM errors | Feature works without LLM; check base URL and model name |

## Privacy

- Passwords, cookies, and tokens are never logged or committed
- Sensitive answers are redacted in diagnostic exports
- All website content is treated as untrusted data
- Final submission is always performed manually by the user

## Known limitations

- Greenhouse only for application preparation (Workday/Lever detected but not supported)
- No LinkedIn, Indeed, or other platform automation
- File upload (resume) requires explicit selection — not silently uploaded
- Multi-page applications may require manual navigation for unsupported intermediate steps
- Optional LLM integration for field label normalization only — never controls browser actions

## Next recommended provider

**Workday** is the recommended next adapter due to prevalence in enterprise hiring. The provider-adapter interface and placeholder are in place at `apps/api/app/services/application_assistant/providers/workday.py`.
