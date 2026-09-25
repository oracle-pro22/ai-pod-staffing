# Leave saving and HTTP browser compatibility

Authenticated `POST /api/availability` now forwards through the existing authenticated backend bridge to `POST /v1/availability`. Python locks the person, rechecks own-person permission/account access, inserts the absence, and rebuilds all complete recorded capacity weeks in the same database transaction. Refreshing only the leave week would leave other weeks stale because the availability version belongs to the whole person.

Overlapping/excessive absence or protected baseline conflicts roll back both the event and any partial refresh. Existing external commitments remain part of capacity. Unconfirmed weeks and incomplete-week gaps are not silently turned into free capacity. A person may still be excluded legitimately when leave removes the hours needed by a request; existing proposals still require fresh validation before approval.

Browser operation and toast IDs use UUID-v4-shaped IDs built from `crypto.getRandomValues`, which is available on modern browsers on ordinary HTTP as well as HTTPS/localhost. They no longer depend on secure-context-only `crypto.randomUUID`. These IDs are not authentication tokens; authentication and origin checks are unchanged. HTTP compatibility does **not** provide encryption: use HTTPS before sharing real credentials over an untrusted network.

## Deployment

No database migration or environment-variable change is required for these fixes on the already migrated application. Deploy the new files as well as modified files, notably `backend/python/app/availability.py` and `lib/browser-id.ts`. Rebuild the Next.js app and restart this application's API/web services. Restart the worker too when deploying other shared backend changes in the same release. Stop the web service before rebuilding its `.next` directory; do not rebuild over a running development server locally.

On Windows restart the local Python API and Next.js dev server. On the VM run deployment commands in the Linux SSH terminal, not local PowerShell. Keep `STAFFING_APP_ORIGIN` equal to the address used in that browser; localhost and the public VM address are different origins.

Previously saved stale capacity is not silently repaired at startup. A successful new availability save refreshes the person's complete recorded weeks. To repair old stale records without adding a real new event, use the existing reviewed `app.capacity_admin` dry-run/refresh workflow with the person's genuine planning dates. Do not create dummy leave or stamp versions manually.

## Offline checks

- `node --test scripts/test-browser-id.cjs scripts/test-availability-save.cjs`
- From `backend/python`: `python -m pytest tests/test_availability_save.py`
- `node node_modules/typescript/bin/tsc --noEmit --incremental false`

No live Oracle writes or VM operations are performed by these tests. Verify an actual leave save on the deployed application and inspect the next fitment run before presenting the demo.
