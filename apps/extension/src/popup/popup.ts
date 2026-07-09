import '../shared/process-shim';
import { getProfile, saveProfile, clearProfile, createEmptyProfile, enrichProfile } from '../profile/profileStore';
import { getDocuments, saveDocuments } from '../documents/documentStore';
import { compileCoverLetter } from '../documents/coverLetterTemplates';
import { getLearnedAnswers, deleteLearnedAnswer } from '../learning/learnedAnswerStore';
import { learnAnswer } from '../learning/learningEngine';
import { saveApplication, getApplications, deleteApplication, countSubmittedApplications } from '../db/repositories/applicationRepository';
import { generateId } from '../shared/id';
import { logChronicle as logActivityEvent } from '../db/repositories/chronicleRepository';
import { UserProfile, FileAttachment, ApplicationStatus } from '../shared/types';
import { LearnedAnswerScope } from '../shared/learningTypes';
import { syncFromServer, syncToServer } from '../db/sync';
import { SCAN_MESSAGES, AUTOFILL_MESSAGES, cycleMessages } from '../shared/loadingMessages';
import { logToServer, logAutofillResult } from '../shared/serverLog';
import { createOperationId, endTrace, failTrace, startTrace } from '../shared/actionTrace';
import { markApplicationSubmitted } from '../shared/trackApplicationSubmit';

function setStatusDot(state: 'idle' | 'scanning' | 'ready' | 'busy') {
  const dot = document.getElementById('status-dot');
  if (!dot) return;
  dot.classList.remove('is-scanning', 'is-ready', 'is-busy');
  if (state === 'scanning') dot.classList.add('is-scanning');
  if (state === 'ready') dot.classList.add('is-ready');
  if (state === 'busy') dot.classList.add('is-busy');
}

function setActionTitle(text: string) {
  const el = document.getElementById('action-title');
  if (el) el.textContent = text;
}

function scanLoadingHtml() {
  return `<div class="empty-state empty-state-loading">
    <div class="autofill-loader-visual autofill-loader-visual--compact" aria-hidden="true">
      <div class="autofill-loader-ring-track"></div>
      <div class="autofill-loader-ring-spin"></div>
      <div class="autofill-loader-icon">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle cx="11" cy="11" r="7" stroke="currentColor" stroke-width="1.75"/>
          <path d="M20 20l-3.5-3.5" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"/>
        </svg>
      </div>
    </div>
    <p class="empty-title">Scanning page…</p>
    <p class="empty-desc">Looking for form fields on this tab.</p>
  </div>`;
}

function updateLoaderSteps(activeIndex: number) {
  document.querySelectorAll('.autofill-step').forEach((el, index) => {
    el.classList.remove('is-active', 'is-done');
    if (index < activeIndex) el.classList.add('is-done');
    else if (index === activeIndex) el.classList.add('is-active');
  });
}

function animateLoaderMessage(el: HTMLElement | null, message: string) {
  if (!el || el.textContent === message) return;
  el.classList.add('is-changing');
  window.setTimeout(() => {
    el.textContent = message;
    el.classList.remove('is-changing');
  }, 160);
}

function showLoaderPanel(message: string, stepIndex = 0) {
  const panel = document.getElementById('autofill-progress-container');
  const status = document.getElementById('progress-status');
  if (panel) panel.style.display = 'flex';
  animateLoaderMessage(status, message);
  updateLoaderSteps(stepIndex);
}

function hideLoaderPanel() {
  const panel = document.getElementById('autofill-progress-container');
  if (panel) panel.style.display = 'none';
  updateLoaderSteps(-1);
}

function emptyStateHtml(icon: string, title: string, desc: string, extraClass = '') {
  return `<div class="empty-state ${extraClass}">
    <div class="empty-icon">${icon}</div>
    <p class="empty-title">${title}</p>
    <p class="empty-desc">${desc}</p>
  </div>`;
}

function setScanStatus(text: string) {
  const el = document.getElementById('scan-status');
  if (el) el.textContent = text;
}

function setFieldCount(count: number) {
  const badge = document.getElementById('field-count-badge');
  if (!badge) return;
  if (count > 0) {
    badge.style.display = '';
    badge.textContent = `${count} field${count === 1 ? '' : 's'}`;
  } else {
    badge.style.display = 'none';
  }
}

function escapePopupHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
let currentScannedFields: any[] = [];
let detectedCompany = '';
let detectedRole = '';

// File caches
let cachedResume: FileAttachment | undefined;
let cachedCoverLetter: FileAttachment | undefined;

