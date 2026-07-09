export interface SubmitTrackerConfig {
  /** Master switch for automatic submit detection on job sites. */
  enabled: boolean;
  /**
   * When true, only count final submit-style buttons (not multi-step "Save and Continue").
   * Set false to also count continue/next steps as an application.
   */
  finalSubmitOnly: boolean;
  /** Case-insensitive substrings or regex strings matched against button text / aria-label. */
  submitButtonPatterns: string[];
  /** Extra patterns when finalSubmitOnly is false (e.g. "save and continue"). */
  continueButtonPatterns: string[];
  /** Only track on URLs that look like job application pages. */
  requireJobPageUrl: boolean;
  /** Ignore duplicate submit clicks for the same URL within this window (minutes). */
  dedupeMinutes: number;
  /** Show a brief on-page toast when an application is counted. */
  showToast: boolean;
}

export const DEFAULT_SUBMIT_TRACKER_CONFIG: SubmitTrackerConfig = {
  enabled: true,
  finalSubmitOnly: true,
  submitButtonPatterns: [
    '\\bsubmit\\b',
    'send application',
    'complete application',
    'review and submit',
    'apply for (this )?job',
    'submit application',
    'apply now',
    'confirm application',
    'finish application',
    '\\bapply\\b'
  ],
  continueButtonPatterns: ['save and continue', '\\bnext\\b', 'continue application'],
  requireJobPageUrl: true,
  dedupeMinutes: 60,
  showToast: true
};

const STORAGE_KEY = 'submitTrackerConfig';

let cachedConfig: SubmitTrackerConfig | null = null;

export function mergeSubmitTrackerConfig(
  partial?: Partial<SubmitTrackerConfig> | null
): SubmitTrackerConfig {
  return { ...DEFAULT_SUBMIT_TRACKER_CONFIG, ...partial };
}

export async function getSubmitTrackerConfig(): Promise<SubmitTrackerConfig> {
  if (cachedConfig) return cachedConfig;

  try {
    const stored = await chrome.storage.local.get(STORAGE_KEY);
    cachedConfig = mergeSubmitTrackerConfig(stored[STORAGE_KEY] as Partial<SubmitTrackerConfig>);
  } catch {
    cachedConfig = { ...DEFAULT_SUBMIT_TRACKER_CONFIG };
  }

  return cachedConfig;
}

export function setSubmitTrackerConfig(config: Partial<SubmitTrackerConfig>): void {
  cachedConfig = mergeSubmitTrackerConfig(config);
  void chrome.storage.local.set({ [STORAGE_KEY]: cachedConfig });
}

export function patternMatches(text: string, pattern: string): boolean {
  const trimmed = text.replace(/\s+/g, ' ').trim();
  if (!trimmed) return false;
  try {
    return new RegExp(pattern, 'i').test(trimmed);
  } catch {
    return trimmed.toLowerCase().includes(pattern.toLowerCase());
  }
}

export function buttonTextMatchesSubmit(text: string, config: SubmitTrackerConfig): boolean {
  const patterns = config.finalSubmitOnly
    ? config.submitButtonPatterns
    : [...config.submitButtonPatterns, ...config.continueButtonPatterns];

  return patterns.some((pattern) => patternMatches(text, pattern));
}
