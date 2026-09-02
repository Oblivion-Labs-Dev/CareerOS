import { NextResponse } from "next/server";
import fs from "node:fs";
import path from "node:path";

export async function GET() {
  try {
    // 1. Try local data file path
    const dataPath = path.resolve(process.cwd(), "../../data/benchmark_results.json");
    if (fs.existsSync(dataPath)) {
      const content = fs.readFileSync(dataPath, "utf-8");
      return NextResponse.json(JSON.parse(content));
    }

    // 2. Try root workspace path
    const altPath = path.resolve(process.cwd(), "data/benchmark_results.json");
    if (fs.existsSync(altPath)) {
      const content = fs.readFileSync(altPath, "utf-8");
      return NextResponse.json(JSON.parse(content));
    }

    // 3. Try forwarding to backend API
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    const res = await fetch(`${apiUrl}/benchmarks`, { cache: "no-store" });
    if (res.ok) {
      const data = await res.json();
      return NextResponse.json(data);
    }
  } catch (err) {
    console.error("Failed to load benchmarks route", err);
  }

  return NextResponse.json({ leaderboard: [], recommendation: {}, totalTestCases: 0 });
}
