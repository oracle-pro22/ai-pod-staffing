# Python backend — phase 5

**Demo improvement update:** for the populated September roster and corrected available-day planning, use
[Demo Phase 2: correct agent plans](../../docs/demo-agent-phase2.md). It includes the separate v2 policy,
exact current startup commands, read-only verification and test results. The four-persona entry screen is the next phase.

**Current release:** two tool-calling agents, deterministic POD search, Oracle job leases/checkpoints,
proposal publication, Captain decisions and final assignment APIs are implemented. Start with
[the phase-5 guide](../../docs/backend-phase5.md) for identity, assignments, closure and deployment;
[the phase-3 runbook](../../docs/backend-phase3.md) covers Python installation and OCI checks.
No new DDL is needed for phase 5. Assignment reporting, Lead/Member views, closure and disabled email
preparation are implemented. All execution/decision flags remain OFF by default. Live acceptance remains required.

The sections below retain the phase-1 foundation documentation and its historical verification results.
The phase-3 runbook supersedes statements below that describe agents or persistence as unimplemented.

Phase-2 persistence scripts and read adapters are now added. See `docs/backend-phase2.md` at the
repository root for their separate SQL execution order, boundaries and recovery instructions.
The phase-1 run commands below are unchanged; phase 2 does not enable automatic staffing.

This is an additive backend foundation. The existing Next.js application, its API routes,
Oracle data, and OCI rephraser are unchanged. No SQL needs to be executed for phase 1.

## What is implemented

- FastAPI service with liveness, read-only Oracle readiness, authenticated identity and policy endpoints.
- Bounded, lazy Oracle connection pool, application-schema verification and read-only transactions.
- RS256 bearer-token verification against a configured OIDC issuer, audience and JWKS endpoint.
- Database-backed identity/role permissions; the frontend profile dropdown cannot authenticate this service.
- Typed request, evidence, proposal, decision, execution and progress contracts.
- Deterministic eligibility, team validation, scoring and hours-based capacity calculations.
- Interfaces for two future agents and a bounded LangGraph tool-calling compatibility test for OCI.
- Offline tests, environment template and explicit read-only/live verification commands.

There is **no operational staffing agent, request-save trigger, proposal persistence, approval API,
assignment writer, email sender or database migration in this phase**. The two agent interfaces are
not implemented agents. The OCI smoke graph is a real tool-call integration test, not the staffing workflow.

## Folder responsibilities

| Path | Responsibility |
| --- | --- |
| `app/main.py` | FastAPI endpoints and redacted errors |
| `app/config.py`, `.env.example` | Server configuration; no embedded credentials |
| `app/auth.py` | Token verification, Oracle identity lookup, scope/Captain checks |
| `app/database.py` | Oracle read-only pool and schema checks |
| `app/contracts.py` | Strict business input/output contracts |
| `app/policy.py` | Explicitly draft rule defaults |
| `app/capacity.py`, `app/rules.py` | Calculations and mandatory POD validation |
| `app/agents/contracts.py` | Analyst/Planner boundaries and future tool inventory |
| `app/agents/oci_model.py`, `app/agents/smoke.py` | OCI adapter and LangGraph compatibility test |
| `app/cli.py` | Read-only DB check and opt-in OCI check |
| `tests/` | Rules, mocked runtime/auth and mocked graph tests |

Keep the existing TypeScript services in `backend/ai`, `backend/skills`, etc. in place. Moving them now
would unnecessarily couple the functioning UI to an unfinished staffing service.

## 1. Install Python dependencies

Use Python **3.12** and `uv`. From the project root:

```powershell
cd backend/python
uv sync --python 3.12
```

This creates a local `.venv`. The first successful sync resolves dependencies and generates `uv.lock`.
Review and commit that lockfile; subsequent deployment installs should use `uv sync --locked`.
The current checkout has **no generated lockfile**: package-index access timed out during implementation.
Do not claim dependency reproducibility or deploy the service until resolution and full tests succeed.
Use an organisation-approved package mirror if direct PyPI access is blocked; do not disable TLS verification.

The manifest includes FastAPI, Pydantic, python-oracledb, OCI SDK, LangChain, LangGraph,
`langchain-oci` and PyJWT. Exact interoperability remains to be verified after installation.

## 2. Create the Python environment file

Run once, without overwriting an existing configuration:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Edit `.env` locally. It is excluded from Git. Do not paste passwords, wallet contents, private keys or
access tokens into chat or source control. The Python process does not automatically load Next.js `.env.local`.

