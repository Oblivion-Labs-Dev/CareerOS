---
name: weekly-target-jobs
description: >-
  Pull Oracle and DocuSign Senior Software Engineer jobs weekly into CareerOS.
  Use when the user asks to create a target jobs dashboard or page under CareerOS,
  refresh Oracle/DocuSign listings, run the weekly job pull, copy WhatsApp job
  lists, or open /jobs/target-companies.
---

# Weekly Target Company Jobs

Refresh **Oracle** and **DocuSign** US Senior Software Engineer listings into CareerOS.

## When to use

Trigger this skill when the user says any of:

- "create a dashboard" or "create a page" for Oracle/DocuSign/target company jobs in CareerOS
- "refresh target company jobs", "pull Oracle and DocuSign jobs", "weekly job pull"
- "update target jobs", "Oracle and DocuSign dashboard", "WhatsApp job list"

If the dashboard page is missing or broken, ensure these exist before refreshing:

- Page: `apps/web/app/(app)/jobs/target-companies/page.tsx`
- Component: `apps/web/components/jobs/target-company-jobs-dashboard.tsx`
- Nav: `apps/web/lib/nav-config.ts` → "Oracle & DocuSign" under Search & apply

Then open **http://localhost:3000/jobs/target-companies** (API on :8000).

## Top 10 companies

Run a broader pull (Google/Microsoft/Meta are portal-only; 7 others are live API):

```bash
cd CareerOS/apps/api
python scripts/jobs/pull_top10_companies.py --location washington
python scripts/jobs/pull_top10_companies.py --location all --whatsapp
```

Companies: Google, Microsoft, Amazon, Meta, Stripe, Databricks, Anthropic, Airbnb, Oracle, DocuSign.

## Quick refresh (preferred)

From repo root:

```bash
cd CareerOS/apps/api
python scripts/jobs/refresh_target_company_jobs.py --whatsapp --location washington
```

Or call the API (API must be running):

```bash
curl -X POST http://localhost:8000/jobs/target-companies/refresh
curl "http://localhost:8000/jobs/target-companies?company=Oracle&location=washington"
curl "http://localhost:8000/jobs/target-companies/whatsapp?company=all&location=remote"
```

## Dashboard

Open in the web app:

**http://localhost:3000/jobs/target-companies**

Features:
- Filter by company (Oracle / DocuSign / all)
- Filter by location (`all`, `remote`, `washington`)
- **Refresh now** button
- **Copy WhatsApp list** button

## What gets pulled

| Company | Source | Notes |
|---------|--------|-------|
| **DocuSign** | Live API `careers.docusign.com/api/jobs` | Paginated; filters Senior + Software + US |
| **Oracle** | Seed file + live URL verify | `apps/api/data/target_company_jobs/oracle_seed.json` |

## Adding new Oracle jobs

Oracle's public API does not return listings without a browser session. To add roles:

1. Browse https://eeho.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/jobsearch
2. Search `Senior Software Engineer`, location `United States` or `Washington`
3. Append to `oracle_seed.json` or POST:

```bash
curl -X POST http://localhost:8000/jobs/target-companies/oracle-seed \
  -H "Content-Type: application/json" \
  -d '{"jobs":[{"id":"338844","title":"Senior Software Development Engineer","location":"United States (Remote)"}]}'
```

4. Run refresh again.

## Weekly workflow

1. Run refresh script or POST `/jobs/target-companies/refresh`
2. Review dashboard at `/jobs/target-companies`
3. Copy WhatsApp text for sharing
4. Optionally save high-priority roles via ApplyPilot or POST `/jobs/save`

## Filters

- `location=remote` — roles tagged remote/flexible
- `location=washington` — Seattle/WA **plus** remote (matches user preference)
- `company=Oracle` or `company=DocuSign`

## Files

- Service: `apps/api/app/services/target_company_jobs.py`
- Seed: `apps/api/data/target_company_jobs/oracle_seed.json`
- Script: `apps/api/scripts/jobs/refresh_target_company_jobs.py`
- Page: `apps/web/app/(app)/jobs/target-companies/page.tsx`
