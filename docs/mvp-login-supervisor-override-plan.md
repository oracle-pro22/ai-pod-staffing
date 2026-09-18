# MVP plan: login, clean data, supervised recommendations and Captain override

Status: Phase 1 implemented and user-confirmed applied; Phase 2 schema applied and user-confirmed verified; Phase 3 implemented in code with migration and local acceptance steps in `mvp-phase3.md`. Live Phase 3 Oracle/OCI acceptance remains a deployment step. This scope supersedes the earlier catalogue-consolidation and broad-reset wording.

Prepared on 17 September 2026 from application inspection and a read-only Oracle audit. The audit did not change business data, call a model, start a worker or send email. The counts below describe the database configured in the local Python environment; confirm that the VM uses the same database before cutover.

## Confirmed product requirements

- Replace persona selection with email/password login. Use the supplied Oracle email for each account and a common initial password for this MVP. This is application login, not Oracle corporate SSO.
- Load the signed-in person's existing role and privacy scope automatically.
- Add a Supervisor above the existing Request/Evidence Analyst and POD Planner: three agents with distinct responsibilities.
- For a one-Lead request, show one recommended Lead and two distinct alternatives, plus manual selection.
- For a request requiring N Members, show N recommended Members and two additional distinct alternatives, plus manual selection. A request for three Members therefore shows five Member candidates, not nine.
- The Captain may manually select people without matching skills or experience and may exceed the administrator-configured utilization ceiling, currently 85%.
- Manual choices remain selected. The system calculates and displays the consequences before Captain approval; it must not silently substitute different people.
- Captain approval is final. No Lead or Member acceptance step and no 24-hour waiting window.
- Standardize the data and identifiers, retire old test requests from the active application, and add a more diverse, complete workforce for testing.
- Retain the current UI theme, privacy rules, dated allocation model, closure behavior and administrator-editable recommendation ceiling.
- Leave Member-only projects without a designated Lead out of this change, as requested. Actual email sending also remains out of scope.

## Scope boundary — change only the requested functionality

Allowed changes are email/password login, an added Supervisor, recommendation alternatives and selection, Captain manual override with allocation preview and final approval, normalized person/login identifiers, more diverse employee test data, and cleanup of explicitly inventoried old test requests and their dependent records. Supporting schema/API changes must be necessary for those features.

Protected and unchanged:

- All 78 deliverables, including their existing 73 active and 5 retired statuses. No reactivation, retirement, renaming, merging, deleting, reseeding or version consolidation.
- All project types, skill definitions/IDs/names/assessment types, project-type-to-deliverable links, deliverable-to-skill links, CUSTOMER_MAPPING source rows and original catalogue provenance. Treat PROJECT_TYPES, DELIVERABLES, DELIVERABLE_SKILLS, INTERESTS and CUSTOMER_MAPPING as read-only throughout implementation.
- Existing employees' skill ratings, evidence, interests and deliverable experience. Only person-key relinking needed for the agreed ID migration is permitted; values must survive unchanged. New employees use existing catalogue IDs.
- Project Manager's current role-derived behavior; no self-rating change.
- Existing role assignments and privacy rules, apart from creating the requested additional people/accounts and reconnecting login identities.
- The existing two agents' recommendation eligibility, scoring weights, normal effort distribution, availability rules and administrator-editable utilization threshold. Only add orchestration and alternatives; implement manual exceptions in a separate, explicit path.
- The dated allocation formula, project closure behavior, rejection-reason requirement, reports/Excel export, skills management, availability management and other existing functionality.
- Current theme, navigation and screen layouts outside the entry screen and targeted staffing-selection additions. No general UI redesign.
- Existing policy values/history, backup tables and migration ownership records. Reuse the current active approved policy; do not create a replacement policy merely to get a different name.

Do not merge GTM SME and GMT SME or any other catalogue entries. This is no longer an open question in this plan: catalogue cleanup is excluded.

