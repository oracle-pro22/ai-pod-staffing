# Administrator-managed maximum utilization

## What changed

- The active limit starts at **85%** and is stored in Oracle, not a browser constant.
- Administrator → Administration → Agent rules → Maximum utilization lets an Administrator save a number greater than 0 and at most 100, with up to two decimal places and a required reason.
- Each change clones the current policy, preserving its eligibility rules, scheduling algorithm and scoring weights. The new version is approved by the authenticated Administrator, audited, and activated atomically.
- `STAFFING_POLICY_CONTROL` is a single-row pointer to an approved policy. New jobs read it at enqueue time. The old `STAFFING_POLICY_VERSION` environment variable is no longer the authority for new jobs or approvals; existing workspace timezone reads still use the configured historical policy, whose timezone is unchanged by this setting.
- New recommendations and approval validation use exact hours, not rounded percentages, and enforce the limit on each day, the request window, and all complete weeks touched by the request. Available capacity is reduced by leave. Confirmed assignments and external commitments count; pending proposals do not reserve hours.
- Existing commitments above the new ceiling are not cancelled or rewritten. Such a person cannot receive more work in an affected week. Closed project history remains governed by its original policy timezone.
- Old-policy pending proposals are marked stale in the API and cannot be approved. The Captain must re-run fitment. Publication and approval lock the policy pointer so a concurrent Administrator change cannot be missed.
- Changing the setting does not start an agent or send an email. Rejection's existing automatic retry behaviour is unchanged.
- No rotation, scoring-weight changes, or active-POD-count cap were introduced in this change.

## Installation / running

The migration is `sql/oracle/utilization_policy.sql`. On this local database it was applied and verified on 2026-09-15; **do not run it again just to start the application**.

For another database: stop the Python API and worker, finish any running/queued jobs, then run the migration with F5 in SQL Developer as `AI_POD_STAFFING`. It requires approved `staffing-demo-v2`. It adds one table and one policy version (`staffing-utilization-v1`), retaining original policies and all business records. DML failures roll back; Oracle DDL remains committed. Rerunning after success preserves later Administrator settings. Do not run setup.sql or drop original tables.

Restart the API and worker to load the changed code, and refresh/restart Next.js. After this deployment, changing the limit through Administration requires **no restart or environment-file edit**.

For REQ-1050, use Re-run after restarting. Its old recommendation must remain unapproved; the server returns `STALE_POLICY` if an old client tries to approve it.

## Verification

- Oracle: active approved policy `staffing-utilization-v1`, maximum 85.
- Migration preserved counts for requests, people, assignments, assignment days, proposals, decisions, and notification outbox.
- A real Administrator save to 86 was tested inside a rollback-only transaction. It cloned all rules, activated the clone and wrote the audit entry successfully; every test write was rolled back. The saved live setting remains 85.
- Actual Oracle-backed approval of the existing old-policy REQ-1050 proposal was blocked with `STALE_POLICY`, with no assignments or decisions written.
- Read-only replay of REQ-1050's saved candidate evidence at 85 returned Mara (3.2h, 85% request-period / 83% peak week) and Amelia (4.8h, 60% request-period / 52% peak week) as the first option. This is a simulation, not a new saved recommendation; live results can change with current data or agent selection among valid alternatives.
- Offline tests cover invalid/blank inputs, Administrator-only GET/POST, spoofed role headers, optimistic concurrency, atomic rollback on audit failure, exact 85% boundaries, leave, short request windows, existing over-limit commitments, and stale-policy approval.
- Verification totals: TypeScript passed; 120 Node tests passed; 23 focused utilization tests passed. The full Python suite had 392 passing tests and 225 passing subtests, with the same two pre-existing failures: the locally approved legacy SQL fixture expects an unapproved default, and RSA key generation fails in the local OpenSSL entropy environment. Neither was changed or bypassed.
- No browser visual acceptance, email delivery or production OIDC integration test was performed in this change.

## Recovery

An Administrator can change the limit again using the same screen; each revision stays in history. Do not edit approved LOAD_GUARDRAILS rows or manually rewrite existing assignments. A failed save should be followed by Refresh setting before retrying, since a connection failure may leave the commit outcome uncertain.

The initial migration's first attempt found a required audit correlation field. Its policy DML rolled back cleanly; the corrected migration was rerun successfully using the retained empty control table.
