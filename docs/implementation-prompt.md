# CareerOS implementation prompt

Use this prompt with Cursor/Codex inside the CareerOS repository.

The **Phase constraint: three-page surface** section is a hard override for the current phase.

---

```text
Refactor CareerOS into a focused, connected solo job-search workflow.

Do not rewrite the application or delete existing capabilities. Reuse the current routes, components, data models, API clients, extension integration, and design system. Hide unfinished or internal features from the primary UX while preserving their code.

Primary product loop:

Build → Find → Apply → Track → Connect → Prepare

The finished experience should feel like one product rather than separate web, extension, API, and Resume Corpus tools.

Before implementation

1. Read:
   - docs/product-audit-2026-07-17.md
   - repository README and architecture documentation
   - all AGENTS.md and repository instruction files
2. Inspect:
   - current route structure
   - navigation configuration
   - application, job, profile, resume, referral, outreach, and interview models
   - API and extension integration points
   - existing analytics/events
   - Resume Corpus sidebar and feature metadata
3. Produce a short implementation map showing:
   - existing components and routes to reuse
   - routes to merge, redirect, or hide
   - missing data connections
   - migrations or schema changes, if any
4. Preserve all working functionality and user data.

## Phase constraint: three-page surface (HARD OVERRIDE)

For this phase, CareerOS must expose only three pages:

1. Jobs — company job scraping, filtering, matching, and ranking
2. Profile — experience, accomplishments, projects, education, skills, and job preferences
3. Settings — scraper sources and configuration

Disable every other user-facing page and remove it from all navigation, search, command menus, shortcuts, dashboard cards, and cross-page links.

Do not delete any existing page, route, component, API, model, script, migration, or feature. Preserve all code and stored data so disabled features can be restored later.

Implement disabled pages through a centralized feature-flag or route-access configuration. If a user directly visits a disabled route, redirect them to `/jobs` or show a consistent "This feature is currently disabled" page. Do not leave partially accessible routes or dead navigation links.

The application root and `/dashboard` should redirect to `/jobs`.

Development tools may remain accessible only in development mode. Do not refactor or repair disabled features during this phase unless required to keep the build passing.

The finished production navigation must contain only:

- Jobs
- Profile
- Settings

This constraint supersedes conflicting navigation, workspace, redirect, and Playwright expectations elsewhere in this prompt for this phase only. Keep Today, Build, Apply, Connect, Prepare, and other existing workspaces in the codebase, but hide and gate them so they are not part of the production surface.

## 1. Simplify the primary navigation

Replace the current primary navigation with:

- Today
- Build
- Apply
- Connect
- Prepare

Place secondary items in a compact utility menu:

- Resources
- Settings
- Developer Tools, shown only in development
- Roadmap, shown only in development or behind an explicit feature flag

Remove placeholder routes and “coming soon” features from primary navigation. Do not delete their implementations.

Working destinations such as referrals and outreach must become discoverable through the new navigation.

Add compatibility redirects from old public routes wherever appropriate.

Suggested route organization:

- /today
- /build
- /apply
- /connect
- /prepare
- /settings

Keep old nested routes when useful, but present them through these five workspaces.

Make /dashboard redirect to /today instead of /applications.

**Phase override:** Redirect `/` and `/dashboard` to `/jobs` instead. Production nav is Jobs, Profile, Settings only.

## 2. Build a real Today command center

Create a useful daily execution dashboard using real repository data. Do not use fabricated metrics if real data is available.

The page should answer:

- What should I do next?
- Which applications need action?
- Which saved jobs are worth applying to?
- Who should I follow up with?
- What interview preparation is due?
- Is my profile or resume missing anything important?

Include:

### Daily Focus

Show 3–5 prioritized actions across the entire product.

Examples:

- Complete an unfinished application
- Apply to a high-fit saved job
- Follow up on a referral
- Respond to a recruiter
- Prepare for an upcoming interview
- Improve a resume with a low match score

Create deterministic prioritization rules. Do not use an LLM for simple ranking.

Priority should consider:

- deadlines
- interview dates
- application age
- follow-up dates
- job fit or match score
- incomplete required information
- application stage
- user dismissal or snooze state

Each action must link directly to the correct record and support:

- Complete
- Snooze
- Dismiss
- Open details

### Pipeline Snapshot

Show application counts by meaningful stage:

- Saved
- Applying
- Applied
- Recruiter Screen
- Interviewing
- Offer
- Rejected or Closed

Every count must be clickable and open a filtered Apply workspace.

### Follow-ups

Show applications, recruiters, referrals, or contacts that need follow-up. Display the reason and how long the item has been waiting.

### Upcoming

Show upcoming application deadlines, interviews, and scheduled follow-ups in chronological order.

### Weekly Progress

Use existing data to show only useful metrics:

- applications submitted
- responses received
- interviews scheduled
- referrals requested
- follow-ups completed

Avoid vanity metrics and decorative charts without actionable meaning.

Handle empty, loading, partial-data, and error states cleanly.

## 3. Create the Build workspace

Combine profile and the useful subset of Resume Corpus into one workspace.

Primary sections:

- Profile
- Accomplishments
- Resumes
- Job Match
- Resume Builder

Move interview-specific content to Prepare.

Trim the visible Resume Corpus navigation. Remove all “coming soon” entries from the normal sidebar. Keep unfinished views accessible only behind development flags if needed.

Use shared profile and accomplishment data throughout resume creation and matching. Avoid creating duplicate stores or competing versions of the user profile.

The Build workspace should clearly show:

- profile completeness
- resume versions
- last updated time
- strongest reusable accomplishments
- missing information affecting job applications
- recent job matches

## 4. Create the Apply workspace

Unify:

- job discovery or imported jobs
- saved jobs
- applications
- ApplyPilot extension activity

Use tabs or an equally clear workspace pattern:

- Jobs
- Saved
- Applications

Do not create separate disconnected page shells.

### Jobs and Saved Jobs

Support:

- search
- filtering
- sorting
- fit or match information when available
- save/unsave
- start application
- open source job
- archive
- duplicate detection

When “Start application” is selected:

1. Create or reuse the application record.
2. Associate the job, company, selected resume, and captured job description.
3. Set the correct application stage.
4. Open the relevant application workflow.
5. Avoid duplicate application records.

### Editable Application Tracker

Convert the tracker from a mostly read-only display into an action-oriented workflow.

Allow editing:

- stage/status
- application date
- job URL
- company and role
- selected resume
- recruiter or contact
- referral
- next action
- follow-up date
- notes
- interview dates
- outcome

Support at least list/table and pipeline views if the repository already contains reusable components for them. Do not build a complex drag-and-drop system unless the current architecture supports it cleanly.

Each application should expose an activity timeline built from real events:

- captured
- autofill started
- submitted
- stage changed
- contact added
- follow-up completed
- interview scheduled
- outcome recorded

### ApplyPilot Integration

Use the shared API and application models so extension-captured jobs appear in the web app without manual duplication.

Clearly distinguish:

- captured
- autofill in progress
- submitted
- submission unconfirmed
- failed

Do not treat autofill completion as confirmed submission.

If the extension and web app currently use incompatible models, add a normalization layer rather than duplicating business logic.

## 5. Create the Connect workspace

Merge referrals, contacts, and outreach into one coherent experience.

Sections:

- Relationships
- Referrals
- Outreach

Connect records to:

- companies
- jobs
- applications
- messages
- follow-up dates

A relationship detail view should show:

- person and company
- associated job/application
- referral status
- outreach history
- next follow-up
- notes

Reuse existing outreach templates and Gmail-related backend capabilities, but do not expose CLI scripts as product features.

Never send an email automatically. Drafting and preview are allowed, but sending must remain an explicit confirmed action.

Support a clear flow:

Find or add contact → associate job → request referral or draft outreach → record response → schedule follow-up

## 6. Create the Prepare workspace

Make this the single user-facing entry point for interview preparation.

Move or expose the existing Resume Corpus interview-prep functionality here.

Organize preparation by actual application or target role:

- Upcoming interviews
- Company and role context
- Relevant accomplishments
- STAR story bank
- Generated or saved questions
- Practice notes
- Interview stages

Avoid maintaining a second disconnected interview model if Resume Corpus already contains the required data.

When possible, use the job description, selected resume, application, and accomplishment corpus as shared context.

## 7. Wire the data end to end

Create one clear source of truth for each major entity:

- Profile
- Resume
- Accomplishment
- Job
- Application
- Company
- Contact
- Referral
- Outreach activity
- Interview
- Follow-up/task
- Product event

Define and document relationships between these entities.

At minimum:

- A saved job can become an application.
- An application references its source job and selected resume.
- A contact can be associated with a company, job, and application.
- A referral belongs to a contact and may target a job/application.
- Interview preparation belongs to an application or target role.
- Extension events update the same application lifecycle used by the web app.
- Today reads actionable data from all workspaces.
- Completing an action updates its source entity and immediately removes or updates the Today item.

Do not create separate copies of the same record for each workspace.

Add schema migrations only when required. Migrations must preserve existing local and persisted data and be safely repeatable.

## 8. Consolidate product shells

The Next.js web application should be the main user-facing dashboard.

Treat these as supporting surfaces:

- Browser extension: capture and autofill companion
- API HTML dashboard: developer/operations view only
- Scripts and agents: internal automation
- Roadmap modules: development planning

Do not attempt to move the browser extension into the web app. Instead, align its data contracts, authentication, terminology, and status lifecycle with the web app.

Hide the API dashboard, scripts, agent skills, and roadmap from normal product navigation.

## 9. Feature flags and development-only content

Create a centralized feature-flag mechanism if one does not already exist.

Use it for:

- unfinished routes
- experimental Resume Corpus views
- roadmap pages
- internal company-job dashboards
- developer tools
- prototype analytics

Production navigation must not advertise unfinished capabilities.

Avoid scattered environment checks across components.

## 10. UX and visual requirements

Preserve the established CareerOS visual identity, but make the information architecture consistent.

Requirements:

- one shared application shell
- one consistent sidebar/header
- clear workspace titles
- restrained tab counts
- responsive desktop and mobile layouts
- accessible labels and keyboard navigation
- visible focus states
- no overlapping elements
- no layout shifts during loading
- consistent empty states
- no fake data in production
- no dead-end buttons
- no “coming soon” cards in primary workflows

The interface should prioritize the next action over feature discovery.

## 11. Analytics

Wire existing events into a small, useful internal analytics layer.

Track:

- job saved
- application started
- application submitted
- application stage changed
- referral requested
- outreach drafted/sent
- follow-up completed
- interview scheduled
- offer received

Use these events for Today and Weekly Progress where appropriate.

Do not expose a standalone Analytics page until it provides real value. Keep it development-only for now.

## 12. Testing

Add or update:

### Unit tests

- priority calculation for Today actions
- saved-job-to-application conversion
- duplicate application prevention
- stage transitions
- follow-up detection
- feature-flag visibility
- extension event normalization

### Integration tests

- saved job → application
- application → contact/referral
- application → interview preparation
- extension capture → web application tracker
- completed follow-up → Today refresh

### Playwright tests

Test only the workflows changed by this implementation:

1. Navigation displays only Jobs, Profile, and Settings (phase override).
2. Today action opens the correct underlying record.
3. Saved job becomes an application without duplication.
4. Application fields and stages can be edited and persist.
5. Referral/outreach records connect to the application.
6. Interview preparation opens from an interviewing application.
7. Development-only routes are hidden in production mode.
8. Layout has no obvious overlap at common desktop and mobile sizes.

Use multiple browsers only for an explicit thorough verification run. Use Chromium for the normal implementation loop.

## 13. Documentation

Update the README and architecture documentation with:

- product workflow
- new navigation map
- canonical entity ownership
- extension/web synchronization
- feature flags
- hidden/development-only functionality
- route redirects
- migration instructions

Create a concise implementation report containing:

- files changed
- routes changed
- reused components
- schema changes
- functionality hidden behind flags
- tests added
- tests run and results
- known limitations
- recommended next step

## Implementation constraints

- **Phase override:** The three-page surface constraint above is mandatory for this phase and wins over five-workspace navigation targets.

- Do not delete working code simply because it is no longer visible.
- Do not introduce an additional state-management system unless necessary.
- Do not duplicate profile, application, or Resume Corpus data.
- Do not replace working components without a concrete reason.
- Do not change API contracts without updating every consumer.
- Do not use placeholder values to make dashboards appear complete.
- Do not perform unrelated repository-wide cleanup.
- Keep changes incremental and reviewable.
- Preserve backward compatibility where practical.
- Fix all errors introduced by the changes.

Work in phases:

Phase 1: repository analysis and route/data map  
Phase 2: navigation, redirects, feature flags, and shared shell  
Phase 3: Today command center  
Phase 4: Build and Apply consolidation  
Phase 5: Connect and Prepare consolidation  
Phase 6: extension synchronization and cross-workspace wiring  
Phase 7: tests, accessibility, responsive verification, and documentation

After every phase:

- run relevant type checking, linting, and focused tests
- verify affected pages manually or with Playwright
- report what changed and any discovered constraints

Do not stop after producing a plan. Implement the complete refactor, verify the connected workflows, and provide the final implementation report.
```

