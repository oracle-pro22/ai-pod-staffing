# Employee skills and interests — Phase 1

Phase 1 supplies the Oracle migration and backend APIs. The interface is now implemented separately in [Phase 2](self-skills-phase2.md), using the existing Create request UI style. No existing business table is dropped or reloaded, and the seven on-hold governance tables remain on hold.

## What changes

| Existing table | Change | Purpose |
| --- | --- | --- |
| `INTERESTS` | `ASSESSMENT_TYPE`, nullable `DERIVED_ROLE_CODE` with a role foreign key | Distinguish self-assessed skills from capabilities conferred by a role. |
| `PERSON_INTERESTS` | `INTERESTED_FLAG`, `UPDATED_AT`, `UPDATED_BY`; allow nullable strength/evidence | Store proficiency, interest only, or both, plus the latest edit metadata. |
| `PEOPLE` | `SKILLS_VERSION` | Detect stale whole-profile saves, including additions and removals. |
| `ROLE_PERMISSIONS` | Four `MY_SKILLS` rows | Lead and Member get OWN view/create/update; Captain and Administrator do not get this self-service action. Other permissions are unchanged. |

`APP_ROLES` and `APP_USER_ROLES` are read, not changed. Four `AIPS_SK_BK_*` backup tables preserve the pre-migration rows for recovery review. These are not application tables. No new employee, recommendation, request, assignment, or role membership is created by this migration.

Rules:

- Only existing `INTERESTS` entries classified `SELF_RATED` can be selected. No free-text skills or synonym substitution.
- `SK-001 / Project Manager (GTM SME)` is `ROLE_DERIVED`: users cannot add, edit, remove or rate it through this API. GTM SME remains a distinct self-assessed skill.
- The Project Manager role mapping is **deliberately unset** pending confirmation. Even POD Lead preview does not automatically confer it. Once an approved mapping exists, the API requires an active role and an active, currently effective `APP_USER_ROLES` record for that person.
- An interest-only entry has `strength: null`, `interested: true`, and optional evidence. New proficiency ratings are whole numbers 1–5 and require evidence. Existing decimal ratings remain stored unchanged.
- Existing rows default to `INTERESTED_FLAG=N`, meaning interest was **not indicated**, not that an employee expressed disinterest. Migration leaves edit metadata null; it does not fabricate an employee edit.
- Saved ratings use source `Self-assessment`; this is not verified expertise. `UPDATED_BY` is latest-edit metadata, not an immutable audit trail.
- Existing Project Manager ratings remain in the database. The regular app mapper excludes role-derived ratings and unrated interests from rated-skill lists and averages. Role capabilities and interest-only displays are available through the new API for Phase 2. Stored recommendations are not recalculated or rewritten.

## Identity limitation — important

The current app is a **role-preview demo, not authenticated employee sign-in**. In this mode, the server uses the same fixed demo identities as the UI:

| Preview | Person edited |
| --- | --- |
| POD Member | `P-001` |
| POD Lead | `P-006` |

The API rejects a submitted `personId`, role override or source override. It checks that the server-selected person exists and is active and checks the dedicated Oracle permission. However, anyone who can reach a preview-mode server can submit the preview role header. This is not production access control.

Saving now writes directly to Oracle, subject to the existing profile permissions and validation. The extra demo-write flag has been removed. Real deployment still requires authenticated identity-to-person resolution before self-service editing is opened to employees. Do not treat a selected demo profile as an actual role assignment.

## Deploy in this order

1. Stop **only AI Pod Staffing** writers, including local and VM copies connected to this schema. Do not stop other shared-VM applications.
2. In SQL Developer, open a fresh connection to `AI_POD_STAFFING` (connection label `AIPOD`). Resolve any pending work deliberately first; Oracle DDL commits automatically.
3. Open `sql/oracle/self_skills.sql`, select AIPOD and press **F5 / Run Script**. Do not run `setup.sql` again. This migration expects the already-applied official profile and catalogue changes.
4. Verify `SUCCESS: self-skills schema and OWN permissions committed.` For the current 14-skill catalogue, expect 13 self-rated and 1 role-derived entry. Four MY_SKILLS permission rows should be printed, with OWN for Lead and Member.
5. Deploy this matching application code. The main Oracle read now includes `ASSESSMENT_TYPE`, so apply the SQL **before starting this code**.
6. For an explicitly approved demo test, add the following to local `.env.local`, or the VM's `.env.production`:

```ini
STAFFING_DATA_SOURCE=oracle
STAFFING_AUTH_MODE=preview
```

Leave your existing Oracle wallet and credentials unchanged. Do not commit environment files. There is no extra skills-saving flag to configure.

7. Local: run `npm run dev`. VM: run `npm run build` and restart only this app's existing service/process on port 8005. No separate backend process, package installation or port is required.

## API contract

