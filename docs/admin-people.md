# Administrator access and Add person

This update supersedes the Administrator visibility restriction in roles-catalog-application.md.

## Activate

1. Stop only AI Pod Staffing writers (local and VM copies using this schema).
2. In SQL Developer, use a fresh **AIPOD** connection as **AI_POD_STAFFING**, with no pending edits. Open `sql/oracle/admin_people.sql`, select AIPOD, clear any selection, and press **F5 / Run Script**. Do not run setup.sql or the catalogue migration again.
3. Look for `SUCCESS: Administrator can view all sections and add people.`
4. Start locally with `npm run dev` and reload. On the VM, deploy the matching code, run `npm ci` and `npm run build`, then restart only this app's existing service on port 8005.

No environment changes or new dependencies are required. Until the migration is applied, existing database permissions keep Administrator screens locked and Add person unavailable.

## Database scope and recovery

- The SQL checks the session user and current schema, the enhanced PEOPLE table, and all 12 Administrator resource rows.
- It backs up Administrator permissions to `AIPS_BK_ADMIN_ACCESS` without replacing an existing backup.
- It creates `PERSON_ID_SEQ` above existing numeric P- IDs. An incompatible existing sequence stops the migration; it is never reset. Sequence gaps are normal, and IDs beyond P-999 are not truncated.
- It creates a case-insensitive, trimmed unique email index `UQ_PEOPLE_EMAIL_CI`. Existing duplicate emails stop setup for manual review; people are never merged or deleted automatically.
- Only Administrator view/access scope and TEAM_SKILLS create permission change. Other profiles and approval/request-create/export permissions remain unchanged.
- The migration and rollback disable parallel execution for their own session only. The permission change uses one serial UPDATE, avoiding the ORA-12860 sibling-lock failure of the earlier two-update version.
- Existing people, roles assigned to people, requests, catalogue records, and on-hold governance objects are not modified.
- Oracle DDL commits independently. If a later step fails, the backup, sequence or index can remain. Preserve them, inspect the first error, and rerun the full script after resolving it. Do not delete objects to retry.
- If the original run failed with ORA-12860 after the first PL/SQL block completed, the permission transaction was rolled back but its earlier DDL remains. Reopen the corrected admin_people.sql from disk and run the entire file in a fresh AIPOD connection. Existing valid backup/sequence/index objects are reused; they are not recreated or reset.
- `sql/oracle/rollback_admin_people.sql` restores the backed-up view/scope/create permissions only. Use it before unrelated subsequent permission edits. It deliberately retains all people, the sequence, email index and backup.

## Use and verify

1. Select Administrator. Every navigation section should open; AI Fitment includes all stored recommendation evidence. Opening a screen does not grant approval or other write privileges.
2. In Team & Skills click Add person. Enter full name, job title, location, allocation (0–100), active POD count, and preferably email. Allocation and POD count require explicit input, including 0 if applicable.
3. Save. Confirm `Person added` with a P- numeric ID. Reload and verify the person remains in the directory.
4. Switch to POD Captain, open New request, and search for the new person under Request source. Each form opening fetches current active names from Oracle, including people added in another session. The dropdown still displays names only.
5. Select the person and save a test request if desired. The existing request endpoint validates the active person ID and stores the canonical name.
6. Try a duplicate email: the save should fail clearly and retain form input. Identical names are warned about but allowed because different people may share a name.
7. Verify Captain/Lead/Member cannot create people. The endpoint checks both Administrator profile and database create permission, independently of the button.
8. Administrator can inspect any active person's availability using a names-only selector; it does not claim that person is the signed-in administrator.

Creation inserts one active PEOPLE row. It does not create a login, assign APP_USER_ROLES, invent skill evidence, or grant lead eligibility. Approval/assignment/closure and governance persistence remain on hold.

On a network timeout, check the refreshed directory before retrying: the database may have committed even though the response was lost. Email helps identify duplicates; a missing email does not provide cross-request idempotency.

## Verification and security boundary

Run `npm run test:application` (21 tests) and `npm run build`. Tests use mocked Oracle calls and rendered screens, including the old permission baseline and the expanded Administrator permissions. They do not execute the migration or insert live people. Complete the manual checks above after applying SQL.

`STAFFING_AUTH_MODE=preview` still permits role switching for a trusted demo. A browser-selected role is not proof of identity. Authenticated OCI subject mapping and server-side identity-based initial data loading are still required before production RBAC.
