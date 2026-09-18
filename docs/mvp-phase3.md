# MVP Phase 3 — Captain manual override

Phase 1 login/roster and Phase 2 Supervisor/alternatives remain intact. This release adds an explicit, Captain-owned manual workflow; it does not reset data or change catalogue, deliverables, mappings, employee evidence, normal ranking, privacy, closure or reporting formulas.

## Confirmed rule

For each person **explicitly marked manual**:

**Manual POD utilization = (counted existing POD hours + new POD hours) / contracted working hours × 100.**

- Hard maximum **100%**, enforced against exact hours for each day, request period and complete touched week. Not a rounded display check. A 40-hour person with 24 existing POD hours can receive at most 16 new hours in that week, subject to the dated daily schedule.
- Ignore leave and external commitments **for this manual scheduling decision**. Retain their records unchanged. Use the person's own weekly hours; Monday–Friday daily capacity is weekly hours / 5. Do not invent work on weekends, unknown working patterns or missing/stale ledgers.
- Bypass skill/experience suitability and the normal configurable utilization ceiling (initially 85%). Preserve correct active role/account, requested headcount, unique people, valid dates, meaningful positive contributions and the exact total effort.
- Manual choices have **no fit score** and no fabricated AI rationale. Recorded capability gaps and bypassed checks are preserved.
- People **not** marked manual still satisfy normal eligibility, capacity, leave, external-work and support rules. Changing another person's slot does not grant them an exception.

The preview also shows **overall planned workload**, using the unchanged normal formula that counts external work and reduces capacity for leave. That separate figure can exceed 100%, or be undefined on full leave. It is never clipped or presented as the manual authorization limit. This is planned workload, not timesheet/actual hours.

## Workflow

1. Save a valid request. A successful OCI run is not necessary for manual drafting; a current authoritative request, approved policy at approval, role/account and workload records are necessary.
2. Open AI Fitment as the request's responsible Captain and choose **Manual override**. Start from the saved recommended/alternative team, or pick the entire team if no usable recommendation exists.
3. Changing a person marks that slot manual. You can explicitly override an existing selected person as well. New choices cannot be submitted as ordinary validated alternatives through this endpoint.
4. **Calculate preview** pins those people and deterministically divides/schedules the full effort. If it cannot fit, the draft is not saved; choose different people/dates/effort. The system never substitutes someone or silently broadens an exception.
5. Review individual hours, POD-only before/after percentages, peak week, ignored leave/external hours and overall reported workload. Changes are immutable saved draft revisions; drafts reserve zero capacity.
6. Approve through the final confirmation. No Lead/Member acceptance and no mandatory override reason. Rejection still requires a nonblank reason.
7. Approval reloads evidence, locks the request and selected people, checks the current policy and exact snapshot, then commits proposal, decision, assignments/days, audit/provenance, resolution and disabled notification arrangements together. Changed workload/evidence requires recalculation and another review.
8. A saved manual draft prevents automatic/explicit fitment reruns and normal-selection approval from replacing that choice. **Discard manual draft** records a resolution without making assignments and permits fitment again. Wait for an already queued/running job to finish before starting a manual draft; this feature does not terminate jobs.

Every call verifies the signed-in Captain and current request ownership. Lead, Member and standalone Administrator cannot preview or approve manual choices. Existing Administrator visibility of final staffing results is unchanged. Direct API calls cannot set arbitrary hours, scores, a higher ceiling or actor identity.

## Local installation — do this before restarting

No new `.env` variables or data import are needed. Preserve both current env files. `STAFFING_DECISIONS_ENABLED=true` is needed for final decisions, as before. Manual previews themselves make no model calls and do not require a running worker.

1. Stop web, API and worker with **Ctrl+C**. Stop any VM services using this same Oracle schema too. Do not mix old and new application versions.
2. In SQL Developer as `AI_POD_STAFFING`:

```sql
UPDATE staffing_runtime
SET agents_enabled='N', notifications_enabled='N',
    updated_by=USER, updated_at=SYSTIMESTAMP
WHERE runtime_id=1;
COMMIT;

SELECT execution_id, request_id, status
FROM agent_executions WHERE status IN ('QUEUED','RUNNING');
```

If the query returns jobs, resolve their lifecycle before continuing; do not delete history or forcibly edit statuses as a workaround.

