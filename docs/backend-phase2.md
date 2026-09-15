# Agentic backend phase 2 — Oracle persistence foundation

## Scope and status

Phase 2 adds schema, configuration, optional test fixtures, verification/recovery scripts, and Python
read adapters. It does **not** start agents, change the frontend, implement approval endpoints, send email,
or run SQL against the shared database. Existing TypeScript services remain in place.

The files have static checks and offline Python tests. **Oracle execution/compilation has not been
verified here.** Run the scripts in a backed-up development application schema first, retain the complete
SQL Developer output, and stop on the first error. A static test is not an Oracle integration test.

## Files and execution order

All SQL files are in `sql/oracle/` under this repository.

| Order | File | Purpose |
| --- | --- | --- |
| 1 | `phase2.sql` | Add columns and 15 tables; install constraints, indexes, triggers and draft configuration |
| 2 | `phase2_verify.sql` | Read-only fingerprints, constraint/trigger validity and consistency checks |
| 3, optional | `phase2_seed.sql` | Insert 5 new people, 3 requests and supporting evidence/capacity rows |
| 4, optional | `phase2_smoke.sql` | Test real Oracle constraints with temporary DML that is rolled back |
| 5 | `phase2_verify.sql` | Recheck after test data and constraint tests |
| Only if needed | `phase2_recover.sql` | Disable agent/email switches; preserve all data and schema |
| Only after explicit review | `phase2_seed_cleanup.sql` | Remove this fixture batch only, before any agent execution history exists |

Do **not** run `setup.sql`, `install_ai_pod_staffing.sql`, old resets, or previous role/catalogue rollback
files for this upgrade. Those files describe earlier schemas, not this migration.

## Exact SQL Developer steps

1. Stop only AI Pod Staffing's local/VM application writers and any Python worker. Other teams' services stay running.
2. Take a recoverable export/backup using your team's approved procedure. Include the existing application tables,
   their data (including CLOBs), and schema definitions. These scripts do not replace a database backup.
3. Connect through **AIPOD** using database user **AI_POD_STAFFING**, not ADMIN. Use a fresh session with no pending edits.
4. Verify the identity in a worksheet:

   ```sql
   SELECT USER AS connected_user,
          SYS_CONTEXT('USERENV','SESSION_USER') AS session_user_name,
          SYS_CONTEXT('USERENV','CURRENT_SCHEMA') AS current_schema_name
   FROM dual;
   ```

   All three values must be `AI_POD_STAFFING`. A connection's display name alone is not proof of ownership.
5. Open `sql/oracle/phase2.sql` using File → Open, select the AIPOD connection, and press **F5 / Run Script**.
6. Continue only after `SUCCESS: phase-2 schema installed`. Save the Script Output.
7. Open and run `phase2_verify.sql` with F5. It must print `PASS` with no errors. Both runtime switches start `N`.
8. If you want the new testing people/requests, run `phase2_seed.sql` with F5. This is separate and optional.
9. In the stopped development environment, run `phase2_smoke.sql`. It must report success and roll back its test DML.
   It briefly publishes the draft policy **inside its rollback-only test transaction** to exercise a foreign key;
   it does not commit a business approval, assignment or audit row.
10. Run verification again. Restart the existing app and refresh it to see seeded people and requests, if loaded.

No Next.js `.env.local` changes are needed. The Python service still requires the dependency installation and
Oracle/OCI configuration described in `backend/python/README.md`. Do not enable agents or email switches yet.

## Changes to existing tables

| Table | Added fields / behaviour |
| --- | --- |
| `PEOPLE` | `weekly_work_hours` (nullable), `workload_version`, `availability_version`, `staffing_seed_batch` |
| `REQUESTS` | `request_revision`, `responsible_captain_id` FK, `agent_enabled` default `N`, `staffing_seed_batch` |
| `REQUIREMENTS` | `mandatory_flag` default `Y` |
| `AVAILABILITY` | `capacity_kind`: `UNKNOWN`, `NON_AVAILABILITY`, `EXTERNAL_WORK` |

