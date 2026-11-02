import { useId, type HTMLAttributes, type ReactNode } from "react";
import { cn } from "./lib/cn";

export type StatusMarkerTone = "neutral" | "info" | "success" | "warning" | "danger";

export interface StatusMarkerProps
  extends Omit<HTMLAttributes<HTMLSpanElement>, "children" | "title"> {
  /** Decorative symbol that reinforces the status without replacing its visible label. */
  icon: ReactNode;
  /** Short status text that always remains visible, including in compact mode. */
  label: ReactNode;
  /** Additional context announced by assistive technology. */
  description: string;
  /** Semantic color treatment exposed through `data-tone`. */
  tone?: StatusMarkerTone;
  /** Reduces spacing and type size without hiding the label. */
  compact?: boolean;
  /** Optional native hover text. The description can also be passed to `Tooltip`. */
  title?: string;
}

const toneClasses: Record<StatusMarkerTone, string> = {
  neutral: "border-arsenal-border bg-arsenal-elevated text-arsenal-secondary",
  info: "border-arsenal-accent/30 bg-arsenal-accent/10 text-arsenal-accent",
  success: "border-arsenal-success/30 bg-arsenal-success/10 text-arsenal-success",
  warning: "border-amber-500/30 bg-amber-500/10 text-amber-400",
  danger: "border-arsenal-danger/30 bg-arsenal-danger/10 text-arsenal-danger",
};

export function StatusMarker({
  icon,
  label,
  description,
  tone = "neutral",
  compact = false,
  title,
  className,
  id,
  ...props
}: StatusMarkerProps) {
  const generatedId = useId();
  const markerId = id ?? generatedId;
  const descriptionId = `${markerId}-description`;
  const describedBy = [props["aria-describedby"], descriptionId].filter(Boolean).join(" ");

  return (
    <span
      {...props}
      id={id}
      title={title}
      aria-describedby={describedBy}
      className={cn(
        "inline-flex max-w-full items-center rounded-full border font-semibold leading-none",
        compact ? "gap-1 px-2 py-0.5 text-[0.6875rem]" : "gap-1.5 px-2.5 py-1 text-xs",
        toneClasses[tone],
        className,
      )}
      data-tone={tone}
      data-compact={compact ? "true" : "false"}
    >
      <span
        aria-hidden="true"
        className={cn(
          "inline-flex shrink-0 items-center justify-center",
          compact ? "h-3 w-3" : "h-3.5 w-3.5",
        )}
      >
        {icon}
      </span>
      <span className="min-w-0 truncate">{label}</span>
      <span id={descriptionId} className="sr-only">
        {description}
      </span>
    </span>
  );
}
