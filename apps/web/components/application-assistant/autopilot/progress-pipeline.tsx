"use client";

import type { ComponentType } from "react";
import { IconCheck, IconSearch, IconSend, IconShieldCheck, IconStar } from "./icons";

interface ProgressPipelineProps {
  currentStep?: string;
  isRunning: boolean;
  isCompleted?: boolean;
}

const STEPS: { key: string; label: string; icon: ComponentType<{ className?: string }> }[] = [
  { key: "discover", label: "Discover", icon: IconSearch },
  { key: "score", label: "Score", icon: IconStar },
  { key: "apply", label: "Apply", icon: IconSend },
  { key: "verify", label: "Verify", icon: IconShieldCheck },
  { key: "complete", label: "Complete", icon: IconCheck },
];

function stepIndex(status?: string, isCompleted?: boolean) {
  if (isCompleted) return 4;
  const value = status?.toUpperCase() || "";
  if (value.includes("COMPLET")) return 4;
  if (value.includes("VERIF") || value.includes("SUBMIT")) return 3;
  if (value.includes("PAGE") || value.includes("FORM") || value.includes("APPLY")) return 2;
  if (value.includes("SCORE") || value.includes("RANK")) return 1;
  return 0;
}

export function ProgressPipeline({ currentStep, isRunning, isCompleted }: ProgressPipelineProps) {
  const activeIndex = stepIndex(currentStep, isCompleted);

  return (
    <div className="autopilot-pipeline">
      {STEPS.map((step, index) => {
        const StepIcon = step.icon;
        const active = (isRunning && index === activeIndex) || (isCompleted && index === 4);
        const complete = Boolean(isCompleted || (isRunning && index < activeIndex));
        return (
          <div className={`autopilot-pipeline-step${active ? " is-active" : ""}${complete ? " is-complete" : ""}`} key={step.key}>
            {index > 0 ? <span className="autopilot-pipeline-connector" /> : null}
            <span className="autopilot-pipeline-icon"><StepIcon /></span>
            <small>{step.label}</small>
          </div>
        );
      })}
    </div>
  );
}
