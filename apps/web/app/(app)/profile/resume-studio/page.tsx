"use client";

import { useEffect, useRef, useState } from "react";
import styles from "./studio.module.css";

type StudioResult = {
  pdfBase64: string; previewBase64: string; filename: string; elapsedMs: number; pageCount: number; omittedForFit: number;
  result: {
    warnings: string[]; requirementCoverage: number;
    resumeBullets: Array<{ id: string; decision: "KEEP" | "REORDER" | "REPLACE"; richText: Array<{text: string; bold: boolean}>; company: string; project: string; optimizedBullet: string; selectionReason: string; requirementIds: string[]; source: { text: string; field: string } }>;
    requirements: Array<{ id: string; text: string; category: string; coverageStatus: string }>;
  };
};

function Icon({ kind }: { kind: "spark" | "download" | "arrow" | "page" }) {
  return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {kind === "spark" ? <><path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z"/><path d="m20 2 .5 1.5L22 4l-1.5.5L20 6l-.5-1.5L18 4l1.5-.5Z"/></> : kind === "download" ? <><path d="M12 3v12m-4-4 4 4 4-4M5 16v4h14v-4"/></> : kind === "arrow" ? <path d="M5 12h14m-5-5 5 5-5 5"/> : <><path d="M6 3h8l4 4v14H6Z"/><path d="M14 3v5h4M9 12h6m-6 4h6"/></>}
  </svg>;
}

export default function ResumeStudioPage() {
  const [description, setDescription] = useState("");
  const [role, setRole] = useState("");
  const [company, setCompany] = useState("");
  const [result, setResult] = useState<StudioResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [generatedInput, setGeneratedInput] = useState("");
  const controller = useRef<AbortController | null>(null);
  const stale = Boolean(result && generatedInput !== JSON.stringify([description, role, company]));
  useEffect(() => () => controller.current?.abort(), []);

  async function generate(event: React.FormEvent) {
    event.preventDefault();
    if (description.trim().length < 40 || busy) return;
    const input = JSON.stringify([description, role, company]);
    controller.current?.abort();
    const request = new AbortController(); controller.current = request;
    setBusy(true); setError("");
    const timeout = setTimeout(() => request.abort(), 60000);
    try {
      const response = await fetch("/api/resume-studio", {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, signal: request.signal,
        body: JSON.stringify({ jobDescription: description, targetRole: role, targetCompany: company }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Could not generate your resume. Check the description and try again.");
      setResult(data); setGeneratedInput(input);
    } catch (cause) {
      if (request.signal.aborted) setError("Generation timed out. Your job description is still here; please try again.");
      else setError(cause instanceof Error ? cause.message : "Generation failed. Please try again.");
    } finally { clearTimeout(timeout); setBusy(false); }
  }

  function download() {
    if (!result || stale || busy) return;
    const bytes = Uint8Array.from(atob(result.pdfBase64), (character) => character.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes], { type: "application/pdf" }));
    const link = document.createElement("a"); link.href = url; link.download = result.filename; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return <div className={styles.studio}>
    <header className={styles.hero}>
      <div><div className={styles.eyebrow}><span/> YOUR EXPERIENCE, IN FOCUS</div>
        <h1>A new role.<br/><em>Your strongest story.</em></h1>
        <p>Turn a job description into a focused, one-page resume<br className={styles.desktopBreak}/> built from the experience you’ve already saved.</p>
      </div>
      <div className={styles.heroSeal}><Icon kind="page"/><strong>One page.<br/>All you.</strong><span>Original resume style</span></div>
    </header>

    <div className={styles.workspace}>
      <form className={styles.editor} onSubmit={generate}>
        <div className={styles.panelTitle}><span className={styles.step}>01</span><div><h2>The opportunity</h2><p>Paste the posting. We’ll find the right evidence.</p></div></div>
        <div className={styles.fields}><label>Role <span>optional</span><input value={role} onChange={e => setRole(e.target.value)} placeholder="Senior Software Engineer" maxLength={200} disabled={busy}/></label>
          <label>Company <span>optional</span><input value={company} onChange={e => setCompany(e.target.value)} placeholder="Company name" maxLength={200} disabled={busy}/></label></div>
        <label className={styles.descriptionLabel} htmlFor="studio-jd">Job description <span>Required</span></label>
        <textarea id="studio-jd" value={description} onChange={e => setDescription(e.target.value)} placeholder={"Paste the full job description here…\n\nInclude responsibilities, qualifications, and the skills the team is looking for."} maxLength={40000} disabled={busy} required minLength={40}/>
        <div className={styles.textMeta}><span>{description.length.toLocaleString()} / 40,000 characters</span>{description && !busy ? <button type="button" onClick={() => setDescription("")}>Clear</button> : <span>Full posting works best</span>}</div>
        <div className={styles.format}><Icon kind="page"/><div><strong>Classic · US Letter</strong><span>Original styling, fitted to one page</span></div><b>1 PAGE</b></div>
        <button className={styles.generate} disabled={busy || description.trim().length < 40} type="submit"><Icon kind="spark"/>{busy ? "Building your resume…" : result ? "Regenerate resume" : "Generate resume"}<Icon kind="arrow"/></button>
        <p className={styles.localNote}><span/> Uses your saved profile & stories · No API cost</p>
        {error ? <div className={styles.error} role="alert">{error}</div> : null}
        <div className={styles.process}><h3>Made from your experience</h3><ol><li><b>Match</b><span>Score the bullets in your approved resume.</span></li><li><b>Preserve</b><span>Keep strong bullets; consider stronger evidence only for weak slots.</span></li><li><b>Fit</b><span>Retain your fonts, layout, and one-page format.</span></li></ol></div>
      </form>

      <section className={styles.preview} aria-label="Resume preview" aria-busy={busy}>
        <div className={styles.previewToolbar}><div><span className={styles.step}>02</span><h2>Your resume</h2><span className={styles.pageBadge}>1 / 1</span></div>
          <button className={styles.download} type="button" onClick={download} disabled={!result || stale || busy}><Icon kind="download"/>Download PDF</button></div>
        <div className={styles.previewStatus} role="status" aria-live="polite">{busy ? "Selecting your experience and fitting the page…" : stale ? "Description changed. Regenerate to update your resume." : result ? `${result.result.resumeBullets.length} achievements selected · Ready in ${(result.elapsedMs / 1000).toFixed(1)}s` : "Your one-page resume will appear here"}</div>
        <div className={`${styles.paperStage} ${busy ? styles.working : ""}`}>
          {result ? <img className={styles.paper} src={`data:image/png;base64,${result.previewBase64}`} alt="Generated one-page resume, identical to the downloadable PDF"/> : <div className={styles.emptyPaper}>
            <div className={styles.mockName}/><div className={styles.mockContact}/><div className={styles.mockHeading}/>
            {Array.from({ length: 3 }, (_, section) => <div className={styles.mockSection} key={section}><i/>{Array.from({ length: 4 }, (_, line) => <span key={line}/>)}</div>)}
            <div className={styles.emptyPrompt}><div><Icon kind="spark"/></div><h3>Potential, on paper.</h3><p>Add a job description to see<br/>your experience take shape.</p></div>
          </div>}
        </div>
        <div className={styles.previewFoot}><span>US LETTER · 8.5 × 11 IN</span><span>{result ? "Preview and PDF are identical" : "Centered header · Ruled sections · Compact bullets"}</span></div>
      </section>
    </div>

    {result ? <section className={styles.evidence}>
      <div className={styles.evidenceHeader}><div className={styles.panelTitle}><span className={styles.step}>03</span><div><h2>Behind the resume</h2><p>See what stayed, moved, or was replaced, and why.</p></div></div><span>{result.result.resumeBullets.length} SOURCE-BACKED BULLETS</span></div>
      {result.omittedForFit > 0 ? <p className={styles.reviewNote}>{result.omittedForFit} lower-ranked achievements were omitted to keep the resume on one page.</p> : null}
      {result.result.warnings.length > 0 ? <details className={styles.reviewNote}><summary>{result.result.warnings.length} source checks to review before applying</summary><ul>{result.result.warnings.map((warning, i) => <li key={i}>{warning}</li>)}</ul></details> : <p className={styles.reviewNote}>Review the final wording before using this resume for an application.</p>}
      <div className={styles.evidenceGrid}>{result.result.resumeBullets.map((bullet, i) => <details key={`${bullet.id}-${i}`} className={styles.sourceCard}><summary><span>{String(i + 1).padStart(2, "0")}</span><div><b>{bullet.project || bullet.company}</b><small>{bullet.company || "Personal project"}</small></div><span>+</span></summary><h4>{bullet.decision}</h4><p>{bullet.selectionReason}</p><p>{bullet.richText?.map((run, index) => run.bold ? <strong key={index}>{run.text}</strong> : <span key={index}>{run.text}</span>) || bullet.optimizedBullet}</p><h4>Matched to this posting</h4><ul>{result.result.requirements.filter(req => bullet.requirementIds.includes(req.id)).map(req => <li key={req.id}>{req.text}</li>)}</ul><small>Selected from your saved {bullet.source.field.includes("interview") ? "behavioral story" : "resume evidence"}.</small></details>)}</div>
    </section> : null}
  </div>;
}
