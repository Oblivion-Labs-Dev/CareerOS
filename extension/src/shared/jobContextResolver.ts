import { detectAdapter } from '../adapters';
import { JobDetails } from './types';
import {
  formatCompanySlug,
  isBetterCompanyName,
  isBetterRoleTitle,
  parseCompanyFromJobUrl
} from './jobUrlMatching';

const BAD_COMPANIES = new Set(['unknown company', 'workday client', 'ashby client', 'unknown', '']);
const BAD_ROLES = new Set(['unknown role', 'unknown', '']);

function cleanLabel(value?: string | null): string | undefined {
  if (!value) return undefined;
  const cleaned = value.replace(/\s+/g, ' ').trim();
  if (!cleaned || cleaned.length < 2) return undefined;
  return cleaned;
}

function stripCareerSuffix(value: string): string {
  return value
    .replace(/\s*(careers?|jobs?|apply(?: now)?|application)\s*$/i, '')
    .replace(/\s*[-|]\s*workday\s*$/i, '')
    .trim();
}

export function parseFromDocumentTitle(title: string): { company?: string; role?: string } {
  const text = cleanLabel(title);
  if (!text) return {};

  let match = text.match(/^apply for\s+(.+?)\s+(?:at|@|\|)\s+(.+?)(?:\s*[-|]|$)/i);
  if (match) {
    return { role: cleanLabel(match[1]), company: cleanLabel(stripCareerSuffix(match[2])) };
  }

  match = text.match(/^(.+?)\s+at\s+(.+?)(?:\s*[-|]|$)/i);
  if (match) {
    return { role: cleanLabel(match[1]), company: cleanLabel(stripCareerSuffix(match[2])) };
  }

  const parts = text.split(/\s[-–|]\s/).map((part) => part.trim()).filter(Boolean);
  if (parts.length >= 2) {
    const roleLike = /engineer|manager|designer|director|analyst|developer|lead|specialist|architect|scientist/i;
    const first = parts[0];
    const last = parts[parts.length - 1];

    if (/careers?|jobs?|apply|workday|greenhouse|ashby|lever/i.test(last) && parts.length >= 2) {
      return {
        role: cleanLabel(first),
        company: cleanLabel(stripCareerSuffix(parts[parts.length - 2]))
      };
    }

    if (roleLike.test(first)) {
      return { role: cleanLabel(first), company: cleanLabel(stripCareerSuffix(last)) };
    }
    if (roleLike.test(last)) {
      return { role: cleanLabel(last), company: cleanLabel(stripCareerSuffix(first)) };
    }

    return { role: cleanLabel(first), company: cleanLabel(stripCareerSuffix(last)) };
  }

  return { role: text };
}

export function parseFromMeta(doc: Document): { company?: string; role?: string } {
  const readMeta = (selector: string) =>
    cleanLabel(doc.querySelector(selector)?.getAttribute('content'));

  return {
    company:
      readMeta('meta[property="og:site_name"]') ||
      readMeta('meta[name="application-name"]') ||
      readMeta('meta[name="twitter:site"]')?.replace(/^@/, ''),
    role: readMeta('meta[property="og:title"]') || readMeta('meta[name="twitter:title"]')
  };
}

function walkJsonLd(node: unknown): { company?: string; role?: string; location?: string } | null {
  if (!node) return null;

  if (Array.isArray(node)) {
    for (const item of node) {
      const found = walkJsonLd(item);
      if (found) return found;
    }
    return null;
  }

  if (typeof node !== 'object') return null;
  const record = node as Record<string, unknown>;
  const typeValue = record['@type'];
  const types = (Array.isArray(typeValue) ? typeValue : [typeValue]).map(String);

  if (types.includes('JobPosting')) {
    const org = record.hiringOrganization as Record<string, unknown> | undefined;
    const locationNode = record.jobLocation as Record<string, unknown> | undefined;
    const address = locationNode?.address as Record<string, unknown> | undefined;
    return {
      role: cleanLabel(String(record.title || '')),
      company: cleanLabel(String(org?.name || org?.legalName || '')),
      location: cleanLabel(String(address?.addressLocality || address?.name || ''))
    };
  }

  if (record['@graph']) {
    return walkJsonLd(record['@graph']);
  }

  for (const value of Object.values(record)) {
    const found = walkJsonLd(value);
    if (found) return found;
  }

  return null;
}

export function parseFromJsonLd(doc: Document): { company?: string; role?: string; location?: string } {
  for (const script of doc.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      const parsed = JSON.parse(script.textContent || '');
      const found = walkJsonLd(parsed);
      if (found) return found;
    } catch {
      // ignored
    }
  }
  return {};
}

function readHeaderBrand(doc: Document): string | undefined {
  const logoAlt = cleanLabel(doc.querySelector('header img[alt], nav img[alt]')?.getAttribute('alt'));
  if (logoAlt && !/logo|careers|home|apply|jobs/i.test(logoAlt)) return logoAlt;

  const brandLink = doc.querySelector('header a[href="/"], header a[href*="careers"], nav a[href="/"]');
  const brandText = cleanLabel(brandLink?.textContent);
  if (brandText && brandText.length <= 40 && !/careers|jobs|apply/i.test(brandText)) {
    return brandText;
  }

  return undefined;
}

