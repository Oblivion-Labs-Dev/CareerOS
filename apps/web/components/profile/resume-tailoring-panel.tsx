"use client";

import { useCallback, useEffect, useState } from "react";
import {
  approveResumeTailoring,
  fetchAtsScore,
  fetchTailoringMode,
  setTailoringMode as saveTailoringMode,
  tailorResumeForJob,
  type AtsScore,
  type TailoredBullet,
  type TailoringMode,
  type TailoringResult,
} from "@/lib/resume-profiles-api";

type Props = {
  profileId: string | null;
};

const MODE_COPY: Record<TailoringMode, { label: string; description: string }> = {
  off: {
    label: "Off",
    description: "No change. Resume bullets go out exactly as written.",
  },
  honest: {
    label: "Honest",
    description: "Only rewriting or reorganizing to match with the job description as best as possible.",
  },
  aggressive: {
    label: "Aggressive",
    description: "Inflate and optimize the resume to match the job description and maximize callback calls.",
  },
};

function ScoreRing({ score }: { score: number }) {
  const color = score >= 80 ? "#34d399" : score >= 50 ? "#f59e0b" : "#f43f5e";
  const circumference = 2 * Math.PI * 26;
  const offset = circumference * (1 - score / 100);
  return (
    <svg width="64" height="64" viewBox="0 0 64 64" aria-hidden>
      <circle cx="32" cy="32" r="26" fill="none" stroke="var(--border)" strokeWidth="6" />
      <circle
        cx="32"
        cy="32"
        r="26"
        fill="none"
        stroke={color}
        strokeWidth="6"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        strokeLinecap="round"
        transform="rotate(-90 32 32)"
      />
      <text x="32" y="37" textAnchor="middle" fontSize="18" fontWeight="700" fill="var(--text)">
        {score}
      </text>
    </svg>
  );
}