document.addEventListener('DOMContentLoaded', () => {
  void initPopup().catch((err) => {
    console.error('[JobFill] Popup failed to initialize:', err);
    logToServer({
      level: 'error',
      source: 'popup:init',
      message: err.message || 'Popup init failed',
      stack: err.stack
    });
  });
});

async function initPopup() {
  setupTabs();
  const btnDashboard = document.getElementById('btn-open-dashboard');
  btnDashboard?.addEventListener('click', () => {
    chrome.tabs.create({ url: chrome.runtime.getURL('dashboard.html') });
  });
  await syncFromServer();
  await loadProfile();
  await loadDocuments();
  await loadLearningCenter();
  await loadTracker();

  // Profile Redirect
  const btnPopupOpenProfile = document.getElementById('btn-popup-open-profile');
  btnPopupOpenProfile?.addEventListener('click', () => {
    chrome.tabs.create({ url: chrome.runtime.getURL('dashboard.html#profile') });
  });

  // Scan Current Job Page
  const btnScan = document.getElementById('btn-scan');
  btnScan?.addEventListener('click', async () => {
    const reviewList = document.getElementById('review-list');
    if (reviewList) {
      reviewList.innerHTML = scanLoadingHtml();
    }
    setStatusDot('scanning');
    setActionTitle('Scanning…');
    setScanStatus('Reading fields on the active tab.');
    const stopScanMessages = cycleMessages(SCAN_MESSAGES, (message) => setScanStatus(message));

    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.id) {
      stopScanMessages();
      if (reviewList) reviewList.innerHTML = emptyStateHtml('⚠️', 'No active tab', 'Open a job application page in your browser, then try again.', 'empty-state-error');
      setScanStatus('No active webpage found.');
      return;
    }

    await syncFromServer();
    const profile = enrichProfile((await getProfile()) || createEmptyProfile());

    const operationId = createOperationId('scan');
    startTrace(operationId, 'scan', 'popup:scan', { tabUrl: tab.url, tabId: tab.id });

    chrome.runtime.sendMessage({ action: 'scan-all-frames', tabId: tab.id, profile, operationId }, (response) => {
      stopScanMessages();
      if (chrome.runtime.lastError) {
        failTrace(operationId, 'scan', 'popup:scan', chrome.runtime.lastError.message || 'Scan message failed', {
          tabUrl: tab.url
        });
        logToServer({
          level: 'error',
          source: 'popup:scan',
          message: chrome.runtime.lastError.message || 'Scan message failed',
          detail: { tabUrl: tab.url }
        });
        if (reviewList) {
          reviewList.innerHTML = emptyStateHtml('🔌', 'Connection failed', 'Reload the job page and try scanning again.', 'empty-state-error');
        }
        setScanStatus('Could not reach the page. Reload and retry.');
        return;
      }

      if (response && response.success && response.fields) {
        const fields = response.fields;
        currentScannedFields = fields;
        endTrace(operationId, 'scan', 'popup:scan', {
          tabUrl: tab.url,
          success: true,
          fieldCount: fields.length,
          company: response.jobDetails?.company
        });

        // Automatically inject missing/custom fields into UserProfile's customFields
        (async () => {
          try {
            const profileData = await getProfile() || createEmptyProfile();
            if (!profileData.customFields) profileData.customFields = {};
            let profileUpdated = false;

            const BLACKLISTED_KEYWORDS = [
              'search', 'textbox', 'select...', 'select', 'input', 'text', 'textarea',
              'dropdown', 'upload', 'drop or select', 'drag', 'pdf', 'docx', 'doc',
              'resume', 'cover letter', 'cv', 'file', 'attach', 'browse', 'choose file',
              'yes -', 'no -', 'i consent', 'i agree'
            ];
            
            fields.forEach((field: any) => {
              // Only auto-discover text-like custom inputs
              if (
                field.type !== 'text' &&
                field.type !== 'textarea' &&
                field.type !== 'number' &&
                field.type !== 'url'
              ) {
                return;
              }

              // If it's already mapped to a canonical key (other than custom), skip
              if (field.canonicalKey && field.canonicalKey !== 'customQuestion') {
                return;
              }

              const label = (field.labelText || field.name || field.placeholder || '').trim();
              if (!label || label.length < 3) return;

              // Check blacklist
              const labelLower = label.toLowerCase();
              const isBlacklisted = BLACKLISTED_KEYWORDS.some((kw) => labelLower.includes(kw));
              if (isBlacklisted) return;

              if (!profileData.customFields![label]) {
                profileData.customFields![label] = field.proposedValue || '';
                profileUpdated = true;
              }
            });
            
            if (profileUpdated) {
              await saveProfile(profileData);
              await syncToServer();
            }
          } catch (e) {
            console.error('[JobFill] Failed to auto-append custom fields to profile:', e);
          }
        })();

        // Render Job Info Card
        const job = response.jobDetails;
        if (job) {
          detectedCompany = job.company || 'Unknown Company';
          detectedRole = job.role || 'Unknown Role';
          document.getElementById('job-company')!.textContent = detectedCompany;
          document.getElementById('job-role')!.textContent = detectedRole;
          document.getElementById('job-location')!.textContent = job.location || 'Remote';
          document.getElementById('job-platform')!.textContent = job.platform || 'Generic';
          document.getElementById('job-info-card')!.style.display = 'block';
        }

        renderReviewFields(fields);
        setFieldCount(fields.length);
        setScanStatus(`${fields.length} fields ready — review below, then fill.`);
        setActionTitle('Ready to fill');
        setStatusDot('ready');
        document.getElementById('btn-autofill')?.removeAttribute('disabled');
      } else {
        endTrace(operationId, 'scan', 'popup:scan', {
          tabUrl: tab.url,
          success: false,
          error: response?.error || 'no_fields'
        });
        setFieldCount(0);
        setScanStatus('No form fields found on this page.');
        setActionTitle('No form detected');
        setStatusDot('idle');
        if (reviewList) {
          reviewList.innerHTML = emptyStateHtml('📭', 'No fields found', 'This page may not have an application form, or it loads in an iframe.');
        }
      }
    });
  });

  // Autofill Approved
  const btnAutofill = document.getElementById('btn-autofill');
  const btnMarkSubmitted = document.getElementById('btn-mark-submitted');

  btnMarkSubmitted?.addEventListener('click', async () => {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.url) return;

    btnMarkSubmitted.setAttribute('disabled', 'true');
    setStatusDot('busy');
    setActionTitle('Saving to tracker…');

    const result = await markApplicationSubmitted({
      url: tab.url,
      company: detectedCompany !== 'Unknown Company' ? detectedCompany : undefined,
      role: detectedRole !== 'Unknown Role' ? detectedRole : undefined,
      trigger: 'applypilot_popup'
    });

    btnMarkSubmitted.removeAttribute('disabled');

    if (result.success) {
      const dateLabel = result.submittedAt
        ? new Date(result.submittedAt).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
        : 'today';
      setScanStatus(
        `Tracked: ${result.company || detectedCompany} — ${result.role || detectedRole} · ${dateLabel}${result.platform ? ` · ${result.platform}` : ''}`
      );
      setActionTitle('Application saved');
      setStatusDot('ready');
      await loadTracker();
      return;
    }

    setScanStatus(result.error || 'Could not save application to tracker.');
    setActionTitle('Tracker save failed');
    setStatusDot('idle');
  });

  btnAutofill?.addEventListener('click', async () => {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.id) return;

    // 1. Gather all values from the UI review cards
    const approvedFields: { id: string; proposedValue: string; frameId?: number }[] = [];
    const elements = document.querySelectorAll('.review-input-el');

    for (const el of elements) {
      const fieldId = el.getAttribute('data-field-id')!;
      
      // Override Check: Verify if user checked "Fill" next to this field
      const fillToggle = document.querySelector(`.review-fill-toggle[data-field-id="${fieldId}"]`) as HTMLInputElement | null;
      if (fillToggle && !fillToggle.checked) {
        continue; // Skip this field mapping!
      }

      const val = (el as HTMLInputElement | HTMLSelectElement).value.trim();
      const fieldData = currentScannedFields.find((f) => f.id === fieldId);
      const proposedValue = (fieldData?.proposedValue || '').trim();
      const fillValue = val || proposedValue;

      if (!fillValue && fieldData?.type !== 'file') {
        continue;
      }

      approvedFields.push({
        id: fieldId,
        proposedValue: fillValue,
        frameId: fieldData?.frameId
      });

      // 2. Check if we should save/learn this answer
      const learnChk = document.getElementById(`learn-${fieldId}`) as HTMLInputElement | null;
      if (learnChk && learnChk.checked && fillValue) {
        if (fieldData) {
          const scopeSelect = document.getElementById(`scope-${fieldId}`) as HTMLSelectElement | null;
          const scope = (scopeSelect?.value || 'global') as LearnedAnswerScope;

          try {
            await learnAnswer({
              questionText: fieldData.labelText || fieldData.name || fieldData.placeholder || 'Custom question',
              fieldType: fieldData.type,
              answer: fillValue,
              options: fieldData.options,
              canonicalKey: fieldData.canonicalKey || 'customQuestion',
              scope,
              company: scope === 'company' ? detectedCompany : undefined,
              domain: scope === 'domain' ? (tab.url ? new URL(tab.url).hostname : undefined) : undefined
            });
          } catch (err) {
            console.warn('[JobFill] Failed to learn answer:', err);
          }
        }
      }
    }

    // Show loader and run autofill (no fake progress delay)
    setStatusDot('busy');
    setActionTitle('Filling form…');
    showLoaderPanel(AUTOFILL_MESSAGES[0]);
    btnAutofill?.setAttribute('disabled', 'true');
    btnScan?.setAttribute('disabled', 'true');

    const stopMessages = cycleMessages(AUTOFILL_MESSAGES, (message, index) => {
      const status = document.getElementById('progress-status');
      animateLoaderMessage(status, message);
      updateLoaderSteps(index);
    }, 2200);

    await new Promise<void>((resolve) => {
      void executeActualAutofill(() => resolve());
    });

    stopMessages();

    async function executeActualAutofill(onDone: () => void) {
      const finishAutofill = (handler: () => void | Promise<void>) => {
        void Promise.resolve(handler()).finally(onDone);
      };

      let settled = false;
      const settle = (handler: () => void | Promise<void>) => {
        if (settled) return;
        settled = true;
        clearTimeout(autofillTimeout);
        finishAutofill(handler);
      };

      const operationId = createOperationId('autofill');
      startTrace(operationId, 'autofill', 'popup:autofill', { tabUrl: tab.url, tabId: tab.id });

      const autofillTimeout = setTimeout(() => {
        stopMessages();
        hideLoaderPanel();
        btnAutofill?.removeAttribute('disabled');
        btnScan?.removeAttribute('disabled');
        setStatusDot('ready');
        setActionTitle('Timed out');
        setScanStatus('Autofill took too long — try the floating button or retry.');
        failTrace(operationId, 'autofill', 'popup:autofill', 'Timed out waiting for background response', {
          tabUrl: tab.url,
          timeoutMs: 120_000
        });
        logToServer({
          level: 'error',
          source: 'popup:autofill',
          message: 'Autofill timed out waiting for background response',
          detail: { tabUrl: tab.url, timeoutMs: 120_000, operationId }
        });
        settle(() => undefined);
      }, 120_000);

      await syncFromServer();
      const profile = enrichProfile((await getProfile()) || createEmptyProfile());
      profile.resume = cachedResume ?? profile.resume;
      profile.coverLetter = cachedCoverLetter ?? profile.coverLetter;

      const overrides: Record<string, string> = {};
      for (const field of currentScannedFields) {
        if (field.proposedValue?.trim()) {
          overrides[field.id] = field.proposedValue.trim();
        }
      }

      const elements = document.querySelectorAll('.review-input-el');
      for (const el of elements) {
        const fieldId = el.getAttribute('data-field-id');
        if (!fieldId) continue;
        const fillToggle = document.querySelector(
          `.review-fill-toggle[data-field-id="${fieldId}"]`
        ) as HTMLInputElement | null;
        if (fillToggle && !fillToggle.checked) {
          delete overrides[fieldId];
          continue;
        }
        const val = (el as HTMLInputElement | HTMLSelectElement).value.trim();
        if (val) overrides[fieldId] = val;
      }

      const frameIds = [
        ...new Set(
          currentScannedFields
            .map((field) => field.frameId)
            .filter((frameId): frameId is number => typeof frameId === 'number')
        )
      ];

      chrome.runtime.sendMessage(
        { action: 'autofill-complete-all-frames', tabId: tab.id, profile, overrides, frameIds, operationId },
        async (response) => {
          if (chrome.runtime.lastError) {
            settle(async () => {
              failTrace(operationId, 'autofill', 'popup:autofill', chrome.runtime.lastError?.message || 'Runtime message failed', {
                tabUrl: tab.url
              });
              hideLoaderPanel();
              setStatusDot('ready');
              setActionTitle('Fill failed');
              setScanStatus(chrome.runtime.lastError?.message || 'Extension connection lost.');
              logToServer({
                level: 'error',
                source: 'popup:autofill',
                message: chrome.runtime.lastError?.message || 'Runtime message failed',
                detail: { tabUrl: tab.url }
              });
            });
            return;
          }

          btnAutofill?.removeAttribute('disabled');
          btnScan?.removeAttribute('disabled');
          const progressContainer = document.getElementById('autofill-progress-container');

          if (response && response.success) {
          settle(async () => {
          stopMessages();
          logAutofillResult('popup:autofill', {
            filledCount: response.filledCount,
            errors: response.errors,
            url: tab.url,
            company: detectedCompany,
            detail: { frameIds, operationId }
          });
          // Log field errors to IndexedDB if any occurred
          if (response.errors && response.errors.length > 0) {
            for (const err of response.errors) {
              await logActivityEvent({
                type: 'autofill_error',
                message: `Failed to fill field "${err.label}": ${err.error}`,
                metadata: { company: detectedCompany, role: detectedRole, url: tab.url }
              });
            }
          }

          // Track application in IndexedDB and sync to db.json
          await saveApplication({
            jobId: generateId(),
            companyId: generateId(),
            companyName: detectedCompany,
            roleTitle: detectedRole,
            status: 'ready_to_submit',
            priority: 'medium',
            resumeUsedId: cachedResume?.name,
            coverLetterUsedId: cachedCoverLetter?.name,
            notes: tab.url || ''
          });
          await syncToServer();
          await loadTracker();

          // Render Success Animation
          if (progressContainer) {
            const initialHtml = progressContainer.innerHTML;
            const skippedFields = response.skippedFields || [];
            const skippedHtml =
              skippedFields.length > 0
                ? `<div class="skipped-fields-panel" style="margin-top: 10px; text-align: left;">
                    <div style="font-size: 0.68rem; color: var(--error-color); margin-bottom: 6px;">
                      ${skippedFields.length} field${skippedFields.length === 1 ? '' : 's'} need a manual look:
                    </div>
                    <div style="display: flex; flex-direction: column; gap: 6px;">
                      ${skippedFields
                        .map(
                          (field: { label: string; reason: string; fieldId?: string }) =>
                            `<button type="button" class="skipped-field-link" data-field-id="${field.fieldId || ''}" data-field-label="${escapePopupHtml(field.label)}" style="text-align:left; background: rgba(251,113,133,0.08); border: 1px solid rgba(251,113,133,0.25); color: var(--text-primary); border-radius: 8px; padding: 8px 10px; font-size: 0.72rem; cursor: pointer;">
                              ${escapePopupHtml(field.label)}
                              <span style="display:block; margin-top:2px; color: var(--text-muted); font-size: 0.66rem;">${escapePopupHtml(field.reason)}</span>
                            </button>`
                        )
                        .join('')}
                    </div>
                  </div>`
                : response.errors && response.errors.length > 0
                  ? `<div style="font-size: 0.68rem; color: var(--error-color);">${response.errors.length} fields need a manual look.</div>`
                  : '';
            progressContainer.innerHTML = `
              <div class="checkmark-container">
                <div class="checkmark-circle">✓</div>
                <div style="font-weight: 600; color: var(--accent-color); font-size: 0.95rem;">Done</div>
                <div style="font-size: 0.72rem; color: var(--text-muted);">${response.filledCount} fields filled.</div>
                ${skippedHtml}
              </div>
            `;
            progressContainer.querySelectorAll('.skipped-field-link').forEach((button) => {
              button.addEventListener('click', () => {
                if (!tab.id) return;
                const fieldId = button.getAttribute('data-field-id') || '';
                const fieldLabel = button.getAttribute('data-field-label') || '';
                chrome.tabs.sendMessage(tab.id, { action: 'scroll-to-field', fieldId, label: fieldLabel });
              });
            });
            setActionTitle('Fill complete');
            setStatusDot('ready');
            setScanStatus(
              skippedFields.length
                ? `Filled ${response.filledCount} fields. Tap a skipped field to jump to it.`
                : `Filled ${response.filledCount} fields. Review anything we missed.`
            );
            setTimeout(() => {
              progressContainer.style.display = 'none';
              progressContainer.innerHTML = initialHtml;
            }, skippedFields.length ? 12000 : 3200);
          } else {
            alert(`Filled ${response.filledCount} fields.`);
          }
          });
        } else {
          settle(async () => {
          stopMessages();
          hideLoaderPanel();
          setStatusDot('ready');
          setActionTitle('Fill failed');
          setScanStatus(response?.error || 'Autofill did not complete.');
          logToServer({
            level: 'error',
            source: 'popup:autofill',
            message: response?.error || 'Autofill communication failed',
            detail: { company: detectedCompany, tabUrl: tab.url, frameIds }
          });
          await logActivityEvent({
            type: 'autofill_error',
            message: `Autofill crashed: ${response?.error || 'Unknown communication exception'}`,
            metadata: { company: detectedCompany, url: tab.url }
          });
          if (progressContainer) {
            progressContainer.style.display = 'none';
          }
          alert('Autofill failed: ' + (response?.error || 'Unknown error'));
          });
        }
      });
    }
  });

  // Cover Letter Compilation
  const btnCompileCl = document.getElementById('btn-compile-cl');
  btnCompileCl?.addEventListener('click', async () => {
    const profile = await getProfile();
    if (!profile) {
      alert('Please save your profile first to compile details.');
      return;
    }

    const templateId = (document.getElementById('cl-template-select') as HTMLSelectElement).value;
    const docData = await getDocuments();
    const template = docData.coverLetterTemplates.find((t) => t.id === templateId);

    if (template) {
      const output = await compileCoverLetter(template.body, {
        company: detectedCompany || '[Company]',
        role: detectedRole || '[Role]',
        candidateName: profile.fullName || 'Jane Doe',
        topSkills: profile.currentTitle || 'Software Engineering',
        experienceSummary: profile.summary || 'A seasoned professional with years of expertise.'
      });

      const txt = document.getElementById('cl-output') as HTMLTextAreaElement;
      if (txt) txt.value = output;
    }
  });

  // Add Manual Tracker Entry
  const btnAddTracker = document.getElementById('btn-add-tracker');
  const trackerForm = document.getElementById('tracker-form');
  btnAddTracker?.addEventListener('click', () => {
    if (trackerForm) {
      trackerForm.hidden = !trackerForm.hidden;
    }
  });

  trackerForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const company = (document.getElementById('track-company') as HTMLInputElement).value;
    const role = (document.getElementById('track-role') as HTMLInputElement).value;
    const url = (document.getElementById('track-url') as HTMLInputElement).value;
    const status = (document.getElementById('track-status') as HTMLSelectElement).value as ApplicationStatus;

    await saveApplication({
      jobId: generateId(),
      companyId: generateId(),
      companyName: company,
      roleTitle: role,
      status: status === 'autofilled' ? 'autofilled' : status === 'submittedManually' ? 'submitted' : 'saved',
      priority: 'medium',
      notes: url
    });
    await syncToServer();

    trackerForm.reset();
    trackerForm.hidden = true;
    await loadTracker();
  });

  // Setup Document uploads
  setupFileUpload('resume-zone', 'resume-input', 'resume-filename', (f) => (cachedResume = f));
  setupFileUpload('coverletter-zone', 'coverletter-input', 'coverletter-filename', (f) => (cachedCoverLetter = f));

  // Search learned questions
  const searchInput = document.getElementById('learning-search');
  searchInput?.addEventListener('input', async (e) => {
    const term = (e.target as HTMLInputElement).value.toLowerCase();
    await loadLearningCenter(term);
  });

  // Auto-scan current job page on load
  setTimeout(() => {
    btnScan?.click();
  }, 200);
}

