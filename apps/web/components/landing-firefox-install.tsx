"use client";

import { useEffect, useState } from "react";
import { DEFAULT_API_BASE } from "@career-os/core";
import { detectBrowser } from "@/lib/extension-install";
import { getFirefoxInstallUrl, resolveStoreUrls, type ExtensionStoreUrls } from "@/lib/extension-store";
import { StoreInstallButton } from "@/components/store-install-button";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || DEFAULT_API_BASE;

const ENV_STORE_URLS: ExtensionStoreUrls = {
  chrome: process.env.NEXT_PUBLIC_CHROME_WEB_STORE_URL || null,
  edge: process.env.NEXT_PUBLIC_EDGE_ADDONS_URL || null,
  firefox: process.env.NEXT_PUBLIC_FIREFOX_ADDONS_URL || null,
};

/** Hero CTA — shows Add to Firefox when AMO URL is configured and user is on Firefox. */
export function LandingFirefoxInstall() {
  const [storeUrls, setStoreUrls] = useState<ExtensionStoreUrls>(ENV_STORE_URLS);
  const [browser, setBrowser] = useState<"firefox" | "other">("other");

  useEffect(() => {
    setBrowser(detectBrowser() === "firefox" ? "firefox" : "other");
    fetch(`${API_BASE}/extension/info`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data?.storeUrls) {
          setStoreUrls(resolveStoreUrls(data.storeUrls, ENV_STORE_URLS));
        }
      })
      .catch(() => undefined);
  }, []);

  const firefoxUrl = getFirefoxInstallUrl(storeUrls);
  if (!firefoxUrl) return null;

  return (
    <div className="landing-cta" style={{ marginTop: "-2rem", marginBottom: "2.5rem" }}>
      <StoreInstallButton browser="firefox" storeUrls={storeUrls} className="landing-firefox-install" />
      {browser !== "firefox" && (
        <span className="muted" style={{ fontSize: "0.85rem", alignSelf: "center" }}>
          Free on Firefox — one-click install
        </span>
      )}
    </div>
  );
}
