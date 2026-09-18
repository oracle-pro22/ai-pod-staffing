# MVP Phase 2 — Supervisor and selectable POD recommendations

This is the second phase of the [agreed MVP plan](mvp-login-supervisor-override-plan.md), not the original backend schema Phase 2. Phase 1's login, roster and request cleanup stay in place. Do not repeat the data import.

## What changed

- A real OCI tool-calling **Supervisor** delegates to the Request/Evidence Analyst and POD Planner through LangGraph. It can inspect status, route validated business clarifications, retry a malformed delegate output once within the budget, and finish Captain review. The server rejects illegal transitions; completed stages are not repeated after a worker restart.
- Normal execution needs nine model calls when each tool is called separately: three Supervisor, four Analyst, two Planner. The existing total hard cap remains **12 model calls / 40 tool calls**. Analyst maximum is six; Supervisor maximum is four. The policy must permit at least nine. No policy is rewritten by this release.
- New engine `staffing-engine-v4`, prompt `staffing-tools-v5-supervised`, checkpoint format 4. Old queued or leased checkpoints fail with `CHECKPOINT_VERSION`; create a new run after resolving them. Completed historical proposals stay readable.
- One-Lead requests show the recommended Lead plus up to **two distinct eligible Lead alternatives**. N-Member requests show N selected Members plus up to **two additional distinct people**. Multiple-Lead requests preserve their requested Lead count and offer at most two additional Lead people.
- Each alternative is a valid one-person replacement in the current selected POD. Some candidates can replace only particular Members because collective coverage matters. The dropdown shows only their valid replacement targets. Shortages and search limits are displayed honestly.
- Selecting a replacement pins that exact team and recomputes **all** contribution hours, schedules, scores and allocations with existing deterministic rules. No OCI call occurs on selection. After a change the options are recomputed against the new team.
- Original AI recommendations remain immutable. Captain changes are append-only selection revisions with source labels, concurrency checks and idempotency keys. All selected statistics refer to request dates or an explicitly labelled full week. Active-POD counts are labelled with their snapshot date.
- Drafts reserve **zero** capacity. Approval rechecks the preview fingerprint and exact team under the existing transaction locks. Changed workload/evidence requires **Recalculate selection**, review, and another confirmation. A changed request, catalogue or active policy requires a new fitment run.
- An approved Captain selection produces a new immutable proposal revision linked to the original real execution and selection. Decision, assignments, dated hours, provenance, disabled outbox entries and audit commit together. The original recommendation is not edited and no synthetic agent run is created.
- Rejection still requires a reason, records the selected draft reference, and creates no assignment. Existing automatic discovery/rerun behavior is unchanged.

**Unchanged:** catalogue, deliverable/skill mappings, employee assessments, scoring weights, eligibility rules, current Administrator-set utilization ceiling, privacy, login, closure/history, reporting and Excel export. **Manual override remains Phase 3**: no skill or utilization bypass is available here. Email sending remains disabled.

## Install locally after successful Phase 1

No new environment variables, login accounts, passwords or catalogue changes are needed. Keep your existing root `.env.local` and `backend/python/.env`.

1. Stop the local web, API and worker terminals with **Ctrl+C**. If any other worker/API uses this same cloud schema, stop it too. Do not run old and new worker versions together.

2. In SQL Developer, connected as `AI_POD_STAFFING`, pause execution and inspect outstanding work:

```sql
UPDATE staffing_runtime
SET agents_enabled='N', notifications_enabled='N',
    updated_by=USER, updated_at=SYSTIMESTAMP
WHERE runtime_id=1;
COMMIT;

SELECT execution_id, request_id, status
FROM agent_executions
WHERE status IN ('QUEUED','RUNNING');
```

The query must return no rows before the migration. If rows remain, stop here and inspect them; do not delete executions, proposals or assignments. Existing jobs need a deliberate finish/cancellation/recovery before cutover.

3. Open **`sql/oracle/mvp_phase2.sql`** and run the entire script with **F5**. It creates only:

   - `MVP_P2_REVIEWS` — immutable initial recommendation and conditional-option snapshot.
   - `MVP_P2_SELECTIONS` — immutable Captain selection revisions and recalculated previews.
   - `MVP_P2_DECISIONS` — final decision's original-proposal/selection linkage.
   - Three append-only triggers and supporting constraints/indexes.

   No existing table definition, catalogue row, policy, person, permission or business record is changed. Oracle DDL commits independently: if interrupted, keep services stopped, retain created objects, rerun this unchanged script and verify. Never run `setup.sql`, the original `phase2.sql`, or Phase 1 cleanup to recover this migration.

