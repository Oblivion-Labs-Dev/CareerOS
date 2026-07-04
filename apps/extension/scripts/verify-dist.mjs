import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const distDir = path.resolve(__dirname, '..', 'dist');
const manifest = JSON.parse(fs.readFileSync(path.join(distDir, 'manifest.json'), 'utf8'));
const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf8'));

const errors = [];

if (manifest.version !== pkg.version) {
  errors.push(`Version mismatch: manifest=${manifest.version}, package.json=${pkg.version}`);
}

for (const htmlFile of ['popup.html', 'dashboard.html', 'portal.html']) {
  const html = fs.readFileSync(path.join(distDir, htmlFile), 'utf8');
  if (/<script(?![^>]*\bsrc=)[^>]*>/.test(html)) {
    errors.push(`${htmlFile} contains inline <script> (CSP violation risk)`);
  }
  if (html.includes('var process')) {
    errors.push(`${htmlFile} contains inline process shim`);
  }
}

for (const bundle of ['popup.global.js', 'dashboard.global.js', 'content.global.js', 'portal.global.js']) {
  const js = fs.readFileSync(path.join(distDir, bundle), 'utf8');
  if (!js.includes('globalThis.process')) {
    errors.push(`${bundle} missing process shim`);
  }
}

if (errors.length) {
  console.error('[verify-dist] FAILED:\n' + errors.map((e) => `  - ${e}`).join('\n'));
  process.exit(1);
}

console.log(`[verify-dist] OK — CareerOS ApplyPilot v${manifest.version}`);
console.log(`[verify-dist] Load unpacked from: ${distDir}`);
