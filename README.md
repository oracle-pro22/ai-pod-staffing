# AI POD Staffing

An internal Oracle Customer Success Services application for creating staffing requests and assembling project teams (PODs). It matches employee skills, experience and available capacity with project needs, with AI-assisted recommendations reviewed and approved by a POD Captain.

A POD is a time-bound team formed to deliver a specific project or business outcome. Employees maintain their skills, experience, current commitments and planned leave, while Captains capture project deliverables, required capabilities, dates and effort. The application uses these inputs to propose suitable teams, explain the matches and highlight capacity constraints. Captains can review and adjust a proposed team before approval; assigned Leads and Members then see their projects through role-based views, and Leads can close completed work to release future capacity.

Features include employee profiles, current work and leave, role-based access, staffing approvals, allocation calendars, reports and audit history. The four roles are **POD Captain, POD Lead, POD Member and Administrator**. Email delivery is not implemented; notification-outbox records remain disabled.

**Stack:** Next.js, React and TypeScript; Python 3.12 and FastAPI; LangGraph/LangChain OCI; Oracle Database and OCI Generative AI. The web application, API and background worker run separately.

## Prerequisites

- Git, Node.js/npm compatible with the locked Next.js version, Python **3.12** and `uv`.
- Repository access and an approved development database with the `AI_POD_STAFFING` schema, required migrations, catalogue/policy data and a provisioned application account.
- Database credentials, Oracle wallet and network/VPN access where required.
- OCI configuration/signing key, compartment, inference endpoint and a tool-capable model/provider for recommendations.

A clone does **not** create the database or accounts. Ask the maintainer for access and the current migration order. Do not run all SQL files, reset scripts or demo imports against an existing database. Coordinate before using shared data: local actions affect that database, and a worker can process its queued requests.

## 1. Clone and install

The commands below use **PowerShell**.

```powershell
git clone https://github.com/oracle-pro22/ai-pod-staffing.git
cd ai-pod-staffing
npm ci

cd backend/python
uv sync --locked --python 3.12
cd ../..
```

## 2. Configure

From the repository root, copy the examples without overwriting existing files:

```powershell
if (-not (Test-Path .env.local)) { Copy-Item .env.example .env.local }
if (-not (Test-Path backend/python/.env)) { Copy-Item backend/python/.env.example backend/python/.env }
```

Edit both files locally:

| Configuration | What to set |
| --- | --- |
| Oracle Database — both files | `DB_USER=AI_POD_STAFFING`, password, TNS alias, absolute wallet directory and wallet password. |
| OCI — backend file | Config file/profile, GenAI endpoint, compartment, model ID and matching `OCI_GENAI_PROVIDER`. Obtain approved values from the maintainer. |
| Optional AI rephrasing — root file | Configure its OCI values and enable `AI_REPHRASE_ENABLED` only if required. Replace the example endpoint/model values before enabling it. |

Keep these settings in the root `.env.local`:

```dotenv
STAFFING_DATA_SOURCE=oracle
STAFFING_AGENTIC_ENABLED=true
NEXT_PUBLIC_STAFFING_AGENTIC_ENABLED=true
STAFFING_BACKEND_AUTH_MODE=password
STAFFING_DEMO_PERSONAS_ENABLED=false
STAFFING_BACKEND_URL=http://127.0.0.1:8015
STAFFING_APP_ORIGIN=http://127.0.0.1:3001
```

For the full workflow, set these in `backend/python/.env` after confirming the development database is ready:

```dotenv
BACKEND_ENV=local
BACKEND_AUTH_MODE=password
STAFFING_DEMO_PERSONAS_ENABLED=false
STAFFING_WORKER_ENABLED=true
STAFFING_DECISIONS_ENABLED=true
LANGSMITH_TRACING=false
LANGCHAIN_TRACING_V2=false
```

The database owner must also enable `STAFFING_RUNTIME.agents_enabled` for agent execution. Keep notifications disabled. Password mode does not require OIDC or the legacy local-control token. `STAFFING_MVP_DEFAULT_PASSWORD` is for explicit account provisioning, not ordinary sign-in.

