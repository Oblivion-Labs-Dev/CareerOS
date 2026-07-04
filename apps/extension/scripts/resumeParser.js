import { PDFParse } from 'pdf-parse';

const EMAIL_RE = /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/;
const PHONE_RE = /(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b/;
const URL_RE = /https?:\/\/[^\s|,)]+/gi;
const YEARS_RE = /(\d{1,2})\+?\s*years?\s+(?:of\s+)?experience/i;
const LOCATION_RE = /\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*),\s*([A-Z]{2})\b/;
const JOB_LINE_RE =
  /^(.+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(.+)$/;

const MONTH_MAP = {
  jan: '01',
  feb: '02',
  mar: '03',
  apr: '04',
  may: '05',
  jun: '06',
  jul: '07',
  aug: '08',
  sep: '09',
  oct: '10',
  nov: '11',
  dec: '12'
};

function normalizeResumeMonthDate(value) {
  const trimmed = value?.trim() || '';
  if (!trimmed) return '';

  const slashMatch = trimmed.match(/^(\d{1,2})\s*\/\s*(\d{4})$/);
  if (slashMatch) {
    return `${slashMatch[1].padStart(2, '0')}/${slashMatch[2]}`;
  }

  const monthYearMatch = trimmed.match(/^([A-Za-z]{3,9})[-\s]+(\d{4})$/);
  if (monthYearMatch) {
    const month = MONTH_MAP[monthYearMatch[1].slice(0, 3).toLowerCase()];
    if (month) return `${month}/${monthYearMatch[2]}`;
  }

  const yearMonthMatch = trimmed.match(/^(\d{4})[-/](\d{1,2})$/);
  if (yearMonthMatch) {
    return `${yearMonthMatch[2].padStart(2, '0')}/${yearMonthMatch[1]}`;
  }

  return trimmed;
}

function parseEmploymentDateRange(rangeText) {
  const raw = rangeText?.trim() || '';
  if (!raw) {
    return { startDate: '', endDate: '', currentlyEmployed: false };
  }

  const currentlyEmployed = /\b(present|current)\b/i.test(raw);
  const parts = raw.split(/\s+(?:to|–|-|—)\s+/i).map((part) => part.trim()).filter(Boolean);

  return {
    startDate: normalizeResumeMonthDate(parts[0] || ''),
    endDate: currentlyEmployed ? '' : normalizeResumeMonthDate(parts[1] || ''),
    currentlyEmployed
  };
}

/**
 * @param {string} text
 * @returns {Array<{ jobTitle: string; company: string; location: string; currentlyEmployed: boolean; startDate: string; endDate: string; description: string }>}
 */
export function parseWorkExperienceFromResumeText(text) {
  if (!text?.trim()) return [];

  const lines = text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);

  const experienceIdx = lines.findIndex((line) => /^experience$/i.test(line));
  if (experienceIdx < 0) return [];

  const entries = [];
  let current = null;

  for (let i = experienceIdx + 1; i < lines.length; i++) {
    const line = lines[i];
    if (/^(education|skills|projects|certifications|summary|professional summary)$/i.test(line)) {
      break;
    }

    const jobMatch = line.match(JOB_LINE_RE);
    if (jobMatch) {
      if (current) entries.push(current);
      const dates = parseEmploymentDateRange(jobMatch[4]);
      current = {
        jobTitle: jobMatch[1].trim(),
        company: jobMatch[2].trim(),
        location: jobMatch[3].trim(),
        currentlyEmployed: dates.currentlyEmployed,
        startDate: dates.startDate,
        endDate: dates.endDate,
        description: ''
      };
      continue;
    }

    if (current) {
      current.description = current.description ? `${current.description}\n${line}` : line;
    }
  }

  if (current) entries.push(current);
  return entries;
}

/**
 * @param {{ base64: string; name?: string; type?: string } | null | undefined} fileAttachment
 */
