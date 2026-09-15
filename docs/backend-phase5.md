# Phase 5 — assignments, identity and operational handoff

## Implemented locally

- Live Requests shows final PODs, responsibilities, dates and planned hours. Leads/Members see assigned
  projects, never access inferred from request source or legacy recommendations.
- The assigned, currently authorized POD Lead can close a staffed project with a required note.
  Request, assignments and audit update atomically. Day-hour history remains; closed assignments no
  longer reserve capacity. There is no Lead/Member acceptance step. These are planned hours, not timesheets.
- Live Calendar and Reports read final assignments and the current weekly capacity ledger. Weeks use
  the policy timezone. Allocation = (confirmed + external hours) / available hours × 100. Pending
  proposals reserve nothing. Active POD count means confirmed projects whose date range includes today.
  Missing/stale capacity shows “Needs refresh”; it is never assumed free. Reports export scoped Excel records.
- Approval prepares one DISABLED notification-outbox intent per assigned person, atomically with the
  decision/assignments. Missing email is marked RECIPIENT_EMAIL_REQUIRED without blocking valid assignment.
  Payload contains assignment identifiers/role/hours, not private skills or model evidence.
  **No email sender, dispatch endpoint, backfill or automatic enablement exists.** Future delivery must
  revalidate recipient, current assignment, approved template and deduplication before sending.
- Server-rendered staffing data and staffing/chat APIs are filtered by verified identity before the browser.
  Existing skills, availability, people and rephrase routes use verified employee identity in live mode.
  Writes recheck effective mappings and schema. The live role selector cannot impersonate employees.
- Organization sign-in uses Authorization Code + PKCE, signed expiring state, HttpOnly SameSite cookies
  and Python verification of the access token and employee mapping. No browser-embedded secrets.
  Sessions last at most one hour; refresh tokens are not stored. Sign out clears this application's cookie.
- Added dry-run-first capacity refresh and isolated shared-VM systemd templates.

**No new database migration.** Use the installed Phase-2 schema. Do not rerun setup.sql, drop tables,
rewrite migration fingerprints or delete backup/history tables. `phase5_verify.sql` is read-only inspection.
No live data, env files, flags, policy approvals, credentials, OCI calls or VM services were changed by this work.

## Code locations

- Python: `app/assignments.py`, `app/notifications.py`, `app/capacity_admin.py`, endpoints in `app/main.py`.
- Next.js: `backend/staffing/login.ts`, `view-model.ts`, `/api/auth/*`, authenticated request context,
  `components/screens/requests/LiveAssignments.tsx` and live calendar/report routing.
- SQL: `sql/oracle/phase5_verify.sql`.
- VM: `deploy/systemd/ai-pod-{web,api,worker}.service` templates; not installed or started here.

```text
GET  /v1/workspace?resource=REQUESTS&week=2026-09-14
GET  /v1/workspace?resource=ALLOCATION_CALENDAR&week=2026-09-14
GET  /v1/workspace?resource=REPORTS&week=2026-09-14
POST /v1/requests/{request_id}/close
GET  /api/auth/login
GET  /api/auth/callback
POST /api/auth/logout
```

Closure body: `{"request_revision":3,"reason":"All deliverables completed."}`. Requires assigned Lead
and current REQUESTS view/update permission. Same closure retry causes no extra write; conflicting or
stale closure requires refresh. Administrator alone cannot act as the Lead/Captain. Model tools cannot close/approve.

## Setup from your end

### 1. Dependencies and schema checks

Keep `.env.local`, Oracle wallet and `.oci` private. Never commit credentials. Python requires 3.12.
Dependency downloads timed out during implementation, including a network-approved retry.

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing
npm ci
npm run test:application
npm run test:skills
npm run test:agentic
npx tsc --noEmit
cd backend\python
uv sync --cache-dir .uv-cache
uv run python -m unittest discover -s tests -v
uv run python -m app.cli database --env-file .env
```

After successful sync, review/commit the generated `uv.lock`; deploy with `uv sync --frozen`. No lockfile
or complete Python install is claimed yet. Don't deploy with skipped framework tests. The database check
is read-only. The separate Phase-3 OCI smoke command is opt-in and can incur model usage.

In SQL Developer's AI_POD_STAFFING worksheet run `phase2_verify.sql` and `phase5_verify.sql` with F5.
Expected seeded rows may differ from baseline counts. Earlier Phase-4 approvals may lack outbox rows;
the verifier reports them without backfilling or emailing anyone.

### 2. Local testing versus organization sign-in

Local-only testing retains the Phase-4 loopback token configuration. Python BACKEND_LOCAL_SUBJECT
must match APP_USER_ROLES.identity_subject (seed Captain: `seed:backend-p2:P-900101`). Restart Python
to switch the configured subject to the seed Lead/Member. Bind both servers to 127.0.0.1. No IdP setup
is needed for this local mode; role dropdown changes are not authentication.

For the VM, ask the identity administrator for an approved Authorization Code/S256 PKCE client,
authorization/token endpoints, access-token scope/audience, issuer and JWKS URL. Current backend supports
**RS256 JWT access tokens**, not opaque tokens or ID tokens substituted for access tokens. Confirm compatibility.
Register exactly `https://YOUR_APPROVED_HOST/api/auth/callback`. Root `.env.production` on the VM:

