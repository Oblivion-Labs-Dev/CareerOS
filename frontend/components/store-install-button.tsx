"use client";

import type { SupportedBrowser } from "@career-os/core";
import {
  getStoreUrl,
  openStoreInstall,
  storeButtonClass,
  storeButtonLabel,
  type ExtensionStoreUrls,
} from "@/lib/extension-store";

interface StoreInstallButtonProps {
  browser: SupportedBrowser;
  storeUrls: ExtensionStoreUrls;
  updateAvailable?: boolean;
  onInstall?: () => void;
  className?: string;
}

/** Store one-click install — only renders when a store URL is configured. */
export function StoreInstallButton({
  browser,
  storeUrls,
  updateAvailable = false,
  onInstall,
  className = "",
}: StoreInstallButtonProps) {
  const storeUrl = getStoreUrl(browser, storeUrls);
  if (!storeUrl) return null;

  const label = storeButtonLabel(browser);
  const btnClass = `${storeButtonClass(browser)}${className ? ` ${className}` : ""}`;

  return (
    <button
      type="button"
      className={btnClass}
      onClick={() => {
        openStoreInstall(storeUrl);
        onInstall?.();
      }}
    >
      <StoreIcon browser={browser} />
      {updateAvailable ? `Update via ${label}` : label}
    </button>
  );
}

function StoreIcon({ browser }: { browser: SupportedBrowser }) {
  if (browser === "firefox") {
    return (
      <span className="store-install-icon store-install-icon--firefox" aria-hidden>
        <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
          <path d="M12 0C5.373 0 0 5.373 0 12c0 6.627 5.373 12 12 12s12-5.373 12-12C24 5.4 18.6 0 12 0zm5.894 8.221l-1.97 9.28c-.145.658-.537.818-1.084.508l-3-2.21-1.446 1.394c-.14.18-.357.295-.6.295l.213-3.053 5.56-5.023c.242-.213-.054-.334-.373-.121l-6.869 4.326-2.96-.924c-.64-.203-.658-.64.135-.954l11.566-4.458c.538-.196 1.006.128.832.94z" />
        </svg>
      </span>
    );
  }

  return (
    <span className="store-install-icon" aria-hidden>
      ⬇
    </span>
  );
}
