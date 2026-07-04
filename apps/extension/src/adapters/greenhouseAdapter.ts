import { JobDetails } from '../shared/types';
import { PlatformAdapter } from './genericAdapter';

export class GreenhouseAdapter implements PlatformAdapter {
  detect(doc: Document): boolean {
    return (
      doc.location.href.includes('greenhouse.io') ||
      doc.location.href.includes('gh_jid') ||
      doc.location.search.includes('gh_jid') ||
      doc.querySelector('#gh_jid') !== null ||
      doc.querySelector('meta[content*="greenhouse.io"]') !== null
    );
  }

  extractJobDetails(doc: Document): JobDetails {
    const roleEl = doc.querySelector('h1.app-title, .job-title');
    const companyEl = doc.querySelector('.company-name, #header-company-logo img');
    const locationEl = doc.querySelector('.location');

    let company = 'Unknown Company';
    if (companyEl) {
      if (companyEl.tagName === 'IMG') {
        company = companyEl.getAttribute('alt') || 'Unknown Company';
      } else {
        company = companyEl.textContent?.trim() || 'Unknown Company';
      }
    }

    return {
      company,
      role: roleEl?.textContent?.trim() || 'Unknown Role',
      location: locationEl?.textContent?.trim() || 'Unspecified Location',
      description: doc.querySelector('#content')?.textContent?.slice(0, 1000) || '',
      platform: 'Greenhouse'
    };
  }
}
