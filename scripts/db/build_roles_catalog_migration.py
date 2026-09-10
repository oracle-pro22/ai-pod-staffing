"""Build the reviewed, standalone Oracle migration and its recovery companion.

Only generates local SQL. Never connects to Oracle. Run with the supplied CSV.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MID = "ROLES_CATALOG_20260910_V1"
VERSION = "v260810.r2-20260910"
TABLES = {
    "PROJECT_TYPES": "project_type_id project_name project_description source_version source_row",
    "INTERESTS": "interest_id interest_name category source source_version customer_controlled",
    "CUSTOMER_MAPPING": "projects project_description deliverables skills_type_of_work note source_version source_row customer_controlled",
    "DELIVERABLES": "deliverable_id project_type_id project_name deliverable_name skills_raw customer_note source_version source_row active_flag",
    "DELIVERABLE_SKILLS": "deliverable_id skill_id skill_name source_version source_row",
    "APP_ROLES": "role_code role_name role_description active_flag created_at",
    "ROLE_PERMISSIONS": "role_code resource_code access_scope can_view can_create can_update can_approve can_export can_administer",
    "APP_USER_ROLES": "identity_subject role_code person_id active_flag effective_from effective_to assigned_by assigned_at",
}
KEYS = {
    "PROJECT_TYPES": "project_type_id", "INTERESTS": "interest_id",
    "CUSTOMER_MAPPING": "source_version source_row", "DELIVERABLES": "deliverable_id",
    "DELIVERABLE_SKILLS": "deliverable_id skill_id", "APP_ROLES": "role_code",
    "ROLE_PERMISSIONS": "role_code resource_code", "APP_USER_ROLES": "identity_subject role_code",
}
PROTECTED = ["PEOPLE", "PERSON_INTERESTS", "REQUESTS", "REQUIREMENTS", "RECOMMENDATIONS", "AVAILABILITY"]


def lit(value):
    if value is None or value == "":
        return "NULL"
    if isinstance(value, int):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def q(value):
    assert "~'" not in value
    return "q'~" + value + "~'"


def run(sql):
    return "  EXECUTE IMMEDIATE " + q(sql) + ";\n"


def seed_rows(table):
    sql = (ROOT / "sql/oracle/setup.sql").read_text(encoding="utf-8")
    out = []
    for cols, vals in re.findall(r"INTO " + table + r" \(([^\n]+?)\) VALUES \(([^\n]+)\)", sql):
        tokens = re.findall(r"'(?:''|[^'])*'|NULL|[-+]?\d+(?:\.\d+)?", vals)
        values = [None if t == "NULL" else t[1:-1].replace("''", "'") if t.startswith("'") else int(t) for t in tokens]
        names = [c.strip() for c in cols.split(",")]
        assert len(names) == len(values)
        out.append(dict(zip(names, values)))
    return out


def build(source):
    source_bytes = source.read_bytes()
    sha = hashlib.sha256(source_bytes).hexdigest()
    raw = list(csv.DictReader(source_bytes.decode("utf-8-sig").splitlines()))
    assert list(raw[0]) == ["Projects", "Project Description", "Deliverables", "Skills (Type of work)", "Note"]
    rows = []
    name = desc = ""
    for rownum, r in enumerate(raw, 2):
        if r["Projects"].strip():
            name, desc = r["Projects"].strip(), r["Project Description"].strip()
        if r["Deliverables"].strip():
            rows.append(dict(project=name, description=desc, name=r["Deliverables"].strip(),
                             skills=r["Skills (Type of work)"].strip(), note=r["Note"].strip(), row=rownum))
    baseline = {t: seed_rows(t) for t in ("PROJECT_TYPES", "DELIVERABLES", "INTERESTS", "DELIVERABLE_SKILLS")}
    projects = {r["project_name"]: r["project_type_id"] for r in baseline["PROJECT_TYPES"]}
    projects["Special Projects/ Ad Hoc"] = projects.pop("Special Projects")
    skills = {r["interest_name"]: r["interest_id"] for r in baseline["INTERESTS"]}
    skills["Comms Team"] = "SK-014"
    old = {(r["project_type_id"], r["deliverable_name"]): r for r in baseline["DELIVERABLES"]}
    next_id = 56
    for r in rows:
        r["project_id"] = projects[r["project"]]
        found = old.get((r["project_id"], r["name"]))
        r["id"] = found["deliverable_id"] if found else f"DEL-{next_id:03d}"
        r["new"] = found is None
        next_id += int(found is None)
        r["skill_list"] = [s.strip() for s in r["skills"].split(",") if s.strip()]
    retired = [r for r in baseline["DELIVERABLES"] if r["deliverable_id"] not in {n["id"] for n in rows}]
    assert len(rows) == 73 and len(retired) == 5 and sum(r["new"] for r in rows) == 23
    assert sum(len(r["skill_list"]) for r in rows) == 114
    assert set(s for r in rows for s in r["skill_list"]) == set(skills)
    assert len({(r["project_id"], r["name"]) for r in rows}) == len(rows)
    assert [r["row"] for r in rows if not r["skills"]] == [16]

    header = f"""-- AI Pod Staffing: official profiles and revised customer catalogue
