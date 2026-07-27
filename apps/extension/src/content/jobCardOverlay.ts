/**
 * LinkedIn / Indeed job card overlays — H1B, match, saved badges (FrogHire JobInsight style).
 */

import { checkH1bSponsorship, h1bStatusColor } from '../shared/h1bSponsorshipCheck';
import { scanJobKeywords } from '../shared/jobKeywordScan';
import { UserProfile } from '../shared/types';

const OVERLAY_CLASS = 'applypilot-card-badge';
const CARD_SELECTORS: Record<string, string> = {
  linkedin: '.job-card-container, .jobs-search-results__list-item, li[data-occludable-job-id]',
  indeed: '.job_seen_beacon, .resultContent, .jobsearch-ResultsList > li'
};

const STYLE = `
.${OVERLAY_CLASS}-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 6px;
}
.${OVERLAY_CLASS} {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: 999px;
  font-family: 'Outfit', system-ui, sans-serif;
  line-height: 1.3;
}
.${OVERLAY_CLASS}--match { background: rgba(34,211,238,0.2); color: #0891b2; border: 1px solid rgba(34,211,238,0.35); }
.${OVERLAY_CLASS}--saved { background: rgba(124,58,237,0.15); color: #6d28d9; border: 1px solid rgba(124,58,237,0.3); }
.${OVERLAY_CLASS}--h1b { color: #041016; border: none; }
`;

function ensureStyles(): void {
  if (document.getElementById('applypilot-card-overlay-styles')) return;
  const style = document.createElement('style');
  style.id = 'applypilot-card-overlay-styles';
  style.textContent = STYLE;
  document.head.appendChild(style);
}

function cardText(card: Element): string {
  return (card.textContent || '').replace(/\s+/g, ' ').slice(0, 4000);
}

function injectBadges(card: Element, badges: Array<{ label: string; className: string; title?: string; bg?: string }>): void {
  if (card.querySelector(`.${OVERLAY_CLASS}-wrap`)) return;

  const wrap = document.createElement('div');
  wrap.className = `${OVERLAY_CLASS}-wrap`;

  for (const badge of badges) {
    const span = document.createElement('span');
    span.className = `${OVERLAY_CLASS} ${badge.className}`;
    span.textContent = badge.label;
    if (badge.title) span.title = badge.title;
    if (badge.bg) span.style.backgroundColor = badge.bg;
    wrap.appendChild(span);
  }

  card.appendChild(wrap);
}

let savedUrls = new Set<string>();

async function refreshSavedUrls(): Promise<void> {
  try {
    const res = (await chrome.runtime.sendMessage({ action: 'get-saved-job-urls' })) as {
      urls?: string[];
    };
    savedUrls = new Set((res?.urls || []).map((u) => u.split('?')[0]));
  } catch {
    savedUrls = new Set();
  }
}

function isSavedCard(card: Element): boolean {
  const link = card.querySelector('a[href*="jobs/view"], a[href*="job"], a[href*="viewjob"]') as HTMLAnchorElement | null;
  if (!link?.href) return false;
  return savedUrls.has(link.href.split('?')[0]);
}

export function initJobCardOverlays(profile: UserProfile | null): () => void {
  const host = window.location.hostname;
  const site = /linkedin\.com/i.test(host) ? 'linkedin' : /indeed\.com/i.test(host) ? 'indeed' : null;
  if (!site) return () => {};

  ensureStyles();
  void refreshSavedUrls();

  const decorate = () => {
    const cards = document.querySelectorAll(CARD_SELECTORS[site]);
    for (const card of cards) {
      const text = cardText(card);
      if (!text || text.length < 40) continue;

      const badges: Array<{ label: string; className: string; title?: string; bg?: string }> = [];

      if (isSavedCard(card)) {
        badges.push({ label: 'Saved', className: `${OVERLAY_CLASS}--saved` });
      }

      const h1b = checkH1bSponsorship(text);
      if (h1b.status !== 'unknown') {
        badges.push({
          label: h1b.label,
          className: `${OVERLAY_CLASS}--h1b`,
          title: h1b.signals.join(' · ') || h1b.reason,
          bg: h1bStatusColor(h1b.status)
        });
      }

      if (profile) {
        const scan = scanJobKeywords(text, profile);
        if (scan.score >= 45) {
          badges.push({
            label: `${scan.score}% match`,
            className: `${OVERLAY_CLASS}--match`,
            title: scan.matched.slice(0, 8).join(', ')
          });
        }
      }

      if (badges.length) injectBadges(card, badges);
    }
  };

  decorate();
  const observer = new MutationObserver(() => decorate());
  if (document.body) observer.observe(document.body, { childList: true, subtree: true });

  const refreshInterval = window.setInterval(() => {
    void refreshSavedUrls().then(decorate);
  }, 15000);

  return () => {
    observer.disconnect();
    window.clearInterval(refreshInterval);
    document.querySelectorAll(`.${OVERLAY_CLASS}-wrap`).forEach((el) => el.remove());
  };
}
