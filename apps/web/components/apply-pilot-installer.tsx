"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BROWSER_INSTALL_TARGETS,
  DEFAULT_API_BASE,
  type SupportedBrowser,
} from "@career-os/core";
import {
  compareVersions,
  copyExtensionsPageUrl,
  detectBrowser,
  downloadExtensionPackage,
  getExtensionsPageLabel,
  readApplyPilotStatus,
  sendApplyPilotCommand,
  tryOpenExtensionsPage,
  wireExtensionFromWebsite,
} from "@/lib/extension-install";
import {
  getStoreUrl,
  resolveStoreUrls,
  storeButtonLabel,
  type ExtensionStoreUrls,
} from "@/lib/extension-store";
import { StoreInstallButton } from "@/components/store-install-button";
import { copyTextToClipboard } from "@/lib/clipboard";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || DEFAULT_API_BASE;

const ENV_EXTENSION_DIST_PATH = process.env.NEXT_PUBLIC_EXTENSION_DIST_PATH?.trim() || "";

const ENV_STORE_URLS: ExtensionStoreUrls = {
  chrome: process.env.NEXT_PUBLIC_CHROME_WEB_STORE_URL || null,
  edge: process.env.NEXT_PUBLIC_EDGE_ADDONS_URL || null,
  firefox: process.env.NEXT_PUBLIC_FIREFOX_ADDONS_URL || null,
};

interface ExtensionInfo {
  version: string;
  apiBaseUrl: string;
  distReady: boolean;
  distPath?: string;
  installMode?: "store" | "development";
  storeUrls?: ExtensionStoreUrls;
  installHint?: string;
}

interface ApplyPilotInstallerProps {
  initialDistPath?: string;
  initialDistReady?: boolean;
}

