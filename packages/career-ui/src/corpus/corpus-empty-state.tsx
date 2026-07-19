"use client";

import { PrimaryButton, SecondaryButton, StatePanel } from "@arsenal/ui";

export interface CorpusEmptyStateProps {
  title: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
  secondaryLabel?: string;
  onSecondary?: () => void;
}

export function CorpusEmptyState({
  title,
  description,
  actionLabel,
  onAction,
  secondaryLabel,
  onSecondary,
}: CorpusEmptyStateProps) {
  return (
    <div className="flex flex-col items-center gap-4 py-10">
      <StatePanel kind="empty" title={title} description={description} />
      {(actionLabel || secondaryLabel) && (
        <div className="flex flex-wrap items-center justify-center gap-2">
          {actionLabel && onAction ? (
            <PrimaryButton onClick={onAction}>
              {actionLabel}
            </PrimaryButton>
          ) : null}
          {secondaryLabel && onSecondary ? (
            <SecondaryButton onClick={onSecondary}>
              {secondaryLabel}
            </SecondaryButton>
          ) : null}
        </div>
      )}
    </div>
  );
}
