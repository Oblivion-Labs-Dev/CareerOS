import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

const rawBase = process.env.CAREER_OS_API_PUBLIC_URL || process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:4000";
const API_BASE = rawBase.replace("//localhost:", "//127.0.0.1:");

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const target = new URL(`${API_BASE.replace(/\/$/, "")}/${path.join("/")}`);
  target.search = request.nextUrl.search;

  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("origin");
  headers.delete("referer");

  const hasBody = !["GET", "HEAD"].includes(request.method);
  try {
    const response = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
      cache: "no-store",
      redirect: "manual",
    });

    const responseHeaders = new Headers(response.headers);
    responseHeaders.delete("content-encoding");
    responseHeaders.delete("content-length");

    // Guard the upstream stream. The dashboard holds a long-lived SSE
    // connection (/autopilot/events) through this proxy, so every time the API
    // restarts — which `uvicorn --reload` does on any backend edit — that
    // stream is severed mid-flight. Returning `response.body` unwrapped let
    // that surface as an unhandled rejection and take the whole Next dev server
    // down with it: the logs showed the API reloading and answering 200s, then
    // `apps/web dev: Failed`. Closing the stream cleanly turns an upstream
    // restart into a dropped connection the browser simply reconnects after.
    if (!response.body) {
      return new Response(null, { status: response.status, headers: responseHeaders });
    }

    const upstream = response.body;
    const guarded = new ReadableStream({
      async start(controller) {
        const reader = upstream.getReader();
        try {
          for (;;) {
            const { done, value } = await reader.read();
            if (done) break;
            controller.enqueue(value);
          }
          controller.close();
        } catch {
          // Upstream went away (API reload, network blip). End the response
          // instead of rejecting — the client reconnects on its own.
          try {
            controller.close();
          } catch {
            /* already closed */
          }
        } finally {
          reader.releaseLock();
        }
      },
      cancel() {
        upstream.cancel().catch(() => {});
      },
    });

    return new Response(guarded, { status: response.status, headers: responseHeaders });
  } catch (err: any) {
    console.error(`[backend-proxy-error] failed proxying to ${target.toString()}:`, err, err?.cause);
    return Response.json({ detail: "CareerOS API is unavailable.", error: String(err), cause: String(err?.cause), code: err?.cause?.code, target: target.toString() }, { status: 503 });
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
