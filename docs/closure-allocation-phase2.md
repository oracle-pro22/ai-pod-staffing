# Closure and allocation — Phase 2

Implemented 2026-09-15. No schema, seed or environment changes are required.

## User-facing changes

- Both closure entry points explain the next-day release rule and require a completion note. They distinguish planned history from actual hours worked.
- Closed requests show that their past planned hours remain, while later hours no longer consume capacity. Assignment totals are labelled as originally planned hours in the request drawer.
- A successful close invalidates every mounted live-workspace snapshot, aborts its old in-flight request, and refreshes the Next.js server projection. The projection takes the authoritative request status from Python. New navigation therefore receives current capacity, POD counts and scoped team membership.
- Team & Skills, My Availability and Command Center show the allocation week. Team directory percentages share that period; current POD counts are labelled separately. Fitment continues to distinguish request-period allocation from peak weekly allocation.
- Calendar guidance distinguishes overall commitment percentages from project details visible within the viewer's access scope. The browser showed the test project's retained September 15 hour and no later bookings for either person.
- Python returns a past-planned-end indicator only for still-staffed projects whose scheduled completion date is before the policy's current business date. Request detail/assignment views explain that the project remains open and extra hours are not scheduled automatically.

Existing components, colours and page layouts are preserved. This is a same-workspace refresh, not a new cross-browser push-notification service. Another already-open browser session needs to refresh to obtain changes made elsewhere.

## Live request-to-closure test

Only the newly created **REQ-1049 — Sales guide completion check** was assigned and closed. Existing projects were not closed or rescheduled.

1. Created the request through the normal Next.js endpoint as Indranie, POD Captain: 8 hours, Sales Guide (deck), GTM SME, September 15–18, one Lead and one Member.
2. Verified no other queued/running or undiscovered opted-in requests were pending, then ran the worker once. Automatic discovery executed both agents with OCI and returned `READY_FOR_REVIEW`.
3. Reviewed the saved proposal: Elena as Lead and Alex as Member, four hours each, one hour on each scheduled weekday. Approved through the Captain decision endpoint.
4. Verified that Member closure is denied (403), a blank Lead note is rejected (422), and a stale request revision is rejected (409).
5. Opened the new request as Elena in the browser. Verified the disabled empty-note button and confirmation text, entered the completion note, and clicked Confirm closure.
6. Without manually reloading, the drawer changed to Closed. Navigating to Team & Skills showed the refreshed allocation and active-POD count.

| Person | Before approval | After approval | After closure | Active PODs before / approved / closed |
| --- | --- | --- | --- | --- |
| Alex | 70% | 80% | 72.5% | 2 / 3 / 2 |
| Elena | 80% | 90% | 82.5% | 3 / 4 / 3 |

Each retains September 15's one planned hour, contributing 2.5 percentage points to a 40-hour week. Each releases the other three hours. This explains why closing does not simply restore the pre-approval weekly percentage.

Oracle and API checks confirmed:

- Two closed assignments, still recording their original four-hour totals.
- All eight original schedule rows/hours retained, but only two hours counted: one per person on the closure date.
- No contribution from REQ-1049 in the following week's workspace.
- Exactly one closure audit event. Repeating the same close returns `replayed: true`; changing the note returns 409.
- Member sees only their own dated hours. Lead retains Alex's profile because they still share another active POD that Elena leads; offline tests also cover removal when no such POD remains.
- Both assignment email intents remain DISABLED. No email was sent.

The closed test request and its audit/schedule history are deliberately retained, not deleted. It contributes the two retained planned hours to the current week's history. The worker's `--once` process exited; it is not left running continuously.

## Verification

- 119 Node application/integration/persona/skills tests passed.
- TypeScript `--noEmit` passed.
- Full Python suite: 369 passed, 225 subtests passed; the same two pre-existing failures remain (operator-approved policy SQL versus the test's distributed default, and local OpenSSL RSA entropy).
- Ruff passed for the changed Python files.
- Relational tests cover normal/early/weekend closure, historical preservation, overlapping work, leave, timezones, authorization, idempotency and overdue flags. The native Oracle date predicate had 81 successful read-only checks in Phase 1.
- Browser screenshots confirmed the existing layout and readable closure form / updated weekly allocation card. The computer-use skill guided the browser verification; no baseline project was submitted for closure.

Post-closure privacy acceptance passed for **all 17 personas**. All 19 business-table fingerprints were unchanged across that read-only acceptance run. The separate request/approval/closure test above intentionally created the new request and its associated history and called OCI; the privacy rerun made no business writes or model calls.

## Run locally

The Next.js server and Python API were started locally for testing and left running on ports 3001 and 8015. If restarting later, use the existing commands and `.env` files; no new variables are required.

Future work outside this MVP: partial-day or backdated completion, timesheets, reopening, cancellation UI, and capacity-validated extensions/rescheduling. Passing the planned end date alone does not close a project.
