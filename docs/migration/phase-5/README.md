# Phase 5 — root cutover and release readiness

Status: **complete**

Phase 5 promotes the verified component-based application from `/react-preview` to `/` and removes the iframe from the live runtime path.

## Cutover changes

- `app/page.tsx` now composes `StaffingAppProvider`, `AppShell` and `WorkspaceRouter` directly.
- `app/layout.tsx` now loads the React foundation styles globally.
- `app/base.css` supplies only the minimal document-level reset and page background.
- `/react-preview` is retained as a compatibility route and redirects to `/`.
- `/prototype.html` and `public/prototype-app.js` remain unchanged as an explicit rollback reference.
- The old `app/globals.css` file is retained but is no longer imported by the live application.

## Runtime boundary

The browser receives the typed staffing view model rendered through React components. Workbook access remains server-only through `lib/staffing-data.ts`; the live root has no iframe, `innerHTML` renderer or runtime dependency on `prototype-app.js`.

## Verification summary

- Root route loaded at desktop and mobile viewports.
- All nine workspace navigation entries were present.
- Requests and AI Fitment navigation rendered their corresponding screens.
- `/react-preview` redirected to `/`.
- `/prototype.html` remained available.
- `/api/staffing` returned workbook-backed data for 8 people, 3 requests and 11 project types with integrity checks enabled.
- Production build and strict TypeScript checks passed.
- SHA-256 hashes for `public/prototype.html` and `public/prototype-app.js` matched the pre-migration backup.

See `cutover-checklist.md` for the release record.