```ini
STAFFING_AGENTIC_ENABLED=true
NEXT_PUBLIC_STAFFING_AGENTIC_ENABLED=true
STAFFING_BACKEND_URL=http://127.0.0.1:8015
STAFFING_BACKEND_AUTH_MODE=bearer
STAFFING_APP_ORIGIN=https://YOUR_APPROVED_HOST
STAFFING_OIDC_AUTHORIZATION_URL=https://YOUR_IDENTITY_HOST/APPROVED_AUTHORIZATION_PATH
STAFFING_OIDC_TOKEN_URL=https://YOUR_IDENTITY_HOST/APPROVED_TOKEN_PATH
STAFFING_OIDC_CLIENT_ID=YOUR_REGISTERED_CLIENT_ID
STAFFING_OIDC_CLIENT_SECRET=YOUR_CLIENT_SECRET_IF_REQUIRED
STAFFING_OIDC_SCOPE=YOUR_APPROVED_ACCESS_TOKEN_SCOPES
STAFFING_LOGIN_STATE_SECRET=YOUR_RANDOM_SECRET_AT_LEAST_32_CHARACTERS
```

Client-secret authentication uses client_secret_basic; public PKCE clients omit the secret. Don't guess
provider paths or scopes. Current session storage requires a token fitting a browser cookie; test actual
token size. Use an approved HTTPS reverse proxy preserving Host/Origin. Don't use public HTTP:8005 for
cookie login. No network/security-list/proxy configuration was changed here.

In `backend/python/.env` on VM, retain existing Oracle/OCI settings and configure:

```ini
BACKEND_ENV=production
BACKEND_AUTH_MODE=oidc
OIDC_ISSUER=https://YOUR_APPROVED_ISSUER
OIDC_AUDIENCE=YOUR_ACCESS_TOKEN_AUDIENCE
OIDC_JWKS_URL=https://YOUR_APPROVED_JWKS_URL
STAFFING_WORKER_ENABLED=false
STAFFING_DECISIONS_ENABLED=false
STAFFING_POLICY_VERSION=YOUR_REVIEWED_POLICY_VERSION
```

Use Linux wallet/key paths, not Windows paths. Administrators must map verified subjects to employees
and effective roles in APP_USER_ROLES. Name/email never creates access automatically. Unlinked/inactive/
ambiguous mappings fail sign-in. The current UI picks the first actual official profile in Captain/Lead/
Member/Administrator order; multi-role profile switching isn't implemented. Logout is local, not IdP-wide revocation.

### 3. Policy and capacity readiness

Approval requires a reviewed APPROVED policy, even in local mode. This release does not approve one.
Generate a fresh proposal after approving/changing policy evidence. Check effective role coverage,
mandatory Project Manager mapping, skills and deliverable experience before expecting eligible candidates.

Candidates need reviewed weekly_work_hours and current PERSON_CAPACITY_DAYS for every full week
covering the project. New availability invalidates that ledger through the version trigger. Live self-service
absence is classified NON_AVAILABILITY. Legacy UNKNOWN events need review.

Capacity refresh evenly distributes each event's **total allocated_hours** across its Mon–Fri dates.
It refuses missing hours, unknown classification, excessive overlap/range and absent weekly working hours.
It does not infer holidays or alternate working patterns. It refuses overwrites that would lose additional
absence/external work from another ledger source. The original seed has external commitments: don't
blindly reconstruct it from availability alone; preserve/reconcile those inputs first.

Dry-run an explicit person (change person/dates/operator to your reviewed test):

```powershell
uv run python -m app.capacity_admin --env-file .env --person P-900102 --start 2026-09-14 --end 2026-09-27 --operator YOUR_NAME
```