If a necessary dependency requires a change outside this boundary, identify the exact object and impact and obtain direction before proceeding. Do not silently extend cleanup or bundle unrelated fixes into these phases.

## Read-only database findings

| Area | Observed | Cleanup implication |
| --- | --- | --- |
| People | 17: 16 employees and one standalone Administrator | Preserve existing profiles and the standalone Administrator role; add people within the agreed roster. |
| Active roles | 2 Captains, 3 Leads, 11 Members, 1 Administrator | Grow a deliberate, role-balanced roster. |
| Person identifiers | P-001 through P-012, plus P-900101 through P-900105 | Create a complete old-to-new mapping and correct sequence state. |
| Identity mappings | 22: 17 active persona mappings, five inactive older seed mappings | These are not five additional active users. Replace login identity conventions, preserving archived provenance. |
| Email addresses | 17 populated, case-insensitively distinct; none ends in @oracle.com | Obtain the approved person-to-email mapping. Do not invent real employee email addresses. |
| Requests | 20: 11 needing recommendation, 1 in review, 7 staffed, 1 closed | Archive the old test dataset rather than continue its mixed history. |
| Assignments | 24: 22 confirmed, 2 closed | Preserve their schedules in the archive; do not merely set percentages to zero. |
| Proposal history | 13 proposals, 9 decisions, 15 executions | Archive with requests and preserve request/proposal/decision relationships. |
| Notification outbox | 8 disabled entries | Old entries must never be sent after a restart. |
| Policies | Four versions; staffing-utilization-v1 is the active approved 85% policy | Reuse the current active policy. Do not rewrite or delete other versions/history. |
| Deliverables | 78: 73 active, 5 retired | Preserve every record and status exactly. |
| Source spreadsheet mapping | 152 raw rows from different imports | Preserve all source rows and provenance exactly. |
| Skills | 14 catalogue skills; 69 person-skill records | Preserve definitions, employee ratings and evidence; relink person IDs only where necessary. |
| Deliverable experience | Existing references cover 23 distinct deliverables; no invalid deliverable references found | Preserve existing entries; add diverse experience only for the added people. |
| Availability | 724 rows, including 715 dated external-work rows from the main demo import | Preserve leave and external commitments unless particular fixture rows are explicitly included in the agreed cleanup manifest. Do not blanket-delete or rewrite them. |
| Capacity days | 1,071 rows for 17 people, covering 7 September–8 November 2026 | Recalculate affected derived workload and extend the needed date horizon without changing source availability. |
| Legacy workforce fields | Some PEOPLE allocation/active-POD fields differ from calculated dated records | Verify screens use the existing canonical dated calculation. Do not add a second formula or undertake unrelated field removal. |
| Schema/history | 58 tables; 24 have backup-style names | Leave backup tables and migration history alone; their count is not a reason to delete them. |

Integrity checks found no orphaned references across 39 foreign-key relationships. Assignment totals match their dated schedule totals. These checks are not a claim that every possible business invariant has been tested.

Important examples: the cleanup inventory includes the five REQ-910xxx baseline projects, the REQ-900xxx fixtures, REQ-1048, closed REQ-1049, pending REQ-1050 and staffed REQ-1051. Closing all of these is not equivalent to resetting a demo: closing deliberately preserves historical planned hours, and external-work commitments remain independent of project closure.

## Overall journey

Email/password login -> Captain saves a pending request -> Supervisor coordinates Analyst and Planner -> recommended POD and alternatives -> Captain selects alternatives or manually replaces people -> server recalculates the exact selected team -> Captain reviews and approves -> confirmed assignments and dated allocation update -> Lead closes the project when finished.

The request must exist before its agent execution so evidence, drafts and approvals have an identity. Approval finalizes staffing on that same request; it does not create a duplicate request. Pending requests, proposed options and selection drafts do not reserve capacity.

