"use client";

import { useBackendStatus } from "@/hooks/use-backend-status";

type BackendStatusDotProps = {
  className?: string;
};

export function BackendStatusDot({ className }: BackendStatusDotProps) {
  const online = useBackendStatus();
  const state = online === true ? "online" : online === false ? "offline" : "checking";
  const label =
    online === true
      ? "Backend connected"
      : online === false
        ? "Backend offline — start the API server"
        : "Checking backend…";

  return (
    <span
      className={`backend-status-dot backend-status-dot--${state}${className ? ` ${className}` : ""}`}
      role="status"
      aria-label={label}
      title={label}
    />
  );
}
