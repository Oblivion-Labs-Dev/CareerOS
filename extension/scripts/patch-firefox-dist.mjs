/** Patch dist manifest for Firefox AMO validation (web-ext lint reads gecko min version). */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const distDir = path.resolve(__dirname, '..', 'dist');
const manifestPath = path.join(distDir, 'manifest.json');

if (!fs.existsSync(manifestPath)) {
  console.error('[patch-firefox-dist] dist/manifest.json missing');
  process.exit(1);
}

const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));

manifest.browser_specific_settings = {
  gecko: {
    id: 'career-os@applypilot.dev',
    strict_min_version: '128.0',
    data_collection_permissions: {
      required: ['none'],
    },
  },
};

// web-ext lint flags service_worker below Firefox 112; runtime requires MV3 worker on 112+
manifest.background = {
  service_worker: 'background.global.js',
};

if (manifest.action?.default_icon === 'icon.png') {
  manifest.action.default_icon = 'icon-128.png';
}

fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2), 'utf8');
console.log('[patch-firefox-dist] Patched dist/manifest.json for Firefox AMO (min 128.0)');
