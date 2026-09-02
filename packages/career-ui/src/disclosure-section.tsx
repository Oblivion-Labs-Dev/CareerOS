"use client";

import { useId, useState, type HTMLAttributes, type ReactNode } from "react";
import { cn } from "./lib/cn";

export type DisclosureHeadingLevel = 2 | 3 | 4 | 5 | 6;

export interface DisclosureSectionProps
  extends Omit<HTMLAttributes<HTMLElement>, "children" | "title"> {
  title: string;
  children: ReactNode;
  summary?: string;
  leading?: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  disabled?: boolean;
  headingLevel?: DisclosureHeadingLevel;
  headerClassName?: string;
  contentClassName?: string;
}

export function DisclosureSection({
  title,
  children,
  summary,
  leading,
  meta,
  actions,
  open,
  defaultOpen = false,
  onOpenChange,
  disabled = false,
  headingLevel = 3,
  className,
  headerClassName,
  contentClassName,
  id,
  ...props
}: DisclosureSectionProps) {
  const generatedId = useId();
  const [internalOpen, setInternalOpen] = useState(defaultOpen);
  const isControlled = open !== undefined;
  const expanded = isControlled ? open : internalOpen;
  const sectionId = id ?? generatedId;
  const contentId = `${sectionId}-content`;
  const Heading: `h${DisclosureHeadingLevel}` = `h${headingLevel}`;

  const toggle = () => {
    if (disabled) return;
    const nextOpen = !expanded;
    if (!isControlled) setInternalOpen(nextOpen);
    onOpenChange?.(nextOpen);
  };

  return (
    <section
      {...props}
      id={id}
      className={cn(
        "overflow-hidden rounded-arsenal border border-arsenal-border bg-arsenal-surface",
        className,
      )}
      data-state={expanded ? "open" : "closed"}
    >
      <div
        className={cn(
          "flex min-w-0 flex-col gap-2 p-4 sm:flex-row sm:items-center sm:p-5",
          headerClassName,
        )}
      >
        <Heading className="m-0 min-w-0 flex-1 text-base font-semibold">
          <button
            type="button"
            className={cn(
              "flex w-full min-w-0 items-center gap-3 rounded-arsenal-sm text-left text-arsenal-primary",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-arsenal-accent focus-visible:ring-offset-2 focus-visible:ring-offset-arsenal-surface",
              disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer",
            )}
            aria-expanded={expanded}
            aria-controls={contentId}
            disabled={disabled}
            onClick={toggle}
          >
            {leading ? (
              <span aria-hidden="true" className="shrink-0 text-arsenal-accent">
                {leading}
              </span>
            ) : null}
            <span className="min-w-0 flex-1">
              <span className="block truncate">{title}</span>
              {summary ? (
                <span className="mt-1 block text-sm font-normal leading-relaxed text-arsenal-secondary">
                  {summary}
                </span>
              ) : null}
            </span>
            {meta ? (
              <span className="hidden shrink-0 text-xs font-medium text-arsenal-muted sm:inline-flex">
                {meta}
              </span>
            ) : null}
            <span
              aria-hidden="true"
              className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-arsenal-border bg-arsenal-elevated text-lg font-normal leading-none text-arsenal-secondary"
            >
              {expanded ? "−" : "+"}
            </span>
          </button>
        </Heading>
        {actions ? <div className="shrink-0 sm:pl-2">{actions}</div> : null}
      </div>
      <div
        id={contentId}
        hidden={!expanded}
        className={cn(
          "border-t border-arsenal-border p-4 text-arsenal-secondary sm:p-5",
          contentClassName,
        )}
      >
        {children}
      </div>
    </section>
  );
}
