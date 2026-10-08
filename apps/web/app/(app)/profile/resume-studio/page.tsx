"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchResumeVersions, interviewPrepHref, type ResumeVersionSummary } from "@/lib/career-resumes";
import studio from "./studio.module.css";
import { AddedRegions, JobDescriptionMarks, ThreadLayer, useMatchThreads } from "./aggressive-review";
import styles from "./compiler.module.css";

type Strength = "strong" | "moderate" | "weak";
type Match = { requirement_id: string; evidence_id: string; project_id: string; company: string; status: string; claim: string; strength: Strength; matched: string[] };
type Requirement = {
  id: string; section: string; original_text: string; normalized_requirement: string; skills: string[]; importance: "high" | "medium" | "low";
  evidence: Match[]; best_available: Strength | null; planned: Strength | null; resume_strength: Strength | null;
  bullets: { bullet_id: string; strength: Strength }[]; status: "missing" | "uncovered" | "partial" | "covered" | "planned";
};
type Trace = { requirements: Requirement[]; scores: { evidence: number; planned: number; resume: number | null; required_covered: number; required_total: number; method: string } };
type JD = { id: string; title: string; company: string; source: string; dropped: string[] } & Record<string, unknown>;
type CandidateEvidence = { evidence_id: string; type: string; status: string; claim: string };
type Candidate = { project_id: string; name: string; company: string; employment_id: string; reason: string; coverage: Record<string, Strength>; existence_only: boolean; evidence: CandidateEvidence[]; blocked: CandidateEvidence[] };
type Planned = { project_id: string; employment_id: string; reason: string; evidence_ids: string[]; requirement_ids: string[]; score: number; locked: boolean; pinned: boolean; lines: number };
type Plan = { target_role: string; jd_themes: string[]; selected_projects: Planned[]; section_budget: Record<string, number> };
type Call = { task: string; model: string; latency_ms: number; attempts: number; tokens: number | null };
type Query = { source: string; requirements: { requirement_id: string; terms: string[]; adjacent: string[] }[] };
type Analysis = { jd: JD; plan: Plan; trace: Trace; candidates: Candidate[]; warnings: string[]; ranking_source: string; deepseek: Call[]; query: Query; excluded_evidence: string[] };
type Bullet = { id: string; employment_id: string; project_id: string; text: string; evidence_ids: string[]; locked: boolean; name: string; requirements: { id: string; strength: Strength }[]; lint: Lint[] };
type Lint = { code: string; severity: "rewrite" | "flag"; message: string };
type Doc = { summary: Bullet | null; sections: { employment_id: string; bullets: Bullet[] }[]; featured: Bullet[] } & Record<string, unknown>;
type Row = {
  bullet_id: string; text: string; project: string; company: string; source: string; lines: number | null; line_budget: number;
  evidence: { id: string; type: string; status: string; claim: string }[]; lint: Lint[]; issues: { code: string; message: string }[];
  rejected?: { text: string; issues: string[] }[]; restyled_from?: string; style_score: number | null; style_source: string | null;
};
type Gap = { id: string; class: string; text: string; best_available: Strength | null };
type Evaluation = {
  factual_precision: number | null; metric_precision: number | null; technology_precision: number | null; traceability: number | null;
  conflict_leakage: number; claims: number; unsupported_claims: number; supported_jd_recall: number | null; top_requirement_coverage: number | null;
  evidence_utilization: number | null; supported_requirements: number; covered_requirements: number; supported_but_not_used: Gap[];
  no_supported_evidence: Gap[]; redundant_bullet_rate: number | null; page_compliance: number; template_fidelity: number; style_score: number | null;
  user_acceptance_rate: number | null; user_rejection_rate: number | null;
};
type Outcome = { outcome: string; note: string; at: string };
type Version = {
  resume_id: string; status: "draft" | "approved"; job_url: string; docx_sha256: string; pdf_sha256: string | null;
  pdf_checks: { passed?: boolean } & Record<string, unknown>; blocking: string[]; applications: { autopilot_job_id?: string }[]; outcomes?: Outcome[];
};
type Stage = { stage: string; latency_ms: number; deepseek_calls: number; tokens: number | null; retries: number; validation_failures?: number; rewrites?: number; iterations?: number };
type Output = {
  document: Doc; jd_id: string; trace: Trace; valid: boolean; preview: string; previews: string[]; pages: number;
  warnings: string[]; fit_log: string[]; debug: Row[]; deepseek: Call[]; evaluation: Evaluation; resume_version: Version | null; stages: Stage[];
  versions: { retrieval: string; query: string; prompts: Record<string, string>; model: string; template: string };
  layout: {
    engine: string; pages: number; fits: boolean; lines_used: number; capacity_lines: number; spare_lines: number; overflow_lines: number;
    template_drift: string[]; template: { file: string; sha256: string }; regions?: { page: number[]; bullets: Record<string, number[]> };
  };
};
type FeedbackAction = "accept" | "lock" | "reject" | "rewrite" | "swap_evidence" | "exclude";
type Focus = { kind: "req" | "bullet"; id: string } | null;

const SECTION_LABELS: Record<string, string> = {
  responsibilities: "Responsibilities", required_qualifications: "Required qualifications", preferred_qualifications: "Preferred qualifications",
  technologies: "Technologies", domain: "Domain", architecture: "Architecture and system design", leadership: "Leadership and ownership", ai_ml: "AI and ML",
};
const PAGE_SECTIONS: Record<string, string> = { skills: "Listed in the Skills section", education: "Shown in the Education section" };
const STATUS_TEXT: Record<Requirement["status"], string> = {
  covered: "Covered", partial: "Weakly covered", uncovered: "Evidence exists, no bullet", missing: "No evidence in career.json", planned: "Planned",
};

