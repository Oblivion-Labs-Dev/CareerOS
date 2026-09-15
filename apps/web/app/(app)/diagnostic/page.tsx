"use client";

import React, { useEffect, useState, useCallback, useRef } from "react";
import Link from "next/link";
import styles from "@/components/diagnostic/diagnostic.module.css";
import {
  fetchSystemHealth, fetchDiagnosticSeries, type DiagnosticSeries,
  fetchAutopilotMetrics,
  fetchLiveRuns,
  fetchDiagnosticErrors,
  fetchSystemAlarms,
  type SystemHealthData,
  type AutopilotMetricsData,
  type LiveRunRecord,
  type DiagnosticErrorItem,
  type SystemAlarmItem,
} from "@/lib/diagnostic-api";
import { SystemHealthCard } from "@/components/diagnostic/system-health-card";
import { AutopilotMetricsCard } from "@/components/diagnostic/autopilot-metrics-card";
import { LiveRunsTable } from "@/components/diagnostic/live-runs-table";
import { ErrorsTable } from "@/components/diagnostic/errors-table";
import { AlarmsPanel } from "@/components/diagnostic/alarms-panel";

import { TelemetryCharts } from "@/components/diagnostic/telemetry-charts";

export default function DiagnosticPage() {
  const version = useRef(0);
  const [series,setSeries] = useState<DiagnosticSeries|null>(null);
  const [loadError,setLoadError] = useState("");
  const [healthData, setHealthData] = useState<SystemHealthData | null>(null);
  const [metricsData, setMetricsData] = useState<AutopilotMetricsData | null>(null);
  const [period, setPeriod] = useState<"1h" | "24h" | "7d">("24h");
  const [runs, setRuns] = useState<LiveRunRecord[]>([]);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [errors, setErrors] = useState<DiagnosticErrorItem[]>([]);
  const [errorSeverity, setErrorSeverity] = useState<string>("all");
  const [errorService, setErrorService] = useState<string>("all");
  const [errorSearch, setErrorSearch] = useState<string>("");
  const [alarms, setAlarms] = useState<SystemAlarmItem[]>([]);
  const [loading, setLoading] = useState(true);

  const loadAll = useCallback(async () => {
    const request = ++version.current;
    try {
      const [hRes, mRes, rRes, eRes, aRes, sRes] = await Promise.allSettled([
        fetchSystemHealth(),
        fetchAutopilotMetrics(period),
        fetchLiveRuns(),
        fetchDiagnosticErrors({ severity: errorSeverity, service: errorService, search: errorSearch }),
        fetchSystemAlarms(), fetchDiagnosticSeries(period),
      ]);

      if(request !== version.current) return;
      setLoadError([hRes,mRes,rRes,eRes,aRes,sRes].some(r=>r.status==="rejected")?"Some telemetry could not refresh. Previously loaded values may be stale.":"");
      if(sRes.status==="fulfilled") setSeries(sRes.value);
      if (hRes.status === "fulfilled") setHealthData(hRes.value);
      else console.error("[diagnostic] fetchSystemHealth failed:", hRes.reason);

      if (mRes.status === "fulfilled") setMetricsData(mRes.value);
      else console.error("[diagnostic] fetchAutopilotMetrics failed:", mRes.reason);

      if (rRes.status === "fulfilled") {
        setRuns(rRes.value.runs);
        setActiveRunId(rRes.value.activeRunId);
      } else console.error("[diagnostic] fetchLiveRuns failed:", rRes.reason);

      if (eRes.status === "fulfilled") setErrors(eRes.value.errors);
      else console.error("[diagnostic] fetchDiagnosticErrors failed:", eRes.reason);

      if (aRes.status === "fulfilled") setAlarms(aRes.value.alarms);
      else console.error("[diagnostic] fetchSystemAlarms failed:", aRes.reason);
    } catch (err) {
      console.error("[diagnostic] loadAll error:", err);
    } finally {
      setLoading(false);
    }
  }, [period, errorSeverity, errorService, errorSearch]);

  useEffect(() => {
    void loadAll();
    const interval = setInterval(loadAll, 10_000);
    return () => {clearInterval(interval);version.current++;};
  }, [loadAll]);

  const handlePeriodChange = (p: "1h" | "24h" | "7d") => {
    setSeries(null);setMetricsData(null);setLoading(true);setPeriod(p);
  };

  return (
    <div className={styles.pageShell}>
      <header className={styles.pageHeader}>
        <div>
          <h1 className={styles.title}>System Diagnostics &amp; Telemetry</h1>
          <p className={styles.subtitle}>
            Recorded activity, timing and service health. Refreshes every 10 seconds.{" "}
            <Link href="/diagnostic/history">View outcome history &amp; failure reasons →</Link>
          </p>
        </div>
      </header>

      {loadError&&<p role="alert">{loadError}</p>}
      <AutopilotMetricsCard metrics={metricsData} period={period} onPeriodChange={handlePeriodChange} loading={loading}/>
      <TelemetryCharts data={series} loading={loading}/>
      {/* 1. System Health */}
      <SystemHealthCard
        services={healthData?.services ?? []}
        overallStatus={healthData?.overallStatus ?? "Healthy"}
        updatedAt={healthData?.updatedAt ?? ""}
        onRefresh={loadAll}
        loading={loading}
      />

      {/* 3. Live & Recent Runs */}
      <LiveRunsTable
        runs={runs}
        activeRunId={activeRunId}
        loading={loading}
      />

      {/* 4. Errors Ledger */}
      <ErrorsTable
        errors={errors}
        severity={errorSeverity}
        service={errorService}
        search={errorSearch}
        onSeverityChange={setErrorSeverity}
        onServiceChange={setErrorService}
        onSearchChange={setErrorSearch}
        loading={loading}
      />

      {/* 5. System Alarms */}
      <AlarmsPanel
        alarms={alarms}
        onAlarmsChanged={loadAll}
        loading={loading}
      />
    </div>
  );
}
