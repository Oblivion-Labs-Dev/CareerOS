import { requireExtensionRuntime } from './extensionRuntime';

export class RuntimeMessageTimeoutError extends Error {
  readonly timeoutMs: number;

  constructor(action: string, timeoutMs: number) {
    super(`${action} timed out after ${Math.round(timeoutMs / 1000)}s`);
    this.name = 'RuntimeMessageTimeoutError';
    this.timeoutMs = timeoutMs;
  }
}

export function sendRuntimeMessage<T>(
  message: Record<string, unknown>,
  timeoutMs: number,
  actionLabel = 'Request'
): Promise<T> {
  return new Promise((resolve, reject) => {
    let runtime: ReturnType<typeof requireExtensionRuntime>;
    try {
      runtime = requireExtensionRuntime();
    } catch (error) {
      reject(error);
      return;
    }

    const timer = window.setTimeout(() => {
      reject(new RuntimeMessageTimeoutError(actionLabel, timeoutMs));
    }, timeoutMs);

    runtime.sendMessage(message, (response) => {
      window.clearTimeout(timer);
      if (runtime.lastError) {
        reject(new Error(runtime.lastError.message));
        return;
      }
      resolve(response as T);
    });
  });
}