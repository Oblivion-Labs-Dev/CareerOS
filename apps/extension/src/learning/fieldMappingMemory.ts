import { getFieldMappings, saveFieldMappings } from '../db/repositories/fieldMappingRepository';
import { normalizeQuestionText } from './questionNormalizer';
import { stringSimilarity } from './fuzzyMatcher';

export interface FieldMappingLookup {
  value: string;
  canonicalKey?: string;
  confidence: number;
  source: 'mapping';
}

function normalizeLabel(label: string): string {
  return normalizeQuestionText(label);
}

/** Reuse prior fills for this ATS host + question label (Simplify-style field memory). */
export async function lookupFieldMapping(
  domain: string | undefined,
  label: string,
  fieldType: string
): Promise<FieldMappingLookup | null> {
  if (!domain || !label.trim()) return null;
  const normalized = normalizeLabel(label);
  if (!normalized) return null;

  const mappings = await getFieldMappings();
  let best: FieldMappingLookup | null = null;
  let bestScore = 0;

  for (const mapping of mappings) {
    if (mapping.fieldType !== fieldType) continue;
    if (mapping.domain && mapping.domain !== domain) continue;

    const labelScore = stringSimilarity(normalized, mapping.normalizedLabel || normalizeLabel(mapping.rawLabel));
    const value = (mapping.finalValue || mapping.proposedValue || '').trim();
    if (!value || labelScore < 0.72) continue;

    const score = labelScore * Math.max(0.5, mapping.confidence || 0.7);
    if (score > bestScore) {
      bestScore = score;
      best = {
        value,
        canonicalKey: mapping.canonicalKey,
        confidence: score,
        source: 'mapping',
      };
    }
  }

  return best;
}

export async function rememberAutofillMappings(params: {
  domain?: string;
  sessionId: string;
  applicationId?: string;
  entries: Array<{
    label: string;
    fieldType: string;
    canonicalKey?: string;
    value: string;
    confidence: number;
    source: 'profile' | 'learned_answer' | 'manual' | 'template' | 'skipped' | 'mapping';
    wasEdited?: boolean;
  }>;
}): Promise<void> {
  if (!params.entries.length) return;

  const payload = params.entries
    .filter((entry) => entry.label.trim() && entry.value.trim())
    .map((entry) => ({
      applicationId: params.applicationId || 'autofill-session',
      sessionId: params.sessionId,
      rawLabel: entry.label,
      normalizedLabel: normalizeLabel(entry.label),
      fieldType: entry.fieldType,
      canonicalKey: entry.canonicalKey,
      proposedValue: entry.value,
      finalValue: entry.value,
      confidence: Math.min(Math.max(entry.confidence, 0), 1),
      source: entry.source === 'mapping' ? ('manual' as const) : entry.source,
      wasEdited: entry.wasEdited ?? false,
      domain: params.domain,
    }));

  if (!payload.length) return;
  await saveFieldMappings(payload);
}