export function parseFromDom(doc: Document): { company?: string; role?: string; location?: string } {
  const readText = (selector: string) => cleanLabel(doc.querySelector(selector)?.textContent);

  const company =
    readHeaderBrand(doc) ||
    readText('[data-automation-id="company"]') ||
    readText('[data-automation-id="companyLink"]') ||
    readText('.company-name') ||
    readText('.employer-name') ||
    readText('[class*="company-name"]') ||
    readText('[class*="CompanyName"]') ||
    readText('[data-company-name]');

  const role =
    readText('[data-automation-id="jobPostingHeader"]') ||
    readText('h1.app-title') ||
    readText('.job-title') ||
    readText('[data-automation-id="jobTitle"]') ||
    readText('h1');

  const location =
    readText('[data-automation-id="location"]') ||
    readText('.location') ||
    readText('[data-automation-id="locations"]');

  return { company, role, location };
}

export function parseRoleFromWorkdayUrl(href: string): string | null {
  const match = href.match(/\/job\/[^/]+\/([^/?#]+)/i);
  if (!match?.[1]) return null;
  const decoded = decodeURIComponent(match[1]);
  return formatCompanySlug(decoded.replace(/_/g, '-'));
}

function pickCompany(...candidates: Array<string | null | undefined>): string {
  let best = '';
  for (const candidate of candidates) {
    const cleaned = cleanLabel(candidate);
    if (!cleaned) continue;
    if (isBetterCompanyName(cleaned, best)) best = cleaned;
  }
  return best;
}

function pickRole(...candidates: Array<string | null | undefined>): string {
  let best = '';
  for (const candidate of candidates) {
    const cleaned = cleanLabel(candidate);
    if (!cleaned) continue;
    if (isBetterRoleTitle(cleaned, best)) best = cleaned;
  }
  return best;
}

export function resolveJobContext(
  doc: Document = typeof document !== 'undefined' ? document : ({} as Document),
  pageUrl?: string
): JobDetails {
  const href = pageUrl || doc.location?.href || '';
  const adapterDetails = detectAdapter(doc).extractJobDetails(doc);
  const urlCompany = href ? parseCompanyFromJobUrl(href) : null;
  const urlRole = href ? parseRoleFromWorkdayUrl(href) : null;
  const meta = parseFromMeta(doc);
  const titleParts = parseFromDocumentTitle(doc.title || '');
  const jsonLd = parseFromJsonLd(doc);
  const dom = parseFromDom(doc);

  const company = pickCompany(
    adapterDetails.company,
    urlCompany,
    dom.company,
    jsonLd.company,
    meta.company,
    titleParts.company
  );

  const role = pickRole(adapterDetails.role, dom.role, jsonLd.role, urlRole, titleParts.role, meta.role);

  const location =
    cleanLabel(adapterDetails.location) ||
    cleanLabel(dom.location) ||
    cleanLabel(jsonLd.location) ||
    'Remote / Unspecified';

  const platform =
    adapterDetails.platform && adapterDetails.platform !== 'Generic'
      ? adapterDetails.platform
      : href.includes('greenhouse.io')
        ? 'Greenhouse'
        : href.includes('myworkday')
          ? 'Workday'
          : href.includes('lever.co')
            ? 'Lever'
            : href.includes('ashbyhq.com')
              ? 'Ashby'
              : adapterDetails.platform || 'Generic';

  return {
    company: company || urlCompany || 'Unknown Company',
    role: role || 'Unknown Role',
    location,
    description: adapterDetails.description || '',
    platform
  };
}

export function enrichJobDetails(base: JobDetails, pageUrl?: string, pageTitle?: string): JobDetails {
  const titleParts = pageTitle ? parseFromDocumentTitle(pageTitle) : {};
  const urlCompany = pageUrl ? parseCompanyFromJobUrl(pageUrl) : null;
  const urlRole = pageUrl ? parseRoleFromWorkdayUrl(pageUrl) : null;

  return {
    ...base,
    company: pickCompany(base.company, urlCompany, titleParts.company) || urlCompany || base.company,
    role: pickRole(base.role, urlRole, titleParts.role) || base.role,
    location: base.location || 'Remote / Unspecified',
    platform:
      base.platform && base.platform !== 'Generic'
        ? base.platform
        : pageUrl?.includes('greenhouse.io')
          ? 'Greenhouse'
          : pageUrl?.includes('myworkday')
            ? 'Workday'
            : base.platform
  };
}

export function isKnownCompany(value?: string): boolean {
  return Boolean(value && !BAD_COMPANIES.has(value.trim().toLowerCase()));
}

export function isKnownRole(value?: string): boolean {
  return Boolean(value && !BAD_ROLES.has(value.trim().toLowerCase()));
}
