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
    url?: string;
    company?: string;
    detail?: Record<string, unknown>;
  }
): void {
  if (result.errors?.length) {
    for (const err of result.errors) {
      logToServer({
        level: 'error',
        source,
        message: `Autofill field failed: ${err.label}`,
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

  logToServer({
    level: result.errors?.length ? 'warn' : 'info',
    source,
    message: result.errors?.length
      ? `Autofill finished with ${result.errors.length} error(s)`
      : 'Autofill finished',
    detail: {
      filledCount: result.filledCount ?? 0,
      errorCount: result.errors?.length ?? 0,
      company: result.company,
      ...result.detail
    },
    url: result.url
  });
}
