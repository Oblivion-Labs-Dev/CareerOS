"use client";

interface DonutProgressRingProps {
  processed: number;
  target: number;
  submitted: number;
  staged: number;
  skipped: number;
  failed: number;
  isCompleted?: boolean;
  onSelectSegment?: (key: "submitted" | "staged" | "skipped" | "failed") => void;
}

const LEGEND = [
  { key: "submitted", label: "Submitted", color: "#10e6bb" },
  { key: "staged", label: "Staged", color: "#ffad3d" },
  { key: "skipped", label: "Skipped", color: "#9563f4" },
  { key: "failed", label: "Failed", color: "#ff5264" },
] as const;

export function DonutProgressRing({
  processed,
  target,
  submitted,
  staged,
  skipped,
  failed,
  isCompleted,
  onSelectSegment,
}: DonutProgressRingProps) {
  const safeTotal = Math.max(1, submitted + staged + skipped + failed);
  const radius = 54;
  const circumference = 2 * Math.PI * radius;
  const values = { submitted, staged, skipped, failed };
  let cumulative = 0;

  return (
    <div className="autopilot-donut-layout">
      <div className="autopilot-donut">
        <svg viewBox="0 0 140 140" aria-hidden>
          <circle cx="70" cy="70" r={radius} fill="none" stroke="rgba(104,132,164,.13)" strokeWidth="9" />
          {LEGEND.map((item) => {
            const value = values[item.key];
            const segment = (value / safeTotal) * circumference;
            const offset = -cumulative;
            cumulative += segment;
            return value > 0 ? (
              <circle
                key={item.key}
                cx="70"
                cy="70"
                r={radius}
                fill="none"
                stroke={item.color}
                strokeWidth="9"
                strokeDasharray={`${segment} ${circumference}`}
                strokeDashoffset={offset}
                strokeLinecap="butt"
                style={{ cursor: onSelectSegment ? "pointer" : "default" }}
                onClick={() => onSelectSegment?.(item.key)}
              />
            ) : null;
          })}
        </svg>
        <span className="autopilot-donut-center">
          <strong>{isCompleted ? target : processed}</strong>
          <small>{isCompleted ? "Complete" : "Processed"}</small>
        </span>
      </div>

      <div className="autopilot-donut-legend">
        {LEGEND.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => onSelectSegment?.(item.key)}
            className="autopilot-donut-legend-item text-left bg-transparent border-none p-0 cursor-pointer hover:opacity-80 transition-opacity"
          >
            <span><i style={{ background: item.color }} />{item.label}</span>
            <strong>{values[item.key]}</strong>
          </button>
        ))}
      </div>
    </div>
  );
}

