import { type HTMLAttributes, type ReactNode } from "react";
import { cn } from "./lib/cn";

export type StatePanelKind = "empty" | "loading" | "error";

export interface StatePanelProps
  extends Omit<HTMLAttributes<HTMLDivElement>, "children" | "role" | "title"> {
  kind: StatePanelKind;
  title: string;
  description?: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
  size?: "compact" | "default";
}

const iconToneClasses: Record<StatePanelKind, string> = {
  empty: "border-arsenal-border bg-arsenal-elevated text-arsenal-muted",
  loading: "border-arsenal-accent bg-arsenal-elevated text-arsenal-accent",
  error: "border-arsenal-danger bg-arsenal-elevated text-arsenal-danger",
};

function DefaultStateIcon({ kind }: { kind: StatePanelKind }) {
  if (kind === "loading") {
    return (
      <span
        className="h-5 w-5 animate-spin rounded-full border-2 border-arsenal-border border-t-arsenal-accent"
        aria-hidden="true"
      />
    );
  }

  return (
    <span aria-hidden="true" className="text-lg font-semibold leading-none">
      {kind === "error" ? "!" : "—"}
    </span>
  );
}

export function StatePanel({
  kind,
  title,
  description,
  icon,
  action,
  size = "default",
  className,
  ...props
}: StatePanelProps) {
  const role = kind === "error" ? "alert" : "status";
  const live = kind === "error" ? "assertive" : "polite";

  return (
    <div
      {...props}
      role={role}
      aria-live={live}
      aria-busy={kind === "loading" ? true : undefined}
      className={cn(
        "flex w-full min-w-0 flex-col items-center justify-center rounded-arsenal border border-arsenal-border bg-arsenal-surface text-center",
        size === "compact" ? "gap-2 px-4 py-5" : "gap-3 px-5 py-8 sm:px-8 sm:py-10",
        className,
      )}
      data-state={kind}
    >
      <span
        className={cn(
          "inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full border",
          iconToneClasses[kind],
        )}
        aria-hidden="true"
      >
        {icon ?? <DefaultStateIcon kind={kind} />}
      </span>
      <div className="min-w-0 max-w-lg">
        <p className="text-sm font-semibold text-arsenal-primary sm:text-base">{title}</p>
        {description ? (
          <div className="mt-1 text-sm leading-relaxed text-arsenal-secondary">{description}</div>
        ) : null}
      </div>
      {action ? <div className="mt-1 flex flex-wrap justify-center gap-2">{action}</div> : null}
    </div>
  );
}
