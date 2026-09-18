"""Explicit Phase-1 maintenance: template -> preview -> apply -> verify.

Never run at application startup. No model/email calls. No catalogue DML.
All business DML is transactional; four immutable-history delete guards are
temporarily suspended only during a stopped-service, archived maintenance run.
Original trigger text is never changed. An interrupted guard change is recoverable.
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from pydantic import Field, field_validator, model_validator

from app.accounts import hash_password, normalize_email
from app.capacity_admin import build_days
from app.contracts import Contract
from app.demo_data import read_catalog
from app.demo_dataset import DemoDataset
from app.errors import ServiceError
from app.execution_store import execute
from app.mvp_roster import PERSON_RENAMES, additional_people, placeholder_email
from app.storage import document, rows

PROTECTED = ("PROJECT_TYPES", "DELIVERABLES", "DELIVERABLE_SKILLS", "INTERESTS", "CUSTOMER_MAPPING",
             "APP_ROLES", "ROLE_PERMISSIONS", "STAFFING_POLICIES", "ELIGIBILITY_RULES", "LOAD_GUARDRAILS", "SCORING_WEIGHTS")
REQUEST_TABLES = ("NOTIFICATION_OUTBOX", "ASSIGNMENT_DAYS", "POD_ASSIGNMENTS", "POD_PROPOSAL_MEMBERS",
                  "APPROVAL_DECISIONS", "POD_PROPOSALS", "AGENT_EXECUTION_EVENTS", "AGENT_EXECUTIONS",
                  "RECOMMENDATIONS", "REQUIREMENTS", "REQUESTS")
PERSON_TABLES = ("PEOPLE", "PERSON_INTERESTS", "AVAILABILITY", "PERSON_CAPACITY_DAYS", "APP_USER_ROLES")
SNAPSHOT_TABLES = PERSON_TABLES + REQUEST_TABLES
GUARDS = ("P2_MEMBER_FREEZE", "P2_PROPOSAL_FREEZE", "P2_DECISION_APPEND", "P2_EVENT_APPEND")
RESTORE_GUARDS = (*GUARDS, "P2_DECISION_REVIEW")
PERSON_CHILDREN = {"PERSON_INTERESTS", "AVAILABILITY", "PERSON_CAPACITY_DAYS", "APP_USER_ROLES", "APP_ACCOUNTS"}
SCHEMA_COLUMNS = {
    "APP_ACCOUNTS": {"ACCOUNT_ID", "PERSON_ID", "IDENTITY_SUBJECT", "LOGIN_EMAIL", "PASSWORD_HASH", "ACTIVE_FLAG", "FAILED_ATTEMPTS", "LOCKED_UNTIL", "CREATED_AT", "CREATED_BY"},
    "APP_SESSIONS": {"TOKEN_HASH", "ACCOUNT_ID", "CREATED_AT", "EXPIRES_AT", "REVOKED_AT"},
    "MVP_P1_ARCHIVE": {"BATCH_ID", "TABLE_NAME", "ROW_KEY", "ROW_JSON", "ARCHIVED_AT", "OPERATOR_NAME"},
    "MVP_P1_RUNS": {"BATCH_ID", "MANIFEST_HASH", "STATUS", "METADATA_JSON", "CREATED_AT", "OPERATOR_NAME"},
}
TIMESTAMP_FORMAT = 'YYYY-MM-DD"T"HH24:MI:SS.FF9'
TIMESTAMP_TZ_FORMAT = TIMESTAMP_FORMAT + 'TZH:TZM'


class Manifest(Contract):
    version: int = 1
    batch_id: str = Field(pattern=r"^mvp1-[A-Za-z0-9_-]{1,30}$")
    anchor: date
    archive_request_ids: tuple[str, ...] = ()
    person_id_map: dict[str, str] = Field(default_factory=dict)
    account_emails: dict[str, str]
    add_people: bool = True
    expected_snapshot: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("account_emails")
    @classmethod
    def emails(cls, values):
        return {k: normalize_email(v) for k, v in values.items()}

    @model_validator(mode="after")
    def validate_manifest(self):
        if self.version != 1 or self.anchor.weekday() != 0:
            raise ValueError("Use manifest version 1 and a Monday anchor")
        ids = [*self.archive_request_ids, *self.person_id_map, *self.person_id_map.values(), *self.account_emails]
        if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,30}", v) for v in ids):
            raise ValueError("Invalid identifier")
        if len(set(self.archive_request_ids)) != len(self.archive_request_ids):
            raise ValueError("Duplicate request IDs")
        if set(self.person_id_map) & set(self.person_id_map.values()) or len(set(self.person_id_map.values())) != len(self.person_id_map):
            raise ValueError("Person mapping must be one-to-one without cycles")
        if len(set(self.account_emails.values())) != len(self.account_emails):
            raise ValueError("Duplicate login emails")
        return self


def demand(condition, message, code="MVP_PREFLIGHT"):
    if not condition:
        raise ServiceError(code, message, 409)


def progress(message):
    print(message, file=sys.stderr, flush=True)


def driver_error_details(error):
    """Expose only a driver error code in this operator CLI, never raw SQL/binds."""
    import oracledb
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, oracledb.Error) and error.args:
            code = getattr(error.args[0], 'full_code', None)
            if isinstance(code, str) and re.fullmatch(r'(ORA-\d{5}|DPY-\d{4}|DPI-\d{4})', code):
                return {'driver_code': code}
        error = error.__cause__ or error.__context__
    return {}


def packed(value):
    if hasattr(value, "read"):
        value = value.read()
    if isinstance(value, datetime):
        return {"$datetime": value.isoformat()}
    if isinstance(value, date):
        return {"$date": value.isoformat()}
    if isinstance(value, Decimal):
        return {"$decimal": str(value)}
    if isinstance(value, dict):
        return {k: packed(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [packed(v) for v in value]
    return value


def unpacked(value):
    if isinstance(value, dict):
        if set(value) == {"$datetime"}:
            return datetime.fromisoformat(value["$datetime"])
        if set(value) == {"$date"}:
            return date.fromisoformat(value["$date"])
        if set(value) == {"$decimal"}:
            return Decimal(value["$decimal"])
        return {k: unpacked(v) for k, v in value.items()}
    if isinstance(value, list):
        return [unpacked(v) for v in value]
    return value


def canonical(value):
    return json.dumps(packed(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def column_types(c, table):
    demand(table in (*PROTECTED, *SNAPSHOT_TABLES, "APP_ACCOUNTS", "APP_SESSIONS"), "Table not allowlisted")
    columns = rows(c, "SELECT column_name,data_type FROM user_tab_columns WHERE table_name=:name ORDER BY column_id", name=table)
    demand(columns and all(re.fullmatch(r'[A-Z][A-Z0-9_]*', r['column_name']) for r in columns), 'Unexpected table columns.')
    return {r['column_name'].lower(): r['data_type'] for r in columns}


def timestamp_format(data_type):
    if data_type.startswith('TIMESTAMP'):
        demand('LOCAL TIME ZONE' not in data_type, 'Local-time-zone columns need explicit archival review.')
        return TIMESTAMP_TZ_FORMAT if 'WITH TIME ZONE' in data_type else TIMESTAMP_FORMAT
    return None


def table_rows(c, table):
    projection = []
    for name, kind in column_types(c, table).items():
        fmt = timestamp_format(kind)
        # Preserve Oracle nanoseconds and offsets rather than truncating them to a
        # Python datetime. This also makes a later exact restore verifiable.
        projection.append(f"TO_CHAR({name},'{fmt}') {name}" if fmt else name)
    return [packed(r) for r in rows(c, f"SELECT {','.join(projection)} FROM {table}")]


def snapshot(c):
    result = {table: table_rows(c, table) for table in (*PROTECTED, *SNAPSHOT_TABLES)}
    return result


def fingerprints(saved):
    return {table: digest(sorted(canonical(row) for row in data)) for table, data in saved.items()}


def snapshot_hash(saved):
    return digest(fingerprints(saved))


def require_schema(c):
    for table, expected in SCHEMA_COLUMNS.items():
        actual = rows(c, "SELECT column_name FROM user_tab_columns WHERE table_name=:name", name=table)
        demand({r["column_name"] for r in actual} == expected, "Run and verify sql/oracle/mvp_phase1.sql first.")
    bad = rows(c, """SELECT constraint_name FROM user_constraints WHERE table_name IN
        ('APP_ACCOUNTS','APP_SESSIONS','MVP_P1_ARCHIVE','MVP_P1_RUNS') AND (status<>'ENABLED' OR validated<>'VALIDATED')""")
    demand(not bad, "Phase-1 constraints must be enabled and validated.")
    keys = rows(c, """SELECT k.table_name,k.constraint_type,k.constraint_name,cc.column_name
        FROM user_constraints k JOIN user_cons_columns cc ON cc.constraint_name=k.constraint_name
        WHERE k.table_name IN ('APP_ACCOUNTS','APP_SESSIONS','MVP_P1_ARCHIVE','MVP_P1_RUNS')
        AND k.constraint_type IN ('P','U') ORDER BY cc.position""")
    grouped = {}
    for key in keys:
        grouped.setdefault((key['table_name'], key['constraint_type'], key['constraint_name']), []).append(key['column_name'])
    shapes = {(table, kind, tuple(columns)) for (table, kind, _), columns in grouped.items()}
    required = {('APP_ACCOUNTS', 'P', ('ACCOUNT_ID',)), ('APP_ACCOUNTS', 'U', ('PERSON_ID',)),
                ('APP_ACCOUNTS', 'U', ('IDENTITY_SUBJECT',)), ('APP_ACCOUNTS', 'U', ('LOGIN_EMAIL',)),
                ('APP_SESSIONS', 'P', ('TOKEN_HASH',)), ('MVP_P1_RUNS', 'P', ('BATCH_ID',)),
                ('MVP_P1_ARCHIVE', 'P', ('BATCH_ID', 'TABLE_NAME', 'ROW_KEY'))}
    demand(required <= shapes, "Phase-1 primary/unique keys do not match the migration.")
    links = rows(c, """SELECT r.table_name,cc.column_name,p.table_name parent_table FROM user_constraints r
        JOIN user_cons_columns cc ON cc.constraint_name=r.constraint_name
        JOIN user_constraints p ON p.constraint_name=r.r_constraint_name
        WHERE r.table_name IN ('APP_ACCOUNTS','APP_SESSIONS') AND r.constraint_type='R'""")
    demand({('APP_ACCOUNTS','PERSON_ID','PEOPLE'), ('APP_SESSIONS','ACCOUNT_ID','APP_ACCOUNTS')} <=
           {(r['table_name'],r['column_name'],r['parent_table']) for r in links}, "Account/session foreign keys are missing.")


def require_stopped(c):
    runtime = rows(c, "SELECT agents_enabled,notifications_enabled FROM staffing_runtime WHERE runtime_id=1")
    demand(len(runtime) == 1 and runtime[0] == {"agents_enabled": "N", "notifications_enabled": "N"},
           "Stop application writers and set agent/email runtime switches to N first.")
    demand(not rows(c, "SELECT execution_id FROM agent_executions WHERE status IN ('RUNNING','QUEUED')"),
           "Resolve queued/running executions before maintenance; no jobs were changed.")


def make_template(c, anchor):
    saved = snapshot(c)
    mapping = {k: v for k, v in PERSON_RENAMES.items() if any(p["person_id"] == k for p in saved["PEOPLE"])}
    emails = {mapping.get(p["person_id"], p["person_id"]): placeholder_email(p["full_name"]) for p in saved["PEOPLE"] if p["active_flag"] == "Y"}
    emails.update({p.person_id: p.email for p in additional_people()})
    return Manifest(batch_id="mvp1-" + anchor.isoformat(), anchor=anchor,
                    archive_request_ids=tuple(sorted(r["request_id"] for r in saved["REQUESTS"])),
                    person_id_map=mapping, account_emails=emails, expected_snapshot=snapshot_hash(saved))


def selected_request_rows(saved, request_ids):
    ids = set(request_ids)
    proposals = {r["proposal_id"] for r in saved["POD_PROPOSALS"] if r["request_id"] in ids}
    assignments = {r["assignment_id"] for r in saved["POD_ASSIGNMENTS"] if r["request_id"] in ids}
    executions = {r["execution_id"] for r in saved["AGENT_EXECUTIONS"] if r["request_id"] in ids}
    foreign = {"ASSIGNMENT_DAYS": ("assignment_id", assignments), "POD_PROPOSAL_MEMBERS": ("proposal_id", proposals),
               "AGENT_EXECUTION_EVENTS": ("execution_id", executions)}
    return {table: [row for row in saved[table] if row[foreign.get(table, ("request_id", ids))[0]] in foreign.get(table, ("request_id", ids))[1]]
            for table in REQUEST_TABLES}


def dataset(manifest):
    return DemoDataset(manifest.anchor, manifest.anchor + timedelta(days=62), additional_people() if manifest.add_people else (), (), ())


def preflight(c, manifest):
    saved = snapshot(c)
    demand(snapshot_hash(saved) == manifest.expected_snapshot, "Data changed since the template was created. Generate and review a fresh manifest.", "MVP_STALE_MANIFEST")
    ids = {r["person_id"] for r in saved["PEOPLE"]}
    demand(set(manifest.person_id_map) <= ids and not set(manifest.person_id_map.values()) & ids, "Person normalization conflicts with current IDs.")
    if manifest.person_id_map:
        person_copy_columns(c)  # Validate the exact rename metadata query before maintenance.
    demand(set(manifest.archive_request_ids) <= {r["request_id"] for r in saved["REQUESTS"]}, "A selected request is missing.")
    additions = dataset(manifest)
    demand(not ids & {p.person_id for p in additions.people}, "An added person ID already exists.")
    active = {manifest.person_id_map.get(p["person_id"], p["person_id"]) for p in saved["PEOPLE"] if p["active_flag"] == "Y"}
    demand(set(manifest.account_emails) == active | {p.person_id for p in additions.people}, "Provide exactly one email for each active and added person.")
    chosen = selected_request_rows(saved, manifest.archive_request_ids)
    # Historical frozen evidence keeps original IDs in the archive. All linked requests
    # for a renamed person must be included; never rewrite JSON history by replacement.
    old = set(manifest.person_id_map)
    person_columns = ("person_id", "recipient_person_id", "request_source_person_id", "responsible_captain_id", "captain_person_id")
    for table in REQUEST_TABLES:
        retained = [r for r in saved[table] if r not in chosen[table]]
        demand(not any(r.get(k) in old for r in retained for k in person_columns),
               "A renamed person is referenced by a retained request. Include that request or omit the rename.")
        demand(not any(person in canonical(r) for person in old for r in retained),
               "Retained request evidence still names a normalized ID. Archive that request or omit the rename.")
    # Unknown consumers must be explicitly designed for, not automatically rewritten.
    refs = rows(c, """SELECT a.table_name,a.column_name FROM user_cons_columns a
        JOIN user_constraints r ON r.constraint_name=a.constraint_name
        JOIN user_constraints p ON p.constraint_name=r.r_constraint_name
        WHERE r.constraint_type='R' AND p.table_name='PEOPLE'""")
    demand(all(r["table_name"] in PERSON_CHILDREN | set(REQUEST_TABLES) and r["column_name"] in
               {"PERSON_ID", "REQUEST_SOURCE_PERSON_ID", "RESPONSIBLE_CAPTAIN_ID", "RECIPIENT_PERSON_ID"} for r in refs),
           "An additional person-ID consumer needs migration review.")
    read_catalog(c, additions)  # Read-only; never call the older demo loader's mutators.
    for p in saved["PEOPLE"]:
        if p["active_flag"] != "Y":
            continue
        roles = {r["role_code"] for r in saved["APP_USER_ROLES"] if r["person_id"] == p["person_id"] and r["active_flag"] == "Y"}
        demand(len(roles) == 1 and roles <= {"POD_CAPTAIN", "POD_LEAD", "POD_MEMBER", "SYSTEM_ADMINISTRATOR"},
               "Every account needs one unambiguous current role.")
        effective = rows(c, """SELECT DISTINCT role_code FROM app_user_roles WHERE person_id=:id AND active_flag='Y'
            AND effective_from<=TRUNC(SYSDATE) AND (effective_to IS NULL OR effective_to>=TRUNC(SYSDATE))""", id=p["person_id"])
        demand({r['role_code'] for r in effective} == roles, "Resolve expired or future-only role grants before account loading.")
        demand(sum(r['person_id'] == p['person_id'] and r['active_flag'] == 'Y' for r in saved['APP_USER_ROLES']) == 1,
               "Duplicate active role grants need review before account loading.")
        capacity_inputs(c, p['person_id'], manifest.anchor, manifest.anchor + timedelta(days=62))
    return saved, chosen, additions


def profile_fingerprints(saved, mapping=None):
    mapping = mapping or {}
    return {mapping.get(p["person_id"], p["person_id"]): digest({
        "experience": p["deliverable_experience_json"],
        "skills": sorted(canonical({k: v for k, v in r.items() if k != "person_id"})
                         for r in saved["PERSON_INTERESTS"] if r["person_id"] == p["person_id"]),
    }) for p in saved["PEOPLE"]}


def preview(c, manifest):
    saved, chosen, added = preflight(c, manifest)
    return {"writes": 0, "batch_id": manifest.batch_id, "archive_request_ids": manifest.archive_request_ids,
            "archive_counts": {t: len(r) for t, r in chosen.items()}, "person_id_map": manifest.person_id_map,
            "added_people": [{"person_id": p.person_id, "name": p.full_name, "role": p.role_code,
                              "login_email": manifest.account_emails[p.person_id]} for p in added.people],
            "account_count": len(manifest.account_emails), "protected_tables": fingerprints({t: saved[t] for t in PROTECTED}),
            "catalogue_changes": 0, "existing_assessment_changes": 0, "model_calls": 0, "emails_sent": 0}


def sql(c, text, **binds):
    execute(c, text, binds)


def guard_fingerprints(c):
    result = {}
    for guard in RESTORE_GUARDS:
        source = rows(c, "SELECT text FROM user_source WHERE name=:name AND type='TRIGGER' ORDER BY line", name=guard)
        state = rows(c, "SELECT status FROM user_triggers WHERE trigger_name=:name", name=guard)
        demand(source and len(state) == 1, "Missing maintenance trigger.")
        result[guard] = {"sha256": digest([r["text"] for r in source]), "status": state[0]["status"]}
    return result


def archive_snapshot(c, manifest, saved, guards, operator):
    metadata = {"protected": fingerprints({t: saved[t] for t in PROTECTED}),
                "profiles": profile_fingerprints(saved, manifest.person_id_map), "guards": guards,
                "manifest": manifest.model_dump(mode="json"), "archive": fingerprints({t: saved[t] for t in SNAPSHOT_TABLES})}
    import oracledb
    for table in SNAPSHOT_TABLES:
        entries = [{"batch": manifest.batch_id, "tableName": table, "rowKey": digest(row), "rowJson": canonical(row), "operatorName": operator} for row in saved[table]]
        with c.cursor() as cursor:
            cursor.setinputsizes(rowJson=oracledb.DB_TYPE_CLOB)
            for offset in range(0, len(entries), 100):
                cursor.executemany("""INSERT INTO mvp_p1_archive(batch_id,table_name,row_key,row_json,operator_name)
                    VALUES(:batch,:tableName,:rowKey,:rowJson,:operatorName)""", entries[offset:offset+100])
        progress(f"Archived {table}: {len(entries)} rows")
    execute(c, """INSERT INTO mvp_p1_runs(batch_id,manifest_hash,status,metadata_json,operator_name)
        VALUES(:batch,:hash,'PREPARED',:metadata,:operatorName)""",
        {"batch": manifest.batch_id, "hash": digest(manifest.model_dump(mode="json")), "metadata": canonical(metadata), "operatorName": operator}, ("metadata",))
    c.commit()  # Explicit durable archive BEFORE any DDL or business DML.
    return metadata


def verify_archive(c, batch, metadata):
    archived = {t: [] for t in SNAPSHOT_TABLES}
    for row in rows(c, "SELECT table_name,row_key,row_json FROM mvp_p1_archive WHERE batch_id=:batch", batch=batch):
        value = document(row["row_json"])
        demand(row["table_name"] in archived and digest(value) == row["row_key"], "Archive fingerprint mismatch.")
        archived[row["table_name"]].append(value)
    demand(fingerprints(archived) == metadata["archive"], "Archive is incomplete or changed.")
    return archived


def archive_requests(c, manifest):
    for request_id in manifest.archive_request_ids:
        for table in REQUEST_TABLES:
            predicate = {
                "ASSIGNMENT_DAYS": "assignment_id IN (SELECT assignment_id FROM pod_assignments WHERE request_id=:id)",
                "POD_PROPOSAL_MEMBERS": "proposal_id IN (SELECT proposal_id FROM pod_proposals WHERE request_id=:id)",
                "AGENT_EXECUTION_EVENTS": "execution_id IN (SELECT execution_id FROM agent_executions WHERE request_id=:id)",
            }.get(table, "request_id=:id")
            sql(c, f"DELETE FROM {table} WHERE {predicate}", id=request_id)


def person_copy_columns(c):
    # VIRTUAL_COLUMN is in USER_TAB_COLS, not USER_TAB_COLUMNS. Keep stored
    # user columns (including user-created invisible ones), not generated internals.
    columns = [r['column_name'] for r in rows(c, """SELECT column_name FROM user_tab_cols
        WHERE table_name='PEOPLE' AND virtual_column='NO' AND user_generated='YES' ORDER BY column_id""")]
    demand('PERSON_ID' in columns and all(re.fullmatch(r'[A-Z][A-Z0-9_]*', name) for name in columns),
           'PEOPLE copy columns could not be verified before ID normalization.')
    return columns


def rename_people(c, manifest):
    columns = person_copy_columns(c)
    for old, new in manifest.person_id_map.items():
        progress(f'Relinking {old} -> {new}')
        demand(not rows(c, "SELECT person_id FROM app_accounts WHERE person_id=:id", id=old), "Normalize IDs before loading accounts.")
        original = rows(c, "SELECT email_address,external_identity_subject FROM people WHERE person_id=:id", id=old)[0]
        # The replacement parent must exist before relinking immediate FKs. Release
        # unique identity fields only within this transaction, then move them intact.
        sql(c, "UPDATE people SET email_address=NULL,external_identity_subject=NULL WHERE person_id=:id", id=old)
        projection = [":newId" if name == "PERSON_ID" else name for name in columns]
        sql(c, f"INSERT INTO people({','.join(columns)}) SELECT {','.join(projection)} FROM people WHERE person_id=:oldId", newId=new, oldId=old)
        for table in sorted(PERSON_CHILDREN - {"APP_ACCOUNTS"}):
            sql(c, f"UPDATE {table} SET person_id=:newId WHERE person_id=:oldId", newId=new, oldId=old)
        sql(c, "DELETE FROM people WHERE person_id=:id", id=old)
        sql(c, "UPDATE people SET email_address=:email,external_identity_subject=:subject WHERE person_id=:id", id=new, email=original["email_address"], subject=original["external_identity_subject"])
        # ID relinking triggers version increments; preserve the actual capacity inputs,
        # but make their availability revision agree with the renamed parent.
        sql(c, """UPDATE person_capacity_days SET availability_version=(SELECT availability_version FROM people WHERE person_id=:id)
            WHERE person_id=:id""", id=new)


def insert_people(c, manifest, added, operator):
    skills, catalogue = read_catalog(c, added)
    for p in added.people:
        experience = [{"deliverableId": catalogue[(e.project_type, e.deliverable_name)]["deliverable_id"],
                       "experienceLevel": e.experience_level, "contributionScope": e.contribution_scope,
                       "interested": e.interested, "experience": e.experience} for e in p.deliverables]
        execute(c, """INSERT INTO people(person_id,full_name,initials,job_title,location,weekly_work_hours,email_address,
            allocation_pct,active_pods,active_flag,staffing_eligible_flag,skills_version,deliverable_experience_json,staffing_seed_batch)
            VALUES(:id,:name,:initials,:title,:location,:hours,:email,0,0,'Y',:eligible,1,:experience,:batch)""",
            {"id": p.person_id, "name": p.full_name, "initials": p.initials, "title": p.job_title, "location": p.location,
             "hours": p.weekly_hours, "email": manifest.account_emails[p.person_id], "eligible": "Y" if p.staffing_eligible else "N",
             "experience": canonical(experience), "batch": manifest.batch_id}, ("experience",))
        for s in p.skills:
            sql(c, """INSERT INTO person_interests(person_id,interest_id,strength,evidence_note,source,interested_flag,updated_by)
                VALUES(:person,:skill,:strength,:evidence,:source,:interested,:operatorName)""", person=p.person_id,
                skill=skills[s.name]["interest_id"], strength=s.strength, evidence=s.evidence, source=manifest.batch_id,
                interested="Y" if s.interested else "N", operatorName=operator)
        # Only new people get generated workload. Existing source events remain untouched.
        for offset in range(63):
            day = manifest.anchor + timedelta(days=offset)
            if day.weekday() < 5 and p.external_weekly_hours:
                sql(c, """INSERT INTO availability(person_id,event_type,starts_on,ends_on,title,allocated_hours,capacity_kind,created_by)
                    VALUES(:person,'External work',:day,:day,'Ongoing business commitments',:hours,'EXTERNAL_WORK',:batch)""",
                    person=p.person_id, day=day, hours=p.external_weekly_hours / 5, batch=manifest.batch_id)
        # Small, dated absences demonstrate different availability without affecting all profiles.
        if int(p.person_id[2:]) % 4 == 0:
            day = manifest.anchor + timedelta(days=10)
            sql(c, """INSERT INTO availability(person_id,event_type,starts_on,ends_on,title,allocated_hours,capacity_kind,created_by)
                VALUES(:person,'Leave',:day,:day,'Planned leave',4,'NON_AVAILABILITY',:batch)""", person=p.person_id, day=day, batch=manifest.batch_id)


def provision_accounts(c, manifest, saved, added, operator, password):
    old_roles = {manifest.person_id_map.get(p["person_id"], p["person_id"]): sorted({r["role_code"] for r in saved["APP_USER_ROLES"]
                 if r["person_id"] == p["person_id"] and r["active_flag"] == "Y"}) for p in saved["PEOPLE"]}
    old_roles.update({p.person_id: [p.role_code] for p in added.people})
    # Permit reviewed email swaps without transient unique-key collisions.
    for person in manifest.account_emails:
        sql(c, "UPDATE people SET email_address=NULL WHERE person_id=:person", person=person)
    for person, email in manifest.account_emails.items():
        account = "ACC-" + uuid4().hex
        subject = "acct:" + account
        sql(c, """INSERT INTO app_accounts(account_id,person_id,identity_subject,login_email,password_hash,created_by)
            VALUES(:account,:person,:subject,:email,:password,:operatorName)""", account=account, person=person,
            subject=subject, email=email, password=hash_password(password), operatorName=operator)
        sql(c, "UPDATE people SET email_address=:email,external_identity_subject=:subject WHERE person_id=:person", email=email, person=person, subject=subject)
        # Original role grants remain in the archive. Active role codes are unchanged.
        sql(c, "DELETE FROM app_user_roles WHERE person_id=:person", person=person)
        for role in old_roles[person]:
            original_id = next((old for old, new in manifest.person_id_map.items() if new == person), person)
            original_grants = [r for r in saved["APP_USER_ROLES"] if r["person_id"] == original_id and r["role_code"] == role and r["active_flag"] == "Y"]
            demand(len(original_grants) <= 1, "Duplicate active role grants need review.")
            grant = original_grants[0] if original_grants else None
            def stored_day(value):
                return datetime.fromisoformat(value["$datetime"]) if value and "$datetime" in value else date.fromisoformat(value["$date"]) if value else None
            sql(c, """INSERT INTO app_user_roles(identity_subject,role_code,person_id,active_flag,effective_from,assigned_by)
                VALUES(:subject,:role,:person,'Y',NVL(:effectiveFrom,TRUNC(SYSDATE)),:operatorName)""", subject=subject, role=role, person=person,
                effectiveFrom=stored_day(grant['effective_from']) if grant else None, operatorName=operator)
            if grant and grant['effective_to']:
                sql(c, "UPDATE app_user_roles SET effective_to=:day WHERE identity_subject=:subject AND role_code=:role",
                    day=stored_day(grant['effective_to']), subject=subject, role=role)
        progress(f"Account prepared: {person}")


def capacity_inputs(c, person, start, end):
    profile = rows(c, "SELECT weekly_work_hours,availability_version FROM people WHERE person_id=:id", id=person)[0]
    events = rows(c, """SELECT availability_id,capacity_kind,starts_on,ends_on,allocated_hours FROM availability
        WHERE person_id=:id AND starts_on<=:endDay AND ends_on>=:startDay""", id=person, startDay=start, endDay=end)
    days = build_days(profile["weekly_work_hours"], start, end, events)
    existing = rows(c, """SELECT work_date,available_hours,external_committed_hours FROM person_capacity_days
        WHERE person_id=:id AND work_date BETWEEN :startDay AND :endDay""", id=person, startDay=start, endDay=end)
    # Check in the read-only preview too, before any archive or guard maintenance.
    for d in existing:
        value = days[d["work_date"].date() if isinstance(d["work_date"], datetime) else d["work_date"]]
        demand(Decimal(str(d["available_hours"])) >= value["available"] and Decimal(str(d["external_committed_hours"])) <= value["external"],
               "Existing capacity has extra commitments: reconcile those inputs before applying.")
    return profile, events, days


def refresh_derived_capacity(c, manifest, operator):
    for person in manifest.account_emails:
        profile, events, days = capacity_inputs(c, person, manifest.anchor, manifest.anchor + timedelta(days=62))
        for day, value in days.items():
            execute(c, """MERGE INTO person_capacity_days d USING(SELECT :person person_id,:day work_date FROM dual) s
                ON(d.person_id=s.person_id AND d.work_date=s.work_date)
                WHEN MATCHED THEN UPDATE SET available_hours=:hours,external_committed_hours=:external,
                    availability_version=:version,input_refs_json=:refs,source_version=:batch,verified_by=:operatorName,verified_at=SYSTIMESTAMP
                WHEN NOT MATCHED THEN INSERT(person_id,work_date,available_hours,external_committed_hours,availability_version,
                    input_refs_json,source_version,verified_by,verified_at)
                    VALUES(:person,:day,:hours,:external,:version,:refs,:batch,:operatorName,SYSTIMESTAMP)""",
                {"person": person, "day": day, "hours": value["available"], "external": value["external"], "version": profile["availability_version"],
                 "refs": canonical({"availability_ids": [e["availability_id"] for e in events], "method": "Mon-Fri equal event hours"}),
                 "batch": manifest.batch_id, "operatorName": operator}, ("refs",))


def check_preservation(c, saved, manifest):
    after = snapshot(c)
    demand(fingerprints({t: saved[t] for t in PROTECTED}) == fingerprints({t: after[t] for t in PROTECTED}),
           "Protected catalogue/policy content changed. Rolling back.", "MVP_PROTECTED_CHANGE")
    expected = profile_fingerprints(saved, manifest.person_id_map)
    actual = profile_fingerprints(after)
    demand(all(actual.get(k) == v for k, v in expected.items()), "Existing assessments changed. Rolling back.", "MVP_PROTECTED_CHANGE")
    # Source availability is preserved exactly, except its foreign-key relink.
    expected_events = [{**r, "person_id": manifest.person_id_map.get(r["person_id"], r["person_id"])} for r in saved["AVAILABILITY"]]
    demand(all(r in after["AVAILABILITY"] for r in expected_events), "Existing availability changed. Rolling back.", "MVP_PROTECTED_CHANGE")
    for person in saved['PEOPLE']:
        current_id = manifest.person_id_map.get(person['person_id'], person['person_id'])
        if current_id in manifest.account_emails:
            previous_roles = {r['role_code'] for r in saved['APP_USER_ROLES'] if r['person_id'] == person['person_id'] and r['active_flag'] == 'Y'}
            new_roles = {r['role_code'] for r in after['APP_USER_ROLES'] if r['person_id'] == current_id and r['active_flag'] == 'Y'}
            demand(previous_roles == new_roles, 'An existing role changed. Rolling back.', 'MVP_PROTECTED_CHANGE')
    check_account_links(c, after, manifest)
    return after


def check_account_links(c, current, manifest):
    accounts = rows(c, 'SELECT account_id,person_id,identity_subject,login_email,active_flag FROM app_accounts')
    demand(len(accounts) == len(manifest.account_emails) and {a['person_id'] for a in accounts} == set(manifest.account_emails), 'Imported account roster is incomplete.')
    people = {p['person_id']: p for p in current['PEOPLE']}
    for account in accounts:
        person = people.get(account['person_id'])
        demand(person and person['active_flag'] == 'Y' and account['active_flag'] == 'Y'
               and person['external_identity_subject'] == account['identity_subject']
               and person['email_address'] == account['login_email'] == manifest.account_emails[account['person_id']],
               'Account and employee identity mapping do not agree.')
        grants = [r for r in current['APP_USER_ROLES'] if r['person_id'] == account['person_id'] and r['active_flag'] == 'Y']
        demand(len(grants) == 1 and grants[0]['identity_subject'] == account['identity_subject'], 'Account role mapping is incomplete or ambiguous.')
    return len(accounts)


def recover_guards(c, batch):
    require_schema(c)
    require_stopped(c)
    run = rows(c, "SELECT metadata_json FROM mvp_p1_runs WHERE batch_id=:batch", batch=batch)
    demand(len(run) == 1, "Unknown maintenance batch.")
    original = document(run[0]["metadata_json"])["guards"]
    current = guard_fingerprints(c)
    for name in RESTORE_GUARDS:
        demand(current[name]["sha256"] == original[name]["sha256"], "Trigger definition changed. Manual recovery review required.")
    enable_guards(c, RESTORE_GUARDS)
    return {"guards_restored": True, "business_data_changed": False}


def enable_guards(c, names):
    failed = []
    for name in names:
        try:
            sql(c, f"ALTER TRIGGER {name} ENABLE")
        except Exception:
            failed.append(name)
    demand(not failed, "Keep writers stopped and run recover-guards; guard restoration was incomplete.", "MVP_GUARD_RECOVERY")


def apply(c, manifest, operator, password):
    require_schema(c)
    require_stopped(c)
    runs = rows(c, "SELECT status,manifest_hash,metadata_json FROM mvp_p1_runs WHERE batch_id=:batch", batch=manifest.batch_id)
    if runs and runs[0]["status"] == "APPLIED":
        demand(runs[0]["manifest_hash"] == digest(manifest.model_dump(mode="json")), "Batch already used for another manifest.")
        advance_sequence(c)
        return {"already_applied": True, **verify(c, manifest.batch_id)}
    demand(not runs or runs[0]['status'] == 'PREPARED', 'This batch was restored. Generate a new batch ID for another migration.')
    demand(not rows(c, "SELECT account_id FROM app_accounts"), "Accounts already exist. This initial migration never resets their passwords.")
    saved, chosen, added = preflight(c, manifest)
    guards = guard_fingerprints(c)
    demand(all(g["status"] == "ENABLED" for g in guards.values()), "Run recover-guards for the interrupted batch before retrying.")
    if runs:
        demand(runs[0]["manifest_hash"] == digest(manifest.model_dump(mode="json")), "Prepared manifest differs; inspect the retained archive.")
        metadata = document(runs[0]["metadata_json"])
    else:
        metadata = archive_snapshot(c, manifest, saved, guards, operator)
    demand(8 <= len(password) <= 1024, "Configure STAFFING_MVP_DEFAULT_PASSWORD (8–1024 characters) before apply.")
    demand(guards == metadata['guards'], 'Maintenance trigger definitions changed since the archive was prepared.')
    verify_archive(c, manifest.batch_id, metadata)
    try:
        progress("Entering stopped-service maintenance; preserving trigger definitions")
        for guard in GUARDS:
            sql(c, f"ALTER TRIGGER {guard} DISABLE")
        for table in sorted((*PROTECTED, *SNAPSHOT_TABLES, "APP_ACCOUNTS", "APP_SESSIONS")):
            sql(c, f"LOCK TABLE {table} IN EXCLUSIVE MODE NOWAIT")
        require_stopped(c)
        demand(snapshot_hash(snapshot(c)) == manifest.expected_snapshot, "Data changed while preparing maintenance.", "MVP_STALE_MANIFEST")
        progress("Removing only manifest-listed archived requests")
        archive_requests(c, manifest)
        progress("Relinking person IDs; retaining assessments and source availability")
        rename_people(c, manifest)
        progress("Adding new people, skills and dated commitments")
        insert_people(c, manifest, added, operator)
        provision_accounts(c, manifest, saved, added, operator, password)
        progress("Recalculating dated capacity from preserved source events")
        refresh_derived_capacity(c, manifest, operator)
        progress("Checking protected records before commit")
        after = check_preservation(c, saved, manifest)
        metadata["after_snapshot"] = snapshot_hash(after)
        metadata["account_ids"] = sorted(r['account_id'] for r in rows(c, "SELECT account_id FROM app_accounts"))
        metadata["archive_counts"] = {t: len(v) for t, v in chosen.items()}
        execute(c, "UPDATE mvp_p1_runs SET status='APPLIED',metadata_json=:metadata WHERE batch_id=:batch",
                {"batch": manifest.batch_id, "metadata": canonical(metadata)}, ("metadata",))
        c.commit()
    except BaseException:
        c.rollback()
        raise
    finally:
        # No business DML remains pending when Oracle implicitly commits these DDLs.
        enable_guards(c, GUARDS)
    advance_sequence(c)
    return {"committed": True, **verify(c, manifest.batch_id)}


def advance_sequence(c):
    # Sequence changes are non-transactional; never rewind. Only advance if needed.
    maximum = rows(c, "SELECT NVL(MAX(TO_NUMBER(SUBSTR(person_id,3))),0) n FROM people WHERE REGEXP_LIKE(person_id,'^P-[0-9]+$')")[0]['n']
    sequence = rows(c, "SELECT last_number,increment_by,cache_size,cycle_flag FROM user_sequences WHERE sequence_name='PERSON_ID_SEQ'")
    demand(len(sequence) == 1 and sequence[0]["increment_by"] == 1 and sequence[0]["cache_size"] == 0 and sequence[0]["cycle_flag"] == "N", "Review person sequence before restarting services.")
    if sequence[0]['last_number'] <= maximum:
        # Oracle 19c+ forward-only restart, after business commit and with writers
        # stopped. Avoid hundreds of thousands of NOCACHE NEXTVAL calls on restore.
        # Never issue a bare RESTART, rewind, or temporarily alter INCREMENT BY.
        sql(c, f'ALTER SEQUENCE person_id_seq RESTART START WITH {int(maximum) + 1}')


def verify(c, batch):
    require_schema(c)
    run = rows(c, "SELECT status,metadata_json FROM mvp_p1_runs WHERE batch_id=:batch", batch=batch)
    demand(len(run) == 1 and run[0]["status"] == "APPLIED", "The batch has not been applied.")
    metadata = document(run[0]["metadata_json"])
    verify_archive(c, batch, metadata)
    current = snapshot(c)
    demand(metadata["protected"] == fingerprints({t: current[t] for t in PROTECTED}), "Protected data differs from the pre-migration snapshot.")
    profiles = profile_fingerprints(current)
    preserved = all(profiles.get(k) == v for k, v in metadata["profiles"].items())
    maximum = max((int(r['person_id'][2:]) for r in current['PEOPLE'] if re.fullmatch(r'P-\d+', r['person_id'])), default=0)
    sequence = rows(c, "SELECT last_number,increment_by,cache_size,cycle_flag FROM user_sequences WHERE sequence_name='PERSON_ID_SEQ'")
    demand(len(sequence) == 1 and sequence[0]['last_number'] > maximum and sequence[0]['increment_by'] == 1
           and sequence[0]['cache_size'] == 0 and sequence[0]['cycle_flag'] == 'N', 'Person sequence must be advanced before restart; rerun apply with the same manifest.')
    manifest = Manifest.model_validate(metadata['manifest'])
    demand(not set(manifest.archive_request_ids) & {r['request_id'] for r in current['REQUESTS']}, 'An archived request ID reappeared.')
    demand(not set(manifest.person_id_map) & {r['person_id'] for r in current['PEOPLE']}, 'An old person ID reappeared.')
    account_count = check_account_links(c, current, manifest)
    guards = guard_fingerprints(c)
    demand(all(v["status"] == "ENABLED" and v["sha256"] == metadata["guards"][k]["sha256"] for k, v in guards.items()), "Maintenance guards need recovery.")
    return {"verified": True, "batch_id": batch, "protected_tables_unchanged": True,
            "existing_assessments_match_import_snapshot": preserved, "people": len(current["PEOPLE"]),
            "accounts": account_count,
            "roles": rows(c, "SELECT role_code,COUNT(*) count FROM app_user_roles WHERE active_flag='Y' GROUP BY role_code"),
            "requests_remaining": len(current["REQUESTS"]), "model_calls": 0, "emails_sent": 0}


def insert_record(c, table, record, *, update_person=False):
    demand(table in SNAPSHOT_TABLES, 'Restore table not allowlisted.')
    demand(not update_person or table == 'PEOPLE', 'Only restored people may use the update path.')
    values = unpacked(record)
    demand(all(re.fullmatch(r'[a-z_][a-z0-9_]*', k) for k in values), 'Invalid archived column name.')
    columns = column_types(c, table)
    demand(set(values) == set(columns), 'Archived columns no longer match the table.')
    expressions, clobs = {}, []
    for name, kind in columns.items():
        fmt = timestamp_format(kind)
        function = 'TO_TIMESTAMP_TZ' if 'WITH TIME ZONE' in kind else 'TO_TIMESTAMP'
        expressions[name] = f"{function}(:{name},'{fmt}')" if fmt else ':' + name
        if kind == 'CLOB':
            clobs.append(name)
            if isinstance(values[name], (dict, list)):
                values[name] = canonical(values[name])
    if update_person:
        query = f"UPDATE people SET {','.join(f'{k}={expressions[k]}' for k in values if k != 'person_id')} WHERE person_id=:person_id"
    else:
        query = f"INSERT INTO {table}({','.join(values)}) VALUES({','.join(expressions[k] for k in values)})"
    execute(c, query, values, tuple(clobs))


def restore(c, batch, commit=False):
    require_schema(c)
    require_stopped(c)
    run = rows(c, "SELECT status,metadata_json FROM mvp_p1_runs WHERE batch_id=:batch", batch=batch)
    demand(len(run) == 1 and run[0]['status'] in ('APPLIED', 'RESTORED'), 'Restore requires one applied batch.')
    metadata = document(run[0]['metadata_json'])
    saved = verify_archive(c, batch, metadata)
    manifest = Manifest.model_validate(metadata['manifest'])
    if run[0]['status'] == 'RESTORED':
        demand(snapshot_hash(snapshot(c)) == manifest.expected_snapshot, 'Data changed since restoration; reviewed recovery required.')
        demand(not rows(c, 'SELECT account_id FROM app_accounts'), 'Accounts were added since restoration; reviewed recovery required.')
        demand(guard_fingerprints(c) == metadata['guards'], 'Recover or inspect maintenance guards before restarting.')
        if commit:
            advance_sequence(c)
        return {'already_restored': True, 'batch_id': batch, 'archives_preserved': True, 'business_writes': 0,
                'sequence_checked': commit}
    demand(snapshot_hash(snapshot(c)) == metadata['after_snapshot'],
           'Business data changed after migration. Automated restore stopped; use the archive for a reviewed recovery.')
    account_ids = sorted(r['account_id'] for r in rows(c, 'SELECT account_id FROM app_accounts'))
    demand(account_ids == metadata['account_ids'], 'Account roster changed after migration; reviewed recovery required.')
    demand(guard_fingerprints(c) == metadata['guards'], 'Recover or inspect maintenance guards before restoration.')
    if not commit:
        return {'writes': 0, 'batch_id': batch, 'restore_ready': True, 'accounts_to_remove': len(account_ids),
                'archived_requests_to_restore': list(manifest.archive_request_ids)}
    original_ids = {r['person_id'] for r in saved['PEOPLE']}
    added_ids = {r['person_id'] for r in rows(c, 'SELECT person_id FROM people')} - original_ids
    try:
        for guard in RESTORE_GUARDS:
            sql(c, f'ALTER TRIGGER {guard} DISABLE')
        for table in sorted((*PROTECTED, *SNAPSHOT_TABLES, 'APP_ACCOUNTS', 'APP_SESSIONS')):
            sql(c, f'LOCK TABLE {table} IN EXCLUSIVE MODE NOWAIT')
        require_stopped(c)
        demand(snapshot_hash(snapshot(c)) == metadata['after_snapshot'], 'Data changed while preparing restore.')
        for account in account_ids:
            sql(c, 'DELETE FROM app_sessions WHERE account_id=:id', id=account)
            sql(c, 'DELETE FROM app_accounts WHERE account_id=:id', id=account)
        # These tables changed for the initial account/ID import. The strict full
        # after-snapshot gate above prohibits deleting later user work.
        for table in ('PERSON_INTERESTS', 'PERSON_CAPACITY_DAYS', 'AVAILABILITY', 'APP_USER_ROLES'):
            for person in rows(c, 'SELECT person_id FROM people'):
                sql(c, f'DELETE FROM {table} WHERE person_id=:id', id=person['person_id'])
        for person in rows(c, 'SELECT person_id FROM people'):
            sql(c, 'UPDATE people SET email_address=NULL,external_identity_subject=NULL WHERE person_id=:id', id=person['person_id'])
        current_ids = {r['person_id'] for r in rows(c, 'SELECT person_id FROM people')}
        for person in saved['PEOPLE']:
            if person['person_id'] not in current_ids:
                insert_record(c, 'PEOPLE', person)
        for person in added_ids:
            sql(c, 'DELETE FROM people WHERE person_id=:id', id=person)
        for table in ('PERSON_INTERESTS', 'AVAILABILITY', 'APP_USER_ROLES', 'PERSON_CAPACITY_DAYS'):
            for row in saved[table]:
                insert_record(c, table, row)
        archived = selected_request_rows(saved, manifest.archive_request_ids)
        for table in ('REQUESTS', 'REQUIREMENTS', 'RECOMMENDATIONS', 'AGENT_EXECUTIONS', 'AGENT_EXECUTION_EVENTS',
                      'POD_PROPOSALS', 'POD_PROPOSAL_MEMBERS', 'APPROVAL_DECISIONS', 'POD_ASSIGNMENTS', 'ASSIGNMENT_DAYS', 'NOTIFICATION_OUTBOX'):
            for row in archived[table]:
                insert_record(c, table, row)
        # Restore original parent versions last, after normal child triggers fired.
        for record in saved['PEOPLE']:
            insert_record(c, 'PEOPLE', record, update_person=True)
        demand(snapshot_hash(snapshot(c)) == manifest.expected_snapshot, 'Restore content verification failed; rolled back.')
        sql(c, "UPDATE mvp_p1_runs SET status='RESTORED' WHERE batch_id=:batch", batch=batch)
        c.commit()
    except BaseException:
        c.rollback()
        raise
    finally:
        enable_guards(c, RESTORE_GUARDS)
    advance_sequence(c)
    return {'restored': True, 'batch_id': batch, 'archives_preserved': True,
            'note': 'Restore the previous auth configuration before restarting services. Sequences were not rewound.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("template", "preview", "apply", "verify", "restore", "recover-guards", "export-archive"))
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--manifest")
    parser.add_argument("--out")
    parser.add_argument("--anchor", type=date.fromisoformat)
    parser.add_argument("--operator")
    parser.add_argument("--batch")
    parser.add_argument("--services-stopped", action="store_true")
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()
    if args.command in ("apply", "restore", "recover-guards") and not args.services_stopped:
        parser.error("Stop all local/VM writers and pass --services-stopped.")
    if args.command == "apply" and (not args.operator or not args.operator.strip() or len(args.operator) > 255):
        parser.error("Provide --operator.")
    from app.config import Settings
    from app.database import OracleDatabase
    settings = Settings(_env_file=args.env_file)
    database = OracleDatabase(settings)
    try:
        manifest = Manifest.model_validate_json(Path(args.manifest).read_text(encoding="utf-8-sig")) if args.manifest else None
        mutating = args.command == "recover-guards" or args.command in ('apply', 'restore') and args.commit
        # The database write context checks schema and rolls back failed DML. apply()
        # deliberately manages the archive/guard DDL boundaries described above.
        with (database.write() if mutating else database.read()) as c:
            if args.command == "template":
                anchor = args.anchor or date.today() - timedelta(days=date.today().weekday())
                result = make_template(c, anchor).model_dump(mode="json")
            elif args.command in ("preview", "apply"):
                demand(manifest is not None, "Provide --manifest.")
                if args.command == "apply" and args.commit:
                    demand(bool(settings.staffing_mvp_default_password), "Set STAFFING_MVP_DEFAULT_PASSWORD in the Python env file.")
                    result = apply(c, manifest, args.operator, settings.staffing_mvp_default_password.get_secret_value())
                else:
                    result = preview(c, manifest)
            elif args.command == "verify":
                result = verify(c, args.batch)
            elif args.command == "recover-guards":
                result = recover_guards(c, args.batch)
            elif args.command == 'restore':
                result = restore(c, args.batch, args.commit)
            else:
                require_schema(c)
                result = [dict(table=r["table_name"], row=document(r["row_json"])) for r in rows(c,
                          "SELECT table_name,row_json FROM mvp_p1_archive WHERE batch_id=:batch ORDER BY table_name,row_key", batch=args.batch)]
        output = json.dumps(result, indent=2, default=str)
        if args.out:
            with Path(args.out).open("x", encoding="utf-8") as file:
                file.write(output + "\n")
            print(json.dumps({"written": str(Path(args.out).resolve())}))
        else:
            print(output)
    except ServiceError as error:
        print(json.dumps({"error": error.code, "message": error.message, "archives_preserved": True, **driver_error_details(error)}))
        raise SystemExit(1) from None
    except Exception as error:
        print(json.dumps({"error": "MVP_OPERATION_FAILED", "type": type(error).__name__,
                          "message": "Inspect preview/verify before retrying. Archives are retained; recover-guards restores an interrupted guard change.",
                          **driver_error_details(error)}))
        raise SystemExit(1) from None
    finally:
        database.close()


if __name__ == "__main__":
    main()
