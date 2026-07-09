import '../shared/process-shim';
import { resolveJobContext } from '../shared/jobContextResolver';
import { scanPage, ScannedField } from './domScanner';
import { classifyFields } from './fieldClassifier';
import { runFullPageAutofill } from './autofillRunner';
import { clearHighlights, highlightField } from './autofillEngine';
import { UserProfile } from '../shared/types';
import { enrichProfile, hasContactProfileData } from '../profile/profileStore';
import { formatAutofillGapMessage } from './autofillRunner';
import { mountFloatingWidget } from './floatingWidget';
import { markApplicationSubmitted } from '../shared/trackApplicationSubmit';
import { scrollToMarkedField } from './fieldMarker';
import { initSubmitTracker } from './submitTracker';
import { AUTOFILL_MESSAGES, cycleMessages } from '../shared/loadingMessages';
import { logToServer, logAutofillResult } from '../shared/serverLog';
import { extractJobContext, isJobApplicationUrl, isSubmissionConfirmationUrl } from '../shared/jobPageDetection';
import { getPageSubmitRecord, markPageSubmitted } from '../shared/pageSubmitState';
import { createOperationId, endTrace, failTrace, startTrace, traceStep } from '../shared/actionTrace';
import { watchSkippedFieldsForProfileSave } from './skippedFieldProfile';

function truncateCompany(value: string, max = 16): string {
  const trimmed = value.trim();
  if (trimmed.length <= max) return trimmed;
  return `${trimmed.slice(0, max - 1)}…`;
}

function trackAutofillApplication(filledCount: number): void {
  if (!isJobApplicationUrl(document.location.href) || filledCount <= 0) return;
  const { company, role, location, platform } = extractJobContext(document);
  chrome.runtime.sendMessage({
    action: 'record-job-autofill',
    payload: {
      url: document.location.href,
      company,
      role,
      location,
      platform,
      filledCount
    }
  });
}

