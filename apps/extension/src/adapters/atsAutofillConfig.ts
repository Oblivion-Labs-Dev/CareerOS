/** Per-ATS autofill steps inspired by copilot-style remote configs (URL + selector pipelines). */

export type AtsFillMethod =
  | 'click'
  | 'wait'
  | 'text'
  | 'select'
  | 'uploadResume'
  | 'uploadCoverLetter';

export interface AtsFieldStep {
  /** Canonical profile key, or flow control: begin | wait | resume | coverLetter */
  field: string;
  selector: string;
  method: AtsFillMethod;
  waitMs?: number;
  optional?: boolean;
}

export interface AtsAutofillConfig {
  id: string;
  name: string;
  detect: (doc: Document) => boolean;
  preSteps?: AtsFieldStep[];
  fieldSteps: AtsFieldStep[];
}

const GREENHOUSE: AtsAutofillConfig = {
  id: 'greenhouse',
  name: 'Greenhouse',
  detect: (doc) =>
    /greenhouse\.io/i.test(doc.location.hostname) ||
    doc.location.search.includes('gh_jid') ||
    Boolean(doc.querySelector('#gh_jid, meta[content*="greenhouse.io"]')),
  preSteps: [
    {
      field: 'begin',
      selector: '#apply_button, a#apply_button, [data-testid="apply-button"], a[href*="#app"]',
      method: 'click',
      optional: true,
    },
    {
      field: 'wait',
      selector:
        'input[name="job_application[first_name]"], input[name*="first_name"], #first_name, input[type="file"]',
      method: 'wait',
      waitMs: 8000,
      optional: true,
    },
  ],
  fieldSteps: [
    { field: 'resume', selector: 'input[type="file"]', method: 'uploadResume', optional: true },
    {
      field: 'firstName',
      selector: 'input[name="job_application[first_name]"], input[name*="first_name"], #first_name',
      method: 'text',
    },
    {
      field: 'lastName',
      selector: 'input[name="job_application[last_name]"], input[name*="last_name"], #last_name',
      method: 'text',
    },
    {
      field: 'email',
      selector: 'input[name="job_application[email]"], input[type="email"], input[name*="email"]',
      method: 'text',
    },
    {
      field: 'phone',
      selector: 'input[name="job_application[phone]"], input[type="tel"], input[name*="phone"]',
      method: 'text',
    },
    {
      field: 'linkedin',
      selector: 'input[name*="linkedin"], input[id*="linkedin"]',
      method: 'text',
      optional: true,
    },
    {
      field: 'coverLetter',
      selector: 'input[type="file"][name*="cover"], textarea[name*="cover"]',
      method: 'uploadCoverLetter',
      optional: true,
    },
  ],
};

const LEVER: AtsAutofillConfig = {
  id: 'lever',
  name: 'Lever',
  detect: (doc) => /jobs\.(eu\.)?lever\.co/i.test(doc.location.hostname),
  preSteps: [
    {
      field: 'begin',
      selector: '.postings-btn-wrapper a.postings-btn, a.postings-btn.template-btn-apply, a[href*="/apply"]',
      method: 'click',
      optional: true,
    },
    {
      field: 'wait',
      selector: '#resume-upload-input, .application-form input, input[type="file"]',
      method: 'wait',
      waitMs: 6000,
      optional: true,
    },
  ],
  fieldSteps: [
    { field: 'resume', selector: '#resume-upload-input, input[type="file"]', method: 'uploadResume', optional: true },
    { field: 'fullName', selector: 'input[name="name"], input[data-qa="name-input"]', method: 'text' },
    { field: 'email', selector: 'input[name="email"], input[type="email"]', method: 'text' },
    { field: 'phone', selector: 'input[name="phone"], input[type="tel"]', method: 'text' },
    {
      field: 'linkedin',
      selector: 'input[name*="urls[LinkedIn]"], input[name*="linkedin"]',
      method: 'text',
      optional: true,
    },
    {
      field: 'coverLetter',
      selector: 'input[type="file"][name*="cover"], textarea[placeholder*="cover" i]',
      method: 'uploadCoverLetter',
      optional: true,
    },
  ],
};

