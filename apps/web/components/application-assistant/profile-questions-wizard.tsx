"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { SidePanelPortal } from "@/components/side-panel-portal";
import { submitFieldAnswers, submitUnifiedFieldAnswers } from "@/lib/application-assistant-api";
import { optionsForQuestion, PROFILE_KEY_LABELS, isConsentQuestion, isFreeTextApplicationQuestion } from "@/lib/profile-form-options";
import { formatQuestionContext, formatQuestionTitle, isWizardQuestion } from "@/lib/question-display";

export type PendingQuestion = {
  fieldId: string;
  label: string;
  normalizedKey: string;
  fieldType: string;
  required: boolean;
  options: string[];
  suggestedProfileKey?: string | null;
  storageHint?: string;
  helpText?: string;
  section?: string;
  category?: "profile" | "application";
  displayTitle?: string;
  displayContext?: string;
  wizardEligible?: boolean;
  canonicalId?: string;
  variantLabels?: string[];
  applicationCount?: number;
  companyNames?: string[];
  occurrenceCount?: number;
  targets?: {
    appId: string;
    fieldId: string;
    normalizedKey?: string;
    label?: string;
    companyName?: string;
  }[];
};

type WizardStep =
  | { kind: "intro" }
  | { kind: "question"; field: PendingQuestion; index: number };

type ProfileQuestionsWizardProps = {
  open: boolean;
  onClose: () => void;
  mode?: "single" | "unified";
  layout?: "modal" | "panel";
  loading?: boolean;
  loadingMessage?: string;
  appId?: string;
  companyName?: string;
  roleTitle?: string;
  pending?: PendingQuestion[];
  profilePending?: PendingQuestion[];
  applicationPending?: PendingQuestion[];
  profileKeysMissing?: string[];
  applicationCount?: number;
  rawOccurrenceCount?: number;
  onComplete: (result: {
    readyForBrowser: boolean;
    reprepStarted?: boolean;
    pendingCount?: number;
    savedCount?: number;
  }) => void;
};

function WizardShell({
  layout,
  open,
  onClose,
  ariaLabelledBy,
  children,
}: {
  layout: "modal" | "panel";
  open: boolean;
  onClose: () => void;
  ariaLabelledBy?: string;
  children: ReactNode;
}) {
  if (!open) return null;

  if (layout === "panel") {
    return (
      <SidePanelPortal
        open={open}
        onClose={onClose}
        backdropAriaLabel="Close questions panel"
        ariaLabelledBy={ariaLabelledBy}
      >
        {children}
      </SidePanelPortal>
    );
  }

  return (
    <div className="aa-wizard-overlay" role="presentation" onClick={onClose}>
      <div
        className="aa-wizard-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={ariaLabelledBy}
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}

function OptionPicker({
  options,
  value,
  onChange,
}: {
  options: string[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="aa-wizard-options" role="listbox" aria-label="Choose an answer">
      {options.map((opt) => {
        const selected = value === opt;
        return (
          <button
            key={opt}
            type="button"
            role="option"
            aria-selected={selected}
            className={`aa-wizard-option${selected ? " aa-wizard-option--selected" : ""}`}
            onClick={() => onChange(opt)}
          >
            {opt}
          </button>
        );
      })}
    </div>
  );
}

function QuestionInput({
  field,
  value,
  onChange,
  inputRef,
}: {
  field: PendingQuestion;
  value: string;
  onChange: (value: string) => void;
  inputRef?: React.RefObject<HTMLInputElement | HTMLTextAreaElement | null>;
}) {
  if (isConsentQuestion(field)) {
    const checked = /^(yes|true|checked|on|1)$/i.test(value.trim());
    return (
      <label className="aa-wizard-checkbox">
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e.target.checked ? "yes" : "")}
        />
        <span>I understand and agree</span>
      </label>
    );
  }

  const options = optionsForQuestion(field);
  if (options.length > 0) {
    return (
      <OptionPicker
        options={options}
        value={value}
        onChange={onChange}
      />
    );
  }

  if (isFreeTextApplicationQuestion(field)) {
    const multi = /languages|fluent/i.test(`${field.label} ${field.displayTitle || ""}`);
    return (
      <textarea
        ref={inputRef as React.RefObject<HTMLTextAreaElement | null>}
        className="aa-wizard-input aa-wizard-textarea"
        value={value}
        placeholder={multi ? "e.g. English, Spanish" : "e.g. Seattle, San Francisco, Remote"}
        rows={multi ? 3 : 2}
        onChange={(e) => onChange(e.target.value)}
        onMouseDown={(e) => e.stopPropagation()}
        onClick={(e) => e.stopPropagation()}
      />
    );
  }

  if (/^(checkbox|boolean)$/i.test(field.fieldType || "")) {
    const checked = /^(yes|true|checked|on|1)$/i.test(value.trim());
    return (
      <label className="aa-wizard-checkbox">
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e.target.checked ? "yes" : "")}
        />
        <span>I consent / Yes</span>
      </label>
    );
  }
  if (/^(select|select-one|select-multiple|combobox|listbox|radio)$/i.test(field.fieldType || "")) {
    return (
      <p className="muted aa-wizard-input-hint">
        This field is a dropdown on the employer form, but options were not captured yet.
        Re-run prep or type the exact choice from the job application.
      </p>
    );
  }
  return (
    <input
      ref={inputRef as React.RefObject<HTMLInputElement | null>}
      type="text"
      className="aa-wizard-input"
      value={value}
      placeholder="Your answer"
      onChange={(e) => onChange(e.target.value)}
      onMouseDown={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
    />
  );
}

