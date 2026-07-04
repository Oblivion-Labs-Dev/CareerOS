# Publish ApplyPilot to Firefox (AMO)

Firefox Add-ons (AMO) publishing is **free** — no developer registration fee (unlike Chrome's $5).

## Prerequisites

- Firefox account at https://addons.mozilla.org/
- CareerOS API URL for production (or document localhost for reviewer)
- Hosted privacy policy URL (use `docs/privacy-applypilot.md` on GitHub Pages or your site)

## 1. Build the Firefox package

```bash
cd CareerOS
pnpm --filter @career-os/extension build:firefox
```

This produces:

| Output | Purpose |
|--------|---------|
| `apps/extension/dist/` | Load temporary add-on for local testing |
| `apps/extension/releases/careeros-applypilot-v*-firefox-source.zip` | Upload to AMO |

Optional lint:

```bash
pnpm --filter @career-os/extension lint:firefox
```

## 2. Test locally in Firefox

1. Open `about:debugging#/runtime/this-firefox`
2. Click **Load Temporary Add-on**
3. Select `apps/extension/dist/manifest.json`
4. Visit http://localhost:3000/features — version should appear when wired

Extension ID (fixed): `career-os@applypilot.dev`

## 3. Submit to AMO (automated or manual)

### Option A — Automated sign & upload (recommended)

1. Create API keys: https://addons.mozilla.org/developers/addon/api/key/
2. Copy `apps/extension/.env.example` → `apps/extension/.env` and paste `AMO_JWT_ISSUER` + `AMO_JWT_SECRET`
3. Run:

```bash
cd CareerOS
pnpm --filter @career-os/extension build:firefox
pnpm --filter @career-os/extension publish:firefox
```

4. Complete listing metadata in the AMO developer hub (first submission)
5. Privacy policy URL: `https://YOUR-DOMAIN/privacy/applypilot` (built into CareerOS web)

### Option B — Manual upload

1. Go to https://addons.mozilla.org/developers/addons
2. **Submit a New Add-on** → **On Firefox** → **Manifest v3**
3. Upload `releases/careeros-applypilot-v*-firefox-source.zip`
4. Choose **Listed** (public) or **Unlisted** (direct link only)
5. Paste listing content from `apps/extension/amo/listing.md`
6. Add privacy policy URL
7. Submit for review (typically 1–7 days)

## 4. Enable one-click install on CareerOS

After approval, copy your AMO URL and add to `.env`:

```env
NEXT_PUBLIC_FIREFOX_ADDONS_URL=https://addons.mozilla.org/firefox/addon/YOUR-SLUG/
CAREER_OS_FIREFOX_ADDONS_URL=https://addons.mozilla.org/firefox/addon/YOUR-SLUG/
```

Restart web + API. The **Add to Firefox** button on `/features` opens AMO one-click install.

## 5. Updates

1. Bump version in `apps/extension/manifest.json` and `package.json`
2. Run `pnpm --filter @career-os/extension build:firefox`
3. Upload new zip to AMO developer hub
4. Firefox auto-updates installed users after AMO approval

## Technical notes

- Manifest includes `browser_specific_settings.gecko.id` — required for Firefox
- Chrome ignores the gecko block; one manifest works for both browsers
- API download `GET /extension/download?browser=firefox` serves AMO-format zip (manifest at root)
- Minimum Firefox: **109.0** (MV3 service worker support)

## Reviewer notes

If reviewers ask about `<all_urls>`: ApplyPilot must inspect job application forms on employer career sites (Greenhouse, Lever, Workday, etc.) which use varied domains.

If reviewers ask about localhost API: explain users self-host CareerOS; production deployments use HTTPS API URLs in `careeros-config.json`.
