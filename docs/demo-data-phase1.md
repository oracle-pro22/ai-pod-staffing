# Phase 1 — complete demonstration data

This is the **data phase of the new three-phase demo plan**, not the original backend Phase 1. It does not redesign screens, change the runtime agent planner, enable email or add the four-role entry screen. The small administrator-only directory filters keep the administrative account out of employee lists and Request source.

The loader uses the existing Python Oracle connection and current tables. It creates no new business tables. Nine backup tables and one migration-state table are created once. All subsequent business changes and the APPLIED marker commit in **one transaction**.

## What will be loaded

| Profile | People |
| --- | --- |
| POD Captain | Indranie Balkaran (P-009), Brenna Cooper (P-010) |
| POD Lead | Elena Garcia (P-006), Priya Nair (P-004), Mara Bennett (P-900102) |
| POD Member | The other 11 existing employees |
| Administrator | New, standalone P-012; not an employee staffing candidate |

Existing employee IDs and names are preserved. No actual company-directory data is inferred: job details, experience narratives and operational commitments in this dataset are **realistic synthetic examples**, tracked internally by `AIPS_DEMO_COMPLETE_V1`. Missing email addresses use reserved `example.invalid` addresses. Existing addresses are retained; nothing is sent to them.

The dataset includes:

- A complete job title, location and weekly working-hours setting for every employee.
- 66 prepared skill ratings with varied strengths, interests and written evidence. Three other existing self-rated skills are retained. The old self-rated Project Manager entry is removed from the working table and retained in the backup; Project Manager is derived from `POD_LEAD` instead.
- 49 deliverable-experience entries, resolved by exact active project/deliverable names in Oracle.
- Five connected delivery projects, 16 named assignments and 366 scheduled person-hours. The initial September 7 schedule creates 222 assignment-day rows.
- Daily capacity for the current Monday–Sunday week and eight following weeks: 63 days × 17 accounts = 1,071 capacity rows. Weekends have zero capacity; the Administrator receives no staffing work.
- Dated operational commitments, existing leave/commitments, and three new future absence events. POD assignment hours are **not** duplicated as external commitments.
- Missing Captain ownership, Request source IDs, dates and business-purpose text filled on the existing requests. Existing titles and explicit source-person selections remain. The old STAFFED request with no actual assignments returns to Needs recommendation.

Published pending proposals are marked SUPERSEDED when their input records change. Their frozen evidence and previous execution logs are retained. The deliberate unresolved-capability request `REQ-900103` remains a **negative test**, not a successful staffing example; no invented skill is added to satisfy it.

### Allocation example

For the initial September 7 week, Elena has 8 hours on the sales-guide project, 8 hours on the portal project and 8 hours of operational work:

`(8 + 8 + 8) / 40 × 100 = 60%`, across two active PODs.

Aisha has 8 POD hours + 4 operational hours = 30%. These are computed outputs, not values written into the old `PEOPLE.ALLOCATION_PCT` field. Current live allocation views use the capacity ledger. The legacy non-agentic snapshot still contains its old summary fields; use agentic mode for the live-ledger demonstration.

Dates move relative to the loading week. The loader can shorten a **new baseline project** before retained leave only when its unchanged effort still passes the real staffing validator. It never removes existing leave to force a fit. The read-only plan lists all schedule adjustments and calculated percentages.

### Imported assignments versus actual agent recommendations

The five projects represent existing work at the start of the demo. Their required proposal/decision history is explicitly marked `operator_baseline_import`, with the named operator, zero model calls and `NO_MODEL_BASELINE_IMPORT`. They must not be described as work chosen or approved by an actual employee or LLM.

The import creates a separate `staffing-baseline-v1` policy for these records. Its approval is an explicit **demo-operator baseline approval**, not production policy sign-off. Existing `staffing-v1-draft` and your configured runtime policy remain unchanged. Do not change the worker to use the baseline policy.

## Run locally

Use PowerShell. Keep the existing Oracle values in `backend/python/.env`; no new secret or OCI setup is needed for this loader. It makes no OCI calls. `BACKEND_ENV` must be `local` or `test`.

### 1. Preview without changing Oracle

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing\backend\python
.\.venv\Scripts\python.exe -m app.demo_data plan --env-file .env
```

Expect `status: PLAN_ONLY`, `writes: 0`, five projects and 16 assignments. This loads the **actual Oracle catalogue and retained availability**, then validates the planned dataset in memory with the real staffing rules. It is not a test of executing Oracle DML or triggers.

If you normally use uv, `uv run python -m app.demo_data ...` is equivalent. The direct virtual-environment command avoids a uv cache permission problem on this machine.

### 2. Stop writers and disable automatic work

Stop Next.js, the Python API and the worker with **Ctrl+C in their three terminals**. Finish any pending SQL Developer transaction first.

In SQL Developer, connected as `AI_POD_STAFFING`, execute:

```sql
UPDATE staffing_runtime
   SET agents_enabled = 'N', notifications_enabled = 'N',
       updated_by = USER, updated_at = SYSTIMESTAMP
 WHERE runtime_id = 1
   AND (agents_enabled <> 'N' OR notifications_enabled <> 'N');
COMMIT;

SELECT agents_enabled, notifications_enabled
  FROM staffing_runtime WHERE runtime_id = 1;

SELECT execution_id, status
  FROM agent_executions WHERE status IN ('QUEUED', 'RUNNING');