## Phase 1 — Clean data and email/password access

### 1. Prepare a scoped request cleanup

1. Produce an explicit cleanup manifest listing old request IDs, their dependent records and any specifically requested fixture workload rows. Back up those records and identity dependencies and provide a dry-run report and restore procedure. Snapshot protected catalogue/mapping contents and existing profile evidence for before/after comparison.
2. Confirm whether local and VM services share the database. During the eventual cutover, pause every connected worker and prevent concurrent application writes; changing only one machine is insufficient.
3. Resolve queued/running jobs before reset and fence old retries from processing archived requests afterward. There were no queued/running jobs in the audit snapshot, but recheck at cutover.
4. Archive only the manifest's old test requests and dependent requirements, legacy recommendations, executions/events, proposals/members, decisions, assignments/days, request-linked audit records and outbox entries. Preserve original keys and immutable history. Do not modify unrelated audit entries or frozen policy records.
5. Exclude the archived test requests from normal request lists and active capacity calculations. Retain existing leave and external commitments; add documented dated starting workload for new employees. Do not force everyone to 0% or invent replacement workload to conceal the cleanup's effects.
6. Leave the existing schema and catalogue in place. Do not rerun setup.sql, reset the entire database, rebuild catalogue records, or delete old backups. The scoped archival procedure must handle dependency order and immutable history without dropping protections generally.
7. Recalculate affected allocation and active POD counts using the existing dated logic. Verify keys, JSON references and sequences, and prove that protected content is unchanged before restarting services. Stop and restore the affected scope if verification fails.

The implementation must account for append-only decision/audit/event triggers and frozen proposal/policy records. It must not use a blanket person-ID UPDATE or string replacement inside historical JSON. The archive remains readable with an old-to-new identity manifest; active person records use normalized keys, with ratings and experience preserved. Request archival is a maintenance operation distinct from normal project closure: closure continues preserving historical planned workload exactly as it does today.

### 2. Standardize person and login identifiers only

- Keep existing P-001 through P-012. Proposed normalization: P-900101 -> P-013, P-900102 -> P-014, P-900103 -> P-015, P-900104 -> P-016, P-900105 -> P-017, subject to the final migration manifest.
- Allocate added people from the next unused value and set the person sequence above the final populated ID. Do the equivalent verification for request and other generated IDs.
- Separate immutable account identity from email and person display ID. For example, a stable account subject can map to a person and role without embedding a seed batch or email address.
- Replace active demo:d1:* and obsolete seed mappings with the new account mappings; preserve former identifiers in the archive manifest.
- Reuse the current active approved policy and unchanged catalogue. Preserve recommendation weights, role requirements, privacy permissions and the configurable 85% ceiling.
- Keep policy revision history for administrator changes. “Uniform data” refers to current person/login conventions and one operational configuration, not rewriting historical policies or catalogue versions.
- Use a documented, consistent import format for added employees. Retain existing provenance. Update setup guidance only where required for these features; do not delete earlier migration scripts or backups.

### 3. Expand and complete the roster

Confirmed target: 31 accounts, comprising 4 Captains, 6 Leads, 20 Members and 1 standalone Administrator. That adds 2 Captains, 3 Leads and 9 Members to the current roster; no additional Administrator. Keep existing people and roles; do not replace their profiles with a new seed dataset.

- Added employees have unique IDs, supplied emails, role mappings, job information, weekly hours, relevant skills/ratings/evidence and deliverable experience, all using existing catalogue IDs. Preserve existing employees' skill/experience values. Keep unknown or inapplicable fields honestly empty rather than fabricate experience.
- Administrators have account and role data but no fabricated staffing skills, workload or POD eligibility.
- Cover communications, sales collateral, video/creative, enablement, project coordination and customer-story work, with different evidence and experience levels.
- Include meaningful low/medium/high starting workload, part-week leave and upcoming absence for the added test profiles. Use existing working-hours rules rather than introduce new calendar semantics. Generate all workload percentages from dated hours.
- Populate enough qualified Leads and Members for at least three distinct Lead options and N+2 distinct Member options in the main positive demo scenarios. Other requests may legitimately have fewer options.
- Use clearly documented synthetic profile evidence internally; no “dummy data” notices or noisy test labels on normal application screens.
- Choose one date anchor and a documented capacity horizon for added test data. Keep its ownership and identifiers uniform without renaming existing source versions or rewriting retained availability.

