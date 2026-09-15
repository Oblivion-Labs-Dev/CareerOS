"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import styles from "@/components/diagnostic/diagnostic.module.css";
import { fetchOutcomesReport, type OutcomesReport } from "@/lib/diagnostic-api";
import { OutcomesHistory } from "@/components/diagnostic/outcomes-history";

export default function DiagnosticHistoryPage() {
  const version = useRef(0);
  const [report, setReport] = useState<OutcomesReport | null>(null);
  const [period, setPeriod] = useState("12h");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");

  const load = useCallback(async () => {
    const request = ++version.current;
    try {
      const data = await fetchOutcomesReport(period);
      if (request !== version.current) return;
      setReport(data);
      setLoadError("");
    } catch (err) {
      if (request !== version.current) return;
      console.error("[diagnostic/history] fetchOutcomesReport failed:", err);
      setLoadError("Could not load outcome history. Previously loaded values may be stale.");
    } finally {
      if (request === version.current) setLoading(false);
    }
  }, [period]);

  useEffect(() => {
    void load();
    // Longer windows change slowly and cost more to build, so they refresh less often.
    const interval = setInterval(load, period.endsWith("d") ? 120_000 : 30_000);
    return () => {
      clearInterval(interval);
      version.current++;
    };
  }, [load, period]);

  const handlePeriodChange = (p: string) => {
    if (p === period) return;
    setLoading(true);
    setReport(null);
    setPeriod(p);
  };

  return (
    <div className={styles.pageShell}>
      <header className={styles.pageHeader}>
        <div>
          <h1 className={styles.title}>Autopilot Outcome History</h1>
          <p className={styles.subtitle}>
            Every submission, review hold, failure and skip in the chosen window, and why, taken from
            each attempt&apos;s recorded checkpoints.{" "}
            <Link href="/diagnostic">Back to System Diagnostics</Link>
          </p>
        </div>
      </header>

      {loadError && <p role="alert">{loadError}</p>}

      <OutcomesHistory report={report} period={period} onPeriodChange={handlePeriodChange} loading={loading} />
    </div>
  );
}