Never commit real environment files, passwords, wallets or private keys. Use loopback HTTP only for local development; deployment requires approved HTTPS configuration.

## 3. Start locally

Open **three terminals at the repository root**.

**Terminal 1 — API**

```powershell
cd backend/python
uv run --locked --no-sync uvicorn app.main:app --host 127.0.0.1 --port 8015 --env-file .env
```

**Terminal 2 — Web application**

```powershell
npm run dev -- --hostname 127.0.0.1
```

**Terminal 3 — Background worker**

```powershell
cd backend/python
uv run --locked --no-sync python -m app.worker --env-file .env
```

Open [http://127.0.0.1:3001](http://127.0.0.1:3001). Use your provisioned application email/password, **not your Oracle SSO password**. First-time users complete profile setup; screens depend on assigned roles.

The worker processes queued recommendations and may incur OCI usage. For UI/API inspection only, omit Terminal 3 and leave worker/decision flags disabled. This is not a read-only guarantee: coordinate access to shared data. Stop each process with **Ctrl+C**.

## 4. Verify

From the repository root:

```powershell
curl.exe --max-time 5 http://127.0.0.1:8015/health/live
curl.exe --max-time 30 http://127.0.0.1:8015/health/ready
npm run test:login
npm run test:selections
```

`health/live` checks the API process. `health/ready` checks database connectivity/schema identity, not all migrations or OCI readiness. Local API documentation: [http://127.0.0.1:8015/docs](http://127.0.0.1:8015/docs).

Backend tests, from `backend/python`:

```powershell
uv run --locked --no-sync python -m pytest -p no:cacheprovider
```

## Code and documentation

| Folder | What it contains |
| --- | --- |
| `app/` | Next.js pages, layouts and browser-facing API routes. `app/api/` handles web requests and forwards supported operations to the Python API. |
| `components/` | Role-based screens, forms, dialogs and shared UI. Start with `screens/`, `overlays/` and `shell/`. |
| `context/` | Shared client-side workspace state and UI actions. |
| `styles/` | Application and feature-specific CSS; base styles also live in `app/`. |
| `lib/` | Shared helpers, validation, permissions, Oracle repositories and report/export utilities. |
| `backend/staffing/`, `backend/skills/` | Web-side authentication/session handling, Python API bridge and skill-management services. |
| `backend/ai/`, `backend/oci/` | Optional AI text rephrasing and OCI request-signing helpers used by the web server. |
| `backend/python/app/` | FastAPI endpoints, account access, staffing rules, capacity calculations, approvals, Oracle persistence and background processing. |
| `backend/python/app/agents/` | Supervisor, Analyst and Planner prompts, allowed tools and OCI model integration. |
| `types/` | Shared TypeScript data contracts for requests, people, roles and UI state. |
| `data/` | Workbook used by the optional legacy Excel data source; the main setup uses Oracle. |
| `backend/python/tests/`, `scripts/` | Backend tests, web regression tests and supporting database/development utilities. Review operational scripts before running them. |
| `sql/oracle/`, `deploy/`, `docs/` | Database migrations and recovery scripts, host-specific deployment examples, and detailed implementation/operating notes. |

For backend code orientation:

- **API and jobs:** `main.py` defines API endpoints; `worker.py` processes Oracle-backed jobs; `execution_store.py` manages the queue, leases and checkpoints.
- **AI orchestration:** `workflow.py` coordinates the agents in `agents/`; model outputs do not directly approve staffing.
- **Staffing calculations:** `rules.py`, `planning.py` and `capacity.py` handle eligibility, team options, scheduling and workload calculations.
- **Decisions and delivery:** `decisions.py` handles normal approvals/rejections, `manual_store.py` handles manual overrides, and `assignments.py` supports assigned-project views, reports and closure.

The main request flow is: browser UI → Next.js API route → Python API → Oracle. The separate worker reads queued requests, runs the staffing workflow and saves proposals for Captain review.

See [password login](docs/mvp-phase1.md), [recommendations](docs/mvp-phase2.md), [manual override](docs/mvp-phase3.md) and [reports](docs/reports.md). Older phase documents describe historical stages; confirm migration instructions before applying them.