---

## Manual “Process Logs & Errors” workflow (backend POC)

Add a developer-only button on the CareerOS backend page at `http://localhost:8000`:

**Process Logs & Errors**

### POC behavior

When clicked, the workflow must:

1. Read recently captured backend logs and errors from local CareerOS storage.
2. Sanitize secrets and personal data.
3. Group duplicate errors using a stable fingerprint.
4. Select unresolved actionable errors.
5. Create or update a repair task.
6. Build a diagnostic package containing error message, stack trace, nearby logs, occurrence count, first/last occurrence, endpoint, service/version, suspected source files, reproduction details, and validation commands.
7. Send the repair task to the configured coding-agent adapter.
8. Show agent status, output, changed files, diff, and validation results on the backend page.

### Manual-only requirement

Do not process logs automatically. The system must not watch logs continuously, trigger from error events, run on a timer, auto-retry failed agent runs, auto-request review, or push/merge/deploy/create pull requests. Every run begins with an explicit developer click.

### Backend page states

Show: `Idle → Reading logs → Creating task → Sending to agent → Agent working → Validating → Completed / Failed`

Disable the button while a run is active. Prevent duplicate clicks and duplicate repair tasks for the same unresolved error.

Display: logs scanned, errors discovered, duplicate groups, skipped items + reason, repair task created/updated, agent run status, changed files, validation results, failure details.

### Agent safety

The coding agent may create a local branch/worktree and modify code there, but must never modify the developer’s active branch, access production secrets, push, create/merge PRs, deploy, disable tests, or change protected files. Require the smallest reasonable fix and a regression test when practical.

### Initial scope

Support only backend/API errors stored locally. Do not add Loki, OpenTelemetry, Sentry, Temporal, automatic detection, review agents, canary deployments, or A/B testing yet.

Keep the design extensible through:

```ts
interface LogSource {
  readRecentLogs(options: ReadLogOptions): Promise<LogEntry[]>;
}

interface CodingAgentAdapter {
  start(task: RepairTask, workspace: AgentWorkspace): Promise<AgentRun>;
  getStatus(runId: string): Promise<AgentRunStatus>;
  cancel(runId: string): Promise<void>;
}
```

Use a mocked coding agent by default. Enable a real local adapter only through explicit development configuration.

### Required POC test

Demonstrate:

1. Trigger the backend demo error.
2. Open the developer backend page at `:8000`.
3. Click **Process Logs & Errors**.
4. Confirm detection, sanitization, repair task creation, mocked agent run, and validation results on the page.
5. Confirm nothing is pushed, merged, reviewed, or deployed automatically.

