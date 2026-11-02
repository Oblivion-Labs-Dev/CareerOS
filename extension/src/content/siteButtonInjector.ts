/**
 * Jobscan-style inline Save + Scan buttons injected on Indeed, LinkedIn, Glassdoor, Handshake.
 */

import { getInjectionTargetSelector, matchJobSite, parseFromJobSite, SiteParsedJob } from '../shared/jobSiteSelectors';

const INJECTOR_STYLES = `
#applypilot-site-buttons {
  all: unset;
  display: inline-flex;
  font-family: 'Outfit', 'Segoe UI', system-ui, sans-serif;
  border-radius: 40px;
  overflow: hidden;
  box-shadow: 0 4px 16px rgba(34, 211, 238, 0.2);
  margin-left: 12px;
  vertical-align: middle;
}

#applypilot-site-buttons .ap-site-btn {
  all: unset;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #041016;
  font-size: 14px;
  font-weight: 700;
  background: linear-gradient(135deg, #22d3ee 0%, #06b6d4 100%);
  padding: 8px 14px;
  cursor: pointer;
  white-space: nowrap;
  box-sizing: border-box;
}

#applypilot-site-buttons .ap-site-btn:hover:not(:disabled) {
  filter: brightness(1.05);
}

#applypilot-site-buttons .ap-site-btn:disabled {
  opacity: 0.6;
  cursor: wait;
}

#applypilot-site-buttons .ap-site-btn--save {
  border-right: 1px solid rgba(4, 16, 22, 0.12);
}

#applypilot-site-buttons .ap-site-btn--scan {
  background: linear-gradient(135deg, #7c3aed 0%, #6d28d9 100%);
  color: #f5f3ff;
}

#applypilot-site-buttons.style-indeed { border-radius: 8px; margin-left: 16px; }
#applypilot-site-buttons.style-glassdoor { border-radius: 3px; }
#applypilot-site-buttons.style-handshake { border-radius: 40px; }
`;

export interface SiteButtonHandlers {
  onSave: (job: SiteParsedJob) => void | Promise<void>;
  onScan: (job: SiteParsedJob) => void | Promise<void>;
}

let observer: MutationObserver | null = null;
let injected = false;

function ensureStyles(): void {
  if (document.getElementById('applypilot-site-button-styles')) return;
  const style = document.createElement('style');
  style.id = 'applypilot-site-button-styles';
  style.textContent = INJECTOR_STYLES;
  document.head.appendChild(style);
}

function createButtons(handlers: SiteButtonHandlers): HTMLElement | null {
  const parsed = parseFromJobSite(document);
  const site = matchJobSite(document.location.href);
  if (!parsed || !site) return null;

  const wrapper = document.createElement('div');
  wrapper.id = 'applypilot-site-buttons';
  wrapper.classList.add(`style-${site.style}`);

  const saveBtn = document.createElement('button');
  saveBtn.type = 'button';
  saveBtn.className = 'ap-site-btn ap-site-btn--save';
  saveBtn.textContent = 'Save job';
  saveBtn.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    void handlers.onSave(parseFromJobSite(document) || parsed);
  });

  const scanBtn = document.createElement('button');
  scanBtn.type = 'button';
  scanBtn.className = 'ap-site-btn ap-site-btn--scan';
  scanBtn.textContent = 'Scan';
  scanBtn.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    void handlers.onScan(parseFromJobSite(document) || parsed);
  });

  wrapper.appendChild(saveBtn);
  wrapper.appendChild(scanBtn);
  return wrapper;
}

function injectButtons(handlers: SiteButtonHandlers): void {
  if (injected || document.getElementById('applypilot-site-buttons')) {
    injected = true;
    return;
  }

  const targetSelector = getInjectionTargetSelector(document);
  if (!targetSelector) return;

  const target = document.querySelector(targetSelector);
  if (!target) return;

  const buttons = createButtons(handlers);
  if (!buttons) return;

  ensureStyles();

  const site = matchJobSite(document.location.href);
  if (site?.style === 'linkedin') {
    const container = target.closest('div') || target.parentElement;
    container?.appendChild(buttons);
  } else {
    target.after(buttons);
  }

  injected = true;
}

export function initSiteButtonInjector(handlers: SiteButtonHandlers): () => void {
  if (!matchJobSite(document.location.href)) {
    return () => {};
  }

  const attempt = () => injectButtons(handlers);
  attempt();

  if (observer) observer.disconnect();
  observer = new MutationObserver(() => attempt());
  if (document.body) {
    observer.observe(document.body, { childList: true, subtree: true });
  }

  return () => {
    observer?.disconnect();
    observer = null;
    document.getElementById('applypilot-site-buttons')?.remove();
    injected = false;
  };
}

export function resetSiteButtonInjector(): void {
  injected = false;
  document.getElementById('applypilot-site-buttons')?.remove();
}
