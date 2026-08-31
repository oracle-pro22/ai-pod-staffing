# Phase 3 — React workspace migration

Status: **complete**

Phase 3 moves all nine workspace bodies and their primary interaction flows from the monolithic HTML implementation into typed React components. The migrated application remains isolated at `/react-preview`; the approved HTML prototype at `/` and `/prototype.html` is unchanged pending later parity approval and cutover.

## Migrated workspaces

| Workspace | React component | Migrated behavior |
|---|---|---|
| Command Center | `CommandCenter` | Workbook KPIs, queue, capacity, demand, audit access and POD Member substitutions |
| Requests | `RequestsScreen` | Persona scope, search, five filters including Closed, CSV export, request details and request creation |
| AI Fitment | `AiFitmentScreen` | Request selection, summary, recommendation evidence, candidate selection, re-run and approval checkpoint |
| Allocation Calendar | `AllocationCalendarScreen` | Week movement, skill/capacity filters, alternates, schedule, quick allocation and load guardrail |
| Team & Skills | `TeamSkillsScreen` | Profile evidence, capability strength, scoped directory, search, sorting and person details |
| My Availability | `AvailabilityScreen` | Workbook events, personal capacity and session availability entries |
| Agent Execution | `AgentExecutionScreen` | Request selection, six-stage execution, timed logs, cleanup and result handoff |
| Reports | `ReportsScreen` | Operational/catalog KPIs, demand, allocation, recommendation outcomes, callouts and print |
| Administration | `AdministrationScreen` | Role toggles, taxonomies, evidence rules, audit trail, persona preview and save feedback |

## Migrated overlays

- Request-details drawer.
- Create-staffing-request drawer with all 15 approved fields.
- Multiple catalogue and custom deliverables.
- Mapped, removable, catalogue and custom required capabilities.
- Human approval checkpoint modal.
- Quick allocation drawer and overload guardrail modal.
- Person-details drawer.
- Availability-event drawer.
- Notifications, toasts and Ask AI Pod from Phase 2 remain shared globally.

## Persona behavior

- Operations Lead, Request Lead, Executive and System Administrator retain full workspace access.
- Pod Lead sees Elena Garcia and scoped requests/people; Calendar, Agent Execution, Reports and Administration remain locked.
- POD Member sees Alex Rivera, scoped requests and own information.
- POD Member Command Center replaces the team queue with My AI Fitment Preview, renames capacity to My Capacity, and removes Upcoming Demand and Audit Trail.
- POD Member cannot create/export requests, re-run/approve fitment, browse the team directory or enter restricted workspaces.

## Technical result

- Screen rendering uses React components and typed props/state.
- No migrated screen uses `innerHTML`.
- No migrated screen depends on `prototype-app.js`.
- Workbook reading remains server-only through `dataSource.getViewModel()`.
- Workbook data remains immutable; session drafts and temporary entries are stored separately in the provider.
- Agent timers are cleaned up when the component unmounts or a run restarts.
- Stable date formatting remains centralized.

## Verification completed

- Strict TypeScript and production build passed.
- All nine navigation targets rendered the correct React screen.
- Request-details and create-request flows passed.
- Custom/multiple deliverable and custom capability entry passed.
- Draft request saving added the request to the React table.
- Fitment candidate selection and human approval modal passed.
- Calendar rendered eight people and the 85% guardrail blocked an unsafe allocation.
- Person details and availability entry passed.
- Agent execution completed all six stages and produced a result.
- Reports rendered eight KPI cards and four report panels.
- Administration rendered six roles, eleven catalogue projects and three audit entries.
- Pod Lead and POD Member identity, scope and locked controls passed.
- Desktop visual sweeps completed for Command Center, AI Fitment, Allocation Calendar and Administration.
- The legacy root page and public prototype files were not changed.

## Deferred to Phase 4

Phase 4 should perform the complete 1440 × 900 and 390 × 844 screenshot comparison set, correct remaining pixel-level differences, validate keyboard/focus behavior, and run the final route-level regression suite before cutover.
