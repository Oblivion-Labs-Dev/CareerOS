import { defineConfig } from 'tsup';

export default defineConfig({
  entry: {
    content: 'src/content/contentScript.ts',
    webBridge: 'src/content/webBridge.ts',
    background: 'src/background/serviceWorker.ts',
    popup: 'src/popup/popup.ts',
    dashboard: 'src/dashboard/Dashboard.tsx',
    portal: 'src/portal/Portal.tsx'
  },
  format: ['iife'],
  outDir: 'dist',
  bundle: true,
  splitting: false,
  sourcemap: true,
  clean: false,
  minify: false,
  dts: false,
});
