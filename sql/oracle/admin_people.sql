-- Run with F5 in SQL Developer as AI_POD_STAFFING, not ADMIN.
-- Stop ONLY AI Pod Staffing writers first (including other local/VM copies).
-- Use a fresh worksheet connection with no pending work: Oracle DDL commits.
-- Resumable. Never drops tables/data or changes another schema.
SET SERVEROUTPUT ON
SET DEFINE OFF
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK
PROMPT Preparing Administrator access and people creation

DECLARE
  n NUMBER;
  max_id NUMBER;
  next_id NUMBER;
  cache_count NUMBER;
  increment_size NUMBER;
  cycle_value VARCHAR2(1);
  expr LONG;
  PROCEDURE demand(ok BOOLEAN, message VARCHAR2) IS
  BEGIN IF ok IS NULL OR NOT ok THEN RAISE_APPLICATION_ERROR(-20001, message); END IF; END;
BEGIN
  demand(USER = 'AI_POD_STAFFING' AND SYS_CONTEXT('USERENV','SESSION_USER') = 'AI_POD_STAFFING'
    AND SYS_CONTEXT('USERENV','CURRENT_SCHEMA') = 'AI_POD_STAFFING', 'Use the AI_POD_STAFFING connection only.');
  -- This session only: prevent sibling PDML transactions on shared Autonomous DB.
  EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL DML';
  EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL QUERY';
  EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL DDL';
  SELECT COUNT(*) INTO n FROM app_roles WHERE role_code='SYSTEM_ADMINISTRATOR' AND role_name='Administrator' AND active_flag='Y';
  demand(n=1, 'Apply the official profiles migration first.');
  SELECT COUNT(*) INTO n FROM role_permissions WHERE role_code='SYSTEM_ADMINISTRATOR';
  demand(n=12, 'Unexpected Administrator permission baseline. Review before continuing.');
  SELECT COUNT(*) INTO n FROM role_permissions WHERE role_code='SYSTEM_ADMINISTRATOR' AND resource_code IN
    ('DASHBOARD','REQUESTS','AI_FITMENT','ALLOCATION_CALENDAR','TEAM_SKILLS','MY_AVAILABILITY',
     'AGENT_EXECUTION','REPORTS','ADMINISTRATION','PROJECT_CLOSURE','ACCESS_MANAGEMENT','BACKEND_CONFIGURATION');
  demand(n=12, 'Unexpected permission resources.');
  SELECT COUNT(*) INTO n FROM user_tab_columns WHERE table_name='PEOPLE' AND column_name IN
    ('PERSON_ID','FULL_NAME','INITIALS','JOB_TITLE','LOCATION','ALLOCATION_PCT','ACTIVE_PODS','EMAIL_ADDRESS','ACTIVE_FLAG');
  demand(n=9, 'The enhanced PEOPLE table is required.');
  SELECT COUNT(*) INTO n FROM (
    SELECT LOWER(TRIM(email_address)) FROM people WHERE TRIM(email_address) IS NOT NULL
    GROUP BY LOWER(TRIM(email_address)) HAVING COUNT(*)>1);
  demand(n=0, 'Duplicate emails exist ignoring case/outer spaces. Resolve them manually; no people were changed.');
  SELECT NVL(MAX(CASE WHEN REGEXP_LIKE(person_id,'^P-[0-9]+$') THEN TO_NUMBER(SUBSTR(person_id,3)) END),0)
    INTO max_id FROM people;
  demand(max_id < 9999999999999999999999999999, 'Person ID range exhausted.');

  SELECT COUNT(*) INTO n FROM user_objects WHERE object_name='PERSON_ID_SEQ';
  IF n>0 THEN
    SELECT COUNT(*) INTO n FROM user_sequences WHERE sequence_name='PERSON_ID_SEQ';
    demand(n=1, 'PERSON_ID_SEQ exists but is not a sequence.');
    SELECT last_number, cache_size, increment_by, cycle_flag INTO next_id, cache_count, increment_size, cycle_value
      FROM user_sequences WHERE sequence_name='PERSON_ID_SEQ';
    demand(cache_count=0 AND increment_size=1 AND cycle_value='N' AND next_id>max_id,
      'Existing PERSON_ID_SEQ is not safe. Do not reset it; review its settings and existing IDs.');
  END IF;

  SELECT COUNT(*) INTO n FROM user_indexes WHERE index_name='UQ_PEOPLE_EMAIL_CI';
  IF n>0 THEN
    SELECT COUNT(*) INTO n FROM user_indexes WHERE index_name='UQ_PEOPLE_EMAIL_CI' AND table_name='PEOPLE' AND uniqueness='UNIQUE';
    demand(n=1, 'Unexpected UQ_PEOPLE_EMAIL_CI index.');
    SELECT COUNT(*) INTO n FROM user_ind_columns WHERE index_name='UQ_PEOPLE_EMAIL_CI';
    demand(n=1, 'Unexpected email index columns.');
    SELECT column_expression INTO expr FROM user_ind_expressions WHERE index_name='UQ_PEOPLE_EMAIL_CI' AND column_position=1;
    demand(REPLACE(expr,' ','')='LOWER(TRIM("EMAIL_ADDRESS"))', 'Unexpected email index expression.');
  END IF;

  SELECT COUNT(*) INTO n FROM user_objects WHERE object_name='AIPS_BK_ADMIN_ACCESS';
  IF n=0 THEN
    EXECUTE IMMEDIATE 'CREATE TABLE AIPS_BK_ADMIN_ACCESS AS SELECT * FROM role_permissions WHERE role_code=''SYSTEM_ADMINISTRATOR''';
    DBMS_OUTPUT.PUT_LINE('Original Administrator permissions backed up.');
  END IF;
  EXECUTE IMMEDIATE 'SELECT COUNT(*) FROM AIPS_BK_ADMIN_ACCESS' INTO n;
  demand(n=12, 'Unexpected Administrator backup. Stop and inspect.');
  EXECUTE IMMEDIATE 'SELECT COUNT(DISTINCT resource_code) FROM AIPS_BK_ADMIN_ACCESS WHERE role_code=''SYSTEM_ADMINISTRATOR''' INTO n;
  demand(n=12, 'Unexpected Administrator backup keys.');

  SELECT COUNT(*) INTO n FROM user_sequences WHERE sequence_name='PERSON_ID_SEQ';
  IF n=0 THEN
    EXECUTE IMMEDIATE 'CREATE SEQUENCE PERSON_ID_SEQ START WITH ' || TO_CHAR(max_id+1,'TM9') || ' INCREMENT BY 1 NOCACHE NOCYCLE';
    DBMS_OUTPUT.PUT_LINE('Person ID sequence created above existing numeric IDs.');
  END IF;
  SELECT COUNT(*) INTO n FROM user_indexes WHERE index_name='UQ_PEOPLE_EMAIL_CI';
  IF n=0 THEN
    EXECUTE IMMEDIATE 'CREATE UNIQUE INDEX UQ_PEOPLE_EMAIL_CI ON PEOPLE (LOWER(TRIM(email_address)))';
  END IF;