Both endpoints are `Cache-Control: no-store` and use the existing preview header `x-staffing-role: POD Member` or `POD Lead`.

- `GET /api/me/skills` → `{ data: { personId, fullName, version, identityMode, catalogue, skills, roleCapabilities, warnings } }`
- `PATCH /api/me/skills` → `{ data: { personId, version } }`; fetch GET again after success.

PATCH sends only explicitly changed rows and explicitly removed IDs. Omitted skills are unchanged. Every upsert is a complete assessment, not a partial field edit:

```json
{
  "version": 0,
  "upserts": [
    {
      "skillId": "SK-014",
      "strength": null,
      "interested": true,
      "evidence": ""
    }
  ],
  "removeSkillIds": []
}
```

Use the version from the latest GET, not a hardcoded zero. Duplicate IDs or an ID appearing in both lists are rejected. Evidence is limited to 2,000 UTF-8 bytes to fit the existing Oracle column safely. The employee row is locked, the version checked, all changes saved in one transaction, and the version incremented once. A stale version returns **409**; reload and reconcile without automatically overwriting the newer edits. Direct/manual SQL writers must coordinate with this API; bypassing its version protocol is not protected.

## Verify locally

Read-only PowerShell checks after migration and app startup:

```powershell
$skillsHeaders = @{ 'x-staffing-role' = 'POD Member' }
$skillsProfile = (Invoke-RestMethod -Uri 'http://localhost:3001/api/me/skills' -Headers $skillsHeaders).data
$skillsProfile | Select-Object personId, fullName, version, identityMode
$skillsProfile.catalogue | Format-Table
$skillsProfile.skills | Format-Table
$skillsProfile.warnings
```

Check that the ID is `P-001`, the dropdown catalogue contains GTM SME / Comms Team, and does not contain Project Manager. Lead GET should resolve `P-006`. No missing person should fall back to another employee.

Optional **real database write** smoke test: only run after approving that `P-001` is the demo employee you intend to edit. Prefer a skill not already in their list; stop if SK-014 exists so this test does not overwrite their data:

```powershell
if ($skillsProfile.skills.skillId -contains 'SK-014') { throw 'SK-014 already exists. Choose a different test or inspect it first.' }
$skillsBody = @{
  version = $skillsProfile.version
  upserts = @(@{ skillId = 'SK-014'; strength = $null; interested = $true; evidence = '' })
} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Method Patch -Uri 'http://localhost:3001/api/me/skills' -Headers $skillsHeaders -ContentType 'application/json' -Body $skillsBody
```

Then:

1. GET again: one unrated interested entry, version increased by one. Inspect `PERSON_INTERESTS` in SQL Developer for `Self-assessment`, timestamp and preview actor.
2. Resend the **old** body: expect 409, with no change.
3. Attempt SK-001 or an unknown skill: expect 400. Attempt another `personId`: expect 400. Administrator/Captain should get 403.
4. If desired, explicitly remove the newly added test entry using `removeSkillIds: ["SK-014"]` and the latest version. Never remove a pre-existing assessment as test cleanup.
5. For real concurrency acceptance, issue two saves against the same version in two clients: exactly one should succeed; the other returns 409. Offline tests simulate this contract but cannot prove the target Oracle instance's runtime behavior.

Offline checks (no Oracle connection or writes):

```powershell
npm run test:application
npm run test:skills
npx tsc --noEmit
npm run build
```

## If migration or deployment fails

- Keep the application stopped and retain the complete SQL Developer output. DML rolls back on errors, but earlier DDL/backups can remain.
- Resolve the specific error, reconnect if SQL Developer exited the session, and rerun **this migration only**. It retains marked backups, adds missing columns/constraints, and reapplies only MY_SKILLS permissions. A name collision with an unmarked backup deliberately stops for review. Do not drop objects to bypass it.
- For an emergency feature disable after successful deployment, run `sql/oracle/self_skills_disable.sql` with F5 as AIPOD. This locks MY_SKILLS only; it preserves all data and other permissions. Refresh the application afterwards. The old environment flag no longer disables saving.
- Disabling is **not a full schema rollback**. Keep this version's null-safe mapper if interest-only records exist. Do not automatically restore all backup rows: that could overwrite newer legitimate assessments. A full restoration requires a reviewed, scoped data comparison and approval.
- Retain all four `AIPS_SK_BK_*` tables throughout the recovery window. They contain employee data; apply the same access restrictions as the source schema.
- Do not rerun older catalogue/admin migrations blindly after this migration: their historical expected permission counts predate MY_SKILLS.

## Phase 2 handoff (implemented)

The modal and searchable catalogue selector now use these APIs, retain drafts on validation/conflict errors, and refresh the shared view model after success. Self-rated proficiency, interest, and read-only role capabilities are shown separately. No extra business tables are needed. See the [Phase 2 usage guide](self-skills-phase2.md).
