# Phase 5 cutover checklist

## Live route

- [x] `/` renders the React application directly.
- [x] `/` contains no iframe.
- [x] React foundation styles load from the root layout.
- [x] Workbook data is supplied through the server data-source boundary.
- [x] `/react-preview` redirects to `/`.
- [x] `/prototype.html` remains available for rollback comparison.

## Browser acceptance

- [x] Desktop root at 1440 × 900.
- [x] Mobile root at 390 × 844 with no horizontal overflow.
- [x] All nine navigation destinations present.
- [x] Requests workspace navigation.
- [x] AI Fitment workspace navigation and request selector.
- [x] Mobile navigation opens and closes.
- [x] No hydration warning observed.
- [x] No visible runtime error observed.

## Data and build

- [x] `/api/staffing` returned 8 people, 3 requests and 11 project types.
- [x] Workbook integrity check returned `true`.
- [x] Strict TypeScript and optimized production build passed.
- [x] Static scan found no iframe, `innerHTML` or `prototype-app.js` dependency in the React application.
- [x] Legacy public prototype hashes match the backup.

## Rollback boundary

If a visual comparison is required after release, open `/prototype.html`. This fallback is independent of the React root and was not modified during the migration.
