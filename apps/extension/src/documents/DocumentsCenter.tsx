import React, { useState, useEffect } from 'react';
import { getDocuments, saveDocument, deleteDocument, DocumentRecord } from '../db/repositories/documentRepository';
import { getApplications, Application } from '../db/repositories/applicationRepository';

export function DocumentsCenter() {
  const [docs, setDocs] = useState<DocumentRecord[]>([]);
  const [apps, setApps] = useState<Application[]>([]);
  const [newDocLabel, setNewDocLabel] = useState('');
  const [newDocType, setNewDocType] = useState<'resume' | 'cover_letter'>('resume');

  useEffect(() => {
    loadDocs();
  }, []);

  const loadDocs = async () => {
    const list = await getDocuments();
    const appList = await getApplications();
    setDocs(list);
    setApps(appList);
  };

  const handleCreateDoc = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newDocLabel.trim()) return;

    await saveDocument({
      type: newDocType,
      label: newDocLabel,
      active: true
    });

    setNewDocLabel('');
    await loadDocs();
  };

  const handleDelete = async (id: string) => {
    if (confirm('Delete this document variant?')) {
      await deleteDocument(id);
      await loadDocs();
    }
  };

  const handleToggleActive = async (doc: DocumentRecord) => {
    const updated = {
      ...doc,
      active: !doc.active
    };
    await saveDocument(updated);
    await loadDocs();
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <h1 style={{ fontSize: '1.8rem', fontWeight: 600 }}>Documents & Variant Registry</h1>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 300px', gap: '20px' }}>
        {/* Documents list */}
        <div className="review-card" style={{ padding: '20px' }}>
          <h3>Stored Document Variants</h3>
          <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: '12px' }}>Resume files and cover letters targeting specific roles or companies.</p>

          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Label</th>
                  <th>Type</th>
                  <th>Filename</th>
                  <th>State</th>
                  <th>Usages</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {docs.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="empty-table">No documents in registry. Add one using the panel on the right.</td>
                  </tr>
                ) : (
                  docs.map(doc => {
                    const usages = apps.filter(
                      a => a.resumeUsedId === doc.id || a.coverLetterUsedId === doc.id
                    ).length;

                    return (
                      <tr key={doc.id}>
                        <td><strong>{doc.label}</strong></td>
                        <td><span className="badge badge-needs-answer">{doc.type.replace('_', ' ')}</span></td>
                        <td>{doc.fileName || 'No file uploaded'}</td>
                        <td>
                          <button
                            className="btn"
                            style={{
                              padding: '2px 6px',
                              fontSize: '0.7rem',
                              background: doc.active ? 'var(--success-color)' : 'var(--panel-border)',
                              color: 'white',
                              flex: 'none',
                              width: 'fit-content'
                            }}
                            onClick={() => handleToggleActive(doc)}
                          >
                            {doc.active ? 'Active' : 'Archived'}
                          </button>
                        </td>
                        <td>{usages} applications</td>
                        <td>
                          <button className="btn-icon" onClick={() => handleDelete(doc.id)}>🗑️</button>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Add new variant */}
        <div className="review-card" style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px', height: 'fit-content' }}>
          <h3>Register Variant</h3>
          <form onSubmit={handleCreateDoc} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <div className="form-group">
              <label htmlFor="new-doc-label">Label / Name</label>
              <input
                type="text"
                id="new-doc-label"
                value={newDocLabel}
                onChange={(e) => setNewDocLabel(e.target.value)}
                placeholder="e.g. React Frontend variant"
                required
              />
            </div>

            <div className="form-group">
              <label htmlFor="new-doc-type">Document Type</label>
              <select
                id="new-doc-type"
                value={newDocType}
                onChange={(e) => setNewDocType(e.target.value as any)}
              >
                <option value="resume">Resume</option>
                <option value="cover_letter">Cover Letter</option>
              </select>
            </div>

            <button type="submit" className="btn btn-primary" style={{ width: '100%' }}>Register Variant</button>
          </form>
        </div>
      </div>
    </div>
  );
}