Only after reviewing input/results repeat with `--commit`. It updates just that person's expanded
full-week capacity interval under the same person lock used by approval. No roles/events/policies/flags
are changed. This is a trusted operator command using the schema credential, not a self-service API.

### 4. Local integrated test

After dependencies, policy and capacity are ready, deliberately enable matching Next.js flags, Python
worker/decision switches, and the DB agent switch using the Phase-3 scoped instructions. Keep notifications
OFF. Don't enable flags to bypass missing policy/identity/capacity evidence. Three terminals:

```powershell
# Root
npm run dev -- --hostname 127.0.0.1

# backend/python
uv run uvicorn app.main:app --host 127.0.0.1 --port 8015 --env-file .env

# backend/python, separate terminal
uv run python -m app.worker --env-file .env
```

Open `http://127.0.0.1:3001`. Local mode uses the configured identity; organization mode uses Sign in.
Production public-flag changes require a fresh `npm run build` and restart.

## Acceptance checks still required

1. Captain saves → one current-revision execution → real tool events → saved proposal.
2. Feasible/capacity-pressure/unresolved-capability fixtures produce the expected distinct outcomes.
3. Reject requires reason; next run receives it; no assignments/notices from rejection.
4. Approve → one decision, exact assignment/day hours, audit and DISABLED outbox intents.
5. Repeated/uncertain approval never duplicates team/decision/notices. Inspect uncertain request saves before retrying.
6. Concurrent approvals sharing a person serialize/recheck capacity and cannot overbook.
7. Changed skills/roles/dates/catalogue/policy/capacity block stale or invalid approval.
8. Restart only the test worker mid-run; persisted lease/checkpoint recovery and bounded retries work.
9. Assigned Lead/Member sees its POD; unassigned employee cannot. Forged headers/person IDs, revoked
   mappings and invalid/expired/wrong-audience tokens fail at the server.
10. Only assigned Lead closes, with note; history retained and planned capacity released.
11. Calendar/report uses chosen week; unknown capacity isn't free. Excel contains scoped records only.
12. Skills/availability write to signed-in person only; availability requires subsequent capacity refresh.
13. Real IdP tests: PKCE, expired/tampered state, failed code exchange, token size/RS256/audience,
    HTTPS callback/proxy, unlinked subject, cross-origin save/logout and session expiry.
14. Phase5 verifier passes; notifications stay DISABLED, attempts zero, no emails.

Offline mocks do not prove Oracle triggers/locks, IdP/OCI interoperability or browser layout. Complete
the live checks before calling the application production-ready. Search remains bounded, not globally optimal.

## Shared VM templates and recovery

Root: `/home/opc/AIML_INTERNAL_INITIATIVES/AI_POD_STAFFING`. Web binds loopback:8005 behind HTTPS;
API binds loopback:8015; worker exposes no port. Verify `command -v node` and edit the web template if
Node is not `/usr/bin/node`. Build a Linux .venv on VM, don't copy Windows environments/node_modules.
Keep wallets/env/private keys restricted. Review clean git status, pull safely, install locked dependencies,
build successfully and confirm old staffing port/PID ownership before switching to services.

```bash
mkdir -p /home/opc/.config/systemd/user
cp deploy/systemd/ai-pod-web.service deploy/systemd/ai-pod-api.service deploy/systemd/ai-pod-worker.service /home/opc/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ai-pod-api.service ai-pod-web.service ai-pod-worker.service
systemctl --user status ai-pod-api.service ai-pod-web.service ai-pod-worker.service
journalctl --user -u ai-pod-api.service -u ai-pod-worker.service -u ai-pod-web.service -n 100 --no-pager
```

Review any existing same-named unit files before copying. Ask the VM administrator to approve
`loginctl enable-linger opc` for services surviving logout/reboot; this task has not run it.

Stop only these services:

```bash
systemctl --user stop ai-pod-worker.service ai-pod-web.service ai-pod-api.service
```

For upgrades: stop worker; wait for in-flight work/lease expiry; stop web/API; install/build; restart API/web
then worker; check health and queues. Never pkill/killall shared Node/Python processes. Rollback is a
service/code rollback, not deletion of decisions, assignments, audit, outbox or migration backups.
Preview mode is not a secure public deployment and reverting to it does not undo committed assignments.

## Recorded checks

Production Next.js build and TypeScript checks passed. 74 Node tests and 109 offline Python tests passed.
Three Python framework modules were skipped because PyPI dependency downloads timed out. No live
Oracle/OCI/browser/concurrency tests were performed and no email was sent. Full acceptance remains required.
