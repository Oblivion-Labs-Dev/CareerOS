"use client";

import { RouteError } from "@/components/ui/feedback";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="shell" style={{ placeItems: "center", minHeight: "100vh" }}>
      <main className="main" style={{ maxWidth: 520 }}>
        <RouteError area="CareerOS" error={error} reset={reset} />
      </main>
    </div>
  );
}
