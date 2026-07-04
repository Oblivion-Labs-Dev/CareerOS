/**
 * Launch Firefox with ApplyPilot loaded (temporary dev install).
 * Uses background.scripts — required by web-ext temporary install API.
 */
import { execSync } from 'node:child_process';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, '..');
const distDir = path.join(root, 'dist');
const runDir = path.join(root, '.firefox-run');
const firefoxBin =
  process.env.FIREFOX_BIN || 'C:\\Program Files\\Mozilla Firefox\\firefox.exe';

if (!fs.existsSync(path.join(distDir, 'manifest.json'))) {
  console.error('[run-firefox-dev] dist/ missing — run: pnpm build:firefox');
  process.exit(1);
}

if (!fs.existsSync(firefoxBin)) {
  console.error(`[run-firefox-dev] Firefox not found at: ${firefoxBin}`);
  console.error('  Set FIREFOX_BIN to your firefox.exe path');
  process.exit(1);
}

fs.rmSync(runDir, { recursive: true, force: true });
fs.cpSync(distDir, runDir, { recursive: true });

const manifestPath = path.join(runDir, 'manifest.json');
const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
manifest.background = { scripts: ['background.global.js'] };
fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2), 'utf8');

console.log('[run-firefox-dev] Opening Firefox with ApplyPilot (temporary install)…');
console.log('[run-firefox-dev] Close Firefox to exit.\n');

execSync(
  `npx web-ext run --source-dir="${runDir}" --firefox="${firefoxBin}" --start-url "http://localhost:3000/features"`,
  { cwd: root, stdio: 'inherit' },
);
