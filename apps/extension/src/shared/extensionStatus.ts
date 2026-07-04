import { getApiBase } from "./apiConfig";

const VERSION_KEY = "careeros_extension_version";
const WIRED_KEY = "careeros_extension_wired";

export async function getInstalledExtensionStatus(): Promise<{
  wired: boolean;
  version: string;
  apiBaseUrl: string;
}> {
  const stored = await chrome.storage.local.get([WIRED_KEY, VERSION_KEY, "careeros_api_base"]);
  return {
    wired: Boolean(stored[WIRED_KEY]),
    version: String(stored[VERSION_KEY] || chrome.runtime.getManifest().version),
    apiBaseUrl: String(stored.careeros_api_base || (await getApiBase())),
  };
}