| Setting | What to provide |
| --- | --- |
| `DB_USER` | `AI_POD_STAFFING`, enforced for this application |
| `DB_PASSWORD`, `DB_TNS_ALIAS` | Approved existing application database credentials/service alias |
| `DB_WALLET_LOCATION`, `DB_WALLET_PASSWORD` | Wallet directory on this host and its password |
| `DB_POOL_MIN/MAX/INCREMENT` | Default `0/2/1`; separate from the Next.js pool, so account for both |
| `OCI_CONFIG_FILE`, `OCI_CONFIG_PROFILE` | Existing OCI SDK config and profile; key path must work on this host |
| `OCI_GENAI_ENDPOINT/COMPARTMENT_ID/MODEL_ID` | Approved OCI inference endpoint, compartment and tool-capable model |
| `OCI_GENAI_PROVIDER` | Confirmed `langchain-oci` provider, such as `generic`, `meta` or `cohere` |
| `OCI_TIMEOUT_SECONDS` | Read timeout per model request, default 30 seconds |
| `OIDC_ISSUER/AUDIENCE/JWKS_URL` | Approved enterprise **access-token** issuer, backend audience and trusted HTTPS key endpoint |
| `BACKEND_ENV` | `local` during development; `production` requires OIDC configuration |
| `BACKEND_AUTH_MODE` | `oidc` normally; optional server-configured `local` testing mode described below |

Use `generic` only for a supported OpenAI-family model hosted **inside OCI**. This uses OCI signing,
not a new OpenAI API key. A model supporting rephrasing alone does not prove that it supports tool calling.
Provider/model compatibility must pass the smoke test. Do not guess the provider from a model OCID.

Existing request data is not sent to OCI by any phase-1 endpoint. The opt-in smoke test sends only fixed
non-personal arithmetic inputs. External LangSmith tracing is disabled in the smoke CLI.

## 3. Run the service locally

From `backend/python`, after dependency installation and configuration:

```powershell
uv run uvicorn app.main:app --host 127.0.0.1 --port 8015 --env-file .env
```

In another terminal:

```powershell
curl.exe --max-time 5 http://127.0.0.1:8015/health/live
curl.exe --max-time 30 http://127.0.0.1:8015/health/ready
```

- `/health/live`: process responds; does not establish Oracle or OCI readiness.
- `/health/ready`: verifies Oracle connectivity and application schema, read-only. Missing credentials return 503.
- `/docs`: local API documentation; disabled in production.
- `/v1/me`: requires a valid token and active Oracle identity mapping.
- `/v1/policy`: additionally requires `AGENT_EXECUTION` view permission; returns the draft policy.

Port 8015 is a proposed separate backend port, not a replacement for UI ports 3001/8005. Check that it
is free before use. Bind to localhost; do not open a public VM port for this foundation. Stop this
foreground process with Ctrl+C. Production service supervision/reverse proxy integration comes later.

Continue running the UI from the project root with `npm run dev`. No new frontend environment
variable, proxy setting, database SQL or frontend rebuild is required by these additive phase-1 files.

## 4. Identity boundary

The server verifies signature, expiry, issuer, audience and subject. It then resolves that subject
using `APP_USER_ROLES`, active `PEOPLE`, active `APP_ROLES` and `ROLE_PERMISSIONS`.
Effective dates use `TRUNC(SYSDATE)` to match the current application's Oracle queries.
Missing, inactive or ambiguous mappings fail closed. JWT role claims and `x-staffing-role` are not grants.

Each protected record operation must also enforce the permission's `FULL`, `SCOPED` or `OWN` scope.
The helper returns a scope; it does not magically filter a future repository. A Captain decision
requires the actual responsible Captain, not the person named in **Request source**. Administrator
access is not an implicit Captain identity. No role assignment is created by this implementation.

Browser SSO login, token acquisition and Next.js-to-Python forwarding are **not connected yet**.
For local API tests only, you may configure a random token of at least 32 characters and an existing
mapped subject using `BACKEND_AUTH_MODE=local`, `BACKEND_LOCAL_TOKEN`, `BACKEND_LOCAL_SUBJECT`.
This still looks up Oracle permissions, accepts no client-selected identity, and cannot run in production.
Do not assign identities by matching names or by using the demo role dropdown.

## 5. Verify

Full offline suite after installation:

```powershell
uv run python -m unittest discover -s tests -v
uv run python -m compileall -q app tests
```

For a complete offline pass, **zero dependency-related skips** are required. Tests use mocked Oracle,
JWKS and model interfaces; they do not contact the database or OCI. Skipped modules are not passing checks.

Read-only live Oracle verification, after filling `.env`:

```powershell
uv run python -m app.cli database --env-file .env
```

Expected: `database: reachable`, `schema_verified: true`, `writes: 0`.

Optional live OCI interoperability test (two model calls, may incur usage):

```powershell
uv run python -m app.cli oci --env-file .env --live
```

The model must emit the allowed calculation tool call with 16/40, consume its actual result and
finish without further tools. The graph rejects missing, unexpected or repeated tool calls.
Expected: `tool_call: passed`, `langgraph: passed`, `allocation_pct: 40`, `writes: 0`.
This does not test staffing quality, structured proposal generation, production persistence or recovery.

## Rulebook implemented for offline validation

These defaults are **draft backend policy**, not newly finalised business decisions. No frontend
draft/demo notice has been added. Business sign-off and versioned persistence belong to later phases.

- A request needs dates, positive total **person-hours**, requested lead/member counts, deliverables,
  canonical capability IDs, request revision and responsible Captain ID.
