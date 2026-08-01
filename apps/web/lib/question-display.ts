import { PROFILE_KEY_LABELS } from "@/lib/profile-form-options";

type QuestionLike = {
  label: string;
  helpText?: string;
  section?: string;
  fieldType?: string;
  suggestedProfileKey?: string | null;
  storageHint?: string;
  displayTitle?: string;
  displayContext?: string;
  wizardEligible?: boolean;
};

const VAGUE_LABELS = new Set([
  "search",
  "attach",
  "upload",
  "other",
  "specify",
  "please specify",
]);

const VAGUE_LABEL_PATTERN =
  /^(search|attach|upload|other|specify|please specify)$/i;

const VAGUE_LABEL_TITLES: Record<string, string> = {
  attach: "Attach your resume or document",
  upload: "Upload a required file",
  resume: "Upload your resume",
  cv: "Upload your CV",
  search: "Search field (not a question — skip in browser)",
  "please specify": "Follow-up detail (only if a prior answer requires it)",
};

/** UI chrome (search boxes, file pickers) — not real profile questions. */
export function isWizardQuestion(field: QuestionLike): boolean {
  if (field.wizardEligible === false) return false;
  const label = field.label.trim().toLowerCase().replace(/\*+$/, "");
  if (VAGUE_LABELS.has(label) || VAGUE_LABEL_PATTERN.test(label)) return false;
  if (/^search$/i.test(field.fieldType || "")) return false;
  return true;
}

export function formatQuestionTitle(field: QuestionLike): string {
  if (field.displayTitle?.trim()) {
    return field.displayTitle.trim();
  }

  const label = field.label.trim();
  const lower = label.toLowerCase();

  if (field.suggestedProfileKey && PROFILE_KEY_LABELS[field.suggestedProfileKey]) {
    return PROFILE_KEY_LABELS[field.suggestedProfileKey];
  }

  if (VAGUE_LABEL_TITLES[lower]) {
    return VAGUE_LABEL_TITLES[lower];
  }

  if (lower === "attach" || /^attach\b/i.test(label)) {
    return "Attach your resume or document";
  }

  if (label.length <= 3 && field.helpText?.trim()) {
    return field.helpText.trim();
  }

  return label;
}

export function formatQuestionContext(field: QuestionLike): string | null {
  const parts: string[] = [];
  const title = formatQuestionTitle(field);
  const rawLabel = field.label.trim();

  if (field.displayContext?.trim()) {
    parts.push(field.displayContext.trim());
  }

  if (rawLabel && rawLabel !== title && rawLabel.length > 2) {
    parts.push(`Employer form label: “${rawLabel}”`);
  }

  if (field.section?.trim()) {
    parts.push(`Section: ${field.section.trim()}`);
  }

  if (field.helpText?.trim() && field.helpText.trim() !== title) {
    parts.push(field.helpText.trim());
  }

  if (field.storageHint?.trim()) {
    parts.push(field.storageHint.trim());
  }

  return parts.length ? parts.join(" · ") : null;
}