const ASHBY: AtsAutofillConfig = {
  id: 'ashby',
  name: 'Ashby',
  detect: (doc) => /jobs\.ashbyhq\.com/i.test(doc.location.hostname),
  preSteps: [
    {
      field: 'begin',
      selector: 'a[href*="/application"], button[type="submit"]:not([disabled])',
      method: 'click',
      optional: true,
    },
    {
      field: 'wait',
      selector: '.fieldEntry input, .fieldEntry textarea, .fieldEntry input[type="file"]',
      method: 'wait',
      waitMs: 6000,
      optional: true,
    },
  ],
  fieldSteps: [
    {
      field: 'resume',
      selector: '.fieldEntry input[type="file"][accept*="pdf"], input[type="file"]',
      method: 'uploadResume',
      optional: true,
    },
    {
      field: 'firstName',
      selector: 'input[name*="first"], input[autocomplete="given-name"]',
      method: 'text',
    },
    {
      field: 'lastName',
      selector: 'input[name*="last"], input[autocomplete="family-name"]',
      method: 'text',
    },
    { field: 'email', selector: 'input[type="email"], input[name*="email"]', method: 'text' },
    { field: 'phone', selector: 'input[type="tel"], input[name*="phone"]', method: 'text' },
    {
      field: 'linkedin',
      selector: 'input[name*="linkedin"], input[placeholder*="linkedin" i]',
      method: 'text',
      optional: true,
    },
  ],
};

const WORKDAY: AtsAutofillConfig = {
  id: 'workday',
  name: 'Workday',
  detect: (doc) =>
    /myworkdayjobs\.com|myworkdaysite\.com/i.test(doc.location.hostname) ||
    Boolean(doc.querySelector('[data-automation-id="workdayLogo"], [data-automation-id="jobPostingHeader"]')),
  preSteps: [
    {
      field: 'begin',
      selector:
        '[data-automation-id="jobPostingApplyButton"], [data-automation-id="applyButton"], button[data-automation-id*="Apply"]',
      method: 'click',
      optional: true,
    },
    {
      field: 'wait',
      selector: '[data-automation-id="firstName"], [data-automation-id="legalNameSection_firstName"]',
      method: 'wait',
      waitMs: 10000,
      optional: true,
    },
  ],
  fieldSteps: [
    {
      field: 'resume',
      selector: '[data-automation-id="file-upload-input-ref"], input[type="file"]',
      method: 'uploadResume',
      optional: true,
    },
    {
      field: 'firstName',
      selector: '[data-automation-id="firstName"], [data-automation-id="legalNameSection_firstName"]',
      method: 'text',
    },
    {
      field: 'lastName',
      selector: '[data-automation-id="lastName"], [data-automation-id="legalNameSection_lastName"]',
      method: 'text',
    },
    {
      field: 'email',
      selector: '[data-automation-id="email"], input[type="email"]',
      method: 'text',
    },
    {
      field: 'phone',
      selector: '[data-automation-id="phone"], [data-automation-id="phone-number"]',
      method: 'text',
    },
    {
      field: 'linkedin',
      selector: '[data-automation-id*="linkedin" i], input[aria-label*="LinkedIn" i]',
      method: 'text',
      optional: true,
    },
  ],
};

const SMARTRECRUITERS: AtsAutofillConfig = {
  id: 'smartrecruiters',
  name: 'SmartRecruiters',
  detect: (doc) =>
    /smartrecruiters\.com/i.test(doc.location.hostname) ||
    Boolean(doc.querySelector('[data-test="apply-button"], .application-form')),
  preSteps: [
    {
      field: 'begin',
      selector: '[data-test="apply-button"], a[href*="/apply"], button[data-test="apply"]',
      method: 'click',
      optional: true,
    },
    {
      field: 'wait',
      selector: 'input[type="email"], input[name*="email"], input[type="file"]',
      method: 'wait',
      waitMs: 8000,
      optional: true,
    },
  ],
  fieldSteps: [
    { field: 'resume', selector: 'input[type="file"]', method: 'uploadResume', optional: true },
    { field: 'firstName', selector: 'input[name*="firstName"], input[name*="first_name"]', method: 'text' },
    { field: 'lastName', selector: 'input[name*="lastName"], input[name*="last_name"]', method: 'text' },
    { field: 'email', selector: 'input[type="email"], input[name*="email"]', method: 'text' },
    { field: 'phone', selector: 'input[type="tel"], input[name*="phone"]', method: 'text' },
  ],
};

