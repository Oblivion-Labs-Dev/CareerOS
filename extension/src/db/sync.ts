import { getApplications, saveApplication } from './repositories/applicationRepository';
import { getJobs, saveJob } from './repositories/jobRepository';
import { getLearnedAnswers, saveLearnedAnswer } from './repositories/learnedAnswerRepository';
import { getDocuments, saveDocuments } from '../documents/documentStore';
import { getAutofillSessions, saveAutofillSession } from './repositories/autofillSessionRepository';
import { getFieldMappings, saveFieldMapping } from './repositories/fieldMappingRepository';
import { getChronicles as getActivityEvents, saveChronicle as saveActivityEvent } from './repositories/chronicleRepository';
import { getProfile, saveProfile, mergeProfiles } from '../profile/profileStore';
import { getAutofillLogConfig, setAutofillLogConfig } from '../shared/autofillLogConfig';
import { getSubmitTrackerConfig, setSubmitTrackerConfig } from '../shared/submitTrackerConfig';

import { getServerDbUrl, getParseResumeUrl } from '../shared/apiConfig';

async function parseResumeOnServer(force = false): Promise<boolean> {
  try {
    const res = await fetch(await getParseResumeUrl(), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force })
    });
    return res.ok;
  } catch {
    return false;
  }
}

export async function syncFromServer(): Promise<boolean> {
  try {
    await parseResumeOnServer(false);
    const res = await fetch(await getServerDbUrl());
    if (!res.ok) return false;
    const data = await res.json();

    if (data.profile) {
      const local = await getProfile();
      const merged = mergeProfiles(local, data.profile);
      await saveProfile(merged);
    }
    if (data.documents) {
      const localDocs = await getDocuments();
      const serverHasDocs = Boolean(data.documents.defaultResume || data.documents.defaultCoverLetter);
      const localHasDocs = Boolean(localDocs.defaultResume || localDocs.defaultCoverLetter);
      if (serverHasDocs || !localHasDocs) {
        await saveDocuments({
          ...localDocs,
          ...data.documents,
          coverLetterTemplates: data.documents.coverLetterTemplates?.length
            ? data.documents.coverLetterTemplates
            : localDocs.coverLetterTemplates
        });
      }
    }

    if (data.applications) {
      for (const app of data.applications) {
        await saveApplication(app);
      }
    }
    if (data.jobs) {
      for (const job of data.jobs) {
        await saveJob(job);
      }
    }
    if (data.learnedAnswers) {
      for (const qa of data.learnedAnswers) {
        await saveLearnedAnswer(qa);
      }
    }
    if (data.sessions) {
      for (const s of data.sessions) {
        await saveAutofillSession(s);
      }
    }
    if (data.fieldMappings) {
      for (const fm of data.fieldMappings) {
        await saveFieldMapping(fm);
      }
    }
    if (data.activityEvents) {
      for (const ae of data.activityEvents) {
        await saveActivityEvent(ae);
      }
    }
    if (data.settings?.autofillLog) {
      setAutofillLogConfig(data.settings.autofillLog);
    }
    if (data.settings?.submitTracker) {
      setSubmitTrackerConfig(data.settings.submitTracker);
    }
    console.log('[ApplyPilot Sync] Database pulled successfully from CareerOS API.');
    return true;
  } catch (err) {
    console.warn('[ApplyPilot Sync] API not running or unreachable. Using cached IndexedDB data.');
    return false;
  }
}

export async function syncToServer(): Promise<boolean> {
  try {
    const profile = await getProfile();
    const documents = await getDocuments();
    const applications = await getApplications();
    const jobs = await getJobs();
    const learnedAnswers = await getLearnedAnswers();
    const sessions = await getAutofillSessions();
    const fieldMappings = await getFieldMappings();
    const activityEvents = await getActivityEvents();

    const [autofillLog, submitTracker] = await Promise.all([
      getAutofillLogConfig(),
      getSubmitTrackerConfig(),
    ]);

    const payload = {
      profile,
      documents,
      applications,
      jobs,
      learnedAnswers,
      sessions,
      fieldMappings,
      activityEvents,
      settings: {
        autofillLog,
        submitTracker,
      },
    };

    const res = await fetch(await getServerDbUrl(), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });

    return res.ok;
  } catch (err) {
    console.warn('[ApplyPilot Sync] Failed to write changes to CareerOS API.', err);
    return false;
  }
}

import { registerOnWrite } from './db';

let syncTimeout: any = null;

registerOnWrite(() => {
  if (syncTimeout) clearTimeout(syncTimeout);
  syncTimeout = setTimeout(() => {
    syncToServer();
  }, 1000);
});
