import { resolveJobContext } from './jobContextResolver';
import { enrichJobPage, JobPageEnrichment } from './jobPageEnrichment';
import { matchJobSite, parseFromJobSite } from './jobSiteSelectors';
import { checkH1bSponsorship, H1bSponsorshipResult } from './h1bSponsorshipCheck';

const JOB_HOST_PATTERN =
  /greenhouse\.io|lever\.co|ashbyhq\.com|workday|smartrecruiters|taleo|icims|rippling|linkedin\.com\/jobs|indeed\.com|jobvite|workable|bamboohr|recruitee|jazz\.co|paylocity|successfactors|oraclecloud|ultipro|myworkdayjobs|glassdoor\.com|ziprecruiter\.com|monster\.com|\/careers\//i;

const APPLICATION_PATH_PATTERN =
  /\/(apply|application|postings?|jobs?|careers|requisition|candidate)|(?:[?&](?:gh_jid|jobid|jobId|posting|requisitionId)=)/i;

const LISTING_PATH_PATTERN =
  /\/(jobs?|view|posting|postings|careers|requisition|job-detail|jobdetails)|(?:[?&](?:gh_jid|jobid|jobId|jk|vjk)=)/i;

const CONFIRMATION_URL_PATTERN =
  /(thank.?you|thanks for applying|application (?:has been )?(?:received|submitted|sent|complete)|successfully applied|submission (?:received|complete|confirmed)|confirmation|you.?ve applied|application submitted)/i;

export function isJobApplicationUrl(href: string): boolean {
  if (/autofillWithResume/i.test(href)) return true;

  const lower = href.toLowerCase();
  return JOB_HOST_PATTERN.test(lower) && APPLICATION_PATH_PATTERN.test(lower);
}

/** Job posting / listing pages (Huntr-style save target), excluding pure apply forms when possible. */
export function isJobListingUrl(href: string): boolean {
  const lower = href.toLowerCase();
  if (!JOB_HOST_PATTERN.test(lower)) return false;
  if (!LISTING_PATH_PATTERN.test(lower)) return false;
  if (/\/apply(?:\/|$|\?)/i.test(lower) && !/\/jobs?\//i.test(lower)) return false;
  return true;
}

export function isJobSearchPage(href: string): boolean {
  return isJobApplicationUrl(href) || isJobListingUrl(href) || isJobBoardUrl(href) || isSubmissionConfirmationUrl(href);
}

export function isSubmissionConfirmationUrl(href: string): boolean {
  if (CONFIRMATION_URL_PATTERN.test(href)) return true;
  if (/greenhouse\.io\/.*\/confirmation/i.test(href)) return true;
  if (/myworkdaysite\.com|myworkdayjobs\.com/i.test(href) && /(confirmation|success|complete)/i.test(href)) {
    return true;
  }
  return false;
}

export function isWorkdaySubmissionSuccess(doc: Document = document): boolean {
  if (!/myworkdaysite\.com|myworkdayjobs\.com/i.test(doc.location.href)) return false;
  const text = doc.body?.innerText?.slice(0, 8000) || '';
  if (/thank you for applying|application (?:has been )?submitted|successfully applied/i.test(text)) {
    return true;
  }
  return Boolean(
    doc.querySelector(
      '[data-automation-id="applicationConfirmation"], [data-automation-id="successMessage"], [data-automation-id="confirmationPage"]'
    )
  );
}

/** Greenhouse often shows a thank-you state without changing the URL (SPA in-page confirmation). */
export function isGreenhouseSubmissionSuccess(doc: Document = document): boolean {
  const href = doc.location.href;
  if (!/greenhouse\.io/i.test(href)) return false;
  if (isSubmissionConfirmationUrl(href)) return true;

  if (
    doc.querySelector(
      '[data-qa="application-success"], [data-qa="confirmation"], #application_confirmation, .application-confirmation, [class*="ApplicationConfirmation"]'
    )
  ) {
    return true;
  }

  const text = doc.body?.innerText?.slice(0, 12000) || '';
  const hasThankYou =
    /thank you for applying|thanks for applying|application (?:has been )?(?:received|submitted)|your application has been submitted|successfully applied/i.test(
      text
    );
  if (!hasThankYou) return false;

  if (/\/jobs\/\d+\/confirmation/i.test(href)) return true;

  // Same-URL confirmation: thank-you text and most form fields are gone.
  if (/\/jobs\/\d+/i.test(href)) {
    const fillable = doc.querySelectorAll(
      'input:not([type="hidden"]):not([type="submit"]):not([type="button"]), select, textarea'
    ).length;
    return fillable < 10;
  }

  return false;
}

export function isSubmissionSuccessPage(doc: Document = document): boolean {
  return (
    isSubmissionConfirmationUrl(doc.location.href) ||
    isWorkdaySubmissionSuccess(doc) ||
    isGreenhouseSubmissionSuccess(doc)
  );
}

export function isJobBoardUrl(href: string): boolean {
  return Boolean(matchJobSite(href));
}

export interface ExtractedJobContext {
  company: string;
  role: string;
  location: string;
  platform: string;
  description?: string;
  enrichment: JobPageEnrichment;
  h1b: H1bSponsorshipResult;
}

export function extractJobContext(doc: Document = document): ExtractedJobContext {
  const siteParsed = parseFromJobSite(doc);
  const resolved = resolveJobContext(doc);
  let enrichment = enrichJobPage(doc);

  if (siteParsed?.salary && !enrichment.salary) {
    enrichment = { ...enrichment, salary: siteParsed.salary };
  }

  const description = siteParsed?.description || resolved.description || '';
  const pageText = doc.body?.innerText?.slice(0, 16000) || '';
  const h1b = checkH1bSponsorship(`${description} ${pageText}`);

  return {
    company: siteParsed?.company && siteParsed.company !== 'Unknown Company' ? siteParsed.company : resolved.company,
    role: siteParsed?.role && siteParsed.role !== 'Unknown Role' ? siteParsed.role : resolved.role,
    location: resolved.location,
    platform: siteParsed?.siteLabel || resolved.platform,
    description,
    enrichment,
    h1b
  };
}
