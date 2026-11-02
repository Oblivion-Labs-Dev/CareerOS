import { scanPage, ScannedField } from './domScanner';
import { readFieldDisplayValue } from './fieldValue';
import { resolveFieldLabel } from './fieldInference';
import { mergeAddressIntoProfile } from '../profile/addressProfile';
import { saveProfile } from '../profile/profileStore';
import { appendScreeningAnswerForLabel } from '../shared/screeningAnswers';
import { UserProfile } from '../shared/types';
import { FIELD_MARKER_ATTR } from './fieldMarker';

export interface SkippedFieldRef {
  label: string;
  reason: string;
  fieldId: string;
  canonicalKey?: string;
}

function normalizeLabelKey(label: string): string {
  return label.replace(/\*+$/, '').replace(/\s+/g, ' ').trim().toLowerCase();
}

function findFieldByLabel(fields: ScannedField[], label: string): ScannedField | undefined {
  const key = normalizeLabelKey(label);
  if (!key) return undefined;

  return fields.find((field) => {
    const candidates = [field.labelText, field.name, field.placeholder, field.htmlId].filter(Boolean);
    return candidates.some((candidate) => {
      const candidateKey = normalizeLabelKey(candidate);
      return candidateKey === key || candidateKey.includes(key) || key.includes(candidateKey);
    });
  });
}

function resolveSkippedField(
  skipped: SkippedFieldRef,
  fields: ScannedField[],
  doc: Document
): ScannedField | undefined {
  if (skipped.fieldId) {
    const marked = doc.querySelector(
      `[${FIELD_MARKER_ATTR}="${CSS.escape(skipped.fieldId)}"]`
    ) as HTMLElement | null;
    if (marked) {
      const fromMarker = fields.find((field) => field.element === marked || marked.contains(field.element));
      if (fromMarker) return fromMarker;
    }
    const byId = fields.find((field) => field.id === skipped.fieldId);
    if (byId) return byId;
  }
  return findFieldByLabel(fields, skipped.label);
}

function inferCanonicalKeyFromLabel(label: string): string | undefined {
  const normalized = normalizeLabelKey(label);
  if (/currently located|where.*located|where.*live|work location|residence location/.test(normalized)) {
    return 'location';
  }
  if (/legally authorized|authorized to work|work authorization|right to work/.test(normalized)) {
    return 'workAuthorization';
  }
  if (/sponsor|visa|immigration-related employment benefit/.test(normalized)) {
    return 'sponsorship';
  }
  if (/arbitration|agreement|acknowledge|consent|privacy notice|code of conduct/.test(normalized)) {
    return 'agreement';
  }
  return undefined;
}

function isQuestionLikeLabel(label: string): boolean {
  return /\?/.test(label) || label.length > 24;
}

export async function persistSkippedFieldValues(
  profile: UserProfile,
  skipped: SkippedFieldRef[],
  doc: Document = document
): Promise<UserProfile> {
  if (!skipped.length) return profile;

  const fields = scanPage(doc);
  let next = profile;
  let changed = false;

  for (const skippedField of skipped) {
    const field = resolveSkippedField(skippedField, fields, doc);
    if (!field) continue;

    const value = readFieldDisplayValue(field, doc);
    if (!value) continue;

    const label = skippedField.label || resolveFieldLabel(field, doc) || field.labelText || 'Unnamed field';
    const canonicalKey =
      skippedField.canonicalKey === 'workAuthorization' ||
      skippedField.canonicalKey === 'sponsorship' ||
      skippedField.canonicalKey === 'location'
        ? skippedField.canonicalKey
        : inferCanonicalKeyFromLabel(label);

    if (canonicalKey === 'location') {
      if (value.trim() !== (next.location || '').trim()) {
        next = { ...next, location: value.trim() };
        changed = true;
      }
      continue;
    }

    if (canonicalKey === 'workAuthorization' || canonicalKey === 'sponsorship') {
      const answer =
        canonicalKey === 'workAuthorization'
          ? next.workAuthorization || value.trim() || 'Yes'
          : next.sponsorship || value.trim() || 'No';
      const updated = appendScreeningAnswerForLabel(next, label, answer, canonicalKey);
      if (updated !== next) {
        next = updated;
        changed = true;
      }
      continue;
    }

    if (canonicalKey === 'agreement' || field.type === 'checkbox') {
      const answer = value === 'Yes' || field.type === 'checkbox' ? 'Yes' : value.trim();
      const updated = appendScreeningAnswerForLabel(next, label, answer);
      if (updated !== next) {
        next = updated;
        changed = true;
      }
      continue;
    }

    if (isQuestionLikeLabel(label)) {
      const updated = appendScreeningAnswerForLabel(next, label, value.trim());
      if (updated !== next) {
        next = updated;
        changed = true;
      }
      continue;
    }

    const customKey = normalizeLabelKey(label).replace(/[^a-z0-9]+/g, '_').slice(0, 48);
    if (!customKey) continue;
    const existing = next.customFields?.[customKey];
    if (existing === value.trim()) continue;
    next = {
      ...next,
      customFields: {
        ...(next.customFields || {}),
        [customKey]: value.trim()
      }
    };
    changed = true;
  }

  if (changed) {
    await saveProfile(next);
  }

  return next;
}

export function watchSkippedFieldsForProfileSave(
  skipped: SkippedFieldRef[],
  loadProfile: () => Promise<UserProfile>,
  doc: Document = document,
  onSaved?: () => void
): () => void {
  if (!skipped.length) return () => undefined;

  const cleanups: Array<() => void> = [];
  let saveTimer: number | undefined;
  let stopped = false;

  const scheduleSave = () => {
    if (stopped) return;
    if (saveTimer) window.clearTimeout(saveTimer);
    saveTimer = window.setTimeout(() => {
      void loadProfile()
        .then((profile) => persistSkippedFieldValues(profile, skipped, doc))
        .then(() => onSaved?.())
        .catch(() => undefined);
    }, 500);
  };

  for (const skippedField of skipped) {
    const fields = scanPage(doc);
    const field = resolveSkippedField(skippedField, fields, doc);
    if (!field) continue;

    const targets = new Set<HTMLElement>();
    targets.add(field.element);
    const marked = doc.querySelector(
      `[${FIELD_MARKER_ATTR}="${CSS.escape(skippedField.fieldId)}"]`
    ) as HTMLElement | null;
    if (marked) targets.add(marked);

    for (const target of targets) {
      const onChange = () => scheduleSave();
      target.addEventListener('input', onChange);
      target.addEventListener('change', onChange);
      target.addEventListener('blur', onChange, true);
      cleanups.push(() => {
        target.removeEventListener('input', onChange);
        target.removeEventListener('change', onChange);
        target.removeEventListener('blur', onChange, true);
      });
    }
  }

  void loadProfile()
    .then((profile) => persistSkippedFieldValues(profile, skipped, doc))
    .then(() => onSaved?.())
    .catch(() => undefined);

  return () => {
    stopped = true;
    if (saveTimer) window.clearTimeout(saveTimer);
    for (const cleanup of cleanups) cleanup();
  };
}
