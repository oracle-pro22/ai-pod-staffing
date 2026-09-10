-- RECOVERY ONLY: undo roles_catalog.sql
-- Migration: ROLES_CATALOG_20260910_V1; source revision: v260810.r2-20260910
-- CSV: Project-Deliverable-Skills-Mapping-v260810.csv
-- CSV SHA256: ac5e58d77f23e58fe9626add1dacc803c9d39b24a4c6b3e9fc8679944ee8aab1
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

DECLARE
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
      WHEN 'PROJECT_TYPES' THEN v_sql := q'~SELECT JSON_ARRAYAGG(JSON_OBJECT('project_type_id' VALUE project_type_id, 'project_name' VALUE project_name, 'project_description' VALUE project_description, 'source_version' VALUE source_version, 'source_row' VALUE source_row RETURNING CLOB) ORDER BY project_type_id RETURNING CLOB) FROM ~';
      WHEN 'INTERESTS' THEN v_sql := q'~SELECT JSON_ARRAYAGG(JSON_OBJECT('interest_id' VALUE interest_id, 'interest_name' VALUE interest_name, 'category' VALUE category, 'source' VALUE source, 'source_version' VALUE source_version, 'customer_controlled' VALUE customer_controlled RETURNING CLOB) ORDER BY interest_id RETURNING CLOB) FROM ~';
      WHEN 'CUSTOMER_MAPPING' THEN v_sql := q'~SELECT JSON_ARRAYAGG(JSON_OBJECT('projects' VALUE projects, 'project_description' VALUE project_description, 'deliverables' VALUE deliverables, 'skills_type_of_work' VALUE skills_type_of_work, 'note' VALUE note, 'source_version' VALUE source_version, 'source_row' VALUE source_row, 'customer_controlled' VALUE customer_controlled RETURNING CLOB) ORDER BY source_version, source_row RETURNING CLOB) FROM ~';
      WHEN 'DELIVERABLES' THEN v_sql := q'~SELECT JSON_ARRAYAGG(JSON_OBJECT('deliverable_id' VALUE deliverable_id, 'project_type_id' VALUE project_type_id, 'project_name' VALUE project_name, 'deliverable_name' VALUE deliverable_name, 'skills_raw' VALUE skills_raw, 'customer_note' VALUE customer_note, 'source_version' VALUE source_version, 'source_row' VALUE source_row, 'active_flag' VALUE active_flag RETURNING CLOB) ORDER BY deliverable_id RETURNING CLOB) FROM ~';
      WHEN 'DELIVERABLE_SKILLS' THEN v_sql := q'~SELECT JSON_ARRAYAGG(JSON_OBJECT('deliverable_id' VALUE deliverable_id, 'skill_id' VALUE skill_id, 'skill_name' VALUE skill_name, 'source_version' VALUE source_version, 'source_row' VALUE source_row RETURNING CLOB) ORDER BY deliverable_id, skill_id RETURNING CLOB) FROM ~';
      WHEN 'APP_ROLES' THEN v_sql := q'~SELECT JSON_ARRAYAGG(JSON_OBJECT('role_code' VALUE role_code, 'role_name' VALUE role_name, 'role_description' VALUE role_description, 'active_flag' VALUE active_flag, 'created_at' VALUE TO_CHAR(created_at, 'YYYY-MM-DD"T"HH24:MI:SS.FF9TZH:TZM') RETURNING CLOB) ORDER BY role_code RETURNING CLOB) FROM ~';
      WHEN 'ROLE_PERMISSIONS' THEN v_sql := q'~SELECT JSON_ARRAYAGG(JSON_OBJECT('role_code' VALUE role_code, 'resource_code' VALUE resource_code, 'access_scope' VALUE access_scope, 'can_view' VALUE can_view, 'can_create' VALUE can_create, 'can_update' VALUE can_update, 'can_approve' VALUE can_approve, 'can_export' VALUE can_export, 'can_administer' VALUE can_administer RETURNING CLOB) ORDER BY role_code, resource_code RETURNING CLOB) FROM ~';
      WHEN 'APP_USER_ROLES' THEN v_sql := q'~SELECT JSON_ARRAYAGG(JSON_OBJECT('identity_subject' VALUE identity_subject, 'role_code' VALUE role_code, 'person_id' VALUE person_id, 'active_flag' VALUE active_flag, 'effective_from' VALUE TO_CHAR(effective_from, 'YYYY-MM-DD"T"HH24:MI:SS'), 'effective_to' VALUE TO_CHAR(effective_to, 'YYYY-MM-DD"T"HH24:MI:SS'), 'assigned_by' VALUE assigned_by, 'assigned_at' VALUE TO_CHAR(assigned_at, 'YYYY-MM-DD"T"HH24:MI:SS.FF9TZH:TZM') RETURNING CLOB) ORDER BY identity_subject, role_code RETURNING CLOB) FROM ~';
      ELSE RAISE_APPLICATION_ERROR(-20002, 'Unknown migration table');
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
  EXECUTE IMMEDIATE q'~LOCK TABLE APP_ROLES IN EXCLUSIVE MODE NOWAIT~';
  EXECUTE IMMEDIATE q'~LOCK TABLE APP_USER_ROLES IN EXCLUSIVE MODE NOWAIT~';
  EXECUTE IMMEDIATE q'~LOCK TABLE CUSTOMER_MAPPING IN EXCLUSIVE MODE NOWAIT~';
  EXECUTE IMMEDIATE q'~LOCK TABLE DELIVERABLES IN EXCLUSIVE MODE NOWAIT~';
  EXECUTE IMMEDIATE q'~LOCK TABLE DELIVERABLE_SKILLS IN EXCLUSIVE MODE NOWAIT~';
  EXECUTE IMMEDIATE q'~LOCK TABLE INTERESTS IN EXCLUSIVE MODE NOWAIT~';
  EXECUTE IMMEDIATE q'~LOCK TABLE PROJECT_TYPES IN EXCLUSIVE MODE NOWAIT~';
  EXECUTE IMMEDIATE q'~LOCK TABLE ROLE_PERMISSIONS IN EXCLUSIVE MODE NOWAIT~';
  EXECUTE IMMEDIATE q'~LOCK TABLE PEOPLE IN SHARE MODE NOWAIT~';
  EXECUTE IMMEDIATE q'~LOCK TABLE PERSON_INTERESTS IN SHARE MODE NOWAIT~';
  EXECUTE IMMEDIATE q'~LOCK TABLE REQUESTS IN SHARE MODE NOWAIT~';
  EXECUTE IMMEDIATE q'~LOCK TABLE REQUIREMENTS IN SHARE MODE NOWAIT~';
  EXECUTE IMMEDIATE q'~LOCK TABLE RECOMMENDATIONS IN SHARE MODE NOWAIT~';
  EXECUTE IMMEDIATE q'~LOCK TABLE AVAILABILITY IN SHARE MODE NOWAIT~';
  END;

