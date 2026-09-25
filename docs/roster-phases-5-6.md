# Real-roster rollout — Phases 5 and 6

Phase 5 implements the reviewed Excel import. Phase 6 provides automated
regression checks, read-only release reports and the operator/browser acceptance
procedure. These are not the older agent MVP phase numbers.

## Delivery boundary

No additional SQL migration is needed after the verified Phase 2/3/4 schemas.
The importer uses the existing `ROSTER_RESET_RUNS` journal and onboarding tables.
Implementation and read-only planning do **not** reset the live database, import
accounts, enable runtime switches, restart services or send mail/model requests.
Live real-account/browser acceptance can only finish after operator cutover.

The workbook is `Team Names and Access Type.xlsx`, sheet `Team-Role`:

- 25 accounts: 18 enabled, 7 disabled (Timing TBD). Disabled people retain exact
  role grants and first-login enrollment, but cannot sign in or be staffed.
- Exact grants: 3 Administrators, 8 Captains, 25 Leads, 24 Members. These overlap;
  they are not 60 different people. Tester is ignored.
- Amy's Captain + Lead-only exception stays intact. No implicit Member grants.
- Indranie Balkaran, Robert Story and Brenna Cooper have the workbook's Admin
  grant as well as their other explicitly assigned roles. No extra Admin account.
- Fresh person/account identities; no reuse of old demo account/session subjects.
- 40 contracted hours/week (8 per weekday), but no fabricated skills, experience,
  leave, external work, PODs or initial allocation. All 25 start `DRAFT`.
- Required legacy numeric fields start at zero; missing dated capacity remains
  **unknown**, not an assertion of zero actual workload. First-login data drives
  real dated calculations. Job title/location remain `Not provided` until known.
- Manager values are retained in the private import manifest/journal for
  provenance; they do not create accounts or infer permissions.

**Existing projects are not supplied.** First-login POD reports are retained as
self-reported dated workload. Their hours count toward capacity immediately and
do not require Captain approval or block workspace access. Do not manufacture
projects or convert those hours into external commitments. Confirmed assignment
and active-POD counts remain separate until genuine projects are imported later.

## Import guarantees

`python -m app.roster_import plan|apply|verify` is an operator-only CLI, never an
HTTP route or model tool. Plan/verify use read-only database transactions.

The private manifest freezes workbook bytes, exact identities/grants/access,
archive confirmation and fresh IDs. Apply checks that exact manifest against the
unchanged source workbook and archived data, requires an already `RESET` batch,
acquires the same maintenance lock as recovery, and locks the reviewed tables.
It cannot reset data itself or change triggers, constraints, catalogue or policy.
People, separately salted password hashes, exact roles, onboarding and the import
journal commit together; a failure rolls them back together. The person sequence
may advance on rollback; harmless gaps are preferable to reused IDs.

The import result is `IMPORTED`, recorded under `metadata_json.roster_import`.
The recovery journal's top-level state stays `RESET` to preserve the existing
recovery state machine. `roster_reset inspect` shows both states. A same-manifest
retry verifies the initial committed data without duplicating accounts. It is
not a mechanism for changing passwords, overwriting onboarding or reimporting.

## 1. Prepare — safe, no database writes

Keep all local and VM writers using this database stopped and both application
runtime switches OFF. Do not stop other applications on the shared VM. Obtain
and verify the separate access-controlled DBA backup described in Phases 3/4;
the same-schema archive is not a disaster-recovery backup.

In `backend/python/.env`, configure the agreed initial password locally:

```ini
BACKEND_AUTH_MODE=password
STAFFING_DEMO_PERSONAS_ENABLED=false
STAFFING_MVP_DEFAULT_PASSWORD=<your agreed MVP password, 8–1024 characters>
```

Do not use the placeholder literally, paste the password into chat, or commit
the environment file. This value is used only during explicit account import;
changing it later does not reset saved account passwords.

