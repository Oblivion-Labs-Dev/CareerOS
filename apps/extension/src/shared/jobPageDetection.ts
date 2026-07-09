import { resolveJobContext } from './jobContextResolver';

const JOB_HOST_PATTERN =
  /greenhouse\.io|lever\.co|ashbyhq\.com|workday|smartrecruiters|taleo|icims|rippling|linkedin\.com\/jobs|indeed\.com|jobvite|workable|bamboohr|recruitee|jazz\.co|paylocity|successfactors|oraclecloud|ultipro|myworkdayjobs|\/careers\//i;

const APPLICATION_PATH_PATTERN =
  /\/(apply|application|postings?|jobs?|careers|requisition|candidate)|(?:[?&](?:gh_jid|jobid|jobId|posting|requisitionId)=)/i;

const CONFIRMATION_URL_PATTERN =
  /(thank.?you|thanks for applying|application (?:has been )?(?:received|submitted|sent|complete)|successfully applied|submission (?:received|complete|confirmed)|confirmation|you.?ve applied|application submitted)/i;

export function isJobApplicationUrl(href: string): boolean {
  if (/autofillWithResume/i.test(href)) return true;

  const lower = href.toLowerCase();
  return JOB_HOST_PATTERN.test(lower) && APPLICATION_PATH_PATTERN.test(lower);
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

export function extractJobContext(doc: Document = document): {
  company: string;
  role: string;
  location: string;
  platform: string;
} {
  const resolved = resolveJobContext(doc);
  return {
    company: resolved.company,
    role: resolved.role,
    location: resolved.location,
    platform: resolved.platform
  };
}
