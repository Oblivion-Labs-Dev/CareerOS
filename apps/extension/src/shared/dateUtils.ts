export function getCurrentDateString(): string {
  return new Date().toLocaleDateString();
}

export function getCurrentDateTimeISO(): string {
  return new Date().toISOString();
}

export function formatDate(isoString: string): string {
  if (!isoString) return '';
  const d = new Date(isoString);
  return isNaN(d.getTime()) ? '' : d.toLocaleDateString();
}
