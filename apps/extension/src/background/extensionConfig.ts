import { setApiBase, getApiBase } from "../shared/apiConfig";
import { syncFromServer } from "../db/sync";

const CONFIG_FILE = "careeros-config.json";
const VERSION_KEY = "careeros_extension_version";
const WIRED_KEY = "careeros_extension_wired";

export interface ExtensionRuntimeConfig {
  apiBaseUrl: string;
  version: string;
}

export async function readBundledConfig(): Promise<ExtensionRuntimeConfig | null> {
  try {
    const url = chrome.runtime.getURL(CONFIG_FILE);
    const res = await fetch(url);
    if (!res.ok) return null;
    return (await res.json()) as ExtensionRuntimeConfig;
  } catch {
    return null;
  }
}

export async function fetchRemoteExtensionInfo(apiBase: string): Promise<ExtensionRuntimeConfig | null> {
  try {
    const res = await fetch(`${apiBase.replace(/\/$/, "")}/extension/info`);
    if (!res.ok) return null;
    const data = await res.json();
    return {
      apiBaseUrl: String(data.apiBaseUrl || apiBase).replace(/\/$/, ""),
      version: String(data.version || "0.0.0"),
    };
  } catch {
    return null;
  }
}

/** Pull API URL from website, bundled config, or backend, then sync profile data. */
export async function wireExtensionToBackend(preferredApiBase?: string): Promise<boolean> {
  const bundled = await readBundledConfig();
  let apiBase = preferredApiBase?.replace(/\/$/, "") || bundled?.apiBaseUrl || (await getApiBase());

  const remote = await fetchRemoteExtensionInfo(apiBase);
  if (remote?.apiBaseUrl && !preferredApiBase) {
    apiBase = remote.apiBaseUrl;
  }

  await setApiBase(apiBase);
  await chrome.storage.local.set({
    [VERSION_KEY]: remote?.version || bundled?.version || chrome.runtime.getManifest().version,
    [WIRED_KEY]: true,
  });

  return syncFromServer();
}

export async function getInstalledExtensionStatus(): Promise<{
  wired: boolean;
  version: string;
  apiBaseUrl: string;
}> {
  const { getInstalledExtensionStatus: readStatus } = await import("../shared/extensionStatus");
  return readStatus();
}

export function registerExtensionConfigListeners(): void {
  chrome.runtime.onInstalled.addListener(() => {
    void wireExtensionToBackend();
  });

  chrome.runtime.onStartup.addListener(() => {
    void wireExtensionToBackend();
  });
}