3. Open **`sql/oracle/mvp_phase3.sql`** and run the entire script with **F5**. It:

   - Saves original affected table DDL in `MVP_P3_DDL_BACKUP`.
   - Adds `MVP_P3_DRAFTS` and `MVP_P3_RESOLUTIONS` with immutable-history triggers and relational constraints.
   - Adds proposal `ORIGIN_TYPE` (existing rows default to AGENT) and member `MANUAL_FLAG` (existing rows default to N).
   - Allows a NULL execution link **only for MANUAL-origin proposals**, retaining the real execution FK for agents and adding a request FK. A manual decision does not invent a successful agent execution.
   - Allows a NULL score **only for manual members**. Normal members still require a real numeric score. Existing scores and published evidence are retained.
   - Adds guards for frozen proposal origin and manual-member provenance without replacing existing immutability/decision/assignment triggers.

   These intentional schema changes mean the original backend `phase2_verify.sql` DDL fingerprints no longer describe the complete upgraded schema. Use the Phase 3 verifier below, which also verifies the MVP Phase 2 tables and retains existing protection checks. Do not rerun old migrations to “repair” the intentional nullable fields.

4. Verify from PowerShell (read-only):

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing\backend\python
.\.venv\Scripts\python.exe -m app.manual_schema --env-file .env
```

Expect `"verified": true`, `"manual_limit_pct": 100`, `"writes": 0`, `"model_calls": 0`.

Oracle DDL commits independently. On interruption/error, keep services stopped, retain created objects/backups, rerun the unchanged Phase 3 script and verify. Never run `setup.sql`, roster cleanup, table drops or a broad reset. A mismatch needs inspection, not overwriting. Do not roll application code back while pending manual drafts exist: older workers do not understand their protection.

## Start locally

Terminal 1 — API:

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing\backend\python
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8015 --env-file .env
```

Terminal 2 — web:

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing
npm run dev -- --hostname 127.0.0.1
```

Open `http://127.0.0.1:3001`. Login with the existing Captain account. Manual drafting/approval can be tested without starting the worker. Keep email off.

For agent testing too, enable execution deliberately:

```sql
UPDATE staffing_runtime SET agents_enabled='Y', notifications_enabled='N',
    updated_by=USER, updated_at=SYSTIMESTAMP WHERE runtime_id=1;
COMMIT;
```

Terminal 3 — worker (permits OCI usage and durable proposals):

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing\backend\python
.\.venv\Scripts\python.exe -m app.worker --env-file .env
```

## Acceptance checklist

- New valid request, no model call: select the full team manually, calculate, refresh, approve once. Confirm no fabricated execution and exactly one assignment per chosen person.
- Existing recommendation: override one person; confirm all other slots still obey normal rules. Try a high-load/unqualified person from the full active role pool, not only the AI shortlist.
- Known 40-hour week / 24 POD-hour person: 16 additional hours succeeds at 100%; even 16.01 cannot fit for a single-person POD. For a larger team the deterministic split can legitimately give that person fewer hours and give other selected people the remainder.
- Leave/external work: manual POD limit ignores those inputs, but the preview exposes them and overall workload remains truthful. Do not alter source leave to make a demo pass.
- Change assignments between preview and approval: approval must request recalculation, never quietly accept different percentages.
- Two tabs: a stale draft cannot overwrite or approve a newer revision. Duplicate submit/retry creates no duplicate assignments. Discard is audited and makes no assignments.
- Reject with a reason; no assignment. Verify the original recommendation and selection history remain available.
- Verify Member/Lead/Admin boundaries, profile/calendar/report/Excel totals, and normal/early closure preserving historical hours and releasing only future scheduled work.

Offline tests use synthetic models/Oracle command doubles. Live Oracle DDL, cross-session locks, live OCI and the full three-process acceptance rehearsal are separate deployment checks; they are not implied by unit-test success. No live data changes or emails are performed by the verification commands.

Local verification on 17 September 2026: the targeted Phase 2/3 selection, manual-schema and decision suites passed **81 tests** (54 subtests). The full Python suite passed **500 tests** (291 subtests), with two pre-existing failures: the legacy demo-policy SQL has its approval constant set to TRUE while its test expects the original FALSE default, and this machine's OpenSSL provider cannot obtain sufficient entropy for the JWT test's RSA key generation. Those unrelated settings were not changed. All **145 Node tests** and the Next.js production build/type check passed. The manual preview was visually checked with synthetic data, not a live account/database approval.

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing\backend\python
.\.venv\Scripts\python.exe -m pytest tests/test_mvp_phase3.py tests/test_manual_schema.py tests/test_mvp_phase2.py tests/test_phase4.py
cd C:\Users\smaikoti\Desktop\ai-pod-staffing
npm run test:selections
npm run test:agentic
npm run build
```
