# Staffing sample expansion validation

Scenario anchor: 11 September 2026. The application uses the actual current date for current-allocation scoring; this benchmark fixes future request windows so the validation is reproducible against the supplied snapshot.

## Why the original sample failed

The original operational workbook had eight people, 18 skills, 35 skill records and 35 preferences. Each skill had only 1–5 qualified people. Baseline allocations were 68%, 84%, 76%, 62%, 71%, 48%, 54% and 39%. Existing approved assignments and explicit commitments are additional to baseline capacity.

For saved request `REQ-1043` (`Test 1`), 72 hours divided between two people over 11 business days means 3.27 hours per person per day. On an eight-hour day, that adds 40.91 percentage points to allocation. Only one original person was eligible; the remaining eligible person could not cover Comms Review/Comms Plan and was not marked as a pod lead. The system correctly withheld a recommendation. The two other unstaffed imported requests had zero eligible original candidates in their historical windows.

These runs had no OCI inference errors. They ended at Needs Adjustment because of deterministic staffing constraints, not because the model lacked training samples. Synthetic data expands the simulated workforce; it does not train or fine-tune the model.

## Data changes

| Operational table | Before | After |
| --- | ---: | ---: |
| People | 8 | 72 |
| Person Skills | 35 | 467 |
| Preferences | 35 | 530 |
| Availability Events | 4 | 420 |
| Skills | 18 | 18 |

All original rows are retained. Only the four workforce-related tables receive appended records. The saved request count remains four, decisions one, and approved assignments three in the runtime snapshot. The versioned seed keeps its original three historical requests and no operational approvals. All 25 worksheets retain their names and order. Source mapping values, existing header conventions, tables and formatting were preserved and the expanded ranges were visually checked.

The 64 synthetic profiles span eight specialty families, with 32 lead-capable profiles, a mix of 6- and 8-hour workdays, and baseline allocation between 20% and 80%. Proficiency, learning interests and scheduling data are independent. New availability includes 256 incremental commitments, 128 leave events and 32 travel events. Each of the 18 exact catalog labels has at least nine qualified people after the expansion. Synthetic identities, evidence and preferences are explicitly labelled and must not be treated as real employee assessments.

## Deliverable benchmark

The tests join the existing `Deliverables` and `Deliverable Skills` source tables by `deliverable_id`, use their exact skill IDs, and assess each of the 55 deliverables under three planning scenarios. Requirements remain mandatory at proficiency 3/5. The guardrail remains 85%; scoring remains Skills 50%, Allocation 25%, Future availability 15%, Interests 10%. Effort is divided equally among pod members and business days. The production recommendation rule then limits selection to the top 3 eligible lead scores and top 5 eligible contributor scores.

| Scenario | Request window | Hours / pod size | Feasible before | Feasible after |
| --- | --- | --- | ---: | ---: |
| Standard | 14–25 September 2026 | 72 hours / 3 people | 0/55 | 53/55 |
| Short sprint | 12–16 October 2026 | 40 hours / 2 people | 0/55 | 52/55 |
| Extended | 14 December 2026–1 January 2027 | 120 hours / 4 people | 0/55 | 53/55 |
| Total | Three scenarios per deliverable | 165 independent scenarios | 0/165 | 158/165 |

These cases are evaluated independently, not as 165 simultaneous assignments. This is a capacity/coverage test, not a measure of recommendation quality, production throughput or approval rate. Public holidays are not modelled; the application counts Monday–Friday only.

Three failures are `DEL-001`, `DEL-009` and `DEL-016` in the short-sprint scenario. Each requires Project Manager (GTM SME). Qualified program managers are unavailable or exceed the guardrail in that short window. Four more are `DEL-018` and `DEL-019` in the standard and extended scenarios: eligible Comms Review specialists exist in the full scored pool but rank below the top-five contributor shortlist. This is an intentional result of the role limits, not missing master data.

Historical request dates, old recommendation records and human decisions are not rewritten; users must re-run fitment to create fresh proposals under the role-shortlist rule. A saved request can now require adjustment when its necessary specialist falls outside the permitted top scores.

## Application safeguards and scale

- All people remain scored so the audit evidence shows why someone ranked inside or outside the recommendation limits. Pod selection is intentionally constrained to the top 3 eligible lead scores and top 5 eligible contributor scores.
- OCI explains the union of those two role pools, with duplicates removed and every proposed member included. Remaining narratives are labelled scoring-tool evidence. This avoids response truncation when the workforce grows.
- Failed searches provide deterministic headcount, lead and missing-skill diagnostics.
- A full expanded-pool workflow test verifies that recommendations stop at Pending Approval, with no new assignments or decisions.
- Impossible 10,000-hour/two-day requests still fail eligibility checks. Duplicate decisions, stale approvals, locked transactions and literal Excel text protections remain covered by regression tests.

The workbooks were authored and inspected with the spreadsheet workflow, then validated through the Python Excel adapter. Original records and historical sheet values were compared before publishing, and pre-expansion backups were retained.

The original live OCI verification predates the role-limit change and used a separate temporary workbook, not the user's runtime database. Current offline regression tests cover the top-3/top-5 selection boundary, deterministic ranking, human approval pause and assignment safeguards.
