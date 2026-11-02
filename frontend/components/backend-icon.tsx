import { BACKEND_NAV_TOOLTIP } from "@/lib/nav-config";

interface BackendIconProps {
  className?: string;
  title?: string;
}

export function BackendIcon({ className = "", title = BACKEND_NAV_TOOLTIP }: BackendIconProps) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      width="14"
      height="14"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={title ? undefined : true}
      role={title ? "img" : undefined}
    >
      {title ? <title>{title}</title> : null}
      <rect x="4" y="4" width="16" height="6" rx="1.5" />
      <rect x="4" y="14" width="16" height="6" rx="1.5" />
      <circle cx="8" cy="7" r="0.9" fill="currentColor" stroke="none" />
      <circle cx="8" cy="17" r="0.9" fill="currentColor" stroke="none" />
      <path d="M12 7h5M12 17h5" />
    </svg>
  );
}
