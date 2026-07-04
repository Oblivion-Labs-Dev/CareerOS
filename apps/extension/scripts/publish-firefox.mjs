/**
 * Submit a signed build to Firefox Add-ons (AMO) via web-ext.
 *
 * Prerequisites:
 * 1. Firefox account at https://addons.mozilla.org/
 * 2. API credentials: https://addons.mozilla.org/developers/addon/api/key/
 * 3. Set AMO_JWT_ISSUER and AMO_JWT_SECRET in apps/extension/.env (see .env.example)
 *
 * Usage:
 *   pnpm --filter @career-os/extension publish:firefox
 *   pnpm --filter @career-os/extension publish:firefox -- --channel=unlisted
 */
import { execSync } from 'node:child_process';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, '..');
const distDir = path.join(root, 'dist');
const releasesDir = path.join(root, 'releases');

const channel = process.argv.includes('--channel=unlisted') ? 'unlisted' : 'listed';
const issuer = process.env.AMO_JWT_ISSUER?.trim();
const secret = process.env.AMO_JWT_SECRET?.trim();

if (!issuer || !secret) {
  console.error('[publish-firefox] Missing AMO credentials.');
  console.error('  Set AMO_JWT_ISSUER and AMO_JWT_SECRET in apps/extension/.env');
  console.error('  Create keys: https://addons.mozilla.org/developers/addon/api/key/');
  process.exit(1);
}

if (!fs.existsSync(path.join(distDir, 'manifest.json'))) {
  console.error('[publish-firefox] dist/ not found — run build:firefox first');
  process.exit(1);
}

if (!fs.existsSync(releasesDir)) {
  fs.mkdirSync(releasesDir, { recursive: true });
}

console.log(`[publish-firefox] Signing and uploading (${channel})…`);

try {
  execSync(
    [
      'npx web-ext sign',
      `--source-dir="${distDir}"`,
      `--api-key="${issuer}"`,
      `--api-secret="${secret}"`,
      `--channel=${channel}`,
      `--artifacts-dir="${releasesDir}"`,
      '--overwrite-artifacts',
      '--approval-timeout=0',
    ].join(' '),
    { cwd: root, stdio: 'inherit', env: process.env },
  );
} catch {
  process.exit(1);
}

const xpis = fs
  .readdirSync(releasesDir)
  .filter((name) => name.endsWith('.xpi'))
  .map((name) => ({ name, mtime: fs.statSync(path.join(releasesDir, name)).mtimeMs }))
  .sort((a, b) => b.mtime - a.mtime);

const latest = xpis[0];
if (latest) {
  console.log(`\n[publish-firefox] Signed XPI: releases/${latest.name}`);
}

const slug = 'careeros-applypilot';
const amoUrl = `https://addons.mozilla.org/firefox/addon/${slug}/`;

console.log('\n[publish-firefox] Next steps:');
console.log(`  1. Complete AMO listing if first publish (see amo/listing.md)`);
console.log(`  2. After approval, set in CareerOS/.env:`);
console.log(`     NEXT_PUBLIC_FIREFOX_ADDONS_URL=${amoUrl}`);
console.log(`     CAREER_OS_FIREFOX_ADDONS_URL=${amoUrl}`);
console.log('  3. Restart web + API — Add to Firefox button activates on /features');