From Windows PowerShell:

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing\backend\python
New-Item -ItemType Directory -Path .mvp -Force | Out-Null
.\.venv\Scripts\python.exe -m app.roster_import plan --env-file .env --workbook "C:\Users\smaikoti\Downloads\Team Names and Access Type.xlsx" --batch roster4-real-roster --manifest .mvp/roster-import-plan.json
```

Require exit code 0, expected totals and `password_configured: true` **before
resetting anything**. If a manifest already exists, use a new filename rather
than overwriting it. Review its exact names/emails/grants privately; `.mvp/` is
gitignored, but the file still contains employee personal data. Restrict access
like the workbook and do not attach it to a public issue.

A read-only plan was generated locally on 2026-09-23 as
`.mvp/roster-import-plan-20260923.json`; that check reported
`password_configured: false`. Set the password and run a fresh preflight before
cutover. No reset/import was executed as part of implementation.

## 2. Approved cutover — destructive reset, then atomic import

Only after backup verification, import preflight, manifest review, a named
operator and the stopped-writer maintenance window are confirmed:

```powershell
$rosterPlan = Get-Content .mvp/roster-import-plan.json -Raw | ConvertFrom-Json

.\.venv\Scripts\python.exe -m app.roster_reset reset --env-file .env --batch roster4-real-roster --operator smaikoti --services-stopped --confirmation $rosterPlan.archive_confirmation --commit
if ($LASTEXITCODE -ne 0) { throw "Reset did not confirm success. Keep services stopped and inspect the batch." }

.\.venv\Scripts\python.exe -m app.roster_import apply --env-file .env --workbook "C:\Users\smaikoti\Downloads\Team Names and Access Type.xlsx" --batch roster4-real-roster --manifest .mvp/roster-import-plan.json --operator smaikoti --services-stopped --confirmation $rosterPlan.confirmation --commit
if ($LASTEXITCODE -ne 0) { throw "Import did not confirm success. Keep services stopped and inspect the journal." }
```

Reset removes the previously archived live demo roster/business records; retained
archive/shadow tables allow the existing empty-target recovery workflow. Import
creates only the new roster. Catalogue, skill definitions/mappings and policies
must retain their archived fingerprints. No pending jobs, notifications or test
assignments are inserted.

## 3. Verify BEFORE opening the application

```powershell
.\.venv\Scripts\python.exe -m app.roster_import verify --env-file .env --workbook "C:\Users\smaikoti\Downloads\Team Names and Access Type.xlsx" --batch roster4-real-roster --manifest .mvp/roster-import-plan.json
.\.venv\Scripts\python.exe -m app.roster_release --stage initial --env-file .env --workbook "C:\Users\smaikoti\Downloads\Team Names and Access Type.xlsx" --batch roster4-real-roster --manifest .mvp/roster-import-plan.json
```

Both must exit 0 with `verified: true`, 25 accounts, 18 enabled, 7 disabled,
exact roles, 25 DRAFT profiles and zero confirmed work. The initial report
requires runtime switches OFF and unchanged protected data. It is intentionally
not reusable after people log in or submit onboarding; use the onboarding stage
then. Every unexpected mismatch is a stop, not a reason to edit counts manually.

If connection loss makes commit uncertain, keep writers stopped and run
`roster_reset inspect`. If `roster_import_status` is `IMPORTED`, use verification,
not another reset. A verified initial same-manifest retry is safe; a different
manifest/password or subsequent user edits will fail closed. Restore refuses to
overwrite imported/live records. Recovery after a successful import requires a
new reviewed maintenance plan; do not hand-delete the real roster.

## 4. Phase 6 — deploy and genuine-user acceptance

Deploy the matching Python and Next.js revision together. Build the web app with
the VM's actual environment; never copy Windows `.venv`/`node_modules` to Linux.
Existing `.env` files stay private and host-specific.

For the already-configured VM services, **run in the VM shell, not PowerShell**:

```bash
cd /home/opc/AIML_INTERNAL_INITIATIVES/AI_POD_STAFFING
npm ci
npm run build
# Continue only after BOTH commands succeeded and the import checks passed.
systemctl --user daemon-reload
systemctl --user reset-failed ai-pod-api.service ai-pod-worker.service ai-pod-web.service
systemctl --user start ai-pod-api.service ai-pod-web.service
systemctl --user status ai-pod-api.service ai-pod-web.service --no-pager -l
curl --max-time 15 -fsS http://127.0.0.1:8015/health/ready
curl --max-time 15 -I -H 'Host: 140.245.228.123:8005' http://127.0.0.1:8005/
```

Web uses `STAFFING_BACKEND_URL=http://127.0.0.1:8015`, password backend mode,
personas false and `STAFFING_APP_ORIGIN` equal to the exact reviewer-facing
address (scheme/host/port). Do not use a different forwarded origin for login.
Use the approved network/TLS configuration; opening other shared-VM ports or
disabling its firewall is not part of this rollout. A local HTTP 200 does not
prove your team lead can reach the VM through the corporate network.

