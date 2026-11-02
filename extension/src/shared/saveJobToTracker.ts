import {
  findApplicationByUrl,
  findApplicationForSubmit,
  saveApplication,
  Application
} from '../db/repositories/applicationRepository';
import { logChronicle as logActivityEvent } from '../db/repositories/chronicleRepository';
import { generateId } from './id';
import { isBetterCompanyName, isBetterRoleTitle } from './jobUrlMatching';
import { syncToServer } from '../db/sync';
import { lookupDiscoverJobByUrl, saveDiscoverJobToCareerOs } from './careerOsBridge';

export type TrackerPipelineStatus =
  | 'saved'
  | 'submitted'
  | 'interviewing'
  | 'offer'
  | 'rejected';

export interface SaveJobPayload {
  url: string;
  company: string;
  role: string;
  location?: string;
  platform?: string;
  status?: TrackerPipelineStatus;
  source?: string;
  salary?: string;
  employmentType?: string;
  workMode?: string;
  description?: string;
  h1bStatus?: string;
  h1bLabel?: string;
}

export interface SaveJobResult {
  success: boolean;
  duplicate?: boolean;
  applicationId?: string;
  company?: string;
  role?: string;
  status?: Application['status'];
  error?: string;
}

function buildNotes(payload: SaveJobPayload): string {
  const parts = [payload.url];
  if (payload.salary) parts.push(`Salary: ${payload.salary}`);
  if (payload.employmentType) parts.push(`Type: ${payload.employmentType}`);
  if (payload.workMode) parts.push(`Mode: ${payload.workMode}`);
  if (payload.h1bLabel) parts.push(`H1B: ${payload.h1bLabel}`);
  if (payload.description) parts.push(`Description: ${payload.description.slice(0, 500)}`);
  return parts.join('\n');
}

export async function saveJobToTracker(payload: SaveJobPayload): Promise<SaveJobResult> {
  try {
    const existing =
      (await findApplicationByUrl(payload.url)) ||
      (await findApplicationForSubmit({
        url: payload.url,
        company: payload.company,
        role: payload.role
      }));

    if (existing && payload.status === 'saved' && existing.status !== 'saved') {
      return {
        success: true,
        duplicate: true,
        applicationId: existing.id,
        company: existing.companyName,
        role: existing.roleTitle,
        status: existing.status
      };
    }

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
      source: payload.source || existing?.source || 'applypilot_save',
      status: payload.status || existing?.status || 'saved',
      priority: existing?.priority || 'medium',
      resumeUsedId: existing?.resumeUsedId,
      coverLetterUsedId: existing?.coverLetterUsedId,
      submittedAt:
        payload.status === 'submitted' ? new Date().toISOString() : existing?.submittedAt,
      notes: buildNotes(payload)
    });

    await logActivityEvent({
      type: existing ? 'status_changed' : 'job_saved',
      message: `${existing ? 'Updated' : 'Saved'} job: ${companyName} — ${roleTitle}`,
      metadata: {
        url: payload.url,
        platform: payload.platform,
        status: saved.status,
        duplicate: Boolean(existing)
      },
      applicationId: saved.id,
      jobId: saved.jobId
    });

    await syncToServer();

    void lookupDiscoverJobByUrl(payload.url).then((discovered) => {
      if (discovered?.id) void saveDiscoverJobToCareerOs(discovered.id);
    });

    return {
      success: true,
      duplicate: Boolean(existing),
      applicationId: saved.id,
      company: saved.companyName,
      role: saved.roleTitle,
      status: saved.status
    };
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Could not save job';
    return { success: false, error: message };
  }
}
