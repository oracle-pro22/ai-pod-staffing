# Demo improvement — Phase 3: enter as a real person

Phase 3 adds the four-profile entrance to the existing application. It does not replace the dashboard design, reset data, change role assignments, approve PODs or enable email.

## What you will see

Open the application, select a profile, choose a name, and click **Enter workspace**. The searchable list shows names only and uses current, active Oracle role mappings.

| Profile | People already configured | First screen |
| --- | --- | --- |
| POD Captain | Indranie Balkaran, Brenna Cooper | Command Center; create requests and review/approve their PODs |
| POD Lead | Elena Garcia, Priya Nair, Mara Bennett | Requests; only projects assigned to that person |
| POD Member | The other 11 employees | Team & Skills; own skills, interests and deliverable experience |
| Administrator | Standalone Administrator account | Administration; existing administration and people-management tools |

Both Leads and Members can open **My Availability** and add their own unavailable time. The selected person's name appears in the sidebar. **Change profile** in the top bar returns to the entrance and clears the old workspace state. Switching is browser-wide: other open tabs reload, and stale-tab saves are rejected before any backend write.

The entrance does not grant new roles. It reads `PEOPLE`, `APP_USER_ROLES`, `APP_ROLES` and existing permissions. Only the Phase 1 `demo:d1:<person_id>` local identities appear. Request source remains a separate business field: selecting another source never changes who created or owns a request.

## Configuration already applied locally

The following line was added to both files:

- `C:\Users\smaikoti\Desktop\ai-pod-staffing\.env.local`
- `C:\Users\smaikoti\Desktop\ai-pod-staffing\backend\python\.env`

```dotenv
STAFFING_DEMO_PERSONAS_ENABLED=true
```

Keep the existing local configuration:

| Next.js `.env.local` | Python `backend/python/.env` |
| --- | --- |
| `STAFFING_BACKEND_AUTH_MODE=local` | `BACKEND_AUTH_MODE=local` |
| Both agentic flags remain `true` | `BACKEND_ENV=local` |
| `STAFFING_BACKEND_URL=http://127.0.0.1:8015` | `STAFFING_POLICY_VERSION=staffing-demo-v2` |
| `STAFFING_BACKEND_LOCAL_TOKEN` stays unchanged | `BACKEND_LOCAL_TOKEN` must match that token |

No new secret, API key, organization login, SQL migration or data import is required. Leave the working Oracle wallet and OCI configuration unchanged. `BACKEND_LOCAL_SUBJECT` is ignored while profile entry is enabled; the selected person supplies the identity, so you no longer edit it to switch employees.

This entrance is for the local prototype: Next.js must run in development and both servers must bind to `127.0.0.1`. It is not an organization sign-in mechanism and must not be exposed on a shared production host. With the flag off, the existing authentication modes are unchanged. No flag named `NEXT_PUBLIC_STAFFING_DEMO_PERSONAS_ENABLED` is needed.

## Start locally

Stop any old Next.js, Python API and worker terminals with **Ctrl+C** first. Do not start a second copy on the same port. Open three PowerShell terminals:

**1. Python API**

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing\backend\python
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8015 --env-file .env
```

**2. Next.js application**

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing
npm run dev -- --hostname 127.0.0.1
```

**3. Agent worker — when ready to process requests**

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing\backend\python
.\.venv\Scripts\python.exe -m app.worker --env-file .env
```

Open [http://127.0.0.1:3001](http://127.0.0.1:3001). Use that address consistently. Profile entry and existing project viewing need only the first two processes; new agent executions also need the worker.

The worker still needs `STAFFING_WORKER_ENABLED=true`, the approved v2 policy, and the database agent switch enabled. You already enabled the database switch after Phase 2. Starting the worker can process queued or previously opted-in requests, call OCI, and save proposals. Proposals do not reserve capacity. Captain approval is final and saves the assignment; rejection requires a reason. There is no Lead/Member acceptance step. Notifications remain off.

## Short demonstration

1. Enter as **POD Captain → Indranie Balkaran**. Check the sidebar name and open **New request**.
2. Use a complete request schedule inside the populated capacity window (7 September–8 November 2026) and not before today's date. For the current test date, 14–18 September with 24 person-hours and 1 Lead + 2 contributors is a useful example. See the [Phase 2 rules and test case](demo-agent-phase2.md); recommendations are calculated, not hard-coded names.
3. Save the request. With the worker running, follow **Agent Execution**, then **AI Fitment** when the proposal is ready. Review evidence, planned hours and projected allocation before approving or rejecting.
4. Use **Change profile** and enter as the recommended Lead or Member. After approval, the project appears under that person's Requests view. Their skills and availability remain tied to their own person record.
5. Enter as **Administrator**. Open **Team & Skills → Add person** to demonstrate the existing people creation form. Saving creates an actual Oracle person; merely opening the form changes nothing. A new person's role mapping must exist before they can appear in this entrance.

Do not rerun Phase 1 data imports or `setup.sql` to test profile switching.

## Implementation and verification

- Entrance: `components/entry/PersonaEntry.tsx` and scoped `styles/persona-entry.css`, reusing the existing name combobox.
- Next.js session endpoints: `app/api/personas/`, with server-only management credentials and HttpOnly, same-origin session cookies.
- Python directory/session endpoints: `backend/python/app/personas.py`. Eight-hour signed local sessions are checked against fresh database roles on every request. Sessions are not stored in business tables.
- Existing screen data and mutation endpoints use the selected person and selected role. There is no fallback to the fixed Captain after a session expires.
- Imported deliverable experience is now readable without extra display/audit fields; names come from the catalogue, and saves preserve untouched evidence. Technical import-source labels are no longer shown on the skills cards; provenance stays in the database.
- `npm run test:personas` covers mode checks, fresh role mapping, cookie handling, origin validation, stale-tab protection and role-specific landing.
- Browser verification uses existing data and opens forms without saving business changes. No worker, model execution or email is needed for those checks.
- Verification: 114 Node tests passed and TypeScript typechecking passed. Python ran 292 tests: 291 passed; the existing JWT key-generation test is blocked by this machine's OpenSSL entropy error. All 22 new Python persona tests passed. Read-only Oracle checks accepted all 17 active profiles and 49 saved deliverable-experience entries.

If the directory is empty, check the active and effective employee role mappings; do not add unrelated roles merely to fill the list. If a session expires or a role is withdrawn, choose a current profile again. If the entrance cannot load, verify the API is running and the flag is enabled in both files, then restart both processes.