END;
/

-- Only view/scope and TEAM_SKILLS create are changed. Existing approval/export/
-- request-create flags and all other profiles remain unchanged.
DECLARE
  n NUMBER;
BEGIN
  IF USER<>'AI_POD_STAFFING' OR SYS_CONTEXT('USERENV','SESSION_USER')<>'AI_POD_STAFFING'
    OR SYS_CONTEXT('USERENV','CURRENT_SCHEMA')<>'AI_POD_STAFFING' THEN
    RAISE_APPLICATION_ERROR(-20001,'Use AI_POD_STAFFING only.');
  END IF;
  EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL DML';
  EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL QUERY';
  -- Set TEAM_SKILLS create in the same statement; do not update it twice.
  UPDATE /*+ DISABLE_PARALLEL_DML NO_PARALLEL */ role_permissions
    SET can_view='Y', access_scope='FULL',
        can_create=CASE WHEN resource_code='TEAM_SKILLS' THEN 'Y' ELSE can_create END
    WHERE role_code='SYSTEM_ADMINISTRATOR'
      AND resource_code IN ('DASHBOARD','REQUESTS','AI_FITMENT','ALLOCATION_CALENDAR','TEAM_SKILLS','MY_AVAILABILITY',
        'AGENT_EXECUTION','REPORTS','ADMINISTRATION','PROJECT_CLOSURE','ACCESS_MANAGEMENT','BACKEND_CONFIGURATION');
  IF SQL%ROWCOUNT<>12 THEN RAISE_APPLICATION_ERROR(-20002,'Unexpected permission count.'); END IF;
  SELECT COUNT(*) INTO n FROM role_permissions
    WHERE role_code='SYSTEM_ADMINISTRATOR' AND can_view='Y' AND access_scope='FULL';
  IF n<>12 THEN RAISE_APPLICATION_ERROR(-20003,'Administrator view verification failed.'); END IF;
  SELECT COUNT(*) INTO n FROM role_permissions
    WHERE role_code='SYSTEM_ADMINISTRATOR' AND resource_code='TEAM_SKILLS' AND can_create='Y';
  IF n<>1 THEN RAISE_APPLICATION_ERROR(-20004,'People permission verification failed.'); END IF;
  COMMIT;
  DBMS_OUTPUT.PUT_LINE('SUCCESS: Administrator can view all sections and add people.');
  DBMS_OUTPUT.PUT_LINE('No people or catalogue data changed. Keep AIPS_BK_ADMIN_ACCESS for recovery.');
EXCEPTION WHEN OTHERS THEN ROLLBACK; RAISE;
END;
/
