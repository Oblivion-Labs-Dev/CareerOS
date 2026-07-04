import '../shared/process-shim';
import { registerExtensionConfigListeners } from './extensionConfig';
import { scanAllFrames, autofillAllFrames, autofillCompleteAllFrames } from './tabMessaging';
import {
  saveApplication,
  findApplicationByUrl
} from '../db/repositories/applicationRepository';
import { logChronicle as logActivityEvent } from '../db/repositories/chronicleRepository';
import { generateId } from '../shared/id';
import { getCurrentDateTimeISO } from '../shared/dateUtils';
import { syncToServer } from '../db/sync';
import { logToServer } from '../shared/serverLog';

registerExtensionConfigListeners();

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === 'scan-all-frames') {
    scanAllFrames(message.tabId, message.profile, message.operationId).then(sendResponse);
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

        const existing = await findApplicationByUrl(payload.url);
        const now = getCurrentDateTimeISO();
        const saved = await saveApplication({
          id: existing?.id,
          jobId: existing?.jobId || generateId(),
          companyId: existing?.companyId || generateId(),
          companyName: payload.company,
          roleTitle: payload.role,
          location: payload.location,
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
          message: `Recorded application submit for ${payload.company}`,
          detail: {
            role: payload.role,
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
          role: saved.roleTitle
        });
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
