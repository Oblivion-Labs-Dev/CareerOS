import Link from "next/link";

export default function NotFound() {
  return (
    <div className="shell" style={{ placeItems: "center", minHeight: "100vh" }}>
      <main className="main" style={{ maxWidth: 520 }}>
        <article className="workflow-panel">
          <span className="toc-card-kicker">404</span>
          <h1 style={{ marginTop: 8 }}>Page not found</h1>
          <p className="muted">That route does not exist in CareerOS yet.</p>
          <Link href="/" className="btn btn-primary" style={{ marginTop: 16, display: "inline-flex" }}>
            Back to home
          </Link>
        </article>
      </main>
    </div>
  );
}
