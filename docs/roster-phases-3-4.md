# Real-roster rollout — Phases 3 and 4

These are the **real-roster rollout** phases, not the older MVP agent phases.
Phase 2's `roster_multirole.sql` must already be installed and verified.

## Delivery and deployment boundary

Implemented locally:

- Administrator account enable/disable controls, reason and audit history,
  session revocation, concurrent-change protection and last-Administrator guard.
- First-login setup for newly enrolled people: genuine skills, deliverable
  experience, dated leave, external work and existing-POD claims.
- Captain review of existing-POD claims against independently verified assignments.
- Operator-only native Oracle archive, isolated restore rehearsal, explicit reset,
  empty-target restoration and trigger recovery tools.

**This delivery does not execute a live migration, archive, reset or import.**
It does not change environment files, restart services, send mail or call a model.
Real-roster import remains Phase 5; real-account/VM acceptance remains Phase 6.
The 25-person plan remains 18 enabled accounts and 7 accounts that cannot log in;
ignore the Tester column and retain only each person's explicitly granted roles.

## Phase 3 behavior

### Account access

Administration now lists account email, person, enabled state and setup state.
Only a currently enabled Administrator with full access-management permission
can change access. Every change requires a reason and current revision.

- Account changes serialize globally, then lock the target person like staffing
  approvals do. Disabling revokes existing sessions without deleting history.
- You cannot disable yourself or remove the last enabled access Administrator.
- An active project's assigned Lead cannot be disabled until the project/Lead
  situation is explicitly resolved. Member commitments are retained on disable.
- Enabling needs an active person and effective account-matched role grants.
  It does not grant extra roles or bypass incomplete onboarding.
- This screen does not reset passwords, delete accounts or import a roster.

### First login and capacity

Phase 5 must insert `ROSTER_ONBOARDING` with `DRAFT` for **every newly imported
person**, including initially disabled accounts. Existing profiles without a row
remain `LEGACY` and are not silently enrolled or overwritten by this migration.

The setup screen collects:

1. Actual self-rated skills, evidence/interest and existing-catalogue deliverable
   experience. Empty assessments are allowed; expertise is never fabricated.
2. A confirmed dated period containing today (maximum 13 complete weeks), and
   genuine leave, external work or existing-POD work with total hours and dates.
3. Explicit confirmation of accuracy before a single transactional submission.

The default contract is 8 hours per weekday / 40 hours per week. Total event
hours are spread over weekdays using the existing calendar rules. Leave reduces
available hours; external work consumes capacity. The existing capacity refresh
calculates the dated records in the same transaction as onboarding. Failed setup
rolls back together. No allocation percentage or active-POD counter is entered
or invented. Genuine workload above 100% can be reported; it is not silently
clamped down. This does **not** authorize new assignments above the existing limits.

Dates outside the confirmed/refreshed period are not silently provisioned here.
Users still maintain their own skills and availability after setup. Catalogue,
skill definitions and deliverable-to-skill mappings are unchanged.

### Existing PODs — self-reported workload

A reported existing POD is stored separately from external commitments and
approved assignments. Its dated hours count toward the person's capacity as soon
as first-login setup is saved. Saving completes onboarding and opens the workspace;
there is no Captain approval queue or `REVIEW` access hold.

The report does not invent a request, project assignment, approval, or active-POD
count. Genuine projects can be imported later through a separately controlled
process. The retained `PENDING` database value means “self-reported, not linked to
an imported assignment”; it is not a pending approval and does not block staffing.

Normal recommendation policy, explicit slot roles, shared person capacity and
manual overrides' 100% existing-plus-new POD ceiling remain unchanged.

## Install the additive schema first

Do this in a maintenance window, connected as `AI_POD_STAFFING` to the intended
database. Stop **all** local and VM API, worker and web processes using that DB.
Do not stop other applications on the shared VM.

Record the current runtime settings. Disable only this application's switches:

```sql
UPDATE staffing_runtime
SET agents_enabled = 'N', notifications_enabled = 'N'
WHERE runtime_id = 1;
COMMIT;

SELECT agents_enabled, notifications_enabled
FROM staffing_runtime WHERE runtime_id = 1;

SELECT execution_id, request_id, status
FROM agent_executions WHERE status IN ('QUEUED', 'RUNNING');
```

If work remains queued/running, resolve it through the existing reviewed process;
do not delete jobs or force statuses to bypass maintenance checks.

Run **`sql/oracle/roster_onboarding.sql` as a script (F5)**. It creates four
additive structures: `ROSTER_ACCESS_CONTROL`, `ROSTER_ONBOARDING`,
`ROSTER_POD_CLAIMS`, `ROSTER_RESET_RUNS`. It does not enroll, archive, import or
delete people. Oracle DDL commits independently: keep services stopped if it
fails, inspect the mismatch and verify before resuming.

From `C:\Users\smaikoti\Desktop\ai-pod-staffing\backend\python`:

```powershell
.\.venv\Scripts\python.exe -m app.roster_schema --env-file .env
.\.venv\Scripts\python.exe -m app.onboarding_schema --env-file .env
```

Both are read-only checks. No new environment variables are required; retain the
existing password-mode settings. Do not paste `.env` files or credentials into
logs/chat. Deploy the Python and Next.js changes together after schema verification.

## Phase 4: archive and rehearsal, then a separately approved reset

### Scope and prerequisites

The reviewed allowlists in `app/roster_audit.py` are the authority. Reset targets
include old people, accounts/sessions/role assignments, individual assessments,
availability/capacity, requests, recommendations, execution/decision history,
POD assignments and days, notifications, business audit events and onboarding.