Existing IDs, names, catalogue mappings, ratings, role assignments, request content, recommendation rows and
availability records are retained. Existing people get **no assumed working hours**, and existing requests get
**no guessed Captain**. Request source remains independent from the responsible Captain.

Any request update increments `request_revision`. Availability changes increment a person's availability and
workload versions. Capacity-day and assignment changes increment workload versions. The future backend must
lock affected people in sorted ID order before multi-person writes, including moves between people.

Changing the calendar invalidates previously built capacity inputs through `availability_version`. The Python
adapter refuses those stale inputs. Changing weekly hours also needs a capacity rebuild; phase-2 does not expose
a weekly-hours editing endpoint. Old calendar events remain `UNKNOWN` until classified—do not count them as both
absence and external work. There is no automatic conversion of legacy `allocation_pct` into committed hours.

## New tables

| Table | Stored information |
| --- | --- |
| `STAFFING_POLICIES` | Named draft/approved policy versions and business sign-off metadata |
| `ELIGIBILITY_RULES` | Four versioned rule values: minimum rating, eligible Lead/Member roles, step limit |
| `LOAD_GUARDRAILS` | Working-hour default, allocation ceiling and scheduling timezone |
| `SCORING_WEIGHTS` | Skill/deliverable/capacity/interest weights; total must equal 100 |
| `STAFFING_RUNTIME` | Single-row agent and notification switches, both initially off |
| `AGENT_EXECUTIONS` | Durable job state, idempotency key, retries, lease token/expiry, revisions and snapshots |
| `AGENT_EXECUTION_EVENTS` | Ordered append-only progress events |
| `POD_PROPOSALS` | Request-linked proposal versions, dates, hours, Captain, policy and evidence |
| `POD_PROPOSAL_MEMBERS` | Candidates, selected members, scores, responsibilities, planned hours and evidence versions |
| `APPROVAL_DECISIONS` | One final Captain decision per proposal; rejection reason required |
| `POD_ASSIGNMENTS` | Confirmed assignments linked to an approved decision, approved policy and selected candidate |
| `ASSIGNMENT_DAYS` | Per-person daily assignment hours |
| `PERSON_CAPACITY_DAYS` | Reviewed daily available hours and external committed hours, with source/version references |
| `AUDIT_EVENTS` | Append-only application audit-event storage |
| `NOTIFICATION_OUTBOX` | Deduplicated future assignment-email payloads and delivery state; initially disabled |

The application now has **29 business/operational tables**: the current 14 plus these 15. A separate
`AIPS_P2_MIGRATION` table records the migration's steps and original row counts; it is not a business entity.
Earlier backup tables such as `AIPS_BK_*` are retained and are not included in that count.

The seven previously on-hold governance names are brought into scope. If an older incompatible table already
uses one of these names without this migration's journal, installation stops. Do not drop it to bypass the check.

`RECOMMENDATIONS` remains the legacy frontend projection; it is not rewritten or treated as historical final
assignments. Versioned candidates go into `POD_PROPOSAL_MEMBERS`. A later compatibility layer will project the
current version into the existing UI without changing the UI design.

## Integrity and workflow boundaries

- Exactly one active execution per request/revision, and one proposal currently ready for review per request.
- Proposal version and idempotency keys prevent duplicate logical records. IDs are supplied by the backend;
  new operational tables do not use multi-table `INSERT ALL` identity generation.
- Candidates are editable only while the proposal is building. Published evidence is frozen.
- Publishing checks selected Lead/Member counts and their total planned person-hours.
- A decision must reference the proposal's Captain and a current request revision in review. Rejection rejects
  null/blank/whitespace-only reasons. Decision and progress history are append-only.
- An assignment must reference an `APPROVED` decision, an approved policy, and a selected proposal member.
  There is **no acceptance state, 24-hour timer or Lead/Member confirmation**.
