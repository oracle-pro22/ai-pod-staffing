# Project closure and allocation — Phase 1

## Implemented rule

Closing a project preserves its planned schedule through the closure day and releases only later dates. It does not record actual hours worked.

- An open, confirmed assignment contributes its dated scheduled hours.
- A closed assignment contributes scheduled hours on or before its closure day.
- Closure day comes from Oracle's saved `closed_at`, converted to that assignment's original approved policy timezone. It does not depend on the browser timezone, server timezone, or a subsequently selected runtime policy.
- Future schedule rows remain stored for audit but do not consume capacity after closure.
- Cancelled assignments retain their existing exclusion behaviour; a cancellation/reopening workflow is not introduced here.
- Other PODs, external work and absence-adjusted working capacity remain unchanged.

Allocation remains `(counted project hours + external commitments) / available working hours * 100`. A full week without working capacity returns no percentage, not a divide-by-zero or invented 0%.

Example: a 40-hour week has 10 external hours and 10 project hours, spread as 2 project hours each weekday. Closing on Wednesday retains Monday–Wednesday's 6 project hours and releases Thursday–Friday's 4 hours. The week's planned allocation becomes `(10 + 6) / 40 = 40%`, compared with 50% before closure. Historical days are not erased; future weeks contain only their own remaining commitments.

## Important cases

| Case | Result |
| --- | --- |
| Normal completion | The completed schedule continues to count in historical allocation. |
| Early completion | Hours through the closure day remain; tomorrow onward is released. |
| Weekend completion | Prior weekday work remains; future weekdays are released. |
| Closure before scheduled start | All scheduled dates after closure are released. |
| Overdue, still open | Dates do not extend automatically. The project stays open; future weeks receive no invented hours. |
| Overlapping PODs or external commitments | Only the closed project's future contribution changes. |
| Repeat close | The same note replays without another write; a different note conflicts. |
| Unauthorized, stale or failed close | No partial closure is committed. |

Only the actually assigned, currently authorized POD Lead can close with a nonblank note. The client cannot supply a closure date or actual hours. The request lock and sorted person locks are retained. Existing database triggers increment workload versions on assignment closure. Captain approval already reloads and validates capacity under the person locks, so saved proposals do not bypass the new calculation.

## Code and database impact

- `backend/python/app/storage.py`: one shared counted-assignment-day SQL predicate for the capacity ledger.
- `backend/python/app/assignments.py`: the calendar/workspace day query uses that exact predicate; closure audit entries record the next-day release rule and planned-hours basis.
- `backend/python/app/capacity.py`: clarifies that the existing `confirmed_work` ledger field includes retained planned history from closed assignments.

Agent evidence, scheduling, approval validation, weekly profile percentages and workspace calculations already use this shared ledger. Current active-POD counts still exclude closed assignments. Privacy scoping is unchanged, including access to one's own closed-project history without exposing teammates' private schedules.

**No SQL migration, reseed, environment change or manual percentage update is needed.** Existing closed assignments are interpreted using their saved closure timestamps when read; this intentionally corrects previously understated historical allocation. Original schedules, assignment totals and existing audit entries are not rewritten.

Restart the Python API and any running worker so both load the new query. This implementation session did not start/restart services or close any real project. Next.js source/UI is unchanged in Phase 1.

## Verification — 2026-09-15

- Focused closure, storage, approval, lifecycle and privacy regressions: **85 passed**, plus **41 subtests**.
- Full Python suite: **368 passed**, plus **225 subtests**, with the same two pre-existing failures:
  - Policy static test expects the distributed unapproved SQL default; the operator's working script is already configured for approval.
  - Local OpenSSL entropy error during JWT test RSA key generation.
- Native Oracle read-only CTE checks using the production predicate: **81 passed**, covering confirmed/closed/cancelled states; dates before/on/after closure; India, UTC and Los Angeles timezones; midnight boundaries and a daylight-saving transition.
- Read **17 existing Oracle capacity ledgers** with the updated query.
- Confirmed `P2_ASSIGN_VERSION`, `P2_REQUEST_REVISION`, and `P2_LOAD_FREEZE` triggers are enabled.
- Ruff passes for changed production files, new tests/fixture and the updated privacy tests. The older `test_phase5.py` file retains its pre-existing compact-statement lint issues.

Focused tests are offline. They execute the production SQL predicates against relational fixtures, translating only Oracle's timezone expression for SQLite. Oracle date semantics were also checked directly with read-only SELECTs; no live assignment closure, model call, email or business-data write was performed. Live concurrent closure/approval transactions were not exercised in this phase.

Run the focused suite:

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing\backend\python
.\.venv\Scripts\python.exe -m pytest tests/test_closure_allocation.py tests/test_storage.py tests/test_phase4.py tests/test_phase5.py tests/test_team_privacy.py -o addopts= -q
```

## Phase 2 follow-up

Phase 2 adds the closure explanation/confirmation, weekly labels and overdue messaging, refreshes affected screens after closing, and tests the live request → approval → closure journey. See [Phase 2 results](closure-allocation-phase2.md). Partial-day release, backdated closure, timesheets, reopening and extension/rescheduling UI remain outside this MVP.
