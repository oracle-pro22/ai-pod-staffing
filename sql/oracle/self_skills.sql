-- Phase 1. Run ONCE with F5, using the AIPOD connection as AI_POD_STAFFING.
-- Stop only this application's local/VM writers. Use a fresh DB session with
-- no pending work. Oracle DDL commits; ROLLBACK cannot undo schema changes.
-- Safe to resume a failed run. Never drops business tables or deletes records.
-- Backup tables are recovery artifacts, not new application/governance tables.
SET SERVEROUTPUT ON
SET DEFINE OFF
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK
PROMPT Preparing self-service skills and interests

DECLARE
  n NUMBER;
  source_count NUMBER;
  backup_count NUMBER;
  nullable_flag VARCHAR2(1);
  marker VARCHAR2(4000);
  PROCEDURE demand(ok BOOLEAN, message VARCHAR2) IS
  BEGIN
    IF ok IS NULL OR NOT ok THEN RAISE_APPLICATION_ERROR(-20001, message); END IF;
  END;
  PROCEDURE backup_table(source_table VARCHAR2, backup_name VARCHAR2) IS
  BEGIN
    SELECT COUNT(*) INTO n FROM user_objects WHERE object_name = backup_name;
    IF n = 0 THEN
      EXECUTE IMMEDIATE 'CREATE TABLE ' || backup_name || ' AS SELECT * FROM ' || source_table;
      EXECUTE IMMEDIATE 'SELECT COUNT(*) FROM ' || source_table INTO source_count;
      EXECUTE IMMEDIATE 'SELECT COUNT(*) FROM ' || backup_name INTO backup_count;
      demand(source_count = backup_count, 'Backup row count mismatch: ' || backup_name);
      EXECUTE IMMEDIATE 'COMMENT ON TABLE ' || backup_name || ' IS ''AIPS_SELF_SKILLS_V1_BACKUP''';
      DBMS_OUTPUT.PUT_LINE(backup_name || ': backed up ' || backup_count || ' rows.');
    ELSE
      SELECT MAX(comments) INTO marker FROM user_tab_comments WHERE table_name = backup_name;
      demand(marker = 'AIPS_SELF_SKILLS_V1_BACKUP', 'Unrecognized backup object: ' || backup_name || '. Stop and review.');
      DBMS_OUTPUT.PUT_LINE(backup_name || ': retaining original backup.');
    END IF;
  END;
  PROCEDURE add_column(table_name_in VARCHAR2, column_name_in VARCHAR2, definition VARCHAR2) IS
  BEGIN
    SELECT COUNT(*) INTO n FROM user_tab_columns WHERE table_name = table_name_in AND column_name = column_name_in;
    IF n = 0 THEN EXECUTE IMMEDIATE 'ALTER TABLE ' || table_name_in || ' ADD (' || column_name_in || ' ' || definition || ')'; END IF;
  END;
  PROCEDURE add_constraint(table_name_in VARCHAR2, constraint_name_in VARCHAR2, definition VARCHAR2) IS
  BEGIN
    SELECT COUNT(*) INTO n FROM user_constraints WHERE constraint_name = constraint_name_in;
    IF n = 0 THEN
      EXECUTE IMMEDIATE 'ALTER TABLE ' || table_name_in || ' ADD CONSTRAINT ' || constraint_name_in || ' ' || definition;
    ELSE
      SELECT COUNT(*) INTO n FROM user_constraints WHERE constraint_name = constraint_name_in
        AND table_name = table_name_in AND status = 'ENABLED' AND validated = 'VALIDATED';
      demand(n = 1, 'Existing constraint needs review: ' || constraint_name_in);
    END IF;
  END;
  PROCEDURE allow_null(column_name_in VARCHAR2) IS
  BEGIN
    SELECT nullable INTO nullable_flag FROM user_tab_columns WHERE table_name = 'PERSON_INTERESTS' AND column_name = column_name_in;
    IF nullable_flag = 'N' THEN EXECUTE IMMEDIATE 'ALTER TABLE PERSON_INTERESTS MODIFY (' || column_name_in || ' NULL)'; END IF;
  END;
