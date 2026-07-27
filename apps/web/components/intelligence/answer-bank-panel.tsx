"use client";

import { useCallback, useEffect, useState } from "react";
import { getClientApiBaseUrl } from "@/lib/api";

export function AnswerBankPanel() {
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [question, setQuestion] = useState("Why do you want to work here?");
  const [company, setCompany] = useState("");
  const [role, setRole] = useState("");
  const [result, setResult] = useState("");

  const load = useCallback(async () => {
    const res = await fetch(`${getClientApiBaseUrl()}/intelligence/answers/bank`, { cache: "no-store" });
    if (res.ok) {
      const payload = (await res.json()) as { answers: Record<string, unknown> };
      setAnswers(payload.answers || {});
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function lookup(event: React.FormEvent) {
    event.preventDefault();
    const res = await fetch(`${getClientApiBaseUrl()}/intelligence/answers/lookup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, company, roleTitle: role }),
    });
    if (res.ok) {
      const payload = (await res.json()) as { answer: string };
      setResult(payload.answer || "(no match — add to answers.yaml)");
    }
  }

  const customCount = Object.keys(answers).length;

  return (
    <div className="intelligence-panel">
      <section className="workflow-panel">
        <span className="toc-card-kicker">Answer Bank</span>
        <h2>Screening question engine</h2>
        <p className="muted">{customCount} custom answers in answers.yaml · company-aware fallbacks for common ATS questions</p>
        <form className="target-jobs-filters" onSubmit={lookup}>
          <label>Question<textarea value={question} onChange={(e) => setQuestion(e.target.value)} rows={2} /></label>
          <label>Company<input value={company} onChange={(e) => setCompany(e.target.value)} placeholder="stripe" /></label>
          <label>Role<input value={role} onChange={(e) => setRole(e.target.value)} placeholder="Product Manager" /></label>
          <button type="submit" className="btn btn-sm btn-primary">Generate answer</button>
        </form>
        {result ? <pre className="intelligence-answer-preview">{result}</pre> : null}
      </section>
    </div>
  );
}
