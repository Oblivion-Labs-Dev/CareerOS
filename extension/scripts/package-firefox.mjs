import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { execSync } from 'node:child_process';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, '..');
const distDir = path.join(root, 'dist');
const releasesDir = path.join(root, 'releases');

const manifest = JSON.parse(fs.readFileSync(path.join(distDir, 'manifest.json'), 'utf8'));
const version = manifest.version;
const geckoId = manifest.browser_specific_settings?.gecko?.id;

if (!geckoId) {
  console.error('[package-firefox] Missing browser_specific_settings.gecko.id in manifest.json');
  process.exit(1);
}

if (!fs.existsSync(releasesDir)) {
  fs.mkdirSync(releasesDir, { recursive: true });
}

const zipName = `careeros-applypilot-v${version}-firefox-source.zip`;
const zipPath = path.join(releasesDir, zipName);

function zipDirectory(sourceDir, outPath) {
  const absSource = path.resolve(sourceDir);
  const absOut = path.resolve(outPath);
  if (process.platform === 'win32') {
    execSync(
      `powershell -NoProfile -Command "Compress-Archive -Path '${absSource}\\*' -DestinationPath '${absOut}' -Force"`,
      { stdio: 'inherit' }
    );
  } else {
    execSync(`cd "${absSource}" && zip -r "${absOut}" .`, { stdio: 'inherit' });
  }
}

zipDirectory(distDir, zipPath);

console.log(`[package-firefox] OK — Firefox AMO package ready`);
console.log(`[package-firefox] Extension ID: ${geckoId}`);
console.log(`[package-firefox] Upload to AMO: ${zipPath}`);
console.log(`[package-firefox] Local test: about:debugging → Load Temporary Add-on → dist/manifest.json`);