BEGIN
  demand(USER = 'AI_POD_STAFFING' AND SYS_CONTEXT('USERENV','SESSION_USER') = 'AI_POD_STAFFING'
    AND SYS_CONTEXT('USERENV','CURRENT_SCHEMA') = 'AI_POD_STAFFING', 'Use AI_POD_STAFFING only, not ADMIN or another schema.');
  EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL DML';
  EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL QUERY';
  EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL DDL';
  SELECT COUNT(*) INTO n FROM app_roles WHERE active_flag = 'Y' AND
    ((role_code = 'POD_CAPTAIN' AND role_name = 'POD Captain') OR
     (role_code = 'POD_LEAD' AND role_name = 'POD Lead') OR
     (role_code = 'POD_MEMBER' AND role_name = 'POD Member') OR
     (role_code = 'SYSTEM_ADMINISTRATOR' AND role_name = 'Administrator'));
  demand(n = 4, 'Apply the official profile/catalogue migration first.');
  SELECT COUNT(*) INTO n FROM interests WHERE interest_id = 'SK-001' AND interest_name = 'Project Manager (GTM SME)';
  demand(n = 1, 'Unexpected Project Manager catalogue ID/name. No guessing: review the catalogue.');
  SELECT COUNT(*) INTO n FROM interests WHERE interest_id = 'SK-014' AND interest_name = 'Comms Team';
  demand(n = 1, 'The current Comms Team catalogue entry is required.');

  backup_table('INTERESTS', 'AIPS_SK_BK_INT');
  backup_table('PERSON_INTERESTS', 'AIPS_SK_BK_PI');
  backup_table('ROLE_PERMISSIONS', 'AIPS_SK_BK_RP');
  backup_table('PEOPLE', 'AIPS_SK_BK_PEOPLE');

  add_column('INTERESTS', 'ASSESSMENT_TYPE', 'VARCHAR2(12) DEFAULT ''SELF_RATED'' NOT NULL');
  add_column('INTERESTS', 'DERIVED_ROLE_CODE', 'VARCHAR2(40)');
  add_column('PEOPLE', 'SKILLS_VERSION', 'NUMBER(10) DEFAULT 0 NOT NULL');
  add_column('PERSON_INTERESTS', 'INTERESTED_FLAG', 'CHAR(1) DEFAULT ''N'' NOT NULL');
  add_column('PERSON_INTERESTS', 'UPDATED_AT', 'TIMESTAMP WITH TIME ZONE');
  add_column('PERSON_INTERESTS', 'UPDATED_BY', 'VARCHAR2(255)');
  allow_null('STRENGTH');
  allow_null('EVIDENCE_NOTE');

  add_constraint('INTERESTS', 'CK_INT_ASSESSMENT', 'CHECK (assessment_type IN (''SELF_RATED'', ''ROLE_DERIVED''))');
  add_constraint('INTERESTS', 'CK_INT_DERIVED_ROLE', 'CHECK (assessment_type = ''ROLE_DERIVED'' OR derived_role_code IS NULL)');
  add_constraint('INTERESTS', 'FK_INT_DERIVED_ROLE', 'FOREIGN KEY (derived_role_code) REFERENCES APP_ROLES(role_code)');
  add_constraint('PEOPLE', 'CK_PEOPLE_SK_VERSION', 'CHECK (skills_version >= 0)');
  add_constraint('PERSON_INTERESTS', 'CK_PI_INTERESTED', 'CHECK (interested_flag IN (''Y'', ''N''))');
  add_constraint('PERSON_INTERESTS', 'CK_PI_ASSESSMENT', 'CHECK (strength IS NOT NULL OR interested_flag = ''Y'')');
  add_constraint('PERSON_INTERESTS', 'CK_PI_EVIDENCE', 'CHECK (strength IS NULL OR evidence_note IS NOT NULL)');
  -- Existing CK_PI_STRENGTH keeps the range 1..5. Preserve legacy decimal ratings;
  -- new API submissions must use integer ratings. Existing role-skill rows stay intact.
  SELECT COUNT(*) INTO n FROM user_constraints WHERE table_name = 'PERSON_INTERESTS'
    AND constraint_name = 'CK_PI_STRENGTH' AND status = 'ENABLED' AND validated = 'VALIDATED';
  demand(n = 1, 'The existing strength range constraint must be enabled.');

  -- DML follows ALL DDL so it can commit or roll back together. New-column SQL
  -- is dynamic to compile successfully even on the first run before columns exist.
  EXECUTE IMMEDIATE q'[
    UPDATE /*+ DISABLE_PARALLEL_DML NO_PARALLEL */ interests
       SET assessment_type = 'ROLE_DERIVED' WHERE interest_id = 'SK-001'
  ]';
  -- derived_role_code deliberately remains NULL. Do not infer a role assignment
  -- from a job title, preview selector, or old Project Manager proficiency rating.
  FOR role_row IN (SELECT role_code FROM app_roles WHERE role_code IN
    ('POD_CAPTAIN', 'POD_LEAD', 'POD_MEMBER', 'SYSTEM_ADMINISTRATOR')) LOOP
    DECLARE
      allowed_flag CHAR(1) := CASE WHEN role_row.role_code IN ('POD_LEAD', 'POD_MEMBER') THEN 'Y' ELSE 'N' END;
      scope_value VARCHAR2(20) := CASE WHEN role_row.role_code IN ('POD_LEAD', 'POD_MEMBER') THEN 'OWN' ELSE 'LOCKED' END;
    BEGIN
      UPDATE /*+ DISABLE_PARALLEL_DML NO_PARALLEL */ role_permissions
         SET access_scope = scope_value, can_view = allowed_flag, can_create = allowed_flag,
             can_update = allowed_flag, can_approve = 'N', can_export = 'N', can_administer = 'N'
       WHERE role_code = role_row.role_code AND resource_code = 'MY_SKILLS';
      IF SQL%ROWCOUNT = 0 THEN
        INSERT INTO role_permissions (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer)
        VALUES (role_row.role_code, 'MY_SKILLS', scope_value, allowed_flag, allowed_flag, allowed_flag, 'N', 'N', 'N');
      END IF;
    END;
  END LOOP;
  SELECT COUNT(*) INTO n FROM role_permissions WHERE resource_code = 'MY_SKILLS'
    AND role_code IN ('POD_LEAD','POD_MEMBER') AND access_scope = 'OWN'
    AND can_view = 'Y' AND can_create = 'Y' AND can_update = 'Y';
  demand(n = 2, 'Self-service permission verification failed.');
  COMMIT;
  DBMS_OUTPUT.PUT_LINE('SUCCESS: self-skills schema and OWN permissions committed.');
  DBMS_OUTPUT.PUT_LINE('Original ratings/evidence and all other business records retained.');
  DBMS_OUTPUT.PUT_LINE('Project Manager is role-derived; confirm the role mapping before enabling it.');
  DBMS_OUTPUT.PUT_LINE('No user-role assignments or governance tables were created.');
EXCEPTION WHEN OTHERS THEN
  ROLLBACK;
  DBMS_OUTPUT.PUT_LINE('STOP: DML rolled back; earlier DDL/backups may remain. Do not run setup.sql.');
  DBMS_OUTPUT.PUT_LINE('Keep this app stopped, resolve the reported cause, then rerun this file.');
  RAISE;
END;
/

SELECT assessment_type, COUNT(*) AS skill_count FROM interests GROUP BY assessment_type;
SELECT role_code, access_scope, can_view, can_create, can_update FROM role_permissions WHERE resource_code = 'MY_SKILLS' ORDER BY role_code;
