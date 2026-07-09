import { scrollToMarkedField } from './fieldMarker';

const WIDGET_STYLES = `
#jobfill-floating-wrapper {
  position: fixed;
  right: 20px;
  top: 50%;
  transform: translateY(-50%);
  z-index: 2147483647;
  font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
}

#jobfill-floating-button {
  display: flex;
  align-items: center;
  gap: 10px;
  background: rgba(10, 18, 16, 0.92);
  color: #ecfdf5;
  border: 1px solid rgba(46, 229, 157, 0.28);
  border-radius: 999px;
  padding: 10px 14px 10px 10px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.35);
  backdrop-filter: blur(12px);
  transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
}

#jobfill-floating-button:hover:not(:disabled) {
  transform: translateY(-1px);
  border-color: rgba(46, 229, 157, 0.45);
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.4);
}

#jobfill-floating-button:disabled {
  opacity: 0.85;
  cursor: wait;
}

#jobfill-floating-button .jf-mark {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: linear-gradient(145deg, #2ee59d, #14b8a6);
  color: #042f1e;
  font-size: 11px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

#jobfill-floating-button .jf-label {
  white-space: nowrap;
  letter-spacing: -0.01em;
}

#jobfill-floating-button.is-loading {
  border-color: rgba(46, 229, 157, 0.42);
  box-shadow:
    0 0 0 1px rgba(46, 229, 157, 0.12) inset,
    0 0 24px rgba(46, 229, 157, 0.22),
    0 6px 24px rgba(0, 0, 0, 0.38);
  animation: ap-loading-glow 2.2s ease-in-out infinite;
}

#jobfill-floating-button.is-loading .jf-mark {
  background: rgba(4, 47, 30, 0.85);
  border: none;
  color: transparent;
  position: relative;
  overflow: visible;
}

#jobfill-floating-button.is-loading .jf-mark::before,
#jobfill-floating-button.is-loading .jf-mark::after {
  content: '';
  position: absolute;
  border-radius: 50%;
}

#jobfill-floating-button.is-loading .jf-mark::before {
  inset: -2px;
  background: conic-gradient(
    from 180deg,
    transparent 0deg,
    rgba(46, 229, 157, 0.2) 60deg,
    #2ee59d 150deg,
    #6ee7b7 220deg,
    transparent 300deg
  );
  animation: ap-spin 1.1s cubic-bezier(0.55, 0.1, 0.35, 0.9) infinite;
}

#jobfill-floating-button.is-loading .jf-mark::after {
  inset: 1px;
  background: rgba(4, 47, 30, 0.95);
  border-radius: 7px;
}

#jobfill-floating-button.is-loading .jf-label {
  background: linear-gradient(
    90deg,
    #a7f3d0 0%,
    #ecfdf5 40%,
    #6ee7b7 60%,
    #a7f3d0 100%
  );
  background-size: 220% 100%;
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  animation: jf-label-shimmer 2s ease-in-out infinite;
}

#jobfill-floating-button.is-success .jf-mark {
  animation: ap-pop 0.35s ease;
}

#jobfill-floating-button.is-warning .jf-mark {
  background: rgba(251, 191, 36, 0.2);
  color: #fbbf24;
  border: 1px solid rgba(251, 191, 36, 0.35);
}

#jobfill-floating-dismiss {
  position: absolute;
  top: -6px;
  left: -6px;
  width: 18px;
  height: 18px;
  background: rgba(30, 41, 39, 0.95);
  color: #9ca3af;
  border-radius: 50%;
  border: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  cursor: pointer;
  line-height: 1;
}

#jobfill-floating-dismiss:hover {
  color: #ecfdf5;
  background: rgba(55, 65, 81, 0.95);
}

#jobfill-floating-submit {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-width: 156px;
  background: linear-gradient(145deg, #065f46 0%, #047857 100%);
  color: #ecfdf5;
  border: 1px solid rgba(110, 231, 183, 0.55);
  border-radius: 999px;
  padding: 9px 16px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.02em;
  cursor: pointer;
  box-shadow:
    0 4px 18px rgba(4, 120, 87, 0.35),
    0 0 0 1px rgba(255, 255, 255, 0.04) inset;
  backdrop-filter: blur(12px);
  transition: transform 0.2s ease, border-color 0.2s ease, background 0.2s ease, box-shadow 0.2s ease;
}

#jobfill-floating-submit .jf-submit-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.16);
  color: #ecfdf5;
  font-size: 11px;
  font-weight: 800;
  flex-shrink: 0;
}

#jobfill-floating-submit:hover:not(:disabled) {
  transform: translateY(-1px);
  background: linear-gradient(145deg, #047857 0%, #059669 100%);
  border-color: rgba(167, 243, 208, 0.75);
  box-shadow:
    0 6px 22px rgba(4, 120, 87, 0.45),
    0 0 0 1px rgba(255, 255, 255, 0.06) inset;
}

#jobfill-floating-submit:disabled {
  cursor: default;
}

#jobfill-floating-submit.is-tracked,
#jobfill-floating-submit.is-locked {
  background: rgba(10, 18, 16, 0.94);
  border-color: rgba(46, 229, 157, 0.42);
  color: #a7f3d0;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.28);
  opacity: 1;
}

#jobfill-floating-submit.is-locked {
  pointer-events: none;
}

#jobfill-skipped-panel {
  position: absolute;
  right: 0;
  top: calc(100% + 10px);
  width: min(320px, calc(100vw - 40px));
  max-height: 220px;
  overflow: auto;
  background: rgba(10, 18, 16, 0.96);
  border: 1px solid rgba(251, 191, 36, 0.35);
  border-radius: 12px;
  padding: 10px;
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.45);
  display: none;
}

#jobfill-skipped-panel.is-visible {
  display: block;
}

#jobfill-skipped-panel h4 {
  margin: 0 0 8px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: #fbbf24;
}

#jobfill-skipped-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

#jobfill-skipped-list button {
  width: 100%;
  text-align: left;
  background: rgba(251, 191, 36, 0.08);
  border: 1px solid rgba(251, 191, 36, 0.22);
  border-radius: 8px;
  color: #fef3c7;
  padding: 8px 10px;
  font-size: 12px;
  line-height: 1.35;
  cursor: pointer;
}

#jobfill-skipped-list button:hover {
  background: rgba(251, 191, 36, 0.16);
  border-color: rgba(251, 191, 36, 0.4);
}

#jobfill-skipped-list .jf-skipped-reason {
  display: block;
  margin-top: 2px;
  font-size: 10px;
  color: rgba(254, 243, 199, 0.72);
}

@keyframes ap-spin {
  to { transform: rotate(360deg); }
}

@keyframes ap-loading-glow {
  0%, 100% {
    box-shadow:
      0 0 0 1px rgba(46, 229, 157, 0.1) inset,
      0 0 18px rgba(46, 229, 157, 0.16),
      0 6px 24px rgba(0, 0, 0, 0.38);
  }
  50% {
    box-shadow:
      0 0 0 1px rgba(46, 229, 157, 0.18) inset,
      0 0 28px rgba(46, 229, 157, 0.32),
      0 8px 28px rgba(0, 0, 0, 0.42);
  }
}

@keyframes jf-label-shimmer {
  0% { background-position: 120% 0; }
  100% { background-position: -120% 0; }
}

@keyframes ap-pop {
  0% { transform: scale(0.85); }
  60% { transform: scale(1.08); }
  100% { transform: scale(1); }
}
`;

