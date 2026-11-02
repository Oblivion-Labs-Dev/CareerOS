import React, { useState, useEffect } from 'react';
import { getLearnedAnswers, saveLearnedAnswer, deleteLearnedAnswer } from '../db/repositories/learnedAnswerRepository';
import { LearnedAnswer, LearnedAnswerScope } from '../shared/learningTypes';

export function LearningCenter() {
  const [answers, setAnswers] = useState<LearnedAnswer[]>([]);
  const [searchTerm, setSearchTerm] = useState('');

  useEffect(() => {
    loadAnswers();
  }, []);

  const loadAnswers = async () => {
    const list = await getLearnedAnswers();
    setAnswers(list);
  };

  const handleDelete = async (id: string) => {
    if (confirm('Delete this question from memory?')) {
      await deleteLearnedAnswer(id);
      await loadAnswers();
    }
  };

  const handleToggleDisabled = async (answer: LearnedAnswer) => {
    const updated = {
      ...answer,
      disabled: !answer.disabled
    };
    await saveLearnedAnswer(updated);
    await loadAnswers();
  };

  const handleChangeScope = async (answer: LearnedAnswer, scope: LearnedAnswerScope) => {
    const updated = {
      ...answer,
      scope
    };
    await saveLearnedAnswer(updated);
    await loadAnswers();
  };

  const filtered = answers.filter(
    a =>
      a.questionText.toLowerCase().includes(searchTerm.toLowerCase()) ||
      a.answer.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h1 style={{ fontSize: '1.8rem', fontWeight: 600 }}>Self-Learning Memory</h1>
        <input
          type="text"
          placeholder="Search learned questions..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          style={{ width: '300px', fontSize: '0.8rem', padding: '6px 12px' }}
        />
      </div>

      <div className="table-container">
        <table className="data-table">
          <thead>
            <tr>
              <th>Question Text</th>
              <th>Answer Value</th>
              <th>Field Type</th>
              <th>Scope</th>
              <th>Stats (Uses)</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={7} className="empty-table">No learned mappings found.</td>
              </tr>
            ) : (
              filtered.map(a => (
                <tr key={a.id} style={{ opacity: a.disabled ? 0.5 : 1 }}>
                  <td><strong>{a.questionText}</strong></td>
                  <td><code>{a.answer}</code></td>
                  <td>{a.fieldType}</td>
                  <td>
                    <select
                      value={a.scope}
                      onChange={(e) => handleChangeScope(a, e.target.value as LearnedAnswerScope)}
                      style={{ fontSize: '0.75rem', padding: '2px 4px' }}
                    >
                      <option value="global">Global</option>
                      <option value="company">Company</option>
                      <option value="domain">Domain</option>
                    </select>
                  </td>
                  <td>{a.usageCount} usages</td>
                  <td>
                    <button
                      className="btn"
                      style={{
                        padding: '2px 6px',
                        fontSize: '0.7rem',
                        background: a.disabled ? 'var(--panel-border)' : 'var(--success-color)',
                        color: 'white',
                        flex: 'none',
                        width: 'fit-content'
                      }}
                      onClick={() => handleToggleDisabled(a)}
                    >
                      {a.disabled ? 'Disabled' : 'Active'}
                    </button>
                  </td>
                  <td>
                    <button className="btn-icon" onClick={() => handleDelete(a.id)}>🗑️</button>
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
