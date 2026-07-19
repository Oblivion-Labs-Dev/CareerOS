"use client";

import { SegmentedControl, StatePanel } from "@arsenal/ui";
import { InterviewQuestionCard, type InterviewQuestionData } from "@career-os/ui/corpus";
import { useEffect, useMemo, useState } from "react";
import type { CorpusQuestionView, CorpusRecord } from "../corpus-model";
import { QuestionsByBulletPanel } from "./corpus-quality-ui";
import styles from "../resume-corpus.module.css";

type PrepMode = "study" | "practice" | "mock" | "rapid";

type InterviewTrack =
  | "all"
  | "recruiter"
  | "hiring-manager"
  | "behavioral"
  | "technical"
  | "system-design"
  | "staff"
  | "principal"
  | "security"
  | "reliability"
  | "ai-infra"
  | "red-team";

interface QuestionEntry {
  key: string;
  domId: string;
  record: CorpusRecord;
  question: InterviewQuestionData;
  tracks: InterviewTrack[];
}

interface TrackDefinition {
  value: Exclude<InterviewTrack, "all">;
  label: string;
  patterns: RegExp[];
}

const NOTES_STORAGE_KEY = "careeros:resume-corpus:interview-notes:v1";

const MODE_OPTIONS = [
  { value: "study", label: "Study" },
  { value: "practice", label: "Practice" },
  { value: "mock", label: "Mock" },
  { value: "rapid", label: "Rapid review" },
] as const;

const TRACK_DEFINITIONS: readonly TrackDefinition[] = [
  { value: "recruiter", label: "Recruiter", patterns: [/recruiter/, /screen/, /background/, /walk me through/] },
  { value: "hiring-manager", label: "Hiring manager", patterns: [/hiring manager/, /manager/, /personally own/, /prioriti/] },
  { value: "behavioral", label: "Behavioral", patterns: [/behavior/, /tell me about/, /conflict/, /collaborat/, /influence/, /mistake/] },
  { value: "technical", label: "Technical", patterns: [/technical/, /engineering/, /implement/, /debug/, /performance/, /algorithm/] },
  { value: "system-design", label: "System design", patterns: [/system design/, /architecture/, /trade.?off/, /data flow/, /scale/] },
  { value: "staff", label: "Staff", patterns: [/staff/, /cross.?team/, /platform thinking/, /strategy/] },
  { value: "principal", label: "Principal", patterns: [/principal/, /organization/, /portfolio/, /long.?term/] },
  { value: "security", label: "Security", patterns: [/security/, /threat/, /risk/, /privacy/, /compliance/, /auth/] },
  { value: "reliability", label: "Reliability", patterns: [/reliab/, /resilien/, /availability/, /incident/, /retry/, /failure/, /slo/] },
  { value: "ai-infra", label: "AI infrastructure", patterns: [/\bai\b/, /agent/, /model/, /inference/, /machine learning/, /governance/] },
  { value: "red-team", label: "Red team", patterns: [/red.?team/, /adversar/, /abuse/, /attack/, /devil/, /skeptic/, /reject/] },
];

interface CorpusInterviewPrepProps {
  records: CorpusRecord[];
  onSelectRecord: (recordId: string, sectionId?: string) => void;
}

function entrySearchText(record: CorpusRecord, question: CorpusQuestionView): string {
  return [
    question.question,
    question.interviewType,
    question.reviewerPersona,
    question.preparedAnswer,
    record.title,
    record.role,
    record.summary,
    record.technicalChallenge,
    record.architectureDecision,
    record.reliabilityAndScale,
    record.leadership,
    ...record.domains,
    ...record.concepts,
    ...record.technologies,
    ...record.concerns.flatMap((concern) => [concern.reviewer, concern.category, concern.concern]),
  ]
    .filter(Boolean)
    .join(" ")
    .toLocaleLowerCase();
}

function tracksForQuestion(record: CorpusRecord, question: CorpusQuestionView): InterviewTrack[] {
  const text = entrySearchText(record, question);
  return TRACK_DEFINITIONS
    .filter((definition) => definition.patterns.some((pattern) => pattern.test(text)))
    .map((definition) => definition.value);
}

function toQuestionEntry(record: CorpusRecord, question: CorpusQuestionView): QuestionEntry {
  const verifiedMetric = record.metrics.find((metric) => question.metricIds.includes(metric.id) && metric.verification === "verified");
  const key = `${record.id}:${question.id}`;
  return {
    key,
    domId: `interview-${key.replace(/[^a-zA-Z0-9_-]/g, "-")}`,
    record,
    tracks: tracksForQuestion(record, question),
    question: {
      ...question,
      recordTitle: record.title,
      supportingMetric: verifiedMetric ? `${verifiedMetric.name}: ${verifiedMetric.value}` : undefined,
    },
  };
}