export type WidgetState = 'idle' | 'loading' | 'success' | 'warning';

export interface AutofillSkippedFieldRef {
  label: string;
  reason: string;
  fieldId: string;
}

export interface SubmitTrackedInfo {
  company: string;
  role: string;
  submittedAt?: string;
  platform?: string;
}

export interface FloatingWidget {
  setState: (state: WidgetState, label: string) => void;
  setDisabled: (disabled: boolean) => void;
  setSubmitDisabled: (disabled: boolean) => void;
  showSubmitTracked: (info: SubmitTrackedInfo) => void;
  lockSubmitButton: () => void;
  resetSubmitButton: () => void;
  onClick: (handler: () => void | Promise<void>) => void;
  onSubmit: (handler: () => void | Promise<void>) => void;
  showSkippedFields: (fields: AutofillSkippedFieldRef[]) => void;
  hideSkippedFields: () => void;
}

export function mountFloatingWidget(): FloatingWidget {
  if (document.getElementById('jobfill-floating-wrapper')) {
    const existing = document.getElementById('jobfill-floating-button') as HTMLButtonElement | null;
    const submitBtn = document.getElementById('jobfill-floating-submit') as HTMLButtonElement | null;
    const panel = document.getElementById('jobfill-skipped-panel');
    return {
      setState: (state, label) => applyWidgetState(existing, state, label),
      setDisabled: (d) => existing?.toggleAttribute('disabled', d),
      setSubmitDisabled: (d) => submitBtn?.toggleAttribute('disabled', d),
      showSubmitTracked: (info) => applySubmitTracked(submitBtn, info),
      lockSubmitButton: () => lockSubmitButton(submitBtn),
      resetSubmitButton: () => resetSubmitButton(submitBtn),
      onClick: () => {},
      onSubmit: () => {},
      showSkippedFields: (fields) => renderSkippedFieldsPanel(panel, fields),
      hideSkippedFields: () => panel?.classList.remove('is-visible')
    };
  }

  if (!document.getElementById('jobfill-widget-styles')) {
    const style = document.createElement('style');
    style.id = 'jobfill-widget-styles';
    style.textContent = WIDGET_STYLES;
    document.head.appendChild(style);
  }

  const wrapper = document.createElement('div');
  wrapper.id = 'jobfill-floating-wrapper';

  const btn = document.createElement('button');
  btn.id = 'jobfill-floating-button';
  btn.type = 'button';
  btn.innerHTML = `<span class="jf-mark">JF</span><span class="jf-label">Fill application</span>`;

  const submitBtn = document.createElement('button');
  submitBtn.id = 'jobfill-floating-submit';
  submitBtn.type = 'button';
  submitBtn.title = 'After you submit on the employer site, click to track company, role, and date';
  submitBtn.innerHTML = '<span class="jf-submit-icon">✓</span><span class="jf-submit-label">Track submit</span>';

  const dismiss = document.createElement('button');
  dismiss.id = 'jobfill-floating-dismiss';
  dismiss.type = 'button';
  dismiss.setAttribute('aria-label', 'Dismiss');
  dismiss.textContent = '×';

  wrapper.appendChild(btn);
  wrapper.appendChild(submitBtn);
  wrapper.appendChild(dismiss);

  const skippedPanel = document.createElement('div');
  skippedPanel.id = 'jobfill-skipped-panel';
  skippedPanel.innerHTML = `
    <h4>Skipped fields</h4>
    <ul id="jobfill-skipped-list"></ul>
  `;
  wrapper.appendChild(skippedPanel);

  document.body.appendChild(wrapper);

  dismiss.addEventListener('click', (e) => {
    e.stopPropagation();
    wrapper.remove();
  });

  let clickHandler: (() => void | Promise<void>) | null = null;
  btn.addEventListener('click', () => {
    if (btn.disabled || !clickHandler) return;
    void clickHandler();
  });

  let submitHandler: (() => void | Promise<void>) | null = null;
  submitBtn.addEventListener('click', (event) => {
    event.stopPropagation();
    if (submitBtn.disabled || !submitHandler) return;
    void submitHandler();
  });

  return {
    setState: (state, label) => applyWidgetState(btn, state, label),
    setDisabled: (disabled) => btn.toggleAttribute('disabled', disabled),
    setSubmitDisabled: (disabled) => submitBtn.toggleAttribute('disabled', disabled),
    showSubmitTracked: (info) => applySubmitTracked(submitBtn, info),
    lockSubmitButton: () => lockSubmitButton(submitBtn),
    resetSubmitButton: () => resetSubmitButton(submitBtn),
    onClick: (handler) => {
      clickHandler = handler;
    },
    onSubmit: (handler) => {
      submitHandler = handler;
    },
    showSkippedFields: (fields) => renderSkippedFieldsPanel(skippedPanel, fields),
    hideSkippedFields: () => skippedPanel.classList.remove('is-visible')
  };
}

