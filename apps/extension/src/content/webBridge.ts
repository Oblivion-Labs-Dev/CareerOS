import { getInstalledExtensionStatus } from "../shared/extensionStatus";

declare global {
  interface Window {
    __CAREEROS_APPLYPILOT__?: {
      installed: boolean;
      version: string;
      apiBaseUrl: string;
      wired: boolean;
      browser?: string;
    };
  }
}

async function publishStatus(): Promise<void> {
  const status = await getInstalledExtensionStatus();
  const payload = {
    installed: true,
    version: status.version,
    apiBaseUrl: status.apiBaseUrl,
    wired: status.wired,
    browser: navigator.userAgent.includes("Firefox")
      ? "firefox"
      : navigator.userAgent.includes("Edg/")
        ? "edge"
        : "chromium",
  };

  window.__CAREEROS_APPLYPILOT__ = payload;
  window.dispatchEvent(new CustomEvent("careeros-applypilot-status", { detail: payload }));
}

void publishStatus();

window.addEventListener("careeros-applypilot-command", (event) => {
  const detail = (event as CustomEvent<{ action?: string; apiBaseUrl?: string }>).detail;
  if (detail?.action === "reload") {
    chrome.runtime.reload();
    return;
  }
  if (detail?.action === "wire") {
    void import("../background/extensionConfig")
      .then((mod) => mod.wireExtensionToBackend(detail.apiBaseUrl))
      .then(() => publishStatus());
  }
});

chrome.storage.onChanged.addListener((changes, area) => {
  if (
    area === "local" &&
    (changes.careeros_api_base || changes.careeros_extension_wired || changes.careeros_extension_version)
  ) {
    void publishStatus();
  }
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.action === "careeros-get-status") {
    void getInstalledExtensionStatus().then((status) => {
      sendResponse({ success: true, ...status, installed: true });
    });
    return true;
  }
});
