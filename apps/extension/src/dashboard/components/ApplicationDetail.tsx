import React, { useState, useEffect } from 'react';
import { getApplications, saveApplication, Application } from '../../db/repositories/applicationRepository';
import { getAutofillSessions, AutofillSession } from '../../db/repositories/autofillSessionRepository';
import { getFieldMappings, FieldMapping } from '../../db/repositories/fieldMappingRepository';
import { getJobs, Job } from '../../db/repositories/jobRepository';
import { logChronicle as logActivityEvent, Chronicle as ActivityEvent } from '../../db/repositories/chronicleRepository';

interface ApplicationDetailProps {
  applicationId: string;
  onBack: () => void;
}

export function ApplicationDetail({ applicationId, onBack }: ApplicationDetailProps) {
  const [app, setApp] = useState<Application | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [sessions, setSessions] = useState<AutofillSession[]>([]);
  const [mappings, setMappings] = useState<FieldMapping[]>([]);
  const [notes, setNotes] = useState('');
  const [followUpDate, setFollowUpDate] = useState('');

  useEffect(() => {
    loadDetails();
  }, [applicationId]);

  const loadDetails = async () => {
    const apps = await getApplications();
    const currentApp = apps.find(a => a.id === applicationId);
    if (currentApp) {
      setApp(currentApp);
      setNotes(currentApp.notes || '');
      setFollowUpDate(currentApp.nextFollowUpAt || '');

      const allJobs = await getJobs();
      const currentJob = allJobs.find(j => j.id === currentApp.jobId);
      if (currentJob) setJob(currentJob);

      const allSessions = await getAutofillSessions();
      setSessions(allSessions.filter(s => s.applicationId === applicationId));

      const allMappings = await getFieldMappings();
      setMappings(allMappings.filter(m => m.applicationId === applicationId));
    }
  };

  const handleSaveNotes = async () => {
    if (app) {
      const updated = {
        ...app,
        notes,
        nextFollowUpAt: followUpDate || undefined
      };
      await saveApplication(updated);
      await logActivityEvent({
        applicationId,
        type: 'note_added',
        message: 'Updated application notes and follow-up reminder'
      });
      alert('Notes and follow-up saved!');
    }
  };

  if (!app) {
    return <div className="empty-state">Loading application details...</div>;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
        <button className="btn btn-secondary" onClick={onBack} style={{ flex: 'none', width: 'fit-content' }}>← Back</button>
        <h1 style={{ fontSize: '1.8rem', fontWeight: 600, margin: 0 }}>{app.companyName}</h1>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 300px', gap: '20px' }}>
        {/* Main Column */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {/* Job Details Card */}
          <div className="review-card" style={{ padding: '20px' }}>
            <h2>{app.roleTitle}</h2>
            <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '4px' }}>
              📍 {app.location || 'Remote'} | 💻 Platform: {job?.sourcePlatform || 'Generic'}
            </p>
            {job?.jobUrl && (
              <a href={job.jobUrl} target="_blank" rel="noreferrer" className="btn btn-primary" style={{ marginTop: '12px', width: 'fit-content', textDecoration: 'none', display: 'inline-block', fontSize: '0.8rem' }}>
                Open Job Application URL ↗
              </a>
            )}
          </div>

          {/* Field Mappings Log */}
          <div className="review-card" style={{ padding: '20px' }}>
            <h3>Autofill History Mappings</h3>
            <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: '12px' }}>Review answers previously filled on this application.</p>

            <div className="table-container">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Field Label</th>
                    <th>canonical Key</th>
                    <th>Value Filled</th>
                    <th>Confidence</th>
                    <th>Source</th>
                  </tr>
                </thead>
                <tbody>
                  {mappings.length === 0 ? (
                    <tr>
                      <td colspan="5" className="empty-table">No mappings stored for this application.</td>
                    </tr>
                  ) : (
                    mappings.map(m => (
                      <tr key={m.id}>
                        <td>{m.rawLabel}</td>
                        <td><span className="badge badge-needs-answer" style={{ fontSize: '0.65rem' }}>{m.canonicalKey || 'custom'}</span></td>
                        <td><code>{m.finalValue || m.proposedValue}</code></td>
                        <td>{m.confidence ? `${Math.round(m.confidence * 100)}%` : '-'}</td>
                        <td>{m.source}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Sessions List */}
          <div className="review-card" style={{ padding: '20px' }}>
            <h3>Autofill Sessions</h3>
            <div className="table-container">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Session Date</th>
                    <th>Fields Scanned</th>
                    <th>Fields Filled</th>
                    <th>Confidence Alert Count</th>
                    <th>Action State</th>
                  </tr>
                </thead>
                <tbody>
                  {sessions.length === 0 ? (
                    <tr>
                      <td colspan="5" className="empty-table">No sessions recorded yet.</td>
                    </tr>
                  ) : (
                    sessions.map(s => (
                      <tr key={s.id}>
                        <td>{new Date(s.startedAt).toLocaleString()}</td>
                        <td>{s.fieldsDetected}</td>
                        <td>{s.fieldsFilled}</td>
                        <td>{s.lowConfidenceCount}</td>
                        <td><span className="badge badge-high">{s.finalAction}</span></td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* Sidebar Column */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {/* Status Preferences */}
          <div className="review-card" style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <h3>Application Meta</h3>
            
            <div className="form-group">
              <label>Status</label>
              <select
                value={app.status}
                onChange={async (e) => {
                  const updated = { ...app, status: e.target.value as Application['status'] };
                  await saveApplication(updated);
                  await logActivityEvent({
                    applicationId,
                    type: 'status_changed',
                    message: `Status updated to ${e.target.value}`
                  });
                  await loadDetails();
                }}
              >
                <option value="saved">Saved</option>
                <option value="parsed">Parsed</option>
                <option value="autofilled">Autofilled</option>
                <option value="ready_to_submit">Ready to Submit</option>
                <option value="submitted">Submitted</option>
                <option value="interviewing">Interviewing</option>
                <option value="offer">Offer</option>
                <option value="rejected">Rejected</option>
                <option value="withdrawn">Withdrawn</option>
              </select>
            </div>

            <div className="form-group">
              <label>Priority</label>
              <select
                value={app.priority}
                onChange={async (e) => {
                  const updated = { ...app, priority: e.target.value as Application['priority'] };
                  await saveApplication(updated);
                  await loadDetails();
                }}
              >
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
            </div>
          </div>

          {/* Follow ups & Notes */}
          <div className="review-card" style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <h3>Tracker Notes</h3>
            <div className="form-group">
              <label for="detail-followup">Next Follow-up Date</label>
              <input
                type="date"
                id="detail-followup"
                value={followUpDate}
                onChange={(e) => setFollowUpDate(e.target.value)}
              />
            </div>

            <div className="form-group">
              <label for="detail-notes">Tracker Log / Notes</label>
              <textarea
                id="detail-notes"
                rows={5}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Log interviews, contact recruiter name..."
              />
            </div>

            <button className="btn btn-save" onClick={handleSaveNotes}>Save Notes & Date</button>
          </div>
        </div>
      </div>
    </div>
  );
}
