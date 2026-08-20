"use client";

import { useState, type ComponentType } from "react";
import {
  IconActivity,
  IconCpu,
  IconDatabase,
  IconGlobe,
  IconLayers,
  IconRefresh,
  IconShieldCheck,
  IconWrench,
} from "./icons";

interface SystemHealthPanelProps {
  connected?: boolean;
  runnerStatus?: string;
  repairCount?: number;
  lastRepairEvent?: {
    summary: string;
    timestamp: string;
    adapter?: string;
  } | null;
}

type HealthState = "healthy" | "recovering" | "offline";

export function SystemHealthPanel({
  connected = false,
  runnerStatus = "IDLE",
  repairCount = 0,
  lastRepairEvent,
}: SystemHealthPanelProps) {
  const [showDetails, setShowDetails] = useState(false);
  const runnerState: HealthState = !connected
    ? "offline"
    : runnerStatus === "RECOVERING"
      ? "recovering"
      : "healthy";
  const supportingState: HealthState = connected ? "healthy" : "offline";
  const systems: { name: string; icon: ComponentType<{ className?: string }>; state: HealthState }[] = [
    { name: "Application Runner", icon: IconActivity, state: runnerState },
    { name: "Browser Engine", icon: IconGlobe, state: supportingState },
    { name: "AI Assistant (Qwen)", icon: IconCpu, state: supportingState },
    { name: "Repair Engine", icon: IconWrench, state: supportingState },
    { name: "Database", icon: IconDatabase, state: supportingState },
    { name: "ATS Adapters", icon: IconLayers, state: supportingState },
  ];

  return (
    <aside className="autopilot-system-health">
      <header>
        <span>System Health</span>
        <strong className={connected ? "is-healthy" : "is-offline"}>
          <IconShieldCheck /> {connected ? "All systems operational" : "Backend connection offline"}
        </strong>
      </header>

      <div className="autopilot-system-list">
        {systems.map((system) => {
          const SystemIcon = system.icon;
          return (
            <div key={system.name}>
              <span><SystemIcon /> {system.name}</span>
              <small className={`is-${system.state}`}><i />{system.state}</small>
            </div>
          );
        })}
      </div>

      {lastRepairEvent ? (
        <div className="autopilot-repair-event">
          <strong><IconRefresh /> Autonomous recovery</strong>
          <span>{lastRepairEvent.summary}</span>
          <small>{lastRepairEvent.timestamp}</small>
        </div>
      ) : null}

      <button type="button" onClick={() => setShowDetails((value) => !value)}>
        {showDetails ? "Hide System Details" : "View System Details"}
      </button>

      {showDetails ? (
        <div className="autopilot-system-details">
          <span>Runner: <strong>{connected ? runnerStatus : "Unavailable"}</strong></span>
          <span>Repairs this run: <strong>{repairCount}</strong></span>
          <span>Submission guard: <strong>{connected ? "Configured" : "Unavailable"}</strong></span>
        </div>
      ) : null}
    </aside>
  );
}
