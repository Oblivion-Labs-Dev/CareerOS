"use client";

import { useEffect, useState } from "react";
import { getClientApiBaseUrl } from "@/lib/api";

export type OnboardingQuestion = {
  key: string;
  label: string;
  type: "text" | "number" | "select" | "boolean";
  options?: string[];
  required?: boolean;
  help?: string;
};

export type OnboardingSection = {
  id: string;
  title: string;
  description: string;
  questions: OnboardingQuestion[];
};

type Props = {
  open: boolean;
  onClose: () => void;
  onSaved?: () => void;
};

export function OnboardingWizardModal({ open, onClose, onSaved }: Props) {
  const [sections, setSections] = useState<OnboardingSection[]>([]);
  const [answers, setAnswers] = useState<Record<string, any>>({});
  const [currentStep, setCurrentStep] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savedSuccess, setSavedSuccess] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    setError("");
    setSavedSuccess(false);

    fetch(`${getClientApiBaseUrl()}/api/onboarding/questions`)
      .then((res) => {
        if (!res.ok) throw new Error("Failed to load onboarding questions");
        return res.json();
      })
      .then((data) => {
        if (data.sections) {
          setSections(data.sections);
        }
        if (data.currentValues) {
          setAnswers(data.currentValues);
        }
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Could not load onboarding questions");
      })
      .finally(() => {
        setLoading(false);
      });
  }, [open]);

  if (!open) return null;

  const currentSection = sections[currentStep];
  const isLastStep = currentStep === sections.length - 1;

  const handleChange = (key: string, value: any) => {
    setAnswers((prev) => ({ ...prev, [key]: value }));
  };

  const handleNext = () => {
    if (currentStep < sections.length - 1) {
      setCurrentStep((prev) => prev + 1);
    }
  };

  const handlePrev = () => {
    if (currentStep > 0) {
      setCurrentStep((prev) => prev - 1);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setError("");
    try {
      const res = await fetch(`${getClientApiBaseUrl()}/api/onboarding/answers`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answers }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Failed to save answers");
      }
      setSavedSuccess(true);
      onSaved?.();
      setTimeout(() => {
        onClose();
      }, 1500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error saving answers");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="aa-wizard-overlay"
      role="presentation"
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        backgroundColor: "rgba(0, 0, 0, 0.75)",
        backdropFilter: "blur(6px)",
        zIndex: 1000,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "1rem",
      }}
    >
      <div
        className="workflow-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="onboarding-wizard-title"
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "100%",
          maxWidth: "680px",
          maxHeight: "90vh",
          display: "flex",
          flexDirection: "column",
          borderRadius: "var(--radius-lg, 16px)",
          boxShadow: "0 20px 40px rgba(0, 0, 0, 0.4)",
          overflow: "hidden",
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: "1.25rem 1.5rem",
            borderBottom: "1px solid var(--card-edge, rgba(255, 255, 255, 0.1))",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <div>
            <span
              className="toc-card-kicker"
              style={{
                fontSize: "0.75rem",
                textTransform: "uppercase",
                letterSpacing: "0.05em",
                color: "#60a5fa",
              }}
            >
              Candidate Setup Wizard
            </span>
            <h2 id="onboarding-wizard-title" style={{ margin: "0.25rem 0 0", fontSize: "1.25rem" }}>
              Screening Questionnaire
            </h2>
          </div>
          <button
            type="button"
            className="btn btn-sm"
            onClick={onClose}
            aria-label="Close setup wizard"
            style={{ minWidth: "2rem", padding: "0.25rem 0.5rem" }}
          >
            ✕
          </button>
        </div>

        {/* Step Progress Bar */}
        {sections.length > 0 && !loading && (
          <div
            style={{
              padding: "0.75rem 1.5rem",
              background: "rgba(255, 255, 255, 0.02)",
              borderBottom: "1px solid var(--card-edge, rgba(255, 255, 255, 0.05))",
              display: "flex",
              alignItems: "center",
              gap: "0.5rem",
            }}
          >
            {sections.map((sec, idx) => (
              <button
                key={sec.id}
                type="button"
                onClick={() => setCurrentStep(idx)}
                style={{
                  flex: 1,
                  height: "4px",
                  borderRadius: "2px",
                  border: "none",
                  cursor: "pointer",
                  transition: "background 0.2s",
                  background:
                    idx === currentStep
                      ? "#3b82f6"
                      : idx < currentStep
                      ? "rgba(59, 130, 246, 0.5)"
                      : "rgba(255, 255, 255, 0.1)",
                }}
                title={sec.title}
              />
            ))}
            <span style={{ fontSize: "0.75rem", color: "#94a3b8", marginLeft: "0.5rem", whiteSpace: "nowrap" }}>
              Step {currentStep + 1} of {sections.length}
            </span>
          </div>
        )}

        {/* Body Content */}
        <div
          style={{
            padding: "1.5rem",
            overflowY: "auto",
            flex: 1,
            display: "flex",
            flexDirection: "column",
            gap: "1.25rem",
          }}
        >
          {loading && <p className="muted">Loading screening questions…</p>}

          {error && (
            <div
              style={{
                padding: "0.75rem 1rem",
                borderRadius: "8px",
                background: "rgba(239, 68, 68, 0.1)",
                border: "1px solid rgba(239, 68, 68, 0.3)",
                color: "#f87171",
                fontSize: "0.875rem",
              }}
            >
              {error}
            </div>
          )}

          {savedSuccess && (
            <div
              style={{
                padding: "1rem",
                borderRadius: "8px",
                background: "rgba(34, 197, 94, 0.1)",
                border: "1px solid rgba(34, 197, 94, 0.3)",
                color: "#4ade80",
                display: "flex",
                alignItems: "center",
                gap: "0.75rem",
                fontSize: "0.95rem",
              }}
            >
              <span>🎉</span>
              <div>
                <strong>Profile Successfully Configured!</strong>
                <p style={{ margin: "0.25rem 0 0", fontSize: "0.825rem", color: "#86efac" }}>
                  All screening questions have been validated. Autopilot is ready for live submissions.
                </p>
              </div>
            </div>
          )}

          {!loading && currentSection && !savedSuccess && (
            <div>
              <div style={{ marginBottom: "1.25rem" }}>
                <h3 style={{ margin: 0, fontSize: "1.1rem", color: "#f8fafc" }}>{currentSection.title}</h3>
                <p style={{ margin: "0.25rem 0 0", fontSize: "0.85rem", color: "#94a3b8" }}>
                  {currentSection.description}
                </p>
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
                {currentSection.questions.map((q) => {
                  const val = answers[q.key];

                  return (
                    <div
                      key={q.key}
                      style={{
                        padding: "0.85rem",
                        borderRadius: "8px",
                        background: "rgba(255, 255, 255, 0.03)",
                        border: "1px solid rgba(255, 255, 255, 0.06)",
                      }}
                    >
                      <label style={{ display: "block", marginBottom: "0.4rem", fontSize: "0.875rem", fontWeight: 500 }}>
                        {q.label}
                        {q.required && <span style={{ color: "#f87171", marginLeft: "0.25rem" }}>*</span>}
                      </label>
                      {q.help && (
                        <p style={{ margin: "0 0 0.5rem", fontSize: "0.75rem", color: "#94a3b8" }}>{q.help}</p>
                      )}

                      {q.type === "select" && q.options ? (
                        <select
                          className="control"
                          value={val ?? ""}
                          onChange={(e) => handleChange(q.key, e.target.value)}
                          style={{
                            width: "100%",
                            padding: "0.5rem 0.75rem",
                            borderRadius: "6px",
                            background: "var(--control-bg, #0c1420)",
                            color: "#f8fafc",
                            border: "1px solid var(--card-edge, rgba(255, 255, 255, 0.15))",
                          }}
                        >
                          <option value="">-- Select an option --</option>
                          {q.options.map((opt) => (
                            <option key={opt} value={opt}>
                              {opt}
                            </option>
                          ))}
                        </select>
                      ) : q.type === "boolean" ? (
                        <div style={{ display: "flex", gap: "0.75rem" }}>
                          {["Yes", "No"].map((choice) => {
                            const boolVal = choice === "Yes";
                            const isSelected = val === boolVal || val === choice;
                            return (
                              <button
                                key={choice}
                                type="button"
                                className={`btn btn-sm ${isSelected ? "btn-primary" : ""}`}
                                onClick={() => handleChange(q.key, boolVal)}
                                style={{ minWidth: "80px" }}
                              >
                                {choice}
                              </button>
                            );
                          })}
                        </div>
                      ) : (
                        <input
                          type={q.type === "number" ? "number" : "text"}
                          className="control"
                          value={val ?? ""}
                          onChange={(e) =>
                            handleChange(q.key, q.type === "number" ? Number(e.target.value) : e.target.value)
                          }
                          placeholder={q.label}
                          style={{
                            width: "100%",
                            padding: "0.5rem 0.75rem",
                            borderRadius: "6px",
                            background: "var(--control-bg, #0c1420)",
                            color: "#f8fafc",
                            border: "1px solid var(--card-edge, rgba(255, 255, 255, 0.15))",
                          }}
                        />
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* Footer Navigation */}
        <div
          style={{
            padding: "1rem 1.5rem",
            borderTop: "1px solid var(--card-edge, rgba(255, 255, 255, 0.1))",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            background: "rgba(0, 0, 0, 0.2)",
          }}
        >
          <button
            type="button"
            className="btn btn-sm"
            onClick={handlePrev}
            disabled={currentStep === 0 || saving || savedSuccess}
          >
            ← Previous
          </button>

          <div style={{ display: "flex", gap: "0.75rem" }}>
            <button
              type="button"
              className="btn btn-sm"
              onClick={handleSave}
              disabled={saving || savedSuccess}
              title="Save current answers"
            >
              {saving ? "Saving…" : "Save Progress"}
            </button>

            {!isLastStep ? (
              <button
                type="button"
                className="btn btn-sm btn-primary"
                onClick={handleNext}
                disabled={saving || savedSuccess}
              >
                Next →
              </button>
            ) : (
              <button
                type="button"
                className="btn btn-sm btn-primary"
                onClick={handleSave}
                disabled={saving || savedSuccess}
              >
                {saving ? "Saving…" : "Complete Setup ✓"}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
