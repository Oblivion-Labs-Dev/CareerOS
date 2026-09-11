import { Suspense } from "react";
import { GeminiDiagnostics } from "@/components/diagnostics/gemini-diagnostics";

export const metadata = {
  title: "Gemini Diagnostics | CareerOS",
  description:
    "Health, queue depth, cache hit rate and failure counts for the optional Gemini enrichment layer.",
};

export default function GeminiDiagnosticsPage() {
  return (
    <div className="page-content">
      <Suspense fallback={<div style={{ padding: "2rem" }}>Loading diagnostics…</div>}>
        <GeminiDiagnostics />
      </Suspense>
    </div>
  );
}