async function post<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`/api/backend/career/${path}`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${response.status}).`);
  return data as T;
}

function save(name: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a"); link.href = url; link.download = name; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const BUDGET_LABELS: [string, string][] = [["microsoft", "Microsoft"], ["amazon", "Amazon"], ["earlier", "Earlier roles"], ["projects", "Projects"]];
const REASONS: [string, string][] = [
  ["too_ai_sounding", "Too AI-sounding"], ["too_long", "Too long"], ["too_vague", "Too vague"], ["too_many_buzzwords", "Too many buzzwords"],
  ["wrong_emphasis", "Wrong emphasis"], ["repetitive", "Repetitive"], ["metric_unnecessary", "Metric unnecessary"], ["too_technical", "Too technical"],
  ["not_technical_enough", "Not technical enough"], ["prefer_other_project", "Prefer another project"], ["other", "Other"],
];
const OUTCOMES = ["recruiter_response", "screen", "technical_interview", "onsite", "offer", "rejected", "withdrawn"];
const PDF_CHECKS: [string, string][] = [["one_page", "one page"], ["selectable_text", "selectable text"], ["sections_present", "sections present"],
  ["no_clipping", "no clipping"], ["no_missing_content", "no missing content"], ["fonts_from_template", "template fonts"]];

const pct = (value: number | null | undefined) => (value === null || value === undefined ? "n/a" : `${Math.round(value * 100)}%`);

/** Downloads the stored, hash-checked artifact of one immutable resume version under its recruiter-facing name. */
async function download(resumeId: string, format: "docx" | "pdf") {
  const response = await fetch(`/api/backend/career/resumes/${resumeId}/download?format=${format}`, { credentials: "include" });
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail ?? "Download failed.");
  const name = /filename="([^"]+)"/.exec(response.headers.get("Content-Disposition") ?? "")?.[1] ?? `Resume.${format}`;
  save(name, await response.blob());
}

/** One saved version's next steps: review → approve → apply (posting, manual record or Autopilot) → interview prep. */
function SavedVersions({ versions, jobId, busy, run, onChanged }: {
  versions: ResumeVersionSummary[]; jobId: string; busy: string;
  run: <T>(kind: string, task: () => Promise<T>) => Promise<T | undefined>; onChanged: (message: string) => void;
}) {
  if (!versions.length) return null;
  return <div className={styles.saved}>
    <h3 className={styles.sub}>Saved versions for this job</h3>
    {versions.map((v) => {
      const applied = v.applications.find((a) => a.submitted_at) ?? v.applications[0];
      const id = v.resume_id;
      return <div key={id} className={styles.savedRow}>
        <span><b>{v.label}</b> · {applied ? `applied${applied.channel === "manual" ? "" : " via Autopilot"} ${(applied.submitted_at ?? "").slice(0, 10)}` : v.status === "approved" ? "approved" : v.blocking.length ? "draft, needs fixes" : "draft"} · {v.created_at.slice(0, 10)}</span>
        <div className={styles.actions}>
          <button type="button" disabled={!!busy || !!v.blocking.length} onClick={() => run(`pdf:${id}`, () => download(id, "pdf"))}>{busy === `pdf:${id}` ? "Downloading…" : "Download PDF"}</button>
          {v.status === "draft" ? <button type="button" disabled={!!busy || !!v.blocking.length}
            onClick={async () => { if (await run(`approve:${id}`, () => post(`resumes/${id}/approve`, { locks: [] }))) onChanged(`${v.label} approved and frozen.`); }}>Approve</button> : null}
          {v.status === "approved" && v.job_url ? <a className={styles.linkButton} href={v.job_url} target="_blank" rel="noopener noreferrer">Apply ↗</a> : null}
          {v.status === "approved" && !applied ? <>
            <button type="button" disabled={!!busy} title="Record that you submitted this exact PDF yourself"
              onClick={async () => { if (await run(`applied:${id}`, () => post(`resumes/${id}/applied`, { applicationUrl: v.job_url, jobId }))) onChanged(`Application recorded with ${v.label}.`); }}>Mark applied</button>
            <button type="button" className={styles.apply} disabled={!!busy || !v.job_url} title="Queues the application agent with this exact PDF. It never regenerates the resume."
              onClick={async () => { const r = await run(`autopilot:${id}`, () => post<{ message: string }>(`resumes/${id}/apply`, { applicationUrl: v.job_url, company: v.job_company, title: v.job_title }));
                if (r) onChanged(r.message); }}>Apply with Autopilot</button>
          </> : null}
          {applied ? <a className={styles.linkButton} href={interviewPrepHref(id)}>Interview prep</a> : null}
        </div>
      </div>;
    })}
  </div>;
}

function allBullets(doc: Doc | undefined): Bullet[] {
  if (!doc) return [];
  return [doc.summary, ...doc.sections.flatMap((s) => s.bullets), ...doc.featured].filter((b): b is Bullet => !!b);
}

function Metrics({ evaluation: e, onPick }: { evaluation: Evaluation; onPick: (id: string) => void }) {
  const cells: [string, string, boolean][] = [
    ["Factual precision", pct(e.factual_precision), e.factual_precision === null || e.factual_precision === 1],
    ["Metric precision", pct(e.metric_precision), e.metric_precision === null || e.metric_precision === 1],
    ["Technology precision", pct(e.technology_precision), e.technology_precision === null || e.technology_precision === 1],
    ["Traceability", pct(e.traceability), e.traceability === null || e.traceability === 1],
    ["Conflict leakage", String(e.conflict_leakage), e.conflict_leakage === 0],
    ["Supported JD coverage (weighted)", pct(e.supported_jd_recall), true],
    ["Top-requirement coverage", pct(e.top_requirement_coverage), true],
    ["Style score", e.style_score === null ? "n/a" : `${e.style_score}/100`, e.style_score === null || e.style_score >= 70],
    ["One page", e.page_compliance === 1 ? "yes" : "no", e.page_compliance === 1],
    ["Template fidelity", e.template_fidelity === 1 ? "exact" : "drift", e.template_fidelity === 1],
    ["Redundant bullets", pct(e.redundant_bullet_rate), !e.redundant_bullet_rate],
    ["Your acceptance", pct(e.user_acceptance_rate), true],
  ];
  const gaps = (title: string, list: Gap[], hint: string) => <div>
    <h4>{title} ({list.length})</h4>
    {list.length ? list.map((g) => <button key={g.id} type="button" className={styles.link} onClick={() => onPick(g.id)}><code>{g.id}</code> {g.text}</button>)
      : <p className={styles.muted}>{hint}</p>}
  </div>;
  return <div className={styles.metrics}>
    <h3 className={styles.sub}>Evaluation</h3>
    <div className={styles.metricGrid}>{cells.map(([label, value, ok]) => <div key={label} data-ok={ok}><strong>{value}</strong><span>{label}</span></div>)}</div>
    <p className={styles.muted}>{e.claims - e.unsupported_claims}/{e.claims} atomic claims supported. Coverage counts only the {e.supported_requirements} requirements career.json can support; {e.covered_requirements} are covered.</p>
    {gaps("Supported but not used", e.supported_but_not_used, "Every supportable requirement is on the page.")}
    {gaps("No supported evidence", e.no_supported_evidence, "career.json has evidence for every requirement.")}
  </div>;
}

const STRENGTH_PERCENT: Record<Strength, number> = { strong: 100, moderate: 60, weak: 25 };

function Icon({ kind }: { kind: "spark" | "download" | "arrow" | "page" }) {
  return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {kind === "spark" ? <><path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z"/><path d="m20 2 .5 1.5L22 4l-1.5.5L20 6l-.5-1.5L18 4l1.5-.5Z"/></> : kind === "download" ? <><path d="M12 3v12m-4-4 4 4 4-4M5 16v4h14v-4"/></> : kind === "arrow" ? <path d="M5 12h14m-5-5 5 5-5 5"/> : <><path d="M6 3h8l4 4v14H6Z"/><path d="M14 3v5h4M9 12h6m-6 4h6"/></>}
  </svg>;
}

export default function ResumeStudioPage() {
  const [source, setSource] = useState("");
  const [refresh, setRefresh] = useState(false);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [output, setOutput] = useState<Output | null>(null);
  const [focus, setFocus] = useState<Focus>(null);
  const [picking, setPicking] = useState<string[] | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [reason, setReason] = useState("");
  const [preferred, setPreferred] = useState("");
  const [applyUrl, setApplyUrl] = useState("");
  const [outcome, setOutcome] = useState(OUTCOMES[0]);
  const [jobId, setJobId] = useState("");
  const [saved, setSaved] = useState<ResumeVersionSummary[]>([]);
  const [analyzedInput, setAnalyzedInput] = useState("");
  const [editingPosting, setEditingPosting] = useState(false);
  const [activeLink, setActiveLink] = useState<string | null>(null);
  const [traceOpen, setTraceOpen] = useState(false);
  const workspaceRef = useRef<HTMLDivElement>(null);
  const isUrl = /^https?:\/\/\S+$/.test(source.trim());
  const inputKey = jobId ? `job:${jobId}` : source.trim();
  const trace = output?.trace ?? analysis?.trace;
  const bullets = allBullets(output?.document);
  const rows = new Map((output?.debug ?? []).map((r) => [r.bullet_id, r]));
  const candidates = new Map((analysis?.candidates ?? []).map((c) => [c.project_id, c]));
  const requirement = focus?.kind === "req" ? trace?.requirements.find((r) => r.id === focus.id) : undefined;
  const bullet = focus?.kind === "bullet" ? bullets.find((b) => b.id === focus.id) : undefined;
  const highlighted = new Set(requirement?.bullets.map((b) => b.bullet_id));
  const version = output?.resume_version ?? null;
  const shippable = !!output?.valid && !!version && !version.blocking.length;

  const run = useCallback(async <T,>(kind: string, task: () => Promise<T>) => {
    setBusy(kind); setError("");
    try { return await task(); } catch (cause) { setError(cause instanceof Error ? cause.message : "Something went wrong."); } finally { setBusy(""); }
  }, []);

  const loadSaved = useCallback(async (jdId: string) => setSaved(await fetchResumeVersions(jdId)), []);

  const accept = useCallback((data: Analysis) => {
    setAnalysis(data); setPlan(data.plan); setOutput(null); setFocus(null); setPicking(null); setNotice("");
    void loadSaved(data.jd.id);
  }, [loadSaved]);

  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("job") ?? "";
    if (!id) return;
    setJobId(id);
    void run("analyze", () => post<Analysis>("analyze", { jobId: id })).then((data) => { if (data) { accept(data); setAnalyzedInput(`job:${id}`); } });
  }, [run, accept]);

  /** One click: read the posting (when it changed), then write the resume. Matching is always aggressive: the plan
   *  targets every requirement career.json can support, and every line is rewritten for this posting. */
  async function tailor(event: React.FormEvent) {
    event.preventDefault();
    let current = analysis;
    if (!current || refresh || analyzedInput !== inputKey) {
      current = (await run("analyze", () => post<Analysis>("analyze", jobId ? { jobId, refresh } : { ...(isUrl ? { url: source.trim() } : { jobDescription: source }), refresh }))) ?? null;
      if (!current) return;
      accept(current); setAnalyzedInput(inputKey); setRefresh(false);
      await compile(current.plan, null, "generate", [], current);
      return;
    }
    if (plan) await compile(plan, null, "generate", output ? bullets : []);
  }

  async function compile(nextPlan: Plan, regenerate: string[] | null, kind = "generate", keep: Bullet[] = bullets, base: Analysis | null = analysis) {
    if (!base) return;
    const data = await run(kind, () => post<Output>("generate", { jd_id: base.jd.id, plan: nextPlan, bullets: keep, regenerate }));
    if (!data) return;
    const onPage = new Set(allBullets(data.document).map((b) => b.project_id));
    setOutput(data); setPicking(null); setEditingPosting(false); void loadSaved(base.jd.id);
    setPlan({ ...nextPlan, selected_projects: nextPlan.selected_projects.filter((p) => onPage.has(p.project_id)),
      section_budget: { ...nextPlan.section_budget, summary: data.document.summary ? nextPlan.section_budget.summary : 0 } });
  }

  /** Feedback is style and selection signal only: it is stored beside career.json and never changes it. */
  function sendFeedback(action: FeedbackAction, target: Bullet, extra: { replacement_evidence_ids?: string[] } = {}) {
    if (!analysis) return;
    const row = rows.get(target.id);
    const body = {
      action, reason: reason || null, replacement_text: preferred.trim(), jd_id: analysis.jd.id, jd_title: analysis.jd.title, jd_company: analysis.jd.company,
      requirement_ids: target.requirements.map((r) => r.id), resume_id: output?.resume_version?.resume_id ?? "", bullet_id: target.id,
      project_id: target.project_id, company: row?.company ?? "", bullet_text: target.text, evidence_ids: target.evidence_ids,
      prompt_version: output?.versions.prompts.write ?? "", model: output?.versions.model ?? "", retrieval_version: output?.versions.retrieval ?? "", ...extra,
    };
    setReason(""); setPreferred("");
    void post("feedback", body).catch((cause) => setError(cause instanceof Error ? `Feedback not saved: ${cause.message}` : "Feedback not saved."));
  }

  async function approveAndApply(apply: boolean) {
    const version = output?.resume_version;
    if (!version) return;
    const locks = bullets.filter((b) => b.locked).map((b) => b.id);
    if (!apply) {
      const data = await run("approve", () => post<Version>(`resumes/${version.resume_id}/approve`, { locks }));
      if (data && output) { setOutput({ ...output, resume_version: { ...version, ...data } }); setNotice(`Version approved and frozen. Download it or apply below.`); }
      if (data && analysis) void loadSaved(analysis.jd.id);
      return;
    }
    const data = await run("apply", () => post<{ version: Version; message: string }>(`resumes/${version.resume_id}/apply`, {
      applicationUrl: applyUrl.trim(), company: analysis?.jd.company ?? "", title: analysis?.jd.title ?? "", locks }));
    if (data && output) { setOutput({ ...output, resume_version: { ...version, ...data.version } }); setNotice(data.message); }
    if (data && analysis) void loadSaved(analysis.jd.id);
  }

  async function addOutcome() {
    const version = output?.resume_version;
    if (!version) return;
    const data = await run("outcome", () => post<{ outcomes: Outcome[] }>(`resumes/${version.resume_id}/outcomes`, { outcome }));
    if (data && output) setOutput({ ...output, resume_version: { ...version, outcomes: data.outcomes } });
  }

  function setLocked(id: string, locked: boolean) {
    if (!output) return;
    const flip = (b: Bullet) => (b.id === id ? { ...b, locked } : b);
    const doc = output.document;
    setOutput({ ...output, document: { ...doc, summary: doc.summary && flip(doc.summary), featured: doc.featured.map(flip),
      sections: doc.sections.map((s) => ({ ...s, bullets: s.bullets.map(flip) })) } });
  }

  function exclude(target: Bullet) {
    if (!plan) return;
    const next = target.id === "summary" ? { ...plan, section_budget: { ...plan.section_budget, summary: 0 } }
      : { ...plan, selected_projects: plan.selected_projects.filter((p) => p.project_id !== target.project_id) };
    setFocus(null);
    sendFeedback("exclude", target);
    void compile(next, [], "exclude", bullets.filter((b) => b.id !== target.id));
  }

  function swapEvidence(target: Bullet, ids: string[]) {
    if (!plan) return;
    sendFeedback("swap_evidence", target, { replacement_evidence_ids: ids });
    void compile({ ...plan, selected_projects: plan.selected_projects.map((p) => p.project_id === target.project_id ? { ...p, evidence_ids: ids, pinned: true } : p) },
      [target.id], "swap", bullets.map((b) => (b.id === target.id ? { ...b, locked: false } : b)));
  }

  function addProject(projectId: string) {
    const c = candidates.get(projectId);
    if (!plan || !c) return;
    setPlan({ ...plan, selected_projects: [...plan.selected_projects, { project_id: c.project_id, employment_id: c.employment_id, reason: c.reason,
      evidence_ids: c.evidence.slice(0, 3).map((e) => e.evidence_id), requirement_ids: Object.keys(c.coverage), score: 0, locked: false, pinned: false, lines: c.existence_only ? 1 : 2 }] });
  }

  const building = ["analyze", "generate", "rewrite", "swap"].includes(busy);
  const stale = Boolean(output && analyzedInput && analyzedInput !== inputKey);
  const showReview = Boolean(output && !building && !stale && !editingPosting);
  const jdText = typeof analysis?.jd.text === "string" ? analysis.jd.text : "";
  const markRequirements = (trace?.requirements ?? []).map((r) => ({ id: r.id, text: r.original_text }));
  const known = new Set(markRequirements.map((r) => r.id));
  const regions = output?.layout.regions;
  const overlay = bullets.map((b) => {
    const ranked = b.requirements.filter((r) => known.has(r.id)).sort((x, y) => STRENGTH_PERCENT[y.strength] - STRENGTH_PERCENT[x.strength]);
    const firm = ranked.filter((r) => r.strength !== "weak");
    const ids = (firm.length ? firm : ranked).slice(0, 2).map((r) => r.id);
    return { id: b.id, key: b.id, decision: "KEEP" as const, optimizedBullet: b.text, selectionReason: "", requirementIds: ids,
      requirementPercents: Object.fromEntries(b.requirements.map((r) => [r.id, STRENGTH_PERCENT[r.strength]])), slotRect: regions?.bullets[b.id] };
  }).filter((b) => b.requirementIds.length > 0);
  const threads = useMatchThreads(workspaceRef, showReview, overlay.map((b) => `${b.key}:${b.requirementIds.join("+")}`).join("|"));
  useEffect(() => {
    if (!showReview) return;
    const region = workspaceRef.current?.querySelector<HTMLElement>("[role=region]");
    const mark = region?.querySelector<HTMLElement>("mark[data-req]");
    if (region && mark) region.scrollTop += mark.getBoundingClientRect().top - region.getBoundingClientRect().top - 24;
  }, [showReview, output]);
  const preview = output ? (output.previews[0] ?? output.preview) : "";
  const pageRect = regions?.page.length === 4 ? regions.page : undefined;
  const pageW = pageRect ? pageRect[2] - pageRect[0] : 612;
  const pageH = pageRect ? pageRect[3] - pageRect[1] : 792;
  const sections = Object.keys(SECTION_LABELS).map((key) => [key, trace?.requirements.filter((r) => r.section === key) ?? []] as const).filter(([, list]) => list.length);
  const selected = new Set(plan?.selected_projects.map((p) => p.project_id));
  const scores = trace?.scores;

  return <div className={studio.studio}>
    <header className={studio.hero}>
      <div><div className={studio.eyebrow}><span/> YOUR EXPERIENCE, IN FOCUS</div>
        <h1>A new role.<br/><em>Your strongest story.</em></h1>
        <p>Turn a job description into a focused, one-page resume<br className={studio.desktopBreak}/> written from the evidence in your career record.</p>
      </div>
      <div className={studio.heroSeal}><Icon kind="page"/><strong>One page.<br/>All you.</strong><span>Original resume style</span></div>
    </header>

    <div className={studio.workspace} ref={workspaceRef}>
      <form className={studio.editor} onSubmit={tailor}>
        <div className={studio.panelTitle}><span className={studio.step}>01</span><div><h2>The opportunity</h2><p>{jobId ? "Prefilled from the job card." : "Paste the posting or its URL. We’ll find the right evidence."}</p></div></div>
        <fieldset className={studio.modes} style={{ gridTemplateColumns: "1fr" }}><legend>Tailoring mode</legend><label className={studio.modeSelected}><input type="radio" name="tailoring-mode" value="aggressive" checked readOnly/><strong>AGGRESSIVE · ALWAYS ON</strong><span>Every requirement your career record can support is targeted, and every line is rewritten for this posting.</span></label></fieldset>
        <p className={studio.modeNote}>Facts, skills and numbers still come only from your evidence. Every claim is validated before it reaches the page.</p>
        {jobId ? <div className={styles.jobHeader}>
          <b>{analysis ? `${analysis.jd.title || "Role"}${analysis.jd.company ? ` · ${analysis.jd.company}` : ""}` : busy === "analyze" ? "Loading the job…" : "Job from Discover"}</b>
          {typeof analysis?.jd.url === "string" && analysis.jd.url ? <a href={analysis.jd.url} target="_blank" rel="noopener noreferrer">Posting ↗</a> : null}
          <button type="button" className={styles.link} disabled={!!busy} onClick={() => { setJobId(""); setEditingPosting(true); window.history.replaceState(null, "", window.location.pathname); }}>Use a different job</button>
        </div> : null}
        <label className={studio.descriptionLabel} htmlFor="studio-jd">Job description <span>{jobId ? "From the posting" : "Required"}</span></label>
        {showReview && output ? <>
          <JobDescriptionMarks description={jdText} requirements={markRequirements} linkedIds={overlay.flatMap((b) => b.requirementIds)} active={activeLink}
            activeRequirementIds={overlay.find((b) => b.key === activeLink)?.requirementIds ?? []} onHover={setActiveLink}/>
          <div className={studio.textMeta}><span>Each line connects a resume point to the posting sentence it matches. The number is that match.</span>{jobId ? null : <button type="button" onClick={() => { setSource(source || jdText); setEditingPosting(true); }}>Edit posting</button>}</div>
        </> : jobId ? null : <>
          <textarea id="studio-jd" value={source} onChange={(e) => setSource(e.target.value)} placeholder={"Paste the full job description or a job URL…\n\nInclude responsibilities, qualifications, and the skills the team is looking for."} maxLength={40000} disabled={!!busy}/>
          <div className={studio.textMeta}><span>{source.length.toLocaleString()} / 40,000 characters</span>{source && !busy ? <button type="button" onClick={() => setSource("")}>Clear</button> : <span>Full posting works best</span>}</div>
        </>}
        <label className={styles.check}><input type="checkbox" checked={refresh} onChange={(e) => setRefresh(e.target.checked)}/> Re-read the posting’s requirements</label>
        <div className={studio.format}><Icon kind="page"/><div><strong>Your template · US Letter</strong><span>Original typography and layout preserved</span></div><b>1 PAGE</b></div>
        <button className={studio.generate} disabled={!!busy || (!jobId && !isUrl && source.trim().length < 40)} type="submit"><Icon kind="spark"/>{building ? "Building your resume…" : output ? "Regenerate resume" : "Generate resume"}<Icon kind="arrow"/></button>
        <p className={studio.localNote}><span/> Uses your career record · Every line traced to evidence</p>
        {error ? <div className={studio.error} role="alert">{error}</div> : null}
        <SavedVersions versions={saved} jobId={jobId} busy={busy} run={run} onChanged={(message) => { setNotice(message); setError(""); if (analysis) void loadSaved(analysis.jd.id); }}/>
        {notice && !output ? <p className={styles.notice}>{notice}</p> : null}
        <div className={studio.process}><h3>Made from your experience</h3><ol><li><b>Match</b><span>Map every posting requirement to evidence in your career record.</span></li><li><b>Write</b><span>Rewrite each line for this posting; validators reject any unsupported claim.</span></li><li><b>Fit</b><span>Retain your fonts, layout, and one-page format.</span></li></ol></div>
      </form>

      <section className={studio.preview} aria-label="Resume preview" aria-busy={building}>
        <div className={studio.previewToolbar}><div><span className={studio.step}>02</span><h2>Your resume</h2><span className={studio.pageBadge}>{output && !output.layout.fits ? `${output.layout.pages} pages` : "1 / 1"}</span>{showReview && scores?.resume != null ? <span className={studio.matchBadge}>{scores.resume}% match</span> : null}</div>
          <button className={studio.download} type="button" onClick={() => run("pdf", () => download(version!.resume_id, "pdf"))} disabled={!!busy || !shippable}><Icon kind="download"/>{busy === "pdf" ? "Downloading…" : "Download PDF"}</button></div>
        <div className={studio.previewStatus} role="status" aria-live="polite">{building ? "Building your resume. Match lines will connect each point to the posting." : stale ? "Posting changed. Regenerate to update your resume." : showReview && output ? `${scores?.resume == null ? "" : `${scores.resume}% match. `}${overlay.length} point${overlay.length === 1 ? "" : "s"} connected to the posting.${output.valid ? "" : " Validation issues below."}` : "Your one-page resume will appear here"}</div>
        <div className={`${studio.paperStage} ${building ? `${studio.working} ${studio.workingAggressive}` : ""}`}>
          {output && preview ? <div className={studio.paperFrame} style={{ aspectRatio: `${pageW} / ${pageH}` }}>
            <img className={studio.paper} style={{ aspectRatio: `${pageW} / ${pageH}` }} src={preview} alt="Generated one-page resume, identical to the downloadable PDF"/>
            {showReview ? <AddedRegions bullets={overlay} requirements={markRequirements} pageRect={pageRect} active={activeLink} onHover={setActiveLink}/> : null}
          </div> : <div className={studio.emptyPaper}>
            <div className={studio.mockName}/><div className={studio.mockContact}/><div className={studio.mockHeading}/>
            {Array.from({ length: 3 }, (_, section) => <div className={studio.mockSection} key={section}><i/>{Array.from({ length: 4 }, (_, line) => <span key={line}/>)}</div>)}
            <div className={studio.emptyPrompt}><div><Icon kind="spark"/></div><h3>Potential, on paper.</h3><p>Add a job description to see<br/>your experience take shape.</p></div>
          </div>}
        </div>
        {output ? <>
          {version ? <div className={styles.versionBar}>
          <span><code>{version.resume_id}</code> {version.status === "approved" ? "approved, frozen" : "draft"} · DOCX {version.docx_sha256.slice(0, 10)}{version.pdf_sha256 ? ` · PDF ${version.pdf_sha256.slice(0, 10)}` : " · no PDF"}</span>
          <span className={styles.checks}>{PDF_CHECKS.map(([key, label]) => <span key={key} data-ok={version.pdf_checks[key] === true}>{label}</span>)}</span>
          {version.blocking.length ? version.blocking.map((b) => <p key={b} className={styles.flag}>{b}</p>) : null}
          <div className={styles.actions}>
            <button type="button" disabled={!!busy || !shippable || version.status === "approved"} onClick={() => approveAndApply(false)}>{version.status === "approved" ? "Approved" : busy === "approve" ? "Approving…" : "Approve version"}</button>
            {!version.job_url ? <input className={styles.inline} value={applyUrl} onChange={(e) => setApplyUrl(e.target.value)} placeholder="Application URL" maxLength={2000}/> : null}
            <button className={styles.apply} type="button" disabled={!!busy || !shippable || (!version.job_url && !/^https?:\/\//.test(applyUrl.trim()))}
              title="Queues the application agent with this exact PDF. It never regenerates the resume." onClick={() => approveAndApply(true)}>{busy === "apply" ? "Queuing…" : "Apply With This Resume"}</button>
          </div>
          {version.applications.length ? <div className={styles.actions}>
            <select value={outcome} onChange={(e) => setOutcome(e.target.value)} aria-label="Outcome">{OUTCOMES.map((o) => <option key={o} value={o}>{o.replaceAll("_", " ")}</option>)}</select>
            <button type="button" disabled={!!busy} onClick={addOutcome}>Record outcome</button>
            {(version.outcomes ?? []).map((o) => <small key={o.at + o.outcome} className={styles.muted}>{o.outcome.replaceAll("_", " ")} · {o.at.slice(0, 10)}</small>)}
          </div> : null}
        </div> : <p className={styles.warning}>This draft was not stored as a version, so it cannot be downloaded or applied.</p>}
          {notice ? <p className={styles.notice}>{notice}</p> : null}
          {[...output.layout.template_drift, ...output.warnings, ...output.fit_log].map((w) => <p key={w} className={styles.warning}>{w}</p>)}
        </> : null}
        <div className={studio.previewFoot}><span>US LETTER · 8.5 × 11 IN</span><span>{output ? "Preview and PDF are identical" : "Centered header · Ruled sections · Compact bullets"}</span></div>
      </section>
      {showReview ? <ThreadLayer paths={threads} active={activeLink}/> : null}
    </div>

    {output && scores ? <section className={studio.evidence}>
      <div className={studio.coveragePanel}>
        <div><span className={studio.eyebrow}>EVIDENCE COVERAGE</span>
          <h2>{scores.resume ?? scores.planned}% of this posting is covered</h2>
          <p>{scores.required_covered} of {scores.required_total} required qualifications covered. The best your career record can support is {scores.evidence}%. Weighted requirement coverage, never an LLM estimate.</p></div>
        {output.evaluation.no_supported_evidence.length > 0 ? <div className={studio.gapList}>
          <span>Nothing in your recorded experience speaks to:</span>
          <div>{output.evaluation.no_supported_evidence.map((gap) => <b key={gap.id}>{gap.text}</b>)}</div>
        </div> : <p className={studio.reviewNote}>Every requirement this posting names has evidence behind it.</p>}
      </div>

      <div className={studio.evidenceHeader}><div className={studio.panelTitle}><span className={studio.step}>03</span><div><h2>Behind the resume</h2><p>Every line, the posting lines it answers, and the evidence it came from.</p></div></div><span>{bullets.length} SOURCE-BACKED LINES</span></div>
      <div className={studio.evidenceGrid}>{bullets.map((b, i) => {
        const row = rows.get(b.id);
        const answered = b.requirements.map((r) => ({ r, text: markRequirements.find((m) => m.id === r.id)?.text })).filter((x) => x.text);
        return <details key={b.id} className={studio.sourceCard} onMouseEnter={() => setActiveLink(b.id)} onMouseLeave={() => setActiveLink(null)}>
          <summary><span>{String(i + 1).padStart(2, "0")}</span><div><b>{b.id === "summary" ? "Summary" : row?.project ?? b.project_id}</b><small>{b.id === "summary" ? "Professional summary" : row?.company || "Personal project"}  ·  {b.locked ? "LOCKED" : "REWRITTEN"}</small></div><span>+</span></summary>
          <p>{b.text}</p>
          <h4>Matched to this posting</h4>
          {answered.length ? <ul>{answered.map(({ r, text }) => <li key={r.id}>{text} · {STRENGTH_PERCENT[r.strength]}%</li>)}</ul> : <p>Context line: it supports the story rather than a single requirement.</p>}
          <h4>Evidence</h4>
          <ul>{(row?.evidence ?? []).map((e) => <li key={e.id}>{e.claim}</li>)}</ul>
          <button type="button" className={styles.link} onClick={() => { setFocus({ kind: "bullet", id: b.id }); setTraceOpen(true); }}>Inspect, rewrite or swap evidence</button>
        </details>;
      })}</div>
    </section> : null}

    {analysis ? <details className={styles.fullTrace} open={traceOpen} onToggle={(e) => setTraceOpen((e.target as HTMLDetailsElement).open)}>
      <summary>Full trace and controls <span>requirements → evidence → bullets, feedback, rewrites and metrics</span></summary>
      <div className={styles.layout}>
        <section className={studio.editor}>
          {analysis && scores ? <div className={styles.analysis}>
          <div className={styles.scores} title={scores.method}>
            <div><strong>{scores.resume ?? scores.planned}%</strong><span>{scores.resume === null ? "planned coverage" : "resume coverage"}</span></div>
            <div><strong>{scores.evidence}%</strong><span>best possible from career.json</span></div>
            <div><strong>{scores.required_covered}/{scores.required_total}</strong><span>required covered</span></div>
          </div>
          <p className={styles.muted}>{analysis.jd.title || "Role"}{analysis.jd.company ? ` · ${analysis.jd.company}` : ""} · requirements by {analysis.jd.source}, ranking by {analysis.ranking_source}. Scores are weighted requirement coverage, never an LLM estimate.</p>
          {analysis.warnings.map((w) => <p key={w} className={styles.warning}>{w}</p>)}
          {sections.map(([key, list]) => <div key={key}>
            <h3>{SECTION_LABELS[key]}</h3>
            <ul className={styles.reqs}>{list.map((r) => <li key={r.id}><button type="button" data-active={focus?.kind === "req" && focus.id === r.id} onClick={() => setFocus({ kind: "req", id: r.id })}>
              <code>{r.id}</code><span className={styles.status} data-status={r.status}>{STATUS_TEXT[r.status]}</span><small>{r.importance}</small>
              <span className={styles.reqText}>{r.original_text}</span>
            </button></li>)}</ul>
          </div>)}
          {analysis.jd.dropped.length ? <details className={styles.dropped}><summary>{analysis.jd.dropped.length} extracted requirement(s) dropped because the text is not in the posting</summary>{analysis.jd.dropped.map((d) => <p key={d}>{d}</p>)}</details> : null}
        </div> : null}
        </section>
        {plan ? <section className={studio.editor}>
        <div className={studio.panelTitle}><span className={studio.step}>02</span><div><h2>Trace</h2><p>Requirement → evidence → project → bullet.</p></div></div>
        {requirement ? <div className={styles.inspector}>
          <div className={styles.inspectHead}><code>{requirement.id}</code><span className={styles.status} data-status={requirement.status}>{STATUS_TEXT[requirement.status]}</span><small>{SECTION_LABELS[requirement.section]} · {requirement.importance}</small></div>
          <blockquote>{requirement.original_text}</blockquote>
          <p className={styles.muted}><b>Interpreted as:</b> {requirement.normalized_requirement}{requirement.skills.length ? ` · ${requirement.skills.join(", ")}` : ""}</p>
          {(() => {
            const q = analysis?.query.requirements.find((x) => x.requirement_id === requirement.id);
            return q && (q.terms.length || q.adjacent.length) ? <p className={styles.muted}><b>Evidence query:</b> {q.terms.join(", ") || "none"}{q.adjacent.length ? ` · adjacent only (weak): ${q.adjacent.join(", ")}` : ""}</p> : null;
          })()}
          <p className={styles.muted}><b>Strength:</b> best in career.json {requirement.best_available ?? "none"} · planned {requirement.planned ?? "none"} · on resume {requirement.resume_strength ?? "none"}</p>
          <h4>Covered by</h4>
          {requirement.bullets.length ? requirement.bullets.map((c) => PAGE_SECTIONS[c.bullet_id]
            ? <p key={c.bullet_id} className={styles.link}><span data-strength={c.strength}>{c.strength}</span>{PAGE_SECTIONS[c.bullet_id]}</p>
            : <button key={c.bullet_id} type="button" className={styles.link} onClick={() => setFocus({ kind: "bullet", id: c.bullet_id })}>
              <span data-strength={c.strength}>{c.strength}</span>{bullets.find((b) => b.id === c.bullet_id)?.text ?? c.bullet_id}</button>)
            : <p className={styles.flag}>{requirement.status === "missing" ? "Missing: nothing in career.json supports this requirement." : output ? "Uncovered: evidence exists but no bullet on the page uses it." : "Not generated yet."}</p>}
          <h4>Matching evidence</h4>
          {requirement.evidence.length ? <ul className={styles.evidence}>{requirement.evidence.map((m) => <li key={m.evidence_id}>
            <span data-strength={m.strength}>{m.strength}</span><code>{m.evidence_id}</code><small>{candidates.get(m.project_id)?.name ?? m.project_id} · {m.company || "Personal project"} · {m.status}</small><p>{m.claim}</p>
          </li>)}</ul> : <p className={styles.muted}>None.</p>}
        </div> : null}

        {bullet ? <div className={styles.inspector}>
          {(() => {
            const row = rows.get(bullet.id);
            const c = candidates.get(bullet.project_id);
            const planned = plan.selected_projects.find((p) => p.project_id === bullet.project_id);
            return <>
              <div className={styles.inspectHead}><b>{row?.project ?? bullet.project_id}</b><small>{row?.company} · {row?.lines ?? "?"}/{row?.line_budget} lines · {bullet.locked ? "locked" : row?.source}</small></div>
              <p className={styles.bullet}>{bullet.text}</p>
              {row?.restyled_from ? <p className={styles.muted}><b>Before style pass:</b> {row.restyled_from}</p> : null}
              <h4>Targets</h4>
              <div className={styles.chips}>{bullet.requirements.length ? bullet.requirements.map((r) => <button key={r.id} type="button" data-strength={r.strength} onClick={() => setFocus({ kind: "req", id: r.id })}>{r.id} · {r.strength}</button>) : <span className={styles.muted}>No job requirement. Context bullet.</span>}</div>
              <h4>Evidence</h4>
              <ul className={styles.evidence}>{(row?.evidence ?? []).map((e) => <li key={e.id}><code>{e.id}</code><small>{e.type} · {e.status}</small><p>{e.claim}</p></li>)}</ul>
              <h4>Style{row?.style_score != null ? ` · ${row.style_score}/100 (${row.style_source === "critic" ? "DeepSeek critic" : "lint only"})` : ""}</h4>
              {bullet.lint.length ? bullet.lint.map((l) => <p key={l.code + l.message} className={l.severity === "rewrite" ? styles.flag : styles.muted}>{l.code.startsWith("critic:") ? <b>Critic: </b> : null}{l.message}</p>)
                : <p className={styles.muted}>No style issues.</p>}
              {row?.rejected?.length ? <><h4>Rejected drafts</h4>{row.rejected.map((r) => <p key={r.text} className={styles.muted}><s>{r.text}</s> ({r.issues.join(", ")})</p>)}</> : null}
              <h4>Feedback</h4>
              <div className={styles.actions}>
                <select value={reason} onChange={(e) => setReason(e.target.value)} aria-label="Feedback reason">
                  <option value="">Reason (optional)…</option>
                  {REASONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
                <input className={styles.inline} value={preferred} onChange={(e) => setPreferred(e.target.value)} maxLength={1200} placeholder="Wording you would prefer (style example only)"/>
              </div>
              <div className={styles.actions}>
                <button type="button" onClick={() => { if (!bullet.locked) sendFeedback("lock", bullet); setLocked(bullet.id, !bullet.locked); }}>{bullet.locked ? "Unlock" : "Keep / Lock"}</button>
                <button type="button" onClick={() => { sendFeedback("accept", bullet); setNotice("Marked as a good example."); }}>Accept</button>
                <button type="button" disabled={!reason} title={reason ? "" : "Pick a reason first"} onClick={() => { sendFeedback("reject", bullet); setNotice("Rejection saved. Rewrite or exclude to change the page."); }}>Reject</button>
                <button type="button" disabled={!!busy || bullet.locked} onClick={() => { sendFeedback("rewrite", bullet); void compile(plan, [bullet.id], "rewrite"); }}>{busy === "rewrite" ? "Rewriting…" : "Rewrite"}</button>
                {bullet.id !== "summary" && c ? <button type="button" disabled={!!busy} onClick={() => setPicking(picking ? null : (planned?.evidence_ids ?? bullet.evidence_ids))}>Swap evidence</button> : null}
                <button type="button" disabled={!!busy} onClick={() => exclude(bullet)}>Exclude</button>
              </div>
              {picking && c ? <div className={styles.picker}>
                {c.evidence.map((e) => <label key={e.evidence_id}><input type="checkbox" checked={picking.includes(e.evidence_id)}
                  onChange={(ev) => setPicking(ev.target.checked ? [...picking, e.evidence_id] : picking.filter((id) => id !== e.evidence_id))}/>
                  <span><code>{e.evidence_id}</code> <small>{e.status}</small><br/>{e.claim}</span></label>)}
                {c.blocked.map((e) => <label key={e.evidence_id} data-blocked="true"><input type="checkbox" disabled/><span><code>{e.evidence_id}</code> <small>{e.status}, cannot be used</small><br/>{e.claim}</span></label>)}
                <button className={studio.generate} type="button" disabled={!!busy || !picking.length} onClick={() => swapEvidence(bullet, picking)}>{busy === "swap" ? "Rewriting…" : `Rewrite from ${picking.length} evidence record${picking.length === 1 ? "" : "s"}`}</button>
              </div> : null}
            </>;
          })()}
        </div> : null}
        {!requirement && !bullet ? <p className={styles.muted}>Select a requirement on the left or a bullet below to inspect its trace.</p> : null}

        <h3 className={styles.sub}>{output ? "On the page" : "Plan"}</h3>
        <p className={styles.muted}>Section budget for this job: {BUDGET_LABELS.map(([key, label]) => `${label} ${plan.section_budget[key] ?? 0}`).join(" · ")}
          {plan.section_budget.capacity_lines ? ` · ${plan.section_budget.planned_lines}/${plan.section_budget.capacity_lines} template lines planned` : ""}</p>
        <ol className={styles.plan}>{plan.selected_projects.map((p) => {
          const c = candidates.get(p.project_id);
          const b = bullets.find((x) => x.project_id === p.project_id);
          return <li key={p.project_id} data-locked={b?.locked ? "true" : "false"} data-hit={b && highlighted.has(b.id) ? "true" : "false"}>
            <div className={styles.planHead}><b>{c?.name ?? p.project_id}</b><small>{c?.company}{c?.existence_only ? " · existence only" : ""}</small></div>
            {b ? <button type="button" className={styles.bulletButton} data-active={focus?.kind === "bullet" && focus.id === b.id} onClick={() => setFocus({ kind: "bullet", id: b.id })}>{b.text}</button> : <p className={styles.reason}>{p.reason}</p>}
            <div className={styles.chips}>{(b ? b.requirements.map((r) => r.id) : p.requirement_ids).map((id) => <span key={id}>{id}</span>)}{b?.lint.some((l) => l.severity === "rewrite") ? <span data-state="lint">style</span> : null}</div>
            {!output ? <div className={styles.actions}><button type="button" onClick={() => setPlan({ ...plan, selected_projects: plan.selected_projects.filter((x) => x.project_id !== p.project_id) })}>Remove</button></div> : null}
          </li>;
        })}</ol>
        {output?.document.summary ? <button type="button" className={styles.bulletButton} data-active={focus?.kind === "bullet" && focus.id === "summary"} onClick={() => setFocus({ kind: "bullet", id: "summary" })}><b>Summary:</b> {output.document.summary.text}</button> : null}
        <div className={styles.actions}>
          <select value="" onChange={(e) => addProject(e.target.value)} aria-label="Add project" disabled={!!busy}>
            <option value="">Add a project…</option>
            {(analysis?.candidates ?? []).filter((c) => !selected.has(c.project_id)).map((c) => <option key={c.project_id} value={c.project_id}>{c.name} ({c.company})</option>)}
          </select>
        </div>
        <button className={studio.generate} type="button" disabled={!!busy || !plan.selected_projects.length} onClick={() => compile(plan, null, "generate", output ? bullets : [])}>
          {busy === "generate" ? "Writing and validating…" : output ? "Regenerate unlocked bullets" : "Generate resume"}</button>
      </section> : null}
        {output ? <section className={studio.editor}>
          <Metrics evaluation={output.evaluation} onPick={(id) => setFocus({ kind: "req", id })}/>
        <p className={styles.footnote}>Rendered by {output.layout.engine} from {output.layout.template.file} ({output.layout.template.sha256.slice(0, 10)}), the same DOCX you download. {output.layout.lines_used}/{output.layout.capacity_lines} lines{output.layout.fits ? `, ${output.layout.spare_lines} spare` : `, ${output.layout.overflow_lines} over`}. Fonts, sizes, margins and spacing come only from the template.</p>
        <p className={styles.footnote}>Stages: {output.stages.map((s) => `${s.stage} ${s.latency_ms} ms${s.deepseek_calls ? `, ${s.deepseek_calls} call${s.deepseek_calls === 1 ? "" : "s"}${s.tokens ? `, ${s.tokens} tokens` : ""}` : ""}${s.retries ? `, ${s.retries} retries` : ""}${s.validation_failures ? `, ${s.validation_failures} validation failures` : ""}${s.rewrites ? `, ${s.rewrites} rewrites` : ""}${s.iterations ? `, ${s.iterations} fit iterations` : ""}`).join(" · ")}.
          Model {output.versions.model || "none (offline)"} · {output.versions.retrieval} · {Object.entries(output.versions.prompts).map(([k, v]) => `${k} ${v}`).join(", ")}.</p>
        </section> : null}
      </div>
    </details> : null}
  </div>;
}
