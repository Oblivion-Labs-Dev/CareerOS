/** Huntr-inspired extraction of salary, employment type, and work mode from page text. */

export type EmploymentType = 'full_time' | 'part_time' | 'contract' | 'internship' | 'temporary' | 'unknown';
export type WorkMode = 'remote' | 'hybrid' | 'onsite' | 'unknown';

export interface JobPageEnrichment {
  salary?: string;
  employmentType: EmploymentType;
  workMode: WorkMode;
}

const SALARY_PATTERNS = [
  /\$[\d,]+(?:\.\d{2})?\s*[-–—to]+\s*\$?[\d,]+(?:\.\d{2})?/i,
  /[\£€]\s*[\d,]+(?:\.\d{2})?\s*[-–—to]+\s*[\£€]?\s*[\d,]+(?:\.\d{2})?/i,
  /[\d,]+\s*(usd|eur|gbp|cad|aud)\s*[-–—to]+/i,
  /\b(salary|compensation|pay|base)\s*:?\s*\$?\s*[\d,]+(?:k|K)?/i,
  /\b(annual|yearly)\s*(salary|compensation|pay)\s*:?\s*\$?\s*[\d,]+(?:k|K)?/i,
  /\$[\d,]+(?:k|K)\s*(?:\/\s*(?:yr|year|hour|hr))?/i
];

const EMPLOYMENT_PATTERNS: Array<{ type: EmploymentType; pattern: RegExp }> = [
  { type: 'internship', pattern: /\b(internship|co-?op|apprentice(ship)?)\b/i },
  { type: 'contract', pattern: /\bcontract(or|ing)?\b/i },
  { type: 'temporary', pattern: /\b(temporary|freelance)\b/i },
  { type: 'part_time', pattern: /\b(part[\s-]?time|pt)\b/i },
  { type: 'full_time', pattern: /\b(full[\s-]?time|ft)\b/i }
];

const WORK_MODE_PATTERNS: Array<{ mode: WorkMode; pattern: RegExp }> = [
  { mode: 'remote', pattern: /\bremote\b/i },
  { mode: 'hybrid', pattern: /\bhybrid\b/i },
  { mode: 'onsite', pattern: /\b(on[\s-]?site|in[\s-]?office|work[\s-]?from[\s-]?office)\b/i }
];

const EMPLOYMENT_LABELS: Record<EmploymentType, string> = {
  full_time: 'Full-time',
  part_time: 'Part-time',
  contract: 'Contract',
  internship: 'Internship',
  temporary: 'Temporary',
  unknown: ''
};

const WORK_MODE_LABELS: Record<WorkMode, string> = {
  remote: 'Remote',
  hybrid: 'Hybrid',
  onsite: 'On-site',
  unknown: ''
};

export function employmentTypeLabel(type: EmploymentType): string {
  return EMPLOYMENT_LABELS[type] || '';
}

export function workModeLabel(mode: WorkMode): string {
  return WORK_MODE_LABELS[mode] || '';
}

export function employmentTypeColor(type: EmploymentType): string {
  switch (type) {
    case 'full_time':
      return '#4ade80';
    case 'part_time':
      return '#22d3ee';
    case 'contract':
      return '#f472b6';
    case 'internship':
      return '#a78bfa';
    default:
      return '#94a3b8';
  }
}

function readPageText(doc: Document, maxChars = 16000): string {
  const main =
    doc.querySelector('main, [role="main"], .job-description, .job-post, article')?.textContent ||
    doc.body?.textContent ||
    '';
  return main.replace(/\s+/g, ' ').trim().slice(0, maxChars);
}

export function enrichJobPage(doc: Document = document): JobPageEnrichment {
  const text = readPageText(doc);

  let salary: string | undefined;
  for (const pattern of SALARY_PATTERNS) {
    const match = text.match(pattern);
    if (match?.[0]) {
      salary = match[0].trim().slice(0, 80);
      break;
    }
  }

  let employmentType: EmploymentType = 'unknown';
  for (const { type, pattern } of EMPLOYMENT_PATTERNS) {
    if (pattern.test(text)) {
      employmentType = type;
      break;
    }
  }

  let workMode: WorkMode = 'unknown';
  for (const { mode, pattern } of WORK_MODE_PATTERNS) {
    if (pattern.test(text)) {
      workMode = mode;
      break;
    }
  }

  if (workMode === 'unknown') {
    const locationText =
      doc.querySelector('[data-automation-id="location"], .location, [class*="location"]')?.textContent || '';
    if (/\bremote\b/i.test(locationText)) workMode = 'remote';
    else if (/\bhybrid\b/i.test(locationText)) workMode = 'hybrid';
  }

  return { salary, employmentType, workMode };
}