function renderSkippedFieldsPanel(
  panel: HTMLElement | null,
  fields: AutofillSkippedFieldRef[]
): void {
  if (!panel) return;

  const list = panel.querySelector('#jobfill-skipped-list');
  if (!list) return;

  list.innerHTML = '';
  if (!fields.length) {
    panel.classList.remove('is-visible');
    return;
  }

  for (const field of fields) {
    const item = document.createElement('li');
    const button = document.createElement('button');
    button.type = 'button';
    button.innerHTML = `${escapeHtml(field.label)}<span class="jf-skipped-reason">${escapeHtml(field.reason)}</span>`;
    button.addEventListener('click', (event) => {
      event.stopPropagation();
      scrollToMarkedField(document, field.fieldId);
    });
    item.appendChild(button);
    list.appendChild(item);
  }

  panel.classList.add('is-visible');
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function formatSubmitDate(value?: string): string {
  if (!value) return new Date().toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return new Date().toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function truncateLabel(value: string, max = 18): string {
  const trimmed = value.trim();
  if (trimmed.length <= max) return trimmed;
  return `${trimmed.slice(0, max - 1)}…`;
}

function applySubmitTracked(btn: HTMLButtonElement | null, info: SubmitTrackedInfo): void {
  if (!btn) return;
  btn.classList.add('is-tracked');
  const dateLabel = formatSubmitDate(info.submittedAt);
  const companyLabel = truncateLabel(info.company || 'Company');
  btn.innerHTML = `<span class="jf-submit-icon">✓</span><span class="jf-submit-label">${companyLabel} · ${dateLabel}</span>`;
  btn.title = `${info.company} — ${info.role}${info.platform ? ` (${info.platform})` : ''}`;
}

function lockSubmitButton(btn: HTMLButtonElement | null): void {
  if (!btn) return;
  btn.classList.add('is-locked');
  btn.setAttribute('disabled', 'true');
}

function resetSubmitButton(btn: HTMLButtonElement | null): void {
  if (!btn || btn.classList.contains('is-locked')) return;
  btn.classList.remove('is-tracked');
  btn.innerHTML = '<span class="jf-submit-icon">✓</span><span class="jf-submit-label">Track submit</span>';
  btn.title = 'After you submit on the employer site, click to track company, role, and date';
  btn.removeAttribute('disabled');
}

function applyWidgetState(btn: HTMLButtonElement | null, state: WidgetState, label: string): void {
  if (!btn) return;
  btn.classList.remove('is-loading', 'is-success', 'is-warning');
  if (state === 'loading') btn.classList.add('is-loading');
  if (state === 'success') btn.classList.add('is-success');
  if (state === 'warning') btn.classList.add('is-warning');

  const mark = btn.querySelector('.jf-mark');
  const labelEl = btn.querySelector('.jf-label');
  if (labelEl) labelEl.textContent = label;
  if (!mark) return;

  if (state === 'idle') mark.innerHTML = 'AP';
  else if (state === 'loading') mark.innerHTML = '';
  else if (state === 'success') mark.innerHTML = '✓';
  else if (state === 'warning') mark.innerHTML = '!';
}