### 4. Add application login

- Add an email/password entry page using the existing application theme.
- Store normalized unique login email, a salted password hash, account status and a stable account/person link. Seed the common initial password from server-only configuration; do not store plaintext passwords or put the password in source control.
- Verify credentials in Python; issue an expiring, logout-capable session used by the Next.js server and Python API. The browser must not supply trusted role/person claims.
- Replace “Change profile” with account details and “Sign out.” Do not offer public registration, password reset or forced password change in this MVP.
- Disable persona issuance, fixed-user login and preview identity fallbacks when password login is enabled. Check direct API routes, not just the entry page.
- Preserve privacy: Member = own profile; Lead = own profile plus Members in their active led PODs; Captain and Administrator = full staffing visibility. Administrator visibility does not silently grant Captain approval powers.
- Configure local and VM origins explicitly. Password mode must work with the existing VM deployment without requiring corporate OIDC setup or masquerading as a loopback-only persona mode.

Likely new persistent entities: APP_ACCOUNTS and APP_SESSIONS. Reuse PEOPLE, APP_USER_ROLES and ROLE_PERMISSIONS for workforce identity and authorization.

Primary areas: Python config/auth/main; Next.js login/bridge/persona entry; controlled Oracle migration/import and verification utilities. Test existing privacy projections without redesigning them. Tests land with the implementation, not only in phase 3.

Phase 1 exit: scoped cleanup and documented archive; verified IDs, preserved profile evidence and recalculated workload; all four roles can log in with the intended account; no persona bypass; manifest-listed old requests do not appear in active request lists or capacity calculations; protected catalogue/mapping checks show zero changes.

## Phase 2 — Supervisor and selectable recommendations

### 1. Implement three distinct agent responsibilities

| Agent | Responsibility | Not responsible for |
| --- | --- | --- |
| Supervisor | Read execution state; delegate to Analyst/Planner; route essential clarification, bounded retry/replan and review-ready completion | Inventing people, calculating percentages in prose, overriding Captain choices or granting approval |
| Request/Evidence Analyst | Read request scope, catalogue mapping, recorded skills, deliverable evidence and feedback; identify essential missing business information | Asking users for computed scores/hour splits or choosing a final assignment |
| POD Planner | Use deterministic eligibility, scheduling and scoring tools; compare valid options; return a recommended team and factual explanation | Bypassing recommendation rules or writing final assignments |

Implement a genuine bounded tool-calling Supervisor in LangGraph, not just rename the existing fixed graph. Proposed Supervisor tools are delegate_analysis, delegate_planning, inspect_execution_status, request_clarification and finish_review. Application-controlled transitions validate every tool request and publish only a valid result. These are proposed tools, not claims about today's registry.

Keep the current Analyst and Planner responsibilities, calculation functions and normal recommendation rules. Do not retune scoring, remove the interest checkbox, reinterpret skill levels or add new workforce selection criteria as part of introducing the Supervisor.

Extend durable stage checkpoints, engine/schema versions, model/tool budgets and execution logs for the third agent. Resuming an old two-agent checkpoint must not reinterpret it as a new-format execution. Prevent cyclic delegation and duplicate jobs. Record concise actions, outcomes and evidence—not private model reasoning.

### 2. Produce usable, distinct alternatives

