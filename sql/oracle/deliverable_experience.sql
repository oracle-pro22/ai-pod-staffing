-- Run with F5 in a NEW AIPOD SQL Developer worksheet/session, as AI_POD_STAFFING.
-- Prerequisite: self_skills.sql completed. Stop this application's writers first.
-- Additive and resumable. No tables/data are dropped, reloaded, or overwritten.
-- Oracle DDL commits automatically; ROLLBACK does not remove an added column.
SET SERVEROUTPUT ON
SET DEFINE OFF
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK
PROMPT Preparing deliverable experience on PEOPLE

DECLARE
  n NUMBER;
  condition_text VARCHAR2(4000);
  PROCEDURE demand(ok BOOLEAN, message VARCHAR2) IS
  BEGIN
    IF ok IS NULL OR NOT ok THEN RAISE_APPLICATION_ERROR(-20001, message); END IF;
  END;
BEGIN
  demand(USER = 'AI_POD_STAFFING'
    AND SYS_CONTEXT('USERENV', 'SESSION_USER') = 'AI_POD_STAFFING'
    AND SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') = 'AI_POD_STAFFING',
    'STOP: connect directly as AI_POD_STAFFING, not ADMIN or another schema.');
  EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL DML';
  EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL QUERY';
  EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL DDL';
  SELECT COUNT(*) INTO n FROM user_tab_columns
    WHERE table_name = 'PEOPLE' AND column_name = 'SKILLS_VERSION' AND data_type = 'NUMBER';
  demand(n = 1, 'Apply self_skills.sql first.');
  SELECT COUNT(*) INTO n FROM user_tab_columns
    WHERE table_name = 'DELIVERABLES' AND column_name = 'ACTIVE_FLAG';
  demand(n = 1, 'Apply the official catalogue migration first.');
  SELECT COUNT(*) INTO n FROM user_tab_columns
    WHERE table_name = 'PEOPLE' AND column_name = 'DELIVERABLE_EXPERIENCE_JSON';
  IF n = 0 THEN
    EXECUTE IMMEDIATE 'ALTER TABLE AI_POD_STAFFING.PEOPLE ADD (DELIVERABLE_EXPERIENCE_JSON CLOB)';
  END IF;
  SELECT COUNT(*) INTO n FROM user_tab_columns WHERE table_name = 'PEOPLE'
    AND column_name = 'DELIVERABLE_EXPERIENCE_JSON' AND data_type = 'CLOB' AND nullable = 'Y';
  demand(n = 1, 'Existing DELIVERABLE_EXPERIENCE_JSON has an unexpected definition. Stop and review.');
  SELECT COUNT(*) INTO n FROM user_constraints WHERE constraint_name = 'CK_PEOPLE_DELIV_EXP_JSON';
  IF n = 0 THEN
    EXECUTE IMMEDIATE 'ALTER TABLE AI_POD_STAFFING.PEOPLE ADD CONSTRAINT CK_PEOPLE_DELIV_EXP_JSON CHECK (DELIVERABLE_EXPERIENCE_JSON IS JSON)';
  END IF;
  SELECT COUNT(*), MAX(search_condition_vc) INTO n, condition_text FROM user_constraints
    WHERE constraint_name = 'CK_PEOPLE_DELIV_EXP_JSON' AND table_name = 'PEOPLE'
      AND constraint_type = 'C' AND status = 'ENABLED' AND validated = 'VALIDATED';
  demand(n = 1 AND REGEXP_REPLACE(UPPER(condition_text), '[[:space:]"()]', '') = 'DELIVERABLE_EXPERIENCE_JSONISJSON',
    'Existing JSON constraint needs review. No data was changed by this script.');
  DBMS_OUTPUT.PUT_LINE('SUCCESS: deliverable experience is ready. Existing people and skill ratings retained.');
  DBMS_OUTPUT.PUT_LINE('No new business/governance tables or role assignments created.');
END;
/

-- Verification only; existing profiles can have NULL (the application treats it as []).
SELECT column_name, data_type, nullable FROM user_tab_columns
 WHERE table_name = 'PEOPLE' AND column_name IN ('SKILLS_VERSION', 'DELIVERABLE_EXPERIENCE_JSON');