export async function extractTextFromResume(fileAttachment) {
  if (!fileAttachment?.base64) {
    throw new Error('No resume file found in documents.defaultResume');
  }

  const commaIdx = fileAttachment.base64.indexOf(',');
  const rawBase64 = commaIdx >= 0 ? fileAttachment.base64.slice(commaIdx + 1) : fileAttachment.base64;
  const buffer = Buffer.from(rawBase64, 'base64');

  const parser = new PDFParse({ data: buffer });
  try {
    const result = await parser.getText();
    return (result.text || '').replace(/\r/g, '').trim();
  } finally {
    await parser.destroy();
  }
}

/**
 * @param {string} text
 */
export function parseProfileFromResumeText(text) {
  if (!text?.trim()) return {};

  const lines = text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);

  const headerBlock = lines.slice(0, 8).join('\n');
  const parsed = {};

  const email = headerBlock.match(EMAIL_RE)?.[0];
  if (email) parsed.email = email;

  const phone = headerBlock.match(PHONE_RE)?.[0];
  if (phone) parsed.phone = normalizePhone(phone);

  const nameLine = lines.find(
    (line) =>
      line.length > 3 &&
      line.length < 60 &&
      !EMAIL_RE.test(line) &&
      !PHONE_RE.test(line) &&
      !/professional summary|experience|education|skills/i.test(line) &&
      /^[A-Za-z][A-Za-z.'-]+(\s+[A-Za-z][A-Za-z.'-]+){1,3}$/.test(line)
  );
  if (nameLine) {
    const parts = nameLine.split(/\s+/);
    parsed.firstName = parts[0];
    parsed.lastName = parts.slice(1).join(' ');
    parsed.fullName = nameLine;
  }

  const urls = [...new Set(text.match(URL_RE) || [])];
  for (const url of urls) {
    const lower = url.toLowerCase();
    if (!parsed.github && /github\.com\//i.test(lower)) {
      parsed.github = normalizeUrl(url);
      continue;
    }
    if (!parsed.linkedin && /linkedin\.com\//i.test(lower)) {
      parsed.linkedin = normalizeUrl(url);
      continue;
    }
  }

  if (!parsed.linkedin && parsed.github) {
    const handle = parsed.github.replace(/\/$/, '').split('/').pop();
    if (handle) parsed.linkedin = `https://www.linkedin.com/in/${handle}/`;
  }

  if (!parsed.portfolio) {
    const portfolioCandidate = urls.find((url) => {
      const lower = url.toLowerCase();
      return (
        !/github\.com|linkedin\.com|hackerrank|medium\.com|substack|twitter\.com|x\.com/i.test(lower)
      );
    });
    if (portfolioCandidate) parsed.portfolio = normalizeUrl(portfolioCandidate);
  }

  const yearsMatch = text.match(YEARS_RE);
  if (yearsMatch) parsed.yearsExperience = yearsMatch[1];

  const workExperience = parseWorkExperienceFromResumeText(text);
  if (workExperience.length) {
    parsed.workExperience = workExperience;
    parsed.currentTitle = workExperience[0].jobTitle;
    parsed.currentCompany = workExperience[0].company;
    parsed.location = workExperience[0].location;
  } else {
    const experienceIdx = lines.findIndex((line) => /^experience$/i.test(line));
    const experienceLines = experienceIdx >= 0 ? lines.slice(experienceIdx + 1, experienceIdx + 8) : lines.slice(0, 12);

    for (const line of experienceLines) {
      const jobMatch = line.match(JOB_LINE_RE);
      if (jobMatch) {
        parsed.currentTitle = jobMatch[1].trim();
        parsed.currentCompany = jobMatch[2].trim();
        parsed.location = jobMatch[3].trim();
        break;
      }
    }
  }

  if (!parsed.location) {
    const locationMatch = headerBlock.match(LOCATION_RE) || text.match(LOCATION_RE);
    if (locationMatch) parsed.location = `${locationMatch[1]}, ${locationMatch[2]}`;
  }

  if (parsed.currentTitle && !parsed.targetRole) {
    parsed.targetRole = parsed.currentTitle;
  }

  return parsed;
}

