import '../shared/process-shim';
import { detectAdapter } from '../adapters';
import { scanPage, ScannedField } from './domScanner';
import { classifyFields } from './fieldClassifier';
import { runFullPageAutofill } from './autofillRunner';
import { clearHighlights, highlightField } from './autofillEngine';
import { UserProfile } from '../shared/types';
import { enrichProfile, hasContactProfileData } from '../profile/profileStore';
import { formatAutofillGapMessage } from './autofillRunner';
import { mountFloatingWidget } from './floatingWidget';
import { initSubmitTracker } from './submitTracker';
import { AUTOFILL_MESSAGES, cycleMessages } from '../shared/loadingMessages';
import { logToServer, logAutofillResult } from '../shared/serverLog';
import { createOperationId, endTrace, failTrace, startTrace, traceStep } from '../shared/actionTrace';

let activeScannedFields: ScannedField[] = [];

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.action === 'scan') {
    (async () => {
      const operationId = message.operationId as string | undefined;
      try {
        traceStep(operationId, 'scan', 'adapter_detect', 'content:scan');
        const adapter = detectAdapter(document);
        const jobDetails = adapter.extractJobDetails(document);

        traceStep(operationId, 'scan', 'dom_scan_start', 'content:scan');
        const fields = scanPage(document);
        activeScannedFields = fields;
        traceStep(operationId, 'scan', 'dom_scan_end', 'content:scan', { fieldCount: fields.length });

        const profile = enrichProfile(message.profile as UserProfile);
        traceStep(operationId, 'scan', 'classify_start', 'content:scan', { fieldCount: fields.length });
        const classified = await classifyFields(
          fields,
          profile,
          jobDetails.company,
          document.location.hostname
        );
        traceStep(operationId, 'scan', 'classify_end', 'content:scan', {
          classifiedCount: classified.length
        });

        const responseFields = classified.map((c) => ({
          id: c.id,
          type: c.scannedField.type,
          labelText: c.scannedField.labelText,
          placeholder: c.scannedField.placeholder,
          htmlId: c.scannedField.htmlId,
          options: c.scannedField.options,
          canonicalKey: c.canonicalKey,
          proposedValue: c.proposedValue,
          confidence: c.confidence,
          reason: c.reason
        }));

        clearHighlights(document);
        classified.forEach((c) => {
          if (c.proposedValue) {
            highlightField(c.scannedField.element, c.confidence);
          }
        });

        traceStep(operationId, 'scan', 'respond', 'content:scan', {
          fieldCount: responseFields.length,
          company: jobDetails.company
        });

        sendResponse({
          success: true,
          jobDetails,
          fields: responseFields
        });
      } catch (err: any) {
        console.error('Scan error:', err);
        failTrace(message.operationId, 'scan', 'content:scan', err.message || 'Scan failed', {
          url: document.location.href
        });
        logToServer({
          level: 'error',
          source: 'content:scan',
          message: err.message || 'Scan failed',
          stack: err.stack,
          detail: { url: document.location.href }
        });
        sendResponse({ success: false, error: err.message });
      }
    })();
    return true;
  }

  if (message.action === 'autofill' || message.action === 'autofill-complete') {
    (async () => {
      const operationId = message.operationId as string | undefined;
      let company = '';
      try {
        traceStep(operationId, 'autofill', 'handler_start', 'content:autofill', {
          action: message.action
        });
        const profile = enrichProfile(message.profile as UserProfile);
        const overrides = (message.overrides || {}) as Record<string, string>;

        if (message.action === 'autofill') {
          const approvedFields = message.fields as { id: string; proposedValue: string }[];
          if (!approvedFields?.length) {
            failTrace(operationId, 'autofill', 'content:autofill', 'Missing approved fields');
            sendResponse({ success: false, error: 'Missing approved fields.' });
            return;
          }
          for (const approved of approvedFields) {
            if (approved.proposedValue?.trim()) {
              overrides[approved.id] = approved.proposedValue.trim();
            }
          }
          traceStep(operationId, 'autofill', 'approved_fields', 'content:autofill', {
            count: approvedFields.length
          });
        }

        try {
          company = detectAdapter(document).extractJobDetails(document).company || '';
        } catch {}

        activeScannedFields = scanPage(document);
        traceStep(operationId, 'autofill', 'run_full_page_start', 'content:autofill', {
          overrideCount: Object.keys(overrides).length,
          company
        });
        const { filledCount, errors } = await runFullPageAutofill(
          profile,
          overrides,
          company,
          document.location.hostname,
          document,
          operationId
        );
        traceStep(operationId, 'autofill', 'run_full_page_end', 'content:autofill', {
          filledCount,
          errorCount: errors.length
        });

        clearHighlights(document);
        logAutofillResult('content:autofill', {
          filledCount,
          errors,
          url: document.location.href,
          company,
          detail: { operationId }
        });
        sendResponse({ success: true, filledCount, errors });
      } catch (err: any) {
        console.error('[JobFill] Autofill error:', err);
        failTrace(operationId, 'autofill', 'content:autofill', err.message || 'Autofill failed', {
          url: document.location.href,
          company
        });
        logToServer({
          level: 'error',
          source: 'content:autofill',
          message: err.message || 'Autofill failed',
          stack: err.stack,
          detail: { url: document.location.href, company }
        });
        sendResponse({ success: false, error: err.message, filledCount: 0, errors: [] });
      }
    })();
    return true;
  }

  if (message.action === 'highlight') {
    const enabled = message.enabled as boolean;
    if (enabled) {
      const fields = scanPage(document);
      fields.forEach((f) => {
        highlightField(f.element, 'medium');
      });
    } else {
      clearHighlights(document);
    }
    sendResponse({ success: true });
    return;
  }
});

