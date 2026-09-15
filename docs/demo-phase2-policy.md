# Phase 2 scheduling policy

This installs a new demonstration policy, `staffing-demo-v2`, without changing the existing schema or previously saved projects. It does not enable the worker, call OCI, or send email. The original `staffing-v1-draft` and approved `staffing-baseline-v1` remain unchanged.

## Rules to review

- Assign work on the person's available weekdays, respecting leave, external commitments and existing confirmed assignment hours.
- Every selected person must receive at least **the greater of 1 hour and 50% of an equal team share**. For a 24-hour request with three people, each receives at least 4 hours. If the requested team cannot receive meaningful work, return no feasible POD; do not insert a token contribution such as 0.04 hours.
- Preserve the exact requested person-hours across all members and dates. Pending proposals do not reserve capacity.
- Do not exceed 100% of absence-adjusted weekly capacity or any day's remaining hours. A completely unavailable week can have zero proposed work; it cannot receive work.
- Eligible Lead profile: `POD_LEAD`. Eligible supporting profiles: `POD_MEMBER` or `POD_LEAD`, effective for the entire request window.
- Minimum self-rated capability strength: 3/5. Project Manager remains derived from the eligible role, not a self-rating.
- Capability scoring requires recorded evidence. Each deliverable needs relevant coverage among its actual assignees; unrelated team skills do not cover it. Learning/supported contributors need an experienced teammate assigned to the same deliverable.
- Scoring weights: skills 50%, deliverable experience 30%, capacity 15%, interest 5%. These are deterministic calculations, not numbers invented by the language model.
- Captain approval creates final assignments. Rejection requires a reason. The exact published daily schedule is rechecked at approval; if it no longer fits, the Captain must rerun fitment. There is no Lead/Member acceptance step.

The SQL records the operator's explicit demonstration-policy approval. This is not a claim that a business stakeholder approved it for production use.

## Install, review, then approve

1. Keep the Next.js server, Python API and worker stopped. The database agent and notification switches should still be `N` from Phase 1, with no queued/running executions.
2. Open `sql/oracle/demo_phase2_policy.sql` in SQL Developer, connected as `AI_POD_STAFFING`. Run the whole script with **F5**. It creates a separate `DRAFT` in one transaction and verifies its exact configuration. Reruns verify the existing version without overwriting it.
3. Review the rules above. In that same file change these two lines to explicitly approve the demonstration rules:

   ```sql
   approve_policy CONSTANT BOOLEAN := TRUE;
   approval_operator CONSTANT VARCHAR2(255) := 'smaikoti';
   ```

   Use your own operator name. Run the complete script again with **F5**. Expected: `SUCCESS: staffing-demo-v2 verified, status=APPROVED.`
4. In `backend/python/.env`, change the existing setting (or add it once):

   ```dotenv
   STAFFING_POLICY_VERSION=staffing-demo-v2
   ```

   Both the API and worker read this backend file. Do not replace OCI, database, token or persona settings. Public Next.js flags do not select a policy.
5. Restart the services only as directed by the Phase 2 test instructions. Enabling the worker/runtime is a separate explicit step; this SQL never does it. Notifications remain disabled.

## Failure and recovery

If the script reports an error, its DML transaction is rolled back. No DDL is used, and the existing policies/assignments are not changed. Resolve the reported conflict and rerun; do not drop tables, clear backup tables, or rerun the original schema installer.

An existing `staffing-demo-v2` whose contents differ causes a conflict instead of being overwritten. An approved policy is frozen. Future rule changes require a new policy version, not editing this one.

If you need to stop testing, stop the worker/API, disable the database agent switch, and leave the new policy/history in place. To review older data you can restore the previous `STAFFING_POLICY_VERSION` setting; this does not undo final assignments already approved under v2. Cancelling or closing projects remains the application's explicit workflow.

## Storage and historical compatibility

The existing four eligibility-rule rows are retained. The `MAX_AGENT_STEPS` JSON also contains an explicit versioned `scheduling` object. Old policies without this object keep their original equal-weekday scheduling semantics.

New proposals freeze each selected person's `daily_schedule` and `scheduling_algorithm` in the existing member factors JSON. Approval uses that schedule, never a new redistribution. The older approved baseline projects and their assignment days are not recomputed or rewritten.

Continue with [Phase 2 testing and startup](demo-agent-phase2.md#what-to-do-now).
