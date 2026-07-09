import {
  buttonTextMatchesSubmit,
  getSubmitTrackerConfig,
  SubmitTrackerConfig
} from '../shared/submitTrackerConfig';
import { extractJobContext, isJobApplicationUrl, isSubmissionConfirmationUrl, isWorkdaySubmissionSuccess } from '../shared/jobPageDetection';
import { logToServer } from '../shared/serverLog';

const DEDUPE_STORAGE_KEY = 'jobfill-submit-dedupe';

function getButtonLabel(element: HTMLElement): string {
  const parts = [
    element.getAttribute('aria-label'),
    element.getAttribute('data-automation-id')?.replace(/-/g, ' '),
    element.textContent,
    element instanceof HTMLInputElement ? element.value : ''
  ];
  return parts
    .filter(Boolean)
    .join(' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function isExtensionUi(element: HTMLElement): boolean {
  return Boolean(element.closest('#jobfill-floating-wrapper, #jobfill-floating-button'));
}

function isSubmitControl(element: HTMLElement): boolean {
  if (isExtensionUi(element)) return false;

  const tag = element.tagName;
  if (tag === 'INPUT') {
    const type = (element as HTMLInputElement).type?.toLowerCase();
    return type === 'submit' || type === 'button';
  }
  if (tag === 'BUTTON') return true;
  if (element.getAttribute('role') === 'button') return true;

  const automationId = element.getAttribute('data-automation-id') || '';
  if (/submit|apply|bottom-navigation-next-button/i.test(automationId)) return true;

  return false;
}

function normalizeUrlForDedupe(url: string): string {
  try {
    const parsed = new URL(url);
    parsed.search = '';
    return parsed.href;
  } catch {
    return url.split('?')[0];
  }
}

async function wasRecentlyRecorded(url: string, config: SubmitTrackerConfig): Promise<boolean> {
  const key = normalizeUrlForDedupe(url);
  const stored = await chrome.storage.session.get(DEDUPE_STORAGE_KEY);
  const map = (stored[DEDUPE_STORAGE_KEY] || {}) as Record<string, number>;
  const last = map[key];
  if (!last) return false;
  return Date.now() - last < config.dedupeMinutes * 60_000;
}

async function markRecorded(url: string): Promise<void> {
  const key = normalizeUrlForDedupe(url);
  const stored = await chrome.storage.session.get(DEDUPE_STORAGE_KEY);
  const map = (stored[DEDUPE_STORAGE_KEY] || {}) as Record<string, number>;
  map[key] = Date.now();
  await chrome.storage.session.set({ [DEDUPE_STORAGE_KEY]: map });
}

function showSubmitToast(company: string, role: string): void {
  const id = 'jobfill-submit-toast';
  document.getElementById(id)?.remove();

  const toast = document.createElement('div');
  toast.id = id;
  toast.textContent = `Applied tracked · ${company} — ${role}`;
  Object.assign(toast.style, {
    position: 'fixed',
    bottom: '24px',
    left: '50%',
    transform: 'translateX(-50%)',
    zIndex: '2147483646',
    background: 'rgba(10, 18, 16, 0.95)',
    color: '#ecfdf5',
    border: '1px solid rgba(46, 229, 157, 0.35)',
    borderRadius: '999px',
    padding: '10px 18px',
    fontSize: '13px',
    fontFamily: 'system-ui, sans-serif',
    boxShadow: '0 8px 24px rgba(0,0,0,0.35)',
    pointerEvents: 'none'
  });
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 3200);
}

async function recordSubmit(
  trigger: 'button_click' | 'form_submit' | 'confirmation_page',
  buttonText: string,
  config: SubmitTrackerConfig
): Promise<void> {
  const url = location.href;
  if (config.requireJobPageUrl && !isJobApplicationUrl(url) && trigger !== 'confirmation_page') return;
  if (await wasRecentlyRecorded(url, config)) return;

  const { company, role, location: locationText, platform } = extractJobContext(document);

  chrome.runtime.sendMessage(
    {
      action: 'record-job-submit',
      payload: {
        url,
        company,
        role,
        location: locationText,
        platform,
        trigger,
        buttonText
      }
    },
    (response) => {
      if (chrome.runtime.lastError || !response?.success) return;
      void markRecorded(url);
      if (config.showToast) {
        showSubmitToast(response.company || company, response.role || role);
      }
      logToServer({
        level: 'info',
        source: 'submit-tracker',
        message: `Application submitted: ${response.company || company}`,
        detail: { role: response.role || role, trigger, buttonText, url },
        url
      });
    }
  );
}

async function handleSubmitInteraction(
  element: HTMLElement,
  trigger: 'button_click' | 'form_submit'
): Promise<void> {
  const config = await getSubmitTrackerConfig();
  if (!config.enabled) return;

  const label = getButtonLabel(element);
  if (!label && trigger === 'button_click') return;
  if (trigger === 'button_click' && !isSubmitControl(element)) return;
  if (!buttonTextMatchesSubmit(label, config) && trigger === 'button_click') return;

  await recordSubmit(trigger, label, config);
}

let initialized = false;
let lastHref = location.href;

async function watchForConfirmationPage(): Promise<void> {
  const config = await getSubmitTrackerConfig();
  if (!config.enabled) return;
  if (location.href === lastHref && !isWorkdaySubmissionSuccess(document)) return;
  lastHref = location.href;
  if (!isSubmissionConfirmationUrl(location.href) && !isWorkdaySubmissionSuccess(document)) return;
  await recordSubmit('confirmation_page', 'confirmation page', config);
}

export function initSubmitTracker(): void {
  if (initialized) return;
  initialized = true;
  lastHref = location.href;

  document.addEventListener(
    'click',
    (event) => {
      const target = event.target as HTMLElement | null;
      if (!target) return;
      const button = target.closest('button, input[type="submit"], input[type="button"], [role="button"]') as
        | HTMLElement
        | null;
      if (!button) return;
      void handleSubmitInteraction(button, 'button_click');
    },
    true
  );

  window.addEventListener(
    'submit',
    (event) => {
      const form = event.target as HTMLFormElement | null;
      if (!form) return;
      const submitter =
        (event as SubmitEvent).submitter ||
        (form.querySelector('button[type="submit"], input[type="submit"]') as HTMLElement | null);
      if (submitter) {
        void handleSubmitInteraction(submitter as HTMLElement, 'form_submit');
        return;
      }
      void getSubmitTrackerConfig().then((config) => {
        if (!config.enabled) return;
        void recordSubmit('form_submit', 'form submit', config);
      });
    },
    true
  );

  window.addEventListener('popstate', () => void watchForConfirmationPage());
  window.addEventListener('hashchange', () => void watchForConfirmationPage());

  const observer = new MutationObserver(() => {
    void watchForConfirmationPage();
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });

  void watchForConfirmationPage();
  window.setInterval(() => {
    void watchForConfirmationPage();
  }, 2500);
}
