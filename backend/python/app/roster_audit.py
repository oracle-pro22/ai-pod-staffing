"""Read-only real-roster preflight. No apply, archive, reset or account creation path.

The XLSX adapter uses only the Python standard library so this audit is runnable
on the VM as well as Windows. It reads cell values, never formulas or macros.
OracleDatabase.read enforces a single READ ONLY transaction. Reports contain
account identifiers but never passwords, password hashes or session tokens.
"""
import argparse
import hashlib
import io
import json
import posixpath
import re
import sys
import zipfile
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET

from app.accounts import normalize_email
from app.errors import ServiceError
from app.storage import rows

ROLES = ("SYSTEM_ADMINISTRATOR", "POD_CAPTAIN", "POD_LEAD", "POD_MEMBER")
ROLE_COLUMNS = {"Admin": ROLES[0], "POD Captain": ROLES[1], "Pod Lead": ROLES[2], "Pod Member": ROLES[3]}
HEADERS = ("Manager", "Name", "Email", *ROLE_COLUMNS, "Grant Tool Access")
ARCHIVE_TABLES = (
    "ROSTER_POD_CLAIMS", "ROSTER_ONBOARDING",
    "APP_SESSIONS", "APP_ACCOUNTS", "APP_USER_ROLES", "PERSON_INTERESTS", "AVAILABILITY",
    "PERSON_CAPACITY_DAYS", "PEOPLE", "REQUESTS", "REQUIREMENTS", "RECOMMENDATIONS",
    "AGENT_EXECUTIONS", "AGENT_EXECUTION_EVENTS", "POD_PROPOSALS", "POD_PROPOSAL_MEMBERS",
    "APPROVAL_DECISIONS", "POD_ASSIGNMENTS", "ASSIGNMENT_DAYS", "NOTIFICATION_OUTBOX",
    "AUDIT_EVENTS", "MVP_P2_REVIEWS", "MVP_P2_SELECTIONS", "MVP_P2_DECISIONS",
    "MVP_P3_DRAFTS", "MVP_P3_RESOLUTIONS",
)
PROTECTED_TABLES = (
    "ROSTER_ACCESS_CONTROL",
    "PROJECT_TYPES", "DELIVERABLES", "DELIVERABLE_SKILLS", "INTERESTS", "CUSTOMER_MAPPING",
    "APP_ROLES", "ROLE_PERMISSIONS", "STAFFING_POLICIES", "ELIGIBILITY_RULES",
    "LOAD_GUARDRAILS", "SCORING_WEIGHTS", "STAFFING_RUNTIME", "STAFFING_POLICY_CONTROL",
)
# Previous backups are retained, never reset or treated as active application data.
BACKUP_PREFIXES = ("AIPS_", "MVP_P1_", "MVP_P3_DDL_", "ROSTER_", "R4B_", "R4T_")
# Tool-owned SQL execution history is outside the application reset. Do not read
# its contents: those records can contain SQL or credentials from other work.
RETAINED_UTILITY_TABLES = {"DBTOOLS$EXECUTION_HISTORY", "RM2_DDL_BACKUP"}
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def demand(condition, message):
    if not condition:
        raise ServiceError("ROSTER_AUDIT_INVALID", message, 409)


