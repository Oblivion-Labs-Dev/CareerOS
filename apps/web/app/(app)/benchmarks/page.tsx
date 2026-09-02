import { Suspense } from "react";
import { BenchmarkDashboard } from "@/components/benchmark/benchmark-dashboard";

export const metadata = {
  title: "LLM Benchmarks & Safety Leaderboard | CareerOS",
  description: "Direct benchmark comparison across Google Gemini API, Ollama GPT-OSS, Qwen 3B, and Gemma 3 on 40 real application ground truth test cases.",
};

export default function BenchmarksPage() {
  return (
    <div className="page-content" style={{ minHeight: "100vh" }}>
      <Suspense fallback={<div style={{ padding: "2rem", color: "#94a3b8" }}>Loading benchmark dashboard…</div>}>
        <BenchmarkDashboard />
      </Suspense>
    </div>
  );
}
