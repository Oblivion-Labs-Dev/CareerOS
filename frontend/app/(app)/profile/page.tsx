"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { CareerWorkspaceStrip } from "@/components/career-workspace-strip";
import { ProfileApplicationDetailsForm } from "@/components/profile/profile-application-details-form";
import { ProfileExperienceCorpus } from "@/components/profile/profile-experience-corpus";
import { ProfileExperienceSection } from "@/components/profile/profile-experience-section";
import { ProfileDocumentsSection } from "@/components/profile/profile-documents-section";
import { ResumeProfileSwitcher } from "@/components/profile/resume-profile-switcher";
import { ResumeTailoringPanel } from "@/components/profile/resume-tailoring-panel";
import { ResumeScannerDashboard } from "@/components/resume-scanner/resume-scanner-dashboard";
import { WorkflowPage } from "@/components/scaffold-page";
import { useCareerWorkspace } from "@/hooks/use-career-workspace";
import { getClientApiBaseUrl } from "@/lib/api";
import { dashboardHref, discoverHref } from "@/lib/career-workspace";
import { fetchCachedJson, getCachedStale, invalidateCached } from "@/lib/client-fetch-cache";
import { PROFILE_KEY_LABELS } from "@/lib/profile-form-options";
import type { ResumeProfile } from "@/lib/resume-profiles-api";
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
    group: "Mailing address",
    fields: [
      { label: "Street address", key: "streetAddress" as keyof ApplyPilotProfile },
      { label: "City", key: "city" as keyof ApplyPilotProfile },
      { label: "State", key: "state" as keyof ApplyPilotProfile },
      { label: "ZIP / postcode", key: "zip" as keyof ApplyPilotProfile },
      { label: "Country", key: "country" as keyof ApplyPilotProfile },
    ],
  },
  {
    group: "Availability & education",
    fields: [
      { label: "Notice period", key: "noticePeriod" as keyof ApplyPilotProfile },
      { label: "Willing to relocate", key: "relocate" as keyof ApplyPilotProfile },
      { label: "School", key: "school" as keyof ApplyPilotProfile },
      { label: "Degree", key: "degree" as keyof ApplyPilotProfile },
      { label: "Field of study", key: "discipline" as keyof ApplyPilotProfile },
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
  {
    group: "Demographics (EEO)",
    fields: [
      { label: "Gender identity", key: "gender" },
      { label: "Transgender", key: "transgender" },
      { label: "Race / ethnicity", key: "raceEthnicity" },
      { label: "Sexual orientation", key: "sexualOrientation" },
      { label: "Pronouns", key: "pronouns" },
    ],
  },
];

function valueFor(profile: ApplyPilotProfile, key: keyof ApplyPilotProfile) {
  const value = profile[key];
  if (Array.isArray(value)) return `${value.length} saved`;
  if (typeof value === "string" && value.trim()) return value;
  return "Not set";
}

function ProfileDataGrid({ profile }: { profile: ApplyPilotProfile }) {
  const searchParams = useSearchParams();
  const highlightKeys = new Set(
    (searchParams.get("highlight") || "")
      .split(",")
      .map((k) => k.trim())
      .filter(Boolean),
  );

  return (
    <section className="profile-data-grid" aria-label="Saved ApplyPilot profile">
      {highlightKeys.size > 0 && (
        <p className="muted aa-profile-highlight-note">
          Highlighted fields were requested from an application:{" "}
          {[...highlightKeys].map((k) => PROFILE_KEY_LABELS[k] || k).join(", ")}.
        </p>
      )}
      {PROFILE_FIELDS.map((section) => (
        <article className="workflow-panel profile-data-card" key={section.group}>
          <span className="toc-card-kicker">{section.group}</span>
          <div className="profile-field-list">
            {section.fields.map((field) => (
              <div
                className={`profile-field-row${highlightKeys.has(String(field.key)) ? " profile-field-row--highlight" : ""}`}
                key={field.key}
              >
                <span>{field.label}</span>
                <strong>{valueFor(profile, field.key)}</strong>
              </div>
            ))}
          </div>
        </article>
      ))}
    </section>
  );
}

export default function ProfilePage() {
  const { snapshot, prefs, targetLabel } = useCareerWorkspace();
  const [activeResumeProfile, setActiveResumeProfile] = useState<ResumeProfile | null>(null);
  const profileUrl = `${getClientApiBaseUrl()}/profile`;
  const cached = getCachedStale<{ profile: ApplyPilotProfile | null }>(profileUrl);
  const [profile, setProfile] = useState<ApplyPilotProfile>(() => cached?.profile ?? {});
  const [loading, setLoading] = useState(() => !cached);

  const reloadProfile = useCallback(() => {
    invalidateCached(profileUrl);
    void fetchCachedJson<{ profile: ApplyPilotProfile | null }>(profileUrl)
      .then((data) => setProfile(data.profile ?? {}))
      .catch(() => setProfile({}));
  }, [profileUrl]);

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

  useEffect(() => {
    const hash = typeof window !== "undefined" ? window.location.hash.replace("#", "") : "";
    if (!hash) return;
    const target = document.getElementById(hash);
    if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [loading]);
  const screeningAnswers = profile.screeningAnswers || [];
  const workExperience = profile.workExperience || [];
  const rawJson = JSON.stringify(profile, null, 2);

  return (
    <>
      <WorkflowPage
        title="Profile"
        eyebrow="Tell your story"
        subtitle="Your experience, in your own words. Keep your resume, skills, and application details ready for the right opportunity."
        primaryAction={{ href: discoverHref(prefs), label: "View matched jobs" }}
        secondaryAction={{ href: "#documents", label: "Upload resume" }}
        outcomes={[
          "Upload your default resume and sync contact fields into your profile.",
          "Set target role, skills, and location so Job Scraper can score matches.",
          "Scan your resume with Qwen to extract accomplishments and check job fit.",
        ]}
        focusAreas={[
          {
            title: "Resume & documents",
            description: "Upload a default resume for matching, autofill, and Qwen-powered scan.",
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

        {loading ? (
          <p className="muted dashboard-empty" role="status">
            Loading profile…
          </p>
        ) : (
          <>
            <Suspense fallback={<p className="muted dashboard-empty">Loading profile fields…</p>}>
              <ProfileDataGrid profile={profile} />
            </Suspense>

            <section className="workflow-panel dashboard-panel--wide" aria-label="Resume profiles">
              <div className="dashboard-panel-header">
                <div>
                  <span className="toc-card-kicker">Resume profiles</span>
                  <h2>Switch between tailored versions</h2>
                  <p className="muted" style={{ marginTop: "0.35rem" }}>
                    Keep a named resume per target (e.g. &ldquo;Default&rdquo;, &ldquo;Fintech&rdquo;) — one is marked default and feeds job matching and autofill.
                  </p>
                </div>
              </div>
              <ResumeProfileSwitcher activeProfileId={activeResumeProfile?.id ?? null} onSelect={setActiveResumeProfile} />
            </section>

            <ProfileApplicationDetailsForm profile={profile} onSaved={reloadProfile} />

            <ProfileDocumentsSection onProfileSynced={reloadProfile} />

            <ResumeTailoringPanel profileId={activeResumeProfile?.id ?? null} />

            <section className="workflow-panel dashboard-panel--wide profile-resume-scanner-section" id="resume" aria-label="Resume scanner">
              <div className="dashboard-panel-header">
                <div>
                  <span className="toc-card-kicker">Resume intelligence</span>
                  <h2>Scan, match, and improve</h2>
                  <p className="muted" style={{ marginTop: "0.35rem" }}>
                    Qwen extracts skills and accomplishments from your resume, analyzes job fit, and builds your knowledge graph.
                  </p>
                </div>
              </div>
              <ResumeScannerDashboard
                embedded
                profileName={String(profile.fullName || profile.firstName || "").trim()}
              />
            </section>

            <section className="workflow-panel dashboard-panel--wide" id="corpus" aria-label="Experience corpus">
              <div className="dashboard-panel-header">
                <div>
                  <span className="toc-card-kicker">Experience corpus</span>
                  <h2>Everything you have written down</h2>
                  <p className="muted" style={{ marginTop: "0.35rem" }}>
                    Your full body of work — each story with the skills and infrastructure it actually evidences,
                    the numbers you can cite, and the claims it will not support. One story at a time.
                  </p>
                </div>
              </div>
              <ProfileExperienceCorpus />
            </section>

            <section className="dashboard-layout dashboard-layout--full">
              <ProfileExperienceSection profile={profile} onSaved={reloadProfile} />
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