- Generate the recommended full team, then viable distinct Lead replacements and Member replacements. Today's top-three complete-team search alone does not guarantee three different Leads.
- For one Lead and N Members: one recommended Lead plus two Lead alternatives; N recommended Members plus two additional Member alternatives.
- Preselect and highlight the recommended team. A Captain's subsequent selection gets a separate “Selected” indication; preserve what the agent originally recommended for comparison.
- Do not count the same person twice across Lead and Member slots. Retain designated Lead-role eligibility; current Member-role eligibility can include a Lead contributing as a Member.
- Validate recommendations against the administrator's current ceiling, skill/experience rules, availability, dated capacity and collective capability coverage. Preserve meaningful contributions and exact total effort.
- Alternatives are conditional on the rest of the selected POD. Changing someone must refresh the complete team calculation; a candidate's displayed hours and allocation cannot be copied unchanged from another team option.
- If fewer eligible options exist, show the actual available options and a concise reason. Do not pad the list with unsuitable people to satisfy a visual count. Manual selection remains a separate Captain action.

### 3. Add a persisted selection draft and recalculation contract

- Preserve the original AI recommendation as an immutable snapshot.
- Persist a separate Captain selection draft with request/proposal revision, selected IDs/roles, selection source, planned contribution and calculated schedule snapshot.
- Every selection update returns total hours, per-person hours, existing commitment, before/after request-window allocation, peak full-week allocation, active POD information and relevant exceptions.
- Tag recommendation, alternative and manual choices distinctly. Do not persist a fabricated fit score or fake model rationale for a manual choice.
- Tie all statistics to dates and snapshot versions. Refresh or require reconfirmation if the request, people, workload, catalogue or policy changes.
- Do not reserve capacity while a selection is a draft.

Likely schema additions: candidate-option snapshots plus selection drafts/members; reuse proposal, assignment, capacity, decision and audit tables where compatible. Final migrations must respect existing immutable-publication and execution/proposal foreign keys. Manual drafts must not require a fictitious successful model run.

Primary areas: agents/staffing.py and a new Supervisor module; workflow.py; planning.py; agent_budget.py; execution_store.py; typed API contracts; AI Fitment and Agent Execution screens.

Phase 2 exit: an observable three-agent journey produces genuine selectable alternatives; selecting an alternative recalculates the exact team; UI preserves the existing layout/theme; no assignments exist until approval.

## Phase 3 — Captain manual override, final approval and full verification

### 1. Separate manual authority from recommendation rules

The manual picker must load the appropriate active role pool independently of the AI shortlist. A person excluded for weak/missing skills or high utilization must still be selectable manually.

| Rule | AI recommendation / normal alternative | Explicit Captain manual selection |
| --- | --- | --- |
| Required skills and experience | Enforced | Not an eligibility blocker; show any gap factually |
| Current utilization ceiling, initially 85% | Enforced | May be exceeded; show actual result |
| Manual hard ceiling | Not applicable | Existing PODs + new POD hours <=100% of contracted working hours |
| Leave and external commitments | Counted normally | Ignored for manual scheduling only; retained and disclosed separately |
| Selected person | Chosen from validated options | Exactly the Captain's selected person |
| Positive hours, total effort and dates | Enforced | Still required for a coherent assignment |
| Correct role and active account/person | Enforced | Retained; Member-only Lead exception is deferred |
| Registered Captain permission | Enforced for decision | Enforced for override and decision |
| Final approval and durable records | Required | Required, with override provenance |

Manual selection bypasses staffing suitability rules, not account authorization or arithmetic. Apply exceptions to explicitly manual selections, not automatically to every person in the POD. If a change makes a normally selected person exceed the ceiling, show that and require the Captain to explicitly include that person in the override rather than silently broadening the exception.

### 2. Calculate the chosen team's work before approval

