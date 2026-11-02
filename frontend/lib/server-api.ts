import { cookies } from "next/headers";
import { getApiBaseUrl } from "./api";

type FetchOptions = {
  revalidate?: number | false;
};

function fetchOptions(options?: FetchOptions): RequestInit {
  if (options?.revalidate === false) {
    return { cache: "no-store" };
  }
  return { next: { revalidate: options?.revalidate ?? 15 } };
}

/**
 * Server Component / route-handler equivalent of lib/api.ts's fetchJson.
 *
 * `fetchJson`'s `credentials: "include"` only means something in a browser's
 * cookie jar — the server-side fetch implementation has none, so a Server
 * Component calling it against an auth-enforced route gets a 401. This reads
 * the incoming request's cookies via next/headers and forwards them as a
 * `cookie` header instead, the server-side equivalent of what the browser
 * does automatically. Only import this from a Server Component: next/headers
 * throws if pulled into client-bundled code, which is the intended guard
 * against this leaking into a "use client" file.
 */
export async function serverFetchJson<T>(path: string, options?: FetchOptions): Promise<T> {
  const cookieStore = await cookies();
  const cookieHeader = cookieStore.toString();
  const res = await fetch(`${getApiBaseUrl()}${path}`, {
    ...fetchOptions(options),
    headers: cookieHeader ? { cookie: cookieHeader } : undefined,
  });
  if (!res.ok) throw new Error(`Request failed: ${path}`);
  return res.json();
}
