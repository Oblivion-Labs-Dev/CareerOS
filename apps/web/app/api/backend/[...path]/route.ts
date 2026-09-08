import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

const API_BASE = process.env.CAREER_OS_API_PUBLIC_URL || process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:4000";

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
    return new Response(response.body, { status: response.status, headers: responseHeaders });
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