function workExperienceKey(entry) {
  return `${entry.company?.trim().toLowerCase()}|${entry.jobTitle?.trim().toLowerCase()}`;
}

function companyKey(entry) {
  return entry.company?.trim().toLowerCase() || '';
}

function mergeWorkExperienceLists(existing, incoming, force = false) {
  if (!incoming?.length) return existing || [];
  if (!existing?.length || force) return incoming;

  const byKey = new Map(incoming.map((entry) => [workExperienceKey(entry), entry]));
  const byCompany = new Map();
  for (const entry of incoming) {
    const key = companyKey(entry);
    if (!key) continue;
    const current = byCompany.get(key);
    if (!current || (entry.description?.length || 0) > (current.description?.length || 0)) {
      byCompany.set(key, entry);
    }
  }

  const merged = existing.map((entry) => {
    const parsed = byKey.get(workExperienceKey(entry)) || byCompany.get(companyKey(entry));
    if (!parsed) return entry;
    return {
      ...entry,
      jobTitle: entry.jobTitle?.trim() || parsed.jobTitle,
      location: entry.location?.trim() || parsed.location,
      startDate: entry.startDate?.trim() || parsed.startDate,
      endDate: entry.endDate?.trim() || parsed.endDate || '',
      currentlyEmployed: entry.currentlyEmployed ?? parsed.currentlyEmployed,
      description: parsed.description?.trim() || entry.description || ''
    };
  });

  for (const entry of incoming) {
    const company = companyKey(entry);
    if (!company) continue;
    if (!merged.some((item) => companyKey(item) === company)) {
      merged.push(entry);
    }
  }

  const seenCompanies = new Set();
  const deduped = [];
  for (const entry of merged) {
    const company = companyKey(entry);
    if (company && seenCompanies.has(company)) continue;
    if (company) seenCompanies.add(company);
    deduped.push(entry);
  }

  return deduped;
}

function normalizePhone(phone) {
  const digits = phone.replace(/\D/g, '');
  if (digits.length === 11 && digits.startsWith('1')) {
    return `+1 ${digits.slice(1, 4)}-${digits.slice(4, 7)}-${digits.slice(7)}`;
  }
  if (digits.length === 10) {
    return `+1 ${digits.slice(0, 3)}-${digits.slice(3, 6)}-${digits.slice(6)}`;
  }
  return phone.trim();
}

function normalizeUrl(url) {
  return url.replace(/[|,.)]+$/, '').trim();
}

const PROFILE_STRING_KEYS = [
  'firstName',
  'lastName',
  'fullName',
  'email',
  'phone',
  'location',
  'linkedin',
  'github',
  'portfolio',
  'yearsExperience',
  'currentTitle',
  'currentCompany',
  'targetRole'
];

/**
 * @param {Record<string, string>} existing
 * @param {Record<string, string>} extracted
 * @param {{ force?: boolean }} [options]
 */
export function mergeParsedProfile(existing, extracted, options = {}) {
  const merged = { ...existing };
  const force = Boolean(options.force);

  for (const key of PROFILE_STRING_KEYS) {
    const next = extracted[key]?.trim();
    if (!next) continue;
    const current = merged[key]?.trim();
    if (force || !current) {
      merged[key] = next;
    }
  }

  if (!merged.fullName?.trim() && merged.firstName?.trim()) {
    merged.fullName = `${merged.firstName} ${merged.lastName || ''}`.trim();
  }

  if (extracted.workExperience?.length) {
    merged.workExperience = mergeWorkExperienceLists(
      merged.workExperience,
      extracted.workExperience,
      force
    );
  }

  return merged;
}

/**
 * @param {{ profile: Record<string, string>; documents: { defaultResume?: { base64: string } } }} db
 * @param {{ force?: boolean }} [options]
 */
export async function parseResumeIntoDb(db, options = {}) {
  const text = await extractTextFromResume(db.documents?.defaultResume);
  const extracted = parseProfileFromResumeText(text);
  const profile = mergeParsedProfile(db.profile || {}, extracted, options);

  return {
    profile,
    extracted,
    textPreview: text.slice(0, 500)
  };
}