let activeScannedFields: ScannedField[] = [];

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.action === 'ping') {
    sendResponse({ ok: true });
    return false;
  }

  if (message.action === 'scan') {
    (async () => {
      const operationId = message.operationId as string | undefined;
      try {
        traceStep(operationId, 'scan', 'adapter_detect', 'content:scan');
        const jobDetails = resolveJobContext(document);

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
          const context = resolveJobContext(document);
          company = context.company || '';
        } catch {}

        activeScannedFields = scanPage(document);
        traceStep(operationId, 'autofill', 'run_full_page_start', 'content:autofill', {
          overrideCount: Object.keys(overrides).length,
          company
        });
        const { filledCount, errors, skippedFields } = await runFullPageAutofill(
          profile,
          overrides,
          company,
          document.location.hostname,
          document,
          operationId
        );
        traceStep(operationId, 'autofill', 'run_full_page_end', 'content:autofill', {
          filledCount,
          errorCount: errors.length,
          skippedCount: skippedFields.length
        });

        clearHighlights(document);
        logAutofillResult('content:autofill', {
          filledCount,
          errors,
          url: document.location.href,
          company,
          detail: { operationId, skippedCount: skippedFields.length }
        });
        sendResponse({ success: true, filledCount, errors, skippedFields });
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

  if (message.action === 'scroll-to-field') {
    const fieldId = message.fieldId as string | undefined;
    const label = message.label as string | undefined;
    let scrolled = fieldId ? scrollToMarkedField(document, fieldId) : false;
    if (!scrolled && label) {
      const fields = scanPage(document);
      const match = fields.find(
        (field) => field.labelText.replace(/\*+$/, '').trim().toLowerCase() === label.replace(/\*+$/, '').trim().toLowerCase()
      );
      if (match) {
        scrolled = scrollToMarkedField(document, match.id);
      }
    }
    sendResponse({ success: scrolled });
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
  if (isSubmissionConfirmationUrl(href)) return true;
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

  void getPageSubmitRecord(document.location.href).then((record) => {
    if (!record) return;
    widget.showSubmitTracked({
      company: record.company,
      role: record.role,
      submittedAt: record.submittedAt,
      platform: record.platform
    });
    widget.lockSubmitButton();
  });

  widget.onSubmit(async () => {
    widget.setSubmitDisabled(true);
    const ctx = extractJobContext(document);
    const result = await markApplicationSubmitted({
      company: ctx.company,
      role: ctx.role,
      location: ctx.location,
      platform: ctx.platform,
      trigger: 'applypilot_widget'
    });

    if (result.success) {
      const tracked = {
        company: result.company || ctx.company,
        role: result.role || ctx.role,
        submittedAt: result.submittedAt || new Date().toISOString(),
        platform: result.platform || ctx.platform
      };
      widget.showSubmitTracked(tracked);
      widget.lockSubmitButton();
      await markPageSubmitted(document.location.href, tracked);
      widget.setState('success', `${truncateCompany(tracked.company)} tracked`);
      logToServer({
        level: 'info',
        source: 'content:widget',
        message: `Submit tracked: ${tracked.company} — ${tracked.role}`,
        detail: {
          platform: tracked.platform,
          submittedAt: tracked.submittedAt,
          applicationId: result.applicationId
        },
        url: document.location.href
      });
      setTimeout(() => widget.setState('idle', 'Fill application'), 3200);
      return;
    }

    widget.setState('warning', 'Tracker save failed');
    widget.setSubmitDisabled(false);
    logToServer({
      level: 'error',
      source: 'content:widget',
      message: result.error || 'Could not track application submit',
      url: document.location.href
    });
    setTimeout(() => widget.setState('idle', 'Fill application'), 3200);
  });

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
        { action: 'scan-all-frames', profile, operationId },
        (scanResponse) => {
          if (chrome.runtime.lastError || !scanResponse?.success || !scanResponse.fields?.length) {
            failTrace(
              operationId,
              'autofill',
              'content:widget',
              scanResponse?.error || chrome.runtime.lastError?.message || 'No form fields found'
            );
            widget.setState('warning', 'No fields found');
            logToServer({
              level: 'warn',
              source: 'content:widget',
              message: 'Scan found no fillable fields',
              detail: { url: document.location.href, error: scanResponse?.error },
              url: document.location.href
            });
            setTimeout(() => {
              widget.setState('idle', 'Fill application');
              widget.setDisabled(false);
            }, 4200);
            return;
          }

          const frameIds = [
            ...new Set(
              scanResponse.fields
                .map((field: { frameId?: number }) => field.frameId)
                .filter((frameId: number | undefined): frameId is number => typeof frameId === 'number')
            )
          ];

          chrome.runtime.sendMessage(
            { action: 'autofill-active-tab', profile, frameIds, operationId },
            (autofillResponse) => {
          stopMessages();
          let keepSkippedPanelMs = 2800;
          let stopSkippedProfileWatch: (() => void) | undefined;

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
            const skippedFields =
              autofillResponse.skippedFields ||
              autofillResponse.errors?.map((entry: { label: string; error: string; fieldId?: string }) => ({
                label: entry.label,
                reason: entry.error,
                fieldId: entry.fieldId || ''
              })) ||
              [];
            const keepSkippedPanelMsLocal = skippedFields.length ? 12000 : 2800;
            keepSkippedPanelMs = keepSkippedPanelMsLocal;

            if (skippedFields.length) {
              const preview = skippedFields[0]?.label || '';
              const suffix = preview.length > 24 ? `${preview.slice(0, 24)}…` : preview;
              widget.setState('warning', `${skippedFields.length} skipped · ${suffix}`);
              widget.showSkippedFields(skippedFields);
              stopSkippedProfileWatch = watchSkippedFieldsForProfileSave(
                skippedFields,
                () =>
                  new Promise<UserProfile>((resolve, reject) => {
                    chrome.runtime.sendMessage({ action: 'get-profile-for-autofill' }, (res) => {
                      if (chrome.runtime.lastError || !res?.success || !res.profile) {
                        reject(new Error(chrome.runtime.lastError?.message || 'Profile unavailable'));
                        return;
                      }
                      resolve(enrichProfile(res.profile as UserProfile));
                    });
                  }),
                document
              );
            } else if (gapMessage) {
              widget.setState('warning', gapMessage.slice(0, 28));
              widget.hideSkippedFields();
            } else if (autofillResponse.filledCount === 0) {
              widget.setState('warning', 'No fields filled');
              widget.hideSkippedFields();
              logToServer({
                level: 'warn',
                source: 'content:widget',
                message: 'Autofill completed with zero fills',
                detail: {
                  scannedFields: scanResponse.fields.length,
                  frameIds,
                  errorCount: autofillResponse.errors?.length || 0
                },
                url: document.location.href
              });
            } else {
              widget.setState('success', `Filled ${autofillResponse.filledCount} fields`);
              widget.hideSkippedFields();
              trackAutofillApplication(autofillResponse.filledCount || 0);
            }
          }

          setTimeout(() => {
            stopSkippedProfileWatch?.();
            widget.setState('idle', 'Fill application');
            widget.setDisabled(false);
          }, keepSkippedPanelMs);
            }
          );
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