/**
 * Handles Tab navigation
 */
function setupTabs() {
  const tabs = document.querySelectorAll('.tab-btn');
  tabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      tabs.forEach((t) => t.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach((c) => c.classList.remove('active'));

      tab.classList.add('active');
      const target = tab.getAttribute('data-tab');
      if (target) {
        document.getElementById(target)?.classList.add('active');
      }
    });
  });
}

/**
 * Renders mapped fields list in Actions review card list
 */
function renderReviewFields(fields: any[]) {
  const container = document.getElementById('review-list');
  if (!container) return;
  container.innerHTML = '';

  if (fields.length === 0) {
    container.innerHTML = emptyStateHtml('📭', 'No inputs found', 'The scanner did not detect any fillable fields.');
    return;
  }

  fields.forEach((field) => {
    const card = document.createElement('div');
    card.className = 'review-card';

    // Badge color
    let badgeClass = 'badge-needs-answer';
    if (field.confidence === 'high') badgeClass = 'badge-high';
    else if (field.confidence === 'medium') badgeClass = 'badge-medium';
    else if (field.confidence === 'low') badgeClass = 'badge-low';

    const isCustom = !field.canonicalKey || field.canonicalKey === 'customQuestion';
    const badgeText = isCustom ? 'Needs Answer' : field.confidence;

    // Field control
    let controlHtml = '';
    if (field.type === 'select') {
      const selected = field.proposedValue || '';
      if (field.options?.length) {
        const opts = field.options
          .map((o: string) => `<option value="${o}" ${selected === o ? 'selected' : ''}>${o}</option>`)
          .join('');
        controlHtml = `<select class="review-input-el" data-field-id="${field.id}">${opts}</select>`;
      } else {
        controlHtml = `<input type="text" class="review-input-el" data-field-id="${field.id}" value="${selected}" placeholder="Select option...">`;
      }
    } else if (field.type === 'file') {
      const isCover = (field.labelText || '').toLowerCase().includes('cover') || (field.name || '').toLowerCase().includes('cover');
      const defaultName = isCover
        ? (cachedCoverLetter?.name || 'Click or drop cover letter...')
        : (cachedResume?.name || 'Click or drop resume...');
      controlHtml = `
        <div class="popup-file-dropzone" id="dropzone-${field.id}" style="border: 1.5px dashed var(--panel-border); padding: 12px; border-radius: 10px; text-align: center; cursor: pointer; background: rgba(255,255,255,0.01); transition: border-color 0.25s, background-color 0.25s;">
          <span style="font-size: 1.1rem; display: block; margin-bottom: 4px;">📁</span>
          <span id="filename-${field.id}" style="font-size: 0.76rem; color: var(--text-secondary); word-break: break-all;">
            ${defaultName}
          </span>
          <input type="file" id="fileinput-${field.id}" class="review-input-el" data-field-id="${field.id}" accept=".pdf,.doc,.docx" style="display: none;">
        </div>
      `;
    } else {
      controlHtml = `<input type="text" class="review-input-el" data-field-id="${field.id}" value="${field.proposedValue || ''}" placeholder="Answer details...">`;
    }

    card.innerHTML = `
      <div class="review-card-header">
        <label class="field-checkbox-container">
          <input type="checkbox" class="field-checkbox review-fill-toggle" data-field-id="${field.id}" checked>
          <span class="field-title">${field.labelText || field.name || 'Unnamed field'}</span>
        </label>
        <span class="badge ${badgeClass}">${badgeText}</span>
      </div>
      <div class="review-card-body">
        ${controlHtml}
        ${
          field.confidence !== 'high'
            ? `
          <label class="learn-toggle">
            <input type="checkbox" id="learn-${field.id}" checked>
            <span>Learn this answer</span>
            <select id="scope-${field.id}" style="padding: 2px; font-size: 0.7rem;">
              <option value="global">Globally</option>
              <option value="company">For this Company only</option>
              <option value="domain">For this Domain only</option>
            </select>
          </label>
        `
            : ''
        }
      </div>
    `;
    container.appendChild(card);

    if (field.type === 'file') {
      const dropzone = document.getElementById(`dropzone-${field.id}`);
      const fileinput = document.getElementById(`fileinput-${field.id}`) as HTMLInputElement;
      const filenameSpan = document.getElementById(`filename-${field.id}`);

      if (dropzone && fileinput && filenameSpan) {
        dropzone.addEventListener('click', (e) => {
          if (e.target === fileinput) return;
          fileinput.click();
        });

        fileinput.addEventListener('click', (e) => {
          e.stopPropagation();
        });

        const handleFileSelection = (file: File) => {
          filenameSpan.textContent = file.name;
          filenameSpan.style.color = 'var(--accent-color)';

          const reader = new FileReader();
          reader.onload = async (e) => {
            const base64 = e.target?.result as string;
            if (base64) {
              const attachment = { name: file.name, type: file.type, base64 };
              const isCover = (field.labelText || '').toLowerCase().includes('cover') || (field.name || '').toLowerCase().includes('cover');
              if (isCover) {
                cachedCoverLetter = attachment;
              } else {
                cachedResume = attachment;
              }

              // Persist dropped document to extension storage and sync to local database
              try {
                const docs = await getDocuments();
                if (isCover) {
                  docs.defaultCoverLetter = attachment;
                } else {
                  docs.defaultResume = attachment;
                }
                await saveDocuments(docs);
                await syncToServer();
                console.log(`[JobFill] Document "${file.name}" saved and synced successfully.`);
              } catch (err) {
                console.error('[JobFill] Failed to auto-save dropped file:', err);
              }
            }
          };
          reader.readAsDataURL(file);
        };

        fileinput.addEventListener('change', () => {
          if (fileinput.files?.length) {
            handleFileSelection(fileinput.files[0]);
          }
        });

        dropzone.addEventListener('dragover', (e) => {
          e.preventDefault();
          dropzone.style.borderColor = 'var(--accent-color)';
          dropzone.style.background = 'rgba(46, 229, 157, 0.04)';
        });
        dropzone.addEventListener('dragleave', () => {
          dropzone.style.borderColor = 'var(--panel-border)';
          dropzone.style.background = 'rgba(255,255,255,0.01)';
        });
        dropzone.addEventListener('drop', (e) => {
          e.preventDefault();
          dropzone.style.borderColor = 'var(--panel-border)';
          dropzone.style.background = 'rgba(255,255,255,0.01)';
          if (e.dataTransfer?.files.length) {
            fileinput.files = e.dataTransfer.files;
            handleFileSelection(e.dataTransfer.files[0]);
          }
        });
      }
    }
  });
}

