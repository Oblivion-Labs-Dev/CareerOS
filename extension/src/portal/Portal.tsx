import '../shared/process-shim';
import React, { useState, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { getApplications } from '../db/repositories/applicationRepository';
import { getLearnedAnswers } from '../db/repositories/learnedAnswerRepository';
import { syncFromServer } from '../db/sync';
import { getProfile } from '../profile/profileStore';
import { PortalHeader } from './components/PortalHeader';
import { GettingStartedGuide } from './components/GettingStartedGuide';
import { InstrumentCard } from './components/InstrumentCard';

export function Portal() {
  const [appCount, setAppCount] = useState(0);
  const [memoryCount, setMemoryCount] = useState(0);
  const [serverOnline, setServerOnline] = useState(false);
  const [missingFields, setMissingFields] = useState<string[]>([]);

  useEffect(() => {
    void loadCounts();
  }, []);

  const loadCounts = async () => {
    const synced = await syncFromServer();
    setServerOnline(synced);
    
    const apps = await getApplications();
    const memories = await getLearnedAnswers();
    setAppCount(apps.length);
    setMemoryCount(memories.length);

    const profile = await getProfile();
    const required: Record<string, string> = {
      firstName: 'First Name',
      lastName: 'Last Name',
      email: 'Email address',
      phone: 'Phone Number',
      location: 'Location',
      linkedin: 'LinkedIn URL'
    };
    const missing: string[] = [];
    if (profile) {
      for (const [key, label] of Object.entries(required)) {
        const value = profile[key as keyof typeof profile];
        if (typeof value !== 'string' || !value.trim()) {
          missing.push(label);
        }
      }
    } else {
      missing.push(...Object.values(required));
    }
    setMissingFields(missing);
  };

  return (
    <div className="station">
      <PortalHeader serverOnline={serverOnline} />

      {missingFields.length > 0 ? (
        <div className="alert-banner" style={{ background: 'rgba(239, 68, 68, 0.08)', border: '1px solid rgba(239, 68, 68, 0.25)', color: '#f87171', display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 600 }}>
            <span>⚠️</span> Profile Setup Incomplete
          </div>
          <p style={{ margin: 0, fontSize: '0.86rem', color: 'rgba(255, 255, 255, 0.7)' }}>
            Autofill will skip fields because the following details are missing from your profile:
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '4px' }}>
            {missingFields.map((f) => (
              <span key={f} style={{ background: 'rgba(239, 68, 68, 0.15)', padding: '4px 10px', borderRadius: '6px', fontSize: '0.78rem', border: '1px solid rgba(239, 68, 68, 0.3)' }}>
                {f}
              </span>
            ))}
          </div>
          <a href="#profile" style={{ color: 'var(--accent-color)', fontSize: '0.84rem', fontWeight: 500, marginTop: '4px', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
            Go to profile editor to complete ↗
          </a>
        </div>
      ) : (
        <div className="alert-banner" style={{ background: 'rgba(16, 185, 129, 0.08)', border: '1px solid rgba(16, 185, 129, 0.25)', color: 'var(--accent-color)', display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 500 }}>
          <span>✅</span> Profile is fully complete and optimized for form autofilling!
        </div>
      )}

      <div className="station-hero">
        <h2>🧬 Automation command center</h2>
        <p>
          ApplyPilot runs locally on your machine. Job applications, learned answers, and profile data
          sync to <code>apps/extension/db.json</code> and the CareerOS API on port 8000.
        </p>
      </div>

      <GettingStartedGuide />

      <section>
        <h2 className="station-section-title">🌱 Active instruments</h2>
        <div className="instruments-grid">
          <InstrumentCard
            icon="⚡"
            name="ApplyPilot"
            subtitle="Chrome MV3 extension"
            description="Autofill job applications, track your pipeline, and build self-learning answer memory across Greenhouse, Lever, and more."
            status="active"
            tags={['Autofill', 'Tracker', 'Self-learning']}
            stats={[
              { label: 'Applications', value: appCount },
              { label: 'Learned answers', value: memoryCount }
            ]}
            primaryAction={{ label: 'Open tracker ↗', href: 'dashboard.html' }}
            secondaryAction={{ label: 'Edit profile', href: 'dashboard.html#profile' }}
          />

          <InstrumentCard
            icon="💬"
            name="Recruiter Sync"
            subtitle="Messaging pipeline"
            description="Sync recruiter threads, extract contacts, and map conversation updates into your application timeline."
            status="soon"
            tags={['LinkedIn', 'Email', 'Timeline']}
            disabledAction="In development"
          />

          <InstrumentCard
            icon="📊"
            name="Pipeline Analytics"
            subtitle="Insights module"
            description="Conversion funnels, response-rate trends, and follow-up reminders across your entire job search."
            status="soon"
            tags={['Metrics', 'Funnel', 'Follow-ups']}
            disabledAction="Planned"
          />
        </div>
      </section>
    </div>
  );
}

const rootEl = document.getElementById('root');
if (rootEl && window.location.pathname.includes('portal.html')) {
  createRoot(rootEl).render(<Portal />);
}