- Pin selected people; never use a replan to replace them without the Captain's action.
- Reuse the current effort-distribution approach where it can schedule the Captain's pinned team. Add only the manual scheduling behavior needed to accommodate explicit skill/utilization exceptions: if selected people cannot fit under the ceiling, retain them and compute the resulting over-limit schedule instead of dropping their contribution. Do not change normal AI effort splitting or add an unrequested hour-editing interface.
- Preserve exact total hours and deterministic rounding. Do not create nominal 0.04-hour Members solely to meet headcount.
- Skill/experience gaps do not block scheduling in manual mode and do not cause the system to claim coverage that is absent.
- Display both request-window and busiest-week metrics with dates. Normal/reporting formula remains (counted confirmed work + external commitments + newly selected hours) / available working hours after leave × 100. Manual authorization uses only counted POD work plus new hours divided by contracted working hours, capped at 100%; display the two bases separately.
- For example, 24 committed hours plus 12 new hours over 40 available hours gives 90%. It exceeds an 85% recommendation ceiling but is allowed as an explicit Captain override.
- Do not clamp displayed workload percentages. Block manual POD-only scheduling above 100%; full leave does not block manual scheduling if contracted working hours and assignment evidence are known. Overall workload after leave can be undefined or above 100% and must be labelled honestly.
- Reuse deterministic calculation endpoints for selection changes; an OCI call is not necessary every time the Captain clicks a person.
- Keep manual drafting usable when AI returns no valid options or OCI is unavailable, provided authoritative request/workload data is available. Do not require a fake READY_FOR_REVIEW agent execution.

### 3. Final review and approval

The final review shows chosen people, POD roles, responsibilities, hours, dates, existing/projected allocation and manual exceptions. Record the Captain, selected replacements, timestamp and bypassed checks automatically. Do not introduce a mandatory override-reason field or an extra approval stage without a separate request. The existing mandatory reason for rejecting a proposal remains unchanged.

On approval:

1. Verify Captain ownership/authority and draft/request versions.
2. Reload current dated workload and policy. If another approval or data edit changes the preview, return refreshed statistics for Captain confirmation; do not commit unnoticed new figures.
3. Apply normal checks to normal selections and the documented manual rules to explicitly overridden selections.
4. Atomically save the final selection/proposal revision, decision, confirmed assignments, dated schedule and audit linkage. Preserve the original recommendation and selection difference.
5. Update the existing request's staffing status and refresh affected views. Keep operations idempotent against double-clicks/retries.
6. Retain notification arrangements with sending disabled.

Published snapshots must not be edited in place. Adapt proposal-origin relationships to support manual decisions honestly. Record who selected whom and which rules were bypassed; an agent or client-supplied flag cannot grant override authority.

Keep existing closure semantics: remove a closed project from active POD counts, retain planned hours through the closure date, release later scheduled hours, and recalculate from dated records. Do not turn a demo-data reset into fake project-completion events.

### 4. End-to-end test matrix

