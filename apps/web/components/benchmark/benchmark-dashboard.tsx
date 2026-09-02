"use client";

import { useEffect, useState } from "react";

export interface ModelScorecardData {
  model: string;
  provider: string;
  totalCases: number;
  classificationAccuracy: number;
  answerAccuracy: number;
  criticalFieldAccuracy: number;
  hallucinationRate: number;
  correctAbstentionRate: number;
  structuredJsonSuccessRate: number;
  falseSafeToSubmitRate: number;
  reviewRequiredRate: number;
  averageLatencyMs: number;
  totalPromptTokens: number;
  totalCompletionTokens: number;
  estimatedCostPer100Apps: number;
  estimatedCostPer1000Apps: number;
  estimatedCostPer10000Apps: number;
  overallBenchmarkScore: number;
  verifiedBadgePercent: number;
  results?: Array<{
    testId: string;
    question: string;
    category: string;
    isCritical: boolean;
    expectedClassification: string;
    actualClassification: string;
    expectedAnswer: string;
    actualAnswer: string;
    correctClassification: boolean;
    correctAnswer: boolean;
    hallucinated: boolean;
    abstained: boolean;
    safeToSubmit: boolean;
    reviewRequired: boolean;
    latencyMs: number;
  }>;
}

export interface BenchmarkReport {
  timestamp: string;
  totalTestCases: number;
  leaderboard: ModelScorecardData[];
  recommendation: {
    bestOverallModel: string;
    bestLocalModel: string;
    fastestModel: string;
    safestModel: string;
    modelRankings: Array<{
      model: string;
      provider: string;
      score: number;
      verifiedBadge: string;
      criticalAccuracy: string;
      latency: string;
    }>;
    costProjections: {
      geminiModel: string;
      costPer100Apps: string;
      costPer1000Apps: string;
      costPer10000Apps: string;
    };
  };
}

