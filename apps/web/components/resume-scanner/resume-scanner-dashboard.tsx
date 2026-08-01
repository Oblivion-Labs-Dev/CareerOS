"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  commitScan,
  createPerson,
  fileToBase64,
  getKnowledgeGraph,
  getQwenStatus,
  listPeople,
  matchJob,
  scanResume,
  type RiGraph,
  type RiMatchResult,
  type RiPerson,
  type RiRecommendations,
  type RiScan,
} from "@/lib/resume-intelligence-api";
import styles from "./resume-scanner.module.css";

type Tab = "scan" | "match" | "graph";

type Props = {
  /** When true, hides person management chrome for use on the profile page. */
  embedded?: boolean;
  /** Prefill scan/match person name from profile. */
  profileName?: string;
};

export function ResumeScannerDashboard({ embedded = false, profileName = "" }: Props) {
  const [tab, setTab] = useState<Tab>("scan");
  const [people, setPeople] = useState<RiPerson[]>([]);
  const [personId, setPersonId] = useState("");
  const [newPersonName, setNewPersonName] = useState(profileName);
  const [qwenOk, setQwenOk] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [resumeText, setResumeText] = useState("");
  const [scan, setScan] = useState<RiScan | null>(null);

  const [jobTitle, setJobTitle] = useState("");
  const [jobDescription, setJobDescription] = useState("");
  const [match, setMatch] = useState<RiMatchResult | null>(null);
  const [recommendations, setRecommendations] = useState<RiRecommendations | null>(null);

  const [graph, setGraph] = useState<RiGraph | null>(null);

  const selectedPerson = useMemo(
    () => people.find((p) => p.id === personId) || null,
    [people, personId],
  );

  const refreshPeople = useCallback(async () => {
    const res = await listPeople();
    setPeople(res.people);
    if (!personId && res.people[0]) setPersonId(res.people[0].id);
  }, [personId]);

  useEffect(() => {
    void refreshPeople().catch(() => setPeople([]));
    void getQwenStatus()
      .then((s) => setQwenOk(s.enabled && s.connection?.success))
      .catch(() => setQwenOk(false));
  }, [refreshPeople]);

  useEffect(() => {
    if (profileName.trim()) setNewPersonName(profileName.trim());
  }, [profileName]);

  const handleCreatePerson = async () => {
    if (!newPersonName.trim()) return;
    setLoading(true);
    setError("");
    try {
      const res = await createPerson(newPersonName.trim());
      if (!embedded) setNewPersonName("");
      await refreshPeople();
      setPersonId(res.person.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create person");
    } finally {
      setLoading(false);
    }
  };

  const handleFileUpload = async (file: File | null) => {
    if (!file) return;
    setLoading(true);
    setError("");
    try {
      const { base64, mimeType, filename } = await fileToBase64(file);
      const res = await scanResume({
        personId: personId || undefined,
        personName: selectedPerson?.fullName || newPersonName || "Candidate",
        base64,
        mimeType,
        filename,
        useQwen: true,
      });
      setScan(res.scan);
      if (res.personId) setPersonId(res.personId);
      await refreshPeople();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Scan failed");
    } finally {
      setLoading(false);
    }
  };

  const handleTextScan = async () => {
    if (!resumeText.trim()) return;
    setLoading(true);
    setError("");
    try {
      const res = await scanResume({
        personId: personId || undefined,
        personName: selectedPerson?.fullName || newPersonName || "Candidate",
        text: resumeText,
        useQwen: true,
      });
      setScan(res.scan);
      if (res.personId) setPersonId(res.personId);
      await refreshPeople();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Scan failed");
    } finally {
      setLoading(false);
    }
  };

  const handleCommit = async () => {
    if (!scan) return;
    setLoading(true);
    setError("");
    try {
      await commitScan(scan.id);
      setError("");
      alert("Accomplishments imported to corpus.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Commit failed");
    } finally {
      setLoading(false);
    }
  };

  const handleMatch = async () => {
    if (!jobDescription.trim()) return;
    setLoading(true);
    setError("");
    try {
      const res = await matchJob({
        jobDescription,
        jobTitle,
        personId: personId || undefined,
        resumeText: scan?.textPreview || resumeText,
        useQwen: true,
      });
      setMatch(res.match);
      setRecommendations(res.recommendations);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Match failed");
    } finally {
      setLoading(false);
    }
  };

  const handleLoadGraph = async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getKnowledgeGraph(personId || undefined);
      setGraph(res.graph);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Graph load failed");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (tab === "graph") void handleLoadGraph();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, personId]);

  return (
    <div className={embedded ? `${styles.root} ${styles.embedded}` : styles.root}>
      <div className={styles.toolbar}>
        <div className={styles.tabs}>
          {(["scan", "match", "graph"] as Tab[]).map((t) => (
            <button key={t} type="button" className={tab === t ? styles.tabActive : styles.tab} onClick={() => setTab(t)}>
              {t === "scan" ? "Resume scan" : t === "match" ? "Job match" : "Knowledge graph"}
            </button>
          ))}
        </div>
        <div className={styles.qwenBadge} data-ok={qwenOk === true ? "yes" : qwenOk === false ? "no" : "unknown"}>
          Qwen {qwenOk === true ? "connected" : qwenOk === false ? "offline" : "…"}
        </div>
      </div>

      {!embedded ? (
        <section className={styles.personBar}>
          <label>
            Person
            <select value={personId} onChange={(e) => setPersonId(e.target.value)}>
              <option value="">All / new</option>
              {people.map((p) => (
                <option key={p.id} value={p.id}>{p.fullName}</option>
              ))}
            </select>
          </label>
          <input
            type="text"
            placeholder="New person name"
            value={newPersonName}
            onChange={(e) => setNewPersonName(e.target.value)}
          />
          <button type="button" onClick={handleCreatePerson} disabled={loading || !newPersonName.trim()}>
            Add person
          </button>
        </section>
      ) : people.length > 1 ? (
        <section className={styles.personBarCompact}>
          <label>
            Corpus person
            <select value={personId} onChange={(e) => setPersonId(e.target.value)}>
              {people.map((p) => (
                <option key={p.id} value={p.id}>{p.fullName}</option>
              ))}
            </select>
          </label>
        </section>
      ) : null}

      {error && <p className={styles.error} role="alert">{error}</p>}
      {loading && <p className={styles.loading}>Working…</p>}

      {tab === "scan" && (
        <div className={styles.grid}>
          <section className={styles.panel}>
            <h2>Upload or paste resume</h2>
            <p className={styles.hint}>Qwen extracts contact info, skills, work history, accomplishment candidates, and ATS keyword sets.</p>
            <input
              type="file"
              accept=".pdf,.txt,.doc,.docx"
              onChange={(e) => void handleFileUpload(e.target.files?.[0] || null)}
            />
            <textarea
              rows={12}
              placeholder="Or paste resume text…"
              value={resumeText}
              onChange={(e) => setResumeText(e.target.value)}
            />
            <button type="button" className={styles.primary} onClick={handleTextScan} disabled={loading || !resumeText.trim()}>
              Scan with Qwen
            </button>
          </section>

          <section className={styles.panel}>
            <h2>Scan results</h2>
            {!scan ? (
              <p className={styles.muted}>Run a scan to see structured resume intelligence.</p>
            ) : (
              <>
                <div className={styles.metaRow}>
                  <span>{scan.qwenUsed ? "Qwen enriched" : "Heuristic only"}</span>
                  {scan.qwenError && <span className={styles.warn}>{scan.qwenError}</span>}
                </div>
                {scan.contact && (
                  <div className={styles.block}>
                    <h3>Contact</h3>
                    <p>{scan.contact.fullName} · {scan.contact.email} · {scan.contact.phone}</p>
                  </div>
                )}
                {scan.skills && scan.skills.length > 0 && (
                  <div className={styles.block}>
                    <h3>Skills</h3>
                    <div className={styles.chips}>{scan.skills.map((s) => <span key={s}>{s}</span>)}</div>
                  </div>
                )}
                {scan.atsKeywordSets && (
                  <div className={styles.block}>
                    <h3>ATS keyword sets</h3>
                    <div className={styles.chips}>
                      {(scan.atsKeywordSets.skills || []).slice(0, 12).map((s) => <span key={s}>{s}</span>)}
                    </div>
                  </div>
                )}
                <div className={styles.block}>
                  <h3>Accomplishment candidates ({scan.accomplishmentCandidates?.length || 0})</h3>
                  <ul className={styles.list}>
                    {(scan.accomplishmentCandidates || []).slice(0, 8).map((c) => (
                      <li key={c.tempId || c.id || c.bullet}>
                        <strong>{c.company || "—"}</strong> — {c.bullet || c.title}
                      </li>
                    ))}
                  </ul>
                </div>
                <button type="button" className={styles.primary} onClick={handleCommit} disabled={loading}>
                  Import all to corpus
                </button>
              </>
            )}
          </section>
        </div>
      )}

      {tab === "match" && (
        <div className={styles.grid}>
          <section className={styles.panel}>
            <h2>Target job</h2>
            <input
              type="text"
              placeholder="Job title (optional)"
              value={jobTitle}
              onChange={(e) => setJobTitle(e.target.value)}
            />
            <textarea
              rows={14}
              placeholder="Paste job description…"
              value={jobDescription}
              onChange={(e) => setJobDescription(e.target.value)}
            />
            <button type="button" className={styles.primary} onClick={handleMatch} disabled={loading || !jobDescription.trim()}>
              Analyze match + Qwen recommendations
            </button>
          </section>

          <section className={styles.panel}>
            <h2>Match analysis</h2>
            {!match ? (
              <p className={styles.muted}>Paste a job description to see how your resume corpus matches and what to add for more callbacks.</p>
            ) : (
              <>
                <div className={styles.scoreBlock}>
                  <div className={styles.score}>{match.overallScore}%</div>
                  <div>
                    <p><strong>Call likelihood:</strong> {match.callLikelihood}</p>
                    <p className={styles.muted}>{match.summary}</p>
                  </div>
                </div>
                <div className={styles.block}>
                  <h3>Explicit proof ({match.explicit.length})</h3>
                  <div className={styles.chips}>{match.explicit.slice(0, 15).map((m) => <span key={m.term} data-tier="ok">{m.term}</span>)}</div>
                </div>
                <div className={styles.block}>
                  <h3>Gaps — missing ({match.missing.length})</h3>
                  <div className={styles.chips}>{match.missing.slice(0, 15).map((m) => <span key={m.term} data-tier="bad">{m.term}</span>)}</div>
                </div>
                {match.atsKeywordSets.gapSkills && match.atsKeywordSets.gapSkills.length > 0 && (
                  <div className={styles.block}>
                    <h3>ATS skill gaps</h3>
                    <div className={styles.chips}>{match.atsKeywordSets.gapSkills.slice(0, 12).map((s) => <span key={s} data-tier="bad">{s}</span>)}</div>
                  </div>
                )}
                {recommendations && (
                  <div className={styles.block}>
                    <h3>Qwen — what to add</h3>
                    {recommendations.callLikelihoodSummary && <p>{recommendations.callLikelihoodSummary}</p>}
                    <ul className={styles.list}>
                      {(recommendations.addToResume || []).map((item) => <li key={item}>{item}</li>)}
                      {(recommendations.suggestedBullets || []).map((item) => <li key={item}>{item}</li>)}
                      {(recommendations.keywordPhrasesToAdd || []).map((item) => <li key={item}>Keyword: {item}</li>)}
                    </ul>
                  </div>
                )}
              </>
            )}
          </section>
        </div>
      )}

      {tab === "graph" && (
        <section className={styles.panel}>
          <h2>Knowledge graph</h2>
          <p className={styles.hint}>Built from corpus accomplishments — companies, skills, metrics, and domains linked to each story.</p>
          {!graph || graph.nodes.length === 0 ? (
            <p className={styles.muted}>No graph data yet. Scan a resume and import accomplishments, or use existing corpus entries.</p>
          ) : (
            <>
              <p className={styles.muted}>{graph.stats.nodeCount} nodes · {graph.stats.edgeCount} edges · {graph.stats.accomplishmentCount} accomplishments</p>
              <svg className={styles.graphSvg} viewBox="0 0 900 520" role="img" aria-label="Resume knowledge graph">
                {graph.links.map((link) => {
                  const source = graph.nodes.find((n) => n.id === link.source);
                  const target = graph.nodes.find((n) => n.id === link.target);
                  if (!source || !target) return null;
                  return (
                    <line
                      key={`${link.source}-${link.target}`}
                      x1={source.x}
                      y1={source.y}
                      x2={target.x}
                      y2={target.y}
                      className={styles.graphLink}
                    />
                  );
                })}
                {graph.nodes.map((node) => (
                  <g key={node.id} transform={`translate(${node.x}, ${node.y})`}>
                    <circle r={node.type === "accomplishment" ? 10 : 7} className={styles[`graphNode_${node.type}`] || styles.graphNode_default} />
                    <text y={18} textAnchor="middle" className={styles.graphLabel}>{node.label.slice(0, 22)}</text>
                  </g>
                ))}
              </svg>
            </>
          )}
          <button type="button" onClick={handleLoadGraph} disabled={loading}>Refresh graph</button>
        </section>
      )}
    </div>
  );
}