/**
 * Loads profile settings
 */
async function loadProfile() {
  // Managed via Dashboard
}

/**
 * Loads uploaded files
 */
async function loadDocuments() {
  const docs = await getDocuments();
  if (docs.defaultResume) {
    cachedResume = docs.defaultResume;
    const resumeEl = document.getElementById('resume-filename');
    if (resumeEl) resumeEl.textContent = docs.defaultResume.name;
  }
  if (docs.defaultCoverLetter) {
    cachedCoverLetter = docs.defaultCoverLetter;
    const coverEl = document.getElementById('coverletter-filename');
    if (coverEl) coverEl.textContent = docs.defaultCoverLetter.name;
  }
}

/**
 * Loads Learning center list
 */
async function loadLearningCenter(searchTerm = '') {
  const answers = await getLearnedAnswers();
  const list = document.getElementById('learning-list');
  if (!list) return;

    const filtered = answers.filter((a) => {
      if (!searchTerm) return true;
      const q = (a.questionText || '').toLowerCase();
      const ans = (a.answer || '').toLowerCase();
      const scope = (a.scope || '').toLowerCase();
      return q.includes(searchTerm) || ans.includes(searchTerm) || scope.includes(searchTerm);
    });

  if (filtered.length === 0) {
    list.innerHTML = '<tr><td colspan="5" class="empty-table">No matching records found.</td></tr>';
    return;
  }

  list.innerHTML = filtered
    .map(
      (a) => `
    <tr>
      <td>${a.questionText}</td>
      <td>${a.answer}</td>
      <td><span class="badge badge-needs-answer">${a.scope}</span></td>
      <td>${a.usageCount}</td>
      <td>
        <button type="button" class="btn-icon delete-learned-btn" data-id="${a.id}">🗑️</button>
      </td>
    </tr>
  `
    )
    .join('');

  // Attach delete buttons
  document.querySelectorAll('.delete-learned-btn').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      const id = (e.target as HTMLElement).getAttribute('data-id')!;
      if (confirm('Delete this learned question from memory?')) {
        await deleteLearnedAnswer(id);
        await loadLearningCenter(searchTerm);
      }
    });
  });
}

