"use client";

import React from "react";
import styles from "./diagnostic.module.css";
import type { DiagnosticService } from "@/lib/diagnostic-api";

interface SystemHealthCardProps {
  services: DiagnosticService[];
  overallStatus: "Healthy" | "Degraded" | "Down";
  updatedAt: string;
  onRefresh?: () => void;
  loading?: boolean;
}

export function SystemHealthCard({
  services: rawServices,
  overallStatus,
  updatedAt,
  onRefresh,
  loading = false,
}: SystemHealthCardProps) {
  const services = rawServices;
  const healthyCount = services.filter((s) => s.status === "Healthy").length;

  return (
    <section className={styles.sectionCard} aria-label="System Health">
      <div className={styles.cardHeader}>
        <div className={styles.headerLeft}>
          <h2 className={styles.cardTitle}>System Health</h2>
          <span className={styles.healthSummaryBadge} data-status={services.length ? overallStatus.toLowerCase() : "unknown"}>
            <span className={styles.pulseDot} />
            {services.length ? `${overallStatus} (${healthyCount}/${services.length} services operational)` : loading ? "Checking services…" : "Health data unavailable"}
          </span>
        </div>
        <div className={styles.headerRight}>
          <span className={styles.updatedAtTime}>
            {/* `updatedAt` only ever has a real value once the client's own
             * fetch has resolved - falling back to `new Date()` during render
             * (the previous behavior) evaluates once on the server and again
             * moments later at client hydration, producing two different
             * timestamps and a React hydration-mismatch error on every load. */}
            {updatedAt ? `Updated ${new Date(updatedAt).toLocaleTimeString()}` : "Not yet updated"}
          </span>
          {onRefresh && (
            <button
              type="button"
              onClick={onRefresh}
              disabled={loading}
              className={styles.refreshButton}
              aria-label="Refresh system health"
            >
              ↻
            </button>
          )}
        </div>
      </div>

      <div className={styles.serviceGrid}>
        {services.map((svc) => (
          <div key={svc.id} className={styles.serviceCard} data-service-id={svc.id} data-status={svc.status.toLowerCase()}>
            <div className={styles.serviceTop}>
              <span className={styles.serviceName}>{svc.name}</span>
              <span className={styles.serviceBadge} data-status={svc.status.toLowerCase()}>
                <span className={styles.serviceStatusDot} />
                {svc.status}
              </span>
            </div>
            <p className={styles.serviceDetail}>{svc.details}</p>
            <div className={styles.serviceFoot}>
              <span className={styles.serviceCategory}>{svc.category}</span>
              {svc.latencyMs > 0 && (
                <span className={styles.serviceLatency}>{svc.latencyMs.toFixed(1)}ms</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
