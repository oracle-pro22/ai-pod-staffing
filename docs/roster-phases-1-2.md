# Real roster: Phases 1 and 2

This delivery implements the **read-only migration audit** and the **multi-role
application foundation**. It does not import accounts, archive/reset business
data, change live role grants, or implement first-login onboarding. No existing
environment file is changed.

## Approved target

- The `Team-Role` sheet in `Team Names and Access Type.xlsx` is authoritative.
- Create 25 real-roster accounts in the later import: 18 enabled, seven disabled.
- Keep the seven profiles and exact grants stored, but exclude disabled accounts
  from login, recommendations, alternatives, manual selection and final assignment.
- Ignore `Tester` entirely. Use `Grant Tool Access` for the initial enabled state.
- Default contracted work is 8 hours/day and 40 hours/week. Do not fabricate
  skills, experience, leave, external commitments or existing POD assignments.
- Archive the previous live dataset before replacing it. Do not merge demo
  assessments or old allocation values into the real roster.
- Retain deliverables, skill definitions, deliverable mappings, policy history,
  role configuration, runtime settings and all prior backups.

The roster has eight Captains, 25 Leads, 24 Members and three Administrators
(overlapping grants). Among enabled users the highest-role display is three
Administrators, five Captains and ten Leads. Amy's explicit grants are Captain
and Lead, not Member. Manager-only names are metadata, not accounts or grants.

## Phase 1: read-only audit

The portable command reads the original workbook using the Python standard
library. It validates exact column meanings, literal role flags, normalized
Oracle emails, duplicate emails and access status. It rejects formulas in import
fields and never executes macros. No extra Excel dependency is required.

From `backend/python` on Windows:

```powershell
.\.venv\Scripts\python.exe -m app.roster_audit --workbook "C:\Users\smaikoti\Downloads\Team Names and Access Type.xlsx" --output .mvp/roster-source-review.json --offline
.\.venv\Scripts\python.exe -m app.roster_audit --workbook "C:\Users\smaikoti\Downloads\Team Names and Access Type.xlsx" --env-file .env --output .mvp/roster-database-review.json
```

On the VM use `.venv/bin/python` and the actual copied workbook path. Choose a
new report filename each run. Existing files are never overwritten.

The database command enters `OracleDatabase.read()`, which verifies the schema,
uses `SET TRANSACTION READ ONLY` and rolls back when finished. There is no apply,
archive, reset or commit subcommand. It produces:

- Exact source hash, target counts and proposed per-person grants/status.
- Existing person/account comparison. Matches are reference evidence only, not
  permission to reuse an old identity or copy assessments during the future reset.
- Counts for every proposed archive table, including selection/manual history,
  audit events and sessions.
- Foreign-key inventory, incoming references outside scope and proposed
  child-first ordering. Cycles and unknown tables require review before reset.
- Protected table content/column fingerprints, current approved policy,
  current runtime switches, queued/running jobs and confirmed assignments.
- Trigger inventory and previous backups that must be retained.

Reports contain names, emails and internal IDs. Keep them in ignored `.mvp/`,
restrict access and do not commit them. Password hashes, session tokens and
credential values are never selected or exported. Tool-owned
`DBTOOLS$EXECUTION_HISTORY` is outside scope and its contents are not read.

### Audit performed on 2026-09-23

Read-only Oracle audit found 31 people, 31 accounts and three requests, all
`NEEDS_RECOMMENDATION`. There were three proposals, no approval decisions and no
confirmed assignments. Inventory also included 1,357 availability records,
2,072 capacity-day records and 127 personal assessment rows.

There were two exact email references (Indranie and Robert), one name-only email
correction requiring review (Brenna), and 22 new-person candidates. No assessed
profile is copied automatically. No incoming foreign-key dependencies outside
the planned archive scope and no dependency cycles were found. The audit found
agents enabled and notifications disabled; it did not change either switch.

The local report is `backend/python/.mvp/roster-phase1-audit-20260923-v2.json`.
It is a point-in-time report, not a backup or authorization to reset. Re-run it
before the later maintenance window because records can change.

## Archive and recovery checklist for the later Phase 4

This checklist is prepared now; none of these write operations are performed by
Phase 1 or automatically by application startup.

1. Review a fresh audit, resolve unclassified tables and confirm exact reset
   scope. Preserve tool-owned tables and all previous backups.
2. Stop this application's web/API/worker writers on every host using the same
   database. Capture runtime settings and disable execution/notifications during
   maintenance. Do not stop shared VM infrastructure.
3. Prepare a versioned, access-restricted full recovery archive containing all
   affected rows, schema/constraint/trigger definitions, batch/operator/source
   identity, row counts and fingerprints. Credential-bearing account/session
   tables require protected archival storage; they must not be printed in logs
   or copied into ordinary source control.
4. Preserve Oracle types, JSON payloads, timestamps/time zones and decimal
   precision. Preserve both foreign-key links and references embedded in frozen
   evidence. Copy all related history, not just `PEOPLE` or `REQUESTS`.
5. Verify completeness and a restore in an isolated approved environment before
   clearing any live rows. The audit JSON cannot restore the database because
   it intentionally excludes credentials and most source row data.
6. Only then run the separately reviewed Phase 4 archive/reset operation, using
   dependency-aware ordering. Do not blanket-disable constraints or delete
   backups. Any temporary immutable-history guard handling needs an exact
   before/after definition/state check and interrupted-run recovery procedure.