Start with an enabled real Administrator/Captain, have that person supply genuine
first-login information, and verify these cases. Use a test database for
artificial fixtures; do not contaminate the real roster with invented workloads.

| Check | Expected result |
| --- | --- |
| 18 enabled / 7 pending accounts | Enabled users can sign in; pending users cannot, even with the right password |
| Old account/session | Old demo login and old sessions no longer work |
| First login | Setup required; blank assessments remain blank; contract starts 8h/day, 40h/week |
| Exact roles | Highest granted role controls presentation; lower explicit capabilities remain; Amy is never a Member candidate |
| Self-entered actual work | Dated leave/external hours drive capacity; zero confirmed work is not fabricated seed allocation |
| Existing POD report | Self-reported dated workload counts immediately; setup completes; no approval queue or automatic assignment |
| Incomplete/disabled profile | Excluded from normal, alternative and manual staffing |
| Multi-role team | One person cannot fill two slots; capacity is shared across roles and projects |
| Captain access | Another Captain can view, select, manually override and approve; self-selection/self-approval is permitted |
| Recommendation choices | One Lead + two alternatives, requested contributor count + two alternatives when eligible candidates exist |
| Manual override | Explicit selected person; ignore skill/leave/external constraints only for that slot; existing+new POD hours cannot exceed 100% |
| Approval | Recalculate and show final team/percentages first; commit only on Captain approval; stale capacity/selection rechecked |
| Closure | Only the project's actually assigned Lead can close it |
| Access administration | Reason/audit/session revocation; self-disable and last-Admin/active-project-Lead safeguards retained |
| Sign out / expiration | Sign-out revokes session; expired or revoked sessions require login again |

After genuine onboarding, report progress (still read-only):

```powershell
.\.venv\Scripts\python.exe -m app.roster_release --stage onboarding --env-file .env --workbook "C:\Users\smaikoti\Downloads\Team Names and Access Type.xlsx" --batch roster4-real-roster --manifest .mvp/roster-import-plan.json
```

The report lists enabled completed profiles by exact role, unresolved POD claims
and runtime switches. `verified` is structural verification, **not** proof of
browser acceptance or sufficient skills/capacity for a particular request. At
initial import, zero people are staffing-ready by design. This first-rollout
check expects the approved roster/access/40-hour baseline; deliberate later
roster/access/contract changes need a separately reviewed baseline.

Only when onboarding/real skills permit meaningful staffing and acceptance is
approved, explicitly enable this application's worker runtime. Leave email OFF:

```sql
UPDATE staffing_runtime SET agents_enabled='Y'
WHERE runtime_id=1 AND agents_enabled='N' AND notifications_enabled='N';
COMMIT;
SELECT agents_enabled,notifications_enabled FROM staffing_runtime WHERE runtime_id=1;
```

Then on the VM:

```bash
systemctl --user start ai-pod-worker.service
systemctl --user status ai-pod-api.service ai-pod-worker.service ai-pod-web.service --no-pager -l
journalctl --user -u ai-pod-api.service -u ai-pod-worker.service -u ai-pod-web.service -n 80 --no-pager
```

The existing Python worker flag must also be enabled; neither importer nor
release verifier changes it. Run a genuine agreed test request through the
Supervisor/Analyst/Planner, choices, manual preview and approval. Record the
operator's acceptance separately. No messages or production test requests are
automatically sent/created by these tools.

## Regression coverage

`tests/test_roster_import.py` executes importer DML, transactional rollback,
exact-role/enrollment verification, all 18 enabled / 7 disabled password paths,
fresh salted hashes, idempotent retry, manifest tampering, source drift and
release gating against an isolated in-memory relational database. Oracle
metadata, archival fingerprinting, maintenance locks and actual Oracle constraints
are checked separately by the existing schema/recovery tests and live read-only
preflight. This is not represented as a live Oracle import rehearsal.

Existing roster/access/onboarding/explicit-role/selection tests cover the
remaining business-rule matrix. Run the full Python suite and web tests/build
before release; record unrelated pre-existing failures rather than hiding them.

Implementation verification (2026-09-23): 23 new importer/release tests passed;
the full Python suite had 633 passing tests plus 300 passing subtests, with two
previously observed failures (the demo-policy approval-flag fixture and Windows
OpenSSL entropy during JWT key generation). All 166 web tests and the production
build/type check passed. Live read-only preflight confirmed the retained rehearsal
and unchanged protected data. Live reset/import, real-browser acceptance and VM
deployment have **not** been executed by this implementation.