| Scenario | Required outcome |
| --- | --- |
| Protected catalogue and mapping contents | Exact before/after equality for all existing rows, IDs, names, statuses, links and provenance, not just equal row counts |
| Existing employee skills and experience after ID normalization | Same ratings, evidence, interests and deliverable experience after resolving the old-to-new person mapping |
| Scoped request cleanup | Only manifest-listed requests/dependents affected; unrelated availability, external commitments, policies, backups and audit entries retained |
| Email case/whitespace, wrong password, inactive account, logout, expired session | Correct identity resolution; no fallback to another persona |
| Member, Lead, Captain and Administrator sessions | Existing API, server projection, UI and export privacy preserved |
| Direct persona API and tampered person/role/override fields | Cannot bypass login or Captain authority |
| Positive request with sufficient candidates | One recommended Lead plus two distinct alternatives; N recommended Members plus two distinct alternatives |
| Short candidate pool | Honest smaller list; no fabricated candidates |
| Alternative swap | Whole-POD capability, hours and allocation recalculate correctly |
| Manual person with no matching skill/experience | Selected person retained and assignable after Captain approval |
| Manual person crossing 85% | Exact resulting percentage shown; approval allowed |
| Configured ceiling changed from 85% | AI uses new active value; explicitly manual selections remain exceptions |
| Above 100%, full leave, zero capacity, missing workload | Agreed behavior; no clipped or invented percentage |
| One-day, partial-week, multi-week, leave and rounding cases | Exact hours conserved; window and full-week measures correctly labelled |
| Duplicate person, wrong count, wrong role, invalid dates | Clear structural validation without silently changing the selected team |
| Two Captains approve overlapping work | Fresh capacity checked; changed preview requires reconfirmation |
| Rejection, rerun and retries | Reason retained; no silent replacement of Captain-pinned choices or duplicate assignment |
| OCI timeout/failure, worker restart | Bounded recovery and truthful status; manual workflow remains available where data permits |
| Supervisor prompt injection or repeated delegation | Only allowed transitions; no rule changes, unlimited loop or unauthorized approval |
| Normal/early project closure | History retained, future work released, active POD count updated |
| Request lists, profiles, calendar, reports and Excel export | Same underlying dated allocation and final selected team |
| Data import rerun and restoration | Idempotent scoped changes, valid references, correct sequences and proven recovery |
| Local/VM deployment and restart | Consistent login mode and origin; old workers cannot recreate archived requests |

Run unit tests and API/database integration tests throughout all phases. Rehearse final scenarios with all three application processes and live OCI in a controlled test window; report model calls and DB writes actually performed. Remove or archive only records owned by those test runs afterward so the delivered demo stays clean. Do not run a broad reseed after testing.

Phase 3 exit: a Captain can demonstrate normal selection and genuine manual assignment, preview truthful statistics, approve once, verify all workforce views, and close the project without corrupting historical allocation. Protected-data checks and existing-feature regression tests must also pass.

## Implementation discipline

- Phase order is intentional: establish stable person/account IDs before storing new candidate options and manual selections against them.
- Keep schema changes additive where feasible. Reuse existing staffing, capacity, decision and audit entities; introduce account/session and selection storage only as needed.
- Each migration provides explicit targets, preview, apply, verify and recovery instructions. Verify actual row counts and states again at execution time; the audit numbers above are not an automatic deletion list.
- Tests accompany every phase. Phase 3 adds the full cross-process rehearsal; it is not the first point at which migration or privacy behavior is checked.
- Only affected entry/fitment/execution UI components change. Validate the Command Centre, Team & Skills, My Availability, calendar, Administration, reports and Excel export for regressions; do not redesign them.
- Preserve the existing Next.js, Python API and worker deployment pattern locally and on the VM. Do not deploy or restart user services as part of planning.
- Never promise that unrelated code cannot be touched at all: auth, ID and allocation dependencies may need small supporting edits. Every such edit must be traceable to an approved requirement and retain existing behavior outside that requirement.

## Decisions and inputs still needed

1. **Resolved by the user:** manual utilization includes existing POD assignments and is capped at 100%. A 40-hour person with 24 existing POD hours can receive at most 16 additional hours. Leave and external commitments are ignored only for explicitly manual scheduling; their records and normal overall workload calculations remain intact.
2. **Actual login roster, later:** the user has approved generated `firstname.lastname@oracle.com` placeholders for now. These are login identifiers, not verified employee addresses, and email sending stays disabled. Replace them with the approved mapping when available. Configure the common password locally/server-side rather than publishing it in documentation.

The roster size is confirmed as 4 Captains, 6 Leads, 20 Members and **1 Administrator**. Existing people, roles and profiles remain; only the agreed additions are seeded.

No decision is needed again on common passwords for MVP, skills bypass, exceeding 85%, Captain-final approval, N+2 Member options, protecting every catalogue/mapping record or keeping Member-only Lead assignments out of scope: those requirements are already confirmed.
