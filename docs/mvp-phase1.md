# Phase 1: password login and scoped workforce cleanup

This release implements Phase 1 only. It does not add the Supervisor or manual override; those remain Phases 2 and 3. No migration runs automatically at app startup.

## What changes

- Oracle email/password login replaces profile selection when password mode is configured. Python verifies credentials and revocable, eight-hour sessions. Roles and resource scopes still come from the existing authorization tables.
- Login placeholders use `firstname.lastname@oracle.com`, as requested. They are not verified employee addresses. **Keep notification sending disabled.** Replace the placeholders once the approved roster arrives.
- The proposed final roster is **4 Captains, 6 Leads, 20 Members and 1 Administrator (31 accounts)**. Fourteen new profiles use existing catalogue entries; no Administrator is added.
- Five older person IDs normalize to P-013 through P-017. P-001 through P-012 remain. Added employees are P-018 through P-031.
- An explicit manifest chooses old requests to archive, including dependent staffing history. Archived source rows remain in `MVP_P1_ARCHIVE`, with a recorded manifest and content fingerprints in `MVP_P1_RUNS`.
- Old test requests leave active tables only after their recoverable archive is committed. They no longer contribute scheduled workload. Existing leave/external-work events remain; new employees receive dated external commitments. Existing allocation/closure algorithms are unchanged.
- `APP_ACCOUNTS` and `APP_SESSIONS` hold account hashes and revocable session-token hashes. Existing people, role and permission tables remain authoritative.

## Protected content

No DML targets PROJECT_TYPES, DELIVERABLES, DELIVERABLE_SKILLS, INTERESTS or CUSTOMER_MAPPING. All 78 deliverables and their current statuses/mappings remain untouched. Existing policy tables, role definitions and permissions are also fingerprinted and must remain unchanged.

Existing person-skill ratings/evidence, deliverable experience and source availability must survive, with only their person IDs relinked where needed. Backup tables and old migration metadata are not deleted. Audit events are retained unchanged; their historical IDs can be resolved through the archived manifest.

Normal request cleanup is not simulated project completion: the selected test records are archived. Normal project closure continues preserving history through the closure day and releasing later scheduled hours.

## Before starting

1. Stop the Next.js application, Python API and worker wherever they connect to this database, including the VM and any local copy. Do not stop unrelated applications.
2. Keep a copy of the previous two environment files, and obtain a database/schema backup for an independent recovery option.
3. In SQL Developer, as AI_POD_STAFFING, pause runtime execution:

```sql
UPDATE staffing_runtime
SET agents_enabled='N', notifications_enabled='N', updated_by=USER, updated_at=SYSTIMESTAMP
WHERE runtime_id=1;
COMMIT;
SELECT execution_id,status FROM agent_executions WHERE status IN ('RUNNING','QUEUED');
```

The last query must return no rows. The migration never silently cancels queued/running executions. If rows appear, resolve those executions before cleanup.

## 1. Install the additive schema

Run **sql/oracle/mvp_phase1.sql** with F5 in SQL Developer. This creates four new tables only. It does not provision accounts, change the catalogue or turn agents on. Oracle DDL commits independently, so rerunning retains existing objects and the loader checks their shape before use.

Do not run setup.sql, a whole-database reset or the older app.demo_data loader for this migration.

## 2. Set the two environment files

Keep your existing database, wallet and OCI settings unchanged.

In **backend/python/.env**:

```dotenv
BACKEND_ENV=local
BACKEND_AUTH_MODE=password
STAFFING_DEMO_PERSONAS_ENABLED=false
STAFFING_SESSION_HOURS=8
STAFFING_MVP_DEFAULT_PASSWORD=<choose-one-shared-MVP-password-at-least-8-characters>
```

Replace the entire placeholder value. Do not commit the real password. The loader hashes it separately for every account; applying an already-applied manifest never resets passwords. Remove `STAFFING_MVP_DEFAULT_PASSWORD` after the account import if you do not need it again.

In the **root .env.local** for Windows development, or **root .env.production** for the VM:

```dotenv
STAFFING_DATA_SOURCE=oracle
STAFFING_AGENTIC_ENABLED=true
NEXT_PUBLIC_STAFFING_AGENTIC_ENABLED=true
STAFFING_BACKEND_AUTH_MODE=password
STAFFING_DEMO_PERSONAS_ENABLED=false
STAFFING_BACKEND_URL=http://127.0.0.1:8015
STAFFING_APP_ORIGIN=http://127.0.0.1:3001
```

