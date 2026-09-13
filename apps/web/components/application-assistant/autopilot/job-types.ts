/** A job row as returned by /autopilot/jobs — only fields we know exist. */
export type AutopilotJobRow = {
  id: string;
  company?: string;
  title?: string;
  location?: string;
  status?: string;
  matchScore?: number | null;
  /** Mistral/Ollama resume-vs-JD comparison stored alongside the score. */
  matchReason?: string;
  keyMatchingSkills?: string[];
  missingSkills?: string[];
  matchMethod?: string;
  matchModel?: string;
  /** Backend's own ordering key: location/level tier bonus + match score. */
  queuePriority?: number;
  queuePosition?: number;
  submittedAt?: string;
  submissionConfirmed?: boolean;
  /** "manual" when the user applied by hand and marked it submitted themselves. */
  submissionSource?: string | null;
  previousStatus?: string | null;
  updatedAt?: string;
  queuedAt?: string;
  applicationUrl?: string;
  lastError?: string;
  skipReason?: string;
  lastErrorType?: string;
  resumeFileUsed?: string;
  salary?: string;
  pendingQuestions?: { question: string; rawLabel?: string; options?: string[] }[];
  checkpointHistory?: { step?: string; details?: string; timestamp?: string }[];
  answers?: Record<string, unknown>;
  /** Set only on INELIGIBLE rows: why this posting can never be applied to. */
  ineligibilityReason?: string;
  ineligibilityDetail?: string;
  /** True when this SUBMITTED row is a genuine re-submission of a posting
   * already submitted under another row (same employer, same posting) -
   * kept visible in history but excluded from submitted/success-rate counts. */
  duplicateSubmission?: boolean;
  duplicateOfJobId?: string;
};

