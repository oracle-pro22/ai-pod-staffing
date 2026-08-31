# React Migration Parity Checklist

Use this checklist at the completion of every migrated route.

## Visual

- [x] Exact title, description, labels and capitalization
- [x] Exact navigation icon paths
- [x] Exact background, surface and semantic colors
- [x] Exact sidebar and topbar dimensions
- [x] Exact card borders, radii and shadows
- [x] Exact button height, padding, weight and state colors
- [x] Exact grid columns and gaps
- [x] Exact table columns and row spacing
- [x] Exact progress bars, pills, charts and legends
- [x] Exact drawer/modal/chat placement and stacking
- [x] Desktop comparison against 1440 × 900 baseline
- [x] Mobile comparison against 390 × 844 baseline

## Functional

- [x] Sidebar navigation and active state
- [x] Breadcrumb updates
- [x] Persona selection persists across navigation
- [x] Role-scoped requests and people
- [x] Locked workspaces remain visible and blocked
- [x] POD Member personal dashboard substitutions
- [x] Search and all filters
- [x] Request-details drawer
- [x] Create-request defaults, multiple/custom deliverables and capabilities
- [x] AI Fitment request selection and candidate selection
- [x] Re-run and human approval checkpoint
- [x] Calendar week navigation and allocation guardrail
- [x] Team search and person details
- [x] Availability form
- [x] Agent Execution progress and timer cleanup
- [x] Administration tabs and settings controls
- [x] Ask AI Pod chat
- [x] CSV export and Print/PDF
- [x] Toast, loading, empty and error states

## Technical

- [x] No iframe dependency
- [x] No runtime dependency on `prototype-app.js`
- [x] No `innerHTML` screen rendering
- [x] Strict TypeScript passes
- [x] Production build passes
- [x] No hydration warnings
- [x] No console errors
- [x] No duplicate event handlers
- [x] Stable server/client date formatting
- [x] Workbook remains server-only
- [x] All workbook relationship checks remain active
- [x] Legacy `/prototype.html` remains available as a rollback reference

## Approval rule

A route is complete only when visual, functional and technical checks pass. Intentional product changes are logged separately and must not be mixed into parity fixes.
