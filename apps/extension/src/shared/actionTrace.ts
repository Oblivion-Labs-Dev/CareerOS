import { logToServer } from './serverLog';

export type TraceOperation = 'scan' | 'autofill';

interface TraceState {
  operation: TraceOperation;
  startedAtMs: number;
  startedAt: string;
}

const activeTraces = new Map<string, TraceState>();

export function createOperationId(operation: TraceOperation): string {
  return `${operation}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function parseOperationStartMs(operationId: string): number | undefined {
  const match = operationId.match(/^(?:scan|autofill)-(\d+)-/);
  if (!match) return undefined;
  const ms = Number(match[1]);
  return Number.isFinite(ms) ? ms : undefined;
}

function resolveTraceState(operationId: string): TraceState | undefined {
  const existing = activeTraces.get(operationId);
  if (existing) return existing;

  const startedAtMs = parseOperationStartMs(operationId);
  if (startedAtMs === undefined) return undefined;

  return {
    operation: operationId.startsWith('autofill-') ? 'autofill' : 'scan',
    startedAtMs,
    startedAt: new Date(startedAtMs).toISOString()
  };
}

function baseDetail(
  operationId: string,
  operation: TraceOperation,
  phase: 'start' | 'step' | 'end' | 'error',
  extra?: Record<string, unknown>
) {
  const state = resolveTraceState(operationId);
  const now = Date.now();
  return {
    operation,
    operationId,
    phase,
    startedAt: state?.startedAt,
    at: new Date(now).toISOString(),
    elapsedMs: state ? now - state.startedAtMs : undefined,
    ...extra
  };
}

export function startTrace(
  operationId: string,
  operation: TraceOperation,
  source: string,
  detail?: Record<string, unknown>
): void {
  const startedAt = new Date().toISOString();
  activeTraces.set(operationId, {
    operation,
    startedAtMs: Date.now(),
    startedAt
  });

  logToServer({
    level: 'info',
    source: 'trace',
    message: `${operation}:start`,
    detail: baseDetail(operationId, operation, 'start', { traceSource: source, ...detail })
  });
}

export function traceStep(
  operationId: string | undefined,
  operation: TraceOperation,
  step: string,
  source: string,
  detail?: Record<string, unknown>
): void {
  if (!operationId) return;

  logToServer({
    level: 'info',
    source: 'trace',
    message: `${operation}:step:${step}`,
    detail: baseDetail(operationId, operation, 'step', {
      step,
      traceSource: source,
      ...detail
    })
  });
}

export function endTrace(
  operationId: string | undefined,
  operation: TraceOperation,
  source: string,
  detail?: Record<string, unknown>
): void {
  if (!operationId) return;

  const state = resolveTraceState(operationId);
  const endedAt = new Date().toISOString();
  const durationMs = state ? Date.now() - state.startedAtMs : undefined;
  activeTraces.delete(operationId);

  logToServer({
    level: 'info',
    source: 'trace',
    message: `${operation}:end`,
    detail: {
      operation,
      operationId,
      phase: 'end',
      traceSource: source,
      startedAt: state?.startedAt,
      endedAt,
      durationMs,
      ...detail
    }
  });
}

export function failTrace(
  operationId: string | undefined,
  operation: TraceOperation,
  source: string,
  error: string,
  detail?: Record<string, unknown>
): void {
  if (!operationId) return;

  const state = resolveTraceState(operationId);
  const endedAt = new Date().toISOString();
  const durationMs = state ? Date.now() - state.startedAtMs : undefined;
  activeTraces.delete(operationId);

  logToServer({
    level: 'error',
    source: 'trace',
    message: `${operation}:error`,
    detail: {
      operation,
      operationId,
      phase: 'error',
      traceSource: source,
      error,
      startedAt: state?.startedAt,
      endedAt,
      durationMs,
      ...detail
    }
  });
}
