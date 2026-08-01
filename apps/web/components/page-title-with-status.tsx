"use client";

import { BackendStatusDot } from "@/components/backend-status-dot";

type PageTitleWithStatusProps = {
  children: React.ReactNode;
  className?: string;
  showBackendStatus?: boolean;
};

export function PageTitleWithStatus({
  children,
  className,
  showBackendStatus = true,
}: PageTitleWithStatusProps) {
  return (
    <h1 className={className ? `page-title-with-status ${className}` : "page-title-with-status"}>
      <span>{children}</span>
      {showBackendStatus ? <BackendStatusDot /> : null}
    </h1>
  );
}