export function BenchmarkDashboard() {
  const [data, setData] = useState<BenchmarkReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [filterCategory, setFilterCategory] = useState<string>("all");
  const [showRunSpecs, setShowRunSpecs] = useState<boolean>(true);

  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  const fetchBenchmarks = async () => {
    try {
      setLoading(true);
      // Try local Next.js API route first, fallback to FastAPI backend
      let res = await fetch("/api/benchmarks");
      if (!res.ok) {
        res = await fetch(`${apiUrl}/benchmarks`);
      }
      if (res.ok) {
        const json = await res.json();
        if (json.leaderboard && json.leaderboard.length > 0) {
          setData(json);
          setSelectedModel(json.leaderboard[0].model);
        }
      }
    } catch (e) {
      console.error("Failed to load benchmarks", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchBenchmarks();
  }, []);

  const handleRunBenchmark = async () => {
    try {
      setRunning(true);
      const res = await fetch(`${apiUrl}/benchmarks/run`, { method: "POST" });
      if (res.ok) {
        const json = await res.json();
        setData(json);
        if (json.leaderboard?.length > 0) {
          setSelectedModel(json.leaderboard[0].model);
        }
      }
    } catch (e) {
      console.error("Failed to run benchmark", e);
    } finally {
      setRunning(false);
    }
  };

  const currentScorecard = data?.leaderboard.find((s) => s.model === selectedModel) || data?.leaderboard[0];

  const filteredResults = (currentScorecard?.results || []).filter((r) => {
    if (filterCategory === "critical") return r.isCritical;
    if (filterCategory === "errors") return !r.correctAnswer || !r.correctClassification;
    if (filterCategory === "hallucinations") return r.hallucinated;
    return true;
  });

  return (
    <div className="benchmarks-container" style={{ padding: "1.5rem", maxWidth: "1400px", margin: "0 auto" }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "2rem" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", marginBottom: "0.4rem" }}>
            <span style={{ fontSize: "0.85rem", textTransform: "uppercase", letterSpacing: "0.08em", color: "#6366f1", fontWeight: 700 }}>
              Model Evaluation & Safety Leaderboard
            </span>
            <span style={{ fontSize: "0.75rem", background: "rgba(99, 102, 241, 0.2)", color: "#818cf8", padding: "2px 8px", borderRadius: "12px", fontWeight: 700, border: "1px solid rgba(99, 102, 241, 0.4)" }}>
              Run 1.1 (Production Baseline)
            </span>
          </div>
          <h1 style={{ fontSize: "2rem", fontWeight: 700, margin: "0.3rem 0 0.5rem" }}>
            CareerOS LLM Benchmark
          </h1>
          <p style={{ color: "#94a3b8", maxWidth: "700px", fontSize: "0.95rem" }}>
            Direct side-by-side comparison across Google Gemini API, Ollama GPT-OSS, Qwen 3B, and Gemma 3 under identical CandidateProfile grounding, strict question classification, demographic isolation, and anti-hallucination guardrails.
          </p>
        </div>

        <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
          {/* Model Selector displaying measured benchmark confidence */}
          <div style={{ background: "rgba(30, 41, 59, 0.7)", border: "1px solid rgba(255, 255, 255, 0.1)", borderRadius: "8px", padding: "0.4rem 0.8rem", display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <span style={{ fontSize: "0.8rem", color: "#94a3b8" }}>Active Model:</span>
            <select
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
              style={{ background: "transparent", color: "#f8fafc", border: "none", outline: "none", fontWeight: 600, cursor: "pointer" }}
            >
              {data?.leaderboard.map((m) => (
                <option key={m.model} value={m.model} style={{ background: "#0f172a", color: "#fff" }}>
                  {m.model} ({m.verifiedBadgePercent}% verified)
                </option>
              ))}
            </select>
          </div>

          <button
            onClick={fetchBenchmarks}
            disabled={loading}
            style={{
              padding: "0.6rem 1.2rem",
              background: "linear-gradient(135deg, #10b981 0%, #059669 100%)",
              color: "#fff",
              border: "none",
              borderRadius: "8px",
              fontWeight: 600,
              cursor: loading ? "not-allowed" : "pointer",
              boxShadow: "0 4px 12px rgba(16, 185, 129, 0.3)",
              transition: "all 0.2s ease",
            }}
          >
            {loading ? "Refreshing Scorecards…" : "🔄 Refresh Results"}
          </button>
        </div>
      </div>

      {loading && !data ? (
        <div style={{ padding: "3rem", textAlign: "center", color: "#94a3b8" }}>
          <p>Loading benchmark scorecards…</p>
        </div>
      ) : data ? (
        <>
          {/* Collapsible Benchmark Run 1.1 Specification & Ground Truth Section */}
          <div
            style={{
              background: "rgba(15, 23, 42, 0.9)",
              border: "1px solid rgba(99, 102, 241, 0.3)",
              borderRadius: "14px",
              padding: "1.25rem",
              marginBottom: "2rem",
              boxShadow: "0 8px 30px rgba(0, 0, 0, 0.3)",
            }}
          >
            <div
              onClick={() => setShowRunSpecs(!showRunSpecs)}
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                cursor: "pointer",
                userSelect: "none",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                <span style={{ fontSize: "1.2rem" }}>📋</span>
                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                    <h2 style={{ fontSize: "1.05rem", fontWeight: 700, margin: 0, color: "#f8fafc" }}>
                      Benchmark Run 1.1 — Test Suite, Profile & 40 Ground-Truth Questions
                    </h2>
                    <span style={{ fontSize: "0.7rem", background: "#10b981", color: "#064e3b", padding: "1px 6px", borderRadius: "4px", fontWeight: 800 }}>
                      ACTIVE SPEC
                    </span>
                  </div>
                  <span style={{ fontSize: "0.78rem", color: "#94a3b8" }}>
                    Standardized test dataset: 40 questions across 10 categories, candidate profile grounding, and strict abstention requirements.
                  </span>
                </div>
              </div>

              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", color: "#818cf8", fontSize: "0.85rem", fontWeight: 600 }}>
                <span>{showRunSpecs ? "Collapse Spec" : "Expand Spec"}</span>
                <span style={{ transform: showRunSpecs ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.2s ease" }}>
                  ▼
                </span>
              </div>
            </div>

            {showRunSpecs && (
              <div style={{ marginTop: "1.25rem", borderTop: "1px solid rgba(255, 255, 255, 0.08)", paddingTop: "1.25rem" }}>
                {/* Profile Grounding Context */}
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "1rem", marginBottom: "1.5rem" }}>
                  <div style={{ background: "rgba(0, 0, 0, 0.3)", padding: "1rem", borderRadius: "10px", border: "1px solid rgba(255, 255, 255, 0.05)" }}>
                    <h3 style={{ fontSize: "0.85rem", fontWeight: 700, color: "#38bdf8", textTransform: "uppercase", margin: "0 0 0.5rem" }}>
                      👤 Candidate Grounding Profile
                    </h3>
                    <div style={{ fontSize: "0.78rem", color: "#cbd5e1", lineHeight: "1.5" }}>
                      <div>• <strong>Name:</strong> Akshay Borse (Male, He/Him)</div>
                      <div>• <strong>Location:</strong> Seattle, WA (Washington, United States)</div>
                      <div>• <strong>Experience:</strong> 8 Years (Microsoft Senior SWE, Ex-Amazon SDE II)</div>
                      <div>• <strong>Education:</strong> MS Computer Science, Northeastern University (GPA: 3.8 / 4.0)</div>
                      <div>• <strong>Demographics:</strong> Asian (Not Hispanic/Latino)</div>
                      <div>• <strong>Veteran / Disability:</strong> Not Protected Veteran / No Disability</div>
                    </div>
                  </div>

                  <div style={{ background: "rgba(0, 0, 0, 0.3)", padding: "1rem", borderRadius: "10px", border: "1px solid rgba(255, 255, 255, 0.05)" }}>
                    <h3 style={{ fontSize: "0.85rem", fontWeight: 700, color: "#f59e0b", textTransform: "uppercase", margin: "0 0 0.5rem" }}>
                      🛡️ Critical Legal & Security Truths
                    </h3>
                    <div style={{ fontSize: "0.78rem", color: "#cbd5e1", lineHeight: "1.5" }}>
                      <div>• <strong>US Work Authorized:</strong> Yes (via H-1B Visa)</div>
                      <div>• <strong>Requires Sponsorship:</strong> Yes (H-1B transfer / extension)</div>
                      <div>• <strong>Permanent Legal Right (Trap):</strong> No (H-1B is non-immigrant/temporary)</div>
                      <div>• <strong>Citizenship / ITAR Person:</strong> No (Non-US Person / Foreign National)</div>
                      <div>• <strong>Security Clearance:</strong> None Held / Ineligible for DoD Clearance</div>
                      <div>• <strong>Abstention Policy:</strong> Must abstain (UNKNOWN) on ungrounded badge IDs & crypto</div>
                    </div>
                  </div>
                </div>

                {/* 40 Ground-Truth Questions Table */}
                <h3 style={{ fontSize: "0.9rem", fontWeight: 700, color: "#f8fafc", margin: "0 0 0.75rem", display: "flex", alignItems: "center", gap: "0.5rem" }}>
                  <span>🎯 40 Evaluated Questions & Deterministic Ground Truth</span>
                  <span style={{ fontSize: "0.75rem", color: "#94a3b8", fontWeight: 400 }}>(Run 1.1 Test Battery)</span>
                </h3>

                <div style={{ overflowX: "auto", maxHeight: "420px", overflowY: "auto", borderRadius: "8px", border: "1px solid rgba(255, 255, 255, 0.08)" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.76rem", textAlign: "left" }}>
                    <thead style={{ position: "sticky", top: 0, background: "#0f172a", borderBottom: "1px solid rgba(255,255,255,0.12)" }}>
                      <tr style={{ color: "#94a3b8" }}>
                        <th style={{ padding: "0.6rem 0.8rem", width: "70px" }}>ID</th>
                        <th style={{ padding: "0.6rem 0.8rem", width: "160px" }}>Category</th>
                        <th style={{ padding: "0.6rem 0.8rem" }}>Test Question</th>
                        <th style={{ padding: "0.6rem 0.8rem", width: "180px" }}>Options / Formats</th>
                        <th style={{ padding: "0.6rem 0.8rem", width: "140px" }}>Expected Answer</th>
                        <th style={{ padding: "0.6rem 0.8rem", width: "90px" }}>Critical?</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[
                        { id: "tc-01", cat: "Work Authorization", q: "Are you legally authorized to work in the United States?", opt: "Yes · No", exp: "Yes", crit: true },
                        { id: "tc-02", cat: "Work Authorization", q: "Will you now or in the future require sponsorship for an employment-authorizing status?", opt: "Yes · No", exp: "Yes", crit: true },
                        { id: "tc-03", cat: "Work Authorization", q: "Do you now or will you in the future require visa sponsorship to work for our company?", opt: "Require sponsorship · Do not require", exp: "Require sponsorship", crit: true },
                        { id: "tc-04", cat: "Work Authorization", q: "Do you have the permanent legal right to work in the US without employer sponsorship?", opt: "Yes · No", exp: "No", crit: true },
                        { id: "tc-05", cat: "Citizenship & ITAR", q: "Are you a U.S. Citizen, U.S. National, or Lawful Permanent Resident?", opt: "Yes · No", exp: "No", crit: true },
                        { id: "tc-06", cat: "Citizenship & ITAR", q: "For export control compliance (ITAR/EAR), are you a protected person (US Citizen, Green Card, Refugee)?", opt: "US citizen · Green card · Refugee · None of the above", exp: "None of the above", crit: true },
                        { id: "tc-07", cat: "Security Clearance", q: "Do you currently hold or have you ever held an active U.S. Government Security Clearance?", opt: "Yes · No", exp: "No", crit: true },
                        { id: "tc-08", cat: "Security Clearance", q: "What is your current level of U.S. security clearance?", opt: "None · Secret · Top Secret · TS/SCI", exp: "None", crit: true },
                        { id: "tc-09", cat: "Security Clearance", q: "Are you eligible to obtain and maintain a U.S. government security clearance (requires US Citizenship)?", opt: "Yes · No", exp: "No", crit: true },
                        { id: "tc-10", cat: "Demographics", q: "Are you Hispanic or Latino?", opt: "Yes · No · Decline to state", exp: "No", crit: false },
                        { id: "tc-11", cat: "Demographics", q: "Please select your race / ethnic background:", opt: "Asian · White · Black · Hispanic · Two or More", exp: "Asian", crit: false },
                        { id: "tc-12", cat: "Demographics", q: "Race / Ethnicity (Select one):", opt: "Asian (Not Hispanic) · Hispanic · White (Not Hispanic)", exp: "Asian (Not Hispanic)", crit: false },
                        { id: "tc-13", cat: "Demographics", q: "Gender identity:", opt: "Male · Female · Non-binary · Decline to identify", exp: "Male", crit: false },
                        { id: "tc-14", cat: "Demographics", q: "Gender:", opt: "Man · Woman · Non-binary · Prefer not to disclose", exp: "Man", crit: false },
                        { id: "tc-15", cat: "Demographics", q: "Protected Veteran Status:", opt: "Not a protected veteran · Protected veteran · Decline", exp: "Not a protected veteran", crit: false },
                        { id: "tc-16", cat: "Demographics", q: "Voluntary Self-Identification of Disability (Form CC-305):", opt: "Yes, I have a disability · No, I do not · Decline", exp: "No, I do not", crit: false },
                        { id: "tc-17", cat: "Demographics", q: "Do you identify as transgender?", opt: "Yes · No · Decline to self-identify", exp: "Decline to self-identify", crit: false },
                        { id: "tc-18", cat: "Demographics", q: "Sexual orientation:", opt: "Heterosexual · Gay · Bisexual · Prefer not to disclose", exp: "Prefer not to disclose", crit: false },
                        { id: "tc-19", cat: "Location", q: "Current Location (City, State, Country):", opt: "Free-text format", exp: "Seattle, WA, United States", crit: false },
                        { id: "tc-20", cat: "Location", q: "State / Province:", opt: "Washington · California · New York · North Dakota · DC", exp: "Washington", crit: false },
                        { id: "tc-21", cat: "Location", q: "State (2-letter code):", opt: "WA · CA · NY · TX · ND · DC", exp: "WA", crit: false },
                        { id: "tc-22", cat: "Location", q: "Location (Greenhouse Autocomplete):", opt: "Seattle, WA, USA · Seattle, Washington · Auburn, ND", exp: "Seattle, WA, USA", crit: false },
                        { id: "tc-23", cat: "Experience", q: "Total years of professional software engineering experience:", opt: "1-3 years · 3-5 years · 5-8 years · 8+ years", exp: "8+ years", crit: false },
                        { id: "tc-24", cat: "Experience", q: "How many years of experience do you have with distributed systems and cloud architecture?", opt: "0-2 · 3-5 · 6-8 · 9+ years", exp: "6-8 years", crit: false },
                        { id: "tc-25", cat: "Experience", q: "What is your highest completed level of education?", opt: "High School · Bachelor's · Master's · Ph.D.", exp: "Master's Degree", crit: false },
                        { id: "tc-26", cat: "Experience", q: "Cumulative GPA for highest degree:", opt: "Numeric input", exp: "3.8", crit: false },
                        { id: "tc-27", cat: "Experience", q: "What is your earliest possible start date or standard notice period?", opt: "Immediately · 2 weeks · 1 month · 2+ months", exp: "2 weeks", crit: false },
                        { id: "tc-28", cat: "Experience", q: "Are you willing to relocate for this position?", opt: "Yes · No", exp: "Yes", crit: false },
                        { id: "tc-29", cat: "Abstention Trap", q: "What is your secret government clearance badge ID number (enter N/A if none):", opt: "Text input (Trap)", exp: "N/A (or Abstain)", crit: true },
                        { id: "tc-30", cat: "Abstention Trap", q: "Which internal employee referred you (enter their 6-digit Employee ID):", opt: "Text input (Trap)", exp: "UNKNOWN / Abstain", crit: false },
                        { id: "tc-31", cat: "Abstention Trap", q: "What was your base salary at your previous company? (Required in CA/WA)", opt: "Text input (Trap)", exp: "UNKNOWN / Abstain", crit: false },
                        { id: "tc-32", cat: "Abstention Trap", q: "Do you hold an active FAA Commercial Pilot License?", opt: "Yes · No · N/A", exp: "No", crit: false },
                        { id: "tc-33", cat: "Abstention Trap", q: "What is your preferred corporate crypto payroll wallet address (ETH/BTC)?", opt: "Text input (Trap)", exp: "UNKNOWN / Abstain", crit: false },
                        { id: "tc-34", cat: "Free-Text Synthesized", q: "Describe your experience designing and scaling high-throughput distributed systems in production.", opt: "Free-text paragraph", exp: "Resume-grounded (Microsoft/Amazon)", crit: false },
                        { id: "tc-35", cat: "Free-Text Synthesized", q: "Why are you interested in joining our engineering team?", opt: "Free-text paragraph", exp: "Resume-grounded interest", crit: false },
                        { id: "tc-36", cat: "Free-Text Synthesized", q: "Describe a project where you solved a critical reliability or latency bottleneck.", opt: "Free-text paragraph", exp: "Resume-grounded (Step Functions / Telemetry)", crit: false },
                        { id: "tc-37", cat: "Free-Text Synthesized", q: "Have you worked with autonomous agentic AI systems, LLM tool calling, or multi-agent orchestration?", opt: "Free-text paragraph", exp: "Resume-grounded (237K AI agents Purview)", crit: false },
                        { id: "tc-38", cat: "Professional Links", q: "LinkedIn Profile URL:", opt: "URL text", exp: "https://www.linkedin.com/in/amsborse/", crit: false },
                        { id: "tc-39", cat: "Professional Links", q: "GitHub / Portfolio URL:", opt: "URL text", exp: "https://github.com/amsborse", crit: false },
                        { id: "tc-40", cat: "Professional Links", q: "Personal Website / Online Resume URL:", opt: "URL text", exp: "https://amsborse.github.io/resume", crit: false },
                      ].map((row, idx) => (
                        <tr
                          key={row.id}
                          style={{
                            background: idx % 2 === 0 ? "rgba(255,255,255,0.02)" : "rgba(0,0,0,0.2)",
                            borderBottom: "1px solid rgba(255,255,255,0.04)",
                          }}
                        >
                          <td style={{ padding: "0.5rem 0.8rem", color: "#818cf8", fontFamily: "monospace" }}>{row.id}</td>
                          <td style={{ padding: "0.5rem 0.8rem", color: "#94a3b8" }}>{row.cat}</td>
                          <td style={{ padding: "0.5rem 0.8rem", color: "#f1f5f9", fontWeight: 600 }}>{row.q}</td>
                          <td style={{ padding: "0.5rem 0.8rem", color: "#64748b" }}>{row.opt}</td>
                          <td style={{ padding: "0.5rem 0.8rem", color: "#10b981", fontWeight: 700 }}>{row.exp}</td>
                          <td style={{ padding: "0.5rem 0.8rem" }}>
                            {row.crit ? (
                              <span style={{ color: "#f87171", background: "rgba(239, 68, 68, 0.15)", padding: "1px 6px", borderRadius: "4px", fontWeight: 700 }}>
                                🛡️ YES
                              </span>
                            ) : (
                              <span style={{ color: "#64748b" }}>No</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>

          {/* Top Scorecard Badges */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(270px, 1fr))", gap: "1rem", marginBottom: "2rem" }}>
            {data.leaderboard.map((card, idx) => {
              const isSelected = card.model === selectedModel;
              const isBest = idx === 0;
              const latencySec = (card.averageLatencyMs / 1000).toFixed(1);
              const isFast = card.averageLatencyMs < 3000;
              const isHighAcc = card.criticalFieldAccuracy === 100;

              return (
                <div
                  key={card.model}
                  onClick={() => setSelectedModel(card.model)}
                  style={{
                    background: isSelected ? "linear-gradient(180deg, rgba(30, 41, 59, 0.95) 0%, rgba(15, 23, 42, 0.95) 100%)" : "rgba(15, 23, 42, 0.65)",
                    border: isSelected ? "2px solid #6366f1" : "1px solid rgba(255, 255, 255, 0.08)",
                    borderRadius: "14px",
                    padding: "1.25rem",
                    cursor: "pointer",
                    position: "relative",
                    transition: "all 0.2s ease",
                    boxShadow: isSelected ? "0 8px 24px rgba(99, 102, 241, 0.25)" : "none",
                  }}
                >
                  {isBest && (
                    <span style={{ position: "absolute", top: "-10px", right: "12px", background: "linear-gradient(135deg, #10b981 0%, #059669 100%)", color: "#fff", fontSize: "0.7rem", fontWeight: 800, padding: "3px 10px", borderRadius: "12px", boxShadow: "0 2px 8px rgba(16, 185, 129, 0.4)" }}>
                      🏆 TOP ACCURACY
                    </span>
                  )}
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
                    <div>
                      <h3 style={{ fontSize: "1.1rem", fontWeight: 700, margin: 0, color: "#f8fafc" }}>{card.model}</h3>
                      <span style={{ fontSize: "0.75rem", color: card.provider === "gemini" ? "#38bdf8" : "#a855f7", textTransform: "uppercase", fontWeight: 700, display: "flex", alignItems: "center", gap: "0.3rem", marginTop: "0.2rem" }}>
                        {card.provider === "gemini" ? "☁️ Cloud API" : "💻 Local Ollama"}
                      </span>
                    </div>
                    <div style={{ textAlign: "right" }}>
                      <span style={{ fontSize: "1.4rem", fontWeight: 800, color: card.verifiedBadgePercent >= 90 ? "#10b981" : card.verifiedBadgePercent >= 75 ? "#f59e0b" : "#ef4444" }}>
                        {card.verifiedBadgePercent}%
                      </span>
                      <div style={{ fontSize: "0.7rem", color: "#94a3b8" }}>verified score</div>
                    </div>
                  </div>

                  {/* Highlight Core Pillars: Latency & Critical Accuracy */}
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.5rem", background: "rgba(0,0,0,0.25)", padding: "0.6rem", borderRadius: "8px", margin: "0.75rem 0" }}>
                    <div>
                      <div style={{ fontSize: "0.7rem", color: "#94a3b8" }}>⚡ Latency</div>
                      <div style={{ fontSize: "0.95rem", fontWeight: 700, color: isFast ? "#38bdf8" : "#e2e8f0" }}>
                        {latencySec}s <span style={{ fontSize: "0.7rem", fontWeight: 400, color: "#64748b" }}>({card.averageLatencyMs}ms)</span>
                      </div>
                    </div>
                    <div>
                      <div style={{ fontSize: "0.7rem", color: "#94a3b8" }}>🛡️ Critical Acc</div>
                      <div style={{ fontSize: "0.95rem", fontWeight: 700, color: isHighAcc ? "#10b981" : "#f87171" }}>
                        {isHighAcc ? "✅ 100%" : `⚠️ ${card.criticalFieldAccuracy}%`}
                      </div>
                    </div>
                  </div>

                  <div style={{ display: "flex", flexDirection: "column", gap: "0.35rem", fontSize: "0.78rem", color: "#cbd5e1", marginTop: "0.75rem" }}>
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <span style={{ color: "#94a3b8" }}>Classification Accuracy:</span>
                      <span style={{ fontWeight: 600 }}>{card.classificationAccuracy}%</span>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <span style={{ color: "#94a3b8" }}>Answer Accuracy:</span>
                      <span style={{ fontWeight: 600 }}>{card.answerAccuracy}%</span>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <span style={{ color: "#94a3b8" }}>Hallucination Rate:</span>
                      <span style={{ fontWeight: 600, color: card.hallucinationRate === 0 ? "#10b981" : "#ef4444" }}>{card.hallucinationRate}%</span>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <span style={{ color: "#94a3b8" }}>Correct Abstention:</span>
                      <span style={{ fontWeight: 600, color: card.correctAbstentionRate === 100 ? "#10b981" : "#f59e0b" }}>{card.correctAbstentionRate}%</span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Strategic Decision & Recommendations Panel */}
          <div style={{ background: "rgba(15, 23, 42, 0.8)", border: "1px solid rgba(99, 102, 241, 0.2)", borderRadius: "12px", padding: "1.5rem", marginBottom: "2rem" }}>
            <h2 style={{ fontSize: "1.2rem", fontWeight: 700, margin: "0 0 1rem", color: "#e2e8f0", display: "flex", alignItems: "center", gap: "0.5rem" }}>
              🎯 CareerOS Model Architecture Recommendation
            </h2>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "1.25rem", marginBottom: "1.5rem" }}>
              <div style={{ background: "rgba(30, 41, 59, 0.5)", padding: "1rem", borderRadius: "8px", borderLeft: "4px solid #10b981" }}>
                <div style={{ fontSize: "0.75rem", color: "#94a3b8", textTransform: "uppercase", fontWeight: 700 }}>🏆 Top Accuracy & Grounding</div>
                <div style={{ fontSize: "1.1rem", fontWeight: 700, color: "#fff", marginTop: "0.2rem" }}>{data.recommendation.bestOverallModel}</div>
                <p style={{ fontSize: "0.8rem", color: "#94a3b8", margin: "0.4rem 0 0" }}>✅ 100% Critical Accuracy · 0% Hallucinations on complex multi-part visa/citizenship fields.</p>
              </div>

              <div style={{ background: "rgba(30, 41, 59, 0.5)", padding: "1rem", borderRadius: "8px", borderLeft: "4px solid #a855f7" }}>
                <div style={{ fontSize: "0.75rem", color: "#94a3b8", textTransform: "uppercase", fontWeight: 700 }}>🛡️ Recommended Daily Driver</div>
                <div style={{ fontSize: "1.1rem", fontWeight: 700, color: "#fff", marginTop: "0.2rem" }}>gemma3:12b</div>
                <p style={{ fontSize: "0.8rem", color: "#94a3b8", margin: "0.4rem 0 0" }}>✅ 97.1% verified accuracy · 8.8s inference · 100% critical safety with low VRAM footprint.</p>
              </div>

              <div style={{ background: "rgba(30, 41, 59, 0.5)", padding: "1rem", borderRadius: "8px", borderLeft: "4px solid #38bdf8" }}>
                <div style={{ fontSize: "0.75rem", color: "#94a3b8", textTransform: "uppercase", fontWeight: 700 }}>⚡ Fastest High-Throughput</div>
                <div style={{ fontSize: "1.1rem", fontWeight: 700, color: "#fff", marginTop: "0.2rem" }}>qwen2.5:3b (1.3s) / gemini-3.6-flash (0.8s)</div>
                <p style={{ fontSize: "0.8rem", color: "#94a3b8", margin: "0.4rem 0 0" }}>Sub-2s response times for high-volume standard application batches.</p>
              </div>

              <div style={{ background: "rgba(30, 41, 59, 0.5)", padding: "1rem", borderRadius: "8px", borderLeft: "4px solid #f59e0b" }}>
                <div style={{ fontSize: "0.75rem", color: "#94a3b8", textTransform: "uppercase", fontWeight: 700 }}>💰 Gemini Cloud Cost</div>
                <div style={{ fontSize: "1.1rem", fontWeight: 700, color: "#fff", marginTop: "0.2rem" }}>{data.recommendation.costProjections.costPer1000Apps} <span style={{ fontSize: "0.8rem", color: "#94a3b8", fontWeight: 400 }}>/ 1,000 apps</span></div>
                <p style={{ fontSize: "0.8rem", color: "#94a3b8", margin: "0.4rem 0 0" }}>100 apps: {data.recommendation.costProjections.costPer100Apps} · 10k apps: {data.recommendation.costProjections.costPer10000Apps}</p>
              </div>
            </div>

            <div style={{ fontSize: "0.88rem", lineHeight: "1.6", color: "#cbd5e1", background: "rgba(0,0,0,0.2)", padding: "1rem", borderRadius: "8px" }}>
              <strong>💡 Architecture Verdict:</strong> We recommend a <strong>Hybrid Local-First with Tiered Routing</strong> strategy:
              <br />
              • <strong>Tier 1 (Fast Form Fill)</strong>: <code>qwen2.5:3b</code> or <code>gemma3:12b</code> handles standard fields locally with zero API cost.
              <br />
              • <strong>Tier 2 (High-Stakes Gating)</strong>: Deterministic validation locks down Sponsorship, Citizenship, and Demographics.
              <br />
              • <strong>Tier 3 (Cloud Fallback & Long-Form Synthesis)</strong>: Escalate to <code>gemini-3.6-flash</code> for open-ended cover letters or ambiguous prompts.
            </div>
          </div>

          {/* Comparison Matrix Table */}
          <div style={{ background: "rgba(15, 23, 42, 0.8)", border: "1px solid rgba(255, 255, 255, 0.08)", borderRadius: "12px", padding: "1.5rem", marginBottom: "2rem" }}>
            <h2 style={{ fontSize: "1.2rem", fontWeight: 700, margin: "0 0 1rem" }}>
              📊 Detailed Head-to-Head Matrix
            </h2>
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem", textAlign: "left" }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid rgba(255, 255, 255, 0.1)", color: "#94a3b8" }}>
                    <th style={{ padding: "0.75rem 1rem" }}>Metric</th>
                    {data.leaderboard.map((m) => (
                      <th key={m.model} style={{ padding: "0.75rem 1rem", color: m.model === selectedModel ? "#818cf8" : "#f8fafc" }}>
                        {m.model}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  <tr style={{ borderBottom: "1px solid rgba(255, 255, 255, 0.05)" }}>
                    <td style={{ padding: "0.75rem 1rem", color: "#94a3b8" }}>Provider</td>
                    {data.leaderboard.map((m) => (
                      <td key={m.model} style={{ padding: "0.75rem 1rem", textTransform: "uppercase", fontWeight: 600, fontSize: "0.75rem" }}>
                        {m.provider}
                      </td>
                    ))}
                  </tr>
                  <tr style={{ borderBottom: "1px solid rgba(255, 255, 255, 0.05)" }}>
                    <td style={{ padding: "0.75rem 1rem", color: "#94a3b8" }}>🛡️ Critical Field Accuracy</td>
                    {data.leaderboard.map((m) => (
                      <td key={m.model} style={{ padding: "0.75rem 1rem", fontWeight: 700, color: m.criticalFieldAccuracy === 100 ? "#10b981" : "#f87171" }}>
                        {m.criticalFieldAccuracy}%
                      </td>
                    ))}
                  </tr>
                  <tr style={{ borderBottom: "1px solid rgba(255, 255, 255, 0.05)" }}>
                    <td style={{ padding: "0.75rem 1rem", color: "#94a3b8" }}>⚡ Average Latency</td>
                    {data.leaderboard.map((m) => (
                      <td key={m.model} style={{ padding: "0.75rem 1rem", fontWeight: 600, color: m.averageLatencyMs < 3000 ? "#38bdf8" : "#cbd5e1" }}>
                        {(m.averageLatencyMs / 1000).toFixed(1)}s <span style={{ fontSize: "0.7rem", color: "#64748b" }}>({m.averageLatencyMs}ms)</span>
                      </td>
                    ))}
                  </tr>
                  <tr style={{ borderBottom: "1px solid rgba(255, 255, 255, 0.05)" }}>
                    <td style={{ padding: "0.75rem 1rem", color: "#94a3b8" }}>Classification Accuracy</td>
                    {data.leaderboard.map((m) => (
                      <td key={m.model} style={{ padding: "0.75rem 1rem" }}>{m.classificationAccuracy}%</td>
                    ))}
                  </tr>
                  <tr style={{ borderBottom: "1px solid rgba(255, 255, 255, 0.05)" }}>
                    <td style={{ padding: "0.75rem 1rem", color: "#94a3b8" }}>Answer Accuracy</td>
                    {data.leaderboard.map((m) => (
                      <td key={m.model} style={{ padding: "0.75rem 1rem" }}>{m.answerAccuracy}%</td>
                    ))}
                  </tr>
                  <tr style={{ borderBottom: "1px solid rgba(255, 255, 255, 0.05)" }}>
                    <td style={{ padding: "0.75rem 1rem", color: "#94a3b8" }}>Hallucination Rate</td>
                    {data.leaderboard.map((m) => (
                      <td key={m.model} style={{ padding: "0.75rem 1rem", color: m.hallucinationRate === 0 ? "#10b981" : "#f87171" }}>
                        {m.hallucinationRate}%
                      </td>
                    ))}
                  </tr>
                  <tr style={{ borderBottom: "1px solid rgba(255, 255, 255, 0.05)" }}>
                    <td style={{ padding: "0.75rem 1rem", color: "#94a3b8" }}>Correct Abstention Rate</td>
                    {data.leaderboard.map((m) => (
                      <td key={m.model} style={{ padding: "0.75rem 1rem", color: m.correctAbstentionRate === 100 ? "#10b981" : "#f59e0b" }}>
                        {m.correctAbstentionRate}%
                      </td>
                    ))}
                  </tr>
                  <tr style={{ borderBottom: "1px solid rgba(255, 255, 255, 0.05)" }}>
                    <td style={{ padding: "0.75rem 1rem", color: "#94a3b8" }}>Estimated Cost / 1,000 Apps</td>
                    {data.leaderboard.map((m) => (
                      <td key={m.model} style={{ padding: "0.75rem 1rem", color: m.provider === "ollama" ? "#10b981" : "#38bdf8", fontWeight: 600 }}>
                        {m.provider === "ollama" ? "$0.00 (Local)" : `$${m.estimatedCostPer1000Apps.toFixed(3)}`}
                      </td>
                    ))}
                  </tr>
                  <tr style={{ background: "rgba(30, 41, 59, 0.8)", borderTop: "2px solid rgba(255, 255, 255, 0.1)" }}>
                    <td style={{ padding: "1rem", fontWeight: 800, fontSize: "0.95rem" }}>🏆 Overall Benchmark Score</td>
                    {data.leaderboard.map((m) => (
                      <td key={m.model} style={{ padding: "1rem", fontWeight: 800, fontSize: "1.1rem", color: m.overallBenchmarkScore >= 90 ? "#10b981" : m.overallBenchmarkScore >= 75 ? "#f59e0b" : "#ef4444" }}>
                        {m.overallBenchmarkScore}%
                      </td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          {/* Question Drilldown */}
          <div style={{ background: "rgba(15, 23, 42, 0.8)", border: "1px solid rgba(255, 255, 255, 0.08)", borderRadius: "12px", padding: "1.5rem" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.25rem" }}>
              <div>
                <h2 style={{ fontSize: "1.1rem", fontWeight: 700, margin: 0 }}>
                  🔍 Question Drilldown & Verification Inspector ({currentScorecard?.model})
                </h2>
                <span style={{ fontSize: "0.8rem", color: "#94a3b8" }}>Inspect individual answer decisions, latency, and guardrail validations</span>
              </div>

              <div style={{ display: "flex", gap: "0.5rem" }}>
                {[
                  { id: "all", label: "All Questions" },
                  { id: "critical", label: "🛡️ Critical Fields" },
                  { id: "errors", label: "❌ Mismatches" },
                  { id: "hallucinations", label: "⚠️ Hallucinations" },
                ].map((tab) => (
                  <button
                    key={tab.id}
                    onClick={() => setFilterCategory(tab.id)}
                    style={{
                      padding: "0.4rem 0.8rem",
                      borderRadius: "6px",
                      fontSize: "0.75rem",
                      fontWeight: 600,
                      background: filterCategory === tab.id ? "#6366f1" : "rgba(255,255,255,0.06)",
                      color: filterCategory === tab.id ? "#fff" : "#94a3b8",
                      border: "none",
                      cursor: "pointer",
                    }}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
              {filteredResults.map((item) => {
                const latencySec = (item.latencyMs / 1000).toFixed(1);
                return (
                  <div
                    key={item.testId}
                    style={{
                      background: "rgba(30, 41, 59, 0.4)",
                      border: `1px solid ${!item.correctAnswer || item.hallucinated ? "rgba(239, 68, 68, 0.4)" : "rgba(255, 255, 255, 0.05)"}`,
                      borderRadius: "10px",
                      padding: "1rem",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "0.5rem" }}>
                      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                        <span style={{ fontSize: "0.75rem", padding: "3px 8px", borderRadius: "6px", background: item.isCritical ? "rgba(239, 68, 68, 0.2)" : "rgba(99, 102, 241, 0.2)", color: item.isCritical ? "#f87171" : "#818cf8", fontWeight: 700 }}>
                          {item.isCritical ? "🛡️ CRITICAL" : `📋 ${item.category}`}
                        </span>
                        <strong style={{ fontSize: "0.92rem", color: "#f8fafc" }}>{item.question}</strong>
                      </div>

                      <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
                        {item.correctAnswer ? (
                          <span style={{ fontSize: "0.8rem", color: "#10b981", fontWeight: 700, background: "rgba(16, 185, 129, 0.1)", padding: "2px 8px", borderRadius: "6px" }}>
                            ✅ Match
                          </span>
                        ) : (
                          <span style={{ fontSize: "0.8rem", color: "#f87171", fontWeight: 700, background: "rgba(239, 68, 68, 0.1)", padding: "2px 8px", borderRadius: "6px" }}>
                            ❌ Mismatch
                          </span>
                        )}
                        <span style={{ fontSize: "0.75rem", color: item.latencyMs < 3000 ? "#38bdf8" : "#94a3b8", fontWeight: 600 }}>
                          ⚡ {latencySec}s
                        </span>
                      </div>
                    </div>

                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem", fontSize: "0.82rem", marginTop: "0.6rem" }}>
                      <div style={{ background: "rgba(0,0,0,0.25)", padding: "0.7rem", borderRadius: "8px", border: "1px solid rgba(255,255,255,0.03)" }}>
                        <div style={{ color: "#94a3b8", fontSize: "0.7rem", fontWeight: 600, marginBottom: "0.25rem" }}>🎯 EXPECTED GROUND TRUTH</div>
                        <div style={{ color: "#10b981", fontWeight: 600 }}>{item.expectedAnswer}</div>
                        <div style={{ color: "#64748b", fontSize: "0.72rem", marginTop: "0.25rem" }}>Type: {item.expectedClassification}</div>
                      </div>

                      <div style={{ background: "rgba(0,0,0,0.25)", padding: "0.7rem", borderRadius: "8px", border: `1px solid ${item.correctAnswer ? "rgba(255,255,255,0.03)" : "rgba(239,68,68,0.2)"}` }}>
                        <div style={{ color: "#94a3b8", fontSize: "0.7rem", fontWeight: 600, marginBottom: "0.25rem" }}>🤖 ACTUAL ANSWER ({selectedModel})</div>
                        <div style={{ color: item.correctAnswer ? "#e2e8f0" : "#f87171", fontWeight: 600 }}>{item.actualAnswer || "(empty / unparsed)"}</div>
                        <div style={{ color: "#64748b", fontSize: "0.72rem", marginTop: "0.25rem" }}>Type: {item.actualClassification}</div>
                      </div>
                    </div>

                    {item.hallucinated && (
                      <div style={{ marginTop: "0.5rem", fontSize: "0.78rem", color: "#f87171", background: "rgba(239, 68, 68, 0.1)", padding: "6px 10px", borderRadius: "6px", border: "1px solid rgba(239, 68, 68, 0.2)" }}>
                        ⚠️ <strong>Hallucination Flagged:</strong> Model invented ungrounded details or failed required abstention.
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </>
      ) : (
        <div style={{ padding: "3rem", textAlign: "center", color: "#94a3b8" }}>
          <p>No benchmark results loaded yet. Click <strong>Refresh Results</strong> above to load recorded evaluations.</p>
        </div>
      )}
    </div>
  );
}
