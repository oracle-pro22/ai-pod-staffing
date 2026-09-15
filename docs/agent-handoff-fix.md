# Analyst-to-Planner handoff correction

## Cause

`RUN-7669648d91d64e3cb983afb1874d0194` was an automatically discovered execution for the existing `REQ-1047`, not a newly created request. Its Analyst asked the Captain for a proposed hour split and calculated allocation before those outputs existed. Shared instructions had incorrectly given the Analyst responsibilities belonging to the later planning stage. It also consumed the full twelve-call execution allowance before the Planner could run.

The OCI empty-text warnings were separate: valid function-tool responses intentionally have no answer text, but the upstream generic provider warned before extracting the tool calls.

## Changes

- Analyst instructions and tools now cover request context, candidate overview and rejection feedback. Once those three reads succeed, only the analysis completion tool remains available.
- The deterministic planning step computes team options, contribution hours, schedules and allocation. The Planner selects and explains a validated option; the Captain is never asked to calculate these outputs.
- Model-authored free-form questions cannot become new workflow prerequisites. The Analyst can select an essential missing business objective, expected outcome or project description from the actual request. The server checks that it is absent and supplies the UI question. Blank optional context is not an automatic blocker. Canonical request, mandatory capability, role, evidence and unknown-capacity checks remain in force.
- The total model-call cap stays at the lesser of the policy budget and twelve. The Analyst receives at most six calls and cannot spend the final two calls needed for planning. Policies below six calls are rejected before execution. Separate committed stage counters survive retries and uncertain commits.
- Completed Analyst reads are checkpointed. A retry reconstructs those read-only observations from the same frozen evidence snapshot without spending model calls to reread them. No model text or mutating tool is replayed.
- An instance-local OCI adapter avoids the misleading empty-text warning only for well-formed tool-only responses. Truly empty responses, malformed calls and unrelated warnings remain visible.

No UI redesign, SQL migration, environment change, data import, policy approval, assignment or email change is required. `staffing-tools-v4`, `staffing-engine-v3`, and checkpoint format `3` distinguish these contracts; the scheduling validator is unchanged.

## Verification

A live read-only Oracle + OCI check on 13 September 2026 used `REQ-1047` revision 3 with the installed `staffing-demo-v2` policy. Analyst: four calls, Planner: two calls, total: six tool calls, approximately 24.5 seconds. No clarification or empty-text warning occurred.

| Person | Proposed role | Hours | Current → projected allocation |
| --- | --- | ---: | ---: |
| Elena Garcia | POD Lead | 8 | 60% → 80% |
| Alex Rivera | POD Member | 8 | 50% → 70% |
| Mara Bennett | POD Member | 8 | 55% → 75% |

These results are from that evidence snapshot, not hard-coded choices. The approved policy permits a Lead to contribute in a Member slot. This one-week request has the same request-window and busiest-week denominator.

**Database writes: zero. Emails: zero.** This check exercised actual tool-calling agents and deterministic calculations, but did not publish a proposal or approve an assignment.

Offline regressions cover the original incorrect hour-split question, repair and handoff, genuine missing inputs, missing capacity, meaningful 24-hour allocation, model-budget conservation, retry recovery, old checkpoints, transaction boundaries and OCI warning handling. Final Python result: **333 passed, 195 subtests passed, 1 failed**. The failure is a pre-existing local OpenSSL entropy error in RSA key generation for `test_valid_jwt_and_claim_validation`; that unrelated authentication test was not disabled or changed. Ruff passed for the changed Python files.

## Use the fix locally

1. Stop the existing Python API and worker with `Ctrl+C` in their respective PowerShell windows. Restart both so their prompt/checkpoint versions match. Next.js can stay running.
2. In the **API** window:

   ```powershell
   cd C:\Users\smaikoti\Desktop\ai-pod-staffing\backend\python
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8015 --env-file .env
   ```

3. In the **worker** window:

   ```powershell
   cd C:\Users\smaikoti\Desktop\ai-pod-staffing\backend\python
   .\.venv\Scripts\python.exe -m app.worker --env-file .env
   ```

4. As the request's Captain, create a new sample request, or select `REQ-1047` and use **Re-run**. Expect a **new execution ID**. Existing terminal execution history remains unchanged; it is not automatically retried. An old queued/in-flight checkpoint may finish with `CHECKPOINT_VERSION` and also needs a new run. Do not edit or delete checkpoints in SQL.
5. A feasible request should progress through analysis, deterministic validation and planning to `READY_FOR_REVIEW`. Inspect the proposed POD and calculated hours. Captain approval is still required for final assignment.
