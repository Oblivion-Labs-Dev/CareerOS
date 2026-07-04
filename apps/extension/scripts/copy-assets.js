import fs from 'fs';
import path from 'path';

const filesToCopy = [
  { src: 'manifest.json', dest: 'dist/manifest.json' },
  { src: 'src/popup/popup.html', dest: 'dist/popup.html' },
  { src: 'src/popup/popup.css', dest: 'dist/popup.css' },
  { src: 'src/dashboard/dashboard.html', dest: 'dist/dashboard.html' },
  { src: 'src/dashboard/dashboard.css', dest: 'dist/dashboard.css' },
  { src: 'src/portal/portal.html', dest: 'dist/portal.html' },
  { src: 'src/portal/portal.css', dest: 'dist/portal.css' },
  { src: 'src/shared/process-shim.js', dest: 'dist/process-shim.js' },
  { src: 'icon-16.png', dest: 'dist/icon-16.png' },
  { src: 'icon-48.png', dest: 'dist/icon-48.png' },
  { src: 'icon-128.png', dest: 'dist/icon-128.png' },
  { src: 'icon.png', dest: 'dist/icon.png' }
];

const apiBase = process.env.CAREER_OS_API_URL || 'http://localhost:8000';
const manifest = JSON.parse(fs.readFileSync('manifest.json', 'utf-8'));
const runtimeConfig = {
  apiBaseUrl: apiBase.replace(/\/$/, ''),
  version: manifest.version,
  wiredAt: 'build'
};

filesToCopy.forEach(({ src, dest }) => {
  const destDir = path.dirname(dest);
  if (!fs.existsSync(destDir)) {
    fs.mkdirSync(destDir, { recursive: true });
  }
  fs.copyFileSync(src, dest);
  console.log(`Copied ${src} -> ${dest}`);
});

fs.writeFileSync('dist/careeros-config.json', JSON.stringify(runtimeConfig, null, 2), 'utf-8');
console.log('Wrote dist/careeros-config.json');