const WORKABLE: AtsAutofillConfig = {
  id: 'workable',
  name: 'Workable',
  detect: (doc) =>
    /apply\.workable\.com|jobs\.workable\.com/i.test(doc.location.hostname),
  preSteps: [
    {
      field: 'begin',
      selector: 'a[href*="/apply"], button[type="submit"]',
      method: 'click',
      optional: true,
    },
    {
      field: 'wait',
      selector: 'input[type="email"], input[type="file"], .application-form input',
      method: 'wait',
      waitMs: 7000,
      optional: true,
    },
  ],
  fieldSteps: [
    { field: 'resume', selector: 'input[type="file"]', method: 'uploadResume', optional: true },
    { field: 'fullName', selector: 'input[name="name"], input[name*="fullname"]', method: 'text' },
    { field: 'email', selector: 'input[type="email"], input[name="email"]', method: 'text' },
    { field: 'phone', selector: 'input[type="tel"], input[name="phone"]', method: 'text' },
  ],
};

const ICIMS: AtsAutofillConfig = {
  id: 'icims',
  name: 'iCIMS',
  detect: (doc) => /icims\.com|jibeapply\.com/i.test(doc.location.hostname),
  preSteps: [
    { field: 'wait', selector: '#icims_f_firstName, input[autocomplete="given-name"], input[type="file"]', method: 'wait', waitMs: 8000, optional: true },
  ],
  fieldSteps: [
    { field: 'resume', selector: 'input[type="file"][name*="resume" i], #PortalProfileFields\\.Resume_Content input[type="file"]', method: 'uploadResume', optional: true },
    { field: 'firstName', selector: '#icims_f_firstName, input[autocomplete="given-name"]', method: 'text' },
    { field: 'lastName', selector: '#icims_f_lastName, input[autocomplete="family-name"]', method: 'text' },
    { field: 'email', selector: '#icims_f_email, input[autocomplete="email"], input[type="email"]', method: 'text' },
    { field: 'phone', selector: '#icims_f_mobilePhone, input[autocomplete="tel-national"], input[type="tel"]', method: 'text' },
  ],
};

const INDEED_APPLY: AtsAutofillConfig = {
  id: 'indeed',
  name: 'Indeed Apply',
  detect: (doc) => /smartapply\.indeed\.com/i.test(doc.location.hostname),
  preSteps: [
    { field: 'wait', selector: 'input[name="names-first-name"], input[type="file"]', method: 'wait', waitMs: 8000, optional: true },
  ],
  fieldSteps: [
    { field: 'resume', selector: 'input[data-testid*="resume"][type="file"], input[type="file"]', method: 'uploadResume', optional: true },
    { field: 'firstName', selector: 'input[name="names-first-name"]', method: 'text' },
    { field: 'lastName', selector: 'input[name="names-last-name"]', method: 'text' },
    { field: 'email', selector: 'input[type="email"], input[name*="email"]', method: 'text' },
    { field: 'phone', selector: 'input[type="tel"], input[name*="phone"]', method: 'text' },
  ],
};

const JOBVITE: AtsAutofillConfig = {
  id: 'jobvite',
  name: 'Jobvite',
  detect: (doc) => /jobs\.jobvite\.com/i.test(doc.location.hostname),
  preSteps: [
    { field: 'begin', selector: 'a[href*="/apply"], .jv-button-apply', method: 'click', optional: true },
    { field: 'wait', selector: 'input[type="email"], input[type="file"]', method: 'wait', waitMs: 7000, optional: true },
  ],
  fieldSteps: [
    { field: 'resume', selector: 'input[type="file"]', method: 'uploadResume', optional: true },
    { field: 'firstName', selector: 'input[name*="first"], input[id*="first"]', method: 'text' },
    { field: 'lastName', selector: 'input[name*="last"], input[id*="last"]', method: 'text' },
    { field: 'email', selector: 'input[type="email"]', method: 'text' },
    { field: 'phone', selector: 'input[type="tel"]', method: 'text' },
  ],
};

