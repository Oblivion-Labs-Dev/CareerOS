import { NextResponse } from "next/server";
import { getExtensionDistPath } from "@/lib/extension-dist-path";

export const runtime = "nodejs";

export function GET() {
  const { distPath, distReady } = getExtensionDistPath();
  return NextResponse.json({ distPath, distReady });
}