export function ProfileQuestionsWizard({
  open,
  onClose,
  mode = "single",
  layout = "panel",
  loading = false,
  loadingMessage = "Checking your profile with Qwen…",
  appId = "",
  companyName = "",
  roleTitle = "",
  pending = [],
  profilePending = [],
  applicationPending = [],
  profileKeysMissing = [],
  applicationCount = 0,
  rawOccurrenceCount = 0,
  onComplete,
}: ProfileQuestionsWizardProps) {
  const isUnified = mode === "unified";
  const answerKey = (field: PendingQuestion) => field.canonicalId || field.fieldId;

  const orderedQuestions = useMemo(() => {
    const fromSplit = [...profilePending, ...applicationPending];
    const raw = fromSplit.length > 0 ? fromSplit : pending;
    return raw.filter(isWizardQuestion);
  }, [profilePending, applicationPending, pending]);

  const steps: WizardStep[] = useMemo(() => {
    const list: WizardStep[] = [];
    if (orderedQuestions.length > 1) {
      list.push({ kind: "intro" });
    }
    orderedQuestions.forEach((field, index) => {
      list.push({ kind: "question", field, index });
    });
    return list;
  }, [orderedQuestions]);

  const [stepIndex, setStepIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const questionInputRef = useRef<HTMLInputElement | HTMLTextAreaElement | null>(null);

  useEffect(() => {
    if (open) {
      setStepIndex(0);
      setAnswers({});
      setError("");
    }
  }, [open, appId, mode]);

  const currentStep = steps[stepIndex];
  const currentQuestion = currentStep?.kind === "question" ? currentStep.field : null;

  useEffect(() => {
    if (!open || loading || !currentQuestion) return;
    const id = window.requestAnimationFrame(() => {
      questionInputRef.current?.focus();
    });
    return () => window.cancelAnimationFrame(id);
  }, [open, loading, stepIndex, currentQuestion?.fieldId]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  useEffect(() => {
    if (!open || loading || orderedQuestions.length > 0) return;
    const hadRawFields = pending.length > 0 || profilePending.length > 0 || applicationPending.length > 0;
    if (hadRawFields) {
      onComplete({ readyForBrowser: true, pendingCount: 0 });
      onClose();
    }
  }, [
    open,
    loading,
    orderedQuestions.length,
    pending.length,
    profilePending.length,
    applicationPending.length,
    onClose,
    onComplete,
  ]);

  const totalSteps = steps.length;
  const questionSteps = steps.filter((s) => s.kind === "question").length;
  const currentAnswer = currentQuestion ? answers[answerKey(currentQuestion)]?.trim() || "" : "";
  const isLastStep = stepIndex >= totalSteps - 1;

  async function handleSaveAll() {
    if (saving) return;
    const missing = orderedQuestions.filter((f) => !answers[answerKey(f)]?.trim());
    if (missing.length) {
      setError(`Answer all ${orderedQuestions.length} questions (${missing.length} remaining).`);
      return;
    }
    setSaving(true);
    setError("");
    try {
      if (isUnified) {
        const submissions = orderedQuestions.map((field) => ({
          canonicalId: answerKey(field),
          normalizedKey: field.normalizedKey,
          profileKey: field.suggestedProfileKey || undefined,
          value: answers[answerKey(field)].trim(),
          targets: field.targets || [],
        }));
        const result = await submitUnifiedFieldAnswers(submissions);
        onClose();
        void onComplete({
          readyForBrowser: (result.readyApplicationIds?.length || 0) > 0 || orderedQuestions.length === submissions.length,
          reprepStarted: Boolean(result.repreppedApplicationIds?.length),
        });
      } else {
        const submissions = orderedQuestions.map((field) => ({
          fieldId: field.fieldId || answerKey(field),
          normalizedKey: field.normalizedKey,
          profileKey: field.suggestedProfileKey || undefined,
          value: answers[answerKey(field)].trim(),
        }));
        const result = await submitFieldAnswers(appId, submissions);
        onClose();
        void onComplete({
          readyForBrowser: Boolean(result.readyForBrowser),
          reprepStarted: Boolean(result.reprepStarted),
          pendingCount: result.pendingCount,
          savedCount: result.savedCount,
        });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save answers");
    } finally {
      setSaving(false);
    }
  }

  function handleNext() {
    if (!currentStep) {
      setError("No questions loaded — close and try again.");
      return;
    }
    if (currentStep.kind === "intro") {
      setStepIndex((i) => i + 1);
      return;
    }
    if (!currentAnswer) {
      setError("Choose or enter an answer to continue.");
      return;
    }
    setError("");
    if (isLastStep) {
      void handleSaveAll();
      return;
    }
    setStepIndex((i) => i + 1);
  }

  if (!open) return null;

  const shellClass = layout === "panel" ? "aa-wizard-panel-inner" : "";

  if (loading) {
    return (
      <WizardShell layout={layout} open={open} onClose={onClose}>
        <div className={shellClass}>
          <header className="aa-wizard-header">
            <div>
              <p className="aa-wizard-eyebrow">
                {isUnified
                  ? `${applicationCount} application${applicationCount === 1 ? "" : "s"}`
                  : `${companyName} — ${roleTitle}`}
              </p>
              <h2>Profile questions</h2>
            </div>
            <button type="button" className="aa-wizard-close" onClick={onClose} aria-label="Close">
              ×
            </button>
          </header>
          <div className="aa-wizard-body aa-wizard-body--loading" role="status" aria-live="polite">
            <span className="aa-wizard-loading-spinner" aria-hidden />
            <p><strong>{loadingMessage}</strong></p>
            <p className="muted">
              Qwen compares each question to your saved profile and answer library — even when wording differs.
            </p>
          </div>
        </div>
      </WizardShell>
    );
  }

  if (!orderedQuestions.length) {
    return (
      <WizardShell layout={layout} open={open} onClose={onClose}>
        <div className={shellClass}>
          <header className="aa-wizard-header">
            <div>
              <p className="aa-wizard-eyebrow">{companyName} — {roleTitle}</p>
              <h2>Complete your application profile</h2>
            </div>
            <button type="button" className="aa-wizard-close" onClick={onClose} aria-label="Close">
              ×
            </button>
          </header>
          <div className="aa-wizard-body">
            <p className="muted">No profile questions — you can open the browser when prep finishes.</p>
          </div>
        </div>
      </WizardShell>
    );
  }

  const profileHighlight = profileKeysMissing.join(",");
  const progressPct = totalSteps > 1 ? Math.round(((stepIndex + 1) / totalSteps) * 100) : 100;

  return (
    <WizardShell layout={layout} open={open} onClose={onClose} ariaLabelledBy="aa-wizard-title">
      <div className={shellClass}>
        <header className="aa-wizard-header">
          <div>
            <p className="aa-wizard-eyebrow">
              {isUnified
                ? `${applicationCount} application${applicationCount === 1 ? "" : "s"} · unified profile questions`
                : `${companyName} — ${roleTitle}`}
            </p>
            <h2 id="aa-wizard-title">
              {isUnified ? "Answer once for all applications" : "Complete your application profile"}
            </h2>
          </div>
          <button type="button" className="aa-wizard-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </header>

        <div className="aa-wizard-progress" aria-hidden>
          <span className="aa-wizard-progress-bar" style={{ width: `${progressPct}%` }} />
        </div>
        <p className="aa-wizard-progress-label">
          Step {stepIndex + 1} of {totalSteps}
          {currentStep?.kind === "question" ? ` · Question ${currentStep.index + 1} of ${questionSteps}` : ""}
        </p>

        <div className="aa-wizard-body">
          {currentStep?.kind === "intro" && (
            <>
              <p>
                {isUnified ? (
                  <>
                    AI normalized <strong>{rawOccurrenceCount || pending.length} raw question{(rawOccurrenceCount || pending.length) === 1 ? "" : "s"}</strong>
                    {" "}from {applicationCount} application{applicationCount === 1 ? "" : "s"} into{" "}
                    <strong>{orderedQuestions.length} unique question{orderedQuestions.length === 1 ? "" : "s"}</strong>.
                    Answer each once — CareerOS applies it everywhere it matches.
                  </>
                ) : (
                  <>
                    Prep found <strong>{orderedQuestions.length} question{orderedQuestions.length === 1 ? "" : "s"}</strong> CareerOS will not guess.
                    Answers are saved to your profile and reused on future applications.
                  </>
                )}
              </p>
              <ul className="aa-wizard-intro-list">
                {profilePending.length > 0 && (
                  <li>
                    <strong>{profilePending.length} profile question{profilePending.length === 1 ? "" : "s"}</strong>
                    {" — saved to your profile and reused on future applications."}
                  </li>
                )}
                {applicationPending.length > 0 && (
                  <li>
                    <strong>{applicationPending.length} application-specific</strong>
                    {isUnified
                      ? " — saved to your answer library and reused on similar employers."
                      : ` — saved for ${companyName} and similar employers.`}
                  </li>
                )}
              </ul>
              {profileKeysMissing.length > 0 && (
                <p className="muted">
                  Profile fields:{" "}
                  {profileKeysMissing.map((k) => PROFILE_KEY_LABELS[k] || k).join(", ")}.
                  {" "}
                  <Link href={`/profile?highlight=${encodeURIComponent(profileHighlight)}`} className="aa-wizard-link">
                    View on Profile page
                  </Link>
                </p>
              )}
            </>
          )}

          {currentQuestion && (() => {
            const questionTitle = formatQuestionTitle(currentQuestion);
            const questionContext = formatQuestionContext(currentQuestion);
            return (
            <>
              <span className={`aa-wizard-badge aa-wizard-badge--${currentQuestion.category || "application"}`}>
                {currentQuestion.category === "profile" ? "Saved to profile forever" : "Application-specific"}
              </span>
              <div className="aa-wizard-question">
                <span className="aa-wizard-question-label">
                  {questionTitle}
                  {currentQuestion.required ? <span className="aa-required">*</span> : null}
                </span>
                {questionContext ? (
                  <span className="muted aa-wizard-question-meta">{questionContext}</span>
                ) : null}
                {currentQuestion.suggestedProfileKey && (
                  <span className="muted aa-wizard-question-meta">
                    Saved as: {PROFILE_KEY_LABELS[currentQuestion.suggestedProfileKey] || currentQuestion.suggestedProfileKey}
                  </span>
                )}
                {currentQuestion.variantLabels && currentQuestion.variantLabels.length > 1 ? (
                  <span className="muted aa-wizard-question-meta">
                    Also asked as: {currentQuestion.variantLabels.slice(0, 4).map((v) => `“${v}”`).join(", ")}
                    {currentQuestion.variantLabels.length > 4 ? "…" : ""}
                    {currentQuestion.applicationCount && currentQuestion.applicationCount > 1
                      ? ` · ${currentQuestion.applicationCount} applications`
                      : ""}
                  </span>
                ) : null}
                <QuestionInput
                  field={currentQuestion}
                  value={answers[answerKey(currentQuestion)] || ""}
                  onChange={(v) => setAnswers((prev) => ({ ...prev, [answerKey(currentQuestion)]: v }))}
                  inputRef={questionInputRef}
                />
              </div>
            </>
            );
          })()}

          {error ? <p className="aa-error">{error}</p> : null}
        </div>

        <footer className="aa-wizard-footer">
          <button
            type="button"
            className="btn-secondary btn-sm"
            onClick={() => setStepIndex((i) => Math.max(0, i - 1))}
            disabled={stepIndex === 0 || saving}
          >
            Back
          </button>
          <button
            type="button"
            className="btn-primary btn-sm"
            onClick={() => void handleNext()}
            disabled={saving || !currentStep || (currentStep.kind === "question" && !currentAnswer)}
          >
            {saving
              ? "Saving…"
              : isLastStep
                ? "Save to profile"
                : "Next"}
          </button>
        </footer>
      </div>
    </WizardShell>
  );
}
