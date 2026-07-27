import { scrollToMarkedField } from './fieldMarker';
import {
  employmentTypeColor,
  employmentTypeLabel,
  JobPageEnrichment
} from '../shared/jobPageEnrichment';
import { H1bSponsorshipResult, h1bStatusColor } from '../shared/h1bSponsorshipCheck';
import { TrackerPipelineStatus } from '../shared/saveJobToTracker';

export const COPILOT_UI_VERSION = '4';

const WIDGET_STYLES = `
#jobfill-floating-wrapper {
  position: fixed;
  right: 0;
  top: 50%;
  transform: translateY(-50%);
  z-index: 2147483647;
  font-family: 'Outfit', 'Segoe UI', system-ui, -apple-system, sans-serif;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6px;
  padding-right: 10px;
  max-height: 96vh;
  pointer-events: none;
}

#jobfill-floating-wrapper > * {
  pointer-events: auto;
}

#jobfill-copilot-panel {
  position: relative;
  width: 240px;
  max-height: min(420px, 82vh);
  overflow-x: hidden;
  overflow-y: auto;
  padding: 10px 10px 8px;
  border-radius: 14px 4px 4px 14px;
  border: 1px solid rgba(34, 211, 238, 0.22);
  background:
    radial-gradient(ellipse 90% 60% at 100% 0%, rgba(167, 139, 250, 0.14), transparent 55%),
    rgba(6, 8, 15, 0.94);
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.45), 0 0 24px rgba(34, 211, 238, 0.08);
  backdrop-filter: blur(14px);
  display: none;
  box-sizing: border-box;
}

#jobfill-copilot-panel.is-open {
  display: block;
  animation: jf-panel-in 0.28s cubic-bezier(0.22, 1, 0.36, 1);
}

@keyframes jf-panel-in {
  from { opacity: 0; transform: translateX(12px); }
  to { opacity: 1; transform: translateX(0); }
}

.jf-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}

.jf-brand {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: #22d3ee;
}

.jf-ui-version {
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: #67e8f9;
  opacity: 0.85;
}

.jf-platform-pill {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(167, 139, 250, 0.16);
  color: #c4b5fd;
  border: 1px solid rgba(167, 139, 250, 0.28);
}

.jf-job-role {
  margin: 0;
  font-size: 13px;
  font-weight: 700;
  color: #f1f5f9;
  line-height: 1.35;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.jf-job-subline {
  margin: 4px 0 0;
  font-size: 11px;
  color: #64748b;
  line-height: 1.35;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.jf-meta-row {
  display: flex;
  flex-wrap: nowrap;
  gap: 4px;
  margin: 6px 0 0;
  overflow: hidden;
}

.jf-meta-pill {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(255, 255, 255, 0.04);
  color: #cbd5e1;
}

.jf-meta-pill.is-employment {
  border-color: transparent;
  color: #041016;
}

.jf-meta-pill.is-h1b {
  border-color: transparent;
  color: #041016;
  font-weight: 700;
}

.jf-insights {
  margin: 6px 0 0;
  padding: 5px 7px;
  border-radius: 8px;
  border: 1px solid rgba(248, 113, 113, 0.25);
  background: rgba(248, 113, 113, 0.08);
  font-size: 10px;
  line-height: 1.35;
  color: #fecaca;
  max-height: 48px;
  overflow-y: auto;
}

.jf-insights.is-info {
  border-color: rgba(34, 211, 238, 0.25);
  background: rgba(34, 211, 238, 0.08);
  color: #a5f3fc;
}

.jf-insights strong {
  display: block;
  font-size: 11px;
  margin-bottom: 2px;
}

#jobfill-floating-queue {
  /* toolbar variant */
}

.jf-status-row {
  margin: 8px 0 4px;
}

.jf-pipeline-select {
  width: 100%;
  box-sizing: border-box;
  padding: 6px 8px;
  border-radius: 8px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(255, 255, 255, 0.04);
  color: #e2e8f0;
  font-size: 11px;
  font-weight: 600;
  font-family: inherit;
}

.jf-inline-stat {
  margin: 0 0 6px;
  font-size: 10px;
  color: #64748b;
  line-height: 1.3;
}

#jobfill-floating-save {
  /* toolbar variant — see .jf-toolbar-btn */
}

#jobfill-floating-save:hover:not(:disabled) {
  transform: none;
  filter: brightness(1.05);
}

#jobfill-floating-save:disabled {
  opacity: 0.75;
  cursor: wait;
}

#jobfill-floating-save.is-saved {
  background: rgba(10, 18, 16, 0.94);
  border-color: rgba(167, 139, 250, 0.42);
  color: #ddd6fe;
  cursor: default;
}

#jobfill-floating-save.is-duplicate {
  border-color: rgba(251, 191, 36, 0.45);
  color: #fde68a;
}

#jobfill-floating-scan {
  /* toolbar variant */
}

#jobfill-floating-scan:hover:not(:disabled) {
  filter: brightness(1.05);
}

#jobfill-floating-scan:disabled {
  opacity: 0.75;
  cursor: wait;
}

.jf-match-chip strong.is-good { color: #4ade80; }
.jf-match-chip strong.is-mid { color: #fbbf24; }
.jf-match-chip strong.is-low { color: #f87171; }

#jobfill-scan-panel,
#jobfill-skipped-panel,
#jobfill-error-panel {
  position: static;
  width: 100%;
  max-height: 120px;
  overflow: auto;
  margin-top: 6px;
  border-radius: 8px;
  padding: 8px;
  box-shadow: none;
  display: none;
  box-sizing: border-box;
}

#jobfill-scan-panel {
  background: rgba(6, 14, 24, 0.96);
  border: 1px solid rgba(56, 189, 248, 0.35);
}

#jobfill-skipped-panel {
  background: rgba(10, 18, 16, 0.96);
  border: 1px solid rgba(251, 191, 36, 0.35);
}

#jobfill-error-panel {
  background: rgba(24, 10, 10, 0.96);
  border: 1px solid rgba(248, 113, 113, 0.4);
}

#jobfill-scan-panel.is-visible,
#jobfill-skipped-panel.is-visible,
#jobfill-error-panel.is-visible {
  display: block;
}

#jobfill-scan-panel h4,
#jobfill-skipped-panel h4,
#jobfill-error-panel h4 {
  margin: 0 0 6px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

#jobfill-scan-panel h4 { color: #7dd3fc; }
#jobfill-skipped-panel h4 { color: #fbbf24; }

.jf-skipped-summary {
  margin: 0 0 0.45rem;
  font-size: 0.68rem;
  line-height: 1.35;
  color: rgba(251, 191, 36, 0.92);
}
#jobfill-error-panel h4 { color: #fca5a5; }

#jobfill-scan-panel p {
  margin: 0 0 6px;
  font-size: 11px;
  line-height: 1.45;
  color: #e0f2fe;
}

#jobfill-error-panel p {
  margin: 0;
  font-size: 11px;
  line-height: 1.45;
  color: #fecaca;
  word-break: break-word;
}

#jobfill-skipped-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

#jobfill-skipped-list button {
  width: 100%;
  text-align: left;
  background: rgba(251, 191, 36, 0.08);
  border: 1px solid rgba(251, 191, 36, 0.22);
  border-radius: 8px;
  color: #fef3c7;
  padding: 6px 8px;
  font-size: 11px;
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

#jobfill-scan-panel .jf-scan-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

#jobfill-scan-panel .jf-scan-tag {
  font-size: 10px;
  padding: 2px 7px;
  border-radius: 999px;
  background: rgba(34, 211, 238, 0.12);
  color: #a5f3fc;
  border: 1px solid rgba(34, 211, 238, 0.22);
}

#jobfill-scan-panel .jf-scan-tag.is-missing {
  background: rgba(248, 113, 113, 0.1);
  color: #fecaca;
  border-color: rgba(248, 113, 113, 0.25);
}

.jf-stats-row,
#jobfill-floating-submit {
  display: none !important;
}

.jf-stat-chip {
  flex: 1;
  padding: 6px 8px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(148, 163, 184, 0.14);
  font-size: 11px;
  color: #cbd5e1;
}

.jf-stat-chip strong {
  display: block;
  font-size: 13px;
  color: #f1f5f9;
}

.jf-progress {
  height: 3px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  overflow: hidden;
  margin-bottom: 8px;
  display: none;
}

.jf-progress.is-visible {
  display: block;
}

.jf-progress-bar {
  height: 100%;
  width: 0%;
  border-radius: inherit;
  background: linear-gradient(90deg, #22d3ee, #a78bfa);
  transition: width 0.25s ease;
}

#jobfill-panel-toggle {
  align-self: flex-end;
  width: 36px;
  height: 48px;
  border: none;
  border-radius: 12px 0 0 12px;
  background: linear-gradient(135deg, #22d3ee 0%, #a78bfa 100%);
  color: #041016;
  font-size: 11px;
  font-weight: 800;
  cursor: pointer;
  box-shadow: -4px 4px 20px rgba(34, 211, 238, 0.25);
  letter-spacing: -0.02em;
}

#jobfill-panel-toggle:hover {
  filter: brightness(1.06);
}

#jobfill-floating-actions {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 6px;
  width: 100%;
  margin-top: 2px;
}

.jf-toolbar {
  display: flex;
  gap: 4px;
  width: 100%;
}

.jf-toolbar-btn {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 7px 4px;
  border-radius: 10px;
  font-size: 10px;
  font-weight: 700;
  cursor: pointer;
  border: 1px solid rgba(148, 163, 184, 0.2);
  background: rgba(255, 255, 255, 0.05);
  color: #e2e8f0;
  transition: filter 0.15s ease, background 0.15s ease;
}

.jf-toolbar-btn:hover:not(:disabled) {
  filter: brightness(1.08);
}

.jf-toolbar-btn:disabled {
  opacity: 0.6;
  cursor: wait;
}

#jobfill-floating-save.jf-toolbar-btn {
  background: rgba(124, 58, 237, 0.18);
  border-color: rgba(167, 139, 250, 0.35);
  color: #ddd6fe;
  box-shadow: none;
}

#jobfill-floating-scan.jf-toolbar-btn {
  background: rgba(14, 165, 233, 0.15);
  border-color: rgba(56, 189, 248, 0.3);
  color: #bae6fd;
  box-shadow: none;
}

#jobfill-floating-queue.jf-toolbar-btn {
  background: rgba(124, 58, 237, 0.1);
  border-color: rgba(124, 58, 237, 0.28);
  color: #c4b5fd;
  box-shadow: none;
}

#jobfill-floating-actions.is-listing #jobfill-floating-save {
  flex: 1.4;
  padding: 9px 6px;
  font-size: 11px;
}

#jobfill-floating-save.is-saved,
#jobfill-floating-save.is-duplicate {
  opacity: 0.85;
}

#jobfill-floating-submit.jf-action-link {
  min-width: unset;
  width: 100%;
  padding: 6px 8px;
  font-size: 10px;
  font-weight: 600;
  background: transparent;
  border: none;
  box-shadow: none;
  color: #6ee7b7;
  opacity: 0.85;
}

#jobfill-floating-submit.jf-action-link:hover:not(:disabled) {
  opacity: 1;
  background: rgba(16, 185, 129, 0.08);
  border-radius: 8px;
  transform: none;
}

#jobfill-floating-button {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  background: linear-gradient(135deg, #22d3ee 0%, #06b6d4 45%, #a78bfa 100%);
  color: #041016;
  border: none;
  border-radius: 999px;
  padding: 9px 14px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  box-shadow: 0 6px 24px rgba(34, 211, 238, 0.35);
  transition: transform 0.2s ease, box-shadow 0.2s ease, filter 0.2s ease;
}

#jobfill-floating-button:hover:not(:disabled) {
  transform: translateY(-1px);
  filter: brightness(1.04);
  box-shadow: 0 8px 28px rgba(34, 211, 238, 0.42);
}

#jobfill-floating-button:disabled {
  opacity: 0.85;
  cursor: wait;
}

#jobfill-floating-button .jf-mark {
  display: none;
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

#jobfill-floating-button.is-error {
  border-color: rgba(248, 113, 113, 0.45);
  box-shadow:
    0 0 0 1px rgba(248, 113, 113, 0.12) inset,
    0 0 20px rgba(248, 113, 113, 0.18),
    0 6px 24px rgba(0, 0, 0, 0.38);
}

#jobfill-floating-button.is-error .jf-mark {
  background: rgba(127, 29, 29, 0.35);
  color: #fca5a5;
  border: 1px solid rgba(248, 113, 113, 0.45);
  animation: ap-pop 0.35s ease;
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

export type WidgetState = 'idle' | 'loading' | 'success' | 'warning' | 'error';

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

export interface CopilotJobContext {
  company?: string;
  role?: string;
  platform?: string;
  location?: string;
  enrichment?: JobPageEnrichment;
  h1b?: H1bSponsorshipResult;
}

export type SaveJobWidgetState = 'idle' | 'parsing' | 'saving' | 'saved' | 'duplicate';

export interface FloatingWidget {
  setState: (state: WidgetState, label: string) => void;
  setDisabled: (disabled: boolean) => void;
  setAutofillVisible: (visible: boolean) => void;
  setSubmitDisabled: (disabled: boolean) => void;
  showSubmitTracked: (info: SubmitTrackedInfo) => void;
  lockSubmitButton: () => void;
  resetSubmitButton: () => void;
  setJobContext: (ctx: CopilotJobContext) => void;
  setFieldStats: (ready: number, filled?: number) => void;
  setProgress: (percent: number | null) => void;
  setPipelineStatus: (status: TrackerPipelineStatus) => void;
  setSaveJobState: (state: SaveJobWidgetState, label?: string) => void;
  setMatchScore: (score: number | null) => void;
  setInsights: (html: string | null, tone?: 'warn' | 'info') => void;
  showScanResult: (result: { score: number; matched: string[]; missing: string[] }) => void;
  hideScanResult: () => void;
  openPanel: () => void;
  onClick: (handler: () => void | Promise<void>) => void;
  onSaveJob: (handler: (status: TrackerPipelineStatus) => void | Promise<void>) => void;
  onScan: (handler: () => void | Promise<void>) => void;
  onQueue: (handler: () => void | Promise<void>) => void;
  onSubmit: (handler: () => void | Promise<void>) => void;
  onDismiss: (handler: (() => void) | null) => void;
  showSkippedFields: (fields: AutofillSkippedFieldRef[], summary?: string) => void;
  hideSkippedFields: () => void;
  showError: (message: string) => void;
  hideError: () => void;
}

export function mountFloatingWidget(): FloatingWidget {
  const noopPanel = {
    setJobContext: () => {},
    setFieldStats: () => {},
    setProgress: () => {},
    openPanel: () => {},
    setPipelineStatus: () => {},
    setSaveJobState: () => {},
    setMatchScore: () => {},
    setInsights: () => {},
    showScanResult: () => {},
    hideScanResult: () => {},
    setAutofillVisible: () => {},
  };

  document.getElementById('jobfill-floating-wrapper')?.remove();
  document.getElementById('jobfill-widget-styles')?.remove();

  if (!document.getElementById('jobfill-widget-styles')) {
    const style = document.createElement('style');
    style.id = 'jobfill-widget-styles';
    style.textContent = WIDGET_STYLES;
    document.head.appendChild(style);
  }

  const wrapper = document.createElement('div');
  wrapper.id = 'jobfill-floating-wrapper';
  wrapper.dataset.uiVersion = COPILOT_UI_VERSION;

  const toggleBtn = document.createElement('button');
  toggleBtn.id = 'jobfill-panel-toggle';
  toggleBtn.type = 'button';
  toggleBtn.title = 'ApplyPilot copilot';
  toggleBtn.textContent = 'AP';

  const copilotPanel = document.createElement('div');
  copilotPanel.id = 'jobfill-copilot-panel';
  copilotPanel.innerHTML = `
    <div class="jf-panel-header">
      <span class="jf-brand">ApplyPilot <span class="jf-ui-version">v${COPILOT_UI_VERSION}</span></span>
      <span class="jf-platform-pill" id="jf-platform-pill">ATS</span>
    </div>
    <h3 class="jf-job-role" id="jf-job-role">Job application</h3>
    <p class="jf-job-subline" id="jf-job-subline">Scanning page…</p>
    <div class="jf-meta-row" id="jf-meta-row"></div>
    <div class="jf-insights" id="jf-insights" hidden></div>
    <div class="jf-status-row">
      <select id="jf-pipeline-select" class="jf-pipeline-select" aria-label="Application status">
        <option value="saved">Saved</option>
        <option value="submitted">Applied</option>
        <option value="interviewing">Interview</option>
        <option value="offer">Offer</option>
        <option value="rejected">Rejected</option>
      </select>
    </div>
    <p class="jf-inline-stat" id="jf-inline-stat">Auto-tracks when you submit</p>
    <div class="jf-progress" id="jf-progress"><div class="jf-progress-bar" id="jf-progress-bar"></div></div>
    <div id="jobfill-floating-actions"></div>
    <div id="jobfill-scan-panel">
      <h4>Keyword match</h4>
      <p id="jobfill-scan-summary"></p>
      <div class="jf-scan-tags" id="jobfill-scan-tags"></div>
    </div>
    <div id="jobfill-skipped-panel">
      <h4 id="jobfill-skipped-title">Fields needing attention</h4>
      <p id="jobfill-skipped-summary" class="jf-skipped-summary"></p>
      <ul id="jobfill-skipped-list"></ul>
    </div>
    <div id="jobfill-error-panel">
      <h4>Something went wrong</h4>
      <p id="jobfill-error-message"></p>
    </div>
  `;

  const actionsHost = copilotPanel.querySelector('#jobfill-floating-actions') as HTMLElement;

  const saveBtn = document.createElement('button');
  saveBtn.id = 'jobfill-floating-save';
  saveBtn.type = 'button';
  saveBtn.className = 'jf-toolbar-btn';
  saveBtn.title = 'Save job to tracker';
  saveBtn.textContent = 'Save';

  const scanBtn = document.createElement('button');
  scanBtn.id = 'jobfill-floating-scan';
  scanBtn.type = 'button';
  scanBtn.className = 'jf-toolbar-btn';
  scanBtn.title = 'Keyword match vs your profile';
  scanBtn.textContent = 'Scan';

  const toolbar = document.createElement('div');
  toolbar.className = 'jf-toolbar';
  toolbar.appendChild(saveBtn);
  toolbar.appendChild(scanBtn);

  const btn = document.createElement('button');
  btn.id = 'jobfill-floating-button';
  btn.type = 'button';
  btn.innerHTML = `<span class="jf-mark">AP</span><span class="jf-label">Autofill</span>`;

  const submitBtn = document.createElement('button');
  submitBtn.id = 'jobfill-floating-submit';
  submitBtn.type = 'button';
  submitBtn.hidden = true;
  submitBtn.tabIndex = -1;

  actionsHost.appendChild(btn);
  actionsHost.appendChild(toolbar);

  const dismiss = document.createElement('button');
  dismiss.id = 'jobfill-floating-dismiss';
  dismiss.type = 'button';
  dismiss.setAttribute('aria-label', 'Dismiss or cancel');
  dismiss.textContent = '×';

  wrapper.appendChild(copilotPanel);
  wrapper.appendChild(toggleBtn);
  wrapper.appendChild(dismiss);

  document.body.appendChild(wrapper);

  const openPanel = () => copilotPanel.classList.add('is-open');
  toggleBtn.addEventListener('click', () => {
    copilotPanel.classList.toggle('is-open');
  });
  openPanel();

  const setJobContext = (ctx: CopilotJobContext) => {
    const roleEl = document.getElementById('jf-job-role');
    const sublineEl = document.getElementById('jf-job-subline');
    const platformEl = document.getElementById('jf-platform-pill');
    const metaRow = document.getElementById('jf-meta-row');
    if (roleEl) roleEl.textContent = ctx.role?.trim() || 'Job application';
    if (sublineEl) {
      const parts = [ctx.company?.trim(), ctx.location?.trim()].filter(Boolean);
      sublineEl.textContent = parts.join(' · ') || 'Unknown company';
    }
    if (platformEl) platformEl.textContent = ctx.platform?.trim() || 'ATS';
    if (metaRow) renderMetaPills(metaRow, ctx.enrichment, ctx.h1b);
  };

  let pipelineStatus: TrackerPipelineStatus = 'saved';
  let statReady = 0;
  let statFilled: number | undefined;
  let statMatch = '—';

  const refreshInlineStat = () => {
    const el = document.getElementById('jf-inline-stat');
    if (!el) return;
    if (statReady <= 0 && statMatch === '—') {
      el.textContent = 'Auto-tracks when you submit';
      return;
    }
    const filledLabel = statFilled != null && statFilled >= 0 ? String(statFilled) : '—';
    el.textContent = `${statReady > 0 ? statReady : '—'} fields · ${filledLabel} filled · ${statMatch} match`;
  };

  const pipelineSelect = document.getElementById('jf-pipeline-select') as HTMLSelectElement | null;
  pipelineSelect?.addEventListener('change', () => {
    pipelineStatus = (pipelineSelect.value as TrackerPipelineStatus) || 'saved';
  });

  const setPipelineStatus = (status: TrackerPipelineStatus) => {
    pipelineStatus = status;
    if (pipelineSelect) pipelineSelect.value = status;
  };

  const setSaveJobState = (state: SaveJobWidgetState, label?: string) => {
    applySaveJobState(saveBtn, state, label);
  };

  const setAutofillVisible = (visible: boolean) => {
    btn.style.display = visible ? '' : 'none';
    actionsHost.classList.toggle('is-listing', !visible);
  };

  const setFieldStats = (ready: number, filled?: number) => {
    statReady = ready;
    statFilled = filled;
    refreshInlineStat();
  };

  const setProgress = (percent: number | null) => {
    const track = document.getElementById('jf-progress');
    const bar = document.getElementById('jf-progress-bar');
    if (!track || !bar) return;
    if (percent == null) {
      track.classList.remove('is-visible');
      bar.style.width = '0%';
      return;
    }
    track.classList.add('is-visible');
    bar.style.width = `${Math.max(0, Math.min(100, percent))}%`;
  };

  let clickHandler: (() => void | Promise<void>) | null = null;
  btn.addEventListener('click', () => {
    if (btn.disabled || !clickHandler) return;
    void clickHandler();
  });

  const setInsights = (html: string | null, tone: 'warn' | 'info' = 'warn') => {
    const el = document.getElementById('jf-insights');
    if (!el) return;
    if (!html) {
      el.hidden = true;
      el.innerHTML = '';
      el.classList.remove('is-info');
      return;
    }
    el.hidden = false;
    el.innerHTML = html;
    el.classList.toggle('is-info', tone === 'info');
  };

  const setMatchScore = (score: number | null) => {
    statMatch = score == null ? '—' : `${score}%`;
    refreshInlineStat();
  };

  const showScanResult = (result: { score: number; matched: string[]; missing: string[] }) => {
    setMatchScore(result.score);
    const summary = document.getElementById('jobfill-scan-summary');
    const tags = document.getElementById('jobfill-scan-tags');
    if (summary) {
      summary.textContent = `${result.score}% profile overlap · ${result.matched.length} matched, ${result.missing.length} gaps`;
    }
    if (tags) {
      tags.innerHTML = '';
      for (const word of result.matched) {
        const tag = document.createElement('span');
        tag.className = 'jf-scan-tag';
        tag.textContent = word;
        tags.appendChild(tag);
      }
      for (const word of result.missing) {
        const tag = document.createElement('span');
        tag.className = 'jf-scan-tag is-missing';
        tag.textContent = word;
        tags.appendChild(tag);
      }
    }
    scanPanel?.classList.add('is-visible');
  };

  const hideScanResult = () => {
    document.getElementById('jobfill-scan-panel')?.classList.remove('is-visible');
  };

  const scanPanel = document.getElementById('jobfill-scan-panel');
  const skippedPanel = document.getElementById('jobfill-skipped-panel');
  const errorPanel = document.getElementById('jobfill-error-panel');

  let scanHandler: (() => void | Promise<void>) | null = null;
  scanBtn.addEventListener('click', (event) => {
    event.stopPropagation();
    if (scanBtn.disabled || !scanHandler) return;
    void scanHandler();
  });

  let saveJobHandler: ((status: TrackerPipelineStatus) => void | Promise<void>) | null = null;
  saveBtn.addEventListener('click', (event) => {
    event.stopPropagation();
    if (saveBtn.disabled || !saveJobHandler) return;
    void saveJobHandler(pipelineStatus);
  });

  let submitHandler: (() => void | Promise<void>) | null = null;
  submitBtn.addEventListener('click', (event) => {
    event.stopPropagation();
    if (submitBtn.disabled || !submitHandler) return;
    void submitHandler();
  });

  let dismissHandler: (() => void) | null = null;
  dismiss.addEventListener('click', (e) => {
    e.stopPropagation();
    if (dismissHandler) {
      dismissHandler();
      return;
    }
    wrapper.remove();
  });

  return {
    setState: (state, label) => applyWidgetState(btn, state, label),
    setDisabled: (disabled) => btn.toggleAttribute('disabled', disabled),
    setAutofillVisible,
    setSubmitDisabled: (disabled) => submitBtn.toggleAttribute('disabled', disabled),
    showSubmitTracked: (info) => applySubmitTracked(pipelineSelect, info),
    lockSubmitButton: () => lockSubmitButton(submitBtn),
    resetSubmitButton: () => resetSubmitButton(submitBtn),
    setJobContext,
    setFieldStats,
    setProgress,
    setPipelineStatus,
    setSaveJobState,
    setMatchScore,
    setInsights,
    showScanResult,
    hideScanResult,
    openPanel,
    onClick: (handler) => {
      clickHandler = handler;
    },
    onSaveJob: (handler) => {
      saveJobHandler = handler;
    },
    onScan: (handler) => {
      scanHandler = handler;
    },
    onQueue: () => {
      /* queue lives in popup in v3 */
    },
    onSubmit: (handler) => {
      submitHandler = handler;
    },
    onDismiss: (handler) => {
      dismissHandler = handler;
    },
    showSkippedFields: (fields, summary) => renderSkippedFieldsPanel(skippedPanel, fields, summary),
    hideSkippedFields: () => skippedPanel?.classList.remove('is-visible'),
    showError: (message) => renderErrorPanel(errorPanel, message),
    hideError: () => errorPanel?.classList.remove('is-visible')
  };
}

function renderMetaPills(
  container: HTMLElement,
  enrichment?: JobPageEnrichment,
  h1b?: H1bSponsorshipResult
): void {
  container.innerHTML = '';
  const pills: HTMLElement[] = [];

  if (h1b) {
    const pill = document.createElement('span');
    pill.className = 'jf-meta-pill is-h1b';
    pill.textContent = h1b.label;
    pill.style.backgroundColor = h1bStatusColor(h1b.status);
    pill.title = h1b.signals.length ? h1b.signals.join(' · ') : h1b.reason;
    pills.push(pill);
  }

  if (enrichment?.salary) {
    const pill = document.createElement('span');
    pill.className = 'jf-meta-pill';
    pill.textContent =
      enrichment.salary.length > 22 ? `${enrichment.salary.slice(0, 21)}…` : enrichment.salary;
    pill.title = enrichment.salary;
    pills.push(pill);
  } else if (enrichment) {
    const employmentLabel = employmentTypeLabel(enrichment.employmentType);
    if (employmentLabel) {
      const pill = document.createElement('span');
      pill.className = 'jf-meta-pill is-employment';
      pill.textContent = employmentLabel;
      pill.style.backgroundColor = employmentTypeColor(enrichment.employmentType);
      pills.push(pill);
    }
  }

  for (const pill of pills.slice(0, 2)) {
    container.appendChild(pill);
  }
}

function applySaveJobState(
  btn: HTMLButtonElement | null,
  state: SaveJobWidgetState,
  label?: string
): void {
  if (!btn) return;
  btn.classList.remove('is-saved', 'is-duplicate');
  btn.removeAttribute('disabled');

  switch (state) {
    case 'parsing':
      btn.setAttribute('disabled', 'true');
      btn.textContent = label || '…';
      break;
    case 'saving':
      btn.setAttribute('disabled', 'true');
      btn.textContent = label || '…';
      break;
    case 'saved':
      btn.classList.add('is-saved');
      btn.textContent = label || 'Saved ✓';
      break;
    case 'duplicate':
      btn.classList.add('is-duplicate', 'is-saved');
      btn.textContent = label || 'Saved';
      break;
    default:
      btn.textContent = 'Save';
  }
}

function renderSkippedFieldsPanel(
  panel: HTMLElement | null,
  fields: AutofillSkippedFieldRef[],
  summary?: string
): void {
  if (!panel) return;

  const list = panel.querySelector('#jobfill-skipped-list');
  const summaryEl = panel.querySelector('#jobfill-skipped-summary') as HTMLElement | null;
  if (!list) return;

  list.innerHTML = '';
  if (!fields.length) {
    panel.classList.remove('is-visible');
    if (summaryEl) summaryEl.textContent = '';
    return;
  }

  if (summaryEl) {
    summaryEl.textContent = summary || `${fields.length} field${fields.length === 1 ? '' : 's'} were not filled. Tap to jump.`;
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

function renderErrorPanel(panel: HTMLElement | null, message: string): void {
  if (!panel) return;

  const messageEl = panel.querySelector('#jobfill-error-message');
  if (messageEl) {
    messageEl.textContent = message;
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

function applySubmitTracked(
  pipelineSelect: HTMLSelectElement | null,
  info: SubmitTrackedInfo
): void {
  if (pipelineSelect) {
    pipelineSelect.value = 'submitted';
    pipelineSelect.disabled = true;
  }
  const inline = document.getElementById('jf-inline-stat');
  if (inline) {
    inline.textContent = `Applied · ${truncateLabel(info.company || 'Company', 14)} · ${formatSubmitDate(info.submittedAt)}`;
  }
}

function lockSubmitButton(_btn: HTMLButtonElement | null): void {
  const pipelineSelect = document.getElementById('jf-pipeline-select') as HTMLSelectElement | null;
  if (pipelineSelect) pipelineSelect.disabled = true;
}

function resetSubmitButton(_btn: HTMLButtonElement | null): void {
  /* no visible submit control in v3 */
}

function applyWidgetState(btn: HTMLButtonElement | null, state: WidgetState, label: string): void {
  if (!btn) return;
  btn.classList.remove('is-loading', 'is-success', 'is-warning', 'is-error');
  if (state === 'loading') btn.classList.add('is-loading');
  if (state === 'success') btn.classList.add('is-success');
  if (state === 'warning') btn.classList.add('is-warning');
  if (state === 'error') btn.classList.add('is-error');

  const mark = btn.querySelector('.jf-mark');
  const labelEl = btn.querySelector('.jf-label');
  if (labelEl) labelEl.textContent = label;
  if (!mark) return;

  if (state === 'idle') mark.innerHTML = 'AP';
  else if (state === 'loading') mark.innerHTML = '';
  else if (state === 'success') mark.innerHTML = '✓';
  else if (state === 'warning') mark.innerHTML = '!';
  else if (state === 'error') mark.innerHTML = '✕';
}
