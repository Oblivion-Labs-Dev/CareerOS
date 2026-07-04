import { JobDetails } from '../shared/types';

export interface PlatformAdapter {
  detect(doc: Document): boolean;
  extractJobDetails(doc: Document): JobDetails;
}

export class GenericAdapter implements PlatformAdapter {
  detect(doc: Document): boolean {
    return true; // Default fallback
  }

  extractJobDetails(doc: Document): JobDetails {
    // Try standard page title
    let title = doc.title || 'Unknown Role';
    if (title.includes(' - ')) {
      title = title.split(' - ')[0];
    } else if (title.includes(' | ')) {
      title = title.split(' | ')[0];
    }

    return {
      company: 'Unknown Company',
      role: title.trim(),
      location: 'Remote / Unspecified',
      description: doc.body.innerText.slice(0, 500) + '...',
      platform: 'Generic'
    };
  }
}
