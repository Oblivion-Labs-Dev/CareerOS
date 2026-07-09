import { WorkflowPage } from "@/components/scaffold-page";
import { BackendRequiredBanner } from "@/components/backend-required-banner";
import { fetchJson } from "@/lib/api";
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

export default async function ProfilePage() {
  const data = await fetchJson<{ profile: ApplyPilotProfile | null }>("/profile").catch(() => ({ profile: null }));
  const profile: ApplyPilotProfile = data.profile ?? {};
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
      subtitle="The saved ApplyPilot profile JSON used to answer forms, screeners, and repeated application questions."
      primaryAction={{ href: "/apply-pilot", label: "Use with ApplyPilot" }}
      secondaryAction={{ href: "/resumes", label: "Review documents" }}
      outcomes={[
        "Confirm the exact profile data ApplyPilot can use before submitting applications.",
        "Keep contact, work authorization, links, and preferences in one reusable place.",
        "Review the screening answer bank that powers repeated ATS questions.",
      ]}
      focusAreas={[
        {
          title: "Saved profile",
          description: "Loaded from the Python backend via /profile and included in the /api/db JSON snapshot.",
        },
        {
          title: "ApplyPilot defaults",
          description: "Work authorization, sponsorship, voluntary IDs, and consent answers used during autofill.",
        },
        {
          title: "Answer bank",
          description: "Reusable question/answer pairs with match patterns for common application prompts.",
        },
      ]}
    >
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
    </WorkflowPage>
    </>
  );
}