function readStoredNotes(): Record<string, string> {
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(NOTES_STORAGE_KEY) ?? "{}");
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    return Object.fromEntries(
      Object.entries(parsed).filter((entry): entry is [string, string] => typeof entry[1] === "string"),
    );
  } catch {
    return {};
  }
}

function formatTimer(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  return `${minutes.toString().padStart(2, "0")}:${(seconds % 60).toString().padStart(2, "0")}`;
}

function statusTone(status: InterviewQuestionData["answerStatus"]): "success" | "warning" | "danger" {
  if (status === "prepared" || status === "practiced") return "success";
  if (status === "draft") return "warning";
  return "danger";
}

export function CorpusInterviewPrep({ records, onSelectRecord }: CorpusInterviewPrepProps) {
  const [mode, setMode] = useState<PrepMode>("study");
  const [recordFilter, setRecordFilter] = useState("all");
  const [trackFilter, setTrackFilter] = useState<InterviewTrack>("all");
  const [activeIndex, setActiveIndex] = useState(0);
  const [answerRevealed, setAnswerRevealed] = useState(false);
  const [timerSeconds, setTimerSeconds] = useState(0);
  const [timerRunning, setTimerRunning] = useState(false);
  const [notesByQuestion, setNotesByQuestion] = useState<Record<string, string>>({});
  const [notesLoaded, setNotesLoaded] = useState(false);

  const allQuestions = useMemo(
    () => records.flatMap((record) => record.interviewQuestions.map((question) => toQuestionEntry(record, question))),
    [records],
  );

  const availableTracks = useMemo(
    () => TRACK_DEFINITIONS.filter((definition) =>
      allQuestions.some((entry) => entry.tracks.includes(definition.value)),
    ),
    [allQuestions],
  );

  const recordsWithQuestions = useMemo(
    () => records.filter((record) => record.interviewQuestions.length > 0),
    [records],
  );

  const filteredQuestions = useMemo(
    () => allQuestions.filter((entry) =>
      (recordFilter === "all" || entry.record.id === recordFilter)
      && (trackFilter === "all" || entry.tracks.includes(trackFilter)),
    ),
    [allQuestions, recordFilter, trackFilter],
  );

  const activeEntry = filteredQuestions[activeIndex] ?? filteredQuestions[0];
  const preparedCount = allQuestions.filter((entry) =>
    entry.question.answerStatus === "prepared" || entry.question.answerStatus === "practiced",
  ).length;
  const practicedCount = allQuestions.filter((entry) => entry.question.answerStatus === "practiced").length;
  const filteredPreparedCount = filteredQuestions.filter((entry) =>
    entry.question.answerStatus === "prepared" || entry.question.answerStatus === "practiced",
  ).length;

  useEffect(() => {
    setNotesByQuestion(readStoredNotes());
    setNotesLoaded(true);
  }, []);

  useEffect(() => {
    if (!notesLoaded) return;
    try {
      window.localStorage.setItem(NOTES_STORAGE_KEY, JSON.stringify(notesByQuestion));
    } catch {
      // Notes remain available for this session if storage is unavailable.
    }
  }, [notesByQuestion, notesLoaded]);

  useEffect(() => {
    if (!timerRunning || mode !== "mock") return;
    const intervalId = window.setInterval(() => setTimerSeconds((seconds) => seconds + 1), 1000);
    return () => window.clearInterval(intervalId);
  }, [mode, timerRunning]);

  useEffect(() => {
    if (activeIndex < filteredQuestions.length) return;
    setActiveIndex(0);
    setAnswerRevealed(false);
    setTimerRunning(false);
    setTimerSeconds(0);
  }, [activeIndex, filteredQuestions.length]);

  useEffect(() => {
    if (trackFilter === "all" || availableTracks.some((track) => track.value === trackFilter)) return;
    setTrackFilter("all");
  }, [availableTracks, trackFilter]);

  const selectQuestion = (index: number) => {
    const entry = filteredQuestions[index];
    if (!entry) return;
    setActiveIndex(index);
    setAnswerRevealed(false);
    setTimerRunning(false);
    setTimerSeconds(0);

    if (mode === "study") {
      window.requestAnimationFrame(() => {
        document.getElementById(entry.domId)?.scrollIntoView({ behavior: "smooth", block: "center" });
      });
    }
  };

  const changeMode = (nextMode: PrepMode) => {
    setMode(nextMode);
    setAnswerRevealed(false);
    setTimerRunning(false);
    if (nextMode !== "mock") setTimerSeconds(0);
  };

  const stepQuestion = (direction: -1 | 1) => {
    const nextIndex = activeIndex + direction;
    if (nextIndex < 0 || nextIndex >= filteredQuestions.length) return;
    selectQuestion(nextIndex);
  };

  if (records.length === 0) {
    return (
      <div className={styles.viewStack}>
        <header className={styles.sectionHeading}>
          <div>
            <div className={styles.eyebrow}>Interview preparation</div>
            <h1>Practice from documented work</h1>
            <p>Interview prompts stay linked to the accomplishment that supports each answer.</p>
          </div>
        </header>
        <StatePanel
          kind="empty"
          title="Add an accomplishment before preparing answers"
          description="A real project gives each interview response an honest source for ownership, decisions, tradeoffs, and outcomes."
        />
      </div>
    );
  }

  if (allQuestions.length === 0) {
    return (
      <div className={styles.viewStack}>
        <header className={styles.sectionHeading}>
          <div>
            <div className={styles.eyebrow}>Interview preparation</div>
            <h1>Build the question bank</h1>
            <p>Your accomplishments are available, but no interview questions have been authored yet.</p>
          </div>
        </header>
        <StatePanel
          kind="empty"
          title="No interview questions yet"
          description="Open an accomplishment and add realistic follow-up questions before starting practice or mock sessions."
          action={(
            <button type="button" className={styles.primaryButton} onClick={() => onSelectRecord(records[0]!.id, "interview")}>
              Open first accomplishment
            </button>
          )}
        />
      </div>
    );
  }

  return (
    <div className={styles.viewStack}>
      <header className={styles.sectionHeading}>
        <div>
          <div className={styles.eyebrow}>Interview preparation</div>
          <h1>Defend the work, not a memorized script</h1>
          <p>Study, recall, run a timed mock, or move quickly through flashcards. Every prompt stays linked to its source story.</p>
        </div>
        <div className={styles.heroMeta} aria-label="Interview readiness summary">
          <span className={styles.statusTag} data-tone="success">{preparedCount}/{allQuestions.length} prepared</span>
          <span className={styles.statusTag}>{practicedCount} practiced</span>
        </div>
      </header>

      <QuestionsByBulletPanel records={records} onSelectRecord={onSelectRecord} />

      <div className={styles.toolbar}>
        <SegmentedControl
          label="Preparation mode"
          options={MODE_OPTIONS}
          value={mode}
          onValueChange={changeMode}
          size="sm"
        />
        <div className={styles.toolbarGroup}>
          <label className={styles.fieldGroup} htmlFor="interview-record-filter">
            <span className={styles.label}>Accomplishment</span>
            <select
              id="interview-record-filter"
              className={styles.select}
              value={recordFilter}
              onChange={(event) => {
                setRecordFilter(event.target.value);
                setActiveIndex(0);
                setAnswerRevealed(false);
                setTimerRunning(false);
                setTimerSeconds(0);
              }}
            >
              <option value="all">All accomplishments</option>
              {recordsWithQuestions.map((record) => (
                <option value={record.id} key={record.id}>{record.title}</option>
              ))}
            </select>
          </label>
          <label className={styles.fieldGroup} htmlFor="interview-track-filter">
            <span className={styles.label}>Interview track</span>
            <select
              id="interview-track-filter"
              className={styles.select}
              value={trackFilter}
              onChange={(event) => {
                setTrackFilter(event.target.value as InterviewTrack);
                setActiveIndex(0);
                setAnswerRevealed(false);
                setTimerRunning(false);
                setTimerSeconds(0);
              }}
            >
              <option value="all">All available tracks</option>
              {availableTracks.map((track) => (
                <option value={track.value} key={track.value}>{track.label}</option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {filteredQuestions.length === 0 ? (
        <StatePanel
          kind="empty"
          title="No questions match these filters"
          description="This corpus does not contain a question in the selected accomplishment and interview track. Clear both filters to return to the full queue."
          action={(
            <button
              type="button"
              className={styles.quietButton}
              onClick={() => {
                setRecordFilter("all");
                setTrackFilter("all");
                setActiveIndex(0);
              }}
            >
              Clear filters
            </button>
          )}
        />
      ) : (
        <div className={styles.interviewLayout}>
          <aside className={styles.panel} aria-labelledby="question-queue-title">
            <div className={styles.panelHeader}>
              <div>
                <h2 id="question-queue-title">Question queue</h2>
                <p>{filteredPreparedCount}/{filteredQuestions.length} prepared in this view</p>
              </div>
            </div>
            <nav className={styles.questionQueue} aria-label="Filtered interview question queue">
              {filteredQuestions.map((entry, index) => (
                <button
                  type="button"
                  className={`${styles.questionQueueButton} ${index === activeIndex ? styles.questionQueueButtonActive : ""}`}
                  key={entry.key}
                  aria-current={index === activeIndex ? "true" : undefined}
                  aria-label={`Question ${index + 1} of ${filteredQuestions.length}: ${entry.question.question}`}
                  onClick={() => selectQuestion(index)}
                >
                  <span className={styles.rowCopy}>
                    <strong>{index + 1}. {entry.question.question}</strong>
                    <span>{entry.question.reviewerPersona} · {entry.record.title}</span>
                  </span>
                </button>
              ))}
            </nav>
          </aside>

          <section aria-label={`${MODE_OPTIONS.find((option) => option.value === mode)?.label ?? "Interview"} workspace`}>
            {mode === "study" ? (
              <section aria-labelledby="study-mode-title">
                <div className={styles.panelHeader}>
                  <div>
                    <h2 id="study-mode-title">Study the prepared evidence</h2>
                    <p>Read the prompt, answer, source accomplishment, and verified supporting metric where one exists.</p>
                  </div>
                </div>
                <div className={styles.questionList}>
                  {filteredQuestions.map((entry) => (
                    <div id={entry.domId} key={entry.key}>
                      <InterviewQuestionCard
                        question={entry.question}
                        mode="study"
                        onSelectRecord={() => onSelectRecord(entry.record.id, "interview")}
                      />
                    </div>
                  ))}
                </div>
              </section>
            ) : null}

            {mode === "practice" && activeEntry ? (
              <article className={styles.practiceCard} aria-labelledby="practice-question-title">
                <div className={styles.practiceInner}>
                  <div className={styles.practiceMeta}>
                    <span className={styles.statusTag}>{activeEntry.question.interviewType}</span>
                    <span className={styles.statusTag}>{activeEntry.question.reviewerPersona}</span>
                    <span className={styles.statusTag} data-tone={statusTone(activeEntry.question.answerStatus)}>
                      {activeEntry.question.answerStatus}
                    </span>
                    <span className={styles.statusTag}>{activeIndex + 1}/{filteredQuestions.length}</span>
                  </div>
                  <h2 id="practice-question-title">{activeEntry.question.question}</h2>
                  <button type="button" className={styles.textButton} onClick={() => onSelectRecord(activeEntry.record.id, "interview")}>
                    Open source: {activeEntry.record.title} →
                  </button>

                  {answerRevealed ? (
                    activeEntry.question.preparedAnswer ? (
                      <div className={styles.answerBlock} aria-live="polite">
                        <strong>Prepared answer</strong>
                        <p>{activeEntry.question.preparedAnswer}</p>
                        {activeEntry.question.supportingMetric ? <p>Verified metric: {activeEntry.question.supportingMetric}</p> : null}
                      </div>
                    ) : (
                      <StatePanel
                        kind="empty"
                        size="compact"
                        title="No prepared answer is stored"
                        description="Say what you can support, then open the source accomplishment to write a durable answer."
                      />
                    )
                  ) : (
                    <p className={styles.helper}>Answer aloud before revealing the prepared reference.</p>
                  )}

                  <div className={styles.practiceActions}>
                    <button type="button" className={styles.primaryButton} onClick={() => setAnswerRevealed((visible) => !visible)}>
                      {answerRevealed ? "Hide answer" : "Reveal answer"}
                    </button>
                    <button type="button" className={styles.quietButton} disabled={activeIndex === 0} onClick={() => stepQuestion(-1)}>
                      Previous
                    </button>
                    <button type="button" className={styles.quietButton} disabled={activeIndex === filteredQuestions.length - 1} onClick={() => stepQuestion(1)}>
                      Next question
                    </button>
                  </div>
                </div>
              </article>
            ) : null}

            {mode === "mock" && activeEntry ? (
              <article className={styles.practiceCard} aria-labelledby="mock-question-title">
                <div className={styles.practiceInner}>
                  <div className={styles.practiceMeta}>
                    <span className={styles.statusTag}>{activeEntry.question.reviewerPersona}</span>
                    <span className={styles.statusTag}>{activeEntry.question.difficulty}</span>
                    <span className={styles.timer} role="timer" aria-label={`Elapsed time ${formatTimer(timerSeconds)}`}>
                      {formatTimer(timerSeconds)}
                    </span>
                  </div>
                  <h2 id="mock-question-title">{activeEntry.question.question}</h2>
                  <button type="button" className={styles.textButton} onClick={() => onSelectRecord(activeEntry.record.id, "interview")}>
                    Source: {activeEntry.record.title} →
                  </button>

                  <div className={styles.answerBlock}>
                    <label className={styles.label} htmlFor={`mock-notes-${activeEntry.domId}`}>Session notes</label>
                    <textarea
                      id={`mock-notes-${activeEntry.domId}`}
                      className={styles.textarea}
                      rows={7}
                      value={notesByQuestion[activeEntry.key] ?? ""}
                      placeholder="Capture your outline, moments you stalled, and details to verify."
                      onChange={(event) => setNotesByQuestion((notes) => ({
                        ...notes,
                        [activeEntry.key]: event.target.value,
                      }))}
                    />
                    <p className={styles.helper}>Notes are saved on this device for this specific question.</p>
                  </div>

                  {answerRevealed ? (
                    <div className={styles.answerBlock} aria-live="polite">
                      <strong>Prepared reference</strong>
                      <p>{activeEntry.question.preparedAnswer || "No prepared answer is stored for this question."}</p>
                    </div>
                  ) : null}

                  <div className={styles.practiceActions}>
                    <button type="button" className={styles.primaryButton} onClick={() => setTimerRunning((running) => !running)}>
                      {timerRunning ? "Pause timer" : timerSeconds > 0 ? "Resume timer" : "Start timer"}
                    </button>
                    <button
                      type="button"
                      className={styles.quietButton}
                      onClick={() => {
                        setTimerRunning(false);
                        setTimerSeconds(0);
                      }}
                    >
                      Reset
                    </button>
                    <button type="button" className={styles.quietButton} onClick={() => setAnswerRevealed((visible) => !visible)}>
                      {answerRevealed ? "Hide reference" : "Show reference"}
                    </button>
                    <button type="button" className={styles.quietButton} disabled={activeIndex === 0} onClick={() => stepQuestion(-1)}>
                      Previous
                    </button>
                    <button type="button" className={styles.quietButton} disabled={activeIndex === filteredQuestions.length - 1} onClick={() => stepQuestion(1)}>
                      Next
                    </button>
                  </div>
                </div>
              </article>
            ) : null}

            {mode === "rapid" && activeEntry ? (
              <article className={styles.practiceCard} aria-labelledby="rapid-card-title">
                <div className={styles.practiceInner}>
                  <div className={styles.practiceMeta}>
                    <span className={styles.statusTag}>{activeEntry.question.interviewType}</span>
                    <span className={styles.statusTag}>{activeIndex + 1}/{filteredQuestions.length}</span>
                    <span className={styles.statusTag} data-tone={statusTone(activeEntry.question.answerStatus)}>
                      {activeEntry.question.answerStatus}
                    </span>
                  </div>
                  <div aria-live="polite">
                    <div className={styles.eyebrow}>{answerRevealed ? "Answer" : "Question"}</div>
                    {answerRevealed ? (
                      <div className={styles.answerBlock}>
                        <p id="rapid-card-title">{activeEntry.question.preparedAnswer || "No prepared answer is stored. Open the source story to add one."}</p>
                      </div>
                    ) : (
                      <h2 id="rapid-card-title">{activeEntry.question.question}</h2>
                    )}
                  </div>
                  <button type="button" className={styles.textButton} onClick={() => onSelectRecord(activeEntry.record.id, "interview")}>
                    {activeEntry.record.title} →
                  </button>
                  <div className={styles.practiceActions}>
                    <button type="button" className={styles.primaryButton} onClick={() => setAnswerRevealed((visible) => !visible)}>
                      {answerRevealed ? "Show question" : "Flip card"}
                    </button>
                    <button type="button" className={styles.quietButton} disabled={activeIndex === 0} onClick={() => stepQuestion(-1)}>
                      Previous card
                    </button>
                    <button type="button" className={styles.quietButton} disabled={activeIndex === filteredQuestions.length - 1} onClick={() => stepQuestion(1)}>
                      Next card
                    </button>
                  </div>
                </div>
              </article>
            ) : null}
          </section>
        </div>
      )}
    </div>
  );
}
