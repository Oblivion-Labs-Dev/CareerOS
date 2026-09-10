import Link from "next/link";

export default function AutoApplyPage() {
  return <section className="card" style={{ padding: "2rem" }}>
    <p className="muted">DISABLED PAGE</p>
    <h1>Auto Apply is disabled</h1>
    <p>Use Autopilot to manage and review your applications.</p>
    <Link href="/applications">Open Autopilot →</Link>
  </section>;
}
