import { JobDetails } from '../shared/types';
import { PlatformAdapter } from './genericAdapter';

export class LeverAdapter implements PlatformAdapter {
  detect(doc: Document): boolean {
    return (
      doc.location.href.includes('lever.co') ||
      doc.querySelector('.lever-job') !== null ||
      doc.querySelector('.posting-header') !== null
    );
  }

  extractJobDetails(doc: Document): JobDetails {
    const roleEl = doc.querySelector('.posting-header h2, h2');
    const locationEl = doc.querySelector('.posting-categories .location, .location');
    
    // Lever title is typically "Company - Job Title"
    let company = 'Unknown Company';
    const pageTitle = doc.title;
    if (pageTitle && pageTitle.includes(' - ')) {
      company = pageTitle.split(' - ')[0].trim();
    }

    return {
      company,
      role: roleEl?.textContent?.trim() || 'Unknown Role',
      location: locationEl?.textContent?.trim() || 'Unspecified Location',
      description: doc.querySelector('.section.page-centered')?.textContent?.slice(0, 1000) || '',
      platform: 'Lever'
    };
  }
}
