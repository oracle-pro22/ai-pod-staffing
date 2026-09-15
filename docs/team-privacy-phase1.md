# Team profile visibility — Phase 1

Phase 1 adds the database permission migration and the Python endpoint that supplies the authoritative profile allowlist.

Phase 2 now connects the application and restricts alternate response paths. See [Phase 2 rollout and verification](team-privacy-phase2.md). The Phase 1 SQL has already been applied and verified in the current database; do not rerun it for Phase 2.

| Profile | Allowed full profiles |
| --- | --- |
| POD Member | Own active employee profile |
| POD Lead | Own profile and active employees in confirmed PODs they lead |
| POD Captain | All active staffing employees |
| Administrator | All active staffing employees |

A Lead gains access through a `CONFIRMED` assignment with `role_in_pod='POD_LEAD'` on a `STAFFED` request. Teammates must also have confirmed assignments. Pending recommendations, closed projects and a Lead-profile person occupying a Member slot do not grant access. Approved future or overdue projects remain eligible until formally closed. Employees remain visible if another qualifying active POD still links them to the Lead. Standalone Administrator accounts and inactive employees are excluded from the staffing directory.

## Python change

`GET /v1/workspace?resource=TEAM_SKILLS` now uses a dedicated query in `app/assignments.py`. It returns capacity and active-POD metrics only for the allowed IDs. Its `requests`, `assignments` and `days` arrays are empty: this profile endpoint does not include project rosters or schedule records. Permissions are checked before accessing Oracle. Members remain limited to themselves even while the old SCOPED database row awaits migration; OWN scope further restricts every profile.

Other resource queries retain their current behavior in this phase. **This is not the complete privacy rollout:** the current Next.js page still sources profiles from the Requests workspace. Phase 2 must consume the dedicated Team & Skills allowlist, restrict all alternative payload paths, and remove the Member's directory UI. Do not consider teammate data inaccessible throughout the application until that integration and response-level verification pass.

## SQL Developer steps

Use a fresh worksheet connected as `AI_POD_STAFFING`, with no unrelated pending transaction. Stop the application services during the permission migration.

1. Open `sql/oracle/team_privacy_phase1.sql` and run with **F5**.
2. Open `sql/oracle/team_privacy_phase1_verify.sql` and run with **F5**.
3. Expected scopes: Member `OWN`, Lead `SCOPED`, Captain `FULL`, Administrator `FULL`.

The migration updates only these four `TEAM_SKILLS.access_scope` values. It preserves create/update/approve/export flags and all business records. It creates one small recovery table, `AIPS_TP1_BK_SCOPE`, holding the four original scopes. No new business table is required. Keep the backup until the rollout is accepted.

The apply script can be rerun: it reuses the original backup, accepts original or already-applied scope values, and stops on conflicting later changes. If it fails, permission DML rolls back; Oracle DDL means a created backup stays committed. Inspect the reported error before retrying. Do not rerun `setup.sql`, historical catalogue migrations, or data-import scripts on the current database.

If the initial script reported `ORA-12801` with `ORA-12860` after creating the backup, reopen the updated script from disk and rerun the entire file with F5. The corrected apply and rollback scripts disable parallel DML, query and DDL for their session and explicitly use serial updates. The original backup is reused; do not delete it or run the rollback script as a prerequisite. Already-correct scopes are skipped, then all four results are checked before commit. Keep services stopped while retrying and use a fresh worksheet without unrelated pending transactions. This correction was reviewed locally; successful Oracle execution still needs confirmation from the verify script.

`team_privacy_phase1_rollback.sql` restores only the original scope values and preserves the backup and all action flags. It rejects unrelated later scope changes. This is a configuration rollback, not a code rollback.

## Verification performed

Offline tests execute the production SQL visibility predicate against an in-memory relational fixture. They cover four profiles, legacy Member scope, inactive and Administrator-only employees, confirmed and closed assignments, Lead-as-Member, future approved PODs, closure/revocation, overlapping POD access, endpoint payload limits and database failure. Tests for existing workspace and project closure behavior are also run.

No migration, approval, assignment or model call is executed by these tests. The supplied PL/SQL must still be executed and verified in your Oracle environment.

To run the focused Python tests:

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing\backend\python
.\.venv\Scripts\python.exe -m pytest tests/test_team_privacy.py tests/test_phase5.py tests/test_employee_directory.py -o addopts= -q
```

After migration, restart the Python API with its existing command. Phase 2 will wire the Next.js projection and UI to these rules.
