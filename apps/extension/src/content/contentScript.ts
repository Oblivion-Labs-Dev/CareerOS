import '../shared/process-shim';
import { resolveJobContext } from '../shared/jobContextResolver';
import { scanPage, ScannedField } from './domScanner';
import { classifyFields } from './fieldClassifier';
import { runFullPageAutofill } from './autofillRunner';
import { clearHighlights, highlightField } from './autofillEngine';
import { UserProfile } from '../shared/types';
import { enrichProfile, hasContactProfileData } from '../profile/profileStore';
import { formatAutofillGapMessage } from './autofillRunner';
import { mountFloatingWidget, COPILOT_UI_VERSION } from './floatingWidget';
import { scrollToMarkedField } from './fieldMarker';
import { initSubmitTracker } from './submitTracker';
import { AUTOFILL_MESSAGES, cycleMessages } from '../shared/loadingMessages';
import { logToServer, logAutofillResult } from '../shared/serverLog';
import { extractJobContext, isJobApplicationUrl, isJobBoardUrl, isJobListingUrl, isJobSearchPage, isSubmissionConfirmationUrl } from '../shared/jobPageDetection';
import { employmentTypeLabel, workModeLabel } from '../shared/jobPageEnrichment';
import { TrackerPipelineStatus } from '../shared/saveJobToTracker';
import { scanJobKeywords } from '../shared/jobKeywordScan';
import { parseFromJobSite, SiteParsedJob } from '../shared/jobSiteSelectors';
import { initSiteButtonInjector, resetSiteButtonInjector } from './siteButtonInjector';
import { getPageSubmitRecord } from '../shared/pageSubmitState';
import { createOperationId, endTrace, failTrace, startTrace, traceStep } from '../shared/actionTrace';
import { watchSkippedFieldsForProfileSave } from './skippedFieldProfile';
import { ExtensionContextInvalidError, isExtensionContextValid, requireExtensionRuntime } from '../shared/extensionRuntime';
import { sendRuntimeMessage, RuntimeMessageTimeoutError } from '../shared/runtimeMessage';
import {
  WIDGET_AUTOFILL_TIMEOUT_MS,
  WIDGET_ERROR_DISPLAY_MS,
  WIDGET_OPERATION_TIMEOUT_MS,
  WIDGET_PROFILE_TIMEOUT_MS,
  WIDGET_SCAN_TIMEOUT_MS,
  WIDGET_SUCCESS_DISPLAY_MS,
  WIDGET_WARNING_DISPLAY_MS,
  CONTENT_AUTOFILL_TIMEOUT_MS
} from '../shared/autofillTimeouts';
import { withTimeout, OperationTimeoutError } from '../shared/withTimeout';
import { lookupDiscoverJobByUrl } from '../shared/careerOsBridge';
import { getH1bAwareWarning } from '../shared/h1bAware';
import { buildResumeKeywordSuggestions, formatResumeSuggestionsText } from '../shared/resumeKeywordSuggestions';
import { recordAutofillSession } from '../shared/autofillSessionLog';
import { initJobCardOverlays } from './jobCardOverlay';
import type { FloatingWidget } from './floatingWidget';

function truncateCompany(value: string, max = 16): string {
  const trimmed = value.trim();
  if (trimmed.length <= max) return trimmed;
  return `${trimmed.slice(0, max - 1)}…`;
}

