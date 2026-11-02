export function formatCompanySlug(slug: string): string {
  const spaced = slug
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/[-_]+/g, ' ')
    .trim();
  return spaced.replace(/\b\w/g, (char) => char.toUpperCase());
}

export function parseCompanyFromJobUrl(href: string): string | null {
  try {
    const url = new URL(href);
    const path = url.pathname;

    const greenhouse = path.match(/\/([^/]+)\/jobs\/\d+/i);
    if (greenhouse?.[1] && !['embed', 'job_app'].includes(greenhouse[1].toLowerCase())) {
      return formatCompanySlug(greenhouse[1]);
    }

    const workday = path.match(/\/recruiting\/([^/]+)/i);
    if (workday?.[1]) {
      return formatCompanySlug(workday[1]);
    }

    const lever = path.match(/jobs\.lever\.co\/([^/]+)/i);
    if (lever?.[1]) {
      return formatCompanySlug(lever[1]);
    }

    if (/ashbyhq\.com/i.test(url.hostname)) {
      const ashby = path.match(/^\/([^/]+)(?:\/|$)/i);
      const slug = ashby?.[1]?.toLowerCase();
      if (slug && !['api', 'embed', 'jobs', 'postings'].includes(slug)) {
        return formatCompanySlug(ashby![1]);
      }
    }
  } catch {
    // ignored
  }
  return null;
}

export function jobPostingKey(url: string): string | null {
  try {
    const parsed = new URL(url);
    const path = parsed.pathname.toLowerCase();

    const greenhouse = path.match(/\/jobs\/(\d+)/);
    if (greenhouse) return `gh:${greenhouse[1]}`;

    const workday = path.match(/\/job\/([^/?#]+)/);
    if (workday) return `wd:${workday[1]}`;

    const lever = path.match(/\/([^/]+)\/([a-f0-9-]{8,})(?:\/apply)?$/i);
    if (lever) return `lever:${lever[1]}:${lever[2]}`;

    return `${parsed.hostname}${path}`.replace(/\/apply\/?$/, '');
  } catch {
    return null;
  }
}

export function urlsReferToSameJob(a: string, b: string): boolean {
  if (!a || !b) return false;
  if (a === b) return true;
  if (a.split('?')[0] === b.split('?')[0]) return true;

  const keyA = jobPostingKey(a);
  const keyB = jobPostingKey(b);
  return Boolean(keyA && keyB && keyA === keyB);
}

export function isBetterCompanyName(candidate: string | undefined, current: string | undefined): boolean {
  const bad = new Set(['', 'unknown company', 'workday client', 'ashby client', 'unknown']);
  const normalizedCandidate = (candidate || '').trim().toLowerCase();
  const normalizedCurrent = (current || '').trim().toLowerCase();
  if (bad.has(normalizedCandidate)) return false;
  if (bad.has(normalizedCurrent)) return true;
  return normalizedCandidate.length > normalizedCurrent.length;
}

export function isBetterRoleTitle(candidate: string | undefined, current: string | undefined): boolean {
  const bad = new Set(['', 'unknown role', 'unknown']);
  const normalizedCandidate = (candidate || '').trim().toLowerCase();
  const normalizedCurrent = (current || '').trim().toLowerCase();
  if (bad.has(normalizedCandidate)) return false;
  if (bad.has(normalizedCurrent)) return true;
  return normalizedCandidate.length > normalizedCurrent.length;
}