const BAMBOOHR: AtsAutofillConfig = {
  id: 'bamboohr',
  name: 'BambooHR',
  detect: (doc) => /bamboohr\.com/i.test(doc.location.hostname) && /\/careers/i.test(doc.location.pathname),
  preSteps: [
    { field: 'begin', selector: 'a[href*="/apply"], button[data-fabric-component="Button"]', method: 'click', optional: true },
    { field: 'wait', selector: 'input[type="email"], input[type="file"]', method: 'wait', waitMs: 7000, optional: true },
  ],
  fieldSteps: [
    { field: 'resume', selector: 'input[type="file"]', method: 'uploadResume', optional: true },
    { field: 'firstName', selector: 'input[name*="first"], input[id*="first"]', method: 'text' },
    { field: 'lastName', selector: 'input[name*="last"], input[id*="last"]', method: 'text' },
    { field: 'email', selector: 'input[type="email"]', method: 'text' },
    { field: 'phone', selector: 'input[type="tel"]', method: 'text' },
  ],
};

const JAZZHR: AtsAutofillConfig = {
  id: 'jazzhr',
  name: 'JazzHR',
  detect: (doc) => /applytojob\.com/i.test(doc.location.hostname),
  fieldSteps: [
    { field: 'resume', selector: 'input[type="file"]', method: 'uploadResume', optional: true },
    { field: 'fullName', selector: 'input[name="name"], input[name*="applicant_name"]', method: 'text' },
    { field: 'email', selector: 'input[type="email"]', method: 'text' },
    { field: 'phone', selector: 'input[type="tel"], input[name*="phone"]', method: 'text' },
  ],
};

const ORACLE_CLOUD: AtsAutofillConfig = {
  id: 'oraclecloud',
  name: 'Oracle Cloud',
  detect: (doc) => /oraclecloud\.com/i.test(doc.location.hostname) && /\/apply\//i.test(doc.location.pathname),
  preSteps: [
    { field: 'wait', selector: 'input[type="email"], input[type="file"]', method: 'wait', waitMs: 10000, optional: true },
  ],
  fieldSteps: [
    { field: 'resume', selector: 'input[type="file"]', method: 'uploadResume', optional: true },
    { field: 'firstName', selector: 'input[name*="first"], input[id*="first"]', method: 'text' },
    { field: 'lastName', selector: 'input[name*="last"], input[id*="last"]', method: 'text' },
    { field: 'email', selector: 'input[type="email"]', method: 'text' },
    { field: 'phone', selector: 'input[type="tel"]', method: 'text' },
  ],
};

const RIPPLING: AtsAutofillConfig = {
  id: 'rippling',
  name: 'Rippling',
  detect: (doc) => /ats\.rippling\.com/i.test(doc.location.hostname),
  fieldSteps: [
    { field: 'resume', selector: 'input[type="file"]', method: 'uploadResume', optional: true },
    { field: 'firstName', selector: 'input[name*="first"]', method: 'text' },
    { field: 'lastName', selector: 'input[name*="last"]', method: 'text' },
    { field: 'email', selector: 'input[type="email"]', method: 'text' },
    { field: 'phone', selector: 'input[type="tel"]', method: 'text' },
  ],
};

const RECRUITEE: AtsAutofillConfig = {
  id: 'recruitee',
  name: 'Recruitee',
  detect: (doc) => /recruitee\.com/i.test(doc.location.hostname) && /\/o\//i.test(doc.location.pathname),
  fieldSteps: [
    { field: 'resume', selector: 'input[type="file"]', method: 'uploadResume', optional: true },
    { field: 'fullName', selector: 'input[name="name"]', method: 'text' },
    { field: 'email', selector: 'input[type="email"]', method: 'text' },
    { field: 'phone', selector: 'input[type="tel"]', method: 'text' },
  ],
};

export const ATS_AUTOFILL_CONFIGS: AtsAutofillConfig[] = [
  GREENHOUSE,
  LEVER,
  ASHBY,
  WORKDAY,
  SMARTRECRUITERS,
  WORKABLE,
  ICIMS,
  INDEED_APPLY,
  JOBVITE,
  BAMBOOHR,
  JAZZHR,
  ORACLE_CLOUD,
  RIPPLING,
  RECRUITEE,
];

export function detectAtsAutofillConfig(doc: Document = document): AtsAutofillConfig | null {
  for (const config of ATS_AUTOFILL_CONFIGS) {
    if (config.detect(doc)) return config;
  }
  return null;
}
