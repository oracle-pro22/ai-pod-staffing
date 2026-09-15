# Reports

Reports uses the Command Centre's shared KPI, card, badge and progress-bar components. Live mode has Overview, Capacity, Requests and Excel export views.

## What the KPIs mean

- **Staffed projects:** currently staffed requests in the signed-in user's request scope. Closed projects are counted separately.
- **Awaiting staffing:** unassigned requests, with a separate count of current-revision proposals under the active policy that are ready for review.
- **Weekly utilization:** total known committed hours divided by total known working capacity after leave. This is weighted by hours, not an average of employee percentages.
- **Headroom to the configured limit:** sum of positive per-person weekly capacity remaining below the Administrator's utilization limit. It is not a guarantee that a particular request can be staffed: daily availability and capability checks still apply.

Changing the reporting week changes capacity and dated assignment detail. Request status, decision-history counts and active-POD counts remain current; the screen and exports label this distinction. Unknown capacity is excluded, never assumed to be zero. Hours are planned workload, not timesheets.

## Excel

The export tab downloads separate `.xlsx` reports for KPI summary, people/capacity, requests and dated assignment detail. Exports contain all authorized rows for the selected week, independent of the search filter. Every export obtains a fresh backend snapshot and checks Reports export permission; it does not trust the selected frontend role.

Numbers are numeric Excel cells, headers are frozen, filters are enabled, and user-entered strings remain literal text rather than executable formulas. Assignment detail contains counted project hours; aggregate capacity also includes external commitments.

## Deployment and recovery

Run `sql/oracle/reports_export.sql` as AI_POD_STAFFING once per environment. It enables export only for existing Captain and Administrator Reports viewers, backs up the original flags in AIPS_RPT_EXPORT_BK, and records an audit event. It does not change view scopes or people/project data. The local development database migration was applied on 2026-09-15. Keep the backup during the recovery window; the script includes recovery guidance.

Deploy/restart the Python API and Next.js together. No worker restart or agent execution is needed for Reports.

## Verification

- `npm run test:agentic`: report arithmetic, empty/unknown capacity, Excel cell types and literal text, proxy validation and permission denial.
- `python -m pytest tests/test_reports.py tests/test_team_privacy.py tests/test_phase5.py -o addopts='' -q`: export access and existing role/privacy behavior.
- `npx tsc --noEmit`: frontend type check.
- Browser: choose a Captain or Administrator, open Reports, change week, search Capacity/Requests, and download each report. Members and Leads remain unable to export Reports.

Full-suite baseline issues unrelated to Reports: the locally approved demo SQL conflicts with a test expecting an unapproved template; this machine's OpenSSL entropy error prevents one JWT key-generation test.

Verified on 2026-09-15: 123 frontend tests and TypeScript passed; 43 focused backend tests plus 23 subtests passed. The full Python run had 397 passes and the two baseline failures above. Live browser checks covered Overview, both searchable tables, week navigation and a successful People & Capacity Excel download. For the selected Captain, the Sep 14 week showed 328/632 hours (51.9%) and 209.2h headroom; Sep 21 showed 278/640 hours (43.44%) and 266h headroom while current request counts stayed unchanged.
