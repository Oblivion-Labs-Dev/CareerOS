import { DEFAULT_API_BASE } from "@career-os/core";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || DEFAULT_API_BASE;
const DEFAULT_REVALIDATE_SECONDS = 15;

type FetchOptions = {
  revalidate?: number | false;
};

function fetchOptions(options?: FetchOptions): RequestInit {
  if (options?.revalidate === false) {
    return { cache: "no-store" };
  }
  return { next: { revalidate: options?.revalidate ?? DEFAULT_REVALIDATE_SECONDS } };
}

export async function fetchHealth(options?: FetchOptions): Promise<{ status: string; service?: string }> {
  const res = await fetch(`${API_BASE}/health`, { ...fetchOptions({ revalidate: options?.revalidate ?? 5 }), credentials: "include" });
  if (!res.ok) throw new Error("API unavailable");
  return res.json();
}

async function errorMessageFor(res: Response, path: string): Promise<string> {
  try {
    const body = await res.clone().json();
    if (typeof body?.detail === "string" && body.detail) return body.detail;
    if (typeof body?.message === "string" && body.message) return body.message;
  } catch {
    // Response wasn't JSON (or already consumed) — fall through to the generic message.
  }
  return `Request failed: ${path}`;
}

export async function fetchJson<T>(path: string, options?: FetchOptions): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { ...fetchOptions(options), credentials: "include" });
  if (!res.ok) throw new Error(await errorMessageFor(res, path));
  return res.json();
}

export function getApiBaseUrl(): string {
  return API_BASE;
}

export function getClientApiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_URL || DEFAULT_API_BASE;
}

export async function postJson<T>(path: string, body: unknown, method: "POST" | "PATCH" | "PUT" | "DELETE" = "POST"): Promise<T> {
  const res = await fetch(`${getClientApiBaseUrl()}${path}`, {
    method,
    headers: method === "DELETE" ? undefined : { "Content-Type": "application/json" },
    body: method === "DELETE" ? undefined : JSON.stringify(body),
    credentials: "include",
  });
  if (!res.ok) throw new Error(await errorMessageFor(res, path));
  return res.json();
}
