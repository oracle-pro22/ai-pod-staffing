# Roles and catalogue migration

Run `roles_catalog.sql` once using **F5 / Run Script** in Oracle SQL Developer.
Run `rollback_roles_catalog.sql` only if recovery is needed. Both files are
self-contained; SQL Developer does not need the CSV, Python, or an `@` include.

## Before running

1. Stop **only AI Pod Staffing**, locally and on the VM if both use this schema.
   Keep it stopped until the matching application changes have been deployed.
   Older application builds expect the old profile names and do not filter
   retired deliverables. Deploy the matching application update described in
   `docs/roles-catalog-application.md`. SQL alone does not implement application
   permission checks or project closure.
2. Open a **fresh, dedicated connection** using AIPOD, with no pending edits or
   other scripts. The database session user and current schema must both be
   `AI_POD_STAFFING`. Do not use ADMIN or another team member's account.
3. Open `roles_catalog.sql` with File > Open. Select AIPOD in the file's connection
   dropdown. Click inside the file, clear any text selection, and press **F5**.
4. Keep the complete Script Output, including the first error if one occurs.
   Do not select and rerun a fragment of the file.

## Changes included

- Register POD Captain; rename Pod Lead to POD Lead and System Administrator to
  Administrator. Keep the existing `SYSTEM_ADMINISTRATOR` internal code.
- Keep POD Member. Deactivate Operations Lead, Request Lead and Executive.
- Move Operations Lead / Request Lead user mappings to POD Captain. Identical
  same-user mappings are collapsed; conflicting person IDs, activity flags or
  effective dates stop the migration before changes. The original mapping rows
  remain in the backup. Expired/inactive Executive mappings are preserved;
  active or future Executive assignments stop the migration for review.
- Create 48 permission rows for four profiles across nine existing screen
  resources and three additional resources: PROJECT_CLOSURE, ACCESS_MANAGEMENT,
  BACKEND_CONFIGURATION. Inactive legacy roles have no live permissions.
- Captain can submit/update requests, run/review fitment and approve a POD.
  Captain can view reports and allocation but cannot export or edit allocation.
  Lead can update/close assigned projects but cannot submit requests or approve
  PODs. Member can view assigned team/personal information. Administrator has
  administrative resources only. Personal availability is read-only for now.
  These conservative permissions follow the supplied profile descriptions;
  additional privileges can be explicitly enabled later.
- Import `Project-Deliverable-Skills-Mapping-v260810.csv` as revision
  `v260810.r2-20260910`. Preserve all 85 raw data rows, including 12 separator rows,
  in CUSTOMER_MAPPING. Preserve earlier source revisions as well.
- Keep 11 project IDs; rename Special Projects to Special Projects/ Ad Hoc.
- Preserve the 55 existing deliverable IDs, add DEL-056 through DEL-078, and
  deactivate DEL-005, DEL-013, DEL-020, DEL-041, DEL-044 for future selection.
- Add Comms Team as SK-014, preserving all 13 existing skills. Do not assign it to
  people: the CSV supplies capability requirements, not personnel evidence.
- Preserve the blank skill in CSV row 16 (Service Updates / Solution Matrix
  Updates). Allow DELIVERABLES.skills_raw to be NULL and remove that deliverable's
  default GTM SME link. This means "no default capability supplied," not that the
  task needs no skills. The business owner can supply a corrected mapping later.
- Add DELIVERABLES.active_flag (Y/N, default Y) to identify retired entries.
- Preserve spelling and terminology in the CSV; do not merge GTM, GMT SME,
  Comms Team, Comms Review, Comms Plan or other distinct source labels.

Only the five catalogue tables and three role tables receive data changes.
PEOPLE, PERSON_INTERESTS, REQUESTS, REQUIREMENTS, RECOMMENDATIONS and AVAILABILITY
are not updated. Approval/closure metadata and the seven governance tables are
not part of this migration. No new business tables are created.

## Expected success

Look for **SUCCESS: roles and catalogue migration committed** in Script Output.

