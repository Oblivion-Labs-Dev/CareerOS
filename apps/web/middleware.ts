import { NextRequest, NextResponse } from "next/server";

// Lightweight redirect only — presence of the cookie, not signature/expiry
// verification (that happens server-side in the API's AuthGateMiddleware on
// every actual data request). This just keeps an unauthenticated visitor from
// landing on a page full of empty/broken widgets before bouncing to /login.
const SESSION_COOKIE_NAME = "co_session";

// Same env resolution as app/api/backend/[...path]/route.ts, so this always
// talks to the same API instance the rest of the app is proxying to.
const API_BASE = process.env.CAREER_OS_API_PUBLIC_URL || process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export async function middleware(request: NextRequest) {
  // Auth is opt-in (CAREER_OS_ADMIN_PASSWORD unset = gate is off entirely) — a
  // fresh checkout with no .env must never lock the owner out of their own
  // local instance. Without this check, "no cookie yet" and "auth not
  // configured" are indistinguishable and every navigation would bounce to
  // /login, which itself redirects back, forever.
  let authRequired = false;
  try {
    const res = await fetch(`${API_BASE.replace(/\/$/, "")}/auth/status`, {
      signal: AbortSignal.timeout(2000),
    });
    if (res.ok) {
      authRequired = Boolean((await res.json()).authRequired);
    }
  } catch {
    // API unreachable (e.g. mid-restart) — fail open rather than lock out a
    // single local user; the API's own AuthGateMiddleware still protects data.
    authRequired = false;
  }

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
