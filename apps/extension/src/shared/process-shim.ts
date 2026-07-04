/** React and some deps expect `process.env` — required in MV3 extension pages (no inline scripts). */
(globalThis as typeof globalThis & { process?: { env: { NODE_ENV: string } } }).process =
  (globalThis as typeof globalThis & { process?: { env: { NODE_ENV: string } } }).process || {
    env: { NODE_ENV: 'production' }
  };
