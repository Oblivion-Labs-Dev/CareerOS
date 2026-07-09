# Gmail email integration

Migrated from `Arsenal/scripts/email` and `Arsenal/packages/backend/src/gateways/gmail.ts`.

CareerOS sends mail through Gmail SMTP and can list recruiter-related threads via Gmail IMAP.

## Prerequisites

Gmail requires an **App Password** for SMTP/IMAP clients.

1. Open [Google Account Security](https://myaccount.google.com/security).
2. Enable **2-Step Verification**.
3. Create an **App password** (Mail / Other).
4. Add credentials to `apps/api/.env`:

```env
GMAIL_USER=your-email@gmail.com
GMAIL_APP_PASSWORD=your-16-character-app-password
```

## CLI scripts

From `apps/api`:

```bash
# Send a message
python scripts/email/send_email.py friend@example.com "Subject" "Body text"

# List latest recruiter threads (live IMAP)
python scripts/email/fetch_recruiter_threads.py

# Sync up to 150 threads into data/recruiter_conversations.json
python scripts/email/sync_recruiter_conversations.py
```

## HTTP API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/email/verify` | Verify Gmail SMTP credentials |
| POST | `/email/send` | Send email (`SendEmailPayload` JSON) |
| GET | `/email/recruiter-threads?limit=10` | Live IMAP recruiter thread search |
| GET | `/email/recruiter-conversations` | Read cached sync JSON |
| GET | `/email/outreach-campaigns` | Read saved recruiter outreach send campaigns |

`POST /email/send` requires `X-Career-OS-API-Key` when `CAREER_OS_DEV_MODE=false`.

## Recruiter contacts

`scripts/email/recruiters.example.json` is a starter outreach list migrated from Arsenal. Copy it locally if you want a working `recruiters.json` for custom tooling.

## Recruiter outreach template

`scripts/email/recruiter_outreach_template.json` contains the single generic outreach email. Replace `{{FirstName}}` with the recruiter's first name before sending.

## Notes

- Use `send_email.py` or `POST /email/send` with attachments when sending outreach mail.
- Batch outreach uses `send_recruiter_outreach_batch.py`, which waits ~8s (+ up to 2s jitter) between sends by default to reduce Gmail SMTP throttling.
- If a send fails after retries, the campaign is saved as `paused`. Fix the issue, then resume:

```bash
python scripts/email/send_recruiter_outreach_batch.py --continue
# or
python scripts/email/send_recruiter_outreach_batch.py --continue --campaign-id <campaign-id>
```
- Sync output lands in `apps/api/data/recruiter_conversations.json` (gitignored).