/**
 * Loads tracker list
 */
async function loadTracker() {
  const records = await getApplications();
  const submittedCount = await countSubmittedApplications();
  const list = document.getElementById('tracker-list');
  const submittedTotal = document.getElementById('tracker-submitted-total');
  const tabBadge = document.getElementById('tracker-applied-count');

  if (submittedTotal) submittedTotal.textContent = String(submittedCount);
  if (tabBadge) {
    tabBadge.textContent = String(submittedCount);
    tabBadge.hidden = submittedCount === 0;
  }

  if (!list) return;

  if (records.length === 0) {
    list.innerHTML = '<tr><td colspan="5" class="empty-table">No applications logged yet.</td></tr>';
    return;
  }

  list.innerHTML = records
    .map(
      (r) => `
    <tr>
      <td><strong>${r.companyName}</strong></td>
      <td>${r.roleTitle}</td>
      <td>${new Date(r.submittedAt || r.createdAt).toLocaleDateString()}</td>
      <td><span class="badge badge-high">${r.status === 'submitted' ? 'Applied' : r.status}</span></td>
      <td>
        <button type="button" class="btn-icon delete-track-btn" data-id="${r.id}">🗑️</button>
      </td>
    </tr>
  `
    )
    .join('');

  document.querySelectorAll('.delete-track-btn').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      const id = (e.target as HTMLElement).getAttribute('data-id')!;
      if (confirm('Delete this application record?')) {
        await deleteApplication(id);
        await syncToServer();
        await loadTracker();
      }
    });
  });
}

