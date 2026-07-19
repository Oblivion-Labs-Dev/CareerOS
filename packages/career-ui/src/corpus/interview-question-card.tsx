"use client";

import { Badge, cn } from "@arsenal/ui";
import type { InterviewQuestionData } from "./types";

const DIFFICULTY_VARIANT = {
  foundation: "planned",
  intermediate: "progress",
  advanced: "p1",
  expert: "p0",
} as const;

const STATUS_LABEL = {
  unanswered: "Unanswered",
  draft: "Draft answer",
  prepared: "Prepared",
  practiced: "Practiced",
} as const;

export interface InterviewQuestionCardProps {
  question: InterviewQuestionData;
  mode?: "study" | "practice" | "flashcard";
  revealAnswer?: boolean;
  onReveal?: () => void;
  onSelectRecord?: () => void;
  className?: string;
}

export function InterviewQuestionCard({
  question,
  mode = "study",
  revealAnswer = false,
  onReveal,
  onSelectRecord,
  className,
}: InterviewQuestionCardProps) {
  const showAnswer = mode === "study" || revealAnswer;

  return (
    <article
      className={cn(
        "rounded-xl border border-arsenal-border bg-arsenal-surface p-4",
        className,
      )}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge variant={DIFFICULTY_VARIANT[question.difficulty]}>{question.difficulty}</Badge>
        <Badge variant="planned">{question.interviewType}</Badge>
        <Badge variant="progress">{question.reviewerPersona}</Badge>
        <Badge variant={question.answerStatus === "unanswered" ? "p0" : "done"}>
          {STATUS_LABEL[question.answerStatus]}
        </Badge>
      </div>

      <p className="mt-3 text-sm font-medium leading-relaxed text-arsenal-primary">{question.question}</p>

      {question.recordTitle && onSelectRecord ? (
        <button
          type="button"
          className="mt-2 text-[0.62rem] font-semibold text-arsenal-accent hover:underline"
          onClick={onSelectRecord}
        >
          From: {question.recordTitle}
        </button>
      ) : null}

      {showAnswer && question.preparedAnswer ? (
        <div className="mt-3 rounded-lg border border-arsenal-border bg-arsenal-elevated p-3">
          <span className="text-[0.58rem] font-bold uppercase tracking-wide text-arsenal-muted">Prepared answer</span>
          <p className="mt-1.5 text-xs leading-relaxed text-arsenal-secondary">{question.preparedAnswer}</p>
          {question.supportingMetric ? (
            <p className="mt-2 text-[0.62rem] text-arsenal-muted">Metric: {question.supportingMetric}</p>
          ) : null}
        </div>
      ) : mode === "practice" && !revealAnswer && onReveal ? (
        <button
          type="button"
          className="mt-3 text-xs font-semibold text-arsenal-accent hover:underline"
          onClick={onReveal}
        >
          Reveal answer
        </button>
      ) : null}

      <div className="mt-3 flex items-center justify-between text-[0.62rem] text-arsenal-muted">
        <span>Confidence: {question.confidence}%</span>
        {question.lastPracticedAt ? (
          <span>Last practiced: {new Date(question.lastPracticedAt).toLocaleDateString()}</span>
        ) : null}
      </div>
    </article>
  );
}
