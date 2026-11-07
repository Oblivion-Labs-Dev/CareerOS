"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { CareerWorkspaceStrip } from "@/components/career-workspace-strip";
import { ProfileStepper } from "@/components/profile/profile-stepper";
import { OnboardingWizardModal } from "@/components/profile/onboarding-wizard-modal";
import { WorkflowPage } from "@/components/scaffold-page";
import { useCareerWorkspace } from "@/hooks/use-career-workspace";
import { getClientApiBaseUrl } from "@/lib/api";
import { discoverHref } from "@/lib/career-workspace";
import { fetchCachedJson, getCachedStale, invalidateCached } from "@/lib/client-fetch-cache";
import type { UserProfile } from "@career-os/core";
type ApplyPilotProfile = Partial<UserProfile>;

export default function ProfilePage() {
  const { snapshot, prefs } = useCareerWorkspace();
  const [onboardingOpen, setOnboardingOpen] = useState(false);
  const profileUrl = `${getClientApiBaseUrl()}/profile`;
  const cached = getCachedStale<{ profile: ApplyPilotProfile | null }>(profileUrl);
  const [profile, setProfile] = useState<ApplyPilotProfile>(() => cached?.profile ?? {});
  const [loading, setLoading] = useState(() => !cached);
  const [loadError, setLoadError] = useState<string | null>(null);

  const reloadProfile = useCallback(() => {
    invalidateCached(profileUrl);
    void fetchCachedJson<{ profile: ApplyPilotProfile | null }>(profileUrl)
      .then((data) => setProfile(data.profile ?? {}))
      .catch((err) => {
        console.warn("[profile] reload failed", err);
        setLoadError("Could not reload your profile. Values shown may be out of date.");
      });
  }, [profileUrl]);

  useEffect(() => {
    let cancelled = false;
    void fetchCachedJson<{ profile: ApplyPilotProfile | null }>(profileUrl)
      .then((data) => {
        if (!cancelled) setProfile(data.profile ?? {});
      })
      .catch((err) => {
        console.warn("[profile] load failed", err);
        if (!cancelled) setLoadError("Could not load your profile. Check that the API is running, then refresh.");
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

  useEffect(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      if (params.get("onboard") === "1") {
        setOnboardingOpen(true);
      }
    }
  }, []);

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
          "Keep application answers complete so Autopilot never has to guess.",
        ]}
        focusAreas={[
          {
            title: "Resume & documents",
            description: "Upload a default resume for matching and autofill.",
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

        {loadError ? (
          <p className="workflow-panel" role="alert" style={{ color: "var(--risk, #d9655a)" }}>
            {loadError}
          </p>
        ) : null}

        <section className="workflow-panel" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "1rem", flexWrap: "wrap", border: "1px solid var(--accent, #38bdf8)" }}>
          <div style={{ maxWidth: "700px" }}>
            <span className="toc-card-kicker">Autopilot Readiness Setup</span>
            <h2 style={{ fontSize: "1.1rem", margin: "0.2rem 0" }}>Candidate Onboarding Questionnaire</h2>
            <p className="muted" style={{ margin: 0, fontSize: "0.875rem" }}>
              Configure work authorization, sponsorship requirements, target compensation, and standard ATS screening answers in one place to enable 100% automated applications.
            </p>
          </div>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => setOnboardingOpen(true)}
          >
            Launch Setup Wizard →
          </button>
        </section>

        {loading ? (
          <p className="muted dashboard-empty" role="status">
            Loading profile…
          </p>
        ) : (
          <Suspense fallback={<p className="muted dashboard-empty">Loading profile…</p>}>
            <ProfileStepper profile={profile as ApplyPilotProfile & Record<string, unknown>} onSaved={reloadProfile} />
          </Suspense>
        )}
      </WorkflowPage>

      <OnboardingWizardModal
        open={onboardingOpen}
        onClose={() => setOnboardingOpen(false)}
        onSaved={reloadProfile}
      />
    </>
  );
}
