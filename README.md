# AI Pod Staffing prototype

The original Redwood HTML interface runs inside Next.js. All backend APIs, agent workers, scoring, OCI inference, workbook persistence and human approvals are implemented in Python. AI Fitment, request submission, workflow history, decisions, notifications and the assignment calendar read persisted Excel data. Save Request automatically queues a workflow. No assignment is created until a reviewer approves the pod.

## Run locally

Use Python 3.11+ (tested with 3.12) and Node.js 20.19+ or 22+. Dependencies are isolated in this app's `.venv` and `node_modules`; no shared environment or separately launched worker is required.

```bash
cd /Users/pbaksi/Documents/code/ai-pod-staffing
# On a new checkout: copy .env.example to .env.local and set your values.
./start.sh
```

Open http://localhost:3001. `start.sh` installs missing dependencies on the first run (internet required on a new machine), starts the Python API on `127.0.0.1:8001`, waits for readiness, then starts Next.js on `127.0.0.1:3001`. The supervisor runs inside the Python service. Press **Ctrl+C once** to stop both services, including child processes. An occupied port produces an error without killing any existing process. If either service fails, the launcher stops the other.

For a production build and launch, use `./start.sh --prod`. This rebuilds Next.js before launching both services. `npm run dev` and `npm start` are aliases for these commands. Development uses `.next-dev`; production builds use `.next`, preventing dev/build cache collisions. `npm run build` only builds the frontend. Python source changes require restarting `start.sh`; frontend development retains Next.js hot reload.

Override ports if needed: `FRONTEND_PORT=3011 BACKEND_PORT=8011 ./start.sh`. These can also be set in `.env.local`. The launcher configures the Next.js proxy automatically. `PYTHON_BIN=python3.12 ./start.sh` chooses the interpreter when first creating `.venv`. Do not edit a virtual environment to switch Python versions; recreate it using your selected interpreter.

API documentation: http://127.0.0.1:8001/docs. Health: http://localhost:3001/api/health. Tests: `npm test` (Python regression tests on disposable workbook copies), then `npm run typecheck`. Tests never call OCI or change the runtime workbook. Direct API launch for development, if needed: `.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001 --workers 1`. Normal use needs only `start.sh`.

### Console logging

`./start.sh` streams both services directly to the same terminal, with unbuffered Python output. Timestamped backend logs show startup/readiness, Save Request, each worker/tool stage, candidate/eligible/proposed counts, OCI call start/completion/duration, the human-review pause, decisions, errors and shutdown. Logs include the workflow run ID for correlation. No extra command or log-file viewer is needed.

Default `APP_LOG_LEVEL=INFO` keeps successful health/staffing polling quiet. For all API requests, scoring weights and failure code locations, run `APP_LOG_LEVEL=DEBUG ./start.sh` (also works with `--prod`), or set `APP_LOG_LEVEL=DEBUG` in `.env.local` and restart. `WARNING`, `ERROR` and `CRITICAL` reduce Python application output; Next.js and Uvicorn retain their own console output. API logs show method, route template, status and elapsed time, not query strings or request bodies. Our diagnostics omit personnel details, model prompts/responses, signed headers, credentials and exception payloads, including in debug mode. Detailed workflow evidence remains in AI Fitment and the workbook audit tables. Browser-only JavaScript messages remain in browser developer tools.

## Code structure

```text
start.sh                        Single startup command and dependency checks
app/                            Next.js frontend shell and styling
public/prototype.html           Preserved Redwood UI
public/agentic.js               Browser-side API integration only
next.config.ts                  Routes /api/* to Python; no backend business logic
backend/
  main.py                       FastAPI endpoints and worker lifecycle
  launcher.py                   Starts/stops both services together
  console.py                    Safe console logging and workflow correlation
  config.py, models.py           Server config and typed API input contracts
  repository.py, excel_file.py   Excel database adapter; future 26ai boundary
  service.py                    Request commands and human approval coordinator
  agents/supervisor.py           Durable orchestration and human-review pause
  agents/workers.py              Specialized request/fitment/explanation workers
  tools/scoring.py               Eligibility and four-factor recommendation tools
  tools/model.py                 OCI Python SDK signing and inference adapter
  tests/                        Workflow, API and compatibility regression tests
  requirements.txt              Pinned Python dependencies
```

