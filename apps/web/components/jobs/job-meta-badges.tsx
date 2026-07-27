type H1bStatus = "likely" | "unlikely" | "unknown";

export type JobMetaBadgesProps = {
  location?: string;
  salaryRange?: string;
  employmentType?: string;
  h1bStatus?: H1bStatus;
  h1bLabel?: string;
  h1bReason?: string;
  h1bSignals?: string[];
  freshnessLabel?: string;
  className?: string;
  /** Omit location pill — use when location is shown as standalone text on cards */
  hideLocation?: boolean;
};

function h1bClass(status?: H1bStatus): string {
  if (status === "likely") return "job-meta-pill job-meta-pill--h1b-likely";
  if (status === "unlikely") return "job-meta-pill job-meta-pill--h1b-unlikely";
  return "job-meta-pill job-meta-pill--h1b-unknown";
}

export function JobMetaBadges({
  location,
  salaryRange,
  employmentType,
  h1bStatus,
  h1bLabel,
  h1bReason,
  h1bSignals,
  freshnessLabel,
  className = "",
  hideLocation = false,
}: JobMetaBadgesProps) {
  const pills: Array<{ key: string; className: string; label: string; title?: string }> = [];

  if (!hideLocation && location?.trim()) {
    pills.push({ key: "location", className: "job-meta-pill job-meta-pill--location", label: location.trim() });
  }

  if (salaryRange?.trim()) {
    pills.push({
      key: "salary",
      className: "job-meta-pill job-meta-pill--salary",
      label: salaryRange.trim(),
      title: "Compensation range",
    });
  }

  if (employmentType?.trim()) {
    pills.push({
      key: "employment",
      className: "job-meta-pill job-meta-pill--employment",
      label: employmentType.trim(),
    });
  }

  if (h1bLabel) {
    pills.push({
      key: "h1b",
      className: h1bClass(h1bStatus),
      label: h1bLabel,
      title: h1bSignals?.length ? h1bSignals.join(" · ") : h1bReason,
    });
  }

  if (freshnessLabel?.trim()) {
    pills.push({
      key: "freshness",
      className: "job-meta-pill job-meta-pill--freshness",
      label: freshnessLabel.trim(),
    });
  }

  if (!pills.length) return null;

  return (
    <div className={`job-meta-pills ${className}`.trim()}>
      {pills.map((pill) => (
        <span key={pill.key} className={pill.className} title={pill.title}>
          {pill.label}
        </span>
      ))}
    </div>
  );
}
