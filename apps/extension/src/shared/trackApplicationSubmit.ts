import { extractJobContext } from './jobPageDetection';

export interface MarkSubmittedResult {
  success: boolean;
  applicationId?: string;
  company?: string;
  role?: string;
  location?: string;
  platform?: string;
  submittedAt?: string;
  error?: string;
}

export async function markApplicationSubmitted(options?: {
  url?: string;
  company?: string;
  role?: string;
  location?: string;
  platform?: string;
  trigger?: string;
}): Promise<MarkSubmittedResult> {
  const pageContext =
    typeof document !== 'undefined' ? extractJobContext(document) : null;
  const url = options?.url || (typeof document !== 'undefined' ? document.location.href : '');

  return new Promise((resolve) => {
    chrome.runtime.sendMessage(
      {
        action: 'record-job-submit',
        payload: {
          url,
          company: options?.company || pageContext?.company || 'Unknown Company',
          role: options?.role || pageContext?.role || 'Unknown Role',
          location: options?.location ?? pageContext?.location,
          platform: options?.platform ?? pageContext?.platform,
          trigger: options?.trigger || 'applypilot_button',
          buttonText: 'Submit'
        }
      },
      (response) => {
        if (chrome.runtime.lastError) {
          resolve({ success: false, error: chrome.runtime.lastError.message });
          return;
        }
        resolve((response as MarkSubmittedResult) ?? { success: false });
      }
    );
  });
}