function countFillableControls(doc: Document): number {
  return doc.querySelectorAll(
    'input:not([type="hidden"]):not([type="submit"]):not([type="button"]), textarea, select, [role="combobox"]'
  ).length;
}

function isJobApplicationUrl(href: string): boolean {
  return (
    (/myworkdaysite\.com|myworkdayjobs\.com|boards\.greenhouse\.io|jobs\.lever\.co|jobs\.ashbyhq\.com/i.test(
      href
    ) &&
      /\/(apply|job|postings)/i.test(href)) ||
    /autofillWithResume/i.test(href)
  );
}

function shouldMountFloatingWidget(doc: Document): boolean {
  const href = doc.location.href;
  const fillable = countFillableControls(doc);

  if (window !== window.top) {
    try {
      const topHref = window.top?.location.href || '';
      if (isJobApplicationUrl(topHref)) return false;
    } catch {
      return fillable >= 2;
    }
    return fillable >= 3;
  }

  if (isJobApplicationUrl(href)) return true;
  return fillable >= 3;
}

let widgetMountObserver: MutationObserver | null = null;

function injectFloatingCopilotButton() {
  if (document.getElementById('jobfill-floating-wrapper')) return;
  if (!shouldMountFloatingWidget(document)) return;

  logToServer({
    level: 'info',
    source: 'content:widget',
    message: 'Mounted floating widget',
    detail: {
      frame: window === window.top ? 'top' : 'child',
      fillableCount: countFillableControls(document)
    },
    url: document.location.href
  });

  const widget = mountFloatingWidget();

  widget.onClick(async () => {
    widget.setDisabled(true);
    widget.setState('loading', 'Reading form…');

    const operationId = createOperationId('autofill');
    startTrace(operationId, 'autofill', 'content:widget', { url: document.location.href });

    const stopMessages = cycleMessages(AUTOFILL_MESSAGES, (message) => {
      widget.setState('loading', message);
    });

    chrome.runtime.sendMessage({ action: 'get-profile-for-autofill' }, async (response) => {
      if (chrome.runtime.lastError) {
        stopMessages();
        failTrace(operationId, 'autofill', 'content:widget', chrome.runtime.lastError.message || 'Profile fetch failed');
        widget.setState('warning', 'Try again');
        logToServer({
          level: 'error',
          source: 'content:widget',
          message: chrome.runtime.lastError.message || 'Profile fetch failed',
          url: document.location.href
        });
        setTimeout(() => {
          widget.setState('idle', 'Fill application');
          widget.setDisabled(false);
        }, 2800);
        return;
      }

      if (!response?.success || !response.profile) {
        stopMessages();
        failTrace(operationId, 'autofill', 'content:widget', 'Profile not available');
        widget.setState('warning', 'Open dashboard');
        setTimeout(() => {
          widget.setState('idle', 'Fill application');
          widget.setDisabled(false);
        }, 3200);
        return;
      }

      const profile = enrichProfile(response.profile as UserProfile);
      if (!hasContactProfileData(profile)) {
        stopMessages();
        failTrace(operationId, 'autofill', 'content:widget', 'Profile incomplete');
        widget.setState('warning', 'Set up profile');
        setTimeout(() => {
          widget.setState('idle', 'Fill application');
          widget.setDisabled(false);
        }, 3200);
        return;
      }

      traceStep(operationId, 'autofill', 'profile_loaded', 'content:widget');
      chrome.runtime.sendMessage(
        { action: 'autofill-active-tab', profile, operationId },
        (autofillResponse) => {
          stopMessages();

          if (chrome.runtime.lastError || !autofillResponse?.success) {
            failTrace(
              operationId,
              'autofill',
              'content:widget',
              autofillResponse?.error || chrome.runtime.lastError?.message || 'Autofill failed'
            );
            widget.setState('warning', 'Fill failed');
            logToServer({
              level: 'error',
              source: 'content:widget',
              message: autofillResponse?.error || chrome.runtime.lastError?.message || 'Autofill failed',
              url: document.location.href
            });
          } else {
            logAutofillResult('content:widget', {
              filledCount: autofillResponse.filledCount,
              errors: autofillResponse.errors,
              url: document.location.href
            });

            const gapMessage = formatAutofillGapMessage({
              missingInProfile: [],
              stillEmptyOnPage: [],
              resumeMissing: !profile.resume,
              resumeNotAttached: false
            });

            if (autofillResponse.errors?.length) {
              widget.setState('warning', `${autofillResponse.errors.length} field(s) skipped`);
            } else if (gapMessage) {
              widget.setState('warning', gapMessage.slice(0, 28));
            } else if (autofillResponse.filledCount === 0) {
              widget.setState('warning', 'No fields filled');
            } else {
              widget.setState('success', `Filled ${autofillResponse.filledCount} fields`);
            }
          }

          setTimeout(() => {
            widget.setState('idle', 'Fill application');
            widget.setDisabled(false);
          }, 2800);
        }
      );
    });
  });
}