-- Migration: {MID}; source revision: {VERSION}
-- CSV: {source.name}
-- CSV SHA256: {sha}
-- Run this ENTIRE file with F5 in SQL Developer as AI_POD_STAFFING.
-- Stop this application first and use a fresh connection with no pending work.
-- This is a coordinated DB/application release. Keep the old app stopped afterward.
-- Backups: eight AIPS_BK_* tables plus AIPS_MIG_BACKUP, in this schema only.
-- Backup tables are technical recovery objects, NOT governance/business tables.
-- No grants, users, business tables, requests, people or assignments are dropped.
-- skills_raw becomes nullable to preserve the CSV's intentionally unspecified value.
-- Unresolved active/future Executive assignments or conflicting role mappings STOP.
-- All business DML is one transaction. Oracle DDL commits separately.
-- Recovery: rollback_roles_catalog.sql (only before later edits; guarded).
SET DEFINE OFF
SET SERVEROUTPUT ON SIZE UNLIMITED
SET SQLBLANKLINES ON
SET FEEDBACK ON
SET VERIFY OFF
SET AUTOCOMMIT OFF
WHENEVER OSERROR EXIT FAILURE ROLLBACK
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK
"""

    # All checks and backup creation live inside one block so SQL Developer cannot
    # accidentally continue with a later mutation block after a pre-flight error.
    common = """DECLARE
  l_n NUMBER;
  l_state VARCHAR2(30);
  l_original_active CHAR(1);
  l_original_nullable CHAR(1);
  l_before CLOB;
  l_now CLOB;
  l_sql VARCHAR2(32767);

  PROCEDURE demand(p_ok BOOLEAN, p_message VARCHAR2) IS
  BEGIN
    IF p_ok IS NULL OR NOT p_ok THEN
      RAISE_APPLICATION_ERROR(-20001, SUBSTR(p_message, 1, 1900));
    END IF;
  END;

  FUNCTION count_sql(p_sql VARCHAR2) RETURN NUMBER IS
    v NUMBER;
  BEGIN
    EXECUTE IMMEDIATE p_sql INTO v;
    RETURN v;
  END;

  FUNCTION has_active RETURN BOOLEAN IS
  BEGIN
    RETURN count_sql('SELECT COUNT(*) FROM user_tab_columns WHERE table_name = ''DELIVERABLES'' AND column_name = ''ACTIVE_FLAG''') = 1;
  END;

  FUNCTION capture(p_table VARCHAR2, p_backup BOOLEAN DEFAULT FALSE) RETURN CLOB IS
    v_sql VARCHAR2(32767);
    v_result CLOB;
    v_table VARCHAR2(40);
  BEGIN
    v_table := CASE WHEN p_backup THEN 'AIPS_BK_' ELSE '' END || p_table;
    CASE p_table
