# Phase 3 — staffing agents and durable proposal execution

Phase 4 is now implemented; see `docs/backend-phase4.md` for the live frontend and Captain decision
integration. Statements below about approval/UI being unimplemented describe the phase-3 boundary.

## What changed

The Python backend now implements the real proposal workflow. No frontend files, existing SQL
migration fingerprints, real role assignments, runtime flags or credentials were changed by this implementation.
Your successfully installed phase-2 tables are reused; **do not rerun setup.sql or drop tables**.

1. The worker discovers eligible opted-in requests, or an authenticated Captain queues a run through the API.
2. Oracle stores the execution, input revision, policy version and idempotency key.
3. The Request & Evidence Analyst calls read-only evidence tools and identifies genuine clarification needs.
4. Python enumerates eligible teams, distributes hours and validates mandatory capabilities and capacity.
5. The POD Planner & Explainer calls tools to inspect the validated options, selects an existing plan ID and explains it.
6. The backend rechecks current inputs and atomically stores the proposal, members, execution outcome and audit event.
7. The outcome is READY_FOR_REVIEW, not a final assignment.

**Not yet implemented:** Captain approve/reject endpoints, final assignment writes, frontend consumption of
these new endpoints, notifications and email dispatch. These remain the next integration phases.
Captain approval will be final; there is no Lead/Member acceptance window. Rejection will require a reason.
The worker can already read existing rejection history for the next proposal.

## Current automatic-trigger boundary

This phase provides durable polling intake for requests with `agent_enabled='Y'`, a real
`responsible_captain_id`, valid Captain identity/permissions, an open status and no execution of their current revision.
Polling runs every five seconds by default. A failed/information-needed terminal run is **not** repeatedly
auto-enqueued; a deliberate new idempotency key or a corrected request revision is required.

The existing Next.js request-save route has NOT been switched to this service. Its demo role dropdown
does not establish identity, and Request source is not assumed to be the responsible Captain. Existing
requests with missing Captain/schedule/capacity evidence are not automatically staffed.
The next phase must connect the authenticated request writer and UI; ideally request + queue creation
will share a transaction, with this polling intake retained as reconciliation.

## Implementation map

| File under `backend/python/app` | Responsibility |
| --- | --- |
| `evidence.py` | Consistent Oracle evidence snapshot: request, catalogue, roles, self-ratings, deliverable experience, verified daily capacity and past rejection reasons |
| `planning.py` | Deterministic bounded team search, hours distribution and scoring |
| `agents/staffing.py` | Two OCI tool-calling agents, structured completion, reference checks and closed tool allowlists |
| `workflow.py` | LangGraph collect → analyse → plan → publish, with terminal branches |
| `execution_store.py` | Idempotent queueing, leases, checkpoints, retries, publication transaction and scoped reads |
| `worker.py` | Separate durable worker process; never automatically launched by the web server |
| `main.py` | Authenticated execution/proposal endpoints; persisted policy endpoint |

The operational tools are `get_request_context`, `get_candidate_overview`, `get_person_evidence`,
`get_person_capacity`, `get_rejection_feedback`, `get_validated_options`, `complete_analysis`, and
`complete_plan`. The analyst cannot call planner completion tools. Neither agent has SQL, role-editing,
assignment, approval, shell, internet or email tools. Tool arguments cannot override the server-selected request.

LangGraph controls stage transitions. Durable stage snapshots are stored explicitly in Oracle
`AGENT_EXECUTIONS.checkpoint_json` and `evidence_snapshot_json`; this is **not** a claim of a built-in
LangGraph Oracle checkpointer. Completed stages are reused after restart. An interrupted agent stage
can run again, but its previous model/tool usage remains charged to the persisted budget.
The APIs expose short progress events, not raw prompts, model scratchpads, leases or full candidate snapshots.

## Initial staffing rules and limits

