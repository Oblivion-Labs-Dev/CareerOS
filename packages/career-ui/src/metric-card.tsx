import { useId, type HTMLAttributes, type ReactNode } from "react";
import { cn } from "./lib/cn";

export type MetricTone = "default" | "accent" | "success" | "danger";

export type MetricTrendDirection = "up" | "down" | "neutral";

export type MetricTrendTone = "neutral" | "accent" | "success" | "danger";

export interface MetricTrend {
  label: string;
  direction?: MetricTrendDirection;
  tone?: MetricTrendTone;
}

export interface MetricCardProps
  extends Omit<HTMLAttributes<HTMLElement>, "children" | "title"> {
  label: string;
  value: string | number;
  description?: ReactNode;
  trend?: MetricTrend;
  icon?: ReactNode;
  action?: ReactNode;
  tone?: MetricTone;
  valueClassName?: string;
}

const valueToneClasses: Record<MetricTone, string> = {
  default: "text-arsenal-primary",
  accent: "text-arsenal-accent",
  success: "text-arsenal-success",
  danger: "text-arsenal-danger",
};

const trendToneClasses: Record<MetricTrendTone, string> = {
  neutral: "text-arsenal-muted",
  accent: "text-arsenal-accent",
  success: "text-arsenal-success",
  danger: "text-arsenal-danger",
};

const trendSymbols: Record<MetricTrendDirection, string> = {
  up: "↑",
  down: "↓",
  neutral: "—",
};

const trendDirectionLabels: Record<MetricTrendDirection, string> = {
  up: "Increasing",
  down: "Decreasing",
  neutral: "No change",
};

export function MetricCard({
  label,
  value,
  description,
  trend,
  icon,
  action,
  tone = "default",
  className,
  valueClassName,
  id,
  ...props
}: MetricCardProps) {
  const generatedId = useId();
  const labelId = `${id ?? generatedId}-label`;
  const labelledBy = props["aria-labelledby"] ?? labelId;
  const trendDirection = trend?.direction ?? "neutral";
  const trendTone = trend?.tone ?? "neutral";

  return (
    <article
      {...props}
      id={id}
      aria-labelledby={labelledBy}
      className={cn(
        "min-w-0 rounded-arsenal border border-arsenal-border bg-arsenal-surface p-4 shadow-arsenal sm:p-5",
        className,
      )}
      data-tone={tone}
    >
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="min-w-0">
          <p
            id={labelId}
            className="truncate text-xs font-semibold uppercase tracking-wider text-arsenal-muted"
          >
            {label}
          </p>
          <p
            className={cn(
              "mt-2 break-words text-2xl font-semibold leading-none tracking-tight tabular-nums sm:text-3xl",
              valueToneClasses[tone],
              valueClassName,
            )}
          >
            {value}
          </p>
        </div>
        {icon ? (
          <span
            aria-hidden="true"
            className={cn(
              "inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-arsenal-sm border border-arsenal-border bg-arsenal-elevated",
              valueToneClasses[tone],
            )}
          >
            {icon}
          </span>
        ) : null}
      </div>

      {description || trend || action ? (
        <div className="mt-4 flex min-w-0 flex-wrap items-end justify-between gap-3 border-t border-arsenal-border pt-3">
          <div className="min-w-0 flex-1">
            {description ? (
              <div className="text-sm leading-relaxed text-arsenal-secondary">{description}</div>
            ) : null}
            {trend ? (
              <span
                className={cn(
                  "mt-1 inline-flex items-center gap-1 text-xs font-medium",
                  trendToneClasses[trendTone],
                )}
                aria-label={`${trendDirectionLabels[trendDirection]}: ${trend.label}`}
              >
                <span aria-hidden="true">{trendSymbols[trendDirection]}</span>
                {trend.label}
              </span>
            ) : null}
          </div>
          {action ? <div className="shrink-0">{action}</div> : null}
        </div>
      ) : null}
    </article>
  );
}