"""
    for t, cols in TABLES.items():
        fields = []
        for c in cols.split():
            expr = c
            if c in ("created_at", "assigned_at"):
                expr = f"TO_CHAR({c}, 'YYYY-MM-DD\"T\"HH24:MI:SS.FF9TZH:TZM')"
            elif c in ("effective_from", "effective_to"):
                expr = f"TO_CHAR({c}, 'YYYY-MM-DD\"T\"HH24:MI:SS')"
            fields.append(lit(c) + " VALUE " + expr)
        select = "SELECT JSON_ARRAYAGG(JSON_OBJECT(" + ", ".join(fields) + ") ORDER BY " + ", ".join(KEYS[t].split()) + " RETURNING CLOB) FROM "
        # An individual row can exceed 4000 bytes, so the object also returns CLOB.
        select = select.replace(") ORDER BY ", " RETURNING CLOB) ORDER BY ")
        common += f"      WHEN '{t}' THEN v_sql := {q(select)};\n"
    common += """      ELSE RAISE_APPLICATION_ERROR(-20002, 'Unknown migration table');
    END CASE;
    IF p_table = 'DELIVERABLES' AND NOT p_backup AND NOT has_active THEN
      v_sql := REPLACE(v_sql, '''active_flag'' VALUE active_flag', '''active_flag'' VALUE ''Y''');
    END IF;
    EXECUTE IMMEDIATE v_sql || v_table INTO v_result;
    IF v_result IS NULL THEN v_result := TO_CLOB('[]'); END IF;
    RETURN v_result;
  END;

  PROCEDURE check_snapshot(p_table VARCHAR2, p_image VARCHAR2) IS
    v_expected CLOB;
    v_actual CLOB;
  BEGIN
    demand(p_image IN ('BEFORE_JSON', 'AFTER_JSON'), 'Invalid image');
    EXECUTE IMMEDIATE 'SELECT ' || p_image || ' FROM AIPS_MIG_BACKUP WHERE object_name = :1'
      INTO v_expected USING p_table;
    v_actual := capture(p_table);
    demand(v_expected IS NOT NULL AND DBMS_LOB.COMPARE(v_expected, v_actual) = 0,
      'Data changed in ' || p_table || '. Stopped without overwriting it. Review before proceeding.');
    EXECUTE IMMEDIATE 'SELECT before_json FROM AIPS_MIG_BACKUP WHERE object_name = :1'
      INTO v_expected USING p_table;
    v_actual := capture(p_table, TRUE);
    demand(v_expected IS NOT NULL AND DBMS_LOB.COMPARE(v_expected, v_actual) = 0,
      'Recovery backup changed for ' || p_table || '. Stopped.');
  END;

  PROCEDURE lock_tables IS
  BEGIN
"""
    for t in sorted(TABLES):
        common += run(f"LOCK TABLE {t} IN EXCLUSIVE MODE NOWAIT")
    for t in PROTECTED:
        common += run(f"LOCK TABLE {t} IN SHARE MODE NOWAIT")
    common += "  END;\n\n"
    begin = """BEGIN
  demand(SYS_CONTEXT('USERENV','SESSION_USER') = 'AI_POD_STAFFING'
    AND SYS_CONTEXT('USERENV','CURRENT_SCHEMA') = 'AI_POD_STAFFING',
    'Wrong connection. Both session user and current schema must be AI_POD_STAFFING.');
  -- Avoid the parallel-DML errors encountered in earlier installers.
  EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL DML';
  EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL QUERY';
  EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL DDL';
  EXECUTE IMMEDIATE 'ALTER SESSION SET DDL_LOCK_TIMEOUT = 5';
  EXECUTE IMMEDIATE 'ALTER SESSION SET NLS_SORT = BINARY';
  EXECUTE IMMEDIATE 'ALTER SESSION SET NLS_COMP = BINARY';
"""
    validate_schema = ""
    for t, cols in TABLES.items():
        expected = cols.upper().split()
        counts = f"({len(expected) - 1}, {len(expected)})" if t == "DELIVERABLES" else f"({len(expected)})"
        validate_schema += f"  demand(count_sql('SELECT COUNT(*) FROM user_tables WHERE table_name = ''{t}''') = 1, 'Missing table {t}');\n"
        validate_schema += f"  demand(count_sql('SELECT COUNT(*) FROM user_tab_columns WHERE table_name = ''{t}''') IN {counts}, 'Unexpected columns in {t}; review schema before migrating');\n"
        allowed = ",".join(lit(c) for c in expected)
        validate_schema += f"  demand(count_sql({q('SELECT COUNT(*) FROM user_tab_columns WHERE table_name='+lit(t)+' AND column_name NOT IN ('+allowed+')')})=0, 'Unrecognized columns in {t}; migration stopped');\n"
        for c in expected:
            if t == "DELIVERABLES" and c == "ACTIVE_FLAG":
                continue
            validate_schema += f"  demand(count_sql('SELECT COUNT(*) FROM user_tab_columns WHERE table_name = ''{t}'' AND column_name = ''{c}''') = 1, 'Missing {t}.{c}');\n"
    validate_schema += """  demand(count_sql('SELECT COUNT(*) FROM user_triggers WHERE status = ''ENABLED'' AND table_name IN (''PROJECT_TYPES'',''INTERESTS'',''CUSTOMER_MAPPING'',''DELIVERABLES'',''DELIVERABLE_SKILLS'',''APP_ROLES'',''ROLE_PERMISSIONS'',''APP_USER_ROLES'')') = 0,
    'Enabled triggers found on migration tables. Review their effects before proceeding.');
"""
    journal_check = f"""  demand(count_sql('SELECT COUNT(*) FROM user_tab_columns WHERE table_name = ''AIPS_MIG_BACKUP''') = 9,
    'Unexpected AIPS_MIG_BACKUP definition. Do not reuse or delete an unknown backup.');
  IF count_sql('SELECT COUNT(*) FROM AIPS_MIG_BACKUP') > 0 THEN
    EXECUTE IMMEDIATE 'SELECT migration_id, source_sha, state, original_active, original_nullable FROM AIPS_MIG_BACKUP WHERE object_name = ''HEADER'''
      INTO l_state, l_sql, l_state, l_original_active, l_original_nullable;
    demand(count_sql('SELECT COUNT(*) FROM AIPS_MIG_BACKUP WHERE migration_id <> ''{MID}'' OR source_sha <> ''{sha}''') = 0,
      'Backup belongs to another migration or source revision. Stopped.');
    demand(count_sql('SELECT COUNT(*) FROM AIPS_MIG_BACKUP') = 9, 'Incomplete backup manifest. Stopped.');
  ELSE
    l_state := NULL;
  END IF;
"""
    # Avoid assigning two SELECT targets to one variable.
    journal_check = journal_check.replace("SELECT migration_id, source_sha, state, original_active, original_nullable", "SELECT source_sha, state, original_active, original_nullable").replace("INTO l_state, l_sql, l_state, l_original_active, l_original_nullable", "INTO l_sql, l_state, l_original_active, l_original_nullable")
    primary = header + "\n" + common + begin + validate_schema
    primary += """  -- No business mutation has occurred above this line.
  IF count_sql('SELECT COUNT(*) FROM user_tables WHERE table_name = ''AIPS_MIG_BACKUP''') = 0 THEN
""" + run("""CREATE TABLE AIPS_MIG_BACKUP (
    object_name VARCHAR2(30) PRIMARY KEY, migration_id VARCHAR2(40) NOT NULL,
    source_sha VARCHAR2(64) NOT NULL, state VARCHAR2(20) NOT NULL,
    original_active CHAR(1), original_nullable CHAR(1),
    before_json CLOB, after_json CLOB,
    saved_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL)""") + "  END IF;\n" + journal_check
    primary += """  IF l_state = 'APPLIED' THEN
    lock_tables;
"""
    for t in TABLES:
        primary += f"    check_snapshot('{t}', 'AFTER_JSON');\n"
    primary += """    ROLLBACK;
    DBMS_OUTPUT.PUT_LINE('ALREADY APPLIED AND VERIFIED. No changes were made.');
    RETURN;
  END IF;
  demand(l_state IS NULL OR l_state = 'PREPARED', 'Migration was rolled back or has an unknown state. Use a new reviewed migration.');

  IF l_state IS NULL THEN
    DBMS_OUTPUT.PUT_LINE('Checking the expected catalogue baseline and existing role assignments');
"""
    # Exact catalogue baseline catches changed links, IDs and collisions before writes.
    for t, records in baseline.items():
        primary += f"    demand(count_sql('SELECT COUNT(*) FROM {t}') = {len(records)}, 'Unexpected {t} count; live catalogue differs from reviewed baseline');\n"
        for r in records:
            where = " AND ".join(f"{c} IS NULL" if v is None else f"{c} = {lit(v)}" for c,v in r.items())
            primary += f"    demand(count_sql({q('SELECT COUNT(*) FROM '+t+' WHERE '+where)}) = 1, 'Baseline mismatch in {t}: {str(next(iter(r.values()))).replace(chr(39),chr(39)*2)}');\n"
    primary += """    demand(count_sql('SELECT COUNT(*) FROM user_constraints WHERE constraint_name=''CK_AIPS_DEL_ACTIVE''') = 0, 'Reserved migration constraint already exists');
    demand(count_sql('SELECT COUNT(*) FROM app_roles WHERE role_code NOT IN (''OPERATIONS_LEAD'',''REQUEST_LEAD'',''POD_LEAD'',''POD_MEMBER'',''EXECUTIVE'',''SYSTEM_ADMINISTRATOR'')') = 0,
      'Unrecognized role codes exist; review them before replacing permissions');
    demand(count_sql('SELECT COUNT(*) FROM app_roles') = 6, 'Expected the six original roles');
    demand(count_sql('SELECT COUNT(*) FROM app_user_roles WHERE role_code = ''EXECUTIVE'' AND active_flag = ''Y'' AND (effective_to IS NULL OR effective_to >= TRUNC(SYSDATE))') = 0,
      'Executive has active or future assignments. Choose official profiles for these users first.');
    demand(count_sql('SELECT COUNT(*) FROM app_user_roles a JOIN app_user_roles b ON a.identity_subject=b.identity_subject WHERE a.role_code=''OPERATIONS_LEAD'' AND b.role_code=''REQUEST_LEAD'' AND (DECODE(a.person_id,b.person_id,1,0)=0 OR a.active_flag<>b.active_flag OR a.effective_from<>b.effective_from OR DECODE(a.effective_to,b.effective_to,1,0)=0)') = 0,
      'Conflicting Operations Lead / Request Lead mappings found for the same identity. Resolve person, active flag or date differences first.');
    demand(count_sql('SELECT COUNT(*) FROM customer_mapping WHERE source_version = ''""" + VERSION + """''') = 0, 'Target source revision already exists');
    l_original_active := CASE WHEN has_active THEN 'Y' ELSE 'N' END;
    IF has_active THEN
      demand(count_sql('SELECT COUNT(*) FROM deliverables WHERE active_flag IS NULL OR active_flag <> ''Y''') = 0,
        'Existing deliverable retirement differs from expected baseline');
    END IF;
    SELECT nullable INTO l_original_nullable FROM user_tab_columns
      WHERE table_name='DELIVERABLES' AND column_name='SKILLS_RAW';
    -- Create EMPTY backup structures first. DDL here cannot commit partial data changes.
"""
    for t, cols in TABLES.items():
        select = ", ".join(cols.split())
        create = f"CREATE TABLE AIPS_BK_{t} AS SELECT {select} FROM {t} WHERE 1=0"
        if t == "DELIVERABLES":
            primary += f"    l_sql := {q(create)};\n    IF NOT has_active THEN l_sql := REPLACE(l_sql, ', active_flag', ', CAST(''Y'' AS CHAR(1)) AS active_flag'); END IF;\n"
        else:
            primary += f"    l_sql := {q(create)};\n"
        primary += f"    IF count_sql('SELECT COUNT(*) FROM user_tables WHERE table_name=''AIPS_BK_{t}''') = 0 THEN EXECUTE IMMEDIATE l_sql; END IF;\n"
        primary += f"    demand(count_sql('SELECT COUNT(*) FROM AIPS_BK_{t}') = 0, 'Existing nonempty AIPS_BK_{t}; backup will not be overwritten');\n"
        primary += f"    demand(count_sql('SELECT COUNT(*) FROM user_tab_columns WHERE table_name=''AIPS_BK_{t}''')={len(cols.split())}, 'Unexpected backup structure AIPS_BK_{t}');\n"
    primary += "    lock_tables;\n" + run("LOCK TABLE AIPS_MIG_BACKUP IN EXCLUSIVE MODE NOWAIT")
    # Recheck the baseline after obtaining locks, closing the preparation/DDL race.
    baseline_start = primary.index("    DBMS_OUTPUT.PUT_LINE('Checking the expected catalogue baseline")
    baseline_end = primary.index("    l_original_active :=", baseline_start)
    primary += primary[baseline_start:baseline_end]
    for t, cols in TABLES.items():
        primary += run(f"LOCK TABLE AIPS_BK_{t} IN EXCLUSIVE MODE NOWAIT")
        stmt = f"INSERT INTO AIPS_BK_{t} ({', '.join(cols.split())}) SELECT {', '.join(cols.split())} FROM {t}"
        primary += f"    l_sql := {q(stmt)};\n"
        if t == "DELIVERABLES":
            primary += "    IF NOT has_active THEN l_sql := REPLACE(l_sql, 'source_row, active_flag FROM', 'source_row, CAST(''Y'' AS CHAR(1)) FROM'); END IF;\n"
        primary += "    EXECUTE IMMEDIATE l_sql;\n"
        primary += f"    l_before := capture('{t}');\n    l_now := capture('{t}', TRUE);\n    demand(DBMS_LOB.COMPARE(l_before,l_now)=0, 'Backup verification failed: {t}');\n"
        primary += f"    EXECUTE IMMEDIATE {q('INSERT INTO AIPS_MIG_BACKUP (object_name,migration_id,source_sha,state,before_json) VALUES (:1,:2,:3,\'SNAPSHOT\',:4)')} USING '{t}', '{MID}', '{sha}', l_before;\n"
    primary += f"    EXECUTE IMMEDIATE {q('INSERT INTO AIPS_MIG_BACKUP (object_name,migration_id,source_sha,state,original_active,original_nullable) VALUES (\'HEADER\',:1,:2,\'PREPARED\',:3,:4)')} USING '{MID}', '{sha}', l_original_active, l_original_nullable;\n"
    primary += """    COMMIT;
    DBMS_OUTPUT.PUT_LINE('Eight original tables backed up and verified');
  END IF;

  -- On a retry, verify the original data still matches the saved backup.
  lock_tables;
"""
    for t in TABLES:
        primary += f"  check_snapshot('{t}', 'BEFORE_JSON');\n"
    primary += """  ROLLBACK; -- Release locks before DDL; maintenance window must remain in force.
  IF NOT has_active THEN
    EXECUTE IMMEDIATE 'ALTER TABLE DELIVERABLES ADD (active_flag CHAR(1) DEFAULT ''Y'' NOT NULL)';
  END IF;
  IF count_sql('SELECT COUNT(*) FROM user_constraints WHERE constraint_name=''CK_AIPS_DEL_ACTIVE''') = 0 THEN
    EXECUTE IMMEDIATE 'ALTER TABLE DELIVERABLES ADD CONSTRAINT ck_aips_del_active CHECK (active_flag IN (''Y'',''N''))';
  END IF;
  IF count_sql('SELECT COUNT(*) FROM user_tab_columns WHERE table_name=''DELIVERABLES'' AND column_name=''SKILLS_RAW'' AND nullable=''N''') = 1 THEN
    EXECUTE IMMEDIATE 'ALTER TABLE DELIVERABLES MODIFY (skills_raw NULL)';
  END IF;

  lock_tables;
""" + run("LOCK TABLE AIPS_MIG_BACKUP IN EXCLUSIVE MODE NOWAIT")
    for t in TABLES:
        primary += run(f"LOCK TABLE AIPS_BK_{t} IN SHARE MODE NOWAIT")
        primary += f"  check_snapshot('{t}', 'BEFORE_JSON');\n"
    primary += "  DBMS_OUTPUT.PUT_LINE('Applying catalogue and profile changes in ONE transaction');\n"
    # Preserve raw continuation/blank rows and exact text. Operational values trimmed separately.
    for rownum, r in enumerate(raw, 2):
        vals = [r[k] for k in ("Projects", "Project Description", "Deliverables", "Skills (Type of work)", "Note")]
        primary += run("INSERT INTO CUSTOMER_MAPPING (projects,project_description,deliverables,skills_type_of_work,note,source_version,source_row,customer_controlled) VALUES (" + ",".join(map(lit, vals + [VERSION,rownum,"Yes"])) + ")")
    for p in projects:
        first = next(r for r in rows if r["project"] == p)
        primary += run(f"UPDATE PROJECT_TYPES SET project_name={lit(p)}, project_description={lit(first['description'])}, source_version={lit(VERSION)}, source_row={first['row']} WHERE project_type_id={lit(projects[p])}")
    primary += run(f"INSERT INTO INTERESTS (interest_id,interest_name,category,source,source_version,customer_controlled) VALUES ('SK-014','Comms Team','Communications','Customer Mapping','{VERSION}','Yes')")
    for r in rows:
        cols = "deliverable_id project_type_id project_name deliverable_name skills_raw customer_note source_version source_row active_flag".split()
        vals = [r["id"],r["project_id"],r["project"],r["name"],r["skills"],r["note"],VERSION,r["row"],"Y"]
        if r["new"]:
            primary += run(f"INSERT INTO DELIVERABLES ({','.join(cols)}) VALUES ({','.join(map(lit, vals))})")
        else:
            primary += run("UPDATE DELIVERABLES SET " + ",".join(f"{c}={lit(v)}" for c,v in zip(cols[1:],vals[1:])) + " WHERE deliverable_id="+lit(r["id"]))
        primary += run(f"DELETE FROM DELIVERABLE_SKILLS WHERE deliverable_id={lit(r['id'])}")
        for s in r["skill_list"]:
            primary += run(f"INSERT INTO DELIVERABLE_SKILLS (deliverable_id,skill_id,skill_name,source_version,source_row) VALUES ({lit(r['id'])},{lit(skills[s])},{lit(s)},'{VERSION}',{r['row']})")
    for r in retired:
        primary += run(f"UPDATE DELIVERABLES SET active_flag='N' WHERE deliverable_id={lit(r['deliverable_id'])}")
    role_defs = [
        ("POD_CAPTAIN","POD Captain","Submits requests, reviews the POD, and approves the POD team."),
        ("POD_LEAD","POD Lead","Manages projects assigned to them and closes projects."),
        ("POD_MEMBER","POD Member","Views assigned team and personal information."),
        ("SYSTEM_ADMINISTRATOR","Administrator","Manages backend configuration, access, and administrative changes."),
    ]
    for code,name,description in role_defs:
        if code == "POD_CAPTAIN":
            primary += run(f"INSERT INTO APP_ROLES (role_code,role_name,role_description,active_flag) VALUES ({lit(code)},{lit(name)},{lit(description)},'Y')")
        else:
            primary += run(f"UPDATE APP_ROLES SET role_name={lit(name)},role_description={lit(description)},active_flag='Y' WHERE role_code={lit(code)}")
    primary += run("UPDATE APP_ROLES SET active_flag='N' WHERE role_code IN ('OPERATIONS_LEAD','REQUEST_LEAD','EXECUTIVE')")
    primary += run("DELETE FROM ROLE_PERMISSIONS WHERE role_code IN ('OPERATIONS_LEAD','REQUEST_LEAD','POD_LEAD','POD_MEMBER','EXECUTIVE','SYSTEM_ADMINISTRATOR')")
    resources = ["DASHBOARD","REQUESTS","AI_FITMENT","ALLOCATION_CALENDAR","TEAM_SKILLS","MY_AVAILABILITY","AGENT_EXECUTION","REPORTS","ADMINISTRATION","PROJECT_CLOSURE","ACCESS_MANAGEMENT","BACKEND_CONFIGURATION"]
    # Flags: view, create, update, approve, export, administer.
    policies = {
        "POD_CAPTAIN": {"DASHBOARD":("FULL","YNNNNN"),"REQUESTS":("FULL","YYYNNN"),"AI_FITMENT":("FULL","YYYYNN"),"ALLOCATION_CALENDAR":("FULL","YNNNNN"),"TEAM_SKILLS":("FULL","YNNNNN"),"MY_AVAILABILITY":("OWN","YNNNNN"),"AGENT_EXECUTION":("FULL","YYNNNN"),"REPORTS":("FULL","YNNNNN")},
        "POD_LEAD": {"DASHBOARD":("SCOPED","YNNNNN"),"REQUESTS":("SCOPED","YNYNNN"),"AI_FITMENT":("SCOPED","YNNNNN"),"ALLOCATION_CALENDAR":("SCOPED","YNNNNN"),"TEAM_SKILLS":("SCOPED","YNNNNN"),"MY_AVAILABILITY":("OWN","YNNNNN"),"PROJECT_CLOSURE":("SCOPED","YNYNNN")},
        "POD_MEMBER": {"DASHBOARD":("SCOPED","YNNNNN"),"REQUESTS":("SCOPED","YNNNNN"),"TEAM_SKILLS":("SCOPED","YNNNNN"),"MY_AVAILABILITY":("OWN","YNNNNN")},
        "SYSTEM_ADMINISTRATOR": {"ADMINISTRATION":("FULL","YYYNNY"),"ACCESS_MANAGEMENT":("FULL","YYYNNY"),"BACKEND_CONFIGURATION":("FULL","YYYNNY")},
    }
    for code in policies:
        for resource in resources:
            scope,flags=policies[code].get(resource,("LOCKED","NNNNNN"))
            primary += run("INSERT INTO ROLE_PERMISSIONS (role_code,resource_code,access_scope,can_view,can_create,can_update,can_approve,can_export,can_administer) VALUES ("+",".join(map(lit,[code,resource,scope,*flags]))+")")
    # Same person/date/active duplicates are safe to collapse. Conflicts were blocked.
    primary += run("""INSERT INTO APP_USER_ROLES (identity_subject,role_code,person_id,active_flag,effective_from,effective_to,assigned_by,assigned_at)
  SELECT identity_subject,'POD_CAPTAIN',person_id,active_flag,effective_from,effective_to,assigned_by,assigned_at FROM (
    SELECT a.*,ROW_NUMBER() OVER (PARTITION BY identity_subject ORDER BY CASE role_code WHEN 'OPERATIONS_LEAD' THEN 0 ELSE 1 END) AS rn
    FROM APP_USER_ROLES a WHERE role_code IN ('OPERATIONS_LEAD','REQUEST_LEAD')) WHERE rn=1""")
    primary += run("DELETE FROM APP_USER_ROLES WHERE role_code IN ('OPERATIONS_LEAD','REQUEST_LEAD')")
    primary += "\n  -- Acceptance checks: any failure rolls back ALL catalogue and role DML.\n"
    for t,c in [("PROJECT_TYPES",11),("INTERESTS",14),("DELIVERABLES",78),("DELIVERABLE_SKILLS",129)]:
        primary += f"  demand(count_sql('SELECT COUNT(*) FROM {t}')={c}, '{t}: unexpected final count');\n"
    checks = [
        ("SELECT COUNT(*) FROM deliverables WHERE active_flag='Y'",73,"Active deliverables"),
        ("SELECT COUNT(*) FROM deliverables WHERE active_flag='N'",5,"Retired deliverables"),
        ("SELECT COUNT(*) FROM deliverable_skills ds JOIN deliverables d ON d.deliverable_id=ds.deliverable_id WHERE d.active_flag='Y'",114,"Active skill links"),
        (f"SELECT COUNT(*) FROM customer_mapping WHERE source_version='{VERSION}'",85,"CSV source rows including separators"),
        (f"SELECT COUNT(*) FROM customer_mapping WHERE source_version='{VERSION}' AND TRIM(deliverables) IS NOT NULL",73,"CSV nonblank deliverables"),
        ("SELECT COUNT(*) FROM app_roles WHERE active_flag='Y'",4,"Official active roles"),
        ("SELECT COUNT(*) FROM role_permissions",48,"Official permission rows"),
        ("SELECT COUNT(*) FROM app_user_roles WHERE role_code IN ('OPERATIONS_LEAD','REQUEST_LEAD')",0,"Migrated legacy user roles"),
        ("SELECT COUNT(*) FROM deliverables WHERE active_flag='Y' AND skills_raw IS NULL",1,"Unspecified CSV skill"),
    ]
    for query,n,label in checks:
        primary += f"  demand(count_sql({q(query)})={n}, '{label}: failed');\n"
    # Exhaustively verify intended active row values and edges, beyond counts alone.
    for r in rows:
        conditions={"deliverable_id":r["id"],"project_type_id":r["project_id"],"project_name":r["project"],"deliverable_name":r["name"],"skills_raw":r["skills"] or None,"customer_note":r["note"] or None,"source_version":VERSION,"source_row":r["row"],"active_flag":"Y"}
        where=" AND ".join(f"{c} IS NULL" if v is None else f"{c}={lit(v)}" for c,v in conditions.items())
        primary+=f"  demand(count_sql({q('SELECT COUNT(*) FROM deliverables WHERE '+where)})=1, 'Catalogue verification failed: {r['id']}');\n"
    for t in TABLES:
        primary += f"  l_now := capture('{t}');\n  EXECUTE IMMEDIATE 'UPDATE AIPS_MIG_BACKUP SET after_json=:1 WHERE object_name=:2' USING l_now, '{t}';\n"
    primary += run("UPDATE AIPS_MIG_BACKUP SET state='APPLIED' WHERE object_name='HEADER'")
    primary += """  COMMIT;
  DBMS_OUTPUT.PUT_LINE('SUCCESS: roles and catalogue migration committed');
  DBMS_OUTPUT.PUT_LINE('4 active profiles; 73 active / 5 retired deliverables; 14 skills; 114 active skill links');
  DBMS_OUTPUT.PUT_LINE('85 raw CSV rows saved, including 12 blank separators. Existing source revisions retained.');
  DBMS_OUTPUT.PUT_LINE('No people, request, requirement, recommendation or availability records changed.');
  DBMS_OUTPUT.PUT_LINE('Keep the application stopped until its matching role/catalogue changes are deployed.');
  DBMS_OUTPUT.PUT_LINE('Do not delete AIPS_BK_* or AIPS_MIG_BACKUP during the recovery window.');
EXCEPTION
  WHEN OTHERS THEN
    ROLLBACK;
    DBMS_OUTPUT.PUT_LINE('STOPPED: ' || SQLERRM);
    DBMS_OUTPUT.PUT_LINE(DBMS_UTILITY.FORMAT_ERROR_BACKTRACE);
    DBMS_OUTPUT.PUT_LINE('Uncommitted data changes rolled back. DDL/verified backups may remain.');
    DBMS_OUTPUT.PUT_LINE('Fix the reported cause and rerun this whole file, or use rollback_roles_catalog.sql.');
    RAISE;
END;
/
"""

    recovery = header.replace("-- AI Pod Staffing: official profiles and revised customer catalogue", "-- RECOVERY ONLY: undo roles_catalog.sql") + "\n" + common + begin
    recovery += """  IF count_sql('SELECT COUNT(*) FROM user_tables WHERE table_name=''AIPS_MIG_BACKUP''')=0 THEN
    DBMS_OUTPUT.PUT_LINE('No migration backup exists. No changes to undo.'); RETURN;
  END IF;
""" + journal_check
    recovery += """  IF l_state IS NULL THEN
    DBMS_OUTPUT.PUT_LINE('No committed migration backup: no business/DDL changes to undo. Empty backup objects may remain.'); RETURN;
  END IF;
  IF l_state='ROLLED_BACK' THEN
    DBMS_OUTPUT.PUT_LINE('Recovery already completed. No changes made.'); RETURN;
  END IF;
  demand(l_state IN ('PREPARED','APPLIED','DATA_RESTORED'), 'Unknown recovery state. Stopped.');
  IF l_state <> 'DATA_RESTORED' THEN
    lock_tables;
""" + run("LOCK TABLE AIPS_MIG_BACKUP IN EXCLUSIVE MODE NOWAIT")
    for t in TABLES:
        recovery += run(f"LOCK TABLE AIPS_BK_{t} IN SHARE MODE NOWAIT")
        recovery += f"    check_snapshot('{t}', CASE WHEN l_state='APPLIED' THEN 'AFTER_JSON' ELSE 'BEFORE_JSON' END);\n"
    # All rollback deletes target only migration-created keys; foreign keys remain enabled.
    recovery += f"    demand(count_sql('SELECT COUNT(*) FROM requests WHERE mapping_version=''{VERSION}''')=0, 'Requests now use the new catalogue revision. Recovery stopped.');\n"
    recovery += f"    demand(count_sql('SELECT COUNT(*) FROM requirements WHERE source_version=''{VERSION}''')=0, 'Requirements now use the new catalogue revision. Recovery stopped.');\n"
    recovery += """    demand(count_sql('SELECT COUNT(*) FROM requests r WHERE (r.deliverable_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM AIPS_BK_DELIVERABLES b WHERE b.deliverable_id=r.deliverable_id)) OR EXISTS (SELECT 1 FROM JSON_TABLE(r.deliverables_json, ''$[*]'' COLUMNS (did VARCHAR2(30) PATH ''$.deliverableId'', iid VARCHAR2(30) PATH ''$.id'')) j JOIN deliverables d ON d.deliverable_id=COALESCE(j.did,j.iid) WHERE NOT EXISTS (SELECT 1 FROM AIPS_BK_DELIVERABLES b WHERE b.deliverable_id=d.deliverable_id))')=0,
      'A request now uses a newly added deliverable. Recovery stopped; preserve the new request and review manually.');
    demand(count_sql('SELECT COUNT(*) FROM requirements r WHERE (r.deliverable_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM AIPS_BK_DELIVERABLES b WHERE b.deliverable_id=r.deliverable_id)) OR (r.interest_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM AIPS_BK_INTERESTS b WHERE b.interest_id=r.interest_id))')=0,
      'Requirements now reference new catalogue data. Recovery stopped.');
    demand(count_sql('SELECT COUNT(*) FROM person_interests p WHERE NOT EXISTS (SELECT 1 FROM AIPS_BK_INTERESTS b WHERE b.interest_id=p.interest_id)')=0,
      'A person now has a newly added skill. Recovery stopped.');
    IF l_state='APPLIED' THEN
"""
    # Restore all old keys in place (parents first), then remove new keys child first.
    for t,cols in TABLES.items():
        keys=KEYS[t].split(); names=cols.split()
        join=" AND ".join(f"t.{k}=b.{k}" for k in keys)
        updates=",".join(f"t.{c}=b.{c}" for c in names if c not in keys)
        recovery += run(f"MERGE INTO {t} t USING AIPS_BK_{t} b ON ({join}) WHEN MATCHED THEN UPDATE SET {updates} WHEN NOT MATCHED THEN INSERT ({','.join(names)}) VALUES ({','.join('b.'+c for c in names)})")
    for t in ["APP_USER_ROLES","ROLE_PERMISSIONS","DELIVERABLE_SKILLS","CUSTOMER_MAPPING","DELIVERABLES","INTERESTS","PROJECT_TYPES","APP_ROLES"]:
        join=" AND ".join(f"b.{k}=t.{k}" for k in KEYS[t].split())
        recovery += run(f"DELETE FROM {t} t WHERE NOT EXISTS (SELECT 1 FROM AIPS_BK_{t} b WHERE {join})")
    recovery += "    END IF;\n"
    for t in TABLES:
        recovery += f"    check_snapshot('{t}', 'BEFORE_JSON');\n"
    recovery += run("UPDATE AIPS_MIG_BACKUP SET state='DATA_RESTORED' WHERE object_name='HEADER'")
    recovery += """    COMMIT;
    DBMS_OUTPUT.PUT_LINE('Original data restored and verified. Restoring additive schema changes.');
  END IF;
  -- Check again on DATA_RESTORED retries before finishing the remaining DDL.
  lock_tables;
"""
    for t in TABLES:
        recovery += f"  check_snapshot('{t}', 'BEFORE_JSON');\n"
    recovery += """  ROLLBACK;
  -- DDL is outside the data transaction. If it fails, rerun this recovery script.
  -- DATA_RESTORED prevents replaying the data restore on a retry.
  IF l_original_nullable='N' AND count_sql('SELECT COUNT(*) FROM user_tab_columns WHERE table_name=''DELIVERABLES'' AND column_name=''SKILLS_RAW'' AND nullable=''Y''')=1 THEN
    EXECUTE IMMEDIATE 'ALTER TABLE DELIVERABLES MODIFY (skills_raw NOT NULL)';
  END IF;
  IF count_sql('SELECT COUNT(*) FROM user_constraints WHERE constraint_name=''CK_AIPS_DEL_ACTIVE'' AND table_name=''DELIVERABLES''')=1 THEN
    EXECUTE IMMEDIATE 'ALTER TABLE DELIVERABLES DROP CONSTRAINT ck_aips_del_active';
  END IF;
  IF l_original_active='N' AND has_active THEN
    EXECUTE IMMEDIATE 'ALTER TABLE DELIVERABLES DROP COLUMN active_flag';
  END IF;
""" + run("UPDATE AIPS_MIG_BACKUP SET state='ROLLED_BACK' WHERE object_name='HEADER'") + """  COMMIT;
  DBMS_OUTPUT.PUT_LINE('RECOVERY COMPLETED: original catalogue and role data restored; original schema restored.');
  DBMS_OUTPUT.PUT_LINE('Recovery backups retained. Do not rerun roles_catalog.sql after recovery; obtain a new migration.');
EXCEPTION
  WHEN OTHERS THEN
    ROLLBACK;
    DBMS_OUTPUT.PUT_LINE('RECOVERY STOPPED: ' || SQLERRM);
    DBMS_OUTPUT.PUT_LINE(DBMS_UTILITY.FORMAT_ERROR_BACKTRACE);
    DBMS_OUTPUT.PUT_LINE('No forced overwrite was performed. Preserve backups and review the reported cause.');
    RAISE;
END;
/
"""
    return primary, recovery, dict(rows=rows, retired=retired, policies=policies, sha=sha, raw_rows=len(raw))


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source",type=Path)
    parser.add_argument("--check",action="store_true",help="Verify generated files without writing")
    parser.add_argument("--emit",action="store_true",help="Emit generated SQL as JSON for apply_patch")
    args=parser.parse_args()
    primary,recovery,manifest=build(args.source)
    if args.emit:
        print(json.dumps({"roles_catalog.sql":primary,"rollback_roles_catalog.sql":recovery}))
        raise SystemExit(0)
    for name,content in [("roles_catalog.sql",primary),("rollback_roles_catalog.sql",recovery)]:
        path=ROOT/"sql/oracle"/name
        if args.check:
            assert path.read_text(encoding="utf-8")==content, f"Stale generated file: {path}"
        else:
            path.write_text(content,encoding="utf-8",newline="\n")
        print(f"{'Verified' if args.check else 'Generated'} {name}: {len(content.splitlines())} lines")
    print(f"Source SHA256: {manifest['sha']}")
    print("73 active deliverables, 23 additions, 5 retired, 114 active links; 4 profiles / 48 permissions")