- Only active people with eligible roles covering the full request period are candidates.
- Project Manager capability is role-derived, never inferred from job titles or self-ratings.
- Mandatory capability thresholds must be met across the proposed POD.
- Deliverable experience and interest contribute to ranking; interest alone does not establish proficiency.
- SUPPORTED experience needs an independent/end-to-end capable teammate on the same deliverable.
- Current draft weights: skill 50%, deliverable experience 30%, remaining capacity 15%, interest 5%.
  The worker reads the stored policy, rather than silently substituting these defaults.
- Candidate working hours and complete verified daily capacity must exist. Unknown/stale capacity is not free time.
- Confirmed assignment hours + external work count as committed. Pending proposals reserve nothing.
- Hours are shared across the required Lead/Member slots subject to capacity, then spread evenly over
  Mon–Fri in 0.01-hour units. The total is exactly conserved. Each selected slot has positive hours.
- Each person currently shares the requested deliverables with role-specific responsibilities.
  Per-deliverable specialist scheduling, variable daily patterns and minimum meaningful slot effort are future refinements.
- Allocation = (confirmed + external + proposed hours) / available working hours × 100 for each full week.
  Absence reduces the denominator; individual days and the weekly limit must both pass.
  The model cannot overwrite the calculated hours, scores or maximum allocation.
- Default search: at most 60 candidates, 2,000 team combinations, retain three best validated options.
  A bounded search is not a global optimizer. SEARCH_LIMIT is distinct from NO_FEASIBLE_POD.
  A no-feasible outcome is only for this scheduling model and the available evidence.
- Shared execution budget: at most min(policy maximum steps, 12) model calls, 40 tool calls,
  and up to three queue attempts. OCI output defaults to 2,048 tokens per call.

Names, location and email are not passed as candidate-ranking attributes. Free-text objectives,
experience and rejection reasons remain untrusted context. Prompt instructions and hard tool/output
validation limit their influence, but a human must still review generated explanations for factual accuracy.

## 1. Install and test dependencies

Use Python 3.12. From the project root:

```powershell
cd backend/python
uv sync --python 3.12
uv run python -m unittest discover -s tests -v
```

The first successful sync must create `uv.lock`. Review and commit it; then use `uv sync --locked`
for deployment. Package-index access timed out during implementation, including the elevated retry.
There is currently no resolved lockfile. Framework tests explicitly skip if dependencies are missing;
**a test run with skipped framework modules is not full acceptance**. Use an approved package mirror
if required; do not disable TLS checks.

## 2. Configure the Python service

Create its environment file only if absent:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Set the existing Oracle wallet/password/service alias and OCI config/model/provider settings.
Python loads this `.env` explicitly; it does not inherit Next.js `.env.local` automatically.
Use absolute wallet/private-key paths valid on this host. Do not upload secrets or put credentials in Git.

New settings:

```ini
STAFFING_WORKER_ENABLED=false
STAFFING_POLICY_VERSION=staffing-v1-draft
STAFFING_POLL_SECONDS=5
STAFFING_LEASE_SECONDS=180
STAFFING_MAX_CANDIDATES=60
STAFFING_SEARCH_LIMIT=2000
OCI_MAX_OUTPUT_TOKENS=2048
LANGSMITH_TRACING=false
LANGCHAIN_TRACING_V2=false
```

For local fixture testing only, use `BACKEND_ENV=local`, `BACKEND_AUTH_MODE=local`, a random
`BACKEND_LOCAL_TOKEN` of at least 32 characters, and
`BACKEND_LOCAL_SUBJECT=seed:backend-p2:P-900101` (the seeded Captain). This is an explicit local
test credential, not a real employee login. Every call still resolves roles from Oracle.
Keep the API bound to loopback; never expose local-auth mode on a shared/public interface.

Production requires trusted OIDC configuration and an APPROVED policy. The DRAFT policy is allowed
only for non-production proposal testing; do not approve it just to bypass the deployment gate.
Phase 3 contains no assignment writer, regardless of environment.

## 3. Check Oracle and OCI without staffing writes

Use the phase-1 commands in `backend/python/README.md`:

```powershell
uv run python -m app.cli database --env-file .env
uv run python -m app.cli oci --env-file .env --live
```

`database` is read-only. `oci --live` makes an explicitly requested, billable model/tool-call test
with fixed arithmetic data, not employee evidence. The configured OCI model/provider must pass it;
successful rephrasing does not prove tool-call support.

