"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { DonutProgressRing } from "@/components/application-assistant/autopilot/donut-progress-ring";
import { getAutopilotStatus } from "@/lib/application-assistant-api";
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
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    // Use the shared helper rather than a bare fetch against
    // NEXT_PUBLIC_API_URL: that origin (127.0.0.1) differs from the one the app
    // is served from (localhost), so the session cookie was never sent and the
    // request came back 401 — which this card then rendered as "no activity".
    getAutopilotStatus()
      .then((data) => {
        if (!cancelled) setCumulative(data?.cumulative ?? {});
      })
      .catch(() => {
        if (!cancelled) setLoadError(true);
      })
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

  // "Couldn't load" and "nothing has run yet" are different claims — saying the
  // second when we mean the first contradicts the counters elsewhere on the page.
  if (loadError) {
    return <p className={styles.muted}>Couldn&apos;t load Autopilot activity. Retry in a moment.</p>;
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
