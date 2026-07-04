const SENSITIVE_PATTERNS = [
  /password/i,
  /ssn/i,
  /social\s*security/i,
  /credit\s*card/i,
  /bank/i,
  /routing/i,
  /account\s*number/i,
  /security\s*code/i,
  /cvv/i,
  /pin\b/i,
  /passport/i,
  /national\s*id/i,
  /driver\s*license/i,
  /tax\s*id/i
];

/**
 * Checks if a field contains sensitive information that should never be learned or cached.
 */
export function isSensitiveField(label: string, name: string, id: string): boolean {
  const checkText = `${label} ${name} ${id}`;
  return SENSITIVE_PATTERNS.some(pattern => pattern.test(checkText));
}
