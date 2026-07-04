export interface AutofillLogConfig {
  /** Field has no canonical key and no proposed value (classifier could not map it). */
  unrecognizedFields: boolean;
  /** Field mapped to a profile key but profile value is empty. */
  missingProfileValue: boolean;
  /** We had a value but fillTextOrTextArea / fillSelect returned false. */
  fillReturnedFalse: boolean;
  /** Field is still empty on the page after autofill finishes. */
  stillEmpty: boolean;
  /** Internal rule skips (Rippling mismatch, EEO deferred to combobox pass, etc.). */
  skippedByRule: boolean;
}

export const DEFAULT_AUTOFILL_LOG_CONFIG: AutofillLogConfig = {
  unrecognizedFields: true,
  missingProfileValue: true,
  fillReturnedFalse: true,
  stillEmpty: true,
  skippedByRule: false
};

const STORAGE_KEY = 'autofillLogConfig';

let cachedConfig: AutofillLogConfig | null = null;

export function mergeAutofillLogConfig(
  partial?: Partial<AutofillLogConfig> | null
): AutofillLogConfig {
  return { ...DEFAULT_AUTOFILL_LOG_CONFIG, ...partial };
}

export async function getAutofillLogConfig(): Promise<AutofillLogConfig> {
  if (cachedConfig) return cachedConfig;

  try {
    const stored = await chrome.storage.local.get(STORAGE_KEY);
    cachedConfig = mergeAutofillLogConfig(stored[STORAGE_KEY] as Partial<AutofillLogConfig>);
  } catch {
    cachedConfig = { ...DEFAULT_AUTOFILL_LOG_CONFIG };
  }

  return cachedConfig;
}

export function setAutofillLogConfig(config: Partial<AutofillLogConfig>): void {
  cachedConfig = mergeAutofillLogConfig(config);
  void chrome.storage.local.set({ [STORAGE_KEY]: cachedConfig });
}

export function invalidateAutofillLogConfigCache(): void {
  cachedConfig = null;
}