def serializable(value):
    if hasattr(value, "read"):
        return serializable(value.read())
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return {"decimal": str(value)}
    if isinstance(value, bytes):
        return {"hex": value.hex()}
    if isinstance(value, dict):
        return {str(k): serializable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [serializable(v) for v in value]
    return value


def canonical(value):
    return json.dumps(serializable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def read_workbook(path):
    """Strict, bounded source-value extraction. Tester cells are deliberately unused."""
    path = Path(path)
    demand(path.suffix.lower() == ".xlsx", "Provide the original .xlsx roster workbook.")
    demand(path.stat().st_size <= 10_000_000, "Roster workbook exceeds the 10 MB input limit.")
    content = path.read_bytes()
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        infos = archive.infolist()
        demand(len({i.filename for i in infos}) == len(infos), "Duplicate workbook ZIP entries are ambiguous.")
        demand(sum(i.file_size for i in infos) <= 40_000_000, "Workbook expanded size exceeds the audit limit.")

        def xml(name):
            data = archive.read(name)
            demand(b"<!DOCTYPE" not in data.upper() and b"<!ENTITY" not in data.upper(), "XML entities are not supported.")
            return ET.fromstring(data)

        workbook = xml("xl/workbook.xml")
        sheet = [s for s in workbook.findall("m:sheets/m:sheet", NS) if s.get("name") == "Team-Role"]
        demand(len(sheet) == 1, "Expected exactly one Team-Role worksheet.")
        relationship = sheet[0].get(f"{{{DOC_REL_NS}}}id")
        targets = [r for r in xml("xl/_rels/workbook.xml.rels").findall(f"{{{REL_NS}}}Relationship")
                   if r.get("Id") == relationship and r.get("TargetMode") != "External"]
        demand(len(targets) == 1, "Team-Role must reference an internal worksheet.")
        target = targets[0].get("Target", "")
        sheet_path = posixpath.normpath(target.lstrip("/") if target.startswith("/") else "xl/" + target)
        demand(sheet_path.startswith("xl/worksheets/") and "\\" not in sheet_path, "Unexpected worksheet path.")
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = ["".join(node.itertext()) for node in xml("xl/sharedStrings.xml").findall("m:si", NS)]
        extracted = []
        for row in xml(sheet_path).findall("m:sheetData/m:row", NS):
            cells = {}
            formula_columns = set()
            for cell in row.findall("m:c", NS):
                ref = cell.get("r", "")
                match = re.fullmatch(r"([A-Z]+)([1-9][0-9]*)", ref)
                demand(match is not None, "A roster cell has an invalid address.")
                col = match[1]
                demand(col not in cells, "Duplicate cells in a roster row.")
                if cell.find("m:f", NS) is not None:
                    formula_columns.add(col)
                node = cell.find("m:v", NS)
                value = node.text if node is not None else ""
                if cell.get("t") == "s":
                    demand(value is not None and value.isdigit() and int(value) < len(strings), "Invalid shared string index.")
                    value = strings[int(value)]
                elif cell.get("t") == "inlineStr":
                    value = "".join(t.text or "" for t in cell.findall("m:is//m:t", NS))
                cells[col] = (value or "").strip()
            extracted.append((int(row.get("r", "0")), cells, formula_columns))
            demand(len(extracted) <= 1001, "Roster audit is limited to 1,000 people.")
    demand(extracted, "The roster is empty.")
    _, first, formulas = extracted[0]
    demand(not formulas and len(set(first.values())) == len(first.values()), "Roster headers must be unique text values.")
    columns = {name: col for col, name in first.items()}
    demand(set(HEADERS) <= set(columns), "Required roster headings are missing.")
    people = []
    for number, cells, formulas in extracted[1:]:
        values = {name: cells.get(columns[name], "") for name in HEADERS}
        if not any(values.values()):
            continue
        demand(not (set(columns[name] for name in HEADERS) & formulas), "Use literal values, not formulas, in roster fields.")
        demand(values["Name"] and values["Manager"], f"Row {number} needs a name and manager.")
        grants = []
        for name, role in ROLE_COLUMNS.items():
            flag = values[name].casefold()
            demand(flag in ("", "yes", "no"), f"Row {number} has an unknown role flag.")
            if flag == "yes":
                grants.append(role)
        demand(grants, f"Row {number} has no role grants.")
        access = values["Grant Tool Access"].casefold()
        demand(access in ("yes", "timing tbd"), f"Row {number} has an unknown access status.")
        people.append({"source_row": number, "name": values["Name"], "manager": values["Manager"],
                       "email": normalize_email(values["Email"]), "roles": grants,
                       "account_enabled": access == "yes", "initial_daily_hours": 8,
                       "initial_weekly_hours": 40, "onboarding_required": True})
    demand(people, "No employees were found.")
    demand(len({p["email"] for p in people}) == len(people), "Duplicate normalized Oracle email addresses.")
    return {"format_version": 1, "source_file": path.name, "source_sha256": hashlib.sha256(content).hexdigest(),
            "sheet": "Team-Role", "tester_ignored": True, "people": people}


def source_summary(source):
    people = source["people"]
    enabled = [p for p in people if p["account_enabled"]]
    return {"accounts": len(people), "enabled": len(enabled), "disabled": len(people) - len(enabled),
            "role_grants": dict(Counter(role for p in people for role in p["roles"])),
            "enabled_role_grants": dict(Counter(role for p in enabled for role in p["roles"])),
            "enabled_display_roles": dict(Counter(next(r for r in ROLES if r in p["roles"]) for p in enabled)),
            "external_manager_names": sorted({p["manager"] for p in people} - {p["name"] for p in people}),
            "initial_daily_hours": 8, "initial_weekly_hours": 40, "tester_ignored": True}


def reconcile(source, people, accounts, grants):
    """Matches are reference evidence only: the approved direction is archive then reset."""
    result = []
    for desired in source["people"]:
        exact = {p["person_id"] for p in people if (p.get("email_address") or "").strip().lower() == desired["email"]}
        exact |= {a["person_id"] for a in accounts if (a.get("login_email") or "").strip().lower() == desired["email"]}
        named = {p["person_id"] for p in people if p["full_name"].strip().casefold() == desired["name"].casefold()}
        ambiguous = len(exact) > 1 or bool(exact and named and exact != named)
        candidates = exact or named
        status = "ambiguous_identity" if ambiguous else (
            "exact_email_reference" if exact else "name_only_review_required" if named else "new_person")
        current_roles = sorted({g["role_code"] for g in grants if g["person_id"] in candidates and g["active_flag"] == "Y"})
        result.append({**desired, "match_status": status, "existing_person_ids": sorted(candidates),
                       "existing_active_roles": current_roles,
                       "roles_to_add": sorted(set(desired["roles"]) - set(current_roles)),
                       "roles_to_remove": sorted(set(current_roles) - set(desired["roles"])),
                       "copy_existing_assessments": False, "reuse_identity_automatically": False})
    matched = {pid for item in result for pid in item["existing_person_ids"]}
    return {"rows": result, "existing_people_not_in_roster": [p for p in people if p["person_id"] not in matched],
            "matching_is_reference_only": True, "strategy": "archive_existing_then_create_roster"}


def archive_order(tables, foreign_keys):
    """Child-first deletion order, for review only; self/circular FKs are blockers."""
    pending = set(tables)
    ordered = []
    edges = {(r["child_table"], r["parent_table"]) for r in foreign_keys
             if r["child_table"] in pending and r["parent_table"] in pending}
    while pending:
        leaves = sorted(t for t in pending if not any(parent == t and child in pending for child, parent in edges))
        if not leaves:
            return ordered, sorted(pending)
        ordered.extend(leaves)
        pending.difference_update(leaves)
    return ordered, []


def protected_fingerprint(connection, table, metadata):
    demand(table in PROTECTED_TABLES, "Fingerprint table is not on the protected allowlist.")
    projection = []
    for column in metadata:
        name, kind = column["column_name"], column["data_type"]
        demand(re.fullmatch(r"[A-Z][A-Z0-9_]*", name), "Unexpected protected column identifier.")
        if kind.startswith("TIMESTAMP"):
            demand("LOCAL TIME ZONE" not in kind, "Local-zone timestamp needs a reviewed fingerprint adapter.")
            fmt = 'YYYY-MM-DD"T"HH24:MI:SS.FF9' + ("TZH:TZM" if "WITH TIME ZONE" in kind else "")
            projection.append(f"TO_CHAR({name},'{fmt}') {name}")
        else:
            projection.append(name)
    demand(projection, "Protected table metadata is missing.")
    row_hashes = []
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT {','.join(projection)} FROM {table}")
        while batch := cursor.fetchmany(500):
            row_hashes.extend(digest(row) for row in batch)
            demand(len(row_hashes) <= 250_000, "Protected fingerprint scan exceeds the reviewed row limit.")
    return {"rows": len(row_hashes), "data_sha256": digest(sorted(row_hashes)), "columns_sha256": digest(metadata)}


def audit_database(connection, source):
    tables = {r["table_name"] for r in rows(connection, "SELECT table_name FROM user_tables")}
    required = {"PEOPLE", "APP_ACCOUNTS", "APP_USER_ROLES", "REQUESTS", "POD_ASSIGNMENTS"}
    demand(required <= tables, "The existing account/assignment schema is incomplete.")
    archive = set(ARCHIVE_TABLES) & tables
    protected = set(PROTECTED_TABLES) & tables
    retained = {t for t in tables - archive - protected if t.startswith(BACKUP_PREFIXES)}
    utilities = tables & RETAINED_UTILITY_TABLES
    unknown = sorted(tables - archive - protected - retained - utilities)
    fks = rows(connection, """SELECT c.constraint_name,c.table_name child_table,
        p.table_name parent_table,c.status,c.validated,c.delete_rule
        FROM user_constraints c JOIN user_constraints p
        ON p.constraint_name=c.r_constraint_name AND c.r_owner=USER
        WHERE c.constraint_type='R' ORDER BY c.table_name,c.constraint_name""")
    cross_refs = [r for r in fks if r["parent_table"] in archive and r["child_table"] not in archive]
    delete_order, cycles = archive_order(archive, fks)
    counts = {t: rows(connection, f"SELECT COUNT(*) n FROM {t}")[0]["n"] for t in sorted(archive | protected)}
    columns = rows(connection, """SELECT table_name,column_name,data_type,data_length,data_precision,
        data_scale,nullable,column_id FROM user_tab_columns ORDER BY table_name,column_id""")
    protected_data = {t: protected_fingerprint(connection, t, [r for r in columns if r["table_name"] == t])
                      for t in sorted(protected)}
    people = rows(connection, "SELECT person_id,full_name,email_address,active_flag FROM people ORDER BY person_id")
    accounts = rows(connection, "SELECT account_id,person_id,login_email,active_flag FROM app_accounts ORDER BY person_id")
    grants = rows(connection, """SELECT ur.person_id,ur.role_code,ur.active_flag,ur.effective_from,ur.effective_to
        FROM app_user_roles ur JOIN app_roles ar ON ar.role_code=ur.role_code AND ar.active_flag='Y'
        WHERE ur.active_flag='Y' AND ur.effective_from<=TRUNC(SYSDATE)
          AND (ur.effective_to IS NULL OR ur.effective_to>=TRUNC(SYSDATE))
        ORDER BY ur.person_id,ur.role_code""")
    assignments = rows(connection, """SELECT a.assignment_id,a.request_id,a.person_id,a.role_in_pod,
        a.assigned_hours,a.status FROM pod_assignments a WHERE a.status='CONFIRMED'
        ORDER BY a.request_id,a.person_id""")
    requests = rows(connection, "SELECT request_id,status FROM requests ORDER BY request_id")
    triggers = rows(connection, "SELECT trigger_name,table_name,status,trigger_type,triggering_event FROM user_triggers ORDER BY trigger_name")
    active_jobs = rows(connection, "SELECT execution_id,request_id,status FROM agent_executions WHERE status IN ('QUEUED','RUNNING')") if "AGENT_EXECUTIONS" in tables else []
    runtime = rows(connection, "SELECT runtime_id,agents_enabled,notifications_enabled FROM staffing_runtime") if "STAFFING_RUNTIME" in tables else []
    active_policy = None
    if "STAFFING_POLICY_CONTROL" in tables:
        from app.policy_admin import active_policy_version
        from app.storage import load_policy
        active_policy = load_policy(connection, active_policy_version(connection)).model_dump(mode="json")
    result = {"format_version": 1, "phase": 1, "mode": "read_only", "database_audited": True,
              "captured_at": datetime.now(timezone.utc).isoformat(), "writes": 0, "model_calls": 0, "emails_sent": 0,
              "source": {k: v for k, v in source.items() if k != "people"}, "target": source_summary(source),
              "reconciliation": reconcile(source, people, accounts, grants),
              "existing_counts": {"people": len(people), "accounts": len(accounts), "requests": len(requests)},
              "request_status_counts": dict(Counter(r["status"] for r in requests)),
              "confirmed_assignments": assignments, "active_jobs": active_jobs, "runtime": runtime,
              "active_policy": active_policy,
              "archive_scope": {t: counts[t] for t in sorted(archive)},
              "protected_fingerprints": protected_data, "retained_prior_backups": sorted(retained),
              "retained_non_application_tables": sorted(utilities),
              "foreign_keys": fks, "proposed_child_first_order": delete_order,
              "archive_triggers": [r for r in triggers if r["table_name"] in archive],
              "schema_columns_sha256": digest(columns),
              "review_blockers": {"unclassified_tables": unknown, "incoming_references_outside_scope": cross_refs,
                                  "cyclic_dependencies": cycles,
                                  "missing_expected_tables": sorted(set(ARCHIVE_TABLES + PROTECTED_TABLES) - tables)},
              "archive_created": False, "recovery_tested": False, "reset_authorized_by_report": False,
              "next_gate": "Review inventory; prepare and verify a separate recovery archive before any reset."}
    result["audit_sha256"] = digest(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", required=True)
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--output", required=True, help="New, local JSON report path; existing reports are never overwritten.")
    parser.add_argument("--offline", action="store_true", help="Validate workbook only; never connects to the database.")
    args = parser.parse_args()
    db = None
    try:
        output = Path(args.output).resolve()
        demand(output.suffix.lower() == ".json" and not output.exists(), "Choose a new .json report path.")
        source = read_workbook(args.workbook)
        if args.offline:
            report = {"format_version": 1, "phase": 1, "mode": "workbook_only", "database_audited": False,
                      "source": source, "target": source_summary(source), "writes": 0, "model_calls": 0,
                      "archive_created": False, "recovery_tested": False, "reset_authorized_by_report": False}
        else:
            from app.config import Settings
            from app.database import OracleDatabase
            db = OracleDatabase(Settings(_env_file=args.env_file))
            with db.read() as connection:
                report = audit_database(connection, source)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as handle:
            json.dump(serializable(report), handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        print(json.dumps({"report": str(output), "database_audited": report["database_audited"],
                          "target": report["target"], "writes": 0, "archive_created": False}))
    except (ServiceError, ValueError, OSError, KeyError, zipfile.BadZipFile, ET.ParseError) as error:
        code = error.code if isinstance(error, ServiceError) else "ROSTER_AUDIT_INPUT"
        message = error.message if isinstance(error, ServiceError) else "Check the workbook, environment and output path; no database changes were made."
        print(json.dumps({"error": code, "message": message, "writes": 0}), file=sys.stderr)
        return 1
    finally:
        if db:
            db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