7. After recovery, revoke old sessions rather than making archived credentials
   into usable sessions. Do not blindly replay an old archive over new business
   writes. Restore runtime switches only after verification and explicit release.

## Phase 2 application behavior

### Identity and permissions

- Highest display role: Administrator, Captain, Lead, Member.
- Authenticated capabilities come from actual effective grants, not from a
  browser role header or the Administrator's role-configuration catalogue.
- Admin+Captain retains Captain actions; Admin/Captain with staffing grants can
  edit their own skills and availability without role switching.
- Full-scope Captains share request review, alternative/manual selection,
  approval/rejection and reruns. Existing narrower grants are not silently
  expanded. The current Captain configuration already has full scope.
- Record the actual acting Captain separately from the responsible request
  owner, including the queued worker's initiator and publication checks.
- A Lead sees their own assignments in either slot. Teammate profile visibility
  remains limited to active projects they actually lead.
- The server returns `can_close` only for a currently authorized Lead who is
  actually assigned as that project's Lead. Highest display role does not
  determine closure rights. No Administrator-only closure bypass exists.

### Staffing eligibility

- Lead slots require explicit effective `POD_LEAD`; Member slots require explicit
  effective `POD_MEMBER`. Amy cannot enter Member slots, including manual override.
- Candidate evidence requires an active person and enabled, subject-matched
  account/role mapping. Selected people are checked again before assignment.
- Manual picker returns one person with `role_codes[]`, not duplicate rows.
- A person fills only one slot; capacity still aggregates by `person_id`.
- Existing scoring, scheduling, catalogue mappings and utilization formulas are
  unchanged. Manual overrides still ignore skill/leave/external commitments only
  for overridden slots and retain the 100% existing-plus-new POD hours limit.
- Legacy frozen policies are preserved. Exact role authorization is enforced
  independently, so an old policy cannot grant an absent Member role.
- Engine/checkpoint/validator revisions invalidate obsolete execution/review
  results. Re-run old pending fitment after deployment; do not edit history.

## Required Oracle schema rollout (prepared, not executed)

The previous decision FK/trigger restricted the actor to the owning Captain.
The new code needs `sql/oracle/roster_multirole.sql` for shared-Captain decisions.

During a controlled maintenance window, with application services stopped,
runtime execution/notifications disabled and no queued/running jobs:

1. Review and apply `sql/oracle/roster_multirole.sql` as `AI_POD_STAFFING`.
2. It backs up affected DDL to `RM2_DDL_BACKUP`, installs replacement
   proposal/request and actor integrity before removing the owner-equality FK,
   and replaces the decision trigger with current-actor authorization checks.
3. Run the read-only verifier before restarting:

```powershell
.\.venv\Scripts\python.exe -m app.roster_schema --env-file .env
```

The script retains roster, requests, assignment history and runtime settings.
Oracle DDL commits separately; if interrupted, keep services stopped, inspect
the retained backups and verification output, and resume only after resolving
the mismatch. Do not drop/recreate application tables or rerun setup scripts.

After new cross-Captain decisions exist, the old owner-equality constraint may
no longer be restorable without losing valid decisions. Do not blindly roll
back old DDL over new history; use a coordinated recovery or forward correction.

### Prepare an explicit-role policy revision offline

The audit includes the current approved policy. This command only prints a
proposed clone; it cannot connect to Oracle:

```powershell
.\.venv\Scripts\python.exe -m app.explicit_role_policy --policy-json .mvp/roster-database-review.json --version staffing-exact-roles-v1 --operator smaikoti --approved-at 2026-09-23T00:00:00Z
```

Use the actual intended operator/time. Add `--sql` to print reviewable provisioning
SQL instead. It clones the selected approved policy and changes only the Lead
and Member eligibility values; weights, utilization and scheduling remain the
same. It checks schema, maintenance state and source policy consistency. It
does not execute the SQL, change `STAFFING_POLICY_CONTROL`, change runtime flags,
or create roster accounts. The active-pointer cutover needs its own explicit
reviewed step. Never mutate an existing approved policy in place.

## Not implemented in these phases

Phases 3 and 4 now have a separate [implementation and maintenance guide](roster-phases-3-4.md).
The list below records the boundary of the original Phase 1/2 delivery.

- Phase 3: account activation/deactivation UI/API, last-Administrator protection,
  first-login onboarding, genuine baseline work entry and review.
- Phase 4: recovery archive creation, restore verification and live reset.
- Phase 5: real account import and initial capacity provisioning.
- Phase 6: end-to-end real-account verification and VM release.

Future account deactivation must use the same person-row serialization as final
assignment decisions, revoke sessions, preserve current commitments and flag an
active project Lead for explicit resolution. These are not implemented by merely
excluding disabled people from recommendations in Phase 2.

## Verification for this delivery

- Local optimized Next.js build, including type checking: passed.
- All 162 JavaScript tests: passed.
- Python suite: 545 tests and 300 subtests passed; two failures remain outside
  these changes. The existing historical `demo_phase2_policy.sql` approval flag
  is `TRUE` while its old static test expects `FALSE`. The JWT-generation test
  fails with a local OpenSSL entropy-source error before exercising application
  authorization. Neither was bypassed or silently changed.
- All 42 new roster audit, access, schema and exact-slot eligibility tests passed.
- Live Oracle audit used a read-only transaction. The new Oracle DDL was reviewed
  and tested offline, not installed or integration-tested against live Oracle.
- No account/session login test, model call, assignment, import, deletion,
  archive creation, environment change or service restart was performed.