## 4. Enable proposal testing explicitly

Only after configuration and checks succeed, change `STAFFING_WORKER_ENABLED=true` in the Python
environment. Then run this block with **F5** in an AIPOD SQL Developer worksheet logged in as
AI_POD_STAFFING. It changes a runtime switch, not table structure:

```sql
SET SERVEROUTPUT ON;
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK;
ALTER SESSION DISABLE PARALLEL DML;
ALTER SESSION DISABLE PARALLEL QUERY;
BEGIN
  IF USER <> 'AI_POD_STAFFING'
     OR SYS_CONTEXT('USERENV','CURRENT_SCHEMA') <> 'AI_POD_STAFFING' THEN
    RAISE_APPLICATION_ERROR(-20001, 'Wrong schema. Stop.');
  END IF;
  UPDATE AI_POD_STAFFING.STAFFING_RUNTIME
     SET agents_enabled='Y', updated_by=USER, updated_at=SYSTIMESTAMP
   WHERE runtime_id=1 AND notifications_enabled='N';
  IF SQL%ROWCOUNT <> 1 THEN
    RAISE_APPLICATION_ERROR(-20002, 'Runtime row missing or notifications unexpectedly enabled.');
  END IF;
  COMMIT;
END;
/
```

Manual API queueing below does not require updating `REQUESTS.agent_enabled`.
For a separate automatic-intake test, explicitly opt in only the three phase-2 fixtures:

```sql
BEGIN
  IF USER <> 'AI_POD_STAFFING'
     OR SYS_CONTEXT('USERENV','CURRENT_SCHEMA') <> 'AI_POD_STAFFING' THEN
    RAISE_APPLICATION_ERROR(-20001, 'Wrong schema. Stop.');
  END IF;
  UPDATE AI_POD_STAFFING.REQUESTS SET agent_enabled='Y'
   WHERE request_id IN ('REQ-900101','REQ-900102','REQ-900103')
     AND staffing_seed_batch='AIPS_BACKEND_P2_SEED_V1'
     AND responsible_captain_id='P-900101' AND agent_enabled='N';
  COMMIT;
END;
/
```

This UPDATE increments each affected request revision by design. Run it **before** queueing, not
mid-run. Do not opt in all existing requests. Do not rerun seed cleanup after creating governed history;
preserve proposals, events and audit records during this testing window.

## 5. Start API and worker

Terminal 1, from `backend/python`:

```powershell
uv run uvicorn app.main:app --host 127.0.0.1 --port 8015 --env-file .env
```

Terminal 2, same directory, to run continuously:

```powershell
uv run python -m app.worker --env-file .env
```

Or process at most one available job and exit:

```powershell
uv run python -m app.worker --env-file .env --once
```

`--once` discovers opted-in requests first, then handles one eligible queued/expired-lease job.
It does not guarantee a particular request when several are queued. Keep Next.js running using its
existing command if you need the current UI; `npm run build` alone does not run this Python worker.
API and worker each have their own bounded Oracle pool; default combined maximum is four connections,
in addition to Next.js. On the VM, use separate app-specific process supervision after local acceptance.

## 6. Queue and inspect a fixture through the API

For local testing, place your configured test token into the terminal's `$env:STAFFING_TEST_TOKEN`
without printing it or committing it. Then:

```powershell
$staffingHeaders = @{ Authorization = "Bearer $env:STAFFING_TEST_TOKEN" }
$staffingBody = @{ idempotency_key = "phase3-900101-" + [guid]::NewGuid().ToString("N") } | ConvertTo-Json
$staffingRun = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8015/v1/requests/REQ-900101/executions -Headers $staffingHeaders -ContentType application/json -Body $staffingBody
$staffingRun
Invoke-RestMethod -Uri "http://127.0.0.1:8015/v1/executions/$($staffingRun.execution_id)" -Headers $staffingHeaders
```

