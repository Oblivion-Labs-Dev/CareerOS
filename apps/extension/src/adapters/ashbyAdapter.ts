import { JobDetails } from '../shared/types';
import { PlatformAdapter } from './genericAdapter';
import { parseCompanyFromJobUrl } from '../shared/jobUrlMatching';

function cleanText(value?: string | null): string {
  return value?.replace(/\s+/g, ' ').trim() || '';
}

function parseCompanyFromTitle(title: string): string {
  if (!title) return '';
  if (title.includes(' at ')) {
    return cleanText(title.split(' at ')[1]?.split(' - ')[0]);
  }
  const parts = title.split(/\s[-–|]\s/).map((part) => part.trim()).filter(Boolean);
  if (parts.length >= 2) {
    const last = parts[parts.length - 1];
    if (/careers?|jobs?|apply|ashby/i.test(last) && parts.length >= 2) {
      return cleanText(parts[parts.length - 2]);
    }
    return cleanText(last);
  }
  return '';
}

function parseCompanyFromDom(doc: Document): string {
  const logoAlt = cleanText(
    doc.querySelector('header img[alt], nav img[alt], a[href="/"] img[alt]')?.getAttribute('alt')
  );
  if (logoAlt && !/logo|careers|home|apply|jobs/i.test(logoAlt)) {
    return logoAlt;
  }

  const brandLink = doc.querySelector(
    'header a[href="/"], header a[href*="careers"], nav a[href="/"], [class*="company-name"], [class*="CompanyName"]'
  );
  const brandText = cleanText(brandLink?.textContent);
  if (brandText && brandText.length <= 40 && !/careers|jobs|apply/i.test(brandText)) {
    return brandText;
  }

  for (const script of doc.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      const parsed = JSON.parse(script.textContent || '');
      const orgName = cleanText(
        parsed?.hiringOrganization?.name ||
          parsed?.['@graph']?.find?.((node: { '@type'?: string }) => node['@type'] === 'JobPosting')
            ?.hiringOrganization?.name
      );
      if (orgName) return orgName;
    } catch {
      // ignored
    }
  }

  return '';
}

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

    const company =
      parseCompanyFromJobUrl(doc.location.href) ||
      parseCompanyFromDom(doc) ||
      parseCompanyFromTitle(doc.title || '') ||
      'Unknown Company';

    return {
      company,
      role: roleEl?.textContent?.trim() || 'Unknown Role',
      location: locationEl?.textContent?.trim() || 'Unspecified Location',
      description: doc.querySelector('[class*="description"]')?.textContent?.slice(0, 1000) || '',
      platform: 'Ashby'
    };
  }
}