On the VM change only the application origin above to the address people actually open, for example `http://140.245.228.123:8005`. Use that exact host/port consistently. The Python API can still listen on 127.0.0.1:8015. Password mode does not require OIDC or the old fixed-person/management token. Existing bearer/OIDC/local modes remain available only when explicitly configured instead of password mode.

Plain HTTP does not encrypt credentials; use the agreed VPN-only demo access. Use HTTPS if access expands beyond that environment. This release does not install a reverse proxy or change VM networking.

## 3. Generate and review a manifest (read-only)

From **backend/python** in PowerShell:

```powershell
New-Item -ItemType Directory -Force .mvp
.\.venv\Scripts\python.exe -m app.mvp_phase1 template --env-file .env --anchor 2026-09-14 --out .mvp/manifest.json
.\.venv\Scripts\python.exe -m app.mvp_phase1 preview --env-file .env --manifest .mvp/manifest.json
```

The template's default request list is the current list at generation time. **Review `archive_request_ids` before applying**; delete any ID from the manifest that must remain active. Retained frozen evidence that references an ID being normalized must be archived or that person rename omitted; the tool refuses to rewrite it silently.

Review `person_id_map`, `account_emails`, `add_people` and the Monday `anchor`. The supplied anchor preserves the current September demo period; choose the Monday of your intended demo instead if needed. The capacity horizon is nine complete weeks. Additional absence or commitment baselines cause a review error, never a silent overwrite.

The preview reports writes=0. Existing data changes after manifest generation cause `MVP_STALE_MANIFEST`: stop writers, generate a fresh manifest under a new filename, and review again. Never remove or fake `expected_snapshot` to bypass the check.

`.mvp/` is ignored by Git. Manifest files do not contain the shared password. Generated output uses exclusive file creation and will not overwrite an existing manifest.

## 4. Apply once, then verify

Without `--commit`, apply is a read-only preview. With `--commit`, this command **archives/removes the listed old requests from active tables, normalizes IDs, adds 14 people, replaces login identity mappings and provisions accounts**:

```powershell
.\.venv\Scripts\python.exe -m app.mvp_phase1 apply --env-file .env --manifest .mvp/manifest.json --operator smaikoti --services-stopped --commit
.\.venv\Scripts\python.exe -m app.mvp_phase1 verify --env-file .env --batch mvp1-2026-09-14
```

Use the `batch_id` from your manifest if different. The command prints stage progress to stderr and a JSON result to stdout. A large existing archive can take time; do not launch a second apply while the first is running.

The archive is committed first. The business changes then run in one transaction and are checked before commit. Because existing historical proposals/events/decisions are immutable, the maintenance operation temporarily disables exactly four delete-protection triggers while services are stopped: P2_MEMBER_FREEZE, P2_PROPOSAL_FREEZE, P2_DECISION_APPEND and P2_EVENT_APPEND. Foreign keys remain enabled; trigger definitions, audit protection and catalogue/policy protection are not changed. The original guards are restored afterward and their source fingerprints verified. Do not resume services with disabled guards.

Expected: 31 accounts, one Administrator, protected_tables_unchanged=true, existing_assessments_match_import_snapshot=true, and the intended requests removed. Person sequences only advance; they are never rewound. Existing assessment comparisons may legitimately differ later after users edit their own skills; compare immediately at cutover.

