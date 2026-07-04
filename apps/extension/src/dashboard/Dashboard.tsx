import '../shared/process-shim';
import React, { useState, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { computeDashboardMetrics, DashboardMetrics } from '../db/selectors/dashboardSelectors';
import { getApplications, saveApplication, deleteApplication, Application } from '../db/repositories/applicationRepository';
import { getLearnedAnswers, deleteLearnedAnswer, LearnedAnswer } from '../db/repositories/learnedAnswerRepository';
import { getDocuments, DocumentRecord } from '../db/repositories/documentRepository';
import { getJobs } from '../db/repositories/jobRepository';
import { getAutofillSessions } from '../db/repositories/autofillSessionRepository';
import { getFieldMappings } from '../db/repositories/fieldMappingRepository';
import { PipelineBoard } from './components/PipelineBoard';
import { ApplicationsTable } from './components/ApplicationsTable';
import { ApplicationDetail } from './components/ApplicationDetail';
import { LearningCenter } from '../learning/LearningCenter';
import { DocumentsCenter } from '../documents/DocumentsCenter';
import { syncFromServer } from '../db/sync';
import { ProfileCenter } from '../profile/ProfileCenter';
import { Portal } from '../portal/Portal';

type ViewMode = 'dashboard' | 'profile' | 'applications' | 'learning' | 'documents' | 'settings' | 'detail' | 'station';

function viewFromHash(): ViewMode {
  const hash = window.location.hash.replace('#', '');
  if (hash === 'profile') return 'profile';
  if (hash === 'applications') return 'applications';
  if (hash === 'learning') return 'learning';
  if (hash === 'documents') return 'documents';
  if (hash === 'settings') return 'settings';
  if (hash === 'station') return 'station';
  return 'dashboard';
}

export function Dashboard() {
  const [activeView, setActiveView] = useState<ViewMode>(viewFromHash);
  const [syncReady, setSyncReady] = useState(false);
  const [metrics, setMetrics] = useState<DashboardMetrics | null>(null);
  const [applications, setApplications] = useState<Application[]>([]);
  const [selectedAppId, setSelectedAppId] = useState<string | null>(null);

  useEffect(() => {
    const onHashChange = () => setActiveView(viewFromHash());
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  useEffect(() => {
    loadData();
  }, [activeView]);

  const navigateTo = (view: ViewMode) => {
    setActiveView(view);
    const hash = view === 'dashboard' ? '' : `#${view}`;
    if (window.location.hash !== hash) {
      window.location.hash = hash;
    }
  };

  const loadData = async () => {
    await syncFromServer();
    setSyncReady(true);
    const apps = await getApplications();
    const m = await computeDashboardMetrics();
    setMetrics(m);
    setApplications(apps);
  };

  const handleSelectApp = (id: string) => {
    setSelectedAppId(id);
    setActiveView('detail');
  };

  const handleUpdateStatus = async (id: string, newStatus: Application['status']) => {
    const app = applications.find(a => a.id === id);
    if (app) {
      await saveApplication({ ...app, status: newStatus });
      await loadData();
    }
  };

  const handleDeleteApp = async (id: string) => {
    if (confirm('Delete this application record?')) {
      await deleteApplication(id);
      await loadData();
      if (selectedAppId === id) setSelectedAppId(null);
    }
  };

  const handleClearAll = async () => {
    if (confirm('CAUTION: This will wipe out your local dashboard database! Continue?')) {
      indexedDB.deleteDatabase('arsenal_jobfill_db');
      alert('Database cleared. Reloading dashboard.');
      window.location.reload();
    }
  };

  const handleExportAll = async () => {
    const dbData = {
      applications: await getApplications(),
      jobs: await getJobs(),
      learnedAnswers: await getLearnedAnswers(),
      documents: await getDocuments(),
      sessions: await getAutofillSessions(),
      fieldMappings: await getFieldMappings()
    };
    const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(dbData, null, 2));
    const dl = document.createElement('a');
    dl.setAttribute('href', dataStr);
    dl.setAttribute('download', 'jobfill_dashboard_export.json');
    dl.click();
    dl.remove();
  };

  const handleImportAll = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = async (event) => {
      try {
        const data = JSON.parse(event.target?.result as string);
        // Simple verification
        if (data.applications || data.learnedAnswers) {
          // Put inside IndexedDB
          const request = indexedDB.open('arsenal_jobfill_db', 1);
          request.onsuccess = () => {
            const db = request.result;
            const tx = db.transaction(db.objectStoreNames, 'readwrite');
            if (data.applications) data.applications.forEach((a: any) => tx.objectStore('applications').put(a));
            if (data.jobs) data.jobs.forEach((j: any) => tx.objectStore('jobs').put(j));
            if (data.learnedAnswers) data.learnedAnswers.forEach((la: any) => tx.objectStore('learnedAnswers').put(la));
            if (data.documents) data.documents.forEach((d: any) => tx.objectStore('documents').put(d));
            tx.oncomplete = () => {
              alert('Import completed successfully!');
              loadData();
            };
          };
        } else {
          alert('Invalid export file format.');
        }
      } catch (err) {
        alert('Failed to parse JSON file.');
      }
    };
    reader.readAsText(file);
  };

  return (
    <div className="dash-shell">
      <aside className="dash-sidebar">
        <div>
          <div className="dash-brand">
            <div className="dash-logo-mark" aria-hidden="true">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                <rect x="5" y="3" width="14" height="18" rx="2" stroke="currentColor" strokeWidth="2"/>
                <path d="M9 9h6M9 13h6M9 17h4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>
              </svg>
            </div>
            <div>
              <h2>JobFill</h2>
              <div className="dash-brand-sub">Your application workspace</div>
            </div>
          </div>
        </div>

        <nav className="dash-nav">
          <button className={`dash-nav-link ${activeView === 'station' ? 'active' : ''}`} onClick={() => navigateTo('station')}>
            <span className="dash-nav-icon">🧬</span> Station
          </button>
          <button className={`dash-nav-link ${activeView === 'dashboard' ? 'active' : ''}`} onClick={() => navigateTo('dashboard')}>
            <span className="dash-nav-icon">📊</span> Dashboard
          </button>
          <button className={`dash-nav-link ${activeView === 'profile' ? 'active' : ''}`} onClick={() => navigateTo('profile')}>
            <span className="dash-nav-icon">👤</span> Profile
          </button>
          <button className={`dash-nav-link ${activeView === 'applications' ? 'active' : ''}`} onClick={() => navigateTo('applications')}>
            <span className="dash-nav-icon">💼</span> Applications
          </button>
          <button className={`dash-nav-link ${activeView === 'learning' ? 'active' : ''}`} onClick={() => navigateTo('learning')}>
            <span className="dash-nav-icon">🧠</span> Learning
          </button>
          <button className={`dash-nav-link ${activeView === 'documents' ? 'active' : ''}`} onClick={() => navigateTo('documents')}>
            <span className="dash-nav-icon">📄</span> Documents
          </button>
          <button className={`dash-nav-link ${activeView === 'settings' ? 'active' : ''}`} onClick={() => navigateTo('settings')}>
            <span className="dash-nav-icon">⚙️</span> Settings
          </button>
        </nav>
      </aside>

      <main className="dash-main">
        {activeView === 'dashboard' && metrics && (
          <div className="dash-section">
            <div className="dash-page-header">
              <h1>Overview</h1>
              <p>Real-time pipeline metrics for your job search.</p>
            </div>

            <div className="dash-metrics">
              <div className="portal-card dash-metric-card">
                <span className="dash-metric-label">Total apps</span>
                <h2 className="dash-metric-value">{metrics.totalApplications}</h2>
              </div>
              <div className="portal-card dash-metric-card" style={{ borderColor: 'rgba(46, 229, 157, 0.2)' }}>
                <span className="dash-metric-label">Submitted</span>
                <h2 className="dash-metric-value" style={{ color: 'var(--accent-color)' }}>{metrics.submittedCount}</h2>
              </div>
              <div className="portal-card dash-metric-card" style={{ borderColor: 'rgba(20, 184, 166, 0.2)' }}>
                <span className="dash-metric-label">Interviews</span>
                <h2 className="dash-metric-value" style={{ color: '#14b8a6' }}>{metrics.interviewCount}</h2>
              </div>
              <div className="portal-card dash-metric-card" style={{ borderColor: 'rgba(192, 132, 252, 0.2)' }}>
                <span className="dash-metric-label">Response rate</span>
                <h2 className="dash-metric-value" style={{ color: '#c084fc' }}>{metrics.responseRate}%</h2>
              </div>
              <div className="portal-card dash-metric-card" style={{ borderColor: 'rgba(255, 107, 107, 0.2)' }}>
                <span className="dash-metric-label">Follow-ups</span>
                <h2 className="dash-metric-value" style={{ color: '#ff6b6b' }}>{metrics.followUpsDue}</h2>
              </div>
            </div>

            <div className="portal-card" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <h3 className="dash-section-title">Pipeline conversion funnel</h3>
              
              <div style={{ display: 'flex', width: '100%', height: '10px', borderRadius: '5px', overflow: 'hidden', background: 'rgba(255,255,255,0.03)' }}>
                <div style={{ flex: metrics.totalApplications ? Math.max(1, applications.filter(a => a.status === 'saved').length) : 1, background: 'rgba(255,255,255,0.1)' }} title="Saved"></div>
                <div style={{ flex: metrics.totalApplications ? Math.max(1, applications.filter(a => a.status === 'autofilled' || a.status === 'parsed').length) : 1, background: 'rgba(20, 184, 166, 0.3)' }} title="Autofilled"></div>
                <div style={{ flex: metrics.totalApplications ? Math.max(1, metrics.submittedCount) : 1, background: 'rgba(46, 229, 157, 0.5)' }} title="Submitted"></div>
                <div style={{ flex: metrics.totalApplications ? Math.max(1, metrics.interviewCount) : 1, background: '#14b8a6' }} title="Interviewing"></div>
                <div style={{ flex: metrics.totalApplications ? Math.max(1, applications.filter(a => a.status === 'offer').length) : 1, background: 'var(--accent-color)' }} title="Offers"></div>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'var(--text-muted)', flexWrap: 'wrap', gap: '8px' }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <span style={{ display: 'inline-block', width: '8px', height: '8px', borderRadius: '50%', background: 'rgba(255,255,255,0.2)' }}></span> 
                  Saved ({applications.filter(a => a.status === 'saved').length})
                </span>
                <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <span style={{ display: 'inline-block', width: '8px', height: '8px', borderRadius: '50%', background: 'rgba(20, 184, 166, 0.3)' }}></span> 
                  Autofilled ({applications.filter(a => a.status === 'autofilled' || a.status === 'parsed').length})
                </span>
                <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <span style={{ display: 'inline-block', width: '8px', height: '8px', borderRadius: '50%', background: 'rgba(46, 229, 157, 0.5)' }}></span> 
                  Submitted ({metrics.submittedCount})
                </span>
                <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <span style={{ display: 'inline-block', width: '8px', height: '8px', borderRadius: '50%', background: '#14b8a6' }}></span> 
                  Interviewing ({metrics.interviewCount})
                </span>
                <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <span style={{ display: 'inline-block', width: '8px', height: '8px', borderRadius: '50%', background: 'var(--accent-color)' }}></span> 
                  Offers ({applications.filter(a => a.status === 'offer').length})
                </span>
              </div>
            </div>

            {/* Kanban Pipeline Board */}
            <PipelineBoard applications={applications} onUpdateStatus={handleUpdateStatus} onSelectApp={handleSelectApp} />
          </div>
        )}

        {activeView === 'applications' && (
          <ApplicationsTable applications={applications} onSelectApp={handleSelectApp} onUpdateStatus={handleUpdateStatus} onDeleteApp={handleDeleteApp} />
        )}

        {activeView === 'detail' && selectedAppId && (
          <ApplicationDetail applicationId={selectedAppId} onBack={() => setActiveView('applications')} />
        )}

        {activeView === 'learning' && (
          <LearningCenter />
        )}

        {activeView === 'documents' && (
          <DocumentsCenter />
        )}

        {activeView === 'station' && (
          <Portal />
        )}

        {activeView === 'profile' && syncReady && (
          <ProfileCenter />
        )}
        {activeView === 'profile' && !syncReady && (
          <div className="empty-state" style={{ margin: '40px 0' }}>
            <div className="spinner"></div>
            <p className="empty-title">Loading profile…</p>
          </div>
        )}

        {activeView === 'settings' && (
          <div className="dash-section" style={{ maxWidth: '600px' }}>
            <div className="dash-page-header">
              <h1>Settings</h1>
              <p>Backup, restore, and manage local data.</p>
            </div>
            <div className="review-card" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <h3>Backup & Restore</h3>
              <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Export all your local tracker details, resumes variants history, and learned memories to a single JSON backup file.</p>
              
              <div style={{ display: 'flex', gap: '12px' }}>
                <button className="btn btn-primary" onClick={handleExportAll}>Export Tracker Data</button>
                <label className="btn btn-secondary" style={{ display: 'inline-block', cursor: 'pointer' }}>
                  Import Backup JSON
                  <input type="file" accept=".json" onChange={handleImportAll} style={{ display: 'none' }} />
                </label>
              </div>
            </div>

            <div className="review-card" style={{ padding: '20px', border: '1px solid var(--error-color)', display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <h3 style={{ color: 'var(--error-color)' }}>Dangerous Actions</h3>
              <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Wipe out the entire local IndexedDB database. This action is irreversible.</p>
              <button className="btn btn-danger" onClick={handleClearAll} style={{ width: 'fit-content' }}>Wipe Dashboard Database</button>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

// Mount React Root
const rootEl = document.getElementById('root');
if (rootEl) {
  createRoot(rootEl).render(<Dashboard />);
}
