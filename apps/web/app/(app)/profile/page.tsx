"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { CareerWorkspaceStrip } from "@/components/career-workspace-strip";
import { WorkflowPage } from "@/components/scaffold-page";
import { BackendRequiredBanner } from "@/components/backend-required-banner";
import { useCareerWorkspace } from "@/hooks/use-career-workspace";
import { getClientApiBaseUrl } from "@/lib/api";
import { dashboardHref, discoverHref } from "@/lib/career-workspace";
import { fetchCachedJson, getCachedStale } from "@/lib/client-fetch-cache";
import type { UserProfile } from "@career-os/core";
type ApplyPilotProfile = Partial<UserProfile>;

const PROFILE_FIELDS: Array<{
  group: string;
  fields: Array<{ label: string; key: keyof ApplyPilotProfile }>;
}> = [
  {
    group: "Identity",
    fields: [
      { label: "Name", key: "fullName" },
      { label: "Email", key: "email" },
      { label: "Phone", key: "phone" },
      { label: "Location", key: "location" },
    ],
  },
  {
    group: "Links",
    fields: [
      { label: "LinkedIn", key: "linkedin" },
      { label: "GitHub", key: "github" },
      { label: "Portfolio", key: "portfolio" },
    ],
  },
  {
    group: "Work targets",
    fields: [
      { label: "Current title", key: "currentTitle" },
      { label: "Current company", key: "currentCompany" },
      { label: "Target role", key: "targetRole" },
      { label: "Experience", key: "yearsExperience" },
      { label: "Salary expectations", key: "salaryExpectations" },
    ],
  },
  {
    group: "Screening defaults",
    fields: [
      { label: "Work authorization", key: "workAuthorization" },
      { label: "Needs sponsorship", key: "sponsorship" },
      { label: "SMS consent", key: "smsConsent" },
      { label: "Veteran", key: "veteran" },
      { label: "Disability", key: "disability" },
    ],
  },
];

function valueFor(profile: ApplyPilotProfile, key: keyof ApplyPilotProfile) {
  const value = profile[key];
  if (Array.isArray(value)) return `${value.length} saved`;
  if (typeof value === "string" && value.trim()) return value;
  return "Not set";
}

