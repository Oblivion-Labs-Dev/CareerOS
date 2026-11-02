import React from 'react';
import { Application } from '../../db/repositories/applicationRepository';

interface PipelineBoardProps {
  applications: Application[];
  onUpdateStatus: (id: string, newStatus: Application['status']) => void;
  onSelectApp: (id: string) => void;
}

const COLUMNS: { key: Application['status']; label: string; icon: string }[] = [
  { key: 'saved', label: 'Saved', icon: '🔖' },
  { key: 'parsed', label: 'Parsed', icon: '🔍' },
  { key: 'autofilled', label: 'Autofilled', icon: '⚡' },
  { key: 'ready_to_submit', label: 'Ready to Submit', icon: '✨' },
  { key: 'submitted', label: 'Submitted', icon: '✉️' },
  { key: 'interviewing', label: 'Interviewing', icon: '🧬' },
  { key: 'offer', label: 'Offer', icon: '🎉' },
  { key: 'rejected', label: 'Rejected', icon: '🍂' }
];

export function PipelineBoard({ applications, onSelectApp }: PipelineBoardProps) {
  return (
    <div style={{ display: 'flex', gap: '16px', overflowX: 'auto', paddingBottom: '20px', flex: 1, height: 'calc(100vh - 160px)', minHeight: '520px' }}>
      {COLUMNS.map(col => {
        const colApps = applications.filter(app => app.status === col.key);

        return (
          <div 
            key={col.key} 
            style={{ 
              minWidth: '280px', 
              width: '280px',
              background: 'rgba(10, 20, 16, 0.4)', 
              backdropFilter: 'blur(12px)',
              border: '1px solid rgba(46, 229, 157, 0.05)',
              borderRadius: '16px', 
              padding: '16px 12px', 
              display: 'flex', 
              flexDirection: 'column', 
              gap: '12px',
              boxShadow: '0 8px 32px 0 rgba(0, 0, 0, 0.2)'
            }}
          >
            {/* Column Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(46, 229, 157, 0.1)', paddingBottom: '8px', marginBottom: '4px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ fontSize: '1rem' }}>{col.icon}</span>
                <span style={{ fontWeight: 600, fontSize: '0.88rem', color: 'var(--text-primary)' }}>{col.label}</span>
              </div>
              <span className="badge badge-high" style={{ background: 'rgba(46, 229, 157, 0.08)', color: 'var(--accent-color)', padding: '2px 8px', fontSize: '0.72rem' }}>
                {colApps.length}
              </span>
            </div>

            {/* Column Cards Container */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', overflowY: 'auto', flex: 1, paddingRight: '4px' }}>
              {colApps.length === 0 ? (
                <div style={{ 
                  fontSize: '0.78rem', 
                  color: 'var(--text-muted)', 
                  textAlign: 'center', 
                  padding: '32px 10px', 
                  border: '1px dashed rgba(255, 255, 255, 0.03)',
                  borderRadius: '12px',
                  background: 'rgba(255, 255, 255, 0.01)'
                }}>
                  No applications
                </div>
              ) : (
                colApps.map(app => {
                  // Left border color based on priority
                  let priorityColor = 'rgba(46, 229, 157, 0.3)'; // low = green
                  if (app.priority === 'high') priorityColor = '#ff6b6b'; // high = coral
                  else if (app.priority === 'medium') priorityColor = '#ffca28'; // medium = gold

                  return (
                    <div
                      key={app.id}
                      onClick={() => onSelectApp(app.id)}
                      className="portal-card"
                      style={{ 
                        padding: '12px 14px', 
                        cursor: 'pointer', 
                        display: 'flex', 
                        flexDirection: 'column', 
                        gap: '8px',
                        borderLeft: `3px solid ${priorityColor}`,
                        background: 'rgba(14, 26, 21, 0.3)',
                        borderRadius: '10px',
                        boxShadow: '0 4px 12px rgba(0,0,0,0.1)'
                      }}
                    >
                      {/* Card Title Header */}
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '8px' }}>
                        <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {app.companyName}
                        </span>
                        
                        {app.fitScore && (
                          <span style={{ fontSize: '0.7rem', fontWeight: 700, color: 'var(--accent-color)', background: 'rgba(46,229,157,0.06)', padding: '1px 6px', borderRadius: '4px' }}>
                            {app.fitScore}% Fit
                          </span>
                        )}
                      </div>

                      {/* Role Title */}
                      <span style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {app.roleTitle}
                      </span>

                      {/* Fit Score Mini Progress Bar */}
                      {app.fitScore && (
                        <div style={{ width: '100%', height: '3px', background: 'rgba(255,255,255,0.03)', borderRadius: '2px', overflow: 'hidden', marginTop: '2px' }}>
                          <div style={{ width: `${app.fitScore}%`, height: '100%', background: 'linear-gradient(to right, rgba(46,229,157,0.4), var(--accent-color))' }}></div>
                        </div>
                      )}

                      {/* Footer Specs */}
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.68rem', color: 'var(--text-muted)', marginTop: '4px' }}>
                        <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                          📍 {app.location || 'Remote'}
                        </span>
                        <span>
                          {new Date(app.updatedAt).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                        </span>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
