import { JobDetails } from '../shared/types';
import { PlatformAdapter } from './genericAdapter';

export class AshbyAdapter implements PlatformAdapter {
  detect(doc: Document): boolean {
    return (
      doc.location.href.includes('ashbyhq.com') ||
      doc.querySelector('[class*="ashby"]') !== null
    );
  }

  extractJobDetails(doc: Document): JobDetails {
    const roleEl = doc.querySelector('h1, [class*="jobTitle"]');
    const locationEl = doc.querySelector('[class*="location"], [class*="jobLocation"]');
    
    let company = 'Ashby Client';
    const title = doc.title;
    if (title && title.includes(' at ')) {
      company = title.split(' at ')[1].split(' - ')[0].trim();
    }

    return {
      company,
      role: roleEl?.textContent?.trim() || 'Unknown Role',
      location: locationEl?.textContent?.trim() || 'Unspecified Location',
      description: doc.querySelector('[class*="description"]')?.textContent?.slice(0, 1000) || '',
      platform: 'Ashby'
    };
  }
}