export default function ProfilePage() {
  const { snapshot, prefs, targetLabel } = useCareerWorkspace();
  const profileUrl = `${getClientApiBaseUrl()}/profile`;  const cached = getCachedStale<{ profile: ApplyPilotProfile | null }>(profileUrl);
  const [profile, setProfile] = useState<ApplyPilotProfile>(() => cached?.profile ?? {});
  const [loading, setLoading] = useState(() => !cached);

  useEffect(() => {
    let cancelled = false;
    void fetchCachedJson<{ profile: ApplyPilotProfile | null }>(profileUrl)
      .then((data) => {
        if (!cancelled) setProfile(data.profile ?? {});
      })
      .catch(() => {
        if (!cancelled) setProfile({});
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [profileUrl]);
  const screeningAnswers = profile.screeningAnswers || [];
  const workExperience = profile.workExperience || [];
  const rawJson = JSON.stringify(profile, null, 2);

  return (
    <>
      <div className="page-content">
        <BackendRequiredBanner />
      </div>
      <WorkflowPage
        title="Profile"
        eyebrow="Foundation"
        subtitle="Your saved profile powers job relevancy scoring, dashboard matches, and application defaults."
        primaryAction={{ href: discoverHref(prefs), label: "View matched jobs" }}
        secondaryAction={{ href: dashboardHref(prefs), label: "Open dashboard" }}        outcomes={[
          "Set target role, skills, and location so Job Scraper can score matches.",
          "Keep contact and work authorization answers ready for applications.",
          "Review screening answers that repeat across ATS forms.",
        ]}
        focusAreas={[
          {
            title: "Scoring inputs",
            description: "Target role, current title, skills, and location feed the relevancy engine.",
          },
          {
            title: "Job Scraper link",
            description: `${snapshot?.discoverTotal?.toLocaleString() ?? "0"} roles indexed · rescore after profile changes.`,
          },
          {
            title: "Dashboard link",
            description: `${snapshot?.applicationsCount ?? 0} saved applications appear on your dashboard pipeline.`,
          },
        ]}
      >
        <CareerWorkspaceStrip active="profile" />

        {!loading && (snapshot?.profileCompleteness ?? 0) < 100 ? (
          <section className="workflow-panel profile-connected-panel" aria-label="Profile impact">
            <div className="dashboard-panel-header">
              <div>
                <span className="toc-card-kicker">Connected to Job Scraper</span>
                <h2>{targetLabel}</h2>
                <p className="muted" style={{ marginTop: "0.35rem" }}>
                  Profile is {snapshot?.profileCompleteness ?? 0}% complete. Add skills and target role for stronger matches,
                  then rescore from Job Scraper.
                </p>
              </div>
              <div className="target-jobs-actions">
                <Link href={discoverHref(prefs)} className="btn btn-sm btn-primary">
                  View matches
                </Link>
                <Link href={dashboardHref(prefs)} className="btn btn-sm">
                  Dashboard
                </Link>
              </div>
            </div>
          </section>
        ) : null}

        {loading ? (          <p className="muted dashboard-empty" role="status">
            Loading profile…
          </p>
        ) : (
          <>
            <section className="profile-data-grid" aria-label="Saved ApplyPilot profile">
              {PROFILE_FIELDS.map((section) => (
                <article className="workflow-panel profile-data-card" key={section.group}>
                  <span className="toc-card-kicker">{section.group}</span>
                  <div className="profile-field-list">
                    {section.fields.map((field) => (
                      <div className="profile-field-row" key={field.key}>
                        <span>{field.label}</span>
                        <strong>{valueFor(profile, field.key)}</strong>
                      </div>
                    ))}
                  </div>
                </article>
              ))}
            </section>

            <section className="dashboard-layout dashboard-layout--full">
              <article className="workflow-panel dashboard-panel--wide">
                <div className="dashboard-panel-header">
                  <div>
                    <span className="toc-card-kicker">Work experience</span>
                    <h2>{workExperience.length ? `${workExperience.length} roles saved` : "No work history saved yet"}</h2>
                  </div>
                </div>
                {workExperience.length ? (
                  <div className="dashboard-list">
                    {workExperience.map((entry, index) => (
                      <div className="profile-answer-row" key={`${entry.company}-${index}`}>
                        <div>
                          <h3>
                            {entry.jobTitle || "Role"} @ {entry.company || "Company"}
                          </h3>
                          <span>
                            {[entry.location, entry.startDate, entry.endDate || (entry.currentlyEmployed ? "Present" : "")]
                              .filter(Boolean)
                              .join(" · ")}
                          </span>
                        </div>
                        <strong>{entry.currentlyEmployed ? "Current" : "Past"}</strong>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="muted dashboard-empty">
                    Work experience from your ApplyPilot profile JSON will appear here after sync.
                  </p>
                )}
              </article>
            </section>

            <section className="dashboard-layout">
              <article className="workflow-panel dashboard-panel--wide">
                <div className="dashboard-panel-header">
                  <div>
                    <span className="toc-card-kicker">Screening answers</span>
                    <h2>{screeningAnswers.length ? `${screeningAnswers.length} saved answers` : "No answers saved yet"}</h2>
                  </div>
                </div>
                {screeningAnswers.length ? (
                  <div className="dashboard-list">
                    {screeningAnswers.map((item, index) => (
                      <div className="profile-answer-row" key={item.id || index}>
                        <div>
                          <h3>{item.question || "Untitled question"}</h3>
                          <span>{item.matchPatterns?.slice(0, 2).join(", ") || "No match pattern"}</span>
                        </div>
                        <strong>{item.answer || "Not set"}</strong>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="muted dashboard-empty">ApplyPilot learned answers will appear here after review.</p>
                )}
              </article>

              <article className="workflow-panel profile-json-card">
                <details className="profile-json-details">
                  <summary>
                    <span className="toc-card-kicker">ApplyPilot JSON</span>
                    <h2>Backend profile payload</h2>
                  </summary>
                  <pre>{rawJson}</pre>
                </details>
              </article>
            </section>
          </>
        )}
      </WorkflowPage>
    </>
  );
}
