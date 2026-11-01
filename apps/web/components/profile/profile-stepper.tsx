"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { UserProfile } from "@career-os/core";
import {
  DETAIL_GROUP_KEYS,
  EDUCATION_ROWS,
  ProfileApplicationDetailsForm,
} from "@/components/profile/profile-application-details-form";
import { ProfileDocumentsSection } from "@/components/profile/profile-documents-section";
import { ProfileExperienceCorpus } from "@/components/profile/profile-experience-corpus";
import { ProfileExperienceSection } from "@/components/profile/profile-experience-section";
import { ResumeProfileSwitcher } from "@/components/profile/resume-profile-switcher";
import { ResumeTailoringPanel } from "@/components/profile/resume-tailoring-panel";
import { PROFILE_KEY_LABELS } from "@/lib/profile-form-options";
import type { ResumeProfile } from "@/lib/resume-profiles-api";
import styles from "./profile-stepper.module.css";

type Profile = Partial<UserProfile> & Record<string, unknown>;

type Step = {
  id: string;
  title: string;
  blurb: string;
  /** Detail-form groups this step edits; empty when the step is not a form. */
  groups: string[];
  /** Old in-page anchors that should land on this step. */
  anchors?: string[];
};

const STEPS: Step[] = [
  {
    id: "resume",
    title: "Resume",
    blurb: "Upload your default resume. It feeds matching, autofill and tailoring.",
    groups: [],
    anchors: ["documents", "resume"],
  },
  {
    id: "contact",
    title: "Contact & links",
    blurb: "Where you live and where recruiters can find your work.",
    groups: ["Mailing address", "Compensation & links"],
    anchors: ["application-details"],
  },
  {
    id: "eligibility",
    title: "Work eligibility",
    blurb: "Citizenship, availability and languages. Forms ask these on almost every application.",
    groups: ["Citizenship & work eligibility", "Availability & relocation", "Languages"],
  },
  {
    id: "education",
    title: "Education",
    blurb: "Most recent degree first, plus GPA when a form asks for it.",
    groups: [EDUCATION_ROWS, "Education"],
  },
  {
    id: "experience",
    title: "Experience",
    blurb: "Your roles and the stories behind them. Tailoring only writes from what is here.",
    groups: [],
    anchors: ["experience", "corpus"],
  },
  {
    id: "screening",
    title: "Screening & voluntary",
    blurb: "Standard screening questions and optional self-identification answers.",
    groups: ["Screening answers"],
  },
  {
    id: "tailoring",
    title: "Tailoring & review",
    blurb: "How far tailoring may go, and the answers Autopilot has learned from you.",
    groups: [],
    anchors: ["tailoring"],
  },
];

function filled(value: unknown): boolean {
  if (Array.isArray(value)) return value.length > 0;
  return typeof value === "string" ? value.trim().length > 0 : value != null && value !== false;
}

/** Answered / total for form steps; null for steps whose completeness we can't measure. */
function stepProgress(step: Step, profile: Profile): { done: number; total: number } | null {
  if (step.id === "experience") {
    const n = Array.isArray(profile.workExperience) ? profile.workExperience.length : 0;
    return { done: n > 0 ? 1 : 0, total: 1 };
  }
  const keys = step.groups.flatMap((group) => (group === EDUCATION_ROWS ? [] : DETAIL_GROUP_KEYS[group] ?? []));
  if (step.groups.includes(EDUCATION_ROWS)) keys.unshift("education");
  if (!keys.length) return null;
  return { done: keys.filter((key) => filled(profile[key])).length, total: keys.length };
}

function stepForHighlight(keys: string[]): string | null {
  for (const step of STEPS) {
    const stepKeys = step.groups.flatMap((group) => DETAIL_GROUP_KEYS[group] ?? []);
    if (keys.some((key) => stepKeys.includes(key))) return step.id;
  }
  return null;
}