/**
 * Helpers
 */
function setupFileUpload(
  zoneId: string,
  inputId: string,
  filenameId: string,
  onLoaded: (file: FileAttachment) => void
) {
  const zone = document.getElementById(zoneId);
  const input = document.getElementById(inputId) as HTMLInputElement;
  const filename = document.getElementById(filenameId);

  if (!zone || !input || !filename) return;

  zone.addEventListener('click', () => input.click());
  zone.addEventListener('dragover', (e) => {
    e.preventDefault();
    zone.classList.add('dragover');
  });
  zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
  zone.addEventListener('drop', (e) => {
    e.preventDefault();
    zone.classList.remove('dragover');
    if (e.dataTransfer?.files.length) {
      input.files = e.dataTransfer.files;
      handleFile(e.dataTransfer.files[0], filename, onLoaded);
    }
  });

  input.addEventListener('change', () => {
    if (input.files?.length) {
      handleFile(input.files[0], filename, onLoaded);
    }
  });
}

function handleFile(
  file: File,
  filenameEl: HTMLElement,
  onLoaded: (file: FileAttachment) => void
) {
  filenameEl.textContent = file.name;
  const reader = new FileReader();
  reader.onload = (e) => {
    const base64 = e.target?.result as string;
    if (base64) {
      onLoaded({
        name: file.name,
        type: file.type,
        base64
      });
    }
  };
  reader.readAsDataURL(file);
}