- Assignment dates and individual daily rows are bounded; verification checks daily sums against assignment totals.
- Agent snapshots/checkpoints are JSON storage only. This is **not** a LangGraph checkpointer implementation.
- Capacity checks, signed-user authorization, canonical evidence validation, policy JSON semantics, cross-person
  hour totals, team capability coverage and atomic writes still belong to the phase-3/4 backend transaction layer.
  SQL constraints do not implement those complete workflows or prove that the LLM supplied truthful evidence.
- The revision/Captain database checks are not a replacement for token authentication. Anyone using the schema
  owner's credentials is privileged; do not expose database credentials or direct SQL tools to an agent.

Captain approval will lock the request, proposal and candidate people, re-read workloads and evidence, apply
the deterministic validator, then save decision + assignments + daily hours + audit + disabled outbox atomically.
Two approvals cannot both rely on stale free capacity. Unapproved proposals reserve **no hours**.

## Audit guarantees: explicit limitation

`AUDIT_EVENTS` is a regular Oracle table with a trigger blocking UPDATE and DELETE. It is **not a blockchain
table, cryptographically immutable store or tamper-proof audit against the schema owner/DBA**. The same applies
to append-only decision/progress triggers. Privileged users can disable triggers or perform DDL.

No automatic audit event is fabricated for ordinary application operations in this phase. Future command
handlers must insert audit rows in the same transaction as their business changes. Stronger owner-resistant
retention requires a separately reviewed Oracle blockchain/immutable configuration and privileges; this script
does not repeat the previous blockchain type/retention compatibility issue or pretend a normal table is equivalent.

## Draft defaults

The script stores the phase-1 defaults as `staffing-v1-draft`, status `DRAFT`:

- 40 hours/week; Mon–Fri assumed by the calculator; Asia/Kolkata business timezone.
- 100% capacity ceiling; default capability threshold 3/5.
- Lead role `POD_LEAD`; Member role `POD_MEMBER` or `POD_LEAD`; 12-step agent limit.
- Weights: skill 50, deliverable experience 30, capacity 15, interest 5.

These are not newly approved business rules. The Project Manager `DERIVED_ROLE_CODE` remains unchanged and
is not inferred. Policy publication requires business sign-off and validated values. Agent execution will use
the exact stored policy version, not a silently changing set of defaults. Approved policy records/configuration
are frozen; make a new policy version for revisions.

## Optional fixtures and future replacement

Five new people use numeric IDs **P-900101 through P-900105**, three new requests use **REQ-900101 through
REQ-900103**. They use actual active catalogue IDs and existing JSON shapes. They do not replace Elena, other
existing people, or any current request. Seeded identity subjects use `seed:backend-p2:` and are not real logins.
No email addresses are fabricated; email is disabled.

- `REQ-900101`: 24-hour request for feasible-planning tests.
- `REQ-900102`: 120-hour request in the same week, for insufficient-capacity handling.
- `REQ-900103`: unresolved mandatory custom capability, for the information-needed path.

Dates start the next Monday relative to the seed run. There are 70 daily capacity rows (five people × fourteen
calendar days), one travel event, role assignments, ratings and deliverable experience. Capacity scenarios are
fixtures for future agents; the current UI's cached allocation percentages are not rewired in this phase.

No UI banners or labels mentioning dummy/demo data were added. Provenance is retained in backend fields,
source values and the migration journal. Seed loading is one transaction and refuses ID collisions. Reruns
preserve the loaded records; they do not refresh dates or overwrite edits.

Cleanup is separate, disabled by default, and requires editing its confirmation constant. It removes only this
tagged fixture set. It refuses after agent execution history exists and rolls back if unrelated foreign-key
references prevent deletion. No cascade drops or broad schema reset are provided. Once real governed history
exists, use a reviewed archive/retention process rather than deleting it. A future full test-to-real-data cutover
requires a separately scoped export and reset plan for application-owned data only.

## Failure and recovery

### Corrected first-run ORA-01403 in the migration runner

