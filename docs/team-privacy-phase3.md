# Team privacy — Phase 3 acceptance

Verified locally on 15 September 2026 against the existing Oracle data and running Next.js/Python services.

## Result

The Team & Skills privacy rollout passed live acceptance for all **17 personas**: two Captains, three Leads, eleven Members and the standalone Administrator. This covers the privacy rollout, not a claim that every unrelated application feature has passed production acceptance.

| Check | Result |
| --- | --- |
| Every Member's full-profile and capacity payload | Only their own employee |
| Lead profile scope, independently compared with confirmed assignments on staffed requests | Elena: 5 profiles; Mara: 8; Priya: 3 |
| Captain / Administrator directory | All 16 employees; standalone Administrator excluded |
| Requests roster | Basic teammate identity, POD role, status and role-based responsibilities retained |
| Teammate workload fields and dated hours without profile permission | Omitted |
| Alternate Calendar, Reports and My Availability resources | Allowed scope enforced or 403 returned for locked access |
| Self-skills GET with another person's ID in the query | Still returns only the authenticated person's skills |
| Member request-source lookup and agent-request listing | 403 |
| Member spoofing the Administrator role header | 403 |
| Stale persona page binding | 409 |
| Request after signing out | 401 |
| Member chat asking about capacity | No teammate capacity disclosed |
| Before/after fingerprints of 19 business tables | Unchanged |

## Additional issue found and fixed

Browser testing found that the stored model-authored `responsibilities` text contained phrases such as `Deliverable experience: mentor`, recorded capability coverage and planned hours. Removing separate sensitive fields did not remove those details from the free text.

For roster entries outside the viewer's full-profile scope, both Python and the Next.js projection now derive a basic responsibility from the POD role:

- Lead: “Coordinate the POD and guide delivery of the request's deliverables.”
- Member: “Contribute to the request's deliverables with the POD lead.”

The original detailed responsibility is retained in Oracle and remains visible when the viewer is authorized to see that person's profile. This avoids unreliable keyword redaction and does not alter saved proposals or assignments. Regression tests deliberately inject experience/evidence into the original text and verify that it cannot pass through a basic roster.

## Browser walkthrough completed

Used the computer-use skill and the in-app browser with the actual local services:

1. Alex Rivera (Member): own profile only; no directory, teammate search, sort or View controls. Manage my skills opens with his saved catalogue skills and deliverable experience. Add availability opens. Both forms were cancelled without saving.
2. Alex's REQ-1048: Mara and Elena appear as project teammates without private experience/skill summaries or schedule fields. Alex retains his own detailed assignment. Verified again after the fix and API restart.
3. Priya Nair (Lead): “My active POD team” contains Priya, Aisha Patel and Amelia Hart. Aisha's profile drawer opens with permitted skills/capacity and no teammate edit controls. Priya's own skills management remains available.
4. Indranie Balkaran (Captain): directory contains 16 employees. New request opens, and Request source loads the 16 names without location/role decorations. Cancelled without creating a request.
5. Administrator: all navigation areas remain accessible, the directory contains 16 employees, and Add person opens. Cancelled without creating anyone.
6. Switched Administrator → Member and confirmed the broader directory was no longer present. Returned the browser to the four-profile entry screen after testing.

The existing styling was retained. Only privacy-related response text changed.

## Repeatable live acceptance command

New runner: `backend/python/app/privacy_acceptance.py`.

Keep the Python API and Next.js running with the existing local persona configuration. Do not run a worker or edit business records during the check: concurrent business changes intentionally fail the before/after comparison. The runner does not stop services or change runtime flags.

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing\backend\python
.\.venv\Scripts\python.exe -m app.privacy_acceptance --env-file .env
```

It contacts only `http://127.0.0.1:3001` by default (`--port` can select another local development port), reads Oracle in read-only transactions, and uses separate short-lived local persona cookies. It does not reuse or modify the browser's session. It checks every persona, prints progress, and takes several minutes because the real endpoints calculate capacity from Oracle. Cookies, tokens, raw employee data and database rows are not printed or saved.

The runner sends no business-write endpoint requests. Its POSTs create ephemeral local persona sessions or call the current read-only chat responder; DELETE signs out only its isolated HTTP client. It does not create requests, approve/close PODs, save skills/availability, call OCI or send email.

Expected final lines:

```json
{"business_fingerprints":"UNCHANGED","tables":19}
{"acceptance":"PASS","personas":17,"business_writes":0,"model_calls":0}
```

Persona counts may legitimately change when employees are added or deactivated; expected scope is recomputed from current Oracle assignments, not hard-coded person lists. A failed check exits nonzero without attempting repair or resetting data. If the database-change check fails, investigate concurrent activity rather than deleting records or rerunning migrations.

## Regression results

- Focused Python privacy, acceptance-validator, workspace and directory tests: **39 passed**, plus **22 subtests**.
- Node application, integration, persona and self-skills tests: **118 passed**.
- TypeScript `--noEmit`: passed.
- Ruff for the changed Python implementation, acceptance runner and privacy tests: passed.
- Full Python suite: **349 passed**, **217 subtests passed**, **2 existing unrelated failures**:
  - `test_additive_transaction_requires_explicit_approval`: the test expects the distributed SQL's `APPROVE_POLICY := FALSE`, but the operator's working script is already configured `TRUE` with the operator name. The script was not changed or executed to make this test pass.
  - `test_valid_jwt_and_claim_validation`: RSA key generation fails with the local OpenSSL entropy error. Authentication code and security settings were not changed to bypass it.

Focused rerun:

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing\backend\python
.\.venv\Scripts\python.exe -m pytest tests/test_team_privacy.py tests/test_privacy_acceptance.py tests/test_phase5.py tests/test_employee_directory.py -o addopts= -q
```

Application/typecheck rerun:

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing
node --test scripts/test-application-model.cjs scripts/test-agentic-integration.cjs scripts/test-personas.cjs scripts/test-self-skills.cjs
node node_modules/typescript/bin/tsc --noEmit
```

## Scope and handoff

No new SQL or environment changes are needed. Keep the Phase 1 backup. The Python API was restarted with the fix and the Next.js development server picked up its updated projection. Both were left running locally; the agent worker was not started by this test session.

No destructive closure, actual skill/person/request save, OCI call or email was executed against Oracle. Mutation authorization and lifecycle cases were covered by offline regression tests; this is not a production OIDC, production build, agent-model quality, email delivery or live-write round-trip certification. Closed/overlapping POD visibility and Lead-as-Member cases use the relational offline fixtures so existing assignments remain untouched. The separate historical-allocation-on-project-closure issue remains outside this privacy rollout.