4. In PowerShell, run the **read-only** schema check:

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing\backend\python
.\.venv\Scripts\python.exe -m app.selection_schema --env-file .env
```

Expect `"verified": true`, `"writes": 0`. This checks columns, key relationships, JSON/positive-version constraints and append-only trigger source/status. If it fails, keep services stopped and inspect the mismatch; do not drop or overwrite tables. This is not a live agent or approval test.

5. Start the API and web in their normal terminals:

**Terminal 1 — API**

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing\backend\python
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8015 --env-file .env
```

**Terminal 2 — web**

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing
npm run dev -- --hostname 127.0.0.1
```

Open `http://127.0.0.1:3001` and sign in using an existing Captain account. If a port is already occupied, identify that listener/VM port forward; do not launch a second API on the same port.

6. When ready for OCI usage and proposal writes, re-enable database execution, keeping email off:

```sql
UPDATE staffing_runtime
SET agents_enabled='Y', notifications_enabled='N',
    updated_by=USER, updated_at=SYSTIMESTAMP
WHERE runtime_id=1;
COMMIT;
```

The Python environment must already have `STAFFING_WORKER_ENABLED=true`. For final approval, `STAFFING_DECISIONS_ENABLED=true` and an approved active policy are required, as before. Do not replace the active policy with an old demo policy.

**Terminal 3 — worker**

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing\backend\python
.\.venv\Scripts\python.exe -m app.worker --env-file .env
```

The worker can discover existing opted-in open requests. Starting it is not a read-only check.

## Local acceptance walkthrough

1. Create a complete Captain request using an existing catalogue deliverable, **24 person-hours, one Lead and two Members**, with a working-week schedule inside the loaded capacity horizon. Do not assume every deliverable has three qualified Leads; a smaller valid pool is an expected outcome.
2. In Agent Execution, verify actual **Supervisor → Analyst → Supervisor → Planner → Supervisor → review** events, or a truthful information/capacity failure. No assignments should exist yet.
3. In AI Fitment, verify the selected recommendation badges, up to two distinct alternatives for each group, exact total effort and the original recommendation summary.
4. Select another Lead, then a Member alternative and its replacement target. Verify that the whole selected POD, not just one card, gets recalculated. All normal selections must remain within the current configured utilization ceiling. Refresh the page: the saved selection must remain.
5. Open the same proposal in two tabs. Change the selection in one, then try the old selection/approval from the other. Expect a stale-selection error or a refreshed review, not overwritten state or silent approval.
6. Approve the reviewed selection once. Verify exactly the selected people in Requests/calendar/reports. Allocation changes only at approval, not while choosing candidates. Double-click/retry must not duplicate assignments.
7. For a different unapproved request, reject with a reason. Verify no assignments were created and the reason was retained. Lead and Member accounts must not access alternatives or the selection API; Administrator can inspect but cannot choose/approve as Captain.
8. If another change modifies workload between preview and approval, expect `SELECTION_REFRESH_REQUIRED`. Use **Recalculate selection**, inspect the returned metrics, then confirm again. If that exact team is no longer feasible, choose a currently feasible alternative or run fitment again; nobody is substituted silently.

These are live acceptance steps for the user after migration. Implementation tests use scripted models and Oracle transaction doubles. They do not send emails, import data or prove live Oracle locking/provider compatibility.

### Implementation verification (17 September 2026)

- Python: 468 passed, 268 subtests passed. Two pre-existing failures remain: the legacy demo-policy test expects an unapproved SQL template but the checked-in template is already set to approval; JWT key generation fails in this local OpenSSL entropy provider. Neither was changed for Phase 2.
- Frontend/integration: 138 passed. TypeScript and the Next.js application build passed.
- Visually inspected the rendered recommendation and alternative cards with synthetic, local-only data. This is not a live login/OCI/Oracle acceptance test.
- No live database migration, model invocation, account change or email was performed during implementation.

## Verification commands

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing\backend\python
.\.venv\Scripts\python.exe -m pytest tests/test_mvp_phase2.py tests/test_selection_schema.py tests/test_agent_budget.py tests/test_agent_handoff.py tests/test_phase3_runtime.py tests/test_phase4.py -q

cd C:\Users\smaikoti\Desktop\ai-pod-staffing
npm run test:selections
npm run test:agentic
npm run build
```

If rolling back application code is necessary, stop all services first and retain these tables/history. Do not reopen a pending Captain selection through an old client that only knows the original recommendation. Resolve the review explicitly with the matching version of the application; never remove the new history to make an old client work.