function trackAutofillApplication(filledCount: number): void {
  if (!isJobApplicationUrl(document.location.href) || filledCount <= 0) return;
  const { company, role, location, platform } = extractJobContext(document);
  requireExtensionRuntime().sendMessage({
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
let autofillInProgress = false;

if (!isExtensionContextValid()) {
  console.warn('[ApplyPilot] Extension context is invalid. Refresh this page to use autofill.');
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.action === 'pipeline-updated') {
    if (message.status === 'submitted') {
      const pipelineSelect = document.getElementById('jf-pipeline-select') as HTMLSelectElement | null;
      if (pipelineSelect) {
        pipelineSelect.value = 'submitted';
        pipelineSelect.disabled = true;
      }
    }
    sendResponse({ ok: true });
    return false;
  }

  if (message.action === 'scan-keywords') {
    (async () => {
      try {
        const widget = document.getElementById('jobfill-floating-wrapper');
        const ctx = extractJobContext(document);
        const description = ctx.description || document.body?.innerText?.slice(0, 12000) || '';
        const profileResponse = await sendRuntimeMessage<{ success?: boolean; profile?: UserProfile }>(
          { action: 'get-profile-for-autofill' },
          WIDGET_PROFILE_TIMEOUT_MS,
          'Profile fetch'
        );
        if (!profileResponse?.success || !profileResponse.profile) {
          sendResponse({ success: false, error: 'Profile unavailable' });
          return;
        }
        const result = scanJobKeywords(description, enrichProfile(profileResponse.profile));
        if (widget) {
          // no-op: popup reads response directly
        }
        sendResponse({ success: true, ...result });
      } catch (err: any) {
        sendResponse({ success: false, error: err.message });
      }
    })();
    return true;
  }

  if (message.action === 'ping') {
    sendResponse({ ok: true });
    return false;
  }

  if (message.action === 'scan') {
    (async () => {
      const operationId = message.operationId as string | undefined;
      try {
        traceStep(operationId, 'scan', 'adapter_detect', 'content:scan');
        const jobDetails = extractJobContext(document);

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
        if (!message.skipHighlight) {
          classified.forEach((c) => {
            if (c.proposedValue) {
              highlightField(c.scannedField.element, c.confidence);
            }
          });
        }

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
    if (autofillInProgress) {
      sendResponse({ success: false, error: 'Autofill is already running on this page.' });
      return false;
    }
    autofillInProgress = true;
    (async () => {
      const operationId = message.operationId as string | undefined;
      let company = '';
      let responded = false;
      const respond = (payload: Record<string, unknown>) => {
        if (responded) return;
        responded = true;
        sendResponse(payload);
      };

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
            respond({ success: false, error: 'Missing approved fields.' });
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
        const { filledCount, errors, skippedFields, issueReport } = await withTimeout(
          runFullPageAutofill(
            profile,
            overrides,
            company,
            document.location.hostname,
            document,
            operationId
          ),
          CONTENT_AUTOFILL_TIMEOUT_MS,
          'Autofill'
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
          skippedFields,
          issueSummary: issueReport.summary,
          url: document.location.href,
          company,
          detail: {
            operationId,
            skippedCount: skippedFields.length,
            issueCounts: issueReport.counts,
          }
        });
        respond({ success: true, filledCount, errors, skippedFields, issueReport });
      } catch (err: any) {
        console.error('[JobFill] Autofill error:', err);
        const messageText =
          err instanceof OperationTimeoutError
            ? `${err.message}. Some dropdowns may still be open — close them and try again.`
            : err.message || 'Autofill failed';
        failTrace(operationId, 'autofill', 'content:autofill', messageText, {
          url: document.location.href,
          company
        });
        logToServer({
          level: 'error',
          source: 'content:autofill',
          message: messageText,
          stack: err.stack,
          detail: { url: document.location.href, company }
        });
        respond({ success: false, error: messageText, filledCount: 0, errors: [] });
      } finally {
        autofillInProgress = false;
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

function topFrameHasCopilotWidget(): boolean {
  if (window === window.top) return false;
  try {
    return Boolean(window.top?.document.getElementById('jobfill-floating-wrapper'));
  } catch {
    return false;
  }
}

function isLegacyFloatingWidget(wrapper: HTMLElement): boolean {
  if (wrapper.dataset.uiVersion !== COPILOT_UI_VERSION) return true;
  return Boolean(
    wrapper.querySelector('.jf-stats-row, .jf-pipeline-btn') ||
      wrapper.querySelector('#jobfill-floating-submit:not([hidden])') ||
      wrapper.querySelector('#jobfill-floating-queue:not([hidden])')
  );
}

function purgeLegacyFloatingWidget(): void {
  const stale = document.getElementById('jobfill-floating-wrapper');
  if (!stale || !isLegacyFloatingWidget(stale)) return;
  stale.remove();
  document.getElementById('jobfill-widget-styles')?.remove();
}

purgeLegacyFloatingWidget();

function shouldMountFloatingWidget(doc: Document): boolean {
  const href = doc.location.href;
  const fillable = countFillableControls(doc);

  if (window !== window.top) {
    if (topFrameHasCopilotWidget()) return false;
    try {
      const topHref = window.top?.location.href || '';
      if (isJobSearchPage(topHref)) return false;
    } catch {
      return fillable >= 2;
    }
    return fillable >= 3;
  }

  if (isJobSearchPage(href)) return true;
  return fillable >= 3;
}

let widgetMountObserver: MutationObserver | null = null;
let siteInjectorCleanup: (() => void) | null = null;
let lastTrackedUrl = '';

async function saveJobFromPage(
  source: string,
  pipelineStatus: TrackerPipelineStatus = 'saved'
): Promise<{ success?: boolean; duplicate?: boolean; error?: string; status?: TrackerPipelineStatus }> {
  const ctx = extractJobContext(document);
  return requireExtensionRuntime().sendMessage({
    action: 'record-job-save',
    payload: {
      url: document.location.href,
      company: ctx.company,
      role: ctx.role,
      location: ctx.location,
      platform: ctx.platform,
      status: pipelineStatus,
      source,
      salary: ctx.enrichment.salary,
      employmentType: employmentTypeLabel(ctx.enrichment.employmentType),
      workMode: workModeLabel(ctx.enrichment.workMode),
      description: ctx.description,
      h1bStatus: ctx.h1b.status,
      h1bLabel: ctx.h1b.label
    }
  }) as Promise<{ success?: boolean; duplicate?: boolean; error?: string; status?: TrackerPipelineStatus }>;
}

async function runKeywordScan(widget: ReturnType<typeof mountFloatingWidget>): Promise<void> {
  const ctx = extractJobContext(document);
  const description = ctx.description || document.body?.innerText?.slice(0, 12000) || '';
  if (!description.trim()) {
    widget.showError('No job description found to scan.');
    return;
  }

  const profileResponse = await sendRuntimeMessage<{ success?: boolean; profile?: UserProfile }>(
    { action: 'get-profile-for-autofill' },
    WIDGET_PROFILE_TIMEOUT_MS,
    'Profile fetch'
  );

  if (!profileResponse?.success || !profileResponse.profile) {
    widget.showError('Set up your profile in ApplyPilot to run a keyword scan.');
    return;
  }

  const result = scanJobKeywords(description, enrichProfile(profileResponse.profile));
  widget.showScanResult(result);
  widget.openPanel();
}

function saveJobFromSiteParsed(job: SiteParsedJob, source: string): Promise<{ success?: boolean; duplicate?: boolean }> {
  return chrome.runtime.sendMessage({
    action: 'record-job-save',
    payload: {
      url: job.url,
      company: job.company,
      role: job.role,
      platform: job.siteLabel,
      status: 'saved',
      source,
      salary: job.salary,
      description: job.description
    }
  }) as Promise<{ success?: boolean; duplicate?: boolean }>;
}

async function hydrateCopilotInsights(
  widget: FloatingWidget,
  ctx: ReturnType<typeof extractJobContext>,
  profile?: UserProfile
): Promise<void> {
  const parts: string[] = [];

  const h1bWarning = profile ? getH1bAwareWarning(ctx.h1b, profile) : null;
  if (h1bWarning) {
    widget.setInsights(`<strong>${h1bWarning.title}</strong>${h1bWarning.message}`, h1bWarning.level === 'info' ? 'info' : 'warn');
  } else {
    widget.setInsights(null);
  }

  const discovered = await lookupDiscoverJobByUrl(document.location.href);
  if (discovered) {
    if (discovered.relevancyScore != null) {
      widget.setMatchScore(discovered.relevancyScore);
    }
    parts.push(
      `<strong>CareerOS scraper</strong>${discovered.relevancyScore ?? 0}% match` +
        (discovered.salaryRange ? ` · ${discovered.salaryRange}` : '') +
        (discovered.h1bLabel ? ` · ${discovered.h1bLabel}` : '')
    );
  }

  if (profile && ctx.description) {
    const scan = scanJobKeywords(ctx.description, enrichProfile(profile));
    if (scan.missing.length) {
      const tips = formatResumeSuggestionsText(buildResumeKeywordSuggestions(scan.missing, profile));
      if (tips) parts.push(`<strong>Resume tips</strong><pre style="margin:4px 0 0;white-space:pre-wrap;font:inherit">${tips}</pre>`);
    }
  }

  if (parts.length && !h1bWarning) {
    widget.setInsights(parts.join('<br/>'), 'info');
  } else if (parts.length && h1bWarning) {
    widget.setInsights(
      `<strong>${h1bWarning.title}</strong>${h1bWarning.message}<br/><br/>${parts.join('<br/>')}`,
      h1bWarning.level === 'info' ? 'info' : 'warn'
    );
  }
}

function injectFloatingCopilotButton() {
  purgeLegacyFloatingWidget();
  const existing = document.getElementById('jobfill-floating-wrapper');
  if (existing && existing.dataset.uiVersion === COPILOT_UI_VERSION) return;
  existing?.remove();
  document.getElementById('jobfill-widget-styles')?.remove();
  if (!isExtensionContextValid()) return;
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
  const jobCtx = extractJobContext(document);
  widget.setJobContext(jobCtx);
  widget.openPanel();

  void sendRuntimeMessage<{ success?: boolean; profile?: UserProfile }>(
    { action: 'get-profile-for-autofill' },
    WIDGET_PROFILE_TIMEOUT_MS,
    'Profile fetch'
  ).then((res) => {
    if (res?.profile) void hydrateCopilotInsights(widget, jobCtx, enrichProfile(res.profile));
  });

  const onListingPage = isJobListingUrl(document.location.href) && !isJobApplicationUrl(document.location.href);
  widget.setAutofillVisible(!onListingPage);
  if (onListingPage) {
    widget.setState('idle', 'Save this job');
  }

  void requireExtensionRuntime().sendMessage({ action: 'check-job-saved', url: document.location.href }).then((res: {
    saved?: boolean;
    status?: TrackerPipelineStatus;
  }) => {
    if (res?.saved) {
      widget.setSaveJobState('saved', 'Saved to tracker ✓');
      if (res.status) widget.setPipelineStatus(res.status);
    }
  });

  widget.onSaveJob(async (pipelineStatus) => {
    widget.setSaveJobState('parsing', 'Parsing job…');
    await new Promise((resolve) => setTimeout(resolve, 350));
    widget.setSaveJobState('saving', 'Saving…');

    const result = await saveJobFromPage('applypilot_widget', pipelineStatus);
    const ctx = extractJobContext(document);

    if (result?.success) {
      widget.setSaveJobState(result.duplicate ? 'duplicate' : 'saved');
      if (result.status) widget.setPipelineStatus(result.status);
      logToServer({
        level: 'info',
        source: 'content:widget',
        message: `Job saved: ${ctx.company} — ${ctx.role}`,
        detail: { duplicate: result.duplicate, status: pipelineStatus },
        url: document.location.href
      });
      return;
    }

    widget.setSaveJobState('idle');
    widget.showError(result?.error || 'Could not save job to tracker.');
    logToServer({
      level: 'error',
      source: 'content:widget',
      message: result?.error || 'Job save failed',
      url: document.location.href
    });
  });

  widget.onScan(async () => {
    widget.hideError();
    const scanBtn = document.getElementById('jobfill-floating-scan') as HTMLButtonElement | null;
    scanBtn?.setAttribute('disabled', 'true');
    try {
      await runKeywordScan(widget);
    } catch (err) {
      widget.showError(err instanceof Error ? err.message : 'Scan failed');
    } finally {
      scanBtn?.removeAttribute('disabled');
    }
  });

  if (isJobBoardUrl(document.location.href)) {
    siteInjectorCleanup?.();
    siteInjectorCleanup = initSiteButtonInjector({
      onSave: async (job) => {
        await saveJobFromSiteParsed(job, 'applypilot_site_save');
      },
      onScan: async () => {
        await runKeywordScan(widget);
      }
    });
  }

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

  widget.onClick(async () => {
    widget.setDisabled(true);
    widget.hideError();
    widget.hideSkippedFields();
    widget.setState('loading', 'Reading form…');
    widget.setProgress(12);

    const operationId = createOperationId('autofill');
    startTrace(operationId, 'autofill', 'content:widget', { url: document.location.href });
    const loadingStarted = Date.now();

    const stopMessages = cycleMessages(AUTOFILL_MESSAGES, (message) => {
      const elapsedSec = Math.floor((Date.now() - loadingStarted) / 1000);
      const suffix = elapsedSec >= 6 ? ` · ${elapsedSec}s` : '';
      widget.setState('loading', `${message.replace(/…$/, '')}${suffix}…`);
    }, 1200);

    let operationTimedOut = false;

    const finishOperation = () => {
      window.clearTimeout(operationTimer);
      widget.onDismiss(null);
    };

    const resetWidget = (delayMs: number) => {
      window.setTimeout(() => {
        widget.hideError();
        widget.setState('idle', 'Autofill');
        widget.setDisabled(false);
      }, delayMs);
    };

    const failWidget = (label: string, errorMessage: string, logMessage?: string) => {
      if (operationTimedOut) return;
      operationTimedOut = true;
      stopMessages();
      finishOperation();
      failTrace(operationId, 'autofill', 'content:widget', logMessage || errorMessage);
      widget.setState('error', label);
      widget.showError(errorMessage);
      logToServer({
        level: 'error',
        source: 'content:widget',
        message: logMessage || errorMessage,
        url: document.location.href
      });
      resetWidget(WIDGET_ERROR_DISPLAY_MS);
    };

    const operationTimer = window.setTimeout(() => {
      failWidget(
        'Timed out',
        `Autofill stopped after ${WIDGET_OPERATION_TIMEOUT_MS / 1000}s. Close any open dropdowns and try again.`,
        `Autofill operation timed out after ${WIDGET_OPERATION_TIMEOUT_MS / 1000}s`
      );
    }, WIDGET_OPERATION_TIMEOUT_MS);

    widget.onDismiss(() => {
      failWidget(
        'Cancelled',
        'Autofill cancelled. Close any open dropdowns and try again when ready.',
        'Autofill cancelled from widget'
      );
    });

    try {
      const profileResponse = await sendRuntimeMessage<{
        success?: boolean;
        profile?: UserProfile;
        error?: string;
      }>(
        { action: 'get-profile-for-autofill' },
        WIDGET_PROFILE_TIMEOUT_MS,
        'Profile fetch'
      );

      if (operationTimedOut) return;

      if (!profileResponse?.success || !profileResponse.profile) {
        stopMessages();
        finishOperation();
        failTrace(operationId, 'autofill', 'content:widget', 'Profile not available');
        widget.setState('warning', 'Open dashboard');
        resetWidget(WIDGET_WARNING_DISPLAY_MS);
        return;
      }

      const profile = enrichProfile(profileResponse.profile);
      if (!hasContactProfileData(profile)) {
        stopMessages();
        finishOperation();
        failTrace(operationId, 'autofill', 'content:widget', 'Profile incomplete');
        widget.setState('warning', 'Set up profile');
        resetWidget(WIDGET_WARNING_DISPLAY_MS);
        return;
      }

      traceStep(operationId, 'autofill', 'profile_loaded', 'content:widget');

      const scanResponse = await sendRuntimeMessage<{
        success?: boolean;
        fields?: Array<{ frameId?: number }>;
        error?: string;
      }>(
        { action: 'scan-all-frames', profile, operationId },
        WIDGET_SCAN_TIMEOUT_MS,
        'Form scan'
      );

      if (operationTimedOut) return;

      if (!scanResponse?.success || !scanResponse.fields?.length) {
        stopMessages();
        finishOperation();
        const scanError = scanResponse?.error || 'No form fields found';
        failTrace(operationId, 'autofill', 'content:widget', scanError);
        widget.setState('error', 'No fields found');
        widget.showError(scanError);
        logToServer({
          level: 'warn',
          source: 'content:widget',
          message: 'Scan found no fillable fields',
          detail: { url: document.location.href, error: scanResponse?.error },
          url: document.location.href
        });
        resetWidget(WIDGET_ERROR_DISPLAY_MS);
        return;
      }

      widget.setFieldStats(scanResponse.fields.length);
      widget.setProgress(35);

      const frameIds = [
        ...new Set(
          scanResponse.fields
            .map((field) => field.frameId)
            .filter((frameId): frameId is number => typeof frameId === 'number')
        )
      ];

      const autofillResponse = await sendRuntimeMessage<{
        success?: boolean;
        filledCount?: number;
        errors?: Array<{ label: string; error: string; fieldId?: string }>;
        skippedFields?: Array<{ label: string; reason: string; fieldId: string }>;
        issueReport?: { summary: string; issueCount: number; counts: Record<string, number> };
        error?: string;
      }>(
        { action: 'autofill-active-tab', profile, frameIds, operationId },
        WIDGET_AUTOFILL_TIMEOUT_MS,
        'Autofill'
      );

      if (operationTimedOut) return;

      stopMessages();
      finishOperation();

      if (!autofillResponse?.success) {
        const autofillError = autofillResponse?.error || 'Autofill failed';
        widget.setState('error', 'Fill failed');
        widget.showError(autofillError);
        failTrace(operationId, 'autofill', 'content:widget', autofillError);
        logToServer({
          level: 'error',
          source: 'content:widget',
          message: autofillError,
          url: document.location.href
        });
        resetWidget(WIDGET_ERROR_DISPLAY_MS);
        return;
      }

      logAutofillResult('content:widget', {
        filledCount: autofillResponse.filledCount,
        errors: autofillResponse.errors,
        skippedFields: autofillResponse.skippedFields,
        issueSummary: autofillResponse.issueReport?.summary,
        url: document.location.href,
        detail: {
          issueCounts: autofillResponse.issueReport?.counts,
        },
      });

      widget.setFieldStats(scanResponse.fields.length, autofillResponse.filledCount ?? 0);
      widget.setProgress(100);
      window.setTimeout(() => widget.setProgress(null), 1200);

      const gapMessage = formatAutofillGapMessage({
        missingInProfile: [],
        stillEmptyOnPage: [],
        resumeMissing: !profile.resume,
        resumeNotAttached: false
      });
      const skippedFields =
        autofillResponse.skippedFields ||
        autofillResponse.errors?.map((entry) => ({
          label: entry.label,
          reason: entry.error,
          fieldId: entry.fieldId || ''
        })) ||
        [];

      let keepSkippedPanelMs = WIDGET_SUCCESS_DISPLAY_MS;
      let stopSkippedProfileWatch: (() => void) | undefined;

      if (skippedFields.length) {
        const summary =
          autofillResponse.issueReport?.summary ||
          `${skippedFields.length} field${skippedFields.length === 1 ? '' : 's'} need review`;
        widget.setState('warning', summary.slice(0, 42));
        widget.showSkippedFields(skippedFields, summary);
        keepSkippedPanelMs = WIDGET_WARNING_DISPLAY_MS;
        stopSkippedProfileWatch = watchSkippedFieldsForProfileSave(
          skippedFields,
          () =>
            sendRuntimeMessage<{ success?: boolean; profile?: UserProfile }>(
              { action: 'get-profile-for-autofill' },
              WIDGET_PROFILE_TIMEOUT_MS,
              'Profile fetch'
            ).then((res) => {
              if (!res?.success || !res.profile) {
                throw new Error('Profile unavailable');
              }
              return enrichProfile(res.profile);
            }),
          document
        );
      } else if (gapMessage) {
        widget.setState('warning', gapMessage.slice(0, 28));
        widget.hideSkippedFields();
        keepSkippedPanelMs = WIDGET_WARNING_DISPLAY_MS;
      } else if (autofillResponse.filledCount === 0) {
        widget.setState('error', 'No fields filled');
        widget.showError('The form was scanned but no fields could be filled. Check your profile or fill manually.');
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
        keepSkippedPanelMs = WIDGET_ERROR_DISPLAY_MS;
      } else {
        widget.setState('success', `Filled ${autofillResponse.filledCount} fields`);
        widget.hideSkippedFields();
        trackAutofillApplication(autofillResponse.filledCount || 0);
        void recordAutofillSession({
          url: document.location.href,
          company: extractJobContext(document).company,
          role: extractJobContext(document).role,
          platform: extractJobContext(document).platform,
          fieldsDetected: scanResponse.fields.length,
          fieldsFilled: autofillResponse.filledCount || 0,
          fieldsSkipped: skippedFields.length
        });
      }

      window.setTimeout(() => {
        stopSkippedProfileWatch?.();
        widget.hideError();
        widget.setState('idle', 'Autofill');
        widget.setDisabled(false);
      }, keepSkippedPanelMs);
    } catch (error) {
      if (operationTimedOut) return;

      const message =
        error instanceof ExtensionContextInvalidError
          ? error.message
          : error instanceof RuntimeMessageTimeoutError
          ? `${error.message}. Close any open dropdowns and try again.`
          : error instanceof OperationTimeoutError
            ? error.message
          : error instanceof Error
            ? error.message
            : 'Autofill failed';

      failWidget(
        error instanceof ExtensionContextInvalidError
          ? 'Refresh page'
          : error instanceof RuntimeMessageTimeoutError || error instanceof OperationTimeoutError
            ? 'Timed out'
            : 'Error',
        message
      );
    }
  });
}

function scheduleFloatingWidgetMount(): void {
  const attempt = () => {
    if (document.location.href !== lastTrackedUrl) {
      lastTrackedUrl = document.location.href;
      resetSiteButtonInjector();
      siteInjectorCleanup?.();
      siteInjectorCleanup = null;
    }
    injectFloatingCopilotButton();
  };

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

if (isExtensionContextValid()) {
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
          requireExtensionRuntime().sendMessage({
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

  let cardOverlayCleanup: (() => void) | null = null;
  if (isJobBoardUrl(document.location.href)) {
    void sendRuntimeMessage<{ success?: boolean; profile?: UserProfile }>(
      { action: 'get-profile-for-autofill' },
      WIDGET_PROFILE_TIMEOUT_MS,
      'Profile fetch'
    ).then((res) => {
      cardOverlayCleanup?.();
      cardOverlayCleanup = initJobCardOverlays(res?.profile ? enrichProfile(res.profile) : null);
    });
  }
}
