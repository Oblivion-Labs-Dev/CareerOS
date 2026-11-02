import { scanPage, ScannedField } from './domScanner';

export function resolveFreshField(cached: ScannedField, freshFields: ScannedField[]): ScannedField | null {
  if (cached.dataInput) {
    const byDataInput = freshFields.find(
      (f) => f.dataInput === cached.dataInput && f.type === cached.type
    );
    if (byDataInput) return { ...cached, element: byDataInput.element };
  }

  if (cached.htmlId) {
    const byId = freshFields.find((f) => f.htmlId === cached.htmlId && f.type === cached.type);
    if (byId) return { ...cached, element: byId.element };
  }

  if (cached.labelText) {
    const byLabel = freshFields.find(
      (f) => f.labelText === cached.labelText && f.type === cached.type
    );
    if (byLabel) return { ...cached, element: byLabel.element };
  }

  if (cached.element.isConnected) return cached;
  return null;
}

export function refreshScannedFields(cachedFields: ScannedField[], doc: Document = document): ScannedField[] {
  const freshFields = scanPage(doc);
  return cachedFields
    .map((cached) => resolveFreshField(cached, freshFields))
    .filter((field): field is ScannedField => field !== null);
}

export function autofillFieldPriority(
  type: ScannedField['type'],
  canonicalKey?: string
): number {
  if (canonicalKey === 'resume' || canonicalKey === 'coverLetter') return -1;
  if (type === 'file') return -1;
  if (type === 'text' || type === 'textarea') return 0;
  if (type === 'select') return 1;
  if (type === 'radio' || type === 'checkbox') return 2;
  return 4;
}
