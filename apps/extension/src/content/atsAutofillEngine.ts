import {
  detectAtsAutofillConfig,
  type AtsAutofillConfig,
  type AtsFieldStep,
} from '../adapters/atsAutofillConfig';
import { UserProfile } from '../shared/types';
import { enrichProfile } from '../profile/profileStore';
import { fillFileInput, fillSelect, fillTextOrTextArea } from './autofillEngine';
import { traceStep } from '../shared/actionTrace';

const RESUME_PARSE_WAIT_MS = 2500;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function queryFirst(doc: Document, selector: string): HTMLElement | null {
  for (const part of selector.split(',').map((s) => s.trim())) {
    const el = doc.querySelector(part);
    if (el instanceof HTMLElement) return el;
  }
  return null;
}

function queryAll(doc: Document, selector: string): HTMLElement[] {
  const seen = new Set<HTMLElement>();
  const results: HTMLElement[] = [];
  for (const part of selector.split(',').map((s) => s.trim())) {
    for (const el of Array.from(doc.querySelectorAll(part))) {
      if (el instanceof HTMLElement && !seen.has(el)) {
        seen.add(el);
        results.push(el);
      }
    }
  }
  return results;
}

function hasValue(element: HTMLElement): boolean {
  if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement) {
    return Boolean(element.value?.trim());
  }
  if (element instanceof HTMLSelectElement) {
    return Boolean(element.value?.trim());
  }
  return Boolean(element.textContent?.trim());
}

function profileValueForKey(key: string, profile: UserProfile): string | undefined {
  const map: Record<string, string | undefined> = {
    firstName: profile.firstName,
    lastName: profile.lastName,
    fullName: profile.fullName,
    email: profile.email,
    phone: profile.phone,
    location: profile.location,
    linkedin: profile.linkedin,
    github: profile.github,
    portfolio: profile.portfolio,
    currentCompany: profile.currentCompany,
    currentTitle: profile.currentTitle,
    targetRole: profile.targetRole,
    workAuthorization: profile.workAuthorization,
    sponsorship: profile.sponsorship,
    yearsExperience: profile.yearsExperience,
    salary: profile.salaryExpectations,
  };
  const value = map[key]?.trim();
  return value || undefined;
}

async function waitForSelector(doc: Document, selector: string, timeoutMs: number): Promise<boolean> {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (queryFirst(doc, selector)) return true;
    await sleep(250);
  }
  return Boolean(queryFirst(doc, selector));
}

async function runStep(
  step: AtsFieldStep,
  profile: UserProfile,
  doc: Document,
  operationId?: string
): Promise<boolean> {
  if (step.method === 'wait') {
    const ok = await waitForSelector(doc, step.selector, step.waitMs ?? 5000);
    traceStep(operationId, 'autofill', `ats_wait_${step.field}`, 'autofill:ats', { ok, selector: step.selector });
    return ok;
  }

  const element = queryFirst(doc, step.selector);
  if (!element) {
    traceStep(operationId, 'autofill', `ats_missing_${step.field}`, 'autofill:ats', {
      selector: step.selector,
      optional: step.optional,
    });
    return false;
  }

  if (step.method === 'click') {
    if (element.offsetParent === null && element.getAttribute('hidden') !== null) {
      return false;
    }
    element.click();
    await sleep(step.waitMs ?? 600);
    traceStep(operationId, 'autofill', `ats_click_${step.field}`, 'autofill:ats', { selector: step.selector });
    return true;
  }

  if (hasValue(element) && step.method !== 'uploadResume' && step.method !== 'uploadCoverLetter') {
    return false;
  }

  if (step.method === 'uploadResume') {
    if (!profile.resume) return false;
    fillFileInput(element as HTMLInputElement, profile.resume);
    await sleep(RESUME_PARSE_WAIT_MS);
    traceStep(operationId, 'autofill', 'ats_upload_resume', 'autofill:ats');
    return true;
  }

  if (step.method === 'uploadCoverLetter') {
    if (element instanceof HTMLInputElement && element.type === 'file') {
      if (!profile.coverLetter) return false;
      fillFileInput(element, profile.coverLetter);
      traceStep(operationId, 'autofill', 'ats_upload_cover', 'autofill:ats');
      return true;
    }
    const textValue = profile.coverLetter?.name || profile.customFields?.coverLetterText;
    if (textValue && (element instanceof HTMLTextAreaElement || element instanceof HTMLInputElement)) {
      fillTextOrTextArea(element, textValue);
      traceStep(operationId, 'autofill', 'ats_write_cover', 'autofill:ats');
      return true;
    }
    return false;
  }

  const value = profileValueForKey(step.field, profile);
  if (!value) return false;

  if (step.method === 'select' && element instanceof HTMLSelectElement) {
    fillSelect(element, value);
    traceStep(operationId, 'autofill', `ats_select_${step.field}`, 'autofill:ats');
    return true;
  }

  if (element.isContentEditable) {
    fillTextOrTextArea(element as HTMLTextAreaElement, value);
    traceStep(operationId, 'autofill', `ats_text_${step.field}`, 'autofill:ats');
    return true;
  }

  if (
    element instanceof HTMLInputElement ||
    element instanceof HTMLTextAreaElement
  ) {
    fillTextOrTextArea(element, value);
    traceStep(operationId, 'autofill', `ats_text_${step.field}`, 'autofill:ats');
    return true;
  }

  return false;
}

async function runSteps(
  steps: AtsFieldStep[],
  profile: UserProfile,
  doc: Document,
  operationId?: string
): Promise<number> {
  let filled = 0;
  for (const step of steps) {
    try {
      const ok = await runStep(step, profile, doc, operationId);
      if (ok) filled += 1;
    } catch (err) {
      if (!step.optional) {
        traceStep(operationId, 'autofill', `ats_error_${step.field}`, 'autofill:ats', {
          error: err instanceof Error ? err.message : String(err),
        });
      }
    }
  }
  return filled;
}

export interface AtsAutofillResult {
  platform: string;
  filledCount: number;
  filledKeys: string[];
}

export async function runAtsAutofill(
  profile: UserProfile,
  doc: Document = document,
  operationId?: string,
  config?: AtsAutofillConfig | null
): Promise<AtsAutofillResult | null> {
  const activeConfig = config ?? detectAtsAutofillConfig(doc);
  if (!activeConfig) return null;

  const enriched = enrichProfile(profile);
  traceStep(operationId, 'autofill', 'ats_start', 'autofill:ats', { platform: activeConfig.name });

  let filledCount = 0;
  const filledKeys: string[] = [];

  if (activeConfig.preSteps?.length) {
    filledCount += await runSteps(activeConfig.preSteps, enriched, doc, operationId);
  }

  for (const step of activeConfig.fieldSteps) {
    const before = filledCount;
    filledCount += await runSteps([step], enriched, doc, operationId);
    if (filledCount > before && step.field !== 'wait' && step.field !== 'begin') {
      filledKeys.push(step.field);
    }
  }

  traceStep(operationId, 'autofill', 'ats_complete', 'autofill:ats', {
    platform: activeConfig.name,
    filledCount,
    filledKeys,
  });

  return {
    platform: activeConfig.name,
    filledCount,
    filledKeys,
  };
}

export { detectAtsAutofillConfig };
