"use client";

import React, { useEffect, useState } from "react";
import { getAutopilotStatus } from "@/lib/application-assistant-api";
import { IconActivity } from "./autopilot/icons";

interface ConcurrencyMetrics {
  activeWorkers?: number;
  totalWorkers?: number;
  avgJobTimeSec?: number;
  throughputPerMin?: number;
  totalJobsFinished?: number;
}

/**
 * Throughput and timing for the current Autopilot batch, straight from
 * `concurrencyMetrics` on the status endpoint. Nothing here is estimated: a
 * value the runner has not measured yet (no finished job, status not loaded)
 * shows as "—", never as a plausible default.
 */
export function LatencyDiagnosticsCenter() {
  const [metrics, setMetrics] = useState<ConcurrencyMetrics | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const fetchMetrics = async () => {
      try {
        const res: any = await getAutopilotStatus();
        if (cancelled) return;
        setMetrics(res?.concurrencyMetrics ?? null);
        setError(null);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Could not load Autopilot status");
      }
    };
    fetchMetrics();
    const interval = setInterval(fetchMetrics, 3000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  const finished = metrics?.totalJobsFinished ?? 0;
  const measured = finished > 0;
  const avgJobTime = measured && metrics?.avgJobTimeSec ? `${metrics.avgJobTimeSec.toFixed(1)}` : "—";
  const throughput = measured && metrics?.throughputPerMin != null ? metrics.throughputPerMin.toFixed(1) : "—";
  const workers =
    metrics?.totalWorkers != null ? `${metrics.activeWorkers ?? 0}/${metrics.totalWorkers}` : "—";

  return (
    <div className="space-y-6 font-sans">
      <div className="p-6 rounded-2xl border border-teal-500/20 bg-gradient-to-br from-[#0a1820] via-[#0d1f2d] to-[#07131b] backdrop-blur-2xl shadow-xl flex flex-wrap justify-between items-center gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <IconActivity className="w-5 h-5 text-teal-400" />
            <span>Autopilot Throughput</span>
          </h2>
          <p className="text-xs text-slate-300 mt-1">
            Measured timings for the current batch. Values stay blank until a job finishes.
          </p>
        </div>
        {error ? (
          <span role="alert" className="px-3.5 py-1 text-xs font-bold rounded-full bg-rose-500/15 border border-rose-500/30 text-rose-300">
            {error}
          </span>
        ) : null}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Kpi label="Throughput" value={throughput} unit="jobs/min" note="Finished jobs per minute since the batch started" tone="text-teal-300" />
        <Kpi label="Average Job Time" value={avgJobTime} unit="sec" note="Page open to confirmation, averaged over finished jobs" tone="text-cyan-300" />
        <Kpi label="Workers" value={workers} unit="busy" note="Browser workers running now, out of the configured slots" tone="text-indigo-300" />
        <Kpi label="Jobs Finished" value={metrics ? String(finished) : "—"} unit="this batch" note="Submitted, held for review or failed" tone="text-emerald-300" />
      </div>
    </div>
  );
}

function Kpi({ label, value, unit, note, tone }: { label: string; value: string; unit: string; note: string; tone: string }) {
  return (
    <div className="p-4 rounded-xl border border-white/10 bg-[#060a10] space-y-1">
      <span className="text-[10px] uppercase font-bold text-slate-400">{label}</span>
      <div className={`text-2xl font-black font-mono ${tone}`}>
        {value} <span className="text-xs text-slate-500">{unit}</span>
      </div>
      <p className="text-[11px] text-slate-400">{note}</p>
    </div>
  );
}
