# Official profiles and current catalogue — application rollout

This application version matches the successfully applied `sql/oracle/roles_catalog.sql` migration. Do not rerun the migration or delete its backup tables.

## What changed

- The selector shows **POD Captain**, **POD Lead**, **POD Member**, and **Administrator**.
- Screens and actions use the active Oracle `APP_ROLES` / `ROLE_PERMISSIONS` rows, including create, approve, update, export, and access scopes. Missing/inactive permissions deny access.
- Previous browser preview selections are migrated to the official names. Role switches close dialogs, reset selections/filters, stop animation state, and clear chat history.
- The new-request form and Administration taxonomy include active deliverables only. Expected post-migration catalogue: 11 projects, 73 active deliverables, 14 skills, and 114 active skill links.
- All 78 deliverables remain readable for historical request resolution. Old request descriptions, deliverable snapshots, requirements and source revisions are not regenerated from the new catalogue.
- Comms Team and the renamed Special Projects/ Ad Hoc are read from Oracle, not hard-coded into the form.
- Service Updates / Solution Matrix Updates has no supplied default skills. The form explains this and requires the requester to add at least one capability. It does not silently restore GTM SME.
- New-request saves validate current active deliverables server-side, use canonical database names, and stamp the current source revision. An old open form cannot save a retired mapped deliverable.
- Chat and the staffing JSON endpoint use the same profile scopes. Request saving, availability saving and AI rephrasing recheck database permissions server-side.
- Existing request source name search, date rules, rephrasing, form styling, and Captain demo fitment remain in place.

## Profile behaviour

| Profile | Current application behaviour |
| --- | --- |
| POD Captain | All staffing requests/people; new request and AI rephrase; demo fitment/review; approval opens the existing preview, with a Feature in progress toast on confirmation. |
| POD Lead | Assigned projects, approved POD evidence, team and own availability; no submission, fitment rerun, or approval. Close project currently displays Feature in progress. |
| POD Member | Assigned projects/team and own personal information, read-only. |
| Administrator | Administration, current taxonomy and permission matrix; operational screens locked. Configuration/access/audit actions are placeholders. |

The migration grants no request/report export or availability-create permission to these profiles. Those buttons are intentionally unavailable rather than overriding the database rules.

The seven governance tables remain on hold. Approval persistence, project editing/closure persistence, access editing, and configurable policy management are **not implemented** by this update. No new tables, columns or workflow records were written by this application change.

## Preview identity limitation

`STAFFING_AUTH_MODE=preview` remains a demo mode, **not authenticated production RBAC**. A browser-selectable profile / request header is not a verified identity. The initial server-rendered page still supplies the complete demo view model to support profile switching. Do not treat screen hiding or scoped API responses as a confidentiality boundary.

Preview identity is Captain = the active person named Indranie Balkaran; Lead = P-006; Member = P-001. A missing person yields an empty identity, never an arbitrary fallback. The role selector does not change a person's job title or database membership.

Until final assignments exist, Lead/Member project scope uses an existing recommendation with **selected_flag = Y AND decision_status = APPROVED**; Lead additionally requires a lead role in that POD. Pending, declined, unselected, and simulated demo recommendations do not grant assignment access. Therefore Lead/Member screens may legitimately be empty with the current seed data. No assignments or approvals were fabricated to fill these screens.

Before production rollout, implement authenticated OCI subject mapping, server-side identity-based initial data loading, and the reviewed assignment/approval model. Existing migrated APP_USER_ROLES mappings are preserved but are not used as login authentication yet.

## Run locally

No new environment variables or packages are required. Preserve the existing database wallet/password and OCI GenAI settings in `.env.local`.

```ini
STAFFING_DATA_SOURCE=oracle
STAFFING_AUTH_MODE=preview
```

Oracle is now the default when STAFFING_DATA_SOURCE is omitted. Explicit Excel mode is a legacy data preview without migrated permissions; it is not the supported configuration for this rollout.

From the project directory:

```powershell
npm run test:application
npm run dev
```

Open http://localhost:3001 and reload the page. If a development server is already running, restart only this application's process.

## Deploy on the VM

Keep the successfully migrated database in place. Deploy the matching application files to:

`/home/opc/AIML_INTERNAL_INITIATIVES/AI_POD_STAFFING`

Use your existing approved AI Pod Staffing stop/start procedure; do not stop another application's Node processes. With this application's service stopped:

```bash
cd /home/opc/AIML_INTERNAL_INITIATIVES/AI_POD_STAFFING
npm ci
npm run test:application
npm run build
```

Start/restart only the existing AI Pod Staffing service on port 8005. Preserve the VM's production environment and wallet paths. Do not copy Windows node_modules or .next onto the VM. A production `next start` requires the new `npm run build`; pulling files alone will still show the old build.

## Manual smoke test against your migrated database

1. Reload; confirm exactly four profile options, including a restored session that used Operations Lead.
2. As Captain, open New request. Check Comms Team, Special Projects/ Ad Hoc, and that the five retired IDs cannot be chosen.
3. Select Service Updates / Solution Matrix Updates. Confirm the no-default-capability guidance and add the needed capability explicitly.
4. Check an existing historical request: its stored descriptions/requirements must remain intact.
5. Save a test request only if desired; confirm the new request appears after refresh and Run fitment still shows labelled demo suggestions.
6. Switch to Lead and Member; confirm scoped/empty states and no New request, approval or export buttons. Pending suggestions must not give project access.
7. Switch to Administrator; confirm Administration opens and catalogue/permission tabs work. Governance actions should show Feature in progress.
8. Verify rephrase as Captain with your existing OCI settings. Other profiles must not be able to call it as a permitted action.

## Verification performed

`npm run test:application` runs 14 offline tests against actual mapper, permission, selector, repository and screen-rendering code, using the 48 permission rows from the migration. Tests cover canonical request names, rejected retired submissions, missing permissions, role scoping, demo fitment and rendered actions.

`npm run build` checks compilation/types and produces the production bundle. These checks do not connect to Oracle or invoke OCI GenAI; complete the manual smoke test on your connected machine/VM.

