# CareerOS

CareerOS is a free, self-hosted job-search assistant that runs on your own computer. It finds
openings on company job boards, ranks them against your resume, tailors a resume and cover letter
for each one, fills in application forms for you, and tracks every application, recruiter and
interview in one dashboard.

It works for any role: software engineers, product managers, technical program managers,
designers and analysts. Nothing leaves your machine except the job boards you browse and, if you
add a key, requests to Google's free Gemini API.

## Quick start (Docker, recommended)

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/) and about 10 GB of
free disk space.

```bash
git clone <this-repo-url> CareerOS
cd CareerOS
cp .env.example .env              # Windows: copy .env.example .env
docker compose -f docker-compose.prod.yml up -d --build
```

The first build takes 10–20 minutes. Then open **http://localhost:5000**.

- Put your resume at `careeros-data/resume.pdf`, or upload it from the Resumes page.
- Everything CareerOS stores (database, tailored resumes, browser sign-ins) lives in the
  `careeros-data` folder, so updating or rebuilding keeps it. Back that folder up.
- Update: `git pull` then run the same `docker compose ... up -d --build` command again.
- Stop: `docker compose -f docker-compose.prod.yml down`.

Want a smaller, faster build? Set `CAREEROS_INSTALL_ML=false` in `.env`; resume ranking then uses
keyword search instead of a local embedding model.

## AI features: free, or none at all

CareerOS works without any AI key. Matching, ranking and form filling are deterministic and run
locally.

With a free [Google AI Studio key](https://aistudio.google.com/apikey) set as `GEMINI_API_KEY` in
`.env`, it also drafts cover letters and recruiter emails, tailors resume bullets and summarises job
descriptions. Screening-question answers still come from your own saved profile unless you also
set `CAREEROS_GEMINI_APPLICATIONS=true`. The free tier is enough for normal use, and you are never billed unless you turn on
billing in your Google account yourself.

## Make matching yours

Out of the box, jobs are ordered by how recent they are, how well they match your resume and your
preferred locations. Two files let you tune that:

- **Where you want to work.** Create a JSON file and point `CAREEROS_RANKING_PREFERENCES` at it:

  ```json
  {"preset": "neutral", "preferred_locations": ["Austin", "TX", "Remote"]}
  ```

- **What a good match looks like for you.** Copy
  `apps/api/app/services/application_assistant/resume_match_profile.json`, raise the
  `family_fit` for the kinds of roles you want (`product`, `program`, `design`, `analytics`,
  `backend`, `frontend`, `ml`, `data`, ...), list your skills and point `CAREEROS_MATCH_PROFILE`
  at your copy.

With Docker, put these files in `careeros-data/` and use paths like
`/app/apps/api/data/my_profile.json`. A file that is set but cannot be found or read fails with a
clear error rather than quietly ranking jobs the wrong way.

## Turning on automation

CareerOS is safe by default: it can open applications and fill them in, but it **never presses
the final Submit button and never sends email** until you turn that on.

- **Let Autopilot submit applications:** set `ALLOW_REAL_SUBMISSION=true` in `.env` and restart.
  Review a few filled-in applications first; you are responsible for what gets sent.
- **Email (recruiter outreach, verification codes):** connect Gmail with an app password, see
  [docs/email.md](./docs/email.md).

Night batches and automatic applying stay off until you start them from the Autopilot page.

## Local development

You need Node.js 20+, Python 3.11+ and Git.

```bash
./setup.sh          # Windows: setup.bat
pnpm dev
```

The setup script checks your tools, creates the `.env` files, installs the JavaScript and Python
dependencies plus Playwright's Chromium, builds the browser extension and runs the API smoke
tests. `pnpm dev` starts the API on http://localhost:4000 and the dashboard on
http://localhost:5000 with hot reload. For development inside Docker, use
`docker compose up --build` (see [docs/docker.md](./docs/docker.md)).

Run the API tests with `cd apps/api && python -m pytest tests -m "not network"`.

## What's inside

```
apps/
  web/          Next.js dashboard
  api/          FastAPI backend, Autopilot and job discovery
  extension/    ApplyPilot browser extension for filling forms by hand
packages/
  career-core/  Shared schemas and types
  career-ui/    Shared React components
docs/           Architecture and feature notes
```

- [Architecture](./docs/architecture.md)
- [Application assistant](./docs/application-assistant.md)
- [Docker](./docs/docker.md)
- [Email](./docs/email.md)

## Contributing and security

See [CONTRIBUTING.md](./CONTRIBUTING.md). Report security problems privately as described in
[SECURITY.md](./SECURITY.md).

## License

[MIT](./LICENSE)