Reuse the **same** body/idempotency key after an uncertain HTTP response. A new key means a deliberate
new run, although an already active run for the same request revision is reused.
Repeat the GET to inspect status. `events` contains at most 100 records; use `?after=<next_after>`
for subsequent progress. When `proposals` contains an ID:

```powershell
$staffingStatus = Invoke-RestMethod -Uri "http://127.0.0.1:8015/v1/executions/$($staffingRun.execution_id)" -Headers $staffingHeaders
$staffingProposalId = $staffingStatus.proposals[0].proposal_id
Invoke-RestMethod -Uri "http://127.0.0.1:8015/v1/proposals/$staffingProposalId" -Headers $staffingHeaders
```

The API includes selected people/names, role, planned hours, calculated scores/factors, rationale,
evidence references and request-revision staleness. It does not expose lease tokens or raw checkpoints.
The responsible Captain can access their records; Administrator reads require explicit FULL permission.
Leads and Members do not gain access to pending proposals just by being suggested.

Repeat with REQ-900102 and REQ-900103 using distinct keys. With unchanged seed data/rules:

| Fixture | Intended result |
| --- | --- |
| REQ-900101 | A feasible proposal READY_FOR_REVIEW; actual OCI explanation must still be reviewed |
| REQ-900102 | NO_FEASIBLE_POD under the current 120-hour schedule and verified capacity |
| REQ-900103 | NEEDS_INFORMATION for the unresolved mandatory custom capability |

The analyst can stop for genuine business clarification, and dependency failures can produce FAILED;
fixtures do not force the model to return a predetermined success. The seed dates/capacity window are
fixed when seeded; do not use expired fixtures as evidence of current operational availability.

## Recovery and acceptance checks

- **Worker crash:** RUNNING lease expires (default 180 seconds), another worker claims it with a new
  token. Old tokens cannot save or publish. Model/tool counters and completed stages survive restart.
- **Temporary OCI failure:** known connection/timeouts and HTTP 429/5xx receive bounded backoff.
  Invalid tool calls/output fail without silently generating fake recommendations.
- **Database failure / uncertain commit:** the worker does not assume a write rolled back. Inspect
  the execution ID; terminal jobs are not reclaimed, while expired RUNNING jobs can resume.
- **Changed input:** publication compares current request, catalogue, policy and selected people/versions
  and capacity; changed snapshots end SUPERSEDED and require a new run. A later change is still
  revalidated at future Captain approval; a published proposal does not reserve capacity.
- **Atomic publication:** members, proposal status, event and audit commit together. A failed member insert
  rolls back the publication, including any superseding of a previous READY proposal.
- **No final writes:** verify no `POD_ASSIGNMENTS`, `ASSIGNMENT_DAYS`, `APPROVAL_DECISIONS` or
  `NOTIFICATION_OUTBOX` records were created by these runs. This code does not write to those tables.
- **Stop:** Ctrl+C stops this worker after its bounded current operation. To disable all staffing workers,
  set only `AI_POD_STAFFING.STAFFING_RUNTIME.agents_enabled='N'` in the correct schema and commit.
  Do not delete jobs or issue broad process-kill commands. In-flight OCI calls may finish, but publication
  checks the switch again. Re-enabling later permits expired jobs to resume.

Run `sql/oracle/phase3_verify.sql` for read-only state inspection after testing.
Do not enable production until full framework tests, real Oracle queue/lease/rollback checks, the OCI
tool smoke test and all three fixture journeys have passed. Offline mocks cannot establish Oracle locking
behavior or provider compatibility. Redacted failures require an operator to inspect the correlated worker log.

## Verification in this workspace

2026-09-11: 76 offline tests passed, with three runtime/framework modules explicitly skipped because
PyPI dependency installation timed out. Existing Next.js tests passed (30 skills + 25 application).
Python syntax compilation passed. Ruff could not run because it is not installed. No live Oracle/OCI calls,
runtime activation, fixture execution, assignments or emails were performed here.

The orchestration uses the documented [LangGraph graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)
and [LangChain OCI integration](https://docs.langchain.com/oss/python/integrations/chat/oci_generative_ai).
Actual compatibility of the resolved package versions and your selected model remains a deployment gate.