- Default team size is one Lead and two Members, configurable per snapshot. Counts are not inferred by the LLM.
- Candidates must be active and have eligible role assignments covering the request's scheduled dates.
- A Lead slot requires `POD_LEAD`; a Member slot accepts `POD_MEMBER` or `POD_LEAD`.
- All mandatory capabilities need team coverage; default self-rating threshold is 3/5. Interest alone
  is not a proficiency rating. Self-assessment is not relabelled as independently verified experience.
- Role-derived capabilities such as Project Manager require an explicit approved role mapping;
  no job-title inference or user-entered score can grant them. A missing mapping blocks validation.
- Deliverable experience uses the existing `LEARNING`, `SUPPORTED`, `INDEPENDENT`, `MENTOR` and
  `CONTRIBUTOR`/`END_TO_END` values. It does not automatically grant mapped skills or a Lead role.
- Supported experience needs an independently capable teammate assigned to the same deliverable.
  Free text is evidence supplied by the person, not instructions or proof of verified past delivery.
- Unknown capacity blocks eligibility. Duplicate people, stale revisions/policies, incorrect team size,
  unassigned/extra deliverables and hours that do not sum to the request total are rejected.
- Draft score: skill fit 50%, deliverable experience 30%, remaining capacity 15%, interest 5%.
  Missing ratings score zero and are identified as unknown. Calculations, not the LLM, produce scores.
- Scoring is separate from hard eligibility. A high score cannot override a failed rule.
- An accepted policy version must pass `require_published()` before any future live assignment write.
  `validate_pod()` alone is not authorization, policy publication, evidence verification or a database transaction.

## Simple allocation model

Default weekly capacity is 40 hours, evenly split across Monday–Friday. Dates are business dates in
the policy timezone (initially Asia/Kolkata); future repositories must normalise timestamps accordingly.

`allocation % = (confirmed assigned hours + external committed hours + proposed hours) / available hours × 100`

Available hours are scheduled working hours less non-availability. For current allocation, omit proposed
hours; include them only when evaluating a candidate proposal. Pending/unapproved proposals reserve nothing.
Example: 16 confirmed + 8 proposed hours / 40 available hours = 60% projected allocation.

Hours are spread evenly across working dates, preserving the exact total to 0.01 hour. Check both
full weekly buckets and individual days against a 100% ceiling. A one-day 9-hour task cannot fit in
an 8-hour day merely because the rest of the week is empty. Leave blocks that day's scheduled work;
the calculator does not silently shift it to another day. Full absence is unavailable, not 0% loaded.

The caller must supply complete, de-duplicated daily ledgers for every touched week. The same calendar
commitment must not appear in both external work and confirmed assignments. Existing aggregate
`PEOPLE.allocation_pct` is not added again, and `active_pods` is not a substitute for hours.
Holidays, alternative working patterns, time-of-day overlaps and automatic rescheduling are deferred.
Active POD counts will later count distinct confirmed, non-closed assignments for the selected period.

## Next phases and persistence boundary

Phase 2 supplies reviewed Oracle migrations, authoritative workload inputs, versioned proposal/decision/
assignment storage, execution persistence and resettable test data. No broad schema reset is performed here.

Phase 3 implements the two agents and bounded controller using the declared read/calculation tools.
No generic SQL, shell, permission-editing, assignment or email tools should be exposed to an LLM.
Tool IDs/evidence must be verified against a server-loaded snapshot; prompts alone cannot establish truth.

Later workflow integration must atomically save a request and its execution job, use idempotency keys,
lease/retry queued work, persist progress, and recover after worker restarts. Agent output becomes a
versioned proposal only after deterministic validation. Rejection records a reason and preserves history.

Captain approval will re-read and lock the relevant current records, revalidate capacity and revisions,
and commit assignments once. Pending proposals reserve no hours, so **two approvals must serialize and
re-check capacity**. Captain approval is final; there is no Lead/Member acceptance or timeout.
Email preparation belongs to a later transactional outbox with dispatch disabled until implemented.

## Verification recorded on 2026-09-11

- 38 Pydantic/core rule tests passed using available Python 3.12.
- Runtime/authentication test module and LangGraph test module skipped because dependencies could not install.
- Existing Next.js regression tests: 30 self-skills + 25 application tests passed.
- Python syntax compilation passed.
- PyPI requests timed out; full dependency resolution, API startup and live Oracle/OCI checks remain unverified.
- No live database write, migration, seed operation, email or OCI model call was made.

## Integration references

For the later **three-phase demo improvement plan**, see
[Demo data Phase 1](../../docs/demo-data-phase1.md). It includes a read-only plan,
verified backups, a rollback rehearsal, explicit commit, allocation verification
and scoped recovery. This is separate from the original five backend phases below.

The OCI adapter follows the official [LangChain OCI integration](https://docs.langchain.com/oss/python/integrations/chat/oci_generative_ai)
and [Oracle provider package](https://github.com/oracle/langchain-oracle/tree/main/libs/oci).
Connection pooling follows [python-oracledb connection handling](https://python-oracledb.readthedocs.io/en/latest/user_guide/connection_handling.html).
Token validation follows [PyJWT usage](https://pyjwt.readthedocs.io/en/stable/usage.html).
