/** Jobscan-style per-board DOM selectors for reliable job parsing and button injection. */

export interface JobSiteDomSelectors {
  URL?: string | null;
  salary?: string | null;
  job_title?: string | null;
  company_name?: string | null;
  job_description?: string | null;
  target_for_job_tracker?: string | null;
}

export interface JobSiteConfig {
  id: number;
  label: string;
  url_pattern: string;
  style: 'indeed' | 'linkedin' | 'glassdoor' | 'handshake';
  dom_selectors: JobSiteDomSelectors;
}

/** Adapted from Jobscan job-sites.json (Indeed, LinkedIn, Glassdoor, Handshake). */
export const JOB_SITE_CONFIGS: JobSiteConfig[] = [
  {
    id: 1,
    label: 'Indeed',
    url_pattern: 'indeed.com',
    style: 'indeed',
    dom_selectors: {
      URL: null,
      salary: '#salaryInfoAndJobType > span',
      job_title: '.jobsearch-JobInfoHeader-title',
      company_name: '[data-testid="inlineHeader-companyName"] span a',
      job_description: 'div#jobDescriptionText',
      target_for_job_tracker: '#jobsearch-ViewJobButtons-container'
    }
  },
  {
    id: 3,
    label: 'LinkedIn',
    url_pattern: 'linkedin.com',
    style: 'linkedin',
    dom_selectors: {
      URL: null,
      salary: null,
      job_title: '.job-details-jobs-unified-top-card__job-title, .jobs-unified-top-card__job-title',
      company_name: '.job-details-jobs-unified-top-card__company-name > a, .jobs-unified-top-card__company-name a',
      job_description: '#job-details.jobs-box__html-content, .jobs-description__content',
      target_for_job_tracker: 'button.jobs-save-button.artdeco-button.artdeco-button--3, .jobs-s-apply button'
    }
  },
  {
    id: 4,
    label: 'Glassdoor',
    url_pattern: 'glassdoor.com',
    style: 'glassdoor',
    dom_selectors: {
      URL: '[data-test="job-link"]',
      salary: 'span[data-test="detailSalary"]',
      job_title: '[data-test="job-details-header"] h1',
      company_name: '[data-test="job-details-header"] div a div h4',
      job_description: '.JobDetails_jobDescription__uW_fK, [data-test="jobDescriptionContent"]',
      target_for_job_tracker: '[data-test="location"], [data-test="applyButton"]'
    }
  },
  {
    id: 6,
    label: 'Handshake',
    url_pattern: 'joinhandshake.com',
    style: 'handshake',
    dom_selectors: {
      URL: '#skip-to-content a:has(h1)',
      salary: '#skip-to-content [data-hook="right-content"] div:has(> h4:first-child) ~ div svg + div',
      job_title: '#skip-to-content h1',
      company_name: '#skip-to-content [data-hook="right-content"] a div',
      job_description: '#skip-to-content [data-hook="right-content"] div:not(:first-child):has(div > h4:first-child) + div',
      target_for_job_tracker: 'button[aria-label^="Apply"]'
    }
  }
];

export function matchJobSite(href: string): JobSiteConfig | undefined {
  const lower = href.toLowerCase();
  return JOB_SITE_CONFIGS.find((site) => lower.includes(site.url_pattern));
}

function readSelectorText(doc: Document, selector?: string | null): string {
  if (!selector) return '';
  try {
    const element = doc.querySelector(selector);
    if (!element) return '';
    if (element instanceof HTMLAnchorElement && element.href) return element.innerText.trim() || element.href;
    return (element.textContent || '').replace(/\s+/g, ' ').trim();
  } catch {
    return '';
  }
}

function readSelectorUrl(doc: Document, selector?: string | null, fallback?: string): string {
  if (!selector) return fallback || doc.location.href;
  try {
    const element = doc.querySelector(selector);
    if (element instanceof HTMLAnchorElement && element.href) return element.href;
  } catch {
    // ignored
  }
  return fallback || doc.location.href;
}

export interface SiteParsedJob {
  company: string;
  role: string;
  salary?: string;
  description: string;
  url: string;
  siteLabel: string;
  siteStyle: JobSiteConfig['style'];
  injectionTarget?: string;
}

export function parseFromJobSite(doc: Document = document): SiteParsedJob | null {
  const site = matchJobSite(doc.location.href);
  if (!site) return null;

  const { dom_selectors: sel } = site;
  const company = readSelectorText(doc, sel.company_name);
  const role = readSelectorText(doc, sel.job_title);
  const salary = readSelectorText(doc, sel.salary);
  const description = readSelectorText(doc, sel.job_description);
  const url = readSelectorUrl(doc, sel.URL, doc.location.href);

  if (!company && !role && !description) return null;

  return {
    company: company || 'Unknown Company',
    role: role || 'Unknown Role',
    salary: salary || undefined,
    description,
    url,
    siteLabel: site.label,
    siteStyle: site.style,
    injectionTarget: sel.target_for_job_tracker || undefined
  };
}

export function getInjectionTargetSelector(doc: Document = document): string | null {
  const site = matchJobSite(doc.location.href);
  return site?.dom_selectors.target_for_job_tracker || null;
}
