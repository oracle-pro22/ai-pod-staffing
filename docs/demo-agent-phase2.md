# Demo improvement — Phase 2: correct agent plans

This is Phase 2 of the **three-phase demo improvement**, not the older backend schema migration. Phase 1's populated people, roles, skills, capacity and confirmed projects are retained. The four-profile entrance/persona chooser is covered by the [Phase 3 local run guide](demo-personas-phase3.md); use that guide for the current startup configuration.

If an execution asks for a proposed hour split before planning, see the [Analyst-to-Planner handoff correction](agent-handoff-fix.md). That fix needs an API/worker restart and a new run, not SQL or another data import.

## What changed

1. **Real available-day scheduling.** The previous planner distributed every person's effort over every weekday, including leave. A Friday absence could cap a candidate at 0.04 hours, with one hundredth on each preceding day. The new planner subtracts leave, operational commitments and confirmed project work first, then schedules only on available dates.
2. **Meaningful contributions.** Every selected person receives at least the greater of 1 hour and half an equal team share. For 24 person-hours and three people, the floor is 4 hours/person; an unconstrained team receives 8 each. The exact total is conserved to hundredths. An effort estimate too small for the requested POD asks for clarification instead of padding the team with tiny assignments.
3. **Relevant, evidenced people.** Effective profile, skills, deliverable experience, interests and actual capacity are checked. Unexplained skill ratings do not earn proficiency points; interest is a preference, not proof of capability. Project Manager is role-derived. Learners/supported contributors require an experienced teammate on the same deliverable. Each deliverable needs an assigned experienced end-to-end owner or coverage of its mapped request-required capabilities among its actual assignees.
4. **Calculated scores and clear percentages.** Skills/deliverables/capacity/interest contribute 50/30/15/5 points. V2 team ranking and the existing factor chart weight each person's score by assigned effort. The review distinguishes allocation during the request period from the busiest complete week. Missing capacity never becomes zero. The card design is retained; metric labels are more precise.
5. **Two tool-calling agents remain.** The Analyst reads request and evidence. The Planner chooses among bounded, independently validated POD options. It cannot invent employees, hours or scores, approve a POD, or write SQL. Required references include the request, policy and every selected person's evidence/capacity. The review's numerical explanation is generated from calculated facts, not model prose.
6. **Same schedule through approval.** Proposal factors store the exact dated plan. Publication checks fresh evidence and recalculates metrics. Captain approval rechecks and saves those exact dates. Changed leave/capacity/roles cause a new review, not a silent redistribution. Approval is final; rejection requires a reason. No employee acceptance step or email sender was introduced.

The reviewed policy still permits a POD Lead to contribute in a Member slot. Captains and the standalone Administrator do not become staffing candidates. Search is bounded, and reports whether it examined all combinations; it does not claim a global optimum beyond that bound.

## Verified against your Oracle data

On 13 September 2026, the read-only check for `REQ-1047` (14–18 September, 24 hours) examined all 135 eligible team combinations. The real OCI Analyst and Planner also completed successfully: 8 model calls and 8 tool calls in approximately 33 seconds.

| Selected person | Assignment role | New hours | Before → projected allocation |
| --- | --- | ---: | ---: |
| Elena Garcia | POD Lead | 8 | 60% → 80% |
| Alex Rivera | POD Member | 8 | 50% → 70% |
| Mara Bennett | POD Member | 8 | 55% → 75% |

Each receives 1.6 hours/day. These are evidence-based results from that snapshot, **not hard-coded names**; later approvals, leave or evidence updates can change them. In this one-week example the request-period and peak-week denominators coincide. An 8-hour one-day request in a 40-hour week instead gives 100% during that day but 20% for the full week.

The positive fixture `REQ-900101` returned options. The capacity-pressure fixture `REQ-900102` returned `NO_FEASIBLE_POD`; the incomplete-capability fixture `REQ-900103` returned `NEEDS_INFORMATION`.

These checks used the v2 policy **in memory, still DRAFT**. No database policy was installed/approved, no job queued, and no proposal, assignment or email was written. Runtime agent and notification switches remain `N`.

## What to do now

### 1. Install the new policy (do not reseed)

Follow [the short policy instructions](demo-phase2-policy.md) using [demo_phase2_policy.sql](../sql/oracle/demo_phase2_policy.sql). Run it with **F5** in SQL Developer as `AI_POD_STAFFING`; it creates a separate draft. After reviewing the rules, set `approve_policy` to `TRUE`, set `approval_operator` to your name, and rerun the same file. Expected final status: `staffing-demo-v2`, `APPROVED`.

