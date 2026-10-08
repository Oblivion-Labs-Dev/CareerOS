import { NextRequest, NextResponse } from "next/server";

// Lightweight redirect only — presence of the cookie, not signature/expiry
// verification (that happens server-side in the API's AuthGateMiddleware on
// every actual data request). This just keeps an unauthenticated visitor from
// landing on a page full of empty/broken widgets before bouncing to /login.
const SESSION_COOKIE_NAME = "co_session";

// Same env resolution as app/api/backend/[...path]/route.ts, so this always
// talks to the same API instance the rest of the app is proxying to.
const rawBase = process.env.CAREER_OS_API_PUBLIC_URL || process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:4000";
const API_BASE = rawBase.replace("//localhost:", "//127.0.0.1:");

// Every page request runs this middleware. Calling the API on each one made
// navigation wait on a round trip — and on the full 2s timeout when the API
// was slow or down. Remember the answer briefly instead.
const AUTH_STATUS_TTL_MS = 30_000;
const AUTH_STATUS_MISS_TTL_MS = 5_000;
const AUTH_STATUS_TIMEOUT_MS = 250;

type AuthCache = { authRequired: boolean; expiresAt: number };
let authCache: AuthCache | null = null;

async function authIsRequired(now = Date.now()): Promise<boolean> {
  if (authCache && authCache.expiresAt > now) return authCache.authRequired;
  try {
    const res = await fetch(`${API_BASE.replace(/\/$/, "")}/auth/status`, {
      signal: AbortSignal.timeout(AUTH_STATUS_TIMEOUT_MS),
    });
    const authRequired = res.ok ? Boolean((await res.json()).authRequired) : false;
    authCache = { authRequired, expiresAt: now + AUTH_STATUS_TTL_MS };
    return authRequired;
  } catch {
    // API unreachable — fail open rather than hold every page. Data requests
    // still go through the API's own auth gate. Remember the miss so the next
    // click does not wait on another timeout.
    authCache = { authRequired: false, expiresAt: now + AUTH_STATUS_MISS_TTL_MS };
    return false;
  }
}

export async function middleware(request: NextRequest) {
  // Auth is opt-in (CAREER_OS_ADMIN_PASSWORD unset = gate is off entirely) — a
  // fresh checkout with no .env must never lock the owner out of their own
  // local instance. Without this check, "no cookie yet" and "auth not
  // configured" are indistinguishable and every navigation would bounce to
  // /login, which itself redirects back, forever.
  const authRequired = await authIsRequired();

  if (!authRequired || request.cookies.has(SESSION_COOKIE_NAME)) {
    return NextResponse.next();
  }

  const loginUrl = new URL("/login", request.url);
  loginUrl.searchParams.set("next", request.nextUrl.pathname + request.nextUrl.search);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: [
    /*
     * Match all page routes except:
     * - /login (the login page itself)
     * - /api (proxy routes — protected server-side by the API's own auth gate)
     * - /_next (Next.js internals)
     * - static files (favicon, images, etc.)
     */
    "/((?!login|api|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|css|js)$).*)",
  ],
};
