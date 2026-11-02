import type { SupportedBrowser } from "@career-os/core";

export interface ExtensionStoreUrls {
  chrome?: string | null;
  edge?: string | null;
  firefox?: string | null;
}

/** Resolve store URL from API response or Next.js public env. */
export function resolveStoreUrls(
  fromApi?: ExtensionStoreUrls | null,
  fromEnv?: ExtensionStoreUrls,
): ExtensionStoreUrls {
  const env = fromEnv ?? {};
  return {
    chrome: fromApi?.chrome || env.chrome || null,
    edge: fromApi?.edge || env.edge || null,
    firefox: fromApi?.firefox || env.firefox || null,
  };
}

export function getStoreUrl(
  browser: SupportedBrowser,
  storeUrls: ExtensionStoreUrls | undefined,
): string | null {
  if (!storeUrls) return null;
  switch (browser) {
    case "firefox":
      return normalizeFirefoxStoreUrl(storeUrls.firefox);
    case "edge":
      return storeUrls.edge ?? null;
    case "chrome":
    case "brave":
    case "opera":
      return storeUrls.chrome ?? null;
    default:
      return storeUrls.chrome ?? null;
  }
}

/** Normalize AMO listing URLs for install flow. */
export function normalizeFirefoxStoreUrl(url: string | null | undefined): string | null {
  if (!url?.trim()) return null;
  try {
    const parsed = new URL(url.trim());
    if (!parsed.hostname.includes("addons.mozilla.org")) return url.trim();
    // Ensure trailing slash for AMO listing pages
    if (!parsed.pathname.endsWith("/")) {
      parsed.pathname = `${parsed.pathname}/`;
    }
    return parsed.toString();
  } catch {
    return url.trim();
  }
}

export function getFirefoxInstallUrl(storeUrls?: ExtensionStoreUrls): string | null {
  return getStoreUrl("firefox", storeUrls);
}

export function storeButtonLabel(browser: SupportedBrowser): string {
  switch (browser) {
    case "firefox":
      return "Add to Firefox";
    case "edge":
      return "Add to Edge";
    case "brave":
      return "Add to Brave";
    case "opera":
      return "Add to Opera";
    default:
      return "Add to Chrome";
  }
}

export function storeButtonClass(browser: SupportedBrowser): string {
  switch (browser) {
    case "firefox":
      return "store-install-btn store-install-btn--firefox";
    default:
      return "store-install-btn";
  }
}

export function openStoreInstall(storeUrl: string): void {
  window.open(storeUrl, "_blank", "noopener,noreferrer");
}