There is **no new table or column**. The script adds one policy, four eligibility rules, one load-guardrail row and one scoring-weight row. It does not rewrite existing policies, people or projects. Errors roll back this transaction. Keep all earlier backups; do not run `setup.sql`, reseed, or delete migration/history rows.

### 2. Update the Python configuration

In `C:\Users\smaikoti\Desktop\ai-pod-staffing\backend\python\.env` set these once:

```dotenv
STAFFING_POLICY_VERSION=staffing-demo-v2
STAFFING_WORKER_ENABLED=true
STAFFING_DECISIONS_ENABLED=true
```

Keep your working OCI/database settings, matching local tokens, and `BACKEND_LOCAL_SUBJECT=demo:d1:P-009` for Indranie. Do not type that subject by itself in PowerShell. The existing Next.js `.env.local` configuration does not need another change for this phase. Do not configure organization login merely to run the local version.

### 3. Check the installed policy without starting agents

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing\backend\python
.\.venv\Scripts\python.exe -m app.demo_agent_check --env-file .env --request-id REQ-1047
```

Expected: `OPTIONS_AVAILABLE`, `policy_source: database`, `policy_status: APPROVED`, and `writes: 0`. This is a deterministic read-only calculation, not a saved recommendation. To check before installing the policy, append `--preview-policy`; the output explicitly says `in-memory-preview` and `DRAFT`.

### 4. Enable database execution when ready to test

In SQL Developer, after policy approval and while services are still stopped:

```sql
UPDATE staffing_runtime
SET agents_enabled='Y', notifications_enabled='N',
    updated_by=USER, updated_at=SYSTIMESTAMP
WHERE runtime_id=1;
COMMIT;
SELECT agents_enabled, notifications_enabled
FROM staffing_runtime WHERE runtime_id=1;
```

Expected `Y / N`. Starting the worker permits OCI usage and durable proposal writes. It will also pick up previously opted-in, unprocessed requests: **REQ-1047 is currently one of them**. A proposal does not reserve capacity or become an assignment until the Captain approves.

### 5. Start the three processes in separate PowerShell windows

**Python API:**

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing\backend\python
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8015 --env-file .env
```

**Next.js:**

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing
npm run dev -- --hostname 127.0.0.1
```

**Worker:**

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing\backend\python
.\.venv\Scripts\python.exe -m app.worker --env-file .env
```

Open `http://127.0.0.1:3001` consistently. Do not start duplicate processes on ports 3001/8015. Old engine checkpoints cannot resume under this release; use a new execution/re-run, not database edits to old history.

### 6. Demonstrate the journey

- As the configured Captain, review `REQ-1047` when its new run reaches **Ready for review**, or create a new request with New Service Launch → Sales Guide (deck), GTM SME, one Lead + two Members, and 24 person-hours (3 working days). For the present dataset use 14–18 September 2026; if testing later, choose future dates inside the populated capacity horizon ending 8 November 2026.
- Saving a new request automatically starts staffing. Check Agent Execution, then AI Fitment. Hours must add to 24 and percentages must come from dated capacity, not the old cached People percentage.
- Reject one proposal with a reason and re-run to demonstrate feedback. There is no capacity reservation from rejection or a pending proposal.
- Approve the intended proposal to create real confirmed assignments. The assigned Lead/Member views and allocation calendar should reflect those assignments. The separate persona entrance/switcher is Phase 3; this phase does not add it.
- New competing work or leave before approval can invalidate a proposal. Re-run it; do not expect the application to silently overbook someone. Notification intents remain disabled and no emails are sent.

Approve only the proposal you intend to demonstrate: repeating approvals on additional requests legitimately consumes more capacity and changes later recommendations.

## Verification notes

- 56 new Python tests cover meaningful hours, leave-aware scheduling, exact totals, local deliverable coverage, frozen approval dates, policy compatibility, grounding/version checks and the read-only CLI.
- Full Python suite: 269 of 270 tests passed. The existing JWT test fails while generating an RSA key due to this machine's OpenSSL entropy-source error; it also fails in isolation and outside the sandbox. Authentication code and that test were not bypassed or changed.
- 55 application/agentic JavaScript tests pass; TypeScript type-check passes.
- New policy SQL passed live Oracle compile-only parsing, not execution. Final Oracle publication/approval is an operator acceptance test after the policy is installed; it was not simulated as a completed database write.
- OCI may warn that a tool-only response has no text; actual tool calls passed validation. A warning alone is not an execution failure.

Key code: `app/capacity.py`, `app/rules.py`, `app/planning.py`, `app/agents/staffing.py`, `app/agents/grounding.py`, `app/execution_store.py`, `app/decisions.py`, `app/demo_agent_check.py` under `backend/python`. Existing review cards consume saved metrics; no alternate UI or additional agent service was created.
