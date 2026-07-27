import { saveAutofillSession } from '../db/repositories/autofillSessionRepository';
import { generateId } from './id';
import { getCurrentDateTimeISO } from './dateUtils';

export interface AutofillSessionRecord {
  sessionId: string;
  url: string;
  company: string;
  role: string;
  platform?: string;
  fieldsDetected: number;
  fieldsFilled: number;
  fieldsSkipped: number;
  atsPlatform?: string;
  filledKeys?: string[];
}

export async function recordAutofillSession(
  record: Omit<AutofillSessionRecord, 'sessionId'> & { sessionId?: string }
): Promise<string> {
  const sessionId = record.sessionId || generateId();
  await saveAutofillSession({
    id: sessionId,
    applicationId: sessionId,
    pageUrl: record.url,
    startedAt: getCurrentDateTimeISO(),
    completedAt: getCurrentDateTimeISO(),
    fieldsDetected: record.fieldsDetected,
    fieldsFilled: record.fieldsFilled,
    fieldsSkipped: record.fieldsSkipped,
    lowConfidenceCount: Math.max(0, record.fieldsDetected - record.fieldsFilled - record.fieldsSkipped),
    userApproved: true,
    finalAction: record.fieldsFilled > 0 ? 'filled' : 'reviewed'
  });
  return sessionId;
}
