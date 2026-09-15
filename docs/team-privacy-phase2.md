# Team profile privacy — Phase 2

Phase 2 connects the application to the Phase 1 profile scopes. No database migration, data import, environment change or new permission is required. Keep `AIPS_TP1_BK_SCOPE` for recovery.

## Visible information

| Profile | Team & Skills |
| --- | --- |
| POD Member | Own profile, skills, interests, deliverable experience and capacity. No directory, people search, sorting or teammate View buttons. |
| POD Lead | Own profile and active employees in confirmed PODs they lead, under “My active POD team”. |
| POD Captain | All active staffing employees. |
| Administrator | All active staffing employees; existing Add person action retained. |

For Leads, an active POD means a `STAFFED` request with their `CONFIRMED` `POD_LEAD` assignment and the teammate's `CONFIRMED` assignment. Approved future and overdue PODs qualify until closure. Closed/cancelled/unapproved PODs and a Lead-profile person occupying a Member slot do not grant profile access. Another qualifying active POD can maintain access. Inactive employees and standalone Administrator accounts are excluded from the directory.

Viewing someone does not grant editing rights. Existing self-skills and availability writes still resolve and validate the signed-in person's own ID.

## Enforcement

- Python's Requests, Calendar, Reports and My Availability workspace responses now apply the independent Team & Skills profile boundary before loading capacity. Changing the resource query parameter does not widen profile access.
- Assigned-project rosters remain separate: teammates without full-profile visibility have only IDs, names, POD roles, responsibilities and project-assignment status. Their personal schedule fields, assigned hours and closure notes are omitted; their dated workload rows and overall capacity/active-POD metrics are not returned.
- Next.js separately requests `resource=TEAM_SKILLS` and filters the Oracle people model against that allowlist before serialization. It no longer uses the Requests roster as a profile directory. Members also have an explicit own-only cap. Failure to load the allowlist stops the response; there is no fallback to all people.
- Page data, `/api/staffing` and the chat endpoint use that server projection. Agent proposal/execution endpoints retain their separate Captain/Administrator authorization. Request-source lookup remains a names-only, request-create-authorized endpoint.
- Client selectors and person drawers enforce the own-only Member boundary; Lead preview selectors also require active led PODs. Project views tolerate the intentionally omitted teammate workload fields without displaying fabricated zeroes or crashing.
- Existing persona session checks, profile-switch remounts and stale-tab protection are retained. The local persona entrance is still a demo identity mechanism, not enterprise authentication. Keep the existing agentic/persona setup enabled; the legacy unauthenticated role-switch preview is not an identity/privacy security boundary.

No agent candidate eligibility, scheduling, scoring, proposal approval, project-closure logic or business record was changed. The separate historical-allocation-on-closure fix is still outside this phase.

## Restart and check

Stop the existing Python API and Next.js terminals using Ctrl+C, then restart in two separate PowerShell terminals. Do not start duplicate listeners.

Python API:

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing\backend\python
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8015 --env-file .env
```

Next.js:

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing
npm run dev -- --hostname 127.0.0.1
```

Open `http://127.0.0.1:3001`, refresh, and use Change profile to select a person again. The worker is not needed to verify privacy with existing assignments.

1. Member → Alex Rivera: Team & Skills has only Alex; Manage my skills and My Availability retain his own information. There is no teammate directory/search/sort/View action.
2. Open an assigned request: teammate names, POD roles and responsibilities remain; teammate ratings, evidence, overall allocation and other active-POD counts are absent from network responses as well as the page.
3. Lead → Priya Nair: the current data allows Priya, Aisha Patel and Amelia Hart. Other Leads' unrelated PODs do not appear in her directory.
4. Captain or Administrator: the current directory contains 16 employees, excluding the standalone Administrator account. Administrator's Add person button remains.
5. Network inspection: `/api/staffing` contains only permitted full profiles in `data.people`. `/api/agentic/workspace?resource=REQUESTS` can contain additional basic roster entries, but no private teammate metrics for Members. Locked resources should return 403, not a broader directory.

## Verification performed

- 35 focused Python tests passed, plus 15 subtests. The tests execute the production SQL against an in-memory relational fixture, exercising all resource variants, old/broad Member scopes, Lead-as-Member, closure, overlapping teams, inactive people, missing/locked permissions and database failures.
- All 118 Node application/integration/persona/self-skills tests passed, including server serialization tests with deliberately broader request rosters and rendered Member/Lead Team & Skills checks.
- TypeScript `--noEmit` and Ruff on the changed Python implementation/privacy tests passed.
- Read-only Oracle checks on 14 September 2026 passed using actual saved role mappings: Alex saw one profile; Priya saw three; Captain and Administrator each saw 16. Requests responses preserved basic rosters and excluded unauthorized workload fields. No business writes, model calls or email were performed.
- Full Python suite: 345 passed, 210 subtests passed, two unrelated failures. The static policy test expects `APPROVE_POLICY := FALSE`, while the operator's existing SQL file is configured `TRUE`. The JWT test cannot generate an RSA key because this machine's OpenSSL reports insufficient entropy. Neither the operator's policy script nor authentication code was changed to bypass these failures.

Phase 3 browser and full local HTTP acceptance is now complete. See [Phase 3 results and repeatable checks](team-privacy-phase3.md), including the additional free-text responsibility leak found and fixed during the walkthrough. The counts above describe the earlier Phase 2 run; the Phase 3 report contains the latest results and remaining unrelated test failures.
