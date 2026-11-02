export type CorpusPerformanceMetric =
  | "initial-load"
  | "search"
  | "editor-update"
  | "graph-ready"
  | "resume-generation";

export function recordCorpusPerformance(
  metric: CorpusPerformanceMetric,
  durationMs: number,
  detail: Record<string, string | number | boolean> = {},
) {
  if (typeof window === "undefined" || typeof window.performance === "undefined") return;
  const payload = { metric, durationMs: Math.max(0, Math.round(durationMs * 100) / 100), ...detail };
  try {
    window.performance.mark(`careeros:resume-corpus:${metric}`, { detail: payload });
    window.dispatchEvent(new CustomEvent("careeros:resume-corpus-performance", { detail: payload }));
  } catch {
    // Instrumentation must never interrupt editing or navigation.
  }
}
