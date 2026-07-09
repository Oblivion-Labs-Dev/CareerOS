"use client";

import { Tooltip } from "@arsenal/ui";
import { BackendIcon } from "@/components/backend-icon";
import { BACKEND_NAV_TOOLTIP } from "@/lib/nav-config";

export function BackendNavTooltip({ online }: { online: boolean | null }) {
  const label =
    online === true
      ? "Backend connected"
      : online === false
        ? "Backend offline — start the API server"
        : BACKEND_NAV_TOOLTIP;

  return (
    <Tooltip content={label} label="Backend status" side="right">
      <span
        className={`nav-backend-badge inline-flex${online ? " nav-backend-badge--online" : ""}`}
        role="img"
        aria-label={label}
        onClick={(event) => event.preventDefault()}
      >
        <BackendIcon className="nav-backend-badge-icon" title="" />
      </span>
    </Tooltip>
  );
}
