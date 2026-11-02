"use client";

import { RouteError } from "@/components/ui/feedback";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <RouteError
      area="Job Search Portals"
      error={error}
      reset={reset}
      fallback={{ href: "/dashboard", label: "Back to Dashboard" }}
    />
  );
}
