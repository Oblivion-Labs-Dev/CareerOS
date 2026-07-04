import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const distDir = path.resolve(__dirname, '..', 'dist');
const manifestPath = path.join(distDir, 'manifest.json');

if (!fs.existsSync(manifestPath)) {
  console.error('[verify-firefox] dist/manifest.json not found — run build first');
  process.exit(1);
}

const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
const errors = [];

const gecko = manifest.browser_specific_settings?.gecko;
if (!gecko?.id) {
  errors.push('Missing browser_specific_settings.gecko.id (required for Firefox)');
}
if (!gecko?.strict_min_version) {
  errors.push('Missing browser_specific_settings.gecko.strict_min_version');
}
if (manifest.manifest_version !== 3) {
  errors.push('Firefox build requires manifest_version 3');
}
for (const file of ['background.global.js', 'webBridge.global.js', 'content.global.js', 'popup.global.js']) {
  if (!fs.existsSync(path.join(distDir, file))) {
    errors.push(`Missing ${file}`);
  }
}

if (errors.length) {
  console.error('[verify-firefox] FAILED:\n' + errors.map((e) => `  - ${e}`).join('\n'));
  process.exit(1);
}

console.log(`[verify-firefox] OK — Firefox extension ID ${gecko.id}, min ${gecko.strict_min_version}`);
