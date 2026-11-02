import { Suspense } from "react";
import { MatcherBenchmark } from "@/components/benchmark/matcher-benchmark";

export const metadata = {
  title: "Matcher Benchmark | CareerOS",
  description:
    "Nine resume-to-job matching approaches measured on real postings: BM25, TF-IDF, role shape, MiniLM, cross-encoder and a trained hybrid.",
};

export default function MatcherBenchmarkPage() {
  return (
    <div className="page-content">
      <Suspense fallback={<div style={{ padding: "2rem" }}>Loading benchmark…</div>}>
        <MatcherBenchmark />
      </Suspense>
    </div>
  );
}
