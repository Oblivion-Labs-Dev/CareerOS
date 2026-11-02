"use client";

import React, { useState } from "react";
import styles from "./diagnostic.module.css";
import type { SystemAlarmItem } from "@/lib/diagnostic-api";
import { acknowledgeSystemAlarm } from "@/lib/diagnostic-api";

interface AlarmsPanelProps {
  alarms: SystemAlarmItem[];
  onAlarmsChanged?: () => void;
  loading?: boolean;
}

export function AlarmsPanel({ alarms, onAlarmsChanged, loading = false }: AlarmsPanelProps) {
  const [busyId, setBusyId] = useState<string | null>(null);

  const handleAck = async (alarmId: string) => {
    setBusyId(alarmId);
    try {
      await acknowledgeSystemAlarm(alarmId);
      if (onAlarmsChanged) onAlarmsChanged();
    } catch {
      // transient failure
    } finally {
      setBusyId(null);
    }
  };

  return (
    <section className={styles.sectionCard} aria-label="System Alarms">
      <div className={styles.cardHeader}>
        <div className={styles.headerLeft}>
          <h2 className={styles.cardTitle}>System Alarms</h2>
          <span className={styles.subtext}>
            Operational alarm triggers with debounced thresholds and acknowledgement workflow
          </span>
        </div>
        <span className={styles.alarmCountBadge} data-count={alarms.length}>
          {alarms.length} {alarms.length === 1 ? "Alarm" : "Alarms"} Active
        </span>
      </div>

      <div className={styles.alarmsList}>
        {alarms.length === 0 ? (
          <div className={styles.noAlarmsBanner}>
            <span className={styles.checkGlyph}>✓</span>
            <div>
              <strong>All system monitors normal</strong>
              <p>No systemic alarms firing across inference, automation workers, or API gateways.</p>
            </div>
          </div>
        ) : (
          alarms.map((alarm) => (
            <div
              key={alarm.id}
              className={styles.alarmItem}
              data-severity={alarm.severity}
              data-status={alarm.currentStatus}
            >
              <div className={styles.alarmTop}>
                <div className={styles.alarmTitleRow}>
                  <span className={styles.alarmSeverityTag} data-severity={alarm.severity}>
                    {alarm.severity}
                  </span>
                  <strong className={styles.alarmName}>{alarm.alarm}</strong>
                  <span className={styles.affectedServiceTag}>
                    Service: {alarm.affectedService}
                  </span>
                </div>
                <div className={styles.alarmActionRow}>
                  {alarm.currentStatus === "acknowledged" ? (
                    <span className={styles.acknowledgedBadge}>✓ Acknowledged</span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => handleAck(alarm.id)}
                      disabled={busyId === alarm.id}
                      className={styles.ackButton}
                    >
                      {busyId === alarm.id ? "Acknowledging…" : "Acknowledge"}
                    </button>
                  )}
                </div>
              </div>

              <p className={styles.alarmThreshold}>
                <strong>Threshold:</strong> {alarm.threshold}
              </p>
              <p className={styles.alarmDetail}>{alarm.detail}</p>

              <div className={styles.alarmFoot}>
                <span>First seen: {new Date(alarm.firstSeen).toLocaleTimeString()}</span>
                <span className={styles.metaDot}>·</span>
                <span>Last seen: {new Date(alarm.lastSeen).toLocaleTimeString()}</span>
                <span className={styles.metaDot}>·</span>
                <span>Status: <strong>{alarm.currentStatus}</strong></span>
              </div>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
