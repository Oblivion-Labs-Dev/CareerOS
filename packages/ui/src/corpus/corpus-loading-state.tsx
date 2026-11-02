"use client";

export interface CorpusLoadingStateProps {
  label?: string;
}

export function CorpusLoadingState({ label = "Loading corpus…" }: CorpusLoadingStateProps) {
  return (
    <div
      className="flex flex-col items-center justify-center gap-3 py-16"
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <div
        className="h-8 w-8 animate-spin rounded-full border-2 border-arsenal-border border-t-arsenal-accent"
        aria-hidden="true"
      />
      <span className="text-xs font-semibold text-arsenal-muted">{label}</span>
    </div>
  );
}
