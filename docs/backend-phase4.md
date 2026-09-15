# Phase 4 — live review and Captain decisions

> Phase 5 is implemented locally. See `backend-phase5.md` for current identity, assignment views,
> closure and disabled outbox behavior. The notes below record the Phase-4 boundary.

## Implemented

- New requests can save the authenticated responsible Captain and automatic-staffing intent together
  with the request and its requirements in one Oracle transaction.
- The Python worker discovers that durable intent after commit. No in-memory request-save callback is
  needed; downtime does not lose the intent. It does not execute work until the existing switches are enabled.
- Agent Execution and AI Fitment have an opt-in live path using the existing layout/components.
  The request dropdown uses the backend's identity-scoped request list, including newly created requests.
- The screens poll real execution events and saved proposals. There is no fake recommendation fallback
  in this path. Existing preview behavior remains unchanged when the integration flags are off.
- The Captain can approve a whole validated proposal or reject it with a mandatory reason.
  Approval has a confirmation step. Changing the displayed proposal invalidates an open confirmation.
- Approval rechecks current permissions, request/proposal versions, approved policy, selected role/skill
  evidence, eligibility and current daily/weekly capacity before committing final assignments.
- Decision, proposal state, assignments, assignment-day hours, request status and audit evidence are atomic.
  A failure rolls the whole transaction back. Approval is final; no Lead/Member acceptance or timer exists.
- Rejection preserves its reason/history, creates no assignments, and returns the request to
  NEEDS_RECOMMENDATION. If that request is opted in, its new revision is picked up automatically;
  otherwise the Captain can explicitly rerun it.

**No new DDL is needed. No live database records, policy approvals, runtime flags, secrets or services were
changed during implementation.** Do not rerun setup.sql or remove the installed phase-2 tables.

## Where the code lives

| File | Responsibility |
| --- | --- |
| `backend/python/app/decisions.py` | Transactional Captain decisions, final assignments and daily hours |
| `backend/python/app/execution_store.py` | Scoped request list/latest execution; durable intake prefers the verified creator's linked identity |
| `backend/python/app/main.py` | New decision/list/latest endpoints and verified identity response |
| `backend/staffing/bridge.ts` | Server-only Next.js-to-Python bridge; never forwards preview role as authorization |
| `app/api/agentic/[...path]/route.ts` | Closed endpoint allowlist, error/status forwarding and response no-store |
| `app/api/requests/route.ts` | Uses backend-verified Captain in agentic mode |
| `lib/repositories/staffing-mutation-repository.ts` | Current identity recheck and atomic request/requirements/staffing intent |
| `components/screens/fitment/LiveStaffingReview.tsx` | Real progress, proposal cards and approval/rejection confirmation |

Backend endpoints:

```text
GET  /v1/me
GET  /v1/requests
GET  /v1/requests/{request_id}/execution
POST /v1/requests/{request_id}/executions
GET  /v1/executions/{execution_id}
GET  /v1/proposals/{proposal_id}
POST /v1/decisions
```

The browser uses same-origin `/api/agentic/...`, not direct access to Python or its credentials.
Decision payload:

```json
{
  "proposal_id": "PP-example",
  "proposal_version": 1,
  "action": "REJECTED",
  "reason": "We need more end-to-end launch experience.",
  "idempotency_key": "unique_decision_key_000001"
}
```

The API accepts only APPROVED or REJECTED. It does not accept actor IDs, selected replacement people,
hours overrides or permission overrides. A changed team needs a newly validated proposal.
The UI retains the same operation key when retrying an uncertain run/decision. The backend prevents
double approval even if a client submits a different key after the first approval.
Request creation itself retains the existing create API without a creation-idempotency key: after an
uncertain request-save response, check the request list before submitting another create.

## Identity boundary

The demo role dropdown is NOT a login. In live mode, Python verifies the bearer token and resolves
the subject/person/permissions from APP_USER_ROLES. Request source remains a separate person chosen
on the form; it never establishes the responsible Captain or grants approval rights.
Next.js rechecks that subject's active Captain mapping when it writes the new request.

The live request list is scoped to the responsible Captain, or an explicitly permitted FULL Administrator.
Only the responsible Captain with AI_FITMENT approval permission can decide. Administrator privileges
alone cannot impersonate the Captain. Pending suggestions are not exposed to Leads/Members via these APIs.

For a future trusted login integration, the bridge forwards the request's Authorization bearer token,
or the `staffing_access_token` cookie populated by that integration. Python validates the token independently.
This phase does **not** implement OAuth login/callback/session issuance. Do not deploy the app as a fully
authenticated production system yet: the other existing preview routes still need the planned identity cutover.

For local development only, the bridge can use one explicitly configured server-side local test token.
That mode requires NODE_ENV=development and a loopback Python URL. Run Next.js bound to 127.0.0.1
as shown below; do not expose this fixed-identity mode on a LAN/shared VM. Changing the dropdown does
not switch that configured identity. No backend token is embedded in frontend JavaScript.

## Configuration — leave disabled until integrated testing

In root `.env.local`, later add:

```ini
STAFFING_AGENTIC_ENABLED=false
NEXT_PUBLIC_STAFFING_AGENTIC_ENABLED=false
STAFFING_BACKEND_URL=http://127.0.0.1:8015
STAFFING_BACKEND_AUTH_MODE=local
STAFFING_BACKEND_LOCAL_TOKEN=YOUR_PRIVATE_LOCAL_TEST_TOKEN
```