Sequence advancement uses Oracle 19c+ [ALTER SEQUENCE RESTART START WITH](https://docs.oracle.com/en/database/oracle/oracle-database/19/sqlrf/ALTER-SEQUENCE.html) only when the next ID is behind existing IDs, with writers stopped. It never resets to a smaller value or changes the increment. This avoids a long per-number loop when recovering the original P-900xxx IDs.

## 5. Start the application

For local Windows use three terminals:

```powershell
# Terminal 1 — backend/python
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8015 --env-file .env
```

```powershell
# Terminal 2 — repository root
npm run dev -- --hostname 127.0.0.1
```

Open `http://127.0.0.1:3001`. Use an email from the manifest and the shared password you configured. For example, the existing Alex profile uses `alex.rivera@oracle.com`; the Captain Indranie profile uses `indranie.balkaran@oracle.com`.

Verify login and role visibility before enabling request processing. When ready, retain your existing worker/decision flags, set database agents_enabled='Y' (notifications_enabled remains 'N'), then start:

```powershell
# Terminal 3 — backend/python
.\.venv\Scripts\python.exe -m app.worker --env-file .env
```

On the VM use the same existing three services. Rebuild Next.js when changing public flags and restart it with `.env.production`; Python services continue loading backend/python/.env explicitly. Never launch duplicate API listeners on port 8015.

## Recovery

- If an older copy stopped immediately after `Relinking person IDs` with `DATABASE_UNAVAILABLE`, the initial metadata query incorrectly requested `VIRTUAL_COLUMN` from `USER_TAB_COLUMNS` (ORA-00904). The corrected loader uses `USER_TAB_COLS`, excludes generated/internal columns, and checks that query during the read-only preview. See [Oracle's column dictionary reference](https://docs.oracle.com/en/database/oracle/oracle-database/19/refrn/ALL_TAB_COLS.html). On the inspected `mvp1-2026-09-14` attempt, the batch remained PREPARED, all business/protected content matched its original fingerprint, all 2,543 archive rows verified, and guard definitions/statuses matched the enabled originals. After updating the loader, rerun preview and the same apply command with the existing manifest; do not recreate tables or discard the archive. CLI errors now include a sanitized `driver_code` when available without exposing SQL or credentials.
- Before business commit, an error rolls back the business changes and retains the archive. Read the error and rerun the same reviewed manifest only after resolving it; a changed database requires renewed review.
- If the process was killed during trigger maintenance, keep every writer stopped and run:

```powershell
.\.venv\Scripts\python.exe -m app.mvp_phase1 recover-guards --env-file .env --batch mvp1-2026-09-14 --services-stopped
```

- After commit, retrying the same manifest is idempotent and does not duplicate people or reset passwords. It can finish sequence advancement interrupted after commit.
- To undo an applied migration **before any further business edits**, preview recovery first:

```powershell
.\.venv\Scripts\python.exe -m app.mvp_phase1 restore --env-file .env --batch mvp1-2026-09-14 --services-stopped
# Only after reviewing restore_ready=true:
.\.venv\Scripts\python.exe -m app.mvp_phase1 restore --env-file .env --batch mvp1-2026-09-14 --services-stopped --commit
```

Restoration removes imported accounts/sessions, restores original person/role/availability/capacity rows and returns archived requests to active tables. It refuses if the business snapshot or account roster changed since apply. In addition to the four history guards, restoration briefly disables P2_DECISION_REVIEW to restore genuine already-decided historical rows; all five definitions/statuses are verified and restored. Restore the previous environment authentication settings before restarting. Archive and migration records remain for recovery; sequences are not rewound.

- If later business work exists, automated restoration stops. Export the archive and perform a reviewed, selective recovery instead:

```powershell
.\.venv\Scripts\python.exe -m app.mvp_phase1 export-archive --env-file .env --batch mvp1-2026-09-14 --out .mvp/archive.json
```

Archive JSON contains typed date/decimal values, original IDs and private staffing evidence. Keep it internal and out of Git. Do not delete earlier backup tables or disable unrelated constraints to force a recovery.

## Verification commands

```powershell
# backend/python: offline tests, no Oracle writes or OCI calls
.\.venv\Scripts\python.exe -m pytest

# repository root
npm run test:login
npm run test:personas
npm run test:agentic
npm run test:skills
npm run test:application
npx tsc --noEmit
```

The migration's live apply/restore path still needs an operator-run acceptance test on a recoverable database copy or during the agreed maintenance window. A successful read-only preview and offline test suite do not claim that the migration has already been executed against Oracle.

### Implementation checks performed

- Production Next.js build and TypeScript checks passed; the password entry page was visually checked in the browser.
- All 131 frontend regression tests and all 27 new password/migration tests passed.
- Full Python suite: 424 passed, two failures outside this change. The existing policy SQL test expects `approve_policy=FALSE`, but the checked-in `demo_phase2_policy.sql` already sets it to TRUE; it was not edited. The existing OIDC RSA-generation test fails with an OpenSSL entropy-provider error in this runtime. Neither issue was hidden by changing the old test or policy.
- Read-only Oracle preview passed for 20 listed requests, five ID changes, 14 additional people and 31 accounts total. It confirmed no proposed catalogue/assessment changes. Runtime switches, schema, business data and local environment files were not changed by these checks. No OCI calls or emails were made.
