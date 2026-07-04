import React, { useState } from 'react';

const DIST_PATH = 'CareerOS/apps/extension/dist';

type GettingStartedGuideProps = {
  onCopyPath?: () => void;
};

export function GettingStartedGuide({ onCopyPath }: GettingStartedGuideProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    void navigator.clipboard.writeText(DIST_PATH);
    setCopied(true);
    onCopyPath?.();
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <section className="portal-card guide-panel">
      <h2 className="station-section-title">🚀 Getting started</h2>

      <div className="guide-steps">
        <div className="guide-step">
          <div className="guide-step-num">1</div>
          <div className="guide-step-body">
            <h3>Load the Chrome extension</h3>
            <p>
              Open <code>chrome://extensions/</code>, enable <strong>Developer mode</strong>, click{' '}
              <strong>Load unpacked</strong>, and select your build folder:
            </p>
            <div className="path-box">
              <code>{DIST_PATH}</code>
              <button type="button" onClick={handleCopy} className="btn btn-sm" style={{
                flexShrink: 0,
                flex: 'none',
                background: copied ? 'var(--accent-color)' : 'rgba(255,255,255,0.06)',
                color: copied ? '#042f1e' : 'var(--text-primary)'
              }}>
                {copied ? 'Copied!' : 'Copy path'}
              </button>
            </div>
          </div>
        </div>

        <div className="guide-step">
          <div className="guide-step-num">2</div>
          <div className="guide-step-body">
            <h3>Configure your profile</h3>
            <p>
              Add contact details, links, work authorization, and upload your default resume in the profile editor.
            </p>
            <a href="dashboard.html#profile" className="btn btn-primary btn-sm" style={{ marginTop: 12, display: 'inline-flex', textDecoration: 'none', width: 'fit-content' }}>
              Open profile editor ↗
            </a>
          </div>
        </div>

        <div className="guide-step">
          <div className="guide-step-num">3</div>
          <div className="guide-step-body">
            <h3>Test autofill on a live job</h3>
            <p>Open a job application form, click the extension icon, review mapped fields, then autofill.</p>
            <a
              href="https://www.coupang.jobs/en/jobs/7893001/staff-engineer-backend-post-purchase-experience/?gh_jid=7893001&gh_src=lqh6ahne1us"
              target="_blank"
              rel="noreferrer"
              className="guide-link"
            >
              Coupang Staff Engineer (Greenhouse) ↗
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}
