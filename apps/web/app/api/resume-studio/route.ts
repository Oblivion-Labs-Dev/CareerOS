import { existsSync } from "node:fs";
import path from "node:path";
import { NextRequest, NextResponse } from "next/server";
import { composeInLocalWorker } from "@/lib/resume-studio-worker";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
let activeWorker = false;

export async function POST(request: NextRequest) {
  const input = await request.json().catch(() => null);
  if (input && input.mode === undefined) input.mode = "honest";
  if (!input || typeof input.jobDescription !== "string" || input.jobDescription.trim().length < 40 || input.jobDescription.length > 40000
    || (input.useSemantic !== undefined && typeof input.useSemantic !== "boolean")
    || !["off", "honest", "aggressive"].includes(input.mode)
    || (input.targetRole !== undefined && (typeof input.targetRole !== "string" || input.targetRole.length > 200))
    || (input.targetCompany !== undefined && (typeof input.targetCompany !== "string" || input.targetCompany.length > 200))) {
    return NextResponse.json({ detail: "Paste a job description between 40 and 40,000 characters." }, { status: 422 });
  }
  // Match the existing authenticated backend proxy, including its configured
  // API address; the older shared client helper defaults to another port.
  const api = (process.env.CAREER_OS_API_PUBLIC_URL || process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:4000")
    .replace("//localhost:", "//127.0.0.1:").replace(/\/$/, "");
  const headers = { "Content-Type": "application/json", cookie: request.headers.get("cookie") || "" };
  try {
    const response = await fetch(`${api}/resume/studio`, { method: "POST", headers, body: JSON.stringify(input), cache: "no-store", signal: request.signal });
    if (response.status !== 404) {
      const body = await response.text();
      const result = response.ok ? JSON.parse(body) : null;
      // A running older API may accept but silently ignore the new mode. Use
      // the local worker until that API is upgraded; do not interrupt its jobs.
      if (!response.ok || (result?.result?.mode === input.mode && result?.matchComparison && result?.result?.tailoringSummary && (input.useSemantic === undefined || result?.result?.tailoringConfig?.use_semantic === (input.mode === "off" ? false : input.useSemantic)))) {
        return new NextResponse(body, { status: response.status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
      }
    }

    // Do not restart an older API while its application runner is busy. Read
    // authenticated snapshots and invoke the very same new composer locally.
    const [profileResponse, recordsResponse] = await Promise.all([
      fetch(`${api}/profile`, { headers, cache: "no-store", signal: request.signal }),
      fetch(`${api}/accomplishments`, { headers, cache: "no-store", signal: request.signal }),
    ]);
    if (!profileResponse.ok || !recordsResponse.ok) {
      return NextResponse.json({ detail: "Sign in and make sure your profile is available before generating." }, { status: !profileResponse.ok ? profileResponse.status : recordsResponse.status });
    }
    const [profile, records] = await Promise.all([profileResponse.json(), recordsResponse.json()]);
    const apiRoot = path.resolve(process.cwd(), "../api");
    const python = path.join(apiRoot, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
    if (!existsSync(python)) return NextResponse.json({ detail: "Restart the API to enable Resume Studio, or restore its local Python environment." }, { status: 503 });
    if (activeWorker) return NextResponse.json({ detail: "A resume is already being generated. Please try again in a moment." }, { status: 429 });
    activeWorker = true;
    try {
      const data = await composeInLocalWorker(python, apiRoot,
        { ...input, profile: profile.profile || {}, records: records.accomplishments || [] }, request.signal);
      const result = JSON.parse(data);
      return NextResponse.json(result, { status: result.success ? 200 : 422, headers: { "Cache-Control": "no-store" } });
    } finally { activeWorker = false; }
  } catch {
    return NextResponse.json({ detail: "Generation could not finish. Your profile is unchanged; please try again." }, { status: 503 });
  }
}
