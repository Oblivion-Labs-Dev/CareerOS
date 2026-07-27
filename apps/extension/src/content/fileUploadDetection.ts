import { getLabelText } from './domScanner';

const UPLOAD_COVER_RE = /cover\s*letter|writing\s*sample/i;
const UPLOAD_RESUME_RE = /résumé|resume|\bcv\b|curriculum\s*vitae/i;

export type FileUploadKind = 'resume' | 'coverLetter';

export function detectUploadKindFromHint(hint: string): FileUploadKind | null {
  const lower = hint.toLowerCase();
  if (UPLOAD_COVER_RE.test(lower)) return 'coverLetter';
  if (UPLOAD_RESUME_RE.test(lower)) return 'resume';
  return null;
}

export function fileInputHint(input: HTMLInputElement, doc: Document): string {
  return `${input.id} ${input.name} ${input.getAttribute('aria-label') || ''} ${getLabelText(input, doc)}`;
}

export function detectFileInputUploadKind(
  input: HTMLInputElement,
  doc: Document
): FileUploadKind | null {
  return detectUploadKindFromHint(fileInputHint(input, doc));
}

export function isFileInputFilled(input: HTMLInputElement): boolean {
  return (input.files?.length ?? 0) > 0;
}

export function listFileInputs(doc: Document): HTMLInputElement[] {
  return Array.from(doc.querySelectorAll('input[type="file"]')) as HTMLInputElement[];
}

export function findFileInputForKind(
  kind: FileUploadKind,
  doc: Document
): HTMLInputElement | null {
  for (const input of listFileInputs(doc)) {
    if (detectFileInputUploadKind(input, doc) === kind) {
      return input;
    }
  }
  return null;
}

export function isUploadKindAttached(kind: FileUploadKind, doc: Document): boolean {
  return listFileInputs(doc).some(
    (input) => detectFileInputUploadKind(input, doc) === kind && isFileInputFilled(input)
  );
}

export function zoneTextIndicatesKind(text: string, kind: FileUploadKind): boolean {
  const normalized = text.replace(/\s+/g, ' ').trim();
  if (!/drop or select|attach|upload|choose file|browse/i.test(normalized)) return false;
  const detected = detectUploadKindFromHint(normalized);
  return detected === kind;
}
