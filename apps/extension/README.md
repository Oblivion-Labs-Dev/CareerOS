# ApplyPilot Extension

Chrome + Firefox MV3 extension for CareerOS job application autofill.

## Build

```bash
# Chrome / Chromium / Edge (load unpacked from dist/)
pnpm --filter @career-os/extension build

# Firefox — validates gecko manifest + AMO zip
pnpm --filter @career-os/extension build:firefox
pnpm --filter @career-os/extension lint:firefox
```

## Firefox

- Extension ID: `career-os@applypilot.dev`
- Local test: `about:debugging` → Load Temporary Add-on → `dist/manifest.json`
- Publish: see [docs/firefox-publishing.md](../../docs/firefox-publishing.md) (free on AMO)

## API

Syncs with CareerOS FastAPI at `http://localhost:8000` (configurable via `CAREER_OS_API_URL` at build time).
