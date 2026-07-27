"use client";

import { BackendIcon } from "@/components/backend-icon";
import { BACKEND_BANNER_OFFLINE, BACKEND_START_COMMAND } from "@/lib/nav-config";
import { getClientApiBaseUrl } from "@/lib/api";
import { useBackendStatus } from "@/hooks/use-backend-status";

export function BackendOfflineAlert() {
  const online = useBackendStatus();

  if (online !== false) {
    return null;
  }

  const apiUrl = getClientApiBaseUrl();

  return (
    <div className="backend-offline-alert" role="alert" aria-live="assertive">
      <div className="backend-offline-alert-icon" aria-hidden>
        <BackendIcon className="backend-offline-alert-svg" />
      </div>
      <div className="backend-offline-alert-body">
        <strong>Backend offline — CareerOS API is not running</strong>
        <p>
          {BACKEND_BANNER_OFFLINE} Expected at <code>{apiUrl}</code>.
        </p>
        <pre className="backend-offline-alert-command">
          <code>{BACKEND_START_COMMAND}</code>
        </pre>
      </div>
      <span className="backend-offline-alert-pill">Offline</span>
    </div>
  );
}