export function ApplyPilotInstaller({
  initialDistPath,
  initialDistReady = false,
}: ApplyPilotInstallerProps) {
  const [info, setInfo] = useState<ExtensionInfo | null>(null);
  const [status, setStatus] = useState(readApplyPilotStatus());
  const [detectedBrowser] = useState<SupportedBrowser>(() => detectBrowser());
  const [activeBrowser, setActiveBrowser] = useState<SupportedBrowser>(detectedBrowser);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [lastDownload, setLastDownload] = useState<string | null>(null);
  const [pathCopied, setPathCopied] = useState(false);
  const [localDistPath, setLocalDistPath] = useState<string | null>(
    initialDistPath ?? (ENV_EXTENSION_DIST_PATH || null),
  );
  const [localDistReady, setLocalDistReady] = useState(initialDistReady);

  const apiBase = info?.apiBaseUrl ?? API_BASE;
  const storeUrls = useMemo(
    () => resolveStoreUrls(info?.storeUrls, ENV_STORE_URLS),
    [info?.storeUrls],
  );
  const activeStoreUrl = getStoreUrl(activeBrowser, storeUrls);
  const canStoreInstall = Boolean(activeStoreUrl);

  /** Absolute folder to pick in chrome://extensions → Load unpacked */
  const loadUnpackedPath = localDistPath || info?.distPath || null;
  const distReady = localDistReady || Boolean(info?.distReady);

  const refreshStatus = useCallback(() => {
    setStatus(readApplyPilotStatus());
  }, []);

  useEffect(() => {
    if (initialDistPath) {
      setLocalDistPath(initialDistPath);
      setLocalDistReady(initialDistReady);
    }

    fetch("/api/extension/dist-path")
      .then((res) => {
        if (!res.ok) throw new Error("dist-path unavailable");
        return res.json();
      })
      .then((data: { distPath?: string; distReady?: boolean }) => {
        if (data.distPath) setLocalDistPath(data.distPath);
        if (data.distReady) setLocalDistReady(true);
      })
      .catch(() => undefined);

    fetch(`${API_BASE}/extension/info`)
      .then((res) => res.json())
      .then((data: ExtensionInfo) => setInfo(data))
      .catch(() => setError("CareerOS API is offline. Start the backend for download — local path still works."));

    refreshStatus();
    const onStatus = (event: Event) => {
      setStatus((event as CustomEvent).detail);
    };
    window.addEventListener("careeros-applypilot-status", onStatus);
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        refreshStatus();
      }
    }, 5000);
    return () => {
      window.removeEventListener("careeros-applypilot-status", onStatus);
      window.clearInterval(interval);
    };
  }, [refreshStatus, initialDistPath, initialDistReady]);

  useEffect(() => {
    if (status?.installed) {
      wireExtensionFromWebsite(apiBase);
    }
  }, [status?.installed, apiBase]);

  const serverVersion = info?.version ?? null;
  const installed = Boolean(status?.installed);
  const installedVersion = status?.version ?? null;
  const versionComparison =
    installedVersion && serverVersion ? compareVersions(installedVersion, serverVersion) : null;
  const updateNeeded = versionComparison !== null && versionComparison < 0;
  const upToDate = installed && versionComparison !== null && versionComparison >= 0;

  const target = BROWSER_INSTALL_TARGETS.find((b) => b.id === activeBrowser);
  const browserLabel = BROWSER_INSTALL_TARGETS.find((b) => b.id === detectedBrowser)?.name ?? "Browser";
  const extensionsLabel = getExtensionsPageLabel(activeBrowser);

  const statusLabel = useMemo(() => {
    if (!installed) return "Not installed";
    if (updateNeeded) return `Update available (${installedVersion} → ${serverVersion})`;
    if (upToDate) return `Installed v${installedVersion} · Up to date`;
    return `Installed v${installedVersion}`;
  }, [installed, updateNeeded, upToDate, installedVersion, serverVersion]);

  function handleStoreInstalled() {
    setSuccess(
      `Opened ${storeButtonLabel(activeBrowser)}. Confirm in your browser — ApplyPilot will connect to ${apiBase} when you return here.`,
    );
    window.setTimeout(refreshStatus, 3000);
  }

  async function handleCopyDistPath() {
    if (!loadUnpackedPath) return;
    const ok = await copyTextToClipboard(loadUnpackedPath);
    if (!ok) {
      setError("Could not copy — click the path to select it, then Ctrl+C.");
      return;
    }
    setError(null);
    setPathCopied(true);
    window.setTimeout(() => setPathCopied(false), 1000);
  }

  /** Fastest path without a store listing: download zip + guide to load unpacked. */
  async function handleQuickInstall() {
    if (!distReady) return;
    setLoading(true);
    setError(null);
    setSuccess(null);

    try {
      const filename = await downloadExtensionPackage(apiBase, activeBrowser);
      setLastDownload(filename);

      const copied = await copyExtensionsPageUrl(activeBrowser);
      const opened = tryOpenExtensionsPage(activeBrowser);

      if (installed) {
        wireExtensionFromWebsite(apiBase);
        sendApplyPilotCommand("reload");
      }

      const pasteHint = copied
        ? `${extensionsLabel} copied — paste it in your address bar.`
        : `Open ${extensionsLabel} in your browser.`;

      setSuccess(
        opened
          ? `Downloaded ${filename}. Extensions page opened — enable Developer mode, Load unpacked, select the extracted folder.`
          : `Downloaded ${filename}. ${pasteHint} Then enable Developer mode → Load unpacked → pick the extracted folder.`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Install failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="installer">
      <div
        className={`installer-version-card${updateNeeded ? " installer-version-card--update" : upToDate ? " installer-version-card--ok" : ""}`}
      >
        <div className="installer-stat">
          <span className="installer-label">Your browser</span>
          <strong className="installer-value">{browserLabel}</strong>
        </div>
        <div className="installer-stat">
          <span className="installer-label">Installed</span>
          <strong className="installer-value">{installed ? `v${installedVersion}` : "Not detected"}</strong>
        </div>
        <div className="installer-stat">
          <span className="installer-label">Latest</span>
          <strong className="installer-value">{serverVersion ? `v${serverVersion}` : "—"}</strong>
        </div>
        <div className="installer-stat">
          <span className="installer-label">Status</span>
          <strong className="installer-value">{statusLabel}</strong>
        </div>
        <div className="installer-stat installer-stat--wide">
          <span className="installer-label">Backend</span>
          <strong className="installer-value">{status?.wired ? `Connected · ${apiBase}` : apiBase}</strong>
        </div>
      </div>

      {!canStoreInstall && (
        <div className="installer-banner installer-banner--info">
          <strong>Local install mode.</strong> Chrome and Firefox block true one-click install from websites unless
          the extension is on their official store. Use <strong>Quick install</strong> below — it downloads the
          package and walks you through load unpacked (~30 seconds).
        </div>
      )}

      {updateNeeded && canStoreInstall && (
        <div className="installer-banner">
          Update available: v{installedVersion} → v{serverVersion}. Use {storeButtonLabel(activeBrowser)}.
        </div>
      )}

      {upToDate && (
        <div className="installer-banner installer-banner--ok">
          ApplyPilot v{installedVersion} is installed. Backend wired from this site.
        </div>
      )}

      {error && <div className="installer-error">{error}</div>}
      {success && <div className="installer-banner installer-banner--ok">{success}</div>}

      <div className="installer-browsers">
        {BROWSER_INSTALL_TARGETS.map((browser) => (
          <button
            key={browser.id}
            type="button"
            className={`installer-browser-btn${activeBrowser === browser.id ? " active" : ""}`}
            onClick={() => setActiveBrowser(browser.id)}
            disabled={!browser.available}
          >
            {browser.name}
            {browser.id === detectedBrowser ? " · detected" : ""}
          </button>
        ))}
      </div>

      {target && (
        <div className="installer-panel">
          <div className="installer-local-path">
            <span className="installer-label">Load unpacked — select this folder</span>
            <div className="installer-local-path-row">
              <code
                className="installer-local-path-value"
                title={loadUnpackedPath ?? "Resolving path…"}
                onClick={() => loadUnpackedPath && copyTextToClipboard(loadUnpackedPath)}
              >
                {loadUnpackedPath ?? "Resolving local path…"}
              </code>
              <button
                type="button"
                className={`installer-copy-path-btn${pathCopied ? " installer-copy-path-btn--copied" : ""}`}
                onClick={handleCopyDistPath}
                disabled={!loadUnpackedPath}
                aria-live="polite"
              >
                <span className="installer-copy-path-label">{pathCopied ? "Copied ✓" : "Copy path"}</span>
              </button>
            </div>
            <p className="installer-hint installer-local-path-hint">
              Chrome: <code>chrome://extensions</code> → Developer mode → Load unpacked → paste path above.
              {!distReady && loadUnpackedPath && (
                <>
                  {" "}
                  Run <code>pnpm --filter @career-os/extension build</code> if the folder is empty.
                </>
              )}
            </p>
          </div>

          <div className="installer-actions installer-actions--primary">
            {canStoreInstall ? (
              <StoreInstallButton
                browser={activeBrowser}
                storeUrls={storeUrls}
                updateAvailable={updateNeeded}
                onInstall={handleStoreInstalled}
              />
            ) : (
              <button
                type="button"
                className="btn-primary quick-install-btn"
                disabled={!distReady || loading}
                onClick={handleQuickInstall}
              >
                {loading ? "Downloading…" : "Quick install (download + guide)"}
              </button>
            )}

            {!canStoreInstall && distReady && (
              <button
                type="button"
                className="btn-secondary"
                disabled={loading}
                onClick={handleQuickInstall}
              >
                Re-download package
              </button>
            )}

            {installed && (
              <button type="button" className="btn-secondary" onClick={() => wireExtensionFromWebsite(apiBase)}>
                Sync backend URL
              </button>
            )}
            <button type="button" className="btn-secondary" onClick={refreshStatus}>
              Refresh status
            </button>
          </div>

          <p className="muted installer-store-note">
            {canStoreInstall
              ? "Store install is one click. CareerOS auto-wires the backend when ApplyPilot is active on this site."
              : "After load unpacked, return here — CareerOS detects the extension and connects your API."}
          </p>

          {!canStoreInstall && (
            <div className="installer-dev-panel installer-quick-steps">
              <h4 className="installer-quick-steps-title">3 steps</h4>
              <ol className="installer-steps">
                {target.installSteps.map((step) => (
                  <li key={step}>{step}</li>
                ))}
              </ol>
              {lastDownload && <p className="installer-hint">Last download: {lastDownload}</p>}
              {!distReady && (
                <p className="installer-hint">
                  Run <code>pnpm --filter @career-os/extension build</code> first.
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
