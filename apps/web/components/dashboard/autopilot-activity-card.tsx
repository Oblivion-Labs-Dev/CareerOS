"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { DonutProgressRing } from "@/components/application-assistant/autopilot/donut-progress-ring";
import { getClientApiBaseUrl } from "@/lib/api";
import styles from "./minimal-dashboard.module.css";

type Cumulative = {
  submitted?: number;
  staged?: number;
  skipped?: number;
  failed?: number;
  processed?: number;
};

const SEGMENT_TAB: Record<"submitted" | "staged" | "skipped" | "failed", string> = {
  submitted: "submitted",
  staged: "review",
  skipped: "skipped",
  failed: "failed",
};

export function AutopilotActivityCard() {
  const router = useRouter();
  const [cumulative, setCumulative] = useState<Cumulative | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const api = getClientApiBaseUrl();
    fetch(`${api}/application-assistant/autopilot/status`, { credentials: "include" })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!cancelled && data?.cumulative) setCumulative(data.cumulative);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return <p className={styles.muted}>Loading Autopilot activity…</p>;
  }

  const submitted = cumulative?.submitted ?? 0;
  const staged = cumulative?.staged ?? 0;
  const skipped = cumulative?.skipped ?? 0;
  const failed = cumulative?.failed ?? 0;
  const processed = cumulative?.processed ?? submitted + staged + skipped + failed;

  if (processed === 0) {
    return (
      <p className={styles.empty}>
        No Autopilot activity yet. Add jobs and start a run on the{" "}
        <a href="/applications?tab=autopilot">Autopilot</a> page.
      </p>
    );
  }

  return (
    <DonutProgressRing
      processed={processed}
      target={processed}
      submitted={submitted}
      staged={staged}
      skipped={skipped}
      failed={failed}
      isCompleted
      onSelectSegment={(seg) => router.push(`/applications?tab=${SEGMENT_TAB[seg]}`)}
    />
  );
}
