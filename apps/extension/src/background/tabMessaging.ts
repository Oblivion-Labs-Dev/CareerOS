import { JobDetails, UserProfile } from '../shared/types';
import { logAutofillResult, logToServer } from '../shared/serverLog';
import { endTrace, traceStep } from '../shared/actionTrace';
import { enrichJobDetails } from '../shared/jobContextResolver';
import {
  FRAME_AUTOFILL_TIMEOUT_MS,
  FRAME_PROBE_TIMEOUT_MS,
  FRAME_SCAN_TIMEOUT_MS
} from '../shared/autofillTimeouts';

export interface ScannedFieldMessage {
  id: string;
  frameId: number;
  type: string;
  labelText: string;
  placeholder?: string;
  name?: string;
  options?: string[];
  canonicalKey?: string;
  proposedValue?: string;
  confidence: string;
  reason?: string;
}

interface FrameScanResult {
  frameId: number;
  jobDetails: JobDetails;
  fields: Omit<ScannedFieldMessage, 'frameId'>[];
}

async function getFrameIds(tabId: number): Promise<number[]> {
  try {
    const frames = await chrome.webNavigation.getAllFrames({ tabId });
    if (frames?.length) {
      return frames.map((f) => f.frameId);
    }
  } catch {
    // Fall back to main frame when webNavigation is unavailable.
  }
  return [0];
}

function sendToFrame<T>(tabId: number, frameId: number, message: Record<string, unknown>): Promise<T | null> {
  return new Promise((resolve) => {
    chrome.tabs.sendMessage(tabId, message, { frameId }, (response) => {
      if (chrome.runtime.lastError) {
        resolve(null);
        return;
      }
      resolve(response as T);
    });
  });
}

async function getReachableFrameIds(tabId: number, candidateFrameIds: number[]): Promise<number[]> {
  const reachable: number[] = [];

  await Promise.all(
    candidateFrameIds.map(async (frameId) => {
      const response = await sendToFrameWithTimeout<{ ok?: boolean }>(
        tabId,
        frameId,
        { action: 'ping' },
        FRAME_PROBE_TIMEOUT_MS
      );
      if (response?.ok) reachable.push(frameId);
    })
  );

  return [...new Set(reachable)].sort((a, b) => a - b);
}

function sendToFrameWithTimeout<T>(
  tabId: number,
  frameId: number,
  message: Record<string, unknown>,
  timeoutMs = FRAME_AUTOFILL_TIMEOUT_MS
): Promise<T | null> {
  return Promise.race([
    sendToFrame<T>(tabId, frameId, message),
    new Promise<null>((resolve) => {
      setTimeout(() => resolve(null), timeoutMs);
    })
  ]);
}

function mergeJobDetails(frameResults: FrameScanResult[]): JobDetails {
  const primary =
    frameResults.reduce((best, current) =>
      current.fields.length > best.fields.length ? current : best
    ) ?? frameResults[0];

  const merged: JobDetails = { ...primary.jobDetails };

  for (const frame of frameResults) {
    const details = frame.jobDetails;
    if (details.company && details.company !== 'Unknown Company') {
      merged.company = details.company;
    }
    if (details.role && details.role !== 'Unknown Role') {
      merged.role = details.role;
    }
    if (details.location && !['Unspecified Location', 'Remote / Unspecified'].includes(details.location)) {
      merged.location = details.location;
    }
    if (details.platform && details.platform !== 'Generic') {
      merged.platform = details.platform;
    }
  }

  return merged;
}

export async function scanAllFrames(
  tabId: number,
  profile: UserProfile,
  operationId?: string
): Promise<{ success: boolean; jobDetails?: JobDetails; fields?: ScannedFieldMessage[]; error?: string }> {
  const frameIds = await getFrameIds(tabId);
  const frameResults: FrameScanResult[] = [];

  traceStep(operationId, 'scan', 'frames_discovered', 'background:scan', {
    tabId,
    frameIds,
    frameCount: frameIds.length
  });

  for (const frameId of frameIds) {
    traceStep(operationId, 'scan', 'frame_scan_start', 'background:scan', { tabId, frameId });

    const response = await sendToFrameWithTimeout<{
      success: boolean;
      jobDetails: JobDetails;
      fields: Omit<ScannedFieldMessage, 'frameId'>[];
      error?: string;
    }>(tabId, frameId, { action: 'scan', profile, operationId, skipHighlight: true }, FRAME_SCAN_TIMEOUT_MS);

    traceStep(operationId, 'scan', 'frame_scan_end', 'background:scan', {
      tabId,
      frameId,
      success: response?.success ?? false,
      fieldCount: response?.fields?.length ?? 0,
      error: response?.error
    });

    if (response?.success && response.fields?.length) {
      frameResults.push({
        frameId,
        jobDetails: response.jobDetails,
        fields: response.fields
      });
    }
  }

  if (frameResults.length === 0) {
    logToServer({
      level: 'warn',
      source: 'background:scan',
      message: 'No form fields detected in any frame',
      detail: { tabId, frameCount: frameIds.length, operationId }
    });
    return { success: false, error: 'No form fields detected in any frame.' };
  }

  const tab = await chrome.tabs.get(tabId).catch(() => null);
  const mergedDetails = enrichJobDetails(mergeJobDetails(frameResults), tab?.url, tab?.title);

  const fields = frameResults.flatMap((result) =>
    result.fields.map((field) => ({ ...field, frameId: result.frameId }))
  );

  traceStep(operationId, 'scan', 'merge_complete', 'background:scan', {
    tabId,
    frameCount: frameIds.length,
    framesWithFields: frameResults.length,
    totalFields: fields.length
  });

  return {
    success: true,
    jobDetails: mergedDetails,
    fields
  };
}

