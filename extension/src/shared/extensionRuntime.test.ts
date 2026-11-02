import { describe, expect, it, vi, afterEach } from 'vitest';

describe('extensionRuntime', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('returns null when no extension runtime is available', async () => {
    vi.stubGlobal('chrome', undefined);
    vi.stubGlobal('browser', undefined);
    const { getExtensionRuntime, isExtensionContextValid } = await import('./extensionRuntime');
    expect(getExtensionRuntime()).toBeNull();
    expect(isExtensionContextValid()).toBe(false);
  });

  it('uses chrome.runtime when available', async () => {
    const sendMessage = vi.fn();
    vi.stubGlobal('chrome', { runtime: { id: 'abc', sendMessage, lastError: undefined } });
    vi.stubGlobal('browser', undefined);
    const { requireExtensionRuntime } = await import('./extensionRuntime');
    expect(requireExtensionRuntime()).toBe(chrome.runtime);
  });

  it('throws a friendly error when runtime is missing', async () => {
    vi.stubGlobal('chrome', undefined);
    vi.stubGlobal('browser', undefined);
    const { requireExtensionRuntime, ExtensionContextInvalidError } = await import('./extensionRuntime');
    expect(() => requireExtensionRuntime()).toThrow(ExtensionContextInvalidError);
  });
});

describe('sendRuntimeMessage', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('rejects when extension runtime is unavailable', async () => {
    vi.stubGlobal('chrome', undefined);
    vi.stubGlobal('browser', undefined);
    const { sendRuntimeMessage } = await import('./runtimeMessage');
    await expect(sendRuntimeMessage({ action: 'ping' }, 100, 'Ping')).rejects.toThrow(
      'ApplyPilot lost connection'
    );
  });
});
