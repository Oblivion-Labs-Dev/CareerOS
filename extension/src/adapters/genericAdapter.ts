import { JobDetails } from '../shared/types';
import { parseCompanyFromJobUrl } from '../shared/jobUrlMatching';
import { parseFromDocumentTitle } from '../shared/jobContextResolver';

export interface PlatformAdapter {
  detect(doc: Document): boolean;
  extractJobDetails(doc: Document): JobDetails;
}

export class GenericAdapter implements PlatformAdapter {
  detect(doc: Document): boolean {
    return true; // Default fallback
  }

  extractJobDetails(doc: Document): JobDetails {
    const titleParts = parseFromDocumentTitle(doc.title || '');
    const urlCompany = parseCompanyFromJobUrl(doc.location.href);

    let title = doc.title || 'Unknown Role';
    if (title.includes(' - ')) {
      title = title.split(' - ')[0];
    } else if (title.includes(' | ')) {
      title = title.split(' | ')[0];
    }

    return {
      company: urlCompany || titleParts.company || 'Unknown Company',
      role: titleParts.role || title.trim(),
      location: 'Remote / Unspecified',
      description: doc.body.innerText.slice(0, 500) + '...',
      platform: 'Generic'
    };
  }
}
