export class ExtensionContextInvalidError extends Error {
  constructor(message = 'ApplyPilot lost connection. Refresh this page and try again.') {
    super(message);
    this.name = 'ExtensionContextInvalidError';
  }
}

type ExtensionRuntime = typeof chrome.runtime;

declare global {
  // Firefox MV3 exposes the promise-based API on `browser`.
  const browser: { runtime?: ExtensionRuntime } | undefined;
}

export function getExtensionRuntime(): ExtensionRuntime | null {
  try {
    if (typeof chrome !== 'undefined' && chrome.runtime?.sendMessage) {
      void chrome.runtime.id;
      return chrome.runtime;
    }
    if (typeof browser !== 'undefined' && browser.runtime?.sendMessage) {
      void browser.runtime.id;
      return browser.runtime;
    }
  } catch {
    return null;
  }
  return null;
}

export function isExtensionContextValid(): boolean {
  return getExtensionRuntime() !== null;
}

export function requireExtensionRuntime(): ExtensionRuntime {
  const runtime = getExtensionRuntime();
  if (!runtime?.sendMessage) {
    throw new ExtensionContextInvalidError();
  }
  return runtime;
}
