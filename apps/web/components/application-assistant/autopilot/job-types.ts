/** A job row as returned by /autopilot/jobs — only fields we know exist. */
export type AutopilotJobRow = {
  id: string;
  company?: string;
  title?: string;
  location?: string;
  status?: string;
  matchScore?: number | null;
  submittedAt?: string;
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
};

