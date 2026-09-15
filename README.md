# AI Pod Staffing

AI Pod Staffing is a Next.js and Oracle application that creates staffing requests, uses two OCI Generative AI agents to prepare a POD recommendation, and keeps the final decision with the POD Captain.

The application includes four profiles:

- **POD Captain** — creates requests, reviews recommendations, and approves or rejects a POD.
- **POD Lead** — manages assigned projects, sees active POD members, and closes completed work.
- **POD Member** — views assigned projects and manages only their own skills, interests, deliverable experience, and availability.
- **Administrator** — manages people, access, catalogue information, and the maximum-utilization setting.

## Agent workflow

```text
Captain saves request
        ↓
Execution is queued in Oracle
        ↓
Analyst Agent reads the request and evidence
        ↓
Deterministic rules engine builds and validates feasible POD options
        ↓
Planner Agent selects and explains one validated option
        ↓
Proposal waits for Captain review
        ↓
Captain approves → final assignments
Captain rejects → reason saved and supplied to the next run
```

There are **two agents**, not an unrestricted autonomous system:

1. **Request and Evidence Analyst**
   - Reads the request, catalogue, candidate skill/deliverable evidence, capacity status, and previous rejection feedback.
   - Summarizes the business need.
   - Requests clarification only when objectives, outcomes, or project description are actually missing.
   - Does not choose people or calculate hours.

2. **POD Planner**
   - Reads server-generated, validated POD options.
   - May inspect a selected person's evidence and capacity.
   - Selects an existing plan ID and explains the exact hours, evidence, and projected allocation.
   - Cannot invent a person, change a score, approve a proposal, create an assignment, execute SQL, or send email.

LangGraph coordinates `collect → analyse → deterministic plan → publish`. Oracle stores executions, evidence snapshots, checkpoints, events, proposals, and worker leases so recovery does not depend on in-memory state.

## Staffing rules

Eligibility is a mandatory gate. A high score cannot override a failed rule.

- A request needs valid dates, positive total person-hours, lead/member counts, deliverables, required capabilities, a revision, and a responsible Captain.
- Candidates must be active and have an effective staffing role for the complete request period.
- A Lead slot requires `POD_LEAD`; a Member slot accepts `POD_MEMBER` or `POD_LEAD`.
- The POD must have the requested Lead/Member counts, and one person cannot occupy two slots.
- Assigned hours must equal the request's total effort exactly.
- Each person receives at least the greater of **1 hour** or **50% of an equal team share**.
- Every mandatory capability must be covered. The normal minimum self-rating is **3/5**, and self-rated skills require evidence.
- Project Manager is role-derived; it cannot be added or rated as an ordinary skill.
- Interest improves preference only. It is not proof of proficiency.
- Each person needs relevant capability or deliverable evidence; free capacity alone is insufficient.
- A deliverable needs an evidenced end-to-end `INDEPENDENT`/`MENTOR` owner or coverage of its mapped required capabilities.
- `LEARNING` and `SUPPORTED` contributors require an experienced teammate on the same deliverable.
- Unknown or stale capacity is never treated as free capacity.
- Work is placed only on available weekdays inside the request dates. Leave reduces available hours, while confirmed projects and external commitments consume capacity.
- Allocation is calculated as:

  ```text
  (confirmed project hours + external commitments + proposed hours)
  ÷ working capacity after leave × 100
  ```

- The active maximum allocation is currently **85%** and is editable by an Administrator. It is checked per day, across the request period, and across complete weeks.
- Pending proposals reserve no capacity; approved assignments do.
- Scores are calculated by server code: **skill 50%, deliverable experience 30%, remaining capacity 15%, interest 5%**.
- Search is bounded—normally 2,000 combinations—and is not described as globally optimal.
- Request, policy, roles, skills, availability, capacity, and assignments are rechecked before approval. Stale evidence requires a new run.

Captain approval is final; there is no Lead/Member acceptance step. Rejection requires a reason. The assigned Lead can close the project: historical work is retained and only future scheduled capacity is released.

## Agent safety boundaries

- Request text, experience notes, and rejection reasons are untrusted data, never instructions.
- Agents receive allowlisted read/calculation tools and typed completion tools only.
- Names, location, and protected/personal traits are not selection criteria.
- Scores, schedules, hours, percentages, and eligibility come from deterministic server calculations.
- Model/tool calls have persisted limits, and outputs must cite the request, policy, people, and capacity evidence used.
- The model cannot approve, reject, close projects, write assignments, run arbitrary SQL, or send notifications.
- LangSmith tracing is disabled so staffing evidence is not exported through ambient tracing.

## Approval, allocation, and notifications

