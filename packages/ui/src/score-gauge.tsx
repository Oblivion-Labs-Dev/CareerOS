import { useId, type HTMLAttributes } from "react";
import { cn } from "./lib/cn";

export type ScoreGaugeTone = "accent" | "success" | "danger" | "neutral";

export type ScoreGaugeSize = "sm" | "md" | "lg";

export interface ScoreGaugeProps
  extends Omit<HTMLAttributes<HTMLDivElement>, "children" | "role"> {
  value: number;
  label: string;
  min?: number;
  max?: number;
  valueLabel?: string;
  description?: string;
  tone?: ScoreGaugeTone;
  size?: ScoreGaugeSize;
}

export interface NormalizedScoreRange {
  min: number;
  max: number;
  value: number;
  percentage: number;
}

const gaugeColorVariables: Record<ScoreGaugeTone, string> = {
  accent: "var(--arsenal-accent)",
  success: "var(--arsenal-success)",
  danger: "var(--arsenal-danger)",
  neutral: "var(--arsenal-muted)",
};

const gaugeSizeClasses: Record<ScoreGaugeSize, string> = {
  sm: "h-20 w-20 p-1",
  md: "h-28 w-28 p-1.5",
  lg: "h-36 w-36 p-2",
};

const valueSizeClasses: Record<ScoreGaugeSize, string> = {
  sm: "text-lg",
  md: "text-2xl",
  lg: "text-3xl",
};

/** Normalize score input so the meter always exposes finite, valid ARIA values. */
export function normalizeScoreRange(value: number, min = 0, max = 100): NormalizedScoreRange {
  const safeMin = Number.isFinite(min) ? min : 0;
  const safeMax = Number.isFinite(max) && max > safeMin ? max : safeMin + 100;
  const finiteValue = Number.isFinite(value) ? value : safeMin;
  const safeValue = Math.min(Math.max(finiteValue, safeMin), safeMax);
  const percentage = ((safeValue - safeMin) / (safeMax - safeMin)) * 100;

  return { min: safeMin, max: safeMax, value: safeValue, percentage };
}

function defaultValueLabel(value: number, min: number, max: number): string {
  const rounded = Number.isInteger(value) ? String(value) : value.toFixed(1);
  return min === 0 && max === 100 ? `${rounded}%` : rounded;
}

export function ScoreGauge({
  value,
  label,
  min = 0,
  max = 100,
  valueLabel,
  description,
  tone = "accent",
  size = "md",
  className,
  id,
  ...props
}: ScoreGaugeProps) {
  const generatedId = useId();
  const labelId = `${id ?? generatedId}-label`;
  const descriptionId = description ? `${id ?? generatedId}-description` : undefined;
  const score = normalizeScoreRange(value, min, max);
  const resolvedValueLabel = valueLabel ?? defaultValueLabel(score.value, score.min, score.max);
  const labelledBy = props["aria-labelledby"] ?? labelId;
  const describedBy = props["aria-describedby"] ?? descriptionId;

  return (
    <div
      {...props}
      id={id}
      role="meter"
      aria-valuemin={score.min}
      aria-valuemax={score.max}
      aria-valuenow={score.value}
      aria-valuetext={resolvedValueLabel}
      aria-labelledby={labelledBy}
      aria-describedby={describedBy}
      className={cn("inline-flex min-w-0 flex-col items-center gap-3 text-center", className)}
      data-size={size}
      data-tone={tone}
    >
      <div
        aria-hidden="true"
        className={cn("grid shrink-0 place-items-center rounded-full", gaugeSizeClasses[size])}
        style={{
          background: `conic-gradient(${gaugeColorVariables[tone]} ${score.percentage}%, var(--arsenal-border) ${score.percentage}% 100%)`,
        }}
      >
        <div className="grid h-full w-full place-items-center rounded-full border border-arsenal-border bg-arsenal-surface">
          <span
            className={cn(
              "font-semibold leading-none tracking-tight text-arsenal-primary tabular-nums",
              valueSizeClasses[size],
            )}
          >
            {resolvedValueLabel}
          </span>
        </div>
      </div>
      <div className="min-w-0 max-w-xs">
        <p id={labelId} className="text-sm font-semibold text-arsenal-primary">
          {label}
        </p>
        {description ? (
          <p id={descriptionId} className="mt-1 text-xs leading-relaxed text-arsenal-secondary">
            {description}
          </p>
        ) : null}
      </div>
    </div>
  );
}