| Check | Expected |
| --- | ---: |
| Project types | 11 |
| Deliverables total | 78 |
| Active deliverables | 73 |
| Retired deliverables | 5 |
| Skills | 14 |
| Skill links for active deliverables | 114 |
| All skill links, including historical deliverables | 129 |
| Raw rows in the new source revision | 85 |
| Active official profiles | 4 |
| Permission rows | 48 |

The script checks the exact original catalogue before changing it. If your live
catalogue differs from the supplied setup baseline, it stops instead of guessing
how to merge those changes. Extra people or requests do not affect this check.

## Recovery and reruns

Oracle commits DDL separately. A plain ROLLBACK cannot undo ALTER TABLE.
The migration therefore creates eight `AIPS_BK_*` backup tables and one
`AIPS_MIG_BACKUP` manifest, **only within AI_POD_STAFFING**. These are technical
recovery objects, not the governance tables on hold. It saves and verifies the
original data before changing business-table structure. Do not edit/delete these
backups during the recovery window.

All catalogue/role data changes, final checks and the APPLIED marker commit in
one transaction. A raised error rolls back that entire transaction. Backups and
any completed DDL remain available for recovery.

| Situation | What to do |
| --- | --- |
| Wrong user/schema | Select the AI_POD_STAFFING connection and run the entire file again. |
| Baseline mismatch, unexpected schema or enabled triggers | Stop. Share the first error and inspect the difference. Do not bypass the check. |
| Active/future Executive assignment | Obtain an explicit official-role mapping for that user before rerunning. |
| Conflicting legacy user-role mappings | Review the person's mapping and effective dates; the script will not guess. |
| ORA-01950 / quota or storage error | Ask the DBA for sufficient quota on this schema's tablespace, then rerun the whole migration. No automatic grants are performed. |
| ORA-00054 / object locked | Keep the app stopped; finish other work touching these tables and rerun. Do not kill unrelated sessions. |
| Failure before any backup is committed | Business data is unchanged; empty backup structures may exist. Rerun after fixing the cause. |
| PREPARED state after DDL or data failure | Fix the cause and rerun the migration, or run the recovery file. |
| APPLIED state / uncertain connection result | Rerun the migration; it verifies the saved final snapshot and reports ALREADY APPLIED without duplicating data. |
| Want to undo a completed migration | Keep the app stopped and run the entire recovery file with F5. |
| Recovery detects later data changes/new catalogue usage | It stops. Preserve the backups and review the new records before preparing a targeted recovery. |
| Recovery DDL fails after DATA_RESTORED | Data has already been restored. Fix the DDL cause and rerun recovery to finish the schema step. |
| ROLLED_BACK state | Recovery completed. Use a new reviewed migration to try again; the original backups are not overwritten. |

Recovery compares current data with the saved post-migration snapshots before
restoring records. It restores original rows in place with foreign keys enabled,
removes only newly inserted keys, verifies the original contents, then restores
the original nullable/active-column structure. It also checks that new requests,
requirements or personal skills do not depend on the new catalogue. This is
immediate deployment recovery, not a substitute for regular DBA backups or a
general restore after the application has resumed writing.

To inspect the checkpoint in a separate fresh worksheet after the script exits:

```sql
SELECT object_name, state, saved_at
FROM AI_POD_STAFFING.AIPS_MIG_BACKUP
WHERE object_name = 'HEADER';
```

If the manifest was never created, that query can report ORA-00942; no business
changes can have been made by this migration at that point.

## Application work after successful SQL

Update role names/validation, scoped permissions and user mapping; make permission
lookups deny missing/inactive roles. Filter current catalogue selections by
active_flag while retaining retired records for historical display. Filter raw
customer mapping by the current source revision, handle an empty default-skill
list, and refresh request-form data. Do not automatically rewrite historical
request requirements. Then build, test the four profiles and restart the app.

## Verification performed locally

The generator and tests validate CSV counts, stable IDs, links, retirement,
permissions, transaction failure behavior in a local SQL simulation, recovery
ordering and regeneration consistency. Oracle JSON/DDL syntax was reviewed
against Oracle documentation. **These scripts have not been executed or compiled
against your Oracle database.** Database-side preconditions may therefore stop
execution; preserve the first error rather than editing around it.

Oracle transaction reference:
https://docs.oracle.com/en/database/oracle/oracle-database/19/tdddg/committing-transactions.html
