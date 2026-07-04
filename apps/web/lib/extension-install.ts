import type { SupportedBrowser } from "@career-os/core";

export interface ApplyPilotPageStatus {
  installed: boolean;
  version: string;
  apiBaseUrl: string;
  wired: boolean;
  browser?: string;
}

export function detectBrowser(): SupportedBrowser {
  if (typeof navigator === "undefined") return "chrome";
  const ua = navigator.userAgent.toLowerCase();
  if (ua.includes("firefox")) return "firefox";
  if (ua.includes("edg/")) return "edge";
  if (ua.includes("opr/") || ua.includes("opera")) return "opera";
  if (ua.includes("brave")) return "brave";
  return "chrome";
}

export function compareVersions(left: string, right: string): number {
  const a = left.split(".").map((part) => parseInt(part, 10) || 0);
  const b = right.split(".").map((part) => parseInt(part, 10) || 0);
  const length = Math.max(a.length, b.length);
  for (let i = 0; i < length; i += 1) {
    const diff = (a[i] ?? 0) - (b[i] ?? 0);
    if (diff !== 0) return diff;
  }
  return 0;
}

export function readApplyPilotStatus(): ApplyPilotPageStatus | null {
  if (typeof window === "undefined") return null;
  return window.__CAREEROS_APPLYPILOT__ ?? null;
}

export async function downloadExtensionPackage(
  apiBase: string,
  browser: SupportedBrowser,
): Promise<string> {
  const res = await fetch(`${apiBase.replace(/\/$/, "")}/extension/download?browser=${browser}`);
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || "Could not fetch ApplyPilot from CareerOS");
  }

  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const match = disposition.match(/filename="(.+)"/);
  const filename = match?.[1] ?? `careeros-applypilot-${browser}.zip`;

  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
  return filename;
}

export function sendApplyPilotCommand(
  action: "reload" | "wire",
  options?: { apiBaseUrl?: string },
): void {
  window.dispatchEvent(
    new CustomEvent("careeros-applypilot-command", {
      detail: { action, apiBaseUrl: options?.apiBaseUrl },
    }),
  );
}

/** Push this site's backend URL into the installed extension — no folder needed. */
export function wireExtensionFromWebsite(apiBaseUrl: string): void {
  sendApplyPilotCommand("wire", { apiBaseUrl });
}

export function getBrowserExtensionsUrl(browser: SupportedBrowser): string {
  switch (browser) {
    case "firefox":
      return "about:debugging#/runtime/this-firefox";
    case "edge":
      return "edge://extensions";
    default:
      return "chrome://extensions";
  }
}

export function getExtensionsPageLabel(browser: SupportedBrowser): string {
  switch (browser) {
    case "firefox":
      return "about:debugging";
    case "edge":
      return "edge://extensions";
    default:
      return "chrome://extensions";
  }
}

/** Browsers block opening internal URLs from websites — copy + manual paste is the fallback. */
export async function copyExtensionsPageUrl(browser: SupportedBrowser): Promise<boolean> {
  const url = getBrowserExtensionsUrl(browser);
  try {
    await navigator.clipboard.writeText(url);
    return true;
  } catch {
    return false;
  }
}

export function tryOpenExtensionsPage(browser: SupportedBrowser): boolean {
  const url = getBrowserExtensionsUrl(browser);
  try {
    const opened = window.open(url, "_blank", "noopener,noreferrer");
    return Boolean(opened);
  } catch {
    return false;
  }
}

declare global {
  interface Window {
    __CAREEROS_APPLYPILOT__?: ApplyPilotPageStatus;
  }
}
