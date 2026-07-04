"use client";

import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="shell" style={{ placeItems: "center", minHeight: "100vh" }}>
      <main className="main" style={{ maxWidth: 520 }}>
        <article className="workflow-panel">
          <span className="toc-card-kicker">Something went wrong</span>
          <h1 style={{ marginTop: 8 }}>CareerOS hit an error</h1>
          <p className="muted">Try again. If the problem persists, restart the API and web dev servers.</p>
          <button type="button" className="btn btn-primary" onClick={() => reset()} style={{ marginTop: 16 }}>
            Retry
          </button>
        </article>
      </main>
    </div>
  );
}