The original runner reused the outer `n` counter in both `apply_step()` and `fingerprint()`.
Checking an existing table changed the missing journal-step count from zero to one. The runner then
attempted to select a nonexistent journal row, raising ORA-01403 before its first ALTER TABLE.
The corrected `phase2.sql` gives the helpers independent local counters. All DDL payloads remain
unchanged, so their recorded step hashes remain compatible. No journal rows need to be deleted or
manually marked applied.

For this specific error, close the old SQL Developer file tab without saving stale contents over the
corrected file. Reopen the latest `phase2.sql`, choose AIPOD in a fresh worksheet/session, and run F5.
Keep application writers stopped. The migration journal and original baseline-count entries may already
be committed; leave them in place. After success, continue with `phase2_verify.sql`.

Optional read-only confirmation before retrying:

```sql
SELECT step_key, object_type, object_name, state
FROM AI_POD_STAFFING.AIPS_P2_MIGRATION
ORDER BY step_key;
```

For the first-run counter failure, expect baseline entries but no `ALTER_PEOPLE` entry. If other steps
already exist, keep them; the corrected runner still checks hashes and refuses unrecognised state.

Oracle DDL commits independently. A printed `Rollback` cannot undo already-created tables or added columns.
The migration writes a durable `STARTED` step before each DDL and an `APPLIED` fingerprint afterward.

- **Ordinary DDL failure before creation:** fix the cause, rerun the same unchanged `phase2.sql`; completed steps verify and skip.
- **Lost connection after DDL, before the journal captured its fingerprint:** the script stops on ambiguous state.
  Have the DBA compare the exact object definition and journal entry. Do not mark it applied blindly or drop it automatically.
- **Changed file or changed object definition:** stop and review; no `ORA-00955` suppression or silent adoption.
- **Quota/privilege error:** have the DBA confirm the application's tablespace quota and necessary CREATE TABLE/INDEX/TRIGGER
  privileges. Do not change any teammate's user or tablespace.
- **Parallel sibling-lock error:** sessions explicitly disable parallel DML/query/DDL; ensure app writers are stopped and use a new session.
- **Seed failure:** all fixture DML rolls back; identity sequence gaps in existing tables are harmless.
- **Need the old app running again:** stop workers, run `phase2_recover.sql` to disable switches, review output and restart the
  prior application. The additive tables/columns stay in place. This is an operational rollback, not removal of DDL or restoration of a backup.

Do not delete `AIPS_P2_MIGRATION` to force a rerun. Do not edit an already-applied migration; use a reviewed
follow-up migration for later schema changes. Keep these files and their output with the release record.

## Python adapters and verification

`backend/python/app/storage.py` adds read adapters for policy, request snapshots and daily capacity. Call them
inside a single `OracleDatabase.read()` transaction after enforcing the caller's record scope. They are not
public endpoints and are not wired into the old frontend APIs. The phase-1 `/v1/policy` endpoint still returns its
static draft; phase 3 must use `load_policy()` for the execution's selected persisted policy version.

Unknown Captains/dates/counts and mandatory custom skills return information-needed errors. Duplicate skill
requirements merge using the strongest threshold. Role-derived legacy ratings are ignored. Full-week capacity
must exist and match the current availability version. Only confirmed assignment hours count; proposals do not.

Run offline checks from `backend/python` after installing the dependencies:

```text
uv run python -m unittest discover -s tests -v
uv run python -m compileall -q app tests
```

Tests include adapters and static migration checks. The runtime/auth and LangGraph suites still need the
dependencies that were unavailable during phase 1. A full integration pass additionally requires executing
`phase2_verify.sql` and `phase2_smoke.sql` successfully in Oracle; none was executed by the coding agent.

Oracle behaviour references: [DDL transaction boundaries](https://docs.oracle.com/en/database/oracle/oracle-database/19/cncpt/transactions.html)
and [JSON check constraints](https://docs.oracle.com/en/database/oracle/oracle-database/26/sqlrf/is-json-condition.html).
