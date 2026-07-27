export type ServerLogLevel = 'error' | 'warn' | 'info';

export interface ServerLogEntry {
  level: ServerLogLevel;
  source: string;
  message: string;
  detail?: Record<string, unknown>;
  url?: string;
  stack?: string;
}

import { getLogUrl } from './apiConfig';

function currentUrl(): string | undefined {
  try {
    if (typeof location !== 'undefined' && location.href) {
      return location.href;
    }
  } catch {
    // ignore — extension pages may restrict location
  }
  return undefined;
}

/** Fire-and-forget log to the CareerOS API. */
export function logToServer(entry: ServerLogEntry): void {
  const payload = {
    ...entry,
    ts: new Date().toISOString(),
    url: entry.url || currentUrl()
  };

  void (async () => {
    try {
      await fetch(await getLogUrl(), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        keepalive: true
      });
    } catch {
      // Server offline — console only
    }
  })();

  const prefix = `[ApplyPilot:${entry.source}]`;
  if (entry.level === 'error') {
    console.error(prefix, entry.message, entry.detail || '');
  } else if (entry.level === 'warn') {
    console.warn(prefix, entry.message, entry.detail || '');
  } else {
    console.log(prefix, entry.message, entry.detail || '');
  }
}

export function logAutofillResult(
  source: string,
  result: {
    filledCount?: number;
    errors?: { label: string; error: string }[];
    skippedFields?: { label: string; reason: string; fieldId?: string; category?: string }[];
    issueSummary?: string;
    url?: string;
    company?: string;
    detail?: Record<string, unknown>;
  }
): void {
  if (result.skippedFields?.length) {
    for (const field of result.skippedFields) {
      logToServer({
        level: field.category === 'error' ? 'error' : 'warn',
        source: `${source}:skipped`,
        message: `${field.label}: ${field.reason}`,
        detail: {
          category: field.category,
          fieldId: field.fieldId,
          company: result.company,
          filledCount: result.filledCount,
          ...result.detail
        },
        url: result.url
      });
    }
  }

  if (result.errors?.length) {
    for (const err of result.errors) {
      const isFrameIssue =
        err.label.startsWith('frame:') ||
        err.label === 'frames' ||
        /timed out|unreachable|not loaded/i.test(err.error);
      logToServer({
        level: isFrameIssue ? 'warn' : 'error',
        source,
        message: isFrameIssue ? `Autofill frame issue: ${err.label}` : `Autofill field failed: ${err.label}`,
        detail: {
          error: err.error,
          company: result.company,
          filledCount: result.filledCount,
          ...result.detail
        },
        url: result.url
      });
    }
  }

  const issueCount = result.skippedFields?.length ?? result.errors?.length ?? 0;
  logToServer({
    level: issueCount ? 'warn' : 'info',
    source,
    message: issueCount
      ? `Autofill finished with ${issueCount} field issue(s)${result.issueSummary ? ` — ${result.issueSummary}` : ''}`
      : 'Autofill finished',
    detail: {
      filledCount: result.filledCount ?? 0,
      errorCount: result.errors?.length ?? 0,
      skippedCount: result.skippedFields?.length ?? 0,
      issueSummary: result.issueSummary,
      company: result.company,
      ...result.detail
    },
    url: result.url
  });
}