export function ProfileStepper({ profile, onSaved }: { profile: Profile; onSaved: () => void }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const highlight = useMemo(
    () => (searchParams.get("highlight") || "").split(",").map((k) => k.trim()).filter(Boolean),
    [searchParams],
  );

  const requested = searchParams.get("step");
  const initial = useMemo(() => {
    if (requested && STEPS.some((s) => s.id === requested)) return requested;
    const fromHighlight = stepForHighlight(highlight);
    if (fromHighlight) return fromHighlight;
    const hash = typeof window !== "undefined" ? window.location.hash.replace("#", "") : "";
    return STEPS.find((s) => s.anchors?.includes(hash))?.id ?? STEPS[0].id;
  }, [requested, highlight]);

  const [active, setActive] = useState(initial);
  useEffect(() => setActive(initial), [initial]);

  const [activeResumeProfile, setActiveResumeProfile] = useState<ResumeProfile | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [moving, setMoving] = useState(false);
  const saveRef = useRef<(() => Promise<boolean>) | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const index = STEPS.findIndex((s) => s.id === active);
  const step = STEPS[index] ?? STEPS[0];

  const progress = useMemo(() => STEPS.map((s) => stepProgress(s, profile)), [profile]);
  const measured = progress.filter((p): p is { done: number; total: number } => p != null);
  const answered = measured.reduce((sum, p) => sum + p.done, 0);
  const total = measured.reduce((sum, p) => sum + p.total, 0);
  const percent = total ? Math.round((answered / total) * 100) : null;

  const goTo = useCallback(
    async (id: string) => {
      if (id === active) return;
      setSaveError(null);
      // Autosave the step being left. A failed save keeps the user here, loudly.
      if (saveRef.current) {
        setMoving(true);
        const ok = await saveRef.current().catch(() => false);
        setMoving(false);
        if (!ok) {
          setSaveError("Couldn't save this step. Fix the issue above or try again before moving on.");
          return;
        }
      }
      saveRef.current = null;
      setActive(id);
      const params = new URLSearchParams(searchParams.toString());
      params.set("step", id);
      router.replace(`${pathname}?${params.toString()}`, { scroll: false });
      panelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    },
    [active, pathname, router, searchParams],
  );

  let body: ReactNode;
  if (step.id === "resume") {
    body = (
      <>
        <ProfileDocumentsSection onProfileSynced={onSaved} />
        <div className={styles.subsection}>
          <h3>Resume versions</h3>
          <p className="muted">
            Keep a named resume per target. The default one feeds matching and autofill.
          </p>
          <ResumeProfileSwitcher activeProfileId={activeResumeProfile?.id ?? null} onSelect={setActiveResumeProfile} />
        </div>
      </>
    );
  } else if (step.id === "experience") {
    body = (
      <>
        <ProfileExperienceSection profile={profile} onSaved={onSaved} />
        <div className={styles.subsection}>
          <h3>Experience corpus</h3>
          <p className="muted">Each story with the skills it evidences and the numbers you can cite.</p>
          <ProfileExperienceCorpus />
        </div>
      </>
    );
  } else if (step.id === "tailoring") {
    const answers = Array.isArray(profile.screeningAnswers) ? profile.screeningAnswers : [];
    body = (
      <>
        <ResumeTailoringPanel profileId={activeResumeProfile?.id ?? null} />
        <div className={styles.subsection}>
          <h3>{answers.length ? `${answers.length} learned answers` : "No learned answers yet"}</h3>
          <p className="muted">Answers Autopilot saved after you reviewed an application.</p>
          {answers.length ? (
            <ul className={styles.answers}>
              {answers.map((item, i) => (
                <li key={item.id || i}>
                  <span>{item.question || "Untitled question"}</span>
                  <strong>{item.answer || "Not set"}</strong>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      </>
    );
  } else {
    body = (
      <ProfileApplicationDetailsForm
        key={step.id}
        profile={profile}
        onSaved={onSaved}
        only={step.groups}
        bare
        saveRef={saveRef}
      />
    );
  }

  const next = STEPS[index + 1];
  const prev = STEPS[index - 1];

  return (
    <div className={styles.shell}>
      <nav className={styles.rail} aria-label="Profile sections">
        <div className={styles.overall}>
          <span className={styles.overallLabel}>Answered</span>
          <strong className={styles.overallValue}>{percent == null ? "—" : `${percent}%`}</strong>
          <div
            className={styles.meter}
            role="progressbar"
            aria-label="Profile questions answered"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent ?? undefined}
          >
            <span style={{ width: `${percent ?? 0}%` }} />
          </div>
          <span className={styles.overallHint}>
            {total ? `${answered} of ${total} questions Autopilot reads` : "Loading…"}
          </span>
        </div>
        <ol className={styles.steps}>
          {STEPS.map((s, i) => {
            const p = progress[i];
            const complete = p != null && p.done === p.total;
            return (
              <li key={s.id}>
                <button
                  type="button"
                  className={styles.stepButton}
                  data-active={s.id === active || undefined}
                  data-complete={complete || undefined}
                  aria-current={s.id === active ? "step" : undefined}
                  disabled={moving}
                  onClick={() => void goTo(s.id)}
                >
                  <span className={styles.stepIndex} aria-hidden="true">
                    {complete ? "✓" : i + 1}
                  </span>
                  <span className={styles.stepText}>
                    <span className={styles.stepTitle}>{s.title}</span>
                    {p && s.id !== "experience" ? (
                      <span className={styles.stepMeta}>
                        {p.done}/{p.total} answered
                      </span>
                    ) : null}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      </nav>

      <section className={styles.panel} ref={panelRef} aria-labelledby="profile-step-title">
        <header className={styles.panelHeader}>
          <span className={styles.kicker}>
            Step {index + 1} of {STEPS.length}
          </span>
          <h2 id="profile-step-title">{step.title}</h2>
          <p className="muted">{step.blurb}</p>
          {highlight.length ? (
            <p className={styles.highlight}>
              An application asked for: {highlight.map((k) => PROFILE_KEY_LABELS[k] || k).join(", ")}.
            </p>
          ) : null}
        </header>

        <div className={styles.body} key={step.id}>
          {body}
        </div>

        <footer className={styles.footer}>
          {saveError ? (
            <p className={styles.error} role="alert">
              {saveError}
            </p>
          ) : null}
          <div className={styles.footerActions}>
            {prev ? (
              <button type="button" className="btn-secondary" disabled={moving} onClick={() => void goTo(prev.id)}>
                ← {prev.title}
              </button>
            ) : (
              <span />
            )}
            {next ? (
              <button type="button" className="btn-primary" disabled={moving} onClick={() => void goTo(next.id)}>
                {moving ? "Saving…" : `Save & continue to ${next.title} →`}
              </button>
            ) : null}
          </div>
        </footer>
      </section>
    </div>
  );
}
