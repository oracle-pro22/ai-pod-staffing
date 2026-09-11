# AI Pod Staffing

AI Pod Staffing is a component-based Next.js application for staffing requests, evidence-based fitment, allocation planning and human approval.

## Run locally

```powershell
npm install
npm run dev
```

Open [http://localhost:3001](http://localhost:3001). The development script uses port 3001 because port 3000 is used by another local application on this machine.

For a production check:

```powershell
npm run build
npm run start -- -H 0.0.0.0 -p 8005
```

## Application routes

Employee skills/interests backend setup and safe testing: [Phase 1 runbook](docs/self-skills-phase1.md). Apply `sql/oracle/self_skills.sql` before running the matching Oracle-backed application. The interface is available under Team & Skills; see the [Phase 2 usage guide](docs/self-skills-phase2.md).

- `/` — primary React/Next.js application.
- `/react-preview` — compatibility route that redirects to `/`.
- `/prototype.html` — preserved legacy HTML rollback reference.
- `/api/staffing` — server-side staffing view-model boundary.
- `/api/chat` — server-side chat boundary for the future governed AI integration.

## Structure

- `app/` — Next.js routes and global application styles.
- `components/shell/` — application shell and global navigation.
- `components/screens/` — workspace screens.
- `components/ui/` — reusable controls and overlays.
- `context/` — application state, persona scope and session actions.
- `lib/staffing-data.ts` — server-only workbook adapter.
- `lib/selectors.ts` and `lib/role-policy.ts` — scoped data selection and role policy.
- `data/ai-pod-staffing-prototype.xlsx` — current prototype data source.
- `styles/react-foundation.css` — shared visual system that preserves the approved UI.

## Data and future backend handoff

The workbook is read only on the server; it is not downloaded into the browser. The current API and data-source boundary can later be replaced by Oracle Database 26ai services without rewriting the screen components. `sql/001_ai_pod_staffing.sql` contains the initial relational schema and load templates.

Migration evidence and acceptance records are under `docs/migration/`.
# Deliverable experience update

For catalogue-based deliverable experience and in-field OCI AI rephrasing, run the additive `sql/oracle/deliverable_experience.sql` migration before deploying this update. See [setup and verification](docs/deliverable-experience.md). Existing tables and skill ratings are retained.