BEGIN
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
  IF count_sql('SELECT COUNT(*) FROM user_tables WHERE table_name=''AIPS_MIG_BACKUP''')=0 THEN
    DBMS_OUTPUT.PUT_LINE('No migration backup exists. No changes to undo.'); RETURN;
  END IF;
  demand(count_sql('SELECT COUNT(*) FROM user_tab_columns WHERE table_name = ''AIPS_MIG_BACKUP''') = 9,
    'Unexpected AIPS_MIG_BACKUP definition. Do not reuse or delete an unknown backup.');
  IF count_sql('SELECT COUNT(*) FROM AIPS_MIG_BACKUP') > 0 THEN
    EXECUTE IMMEDIATE 'SELECT source_sha, state, original_active, original_nullable FROM AIPS_MIG_BACKUP WHERE object_name = ''HEADER'''
      INTO l_sql, l_state, l_original_active, l_original_nullable;
    demand(count_sql('SELECT COUNT(*) FROM AIPS_MIG_BACKUP WHERE migration_id <> ''ROLES_CATALOG_20260910_V1'' OR source_sha <> ''ac5e58d77f23e58fe9626add1dacc803c9d39b24a4c6b3e9fc8679944ee8aab1''') = 0,
      'Backup belongs to another migration or source revision. Stopped.');
    demand(count_sql('SELECT COUNT(*) FROM AIPS_MIG_BACKUP') = 9, 'Incomplete backup manifest. Stopped.');
  ELSE
    l_state := NULL;
  END IF;
  IF l_state IS NULL THEN
    DBMS_OUTPUT.PUT_LINE('No committed migration backup: no business/DDL changes to undo. Empty backup objects may remain.'); RETURN;
  END IF;
  IF l_state='ROLLED_BACK' THEN
    DBMS_OUTPUT.PUT_LINE('Recovery already completed. No changes made.'); RETURN;
  END IF;
  demand(l_state IN ('PREPARED','APPLIED','DATA_RESTORED'), 'Unknown recovery state. Stopped.');
  IF l_state <> 'DATA_RESTORED' THEN
    lock_tables;
  EXECUTE IMMEDIATE q'~LOCK TABLE AIPS_MIG_BACKUP IN EXCLUSIVE MODE NOWAIT~';
  EXECUTE IMMEDIATE q'~LOCK TABLE AIPS_BK_PROJECT_TYPES IN SHARE MODE NOWAIT~';
    check_snapshot('PROJECT_TYPES', CASE WHEN l_state='APPLIED' THEN 'AFTER_JSON' ELSE 'BEFORE_JSON' END);
  EXECUTE IMMEDIATE q'~LOCK TABLE AIPS_BK_INTERESTS IN SHARE MODE NOWAIT~';
    check_snapshot('INTERESTS', CASE WHEN l_state='APPLIED' THEN 'AFTER_JSON' ELSE 'BEFORE_JSON' END);
  EXECUTE IMMEDIATE q'~LOCK TABLE AIPS_BK_CUSTOMER_MAPPING IN SHARE MODE NOWAIT~';
    check_snapshot('CUSTOMER_MAPPING', CASE WHEN l_state='APPLIED' THEN 'AFTER_JSON' ELSE 'BEFORE_JSON' END);
  EXECUTE IMMEDIATE q'~LOCK TABLE AIPS_BK_DELIVERABLES IN SHARE MODE NOWAIT~';
    check_snapshot('DELIVERABLES', CASE WHEN l_state='APPLIED' THEN 'AFTER_JSON' ELSE 'BEFORE_JSON' END);
  EXECUTE IMMEDIATE q'~LOCK TABLE AIPS_BK_DELIVERABLE_SKILLS IN SHARE MODE NOWAIT~';
    check_snapshot('DELIVERABLE_SKILLS', CASE WHEN l_state='APPLIED' THEN 'AFTER_JSON' ELSE 'BEFORE_JSON' END);
  EXECUTE IMMEDIATE q'~LOCK TABLE AIPS_BK_APP_ROLES IN SHARE MODE NOWAIT~';
    check_snapshot('APP_ROLES', CASE WHEN l_state='APPLIED' THEN 'AFTER_JSON' ELSE 'BEFORE_JSON' END);
  EXECUTE IMMEDIATE q'~LOCK TABLE AIPS_BK_ROLE_PERMISSIONS IN SHARE MODE NOWAIT~';
    check_snapshot('ROLE_PERMISSIONS', CASE WHEN l_state='APPLIED' THEN 'AFTER_JSON' ELSE 'BEFORE_JSON' END);
  EXECUTE IMMEDIATE q'~LOCK TABLE AIPS_BK_APP_USER_ROLES IN SHARE MODE NOWAIT~';
    check_snapshot('APP_USER_ROLES', CASE WHEN l_state='APPLIED' THEN 'AFTER_JSON' ELSE 'BEFORE_JSON' END);
    demand(count_sql('SELECT COUNT(*) FROM requests WHERE mapping_version=''v260810.r2-20260910''')=0, 'Requests now use the new catalogue revision. Recovery stopped.');
    demand(count_sql('SELECT COUNT(*) FROM requirements WHERE source_version=''v260810.r2-20260910''')=0, 'Requirements now use the new catalogue revision. Recovery stopped.');
    demand(count_sql('SELECT COUNT(*) FROM requests r WHERE (r.deliverable_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM AIPS_BK_DELIVERABLES b WHERE b.deliverable_id=r.deliverable_id)) OR EXISTS (SELECT 1 FROM JSON_TABLE(r.deliverables_json, ''$[*]'' COLUMNS (did VARCHAR2(30) PATH ''$.deliverableId'', iid VARCHAR2(30) PATH ''$.id'')) j JOIN deliverables d ON d.deliverable_id=COALESCE(j.did,j.iid) WHERE NOT EXISTS (SELECT 1 FROM AIPS_BK_DELIVERABLES b WHERE b.deliverable_id=d.deliverable_id))')=0,
      'A request now uses a newly added deliverable. Recovery stopped; preserve the new request and review manually.');
    demand(count_sql('SELECT COUNT(*) FROM requirements r WHERE (r.deliverable_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM AIPS_BK_DELIVERABLES b WHERE b.deliverable_id=r.deliverable_id)) OR (r.interest_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM AIPS_BK_INTERESTS b WHERE b.interest_id=r.interest_id))')=0,
      'Requirements now reference new catalogue data. Recovery stopped.');
    demand(count_sql('SELECT COUNT(*) FROM person_interests p WHERE NOT EXISTS (SELECT 1 FROM AIPS_BK_INTERESTS b WHERE b.interest_id=p.interest_id)')=0,
      'A person now has a newly added skill. Recovery stopped.');
    IF l_state='APPLIED' THEN
  EXECUTE IMMEDIATE q'~MERGE INTO PROJECT_TYPES t USING AIPS_BK_PROJECT_TYPES b ON (t.project_type_id=b.project_type_id) WHEN MATCHED THEN UPDATE SET t.project_name=b.project_name,t.project_description=b.project_description,t.source_version=b.source_version,t.source_row=b.source_row WHEN NOT MATCHED THEN INSERT (project_type_id,project_name,project_description,source_version,source_row) VALUES (b.project_type_id,b.project_name,b.project_description,b.source_version,b.source_row)~';
  EXECUTE IMMEDIATE q'~MERGE INTO INTERESTS t USING AIPS_BK_INTERESTS b ON (t.interest_id=b.interest_id) WHEN MATCHED THEN UPDATE SET t.interest_name=b.interest_name,t.category=b.category,t.source=b.source,t.source_version=b.source_version,t.customer_controlled=b.customer_controlled WHEN NOT MATCHED THEN INSERT (interest_id,interest_name,category,source,source_version,customer_controlled) VALUES (b.interest_id,b.interest_name,b.category,b.source,b.source_version,b.customer_controlled)~';
  EXECUTE IMMEDIATE q'~MERGE INTO CUSTOMER_MAPPING t USING AIPS_BK_CUSTOMER_MAPPING b ON (t.source_version=b.source_version AND t.source_row=b.source_row) WHEN MATCHED THEN UPDATE SET t.projects=b.projects,t.project_description=b.project_description,t.deliverables=b.deliverables,t.skills_type_of_work=b.skills_type_of_work,t.note=b.note,t.customer_controlled=b.customer_controlled WHEN NOT MATCHED THEN INSERT (projects,project_description,deliverables,skills_type_of_work,note,source_version,source_row,customer_controlled) VALUES (b.projects,b.project_description,b.deliverables,b.skills_type_of_work,b.note,b.source_version,b.source_row,b.customer_controlled)~';
  EXECUTE IMMEDIATE q'~MERGE INTO DELIVERABLES t USING AIPS_BK_DELIVERABLES b ON (t.deliverable_id=b.deliverable_id) WHEN MATCHED THEN UPDATE SET t.project_type_id=b.project_type_id,t.project_name=b.project_name,t.deliverable_name=b.deliverable_name,t.skills_raw=b.skills_raw,t.customer_note=b.customer_note,t.source_version=b.source_version,t.source_row=b.source_row,t.active_flag=b.active_flag WHEN NOT MATCHED THEN INSERT (deliverable_id,project_type_id,project_name,deliverable_name,skills_raw,customer_note,source_version,source_row,active_flag) VALUES (b.deliverable_id,b.project_type_id,b.project_name,b.deliverable_name,b.skills_raw,b.customer_note,b.source_version,b.source_row,b.active_flag)~';
  EXECUTE IMMEDIATE q'~MERGE INTO DELIVERABLE_SKILLS t USING AIPS_BK_DELIVERABLE_SKILLS b ON (t.deliverable_id=b.deliverable_id AND t.skill_id=b.skill_id) WHEN MATCHED THEN UPDATE SET t.skill_name=b.skill_name,t.source_version=b.source_version,t.source_row=b.source_row WHEN NOT MATCHED THEN INSERT (deliverable_id,skill_id,skill_name,source_version,source_row) VALUES (b.deliverable_id,b.skill_id,b.skill_name,b.source_version,b.source_row)~';
  EXECUTE IMMEDIATE q'~MERGE INTO APP_ROLES t USING AIPS_BK_APP_ROLES b ON (t.role_code=b.role_code) WHEN MATCHED THEN UPDATE SET t.role_name=b.role_name,t.role_description=b.role_description,t.active_flag=b.active_flag,t.created_at=b.created_at WHEN NOT MATCHED THEN INSERT (role_code,role_name,role_description,active_flag,created_at) VALUES (b.role_code,b.role_name,b.role_description,b.active_flag,b.created_at)~';
  EXECUTE IMMEDIATE q'~MERGE INTO ROLE_PERMISSIONS t USING AIPS_BK_ROLE_PERMISSIONS b ON (t.role_code=b.role_code AND t.resource_code=b.resource_code) WHEN MATCHED THEN UPDATE SET t.access_scope=b.access_scope,t.can_view=b.can_view,t.can_create=b.can_create,t.can_update=b.can_update,t.can_approve=b.can_approve,t.can_export=b.can_export,t.can_administer=b.can_administer WHEN NOT MATCHED THEN INSERT (role_code,resource_code,access_scope,can_view,can_create,can_update,can_approve,can_export,can_administer) VALUES (b.role_code,b.resource_code,b.access_scope,b.can_view,b.can_create,b.can_update,b.can_approve,b.can_export,b.can_administer)~';
  EXECUTE IMMEDIATE q'~MERGE INTO APP_USER_ROLES t USING AIPS_BK_APP_USER_ROLES b ON (t.identity_subject=b.identity_subject AND t.role_code=b.role_code) WHEN MATCHED THEN UPDATE SET t.person_id=b.person_id,t.active_flag=b.active_flag,t.effective_from=b.effective_from,t.effective_to=b.effective_to,t.assigned_by=b.assigned_by,t.assigned_at=b.assigned_at WHEN NOT MATCHED THEN INSERT (identity_subject,role_code,person_id,active_flag,effective_from,effective_to,assigned_by,assigned_at) VALUES (b.identity_subject,b.role_code,b.person_id,b.active_flag,b.effective_from,b.effective_to,b.assigned_by,b.assigned_at)~';
  EXECUTE IMMEDIATE q'~DELETE FROM APP_USER_ROLES t WHERE NOT EXISTS (SELECT 1 FROM AIPS_BK_APP_USER_ROLES b WHERE b.identity_subject=t.identity_subject AND b.role_code=t.role_code)~';
  EXECUTE IMMEDIATE q'~DELETE FROM ROLE_PERMISSIONS t WHERE NOT EXISTS (SELECT 1 FROM AIPS_BK_ROLE_PERMISSIONS b WHERE b.role_code=t.role_code AND b.resource_code=t.resource_code)~';
  EXECUTE IMMEDIATE q'~DELETE FROM DELIVERABLE_SKILLS t WHERE NOT EXISTS (SELECT 1 FROM AIPS_BK_DELIVERABLE_SKILLS b WHERE b.deliverable_id=t.deliverable_id AND b.skill_id=t.skill_id)~';
  EXECUTE IMMEDIATE q'~DELETE FROM CUSTOMER_MAPPING t WHERE NOT EXISTS (SELECT 1 FROM AIPS_BK_CUSTOMER_MAPPING b WHERE b.source_version=t.source_version AND b.source_row=t.source_row)~';
  EXECUTE IMMEDIATE q'~DELETE FROM DELIVERABLES t WHERE NOT EXISTS (SELECT 1 FROM AIPS_BK_DELIVERABLES b WHERE b.deliverable_id=t.deliverable_id)~';
  EXECUTE IMMEDIATE q'~DELETE FROM INTERESTS t WHERE NOT EXISTS (SELECT 1 FROM AIPS_BK_INTERESTS b WHERE b.interest_id=t.interest_id)~';
  EXECUTE IMMEDIATE q'~DELETE FROM PROJECT_TYPES t WHERE NOT EXISTS (SELECT 1 FROM AIPS_BK_PROJECT_TYPES b WHERE b.project_type_id=t.project_type_id)~';
  EXECUTE IMMEDIATE q'~DELETE FROM APP_ROLES t WHERE NOT EXISTS (SELECT 1 FROM AIPS_BK_APP_ROLES b WHERE b.role_code=t.role_code)~';
    END IF;
    check_snapshot('PROJECT_TYPES', 'BEFORE_JSON');
    check_snapshot('INTERESTS', 'BEFORE_JSON');
    check_snapshot('CUSTOMER_MAPPING', 'BEFORE_JSON');
    check_snapshot('DELIVERABLES', 'BEFORE_JSON');
    check_snapshot('DELIVERABLE_SKILLS', 'BEFORE_JSON');
    check_snapshot('APP_ROLES', 'BEFORE_JSON');
    check_snapshot('ROLE_PERMISSIONS', 'BEFORE_JSON');
    check_snapshot('APP_USER_ROLES', 'BEFORE_JSON');
  EXECUTE IMMEDIATE q'~UPDATE AIPS_MIG_BACKUP SET state='DATA_RESTORED' WHERE object_name='HEADER'~';
    COMMIT;
    DBMS_OUTPUT.PUT_LINE('Original data restored and verified. Restoring additive schema changes.');
  END IF;
  -- Check again on DATA_RESTORED retries before finishing the remaining DDL.
  lock_tables;
  check_snapshot('PROJECT_TYPES', 'BEFORE_JSON');
  check_snapshot('INTERESTS', 'BEFORE_JSON');
  check_snapshot('CUSTOMER_MAPPING', 'BEFORE_JSON');
  check_snapshot('DELIVERABLES', 'BEFORE_JSON');
  check_snapshot('DELIVERABLE_SKILLS', 'BEFORE_JSON');
  check_snapshot('APP_ROLES', 'BEFORE_JSON');
  check_snapshot('ROLE_PERMISSIONS', 'BEFORE_JSON');
  check_snapshot('APP_USER_ROLES', 'BEFORE_JSON');
  ROLLBACK;
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
  EXECUTE IMMEDIATE q'~UPDATE AIPS_MIG_BACKUP SET state='ROLLED_BACK' WHERE object_name='HEADER'~';
  COMMIT;
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