- Saving an eligible request automatically creates a queued agent execution.
- The worker publishes a `READY_FOR_REVIEW` proposal; it remains advisory until Captain approval.
- Approval writes the final assignments and dated hours in one guarded transaction.
- Rejection creates no assignment and saves the required reason for the next run.
- Current allocation is recalculated from dated confirmed work, external commitments, leave, and working capacity. It is not a permanently stored percentage.
- Project closure preserves work through the closure date and releases only future hours.
- Approval prepares disabled notification-outbox records for future email integration. **No email sender is enabled or implemented.**

## Local prerequisites

- Node.js and npm
- Python 3.12 and [`uv`](https://docs.astral.sh/uv/)
- An Oracle wallet and `AI_POD_STAFFING` schema with the project migrations already applied
- OCI SDK configuration with a valid signing key and Generative AI permission
- An OCI chat model/provider combination that supports tool calling

For the existing demo database, do **not** rerun `setup.sql`, `phase2.sql`, or the demo-data import. They are already installed. Keep the `AIPS_*_BK*` backup tables during the recovery window.

Install dependencies:

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing
npm install

cd backend\python
uv sync --python 3.12
```

## Local environment files

Passwords, tokens, wallets, and OCI private keys must stay local. These files are ignored by Git:

- `C:\Users\smaikoti\Desktop\ai-pod-staffing\.env.local`
- `C:\Users\smaikoti\Desktop\ai-pod-staffing\backend\python\.env`
- `Wallet_*`
- `.oci` private keys

Generate one local control token and place the **same value** in both environment files:

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing\backend\python
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Root `.env.local`

```ini
STAFFING_DATA_SOURCE=oracle
STAFFING_AUTH_MODE=preview

DB_USER=AI_POD_STAFFING
DB_PASSWORD=<DATABASE_PASSWORD>
DB_TNS_ALIAS=<TNS_ALIAS>
DB_WALLET_LOCATION=C:/absolute/path/to/Wallet_AIMLCOESANDBOX
DB_WALLET_PASSWORD=<WALLET_PASSWORD>
DB_POOL_MIN=0
DB_POOL_MAX=2
DB_POOL_INCREMENT=1

# Optional AI rephrasing in request and experience fields.
AI_REPHRASE_ENABLED=true
OCI_CONFIG_FILE=C:/Users/<YOUR_USER>/.oci/config
OCI_CONFIG_PROFILE=DEFAULT
OCI_GENAI_ENDPOINT=https://inference.generativeai.<REGION>.oci.oraclecloud.com
OCI_GENAI_COMPARTMENT_ID=<COMPARTMENT_OCID>
OCI_GENAI_MODEL_ID=<MODEL_OCID>
AI_REPHRASE_TIMEOUT_MS=15000

# Live backend and local four-profile entrance.
STAFFING_AGENTIC_ENABLED=true
NEXT_PUBLIC_STAFFING_AGENTIC_ENABLED=true
STAFFING_BACKEND_URL=http://127.0.0.1:8015
STAFFING_BACKEND_AUTH_MODE=local
STAFFING_BACKEND_LOCAL_TOKEN=<SAME_RANDOM_TOKEN>
STAFFING_DEMO_PERSONAS_ENABLED=true
STAFFING_APP_ORIGIN=http://127.0.0.1:3001
```

### `backend/python/.env`

```ini
BACKEND_ENV=local
BACKEND_AUTH_MODE=local
BACKEND_LOCAL_TOKEN=<SAME_RANDOM_TOKEN>
STAFFING_DEMO_PERSONAS_ENABLED=true

DB_USER=AI_POD_STAFFING
DB_PASSWORD=<DATABASE_PASSWORD>
DB_TNS_ALIAS=<TNS_ALIAS>
DB_WALLET_LOCATION=C:/absolute/path/to/Wallet_AIMLCOESANDBOX
DB_WALLET_PASSWORD=<WALLET_PASSWORD>
DB_POOL_MIN=0
DB_POOL_MAX=2
DB_POOL_INCREMENT=1

OCI_CONFIG_FILE=C:/Users/<YOUR_USER>/.oci/config
OCI_CONFIG_PROFILE=DEFAULT
OCI_GENAI_ENDPOINT=https://inference.generativeai.<REGION>.oci.oraclecloud.com
OCI_GENAI_COMPARTMENT_ID=<COMPARTMENT_OCID>
OCI_GENAI_MODEL_ID=<TOOL_CAPABLE_MODEL_OCID>
OCI_GENAI_PROVIDER=generic
OCI_TIMEOUT_SECONDS=30
OCI_MAX_OUTPUT_TOKENS=2048

STAFFING_WORKER_ENABLED=true
STAFFING_DECISIONS_ENABLED=true
STAFFING_POLICY_VERSION=staffing-demo-v2
STAFFING_POLL_SECONDS=5
STAFFING_LEASE_SECONDS=180
STAFFING_MAX_CANDIDATES=60
STAFFING_SEARCH_LIMIT=2000

LANGSMITH_TRACING=false
LANGCHAIN_TRACING_V2=false
```

`OCI_GENAI_PROVIDER` must match the model (`generic`, `meta`, or `cohere`). Do not guess it from the OCID. In persona mode, `BACKEND_LOCAL_SUBJECT` is not required because the entrance creates a signed session for the selected database identity.

## Enable agent execution in Oracle

The Python flag and database runtime flag must both be enabled. Keep notifications off:

```sql
UPDATE staffing_runtime
   SET agents_enabled = 'Y',
       notifications_enabled = 'N',
       updated_by = USER,
       updated_at = SYSTIMESTAMP
 WHERE runtime_id = 1;

COMMIT;

SELECT agents_enabled, notifications_enabled
  FROM staffing_runtime
 WHERE runtime_id = 1;
```

Expected result: `Y / N`.

## Run locally in three terminals

Use `127.0.0.1` consistently. Do not start duplicate processes on ports 3001 or 8015.

### Terminal 1 — Python API

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing\backend\python
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8015 --env-file .env
```

### Terminal 2 — Next.js application

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing
npm run dev -- --hostname 127.0.0.1
```

### Terminal 3 — agent worker

```powershell
cd C:\Users\smaikoti\Desktop\ai-pod-staffing\backend\python
.\.venv\Scripts\python.exe -m app.worker --env-file .env
```

Open [http://127.0.0.1:3001](http://127.0.0.1:3001), choose **POD Captain**, select a Captain, and create a request. The API and frontend are enough for browsing; the worker is required to process queued executions and call OCI.

## Quick checks

From `backend/python`:

```powershell
.\.venv\Scripts\python.exe -m app.cli database --env-file .env
.\.venv\Scripts\python.exe -m app.cli oci --env-file .env --live
```

The OCI check may incur model usage. It uses fixed arithmetic data and performs no database writes.

From the project root:

```powershell
npx tsc --noEmit
npm run test:application
npm run test:skills
npm run test:personas
npm run test:agentic
```

From `backend/python`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Demo journey

1. Enter as a POD Captain and create a complete request with dates, effort, POD size, deliverables, capabilities, objectives, and outcomes.
2. Open **Agent Execution** and watch it move through evidence, analysis, rules, planning, and publication.
3. Open **AI Fitment** and review the Lead/Members, evidence, hours, request-period allocation, and peak weekly allocation.
4. Reject once with a reason to demonstrate feedback-aware reruns, or approve to create the final POD.
5. Change profile to the assigned Lead or Member and show their role-scoped project view.
6. The Lead closes completed work with a reason. Reports retain historical work and release future capacity.
7. Use **Reports → Excel export** as a Captain or Administrator to download scoped KPI, capacity, request, or assignment reports.

## Important folders

| Path | Purpose |
| --- | --- |
| `backend/python/app/agents/staffing.py` | Analyst/Planner prompts, tools, and output validation |
| `backend/python/app/workflow.py` | LangGraph workflow |
| `backend/python/app/rules.py` | Eligibility, validation, and scoring rules |
| `backend/python/app/planning.py` | Bounded team search and daily scheduling |
| `backend/python/app/capacity.py` | Allocation and availability calculations |
| `backend/python/app/execution_store.py` | Oracle queue, checkpoints, leases, events, and proposal publication |
| `backend/python/app/decisions.py` | Captain approval/rejection and final assignment transaction |
| `backend/python/app/assignments.py` | POD views, reports, current allocation, and project closure |
| `components/screens/fitment/` | Agent execution and recommendation UI |
| `sql/oracle/` | Additive migrations, verification, and recovery scripts |
| `docs/` | Detailed implementation and operating notes |

## Troubleshooting

- `WinError 10048`: an old process uses port 3001 or 8015. Stop its project terminal with `Ctrl+C`.
- `AGENTS_DISABLED`: set `STAFFING_WORKER_ENABLED=true` and Oracle `STAFFING_RUNTIME.agents_enabled='Y'`.
- `DATABASE_NOT_CONFIGURED`: fill every backend Oracle setting and use an absolute wallet path.
- `ORIGIN_REJECTED`: use `http://127.0.0.1:3001`, set `STAFFING_APP_ORIGIN` to that exact origin, and restart Next.js.
- `INVALID_AGENT_OUTPUT`: verify native tool-call support and the correct `OCI_GENAI_PROVIDER`.
- `NEEDS_INFORMATION`: review missing business inputs, role/capability mapping, or stale/unknown capacity.
- Environment changes require restarting the affected API, worker, or Next.js process. `NEXT_PUBLIC_*` changes always require a Next.js restart/rebuild.

Detailed notes: [backend Phase 3](docs/backend-phase3.md), [backend Phase 4](docs/backend-phase4.md), [backend Phase 5](docs/backend-phase5.md), [persona setup](docs/demo-personas-phase3.md), [agent rules](docs/demo-agent-phase2.md), [privacy](docs/team-privacy-phase3.md), [closure/allocation](docs/closure-allocation-phase2.md), and [reports](docs/reports.md).