The two feature flags must match. Set both true only when ready. Restart Next.js after changes;
the NEXT_PUBLIC flag is compiled into the browser bundle and requires a rebuild for production builds.
The token must be the same private value as Python's BACKEND_LOCAL_TOKEN for local testing.

In `backend/python/.env`:

```ini
BACKEND_ENV=local
BACKEND_AUTH_MODE=local
BACKEND_LOCAL_SUBJECT=seed:backend-p2:P-900101
BACKEND_LOCAL_TOKEN=YOUR_PRIVATE_LOCAL_TEST_TOKEN
STAFFING_WORKER_ENABLED=false
STAFFING_DECISIONS_ENABLED=false
STAFFING_POLICY_VERSION=staffing-v1-draft
```

Keep Oracle/OCI settings from the phase-3 guide. Keep database `STAFFING_RUNTIME.agents_enabled='N'`
and notifications disabled until test activation. The separate decision switch controls approval/rejection
APIs; turning the agent switch off does not itself disable decisions.

**Approval requires an APPROVED policy, even locally.** The phase-2 policy is still DRAFT unless a
responsible person approves/configures it. This release does not approve it automatically or bypass the
database foreign key. Once a reviewed policy is approved, queue a fresh proposal under that approved
configuration; a proposal produced under an older draft snapshot must be regenerated.
Use an explicitly approved testing policy/configuration for final fixture tests, not an undocumented bypass.

## Local commands for the later integrated test

First complete phase-3 dependency installation and read-only Oracle/OCI checks. Full Python framework
testing is not verified until dependency installation succeeds. Then deliberately enable the relevant
flags and database agent switch, using the scoped steps in `docs/backend-phase3.md`.

Frontend terminal:

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing
npm run dev -- --hostname 127.0.0.1
```

API terminal:

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing\backend\python
uv run uvicorn app.main:app --host 127.0.0.1 --port 8015 --env-file .env
```

Worker terminal:

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing\backend\python
uv run python -m app.worker --env-file .env
```

Using the configured local Captain identity:

1. Create a request with both planned dates, valid deliverables/capabilities and effort.
2. Request source can be any valid active person; the responsible Captain comes from authenticated identity.
3. Save. The UI opens Agent Execution. The worker picks up the committed request when enabled.
4. Observe actual progress, or an actionable missing-information/capacity outcome.
5. Review the selected POD, hours, factors and rationale in AI Fitment.
6. Reject one proposal with a reason; inspect saved history and the new run if automatic intent is enabled.
7. Approve a fresh eligible proposal under the approved policy. Check final assignments/daily hours in Oracle.
8. Retry the same decision and test concurrent approvals competing for a person's capacity. There must
   be no duplicate assignments or overbooking. Actual Oracle concurrency tests are still required;
   offline command tests do not prove database lock behavior.

Existing people without verified capacity or effective staffing-role assignments are not treated as free
or eligible. Missing mandatory Project Manager role mapping/custom capability resolution remains a
NEEDS_INFORMATION outcome; this phase does not fabricate those mappings.

## Transaction details and recovery

Lock order is request → policy → selected people sorted by ID → proposal. Publication additionally locks
its execution before the proposal. All selected people are locked before fresh capacity is read. Two
backend approvals sharing a person serialize and the second rechecks the first's committed daily hours.
This guarantee assumes assignment/capacity writers follow the same locking/versioning discipline;
direct administrator SQL still requires coordination.

Skills/role evidence changes require a new proposal. Workload changes are re-evaluated against current
capacity and can still pass if enough room remains. The approval audit captures the decision-time capacity
calculation and input versions. Proposal-card scores remain the original saved recommendation snapshot.

Request status is updated last because the installed trigger increments its revision. Approved/rejected
history retains the input revision it decided; terminal proposal history is not presented as actionable stale work.

On a timeout/uncertain commit, refresh the proposal/decision state before retrying. Reuse the same key
for the same decision. Never fix an error by deleting audit/decision rows, resetting IDs or rerunning setup.sql.
Old DRAFT policies, stale proposals and insufficient capacity produce explicit errors rather than partial assignments.

Rollback of the feature is operational, not destructive: stop the worker, turn off the Python execution
and decision flags, turn off both Next.js integration flags, and restart the affected services. Preserve
all committed assignments and history. Reverting to preview does not undo database decisions.

## Deliberately still Phase 5

- Lead/Member project views and allocation/reporting switched to final assignment tables.
- Identity integration/cutover for remaining preview endpoints and approved production deployment.
- Notification outbox preparation and recipient configuration; email sending remains unimplemented.
- Complete live Oracle/OCI/browser acceptance, concurrency, restart and operational recovery testing.

RECOMMENDATIONS and legacy demo records were not overwritten. No notification records or emails
are produced by the phase-4 decision handler.

## Offline verification

Run from the root:

```powershell
npx tsc --noEmit
npm run test:application
npm run test:skills
npm run test:agentic
```

From `backend/python`:

```powershell
uv run python -m unittest discover -s tests -v
```

Recorded implementation checks: 90 Python tests passed, three framework modules skipped because
dependencies remain unavailable; 25 application + 30 skills + 12 bridge/request-intent tests passed;
TypeScript typechecking passed. No live Oracle/OCI execution, assignment creation or browser acceptance
test was performed. Integration switches and credentials were not changed.
