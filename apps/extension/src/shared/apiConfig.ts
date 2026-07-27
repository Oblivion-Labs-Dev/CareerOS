/** CareerOS API URLs — runtime config from storage, wired by backend on install/startup. */

const STORAGE_KEY = "careeros_api_base";
const DEFAULT_API_BASE = "http://localhost:8001";

export const CAREER_OS_API_BASE = DEFAULT_API_BASE;

export async function getApiBase(): Promise<string> {
  try {
    if (typeof chrome !== "undefined" && chrome.storage?.local) {
      const stored = await chrome.storage.local.get(STORAGE_KEY);
      const value = stored[STORAGE_KEY];
      if (typeof value === "string" && value.trim()) {
        return value.replace(/\/$/, "");
      }
    }
  } catch {
    // fall through to default
  }
  return DEFAULT_API_BASE;
}

export async function setApiBase(url: string): Promise<void> {
  const normalized = url.replace(/\/$/, "");
  if (typeof chrome !== "undefined" && chrome.storage?.local) {
    await chrome.storage.local.set({ [STORAGE_KEY]: normalized });
  }
}

export async function getServerDbUrl(): Promise<string> {
  return `${await getApiBase()}/api/db`;
}

export async function getParseResumeUrl(): Promise<string> {
  return `${await getApiBase()}/api/parse-resume`;
}

export async function getLogUrl(): Promise<string> {
  return `${await getApiBase()}/api/logs`;
}

/** @deprecated Use getServerDbUrl() */
export const SERVER_DB_URL = `${DEFAULT_API_BASE}/api/db`;
export const PARSE_RESUME_URL = `${DEFAULT_API_BASE}/api/parse-resume`;
export const LOG_URL = `${DEFAULT_API_BASE}/api/logs`;
