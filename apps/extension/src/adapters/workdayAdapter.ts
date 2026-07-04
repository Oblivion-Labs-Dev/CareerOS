import { JobDetails } from '../shared/types';
import { PlatformAdapter } from './genericAdapter';

export class WorkdayAdapter implements PlatformAdapter {
  detect(doc: Document): boolean {
    return (
      doc.location.href.includes('myworkdayjobs.com') ||
      doc.location.href.includes('myworkdaysite.com') ||
      doc.querySelector('[data-automation-id="workdayLogo"]') !== null ||
      doc.querySelector('[data-automation-id="jobPostingHeader"]') !== null
    );
  }

  extractJobDetails(doc: Document): JobDetails {
    const roleEl = doc.querySelector('[data-automation-id="jobPostingHeader"], h2, h1');
    const locationEl = doc.querySelector('[data-automation-id="location"]');

    let company = 'Workday Client';
    try {
      const hostname = doc.location.hostname;
      const pathMatch = doc.location.pathname.match(/\/recruiting\/([^/]+)/i);
      if (pathMatch?.[1]) {
        company = pathMatch[1].replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
      } else if (hostname.includes('.myworkdayjobs.com')) {
        company = hostname.split('.')[0].replace(/-/g, ' ').toUpperCase();
      }
    } catch {
      // Ignored
    }

    return {
      company,
      role: roleEl?.textContent?.trim() || 'Unknown Role',
      location: locationEl?.textContent?.trim() || 'Unspecified Location',
      description: doc.querySelector('[data-automation-id="jobDescription"]')?.textContent?.slice(0, 1000) || '',
      platform: 'Workday'
    };
  }
}