Protected data includes catalogue/deliverable mappings/skill definitions,
project types, role definitions/permissions, scoring/eligibility/load rules,
policies and runtime/control records. Previous backups are retained. Unknown
tables, changed input data, invalid constraints and unsupported dependencies
stop the process rather than widening scope. Dependency inspection is scoped
to the owning application's schema; a DBA must review cross-schema consumers.

The tool requires a session-scoped `DBMS_LOCK` maintenance lock that survives
Oracle DDL commits. If the account lacks permission, it fails closed: ask the
DBA to review the requirement. Do not grant broad privileges as a workaround.

Native archive/shadow tables are in the **same restricted Oracle schema** and
contain confidential personal data, password hashes and historical session
material. They are not a backup against database loss or malicious schema-owner
access. Obtain and verify a separate, access-controlled DBA backup before a live
reset; do not export wallets or secrets into the repository.

### Read-only plan

Keep all writers stopped and both runtime switches OFF for the whole maintenance
window. Use one new batch ID (maximum 30 characters, starting with `roster4-`):

```powershell
.\.venv\Scripts\python.exe -m app.roster_reset plan --env-file .env --batch roster4-real-roster
```

Review every target count and the protected list. The plan writes nothing. A
different schema, unsupported column/constraint or unclassified table requires
review, not an ad-hoc delete. Do not proceed if scope or counts are surprising.

### Archive and prove a logical restore

These commands **write private archive/rehearsal tables**, not live-data deletion:

```powershell
.\.venv\Scripts\python.exe -m app.roster_reset archive --env-file .env --batch roster4-real-roster --operator smaikoti --services-stopped --commit
.\.venv\Scripts\python.exe -m app.roster_reset inspect --env-file .env --batch roster4-real-roster
.\.venv\Scripts\python.exe -m app.roster_reset rehearse --env-file .env --batch roster4-real-roster --operator smaikoti --services-stopped --commit
```

Archive stores native typed copies, original DDL/guard definitions, table counts
and content fingerprints. Rehearsal restores those copies to isolated native
shadow tables, compares all row fingerprints and checks original uniqueness,
check and foreign-key relationships against restored values. Source data must
remain unchanged. Archive and shadow tables are retained; nothing is dropped.

Only `REHEARSED` with an exact confirmation fingerprint permits reset. This is
a logical data recovery rehearsal, **not** a full application recovery test or
proof that an independent disaster-recovery backup works.

### Destructive cutover gate — do not run during preparation

Before a reset, independently confirm the scope/backup/rehearsal and have the
Phase 5 import plus a real Administrator ready. Reset removes **all live accounts**
in scope: the app cannot be reopened until the reviewed real roster is imported.
Do not reset now merely because the tooling is implemented.

Only in that approved window, replace the placeholder with the exact fingerprint
returned by the verified rehearsal:

```powershell
.\.venv\Scripts\python.exe -m app.roster_reset reset --env-file .env --batch roster4-real-roster --operator smaikoti --services-stopped --confirmation REPLACE_WITH_VERIFIED_FINGERPRINT --commit
```

This rechecks archive and live data, temporarily disables only recorded guards
on the reset tables (not constraints or protected-table guards), locks the scope,
deletes child-first in one transaction, verifies empty targets and unchanged
protected data, commits the journal and restores original guards. An archive
alone does not authorize deletion; there is no startup/web/model reset endpoint.
Runtime switches remain OFF. Keep services stopped until import and verification.

### Interrupted maintenance / recovery

Always run `inspect` first after uncertainty. Do not rerun destructive commands
blindly, edit journal states, drop archives or overwrite new business records.

- `PREPARING`: inspect objects/ownership markers; `resume-archive` can resume only
  the unchanged batch. DDL interrupted before an ownership marker needs manual
  review, not adoption of an unknown table.
- `ARCHIVED`: original business data remains; run rehearsal when ready.
- `REHEARSED`: reset is eligible only with unchanged data and explicit approval.
- `RESET`: originals are empty. Either reviewed Phase 5 import or recovery follows.
- `RESTORED`: original data was recovered; restored sessions were revoked.

If a guard operation was interrupted, use this explicit recovery command and
inspect its result while keeping writers stopped:

```powershell
.\.venv\Scripts\python.exe -m app.roster_reset recover-guards --env-file .env --batch roster4-real-roster --operator smaikoti --services-stopped --commit
```

Only unchanged original trigger definitions are re-enabled. Unexpected guard
definitions fail closed and require review; definitions are never overwritten.

For a `RESET` batch with all live targets still empty, an approved recovery is:

```powershell
.\.venv\Scripts\python.exe -m app.roster_reset restore --env-file .env --batch roster4-real-roster --operator smaikoti --services-stopped --confirmation REPLACE_WITH_VERIFIED_FINGERPRINT --commit
```

Restore inserts parent-first, verifies exact restored data, then deliberately
revokes historical sessions before commit. It refuses to overwrite new imports
or business writes. It does not drop archives, restore an old environment file,
rewind sequences, change catalogue data or enable agents/notifications.

## Verification and remaining acceptance

Local production build/type checking and all 166 JavaScript tests passed. The
Python suite has 607 passing tests and 300 passing subtests. New Python
tests cover onboarding validation/atomicity, access guards, staffing eligibility,
schema drift, maintenance-lock ordering, archive/reset gates and recovery errors.
Two previously observed Python-suite failures are outside this change: the old
demo policy approval-flag fixture and a Windows OpenSSL entropy error in JWT key
generation. Neither was hidden or bypassed.

No live Oracle migration or archive/rehearsal has been run for this delivery.
Before deployment, prove native Oracle DDL, locks, constraints, archive and restore
on a non-production copy, then conduct the approved live maintenance window.
Complete real-roster import and genuine baseline-POD preparation in Phase 5,
followed by end-to-end login/permissions/selection/approval tests in Phase 6.