The old TypeScript API handlers, backend libraries and standalone Node worker have been replaced, not left as a second backend. The offline `scripts/build-prototype-workbook.mjs` is a historical workbook authoring utility, not an application backend or startup dependency. UI wording, dropdown options and layouts have not been changed by the Python migration.

The backend uses [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/) to manage its worker. Next.js [external rewrites](https://nextjs.org/docs/app/api-reference/config/next-config-js/rewrites) preserve the browser's existing `/api/*` URLs. The UI never receives an OCI signing key.

## OCI configuration

`.env.local` is ignored by Git. Python reads it using `python-dotenv`; shell environment variables take precedence. This machine retains the supplied compartment, Chicago inference endpoint, model `openai.gpt-5.5`, and API-signing profile `DEFAULT` in `~/.oci/config`. The OCI Python SDK reads that profile and its existing private key; neither is copied into the application. Keep the local config readable only by your user. Never prefix a secret with `NEXT_PUBLIC_` or expose it through Next.js `env` configuration.

`OCI_GENAI_API_FORMAT=native` uses the signed `/20231130/actions/chat` endpoint. For OpenAI models the adapter supplies `maxCompletionTokens`, as required by GPT-5.5. Other generic chat models use `maxTokens`. `OCI_GENAI_API_FORMAT=responses` is an alternative signed `/openai/v1/responses` adapter and additionally requires `OCI_GENAI_PROJECT_OCID`. Native inference is the verified default; the Responses alternative needs verification in your project.

`AI_PROVIDER=oci` calls the configured model. A model/network/authentication error marks the workflow Failed, shows an actionable error, and makes no assignments. There is no silent fallback. Set `AI_PROVIDER=demo` explicitly for offline demonstrations; the UI labels this mode and does not call a model. Restart the app and worker after changing environment variables.

The old SerpAPI credential and hosted-application bearer-token setting are not needed by this flow. No credentials are sent to the browser. Check connectivity with `.venv/bin/python -m backend.verify_oci`. `.venv/bin/python -m backend.verify_live_workflow` checks the two model workers using newly invented QA profiles and an isolated temporary workbook, stopping before approval. Both commands explicitly call the configured OCI service; they are not part of ordinary offline regression tests.

OCI API references: [Python SDK signed requests](https://docs.oracle.com/en-us/iaas/tools/python/latest/raw-requests.html), [OCI Responses API](https://docs.oracle.com/en-us/iaas/Content/generative-ai/responses-api.htm).

## Agents, tools and approval

| Component | Implementation | Responsibility |
| --- | --- | --- |
| Staffing supervisor | `backend/agents/supervisor.py` | Durable orchestration, delegation, run lease, failure handling and suspension at human review |
| Request analyst worker | `backend/agents/workers.py` | OCI model interprets the request against the explicitly selected skill requirements |
| Fitment analyst worker | `backend/agents/workers.py` | Calls deterministic eligibility, scoring and pod-selection tools |
| Recommendation writer worker | `backend/agents/workers.py` | OCI model explains candidate evidence, policy guidance and alternates |
| Approval coordinator worker | `backend/service.py` (`decide`) | Resumes on a human decision, revalidates, saves the decision and approved assignments atomically |
| Scoring and eligibility tools | `backend/tools/scoring.py` | Capacity by day, conflicts, proficiency coverage, four-factor scores and best feasible pod |
| Model tool | `backend/tools/model.py` | Signed OCI inference with bounded output and validated structured responses |
| Data and notification tools | `backend/repository.py`, `backend/service.py` | Read/write workbook tables, save audit events and in-app notifications |

The supervisor is a constrained workflow orchestrator. Interpretation and explanation workers use GenAI; numerical ranking and assignment permissions are implemented in Python. This runs in the Python application process, not in a separately deployed OCI managed Agents resource. The module boundaries support moving workers/tools to OCI services later. Use one Uvicorn worker for this local workbook prototype. Persisted run leases recover interrupted work after up to five minutes; Pending Approval runs remain paused after a restart.

Save Request persists the request and Queued run. The worker claims it, validates/interprets requirements, retrieves the current master data, excludes ineligible candidates, scores candidates, selects a feasible pod, retrieves policy guidance, generates rationale, and saves Pending Approval with an in-app notification for the Request Lead. The worker then stops processing that run until a decision arrives. It does not hold a request or model connection open while waiting.

Approval writes the decision, assignments and local notifications in one locked workbook transaction. A repeated decision key cannot duplicate assignments. A revision protects against stale browser decisions. The approval transaction reads current data again; changed master data or assignments require a fresh fitment run. Save adjustment retains a revised selection and reason while remaining Pending Approval. Decline records a reason and creates no assignments. An unfillable request becomes Needs Adjustment. Edit and save it, or update the master data and re-run. Approved requests cannot be edited in this prototype.

## Recommendation calculations

Weights in Agent Settings default to Skills **50%**, Allocation **25%**, Future availability **15%**, Interests **10%**. Administration saves these to Excel. The total must be 100%, and the strict ordering Skills > Allocation > Future availability > Interests is enforced on the server.

Each factor is 0–100. Skill score is mean recorded proficiency across requested skills, divided by 5. Missing proficiency contributes zero. Allocation score is remaining current daily capacity, after baseline allocation, existing assignments and explicit commitments. Future availability score is remaining capacity averaged over the request's business days. Interests score is mean expressed interest for those capabilities, divided by 5; missing preferences contribute zero. The total is the sum of the four factor scores multiplied by their percentage weights. Stored scores and explanations remain tied to their run.

Eligibility is checked before selecting a pod: leave, travel, OOO or explicit conflicts exclude a person on overlapping business days. Proposed allocation must not exceed the configured limit (85% by default) on any day. Each person must meet at least one required skill threshold. The application then forms two role-specific recommendation pools: the top 3 eligible lead-capable people by weighted score and the top 5 eligible people by weighted score for contributor positions. It selects the highest-scoring combination inside those pools that collectively covers every mandatory skill. If those shortlists cannot form a complete pod, the request becomes Needs Adjustment even when a lower-ranked person outside the requested limits could supply the missing skill.

Every candidate is scored and retains factor-level tool evidence. OCI explains the union of the top 3 lead and top 5 contributor recommendation pools, with duplicates removed and every proposed member included. Other rationales are explicitly labelled `Scoring-tool evidence`, not claimed as GenAI output. If no pod is feasible within the role-specific limits, the saved summary distinguishes missing shortlisted coverage from the wider scored pool.

Scheduling assumptions: Monday–Friday, 8 hours/day by default per person, no public-holiday calendar, equal division of total request effort among pod members and then business days. Baseline allocation is a standing percentage; explicit commitments and new assignments are additional, so avoid counting the same work in both. Future availability differs from current allocation when dated commitments/assignments change in the requested window. A high skill weight does not mean skills override hard capacity or conflict exclusions.

## Workbook and migration

`data/agentic-staffing.xlsx` is the versioned seed. On first startup it is copied to **`data/runtime/staffing.xlsx`**, the actual writable database. Override with `STAFFING_WORKBOOK_PATH`. Runtime files and backups are ignored by Git. Later seed edits do not overwrite an existing runtime database.

The seed preserves the supplied `ai-pod-staffing-prototype (1).xlsx` source sheets and customer mapping labels. `People` gains `can_lead` and `daily_hours`. Operational tables are separate: Skills, Person Skills, Preferences, Availability Events, Staffing Requests, Request Skills, Workflow Runs, Fitment Candidates, Workflow Events, Approval Decisions, Assignments, Notifications, Staffing Policies and Agent Settings. IDs provide joins. Candidate evidence JSON is an audit snapshot, while current proficiency and preferences remain separate keyed tables.

The source strengths were migrated to demo skill proficiency. Expressed preferences were synthesized independently and are labelled accordingly. Original-prototype skill labels are also available as `MOCK-*` catalog entries. Imported requests retain historical deadlines; the July 27 start dates, three-person pod sizes and 3/5 skill thresholds are prototype assumptions. Legacy request/recommendation records remain in their original source sheets and are not treated as approved assignments. Review dates and requirements before re-running an imported request. The supplied eight original people remain unchanged; the sample expansion adds 64 clearly labelled fictional people to the same operational tables. The browser reads all 72 people from Excel.

## Expanded synthetic sample

The initial eight-person pool had only 1–5 qualified people per skill and baseline allocations of 39–84%. With the 85% guardrail, a 72-hour two-person request over 11 business days adds 40.91 percentage points per full-time person. Most of the original pool cannot accept that request. Changing model prompts cannot create missing capacity.

The expanded sample has 72 people, 467 person-skill records, 530 independent preference records, and 420 dated availability/commitment records. All 18 catalog skills have at least nine qualified people. Eight specialty families cover program management, communications, portal/reporting, enablement, writing, video, visual design, and technical content. Synthetic IDs start with `SYN-`; names and evidence are explicitly labelled synthetic. New baseline allocations range from 20–80%, with full-time and part-time capacity, mixed proficiency and interests, incremental commitments, leave and travel. Dates are anchored to 2026-09-11 across the following year. These are fictional demo scenarios, not real staffing facts or measured employee assessments.

Both the versioned seed and active runtime workbook were expanded. No existing person, request, requirement, recommendation history, decision or assignment was replaced. Customer source mappings and exact skill labels (including `GTM`, `GMT SME` and `GTM SME`) remain separate and unchanged. Restorable pre-expansion copies are under `data/runtime/backups/before-synthetic-expansion-20260911T102513Z/`.

Restart with `./start.sh`, then **re-run fitment for existing unstaffed requests**. Old recommendations are intentionally retained as historical snapshots, not silently recomputed. New requests automatically use the expanded pool. Master-data changes invalidate an old pending proposal's approval fingerprint, so re-run before approving it. The expansion itself does not call OCI, queue work, approve requests, or create assignments.

See [sample validation results](docs/fitment-data-validation.md) for the 55-deliverable benchmark, its planning assumptions and remaining tight-window failures. Run `.venv/bin/python -m backend.audit_fitment` to assess the current workbook without model calls or writes. `backend/sample_data.py` generates the reproducible synthetic records as JSON; it does not overwrite workbooks. `.venv/bin/python -m backend.verify_live_workflow --expanded-synthetic` explicitly calls OCI with the 64 fictional profiles in an isolated workbook and stops at Pending Approval. After the sample dates become stale, generate and validate a refreshed scenario rather than treating old leave/commitments as a current calendar.

Edit the runtime workbook while the application is stopped, then close Excel before restarting. Preserve sheet names, header names and unique IDs. Prefer literal database values; formulas are rejected in operational tables. New workflow records, candidates and decisions are not added to the historical source sheets. The adapter preserves unrelated workbook XML entries and uses atomic replacement, a previous-file backup, and a cross-process lock. Only one application deployment with a shared local filesystem is supported; do not put this workbook on Object Storage, a network-sync drive, or separate replicas and expect transactional behavior. If restoring a `.backup`, stop the app first and keep a copy of the current workbook.

## Production interfaces

Replace `StaffingRepository` with a transactional Oracle 26ai adapter and a proper job queue when moving beyond the prototype. Preserve optimistic revisions and the decision/assignment transaction. Replace the local worker lease with a durable workflow service if deploying serverless or multiple replicas. Read skills from HR/LMS, allocation and assignments from the delivery system, and dated availability from calendar/HR interfaces. Capture real expressed preferences separately.

The prototype uses `APP_REVIEWER_NAME` as a single local reviewer identity; the role dropdown is a mockup control, not authentication or authorization. Integrate OCI IAM/Identity Domains and enforce Request Lead permissions at the API before exposing it to other users. Notifications currently exist only in the workbook and Notifications drawer; wire an outbox to email/enterprise messaging for external delivery. Model input includes relevant request, candidate and staffing evidence, so apply your organization's data-access and model-use controls for real personnel data. Outcomes are recorded for later evaluation; no automatic retraining is performed.

The historical `sql/001_ai_pod_staffing.sql` is an earlier PostgreSQL placeholder, not an Oracle deployment script. Reports and upcoming-demand graphics remain labelled prototype illustrations; the active workflow and allocation calendar use the workbook. This backend migration does not change the seed or runtime workbook schema, remove saved requests, or reset approval history.
