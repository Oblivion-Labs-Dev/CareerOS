"use client";

import Link from "next/link";
import { dashboardHref, discoverHref } from "@/lib/career-workspace";
import { useCareerWorkspace } from "@/hooks/use-career-workspace";

type CareerWorkspaceStripProps = {
  active: "dashboard" | "discover" | "profile";
};

export function CareerWorkspaceStrip({ active }: CareerWorkspaceStripProps) {
  const { snapshot, prefs, loading, targetLabel } = useCareerWorkspace();

  const total = snapshot?.discoverTotal ?? 0;
  const strong = snapshot?.discoverStrongMatches ?? 0;
  const apps = snapshot?.applicationsCount ?? 0;
  const completeness = snapshot?.profileCompleteness ?? 0;

  return (
    <section className="career-workspace-strip" aria-label="Connected pages">
      <div className="career-workspace-strip-inner">
        <Link
          href={dashboardHref(prefs)}
          className={`career-workspace-chip${active === "dashboard" ? " career-workspace-chip--active" : ""}`}
          aria-current={active === "dashboard" ? "page" : undefined}
        >
          <span className="career-workspace-chip-label">Dashboard</span>
          <strong>{loading ? "…" : `${apps} applications`}</strong>
        </Link>
        <Link
          href={discoverHref(prefs)}
          className={`career-workspace-chip${active === "discover" ? " career-workspace-chip--active" : ""}`}
          aria-current={active === "discover" ? "page" : undefined}
        >
          <span className="career-workspace-chip-label">Job Scraper</span>
          <strong>{loading ? "…" : `${total.toLocaleString()} roles · ${strong} strong`}</strong>
        </Link>
        <Link
          href="/profile"
          className={`career-workspace-chip${active === "profile" ? " career-workspace-chip--active" : ""}`}
          aria-current={active === "profile" ? "page" : undefined}
        >
          <span className="career-workspace-chip-label">Profile</span>
          <strong>{loading ? "…" : `${completeness}% · ${targetLabel}`}</strong>
        </Link>
      </div>
      {!loading && completeness < 70 ? (
        <p className="career-workspace-hint muted">
          Profile is {completeness}% complete — scoring uses your title, skills, and location.{" "}
          <Link href="/profile">Finish profile</Link> then{" "}
          <Link href={discoverHref(prefs)}>rescore jobs</Link>.
        </p>
      ) : null}
    </section>
  );
}