```

Both switches must be N and the execution query must return no rows. Do not delete queued/running jobs to bypass this check. The loader takes non-waiting table locks and stops if another writer is present.

### 3. Rehearse the database changes

```powershell
.\.venv\Scripts\python.exe -m app.demo_data apply --env-file .env --operator smaikoti --services-stopped
```

This creates and verifies the nine backups, executes the real inserts/updates and validation, then **rolls back the business changes**. Expect `verified: true`, `committed: false`, `business_dml_rolled_back: true`. Backup DDL remains committed by Oracle. Sequence values may advance and leave harmless gaps; they are never rewound.

**Do not proceed to commit if rehearsal fails.** Keep the full error code and all backup tables. Connection errors report an unconfirmed result rather than assuming a commit could not have happened.

### 4. Commit the same reviewed dataset

```powershell
.\.venv\Scripts\python.exe -m app.demo_data apply --env-file .env --operator smaikoti --services-stopped --commit
.\.venv\Scripts\python.exe -m app.demo_data verify --env-file .env
```

Expect `committed: true` and then `verified: true`. Use the same operator and loading week as rehearsal. If a Monday passes between rehearsal and commit, provide `--anchor YYYY-MM-DD` with the original Monday to both calls. Do not modify the dataset file between rehearsal and commit.

The applied manifest prevents duplicate loading. Re-running apply verifies the existing installation and does **not** overwrite later employee edits. A changed roster, genuine identity mappings, an existing final assignment before the initial load, an unexpected catalogue or modified backups causes a clear stop instead of replacing data.

### 5. Local identity after loading

The old fixed Amelia Captain mapping is deactivated because Amelia is now a Member. Before starting the API to inspect the new data, change only this line in **`backend/python/.env`** to view Indranie's Captain workspace:

```dotenv
BACKEND_LOCAL_SUBJECT=demo:d1:P-009
```

Keep the existing local token the same in Python and Next.js. No login-provider setup is added here. Other newly mapped subjects include `demo:d1:P-010` (Brenna), `demo:d1:P-006` (Elena), `demo:d1:P-001` (Alex) and `demo:d1:P-012` (Administrator). Switching this fixed subject currently requires an API restart; the four-option persona entry and coordinated session switching are **Phase 3**. A frontend role dropdown alone does not change the backend person.

You can restart Next.js and the API to inspect the data, but **leave the worker and database agent switch off until Phase 2's agent corrections are ready**. This phase does not repair the tiny-contribution/0.13% recommendation issue. Email remains off.

## Verification and maintenance

`verify` checks the prepared roster, exact role distribution, populated self-rated skills and deliverable evidence, role-derived PM, nine weeks of capacity, assignment/day totals, complete request ownership/dates and disabled notification state. It is an installation check, not a claim that all agent behavior, identity integration or email has been tested. Legitimately closed baseline projects are accepted; adding or deleting employees changes the expected installation baseline and needs review.

For a later demo date, refresh capacity without reseeding employee skills or creating more baseline projects:

```powershell
.\.venv\Scripts\python.exe -m app.demo_data refresh --env-file .env --operator smaikoti --services-stopped
.\.venv\Scripts\python.exe -m app.demo_data refresh --env-file .env --operator smaikoti --services-stopped --commit
```

Stop writers and set both runtime switches N first, as above. Refresh uses current working hours and retained availability/assignments. Only this loader's marked recurring operational commitments inside the refreshed window are rebuilt around current leave. User-entered commitments and absences are not deleted. If existing POD work now conflicts with leave, refresh fails and rolls back; it does not move the approved assignment. Future new employees require their own working-hours/capacity setup rather than silently inheriting a fictional profile.

## Recovery

If an earlier rehearsal stopped on `Backup AIPS_D1_BK_PEOPLE does not match its original source fingerprint`, update to the corrected loader before retrying. Oracle can return an original JSON column as a decoded object/array but its CTAS backup as CLOB text. The corrected comparison uses the source column's JSON metadata while retaining the original source and raw-backup fingerprints for change detection. Do not delete or recreate the existing backup/state tables. Retry the rehearsal with the original operator and anchor; a real value, row-count or schema difference still stops the operation.

Keep `AIPS_D1_STATE` and all nine `AIPS_D1_BK_*` tables. The capacity backup is named `AIPS_D1_BK_CAPACITY_DAYS`. Leave earlier `AIPS_BK_*`, `AIPS_SK_*` and phase-2 migration objects untouched.

- If business DML fails, the transaction rolls back; verified backups remain for diagnosis and retry. An interrupted backup copy resumes only when ownership, anchor, source data and fingerprints still match.
- Before later use or any committed capacity refresh, the following commands rehearse and then commit a logical recovery:

```powershell
.\.venv\Scripts\python.exe -m app.demo_data recover --env-file .env --operator smaikoti --services-stopped
.\.venv\Scripts\python.exe -m app.demo_data recover --env-file .env --operator smaikoti --services-stopped --commit
```

- Recovery compares fingerprints across 27 mutable/history/configuration tables. It **refuses** if data changed after initial apply, including a committed refresh. This avoids erasing new requests, approvals or employee edits. A later recovery needs a reviewed selective plan.
- Recovery restores original mutable inputs, deactivates the added Administrator, cancels imported assignments and closes imported projects. Immutable decisions, proposals, execution/audit history and baseline policy remain as an honest record of the import/recovery. Old superseded proposals stay superseded. Revision counters are never rolled backwards. This is not a byte-for-byte database reset.
- Recovery does not drop tables, disable triggers, remove existing backup sets, send email or restart services. A recovered batch cannot be blindly reapplied.

## Checks performed while implementing

- Offline dataset, simulation and loader-safeguard tests.
- Read-only live Oracle plans for September 13 and September 14, including retained leave, real catalogue mapping and all five sequential baseline validations.
- SQL parsing against live column types, without executing the DML.

Actual Oracle DML/trigger execution and committed loading are verified by the operator rehearsal/apply steps above, not by the read-only checks.
