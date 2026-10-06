# Implementation Plan: Hacker News Hiring Workspace

## Overview

Add a dedicated `/jobs/hacker-news` page and enabled navigation entry that reuses
CareerOS's existing Hacker News ingestion and job-discovery workflow.

## Architecture Decisions

- Reuse `JobDiscoverDashboard` instead of creating a second job list, queue, or
  application flow.
- Scope requests with the existing API `source=hackernews` filter.
- Keep the general `/jobs/discover` page and its URL behavior unchanged.

## Task List

Tracked in GitHub issue [#87](https://github.com/Oblivion-Labs-Dev/CareerOS/issues/87).

### Phase 1: Dedicated route and navigation

- [x] Add `/jobs/hacker-news` route and enabled sidebar item.
- [x] Make the shared discovery dashboard support a fixed source scope and
      preserve that route while filters change.

### Checkpoint: Core page

- [x] HN page requests only `source=hackernews`.
- [x] Existing Browse Jobs route remains unchanged.

### Phase 2: Verification

- [x] Run web TypeScript typecheck.
- [x] Run focused API/source tests as applicable.
- [x] Review the final diff and confirm unrelated working-tree edits are intact.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Shared dashboard cache shows general jobs | High | Disable the general discovery cache for the scoped page. |
| Filter changes navigate back to Browse Jobs | Medium | Use a configurable page path in URL synchronization. |
| HN jobs enter a separate workflow | High | Reuse existing queue and ApplyPilot callbacks. |

## Open Questions

- Rich HN-specific metadata and outreach drafting are follow-up work after the
  dedicated page is in place.