export async function autofillCompleteAllFrames(
  tabId: number,
  profile: UserProfile,
  overrides?: Record<string, string>,
  targetFrameIds?: number[],
  operationId?: string
): Promise<{
  success: boolean;
  filledCount: number;
  errors: { label: string; error: string; fieldId?: string }[];
  skippedFields: { label: string; reason: string; fieldId: string; canonicalKey?: string }[];
}> {
  const allFrameIds = await getFrameIds(tabId);
  const requested =
    targetFrameIds?.length ?
      targetFrameIds.filter((id) => allFrameIds.includes(id))
    : allFrameIds;
  const frameIds = await getReachableFrameIds(tabId, requested);

  let filledCount = 0;
  const errors: { label: string; error: string; fieldId?: string }[] = [];
  const skippedFields: { label: string; reason: string; fieldId: string; canonicalKey?: string }[] = [];

  traceStep(operationId, 'autofill', 'frames_targeted', 'background:autofill', {
    tabId,
    frameIds,
    requestedFrames: requested,
    frameCount: frameIds.length,
    overrideCount: Object.keys(overrides || {}).length
  });

  if (!frameIds.length) {
    const message = 'No reachable frames with ApplyPilot loaded on this tab.';
    logToServer({
      level: 'warn',
      source: 'background:autofill-complete',
      message,
      detail: { tabId, requestedFrames: requested, operationId }
    });
    return {
      success: false,
      filledCount: 0,
      errors: [{ label: 'frames', error: message }],
      skippedFields: []
    };
  }

  const results = await Promise.all(
    frameIds.map(async (frameId) => {
      traceStep(operationId, 'autofill', 'frame_autofill_start', 'background:autofill', {
        tabId,
        frameId
      });

      const response = await sendToFrameWithTimeout<{
        success: boolean;
        filledCount?: number;
        errors?: { label: string; error: string; fieldId?: string }[];
        skippedFields?: { label: string; reason: string; fieldId: string; canonicalKey?: string }[];
        error?: string;
      }>(tabId, frameId, {
        action: 'autofill-complete',
        profile,
        overrides: overrides || {},
        operationId
      });

      if (!response) {
        errors.push({
          label: `frame:${frameId}`,
          error: 'Frame autofill timed out or unreachable'
        });
        traceStep(operationId, 'autofill', 'frame_autofill_timeout', 'background:autofill', {
          tabId,
          frameId,
          timeoutMs: FRAME_AUTOFILL_TIMEOUT_MS
        });
        logToServer({
          level: 'warn',
          source: 'background:autofill-complete',
          message: `Frame ${frameId} autofill timed out`,
          detail: { tabId, frameId, timeoutMs: FRAME_AUTOFILL_TIMEOUT_MS, operationId }
        });
        return 0;
      }

      traceStep(operationId, 'autofill', 'frame_autofill_end', 'background:autofill', {
        tabId,
        frameId,
        success: response.success,
        filledCount: response.filledCount ?? 0,
        errorCount: response.errors?.length ?? 0,
        error: response.error
      });

      if (response.success) {
        if (response.errors?.length) {
          errors.push(...response.errors);
        }
        if (response.skippedFields?.length) {
          skippedFields.push(...response.skippedFields);
        }
        return response.filledCount ?? 0;
      }

      if (response.error) {
        errors.push({ label: `frame:${frameId}`, error: response.error });
      }
      return 0;
    })
  );

  filledCount = results.reduce((sum, count) => sum + count, 0);

  endTrace(operationId, 'autofill', 'background:autofill', {
    tabId,
    success: true,
    filledCount,
    errorCount: errors.length,
    skippedCount: skippedFields.length,
    frameCount: frameIds.length
  });

  logAutofillResult('background:autofill-complete', {
    filledCount,
    errors,
    detail: {
      tabId,
      frameCount: frameIds.length,
      targetedFrames: frameIds,
      operationId,
      skippedCount: skippedFields.length
    }
  });

  return { success: true, filledCount, errors, skippedFields };
}

export async function autofillAllFrames(
  tabId: number,
  fields: { id: string; proposedValue: string; frameId?: number }[],
  profile: UserProfile
): Promise<{ success: boolean; filledCount: number; errors: { label: string; error: string }[] }> {
  const byFrame = new Map<number, { id: string; proposedValue: string }[]>();

  for (const field of fields) {
    const frameId = field.frameId ?? 0;
    if (!byFrame.has(frameId)) {
      byFrame.set(frameId, []);
    }
    byFrame.get(frameId)!.push({ id: field.id, proposedValue: field.proposedValue });
  }

  let filledCount = 0;
  const errors: { label: string; error: string }[] = [];

  for (const [frameId, frameFields] of byFrame) {
    const response = await sendToFrame<{
      success: boolean;
      filledCount?: number;
      errors?: { label: string; error: string }[];
    }>(tabId, frameId, {
      action: 'autofill',
      fields: frameFields,
      profile
    });

    if (response?.success) {
      filledCount += response.filledCount ?? 0;
      if (response.errors?.length) {
        errors.push(...response.errors);
      }
    }
  }

  return { success: true, filledCount, errors };
}