function AtsScorePanel({ profileId }: { profileId: string | null }) {
  const [score, setScore] = useState<AtsScore | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    fetchAtsScore(profileId ?? undefined)
      .then((result) => {
        if (!cancelled) setScore(result);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Could not load ATS score");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [profileId]);

  if (loading) return <p className="muted dashboard-empty">Scoring resume…</p>;
  if (error) return <p className="muted dashboard-empty">{error}</p>;
  if (!score) return null;

  return (
    <div style={{ display: "flex", gap: "1.25rem", alignItems: "flex-start", flexWrap: "wrap" }}>
      <ScoreRing score={score.score} />
      <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: "0.5rem", flex: 1, minWidth: "16rem" }}>
        {score.checklist.map((item) => (
          <li key={item.label} style={{ display: "flex", gap: "0.5rem", alignItems: "flex-start" }}>
            <span
              aria-hidden
              style={{
                marginTop: "0.15rem",
                display: "inline-block",
                width: "0.9rem",
                height: "0.9rem",
                flexShrink: 0,
                borderRadius: "50%",
                background: item.passed ? "rgba(52,211,153,0.18)" : "rgba(244,63,94,0.18)",
                border: `1px solid ${item.passed ? "#34d399" : "#f43f5e"}`,
              }}
            />
            <span>
              <strong style={{ color: item.passed ? "#34d399" : "#f43f5e" }}>{item.label}</strong>
              <br />
              <span className="muted" style={{ fontSize: "var(--cos-text-sm)" }}>
                {item.detail}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function TailoringModeDial({ mode, onChange }: { mode: TailoringMode; onChange: (mode: TailoringMode) => void }) {
  return (
    <div>
      <div style={{ display: "inline-flex", borderRadius: "var(--radius-full)", border: "1px solid var(--border)", overflow: "hidden" }}>
        {(Object.keys(MODE_COPY) as TailoringMode[]).map((key) => {
          const active = key === mode;
          return (
            <button
              key={key}
              type="button"
              onClick={() => onChange(key)}
              style={{
                padding: "0.5rem 1.1rem",
                fontSize: "var(--cos-text-sm)",
                fontWeight: active ? 650 : 500,
                border: "none",
                cursor: "pointer",
                background: active ? "var(--accent)" : "transparent",
                color: active ? "#04211c" : "var(--text-secondary)",
              }}
            >
              {MODE_COPY[key].label}
            </button>
          );
        })}
      </div>
      <p className="muted" style={{ marginTop: "0.5rem", fontSize: "var(--cos-text-sm)", maxWidth: "38rem" }}>
        {MODE_COPY[mode].description}
      </p>
    </div>
  );
}

function BulletDiffRow({ bullet }: { bullet: TailoredBullet }) {
  return (
    <div
      style={{
        padding: "0.75rem 0.9rem",
        borderRadius: "var(--radius-sm)",
        border: "1px solid var(--border)",
        background: "var(--card)",
        display: "grid",
        gap: "0.4rem",
      }}
    >
      <span className="muted" style={{ fontSize: "var(--cos-text-xs)" }}>
        {[bullet.company, bullet.role, bullet.project].filter(Boolean).join(" · ") || "Accomplishment"}
      </span>
      {bullet.changed ? (
        <>
          <p style={{ margin: 0, textDecoration: "line-through", color: "var(--text-secondary)", opacity: 0.7 }}>{bullet.original}</p>
          <p style={{ margin: 0, color: "var(--accent)", background: "rgba(88,222,196,0.08)", borderRadius: "var(--radius-sm)", padding: "0.4rem 0.5rem" }}>
            {bullet.tailored}
          </p>
        </>
      ) : (
        <p style={{ margin: 0 }}>{bullet.tailored || bullet.original}</p>
      )}
    </div>
  );
}

function TailorForJob({ mode }: { mode: TailoringMode }) {
  const [company, setCompany] = useState("");
  const [role, setRole] = useState("");
  const [jd, setJd] = useState("");
  const [result, setResult] = useState<TailoringResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [approved, setApproved] = useState(false);
  const [error, setError] = useState("");

  const handleGenerate = async () => {
    setLoading(true);
    setError("");
    setApproved(false);
    try {
      const res = await tailorResumeForJob({
        targetCompany: company,
        targetRole: role,
        jobDescription: jd,
        mode,
      });
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not tailor resume");
    } finally {
      setLoading(false);
    }
  };

  const handleApprove = async () => {
    if (!result) return;
    await approveResumeTailoring({
      mode: result.mode,
      targetCompany: company,
      targetRole: role,
      bullets: result.bullets,
      skillsList: result.skillsList,
    });
    setApproved(true);
  };

  const changedCount = result?.bullets.filter((b) => b.changed).length ?? 0;

  return (
    <div style={{ display: "grid", gap: "0.75rem" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(10rem, 1fr))", gap: "0.6rem" }}>
        <input
          value={company}
          onChange={(e) => setCompany(e.target.value)}
          placeholder="Target company"
          style={inputStyle}
        />
        <input value={role} onChange={(e) => setRole(e.target.value)} placeholder="Target role" style={inputStyle} />
      </div>
      <textarea
        value={jd}
        onChange={(e) => setJd(e.target.value)}
        placeholder="Paste the job description…"
        rows={4}
        style={{ ...inputStyle, resize: "vertical", fontFamily: "inherit" }}
      />
      <div>
        <button type="button" className="btn btn-sm btn-primary" disabled={loading || !jd.trim()} onClick={() => void handleGenerate()}>
          {loading ? "Tailoring…" : mode === "off" ? "Preview (unchanged)" : "Generate tailored bullets"}
        </button>
      </div>

      {error ? <p style={{ color: "#f43f5e", fontSize: "var(--cos-text-sm)" }}>{error}</p> : null}

      {result ? (
        <div style={{ display: "grid", gap: "0.6rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.5rem" }}>
            <span className="muted" style={{ fontSize: "var(--cos-text-sm)" }}>
              {result.overallCritique || (changedCount ? `${changedCount} bullet(s) changed — review before approving.` : "Nothing changed.")}
            </span>
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <a
                href={`/resumes/Akshay_Borse_Resume_${mode.toUpperCase()}.pdf`}
                target="_blank"
                rel="noopener noreferrer"
                className="btn btn-sm"
                style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem", textDecoration: "none" }}
              >
                <span>📄</span>
                <span>View {mode.toUpperCase()} PDF</span>
              </a>
              {!approved ? (
                <button type="button" className="btn btn-sm btn-primary" onClick={() => void handleApprove()} disabled={!result.bullets.length}>
                  Approve & save
                </button>
              ) : (
                <span style={{ color: "#34d399", fontSize: "var(--cos-text-sm)", fontWeight: 650 }}>✓ Approved</span>
              )}
            </div>
          </div>
          <div style={{ display: "grid", gap: "0.5rem" }}>
            {result.bullets.map((bullet) => (
              <BulletDiffRow key={bullet.id} bullet={bullet} />
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  padding: "0.55rem 0.7rem",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--border)",
  background: "var(--card)",
  color: "var(--text)",
  fontSize: "var(--cos-text-sm)",
  width: "100%",
};

export function ResumeTailoringPanel({ profileId }: Props) {
  const [mode, setMode] = useState<TailoringMode>("honest");
  const [loadingMode, setLoadingMode] = useState(true);

  const loadMode = useCallback(() => {
    setLoadingMode(true);
    fetchTailoringMode()
      .then(setMode)
      .finally(() => setLoadingMode(false));
  }, []);

  useEffect(() => {
    loadMode();
  }, [loadMode]);

  const handleModeChange = async (next: TailoringMode) => {
    setMode(next);
    await saveTailoringMode(next);
  };

  return (
    <section className="workflow-panel dashboard-panel--wide" aria-label="Resume tailoring">
      <div className="dashboard-panel-header">
        <div>
          <span className="toc-card-kicker">ATS readiness</span>
          <h2>How this resume reads to an ATS</h2>
        </div>
      </div>
      <AtsScorePanel profileId={profileId} />

      <div style={{ marginTop: "1.5rem", paddingTop: "1.25rem", borderTop: "1px solid var(--border)" }}>
        <span className="toc-card-kicker">Resume optimization</span>
        <h2 style={{ marginBottom: "0.5rem" }}>Tailoring mode</h2>
        {loadingMode ? <p className="muted dashboard-empty">Loading…</p> : <TailoringModeDial mode={mode} onChange={(m) => void handleModeChange(m)} />}
      </div>

      <div style={{ marginTop: "1.5rem", paddingTop: "1.25rem", borderTop: "1px solid var(--border)" }}>
        <span className="toc-card-kicker">Tailor for a job</span>
        <h2 style={{ marginBottom: "0.5rem" }}>Every change shown to you, never silently sent</h2>
        <p className="muted" style={{ marginTop: 0, marginBottom: "0.75rem", fontSize: "var(--cos-text-sm)" }}>
          Generates a diff against your saved accomplishments — original struck through, tailored version highlighted. Nothing is applied until you approve it.
        </p>
        {!loadingMode ? <TailorForJob mode={mode} /> : null}
      </div>
    </section>
  );
}
