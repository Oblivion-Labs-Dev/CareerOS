import '../shared/process-shim';
import { registerExtensionConfigListeners } from './extensionConfig';
import { scanAllFrames, autofillAllFrames, autofillCompleteAllFrames } from './tabMessaging';
import {
  saveApplication,
  findApplicationByUrl,
  findApplicationForSubmit
} from '../db/repositories/applicationRepository';
import { isBetterCompanyName, isBetterRoleTitle } from '../shared/jobUrlMatching';
import { logChronicle as logActivityEvent } from '../db/repositories/chronicleRepository';
import { generateId } from '../shared/id';
import { getCurrentDateTimeISO } from '../shared/dateUtils';
import { syncToServer } from '../db/sync';
import { logToServer } from '../shared/serverLog';
import { fillReactSelectInMainWorld } from './mainWorldReactSelect';

registerExtensionConfigListeners();

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === 'scan-all-frames') {
    const tabId = message.tabId ?? sender.tab?.id;
    if (!tabId) {
      sendResponse({ success: false, error: 'No active tab for scan.' });
      return true;
    }
    scanAllFrames(tabId, message.profile, message.operationId).then(sendResponse);
    return true;
  }

  if (message.action === 'autofill-all-frames') {
    autofillAllFrames(message.tabId, message.fields, message.profile).then(sendResponse);
    return true;
  }

  if (message.action === 'autofill-complete-all-frames') {
    autofillCompleteAllFrames(
      message.tabId,
      message.profile,
      message.overrides,
      message.frameIds,
      message.operationId
    ).then(sendResponse);
    return true;
  }

  if (message.action === 'autofill-active-tab') {
    const tabId = sender.tab?.id;
    if (!tabId) {
      sendResponse({ success: false, error: 'No active tab for autofill.' });
      return true;
    }
    autofillCompleteAllFrames(
      tabId,
      message.profile,
      message.overrides,
      message.frameIds,
      message.operationId
    ).then(sendResponse);
    return true;
  }

  if (message.action === 'main-world-fill-react-select') {
    const tabId = sender.tab?.id;
    const frameId = sender.frameId ?? 0;
    if (!tabId || !message.inputId || !message.value) {
      sendResponse({ success: false });
      return false;
    }
    fillReactSelectInMainWorld(tabId, frameId, message.inputId as string, message.value as string).then(
      (success) => sendResponse({ success })
    );
    return true;
  }

  if (message.action === 'get-profile-for-autofill') {
    (async () => {
      try {
        const { resolveProfileForAutofill } = await import('../profile/profileStore');
        const profile = await resolveProfileForAutofill();
        sendResponse({ success: true, profile });
      } catch (err: any) {
        sendResponse({ success: false, error: err.message });
      }
    })();
    return true;
  }

  if (message.action === 'record-job-submit') {
    (async () => {
      try {
        const payload = message.payload as {
          url: string;
          company: string;
          role: string;
          location?: string;
          platform?: string;
          trigger: string;
          buttonText: string;
        };

        const existing = await findApplicationForSubmit({
          url: payload.url,
          company: payload.company,
          role: payload.role
        });
        const now = getCurrentDateTimeISO();
        const companyName = isBetterCompanyName(payload.company, existing?.companyName)
          ? payload.company
          : existing?.companyName || payload.company;
        const roleTitle = isBetterRoleTitle(payload.role, existing?.roleTitle)
          ? payload.role
          : existing?.roleTitle || payload.role;
        const saved = await saveApplication({
          id: existing?.id,
          jobId: existing?.jobId || generateId(),
          companyId: existing?.companyId || generateId(),
          companyName,
          roleTitle,
          location: payload.location || existing?.location,
          platform: payload.platform || existing?.platform,
          source: payload.trigger,
          status: 'submitted',
          priority: existing?.priority || 'medium',
          resumeUsedId: existing?.resumeUsedId,
          coverLetterUsedId: existing?.coverLetterUsedId,
          submittedAt: now,
          notes: payload.url
        });

        await logActivityEvent({
          type: 'application_submitted',
          message: `Application submitted (${payload.trigger}): ${payload.company} — ${payload.role}`,
          metadata: {
            url: payload.url,
            buttonText: payload.buttonText,
            platform: payload.platform
          },
          applicationId: saved.id,
          jobId: saved.jobId
        });

        await syncToServer();

        logToServer({
          level: 'info',
          source: 'background:submit-tracker',
          message: `Recorded application submit for ${companyName}`,
          detail: {
            role: roleTitle,
            trigger: payload.trigger,
            buttonText: payload.buttonText,
            applicationId: saved.id
          },
          url: payload.url
        });

        sendResponse({
          success: true,
          applicationId: saved.id,
          company: saved.companyName,
          role: saved.roleTitle,
          location: saved.location,
          platform: saved.platform,
          submittedAt: saved.submittedAt
        });

        chrome.tabs.query({}, (tabs) => {
          for (const tab of tabs) {
            if (!tab.id) continue;
            chrome.tabs.sendMessage(tab.id, { action: 'pipeline-updated', status: 'submitted' }).catch(() => {});
          }
        });
      } catch (err: any) {
        sendResponse({ success: false, error: err.message });
      }
    })();
    return true;
  }

  if (message.action === 'get-tracker-stages-count') {
    (async () => {
      try {
        const { getApplications } = await import('../db/repositories/applicationRepository');
        const apps = await getApplications();
        sendResponse({
          success: true,
          stages: {
            saved: apps.filter((a) => a.status === 'saved').length,
            applied: apps.filter((a) => a.status === 'submitted').length,
            interview: apps.filter((a) => a.status === 'interviewing').length,
            offer: apps.filter((a) => a.status === 'offer').length
          }
        });
      } catch (err: any) {
        sendResponse({ success: false, error: err.message });
      }
    })();
    return true;
  }

  if (message.action === 'check-job-saved') {
    (async () => {
      try {
        const url = message.url as string;
        const existing = await findApplicationByUrl(url);
        if (!existing) {
          sendResponse({ saved: false });
          return;
        }
        const pipelineStatuses = new Set(['saved', 'submitted', 'interviewing', 'offer', 'rejected']);
        sendResponse({
          saved: true,
          status: pipelineStatuses.has(existing.status) ? existing.status : 'saved'
        });
      } catch (err: any) {
        sendResponse({ saved: false, error: err.message });
      }
    })();
    return true;
  }

  if (message.action === 'record-job-save') {
    (async () => {
      try {
        const payload = message.payload as {
          url: string;
          company: string;
          role: string;
          location?: string;
          platform?: string;
          status?: string;
          source?: string;
          salary?: string;
          employmentType?: string;
          workMode?: string;
          description?: string;
          h1bStatus?: string;
          h1bLabel?: string;
        };

        const { saveJobToTracker } = await import('../shared/saveJobToTracker');
        const result = await saveJobToTracker({
          url: payload.url,
          company: payload.company,
          role: payload.role,
          location: payload.location,
          platform: payload.platform,
          status: payload.status as import('../shared/saveJobToTracker').TrackerPipelineStatus,
          source: payload.source,
          salary: payload.salary,
          employmentType: payload.employmentType,
          workMode: payload.workMode,
          description: payload.description,
          h1bStatus: payload.h1bStatus,
          h1bLabel: payload.h1bLabel
        });

        sendResponse(result);
      } catch (err: any) {
        sendResponse({ success: false, error: err.message });
      }
    })();
    return true;
  }

  if (message.action === 'record-job-autofill') {
    (async () => {
      try {
        const payload = message.payload as {
          url: string;
          company: string;
          role: string;
          location?: string;
          platform?: string;
          filledCount?: number;
        };

        const existing = await findApplicationForSubmit({
          url: payload.url,
          company: payload.company,
          role: payload.role
        });
        const nextStatus = existing?.status === 'submitted' ? 'submitted' : 'autofilled';
        const companyName = isBetterCompanyName(payload.company, existing?.companyName)
          ? payload.company
          : existing?.companyName || payload.company;
        const roleTitle = isBetterRoleTitle(payload.role, existing?.roleTitle)
          ? payload.role
          : existing?.roleTitle || payload.role;
        const saved = await saveApplication({
          id: existing?.id,
          jobId: existing?.jobId || generateId(),
          companyId: existing?.companyId || generateId(),
          companyName,
          roleTitle,
          location: payload.location || existing?.location,
          platform: payload.platform || existing?.platform,
          status: nextStatus,
          priority: existing?.priority || 'medium',
          resumeUsedId: existing?.resumeUsedId,
          coverLetterUsedId: existing?.coverLetterUsedId,
          submittedAt: existing?.submittedAt,
          notes: payload.url
        });

        await logActivityEvent({
          type: 'application_autofilled',
          message: `Application tracked after autofill: ${payload.company} — ${payload.role}`,
          metadata: {
            url: payload.url,
            platform: payload.platform,
            filledCount: payload.filledCount
          },
          applicationId: saved.id,
          jobId: saved.jobId
        });

        await syncToServer();

        sendResponse({
          success: true,
          applicationId: saved.id,
          company: saved.companyName,
          role: saved.roleTitle,
          status: saved.status
        });
      } catch (err: any) {
        sendResponse({ success: false, error: err.message });
      }
    })();
    return true;
  }

  if (message.action === 'get-saved-job-urls') {
    (async () => {
      try {
        const { getApplications } = await import('../db/repositories/applicationRepository');
        const apps = await getApplications();
        sendResponse({ urls: apps.map((a) => a.url).filter(Boolean) });
      } catch (err: any) {
        sendResponse({ urls: [], error: err.message });
      }
    })();
    return true;
  }

  if (message.action === 'get-apply-queue') {
    (async () => {
      try {
        const { getApplyQueue } = await import('../shared/applyQueue');
        sendResponse({ success: true, queue: await getApplyQueue() });
      } catch (err: any) {
        sendResponse({ success: false, error: err.message });
      }
    })();
    return true;
  }

  if (message.action === 'add-to-apply-queue') {
    (async () => {
      try {
        const { addToApplyQueue } = await import('../shared/applyQueue');
        const item = await addToApplyQueue(message.payload);
        sendResponse({ success: true, item });
      } catch (err: any) {
        sendResponse({ success: false, error: err.message });
      }
    })();
    return true;
  }

  if (message.action === 'remove-from-apply-queue') {
    (async () => {
      try {
        const { removeFromApplyQueue } = await import('../shared/applyQueue');
        await removeFromApplyQueue(message.id as string);
        sendResponse({ success: true });
      } catch (err: any) {
        sendResponse({ success: false, error: err.message });
      }
    })();
    return true;
  }

  if (message.action === 'start-apply-queue') {
    (async () => {
      try {
        const { getNextQueuedJob, markQueueItem } = await import('../shared/applyQueue');
        const next = await getNextQueuedJob();
        if (!next) {
          sendResponse({ success: false, error: 'Queue is empty' });
          return;
        }
        await markQueueItem(next.id, 'in_progress');
        const tab = await chrome.tabs.create({ url: next.url, active: true });
        sendResponse({ success: true, item: next, tabId: tab.id });
      } catch (err: any) {
        sendResponse({ success: false, error: err.message });
      }
    })();
    return true;
  }

  if (message.action === 'learn-submitted-answer') {
    (async () => {
      try {
        const { learnAnswer } = await import('../learning/learningEngine');
        await learnAnswer({
          questionText: message.questionText,
          fieldType: message.fieldType,
          answer: message.answer,
          options: message.options,
          scope: 'global'
        });
        sendResponse({ success: true });
      } catch (err: any) {
        sendResponse({ success: false, error: err.message });
      }
    })();
    return true;
  }

  return false;
});

function reloadOpenJobTabs(): void {
  chrome.tabs.query({ url: ['http://*/*', 'https://*/*'] }, (tabs) => {
    for (const tab of tabs) {
      if (tab.id != null) {
        void chrome.tabs.reload(tab.id).catch(() => {});
      }
    }
  });
}

chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === 'update' || details.reason === 'install') {
    reloadOpenJobTabs();
  }
});
