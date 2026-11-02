import React from 'react';

export type InstrumentCardProps = {
  icon: string;
  name: string;
  subtitle: string;
  description: string;
  status: 'active' | 'soon';
  tags?: string[];
  stats?: { label: string; value: number }[];
  primaryAction?: { label: string; href: string };
  secondaryAction?: { label: string; href: string };
  disabledAction?: string;
};

export function InstrumentCard({
  icon,
  name,
  subtitle,
  description,
  status,
  tags,
  stats,
  primaryAction,
  secondaryAction,
  disabledAction
}: InstrumentCardProps) {
  const isActive = status === 'active';

  return (
    <article
      className={`instrument-card ${isActive ? 'instrument-card--active' : 'instrument-card--inactive'}`}
    >
      <div className="instrument-card-header">
        <div className="instrument-icon" aria-hidden>{icon}</div>
        <div className="instrument-card-title">
          <h3>{name}</h3>
          <span>{subtitle}</span>
        </div>
        <span className={`instrument-badge instrument-badge--${isActive ? 'active' : 'soon'}`}>
          {isActive ? 'Active' : 'Coming soon'}
        </span>
      </div>

      <p className="instrument-desc">{description}</p>

      {tags && tags.length > 0 && (
        <div className="instrument-tags">
          {tags.map((tag) => (
            <span key={tag} className="tag">{tag}</span>
          ))}
        </div>
      )}

      {stats && stats.length > 0 && (
        <div className="instrument-stats">
          {stats.map((s) => (
            <div key={s.label} className="stat-chip">
              <span className="stat-chip-value">{s.value}</span>
              <span className="stat-chip-label">{s.label}</span>
            </div>
          ))}
        </div>
      )}

      <div className="instrument-actions">
        {primaryAction && (
          <a href={primaryAction.href} className="btn btn-primary">{primaryAction.label}</a>
        )}
        {secondaryAction && (
          <a href={secondaryAction.href} className="btn btn-secondary">{secondaryAction.label}</a>
        )}
        {disabledAction && (
          <button type="button" className="btn btn-secondary" disabled style={{ cursor: 'not-allowed', opacity: 0.6 }}>
            {disabledAction}
          </button>
        )}
      </div>
    </article>
  );
}