function scheduleFloatingWidgetMount(): void {
  const attempt = () => injectFloatingCopilotButton();

  attempt();
  [1000, 2500, 5000, 10000].forEach((delay) => setTimeout(attempt, delay));

  if (widgetMountObserver || !document.body) return;

  let debounce: ReturnType<typeof setTimeout> | null = null;
  widgetMountObserver = new MutationObserver(() => {
    if (debounce) clearTimeout(debounce);
    debounce = setTimeout(attempt, 400);
  });
  widgetMountObserver.observe(document.body, { childList: true, subtree: true });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', scheduleFloatingWidgetMount);
} else {
  scheduleFloatingWidgetMount();
}

window.addEventListener(
  'submit',
  (event) => {
    try {
      const form = event.target as HTMLFormElement;
      if (!form) return;

      const fields = scanPage(document);
      fields.forEach((field) => {
        if (field.type === 'file') return;

        let value = '';
        if (field.element instanceof HTMLInputElement) {
          if (field.element.type === 'checkbox') {
            value = field.element.checked ? 'Yes' : 'No';
          } else if (field.element.type === 'radio') {
            if (field.element.checked) {
              value = field.labelText || field.element.value;
            } else {
              return;
            }
          } else {
            value = field.element.value;
          }
        } else if (field.element instanceof HTMLTextAreaElement) {
          value = field.element.value;
        } else if (field.element instanceof HTMLSelectElement) {
          value = field.element.options[field.element.selectedIndex]?.text || '';
        } else {
          value = field.element.textContent || '';
        }

        value = value.trim();
        const questionText = field.labelText || field.name || field.placeholder || '';

        if (questionText && questionText.length > 2 && value && value.length < 500) {
          chrome.runtime.sendMessage({
            action: 'learn-submitted-answer',
            questionText,
            fieldType: field.type,
            answer: value,
            options: field.options
          });
        }
      });
    } catch (err) {
      console.error('[JobFill Auto-learning] Error on form submission scan:', err);
    }
  },
  true
);

console.log('Arsenal JobFill content script initialized.');
initSubmitTracker();
