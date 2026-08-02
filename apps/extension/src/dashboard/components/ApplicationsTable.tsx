import React, { useState } from 'react';
import { Application } from '../../db/repositories/applicationRepository';

interface ApplicationsTableProps {
  applications: Application[];
  onSelectApp: (id: string) => void;
  onUpdateStatus: (id: string, newStatus: Application['status']) => void;
  onDeleteApp: (id: string) => void;
}

export function ApplicationsTable({ applications, onSelectApp, onUpdateStatus, onDeleteApp }: ApplicationsTableProps) {
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');

  const filtered = applications.filter(app => {
    const matchesSearch =
      app.companyName.toLowerCase().includes(searchTerm.toLowerCase()) ||
      app.roleTitle.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesStatus = statusFilter === 'all' || app.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h1 style={{ fontSize: '1.8rem', fontWeight: 600 }}>All Applications</h1>
        
        <div style={{ display: 'flex', gap: '10px' }}>
          <input
            type="text"
            placeholder="Search company or role..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            style={{ fontSize: '0.8rem', padding: '6px 12px' }}
          />

          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            style={{ fontSize: '0.8rem', padding: '6px 12px' }}
          >
            <option value="all">All Statuses</option>
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
      </div>

      <div className="table-container">
        <table className="data-table">
          <thead>
            <tr>
              <th>Company</th>
              <th>Role</th>
              <th>Status</th>
              <th>Priority</th>
              <th>Fit Score</th>
              <th>Last Activity</th>
              <th>Follow-up</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={8} className="empty-table">No applications match your filter.</td>
              </tr>
            ) : (
              filtered.map(app => (
                <tr key={app.id}>
                  <td><strong style={{ cursor: 'pointer', color: '#a5b4fc' }} onClick={() => onSelectApp(app.id)}>{app.companyName}</strong></td>
                  <td>{app.roleTitle}</td>
                  <td>
                    <select
                      value={app.status}
                      onChange={(e) => onUpdateStatus(app.id, e.target.value as Application['status'])}
                      style={{ padding: '3px 6px', fontSize: '0.75rem' }}
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
                  </td>
                  <td>
                    <span className={`badge ${app.priority === 'high' ? 'badge-low' : app.priority === 'medium' ? 'badge-medium' : 'badge-high'}`}>
                      {app.priority}
                    </span>
                  </td>
                  <td>{app.fitScore ? `${app.fitScore}%` : '-'}</td>
                  <td>{new Date(app.updatedAt).toLocaleDateString()}</td>
                  <td>{app.nextFollowUpAt ? new Date(app.nextFollowUpAt).toLocaleDateString() : '-'}</td>
                  <td>
                    <button type="button" className="btn-icon" onClick={() => onSelectApp(app.id)} style={{ marginRight: '8px' }}>👁️</button>
                    <button type="button" className="btn-icon" onClick={() => onDeleteApp(app.id)}>🗑️</button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
