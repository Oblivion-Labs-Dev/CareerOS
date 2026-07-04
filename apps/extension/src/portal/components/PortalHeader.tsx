import React from 'react';

type PortalHeaderProps = {
  serverOnline: boolean;
};

export function PortalHeader({ serverOnline }: PortalHeaderProps) {
  return (
    <header className="station-header">
      <div className="station-brand">
        <h1>Arsenal Station</h1>
        <p>Oblivion Labs · local automation command center</p>
      </div>
      <div className="station-status">
        <span className="pulse"></span>
        <span className={`status-pill ${serverOnline ? 'status-pill--online' : 'status-pill--offline'}`}>
          <span className="status-dot"></span>
          {serverOnline ? 'Local server connected' : 'Server offline — run node server.js'}
        </span>
      </div>
    </header>
  );
}
