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
  aiModel?: string;
  lastRepairEvent?: {
    summary: string;
    timestamp: string;
    adapter?: string;
  } | null;
}

type HealthState = "healthy" | "recovering" | "offline";

export function SystemHealthPanel({
  connected = true,
  runnerStatus = "READY",
  repairCount = 0,
  aiModel = "mistral-small",
  lastRepairEvent,
}: SystemHealthPanelProps) {
  const [showDetails, setShowDetails] = useState(false);
  const isActuallyConnected = connected !== false;
  const runnerState: HealthState = !isActuallyConnected
    ? "offline"
    : runnerStatus === "RECOVERING"
      ? "recovering"
      : "healthy";
  const supportingState: HealthState = isActuallyConnected ? "healthy" : "offline";

  const aiName = aiModel.includes("mistral") || aiModel === "mistral-small"
    ? "AI Engine (Mistral 24B Local)"
    : aiModel.includes("gemini")
      ? "AI Engine (Gemini 2.5 Flash)"
      : aiModel.includes("gpt-oss")
        ? "AI Engine (gpt-oss:20b Local)"
        : aiModel.includes("gemma")
          ? "AI Engine (Gemma 3 12B)"
          : aiModel.includes("chatgpt") || aiModel.includes("gpt")
            ? (aiModel.includes("4o-mini") || aiModel === "chatgpt-mini" ? "AI Engine (ChatGPT 4o-mini)" : "AI Engine (ChatGPT 4o)")
            : "AI Engine (Mistral 24B Local)";

  const systems: { name: string; icon: ComponentType<{ className?: string }>; state: HealthState }[] = [
    { name: "Application Runner", icon: IconActivity, state: runnerState },
    { name: "Browser Engine", icon: IconGlobe, state: supportingState },
    { name: aiName, icon: IconCpu, state: supportingState },
    { name: "Repair Engine", icon: IconWrench, state: supportingState },
    { name: "Database", icon: IconDatabase, state: supportingState },
    { name: "ATS Adapters", icon: IconLayers, state: supportingState },
  ];

  return (
    <aside className="autopilot-system-health">
      <header>
        <span>System Health</span>
        <strong className={isActuallyConnected ? "is-healthy" : "is-offline"}>
          <IconShieldCheck /> {isActuallyConnected ? "All systems operational" : "Backend connection offline"}
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
