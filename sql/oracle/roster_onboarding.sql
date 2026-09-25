-- Real-roster Phase 3/4 additive structures. No accounts are enrolled or removed.
-- Stop app writers and disable agent/notification switches. Run as AI_POD_STAFFING (F5).
SET SERVEROUTPUT ON
SET DEFINE OFF
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK
DECLARE
  n NUMBER;
  PROCEDURE install(name VARCHAR2, ddl VARCHAR2) IS
  BEGIN
    SELECT COUNT(*) INTO n FROM user_objects WHERE object_name=name;
    IF n=0 THEN EXECUTE IMMEDIATE ddl;
    ELSE
      SELECT COUNT(*) INTO n FROM user_tables WHERE table_name=name;
      IF n<>1 THEN RAISE_APPLICATION_ERROR(-20350,'Unexpected object: '||name); END IF;
    END IF;
  END;
BEGIN
  IF USER<>'AI_POD_STAFFING' OR SYS_CONTEXT('USERENV','CURRENT_SCHEMA')<>'AI_POD_STAFFING' THEN
    RAISE_APPLICATION_ERROR(-20350,'Use AI_POD_STAFFING only.'); END IF;
  SELECT COUNT(*) INTO n FROM staffing_runtime WHERE runtime_id=1 AND agents_enabled='N' AND notifications_enabled='N';
  IF n<>1 THEN RAISE_APPLICATION_ERROR(-20350,'Stop writers and disable runtime switches first.'); END IF;
  SELECT COUNT(*) INTO n FROM agent_executions WHERE status IN ('QUEUED','RUNNING');
  IF n<>0 THEN RAISE_APPLICATION_ERROR(-20350,'Resolve queued/running executions first.'); END IF;
  install('ROSTER_ACCESS_CONTROL',q'~CREATE TABLE roster_access_control (
    control_id NUMBER PRIMARY KEY CHECK(control_id=1), revision NUMBER DEFAULT 1 NOT NULL CHECK(revision>=1))~');
  install('ROSTER_ONBOARDING',q'~CREATE TABLE roster_onboarding (
    person_id VARCHAR2(30) PRIMARY KEY REFERENCES people(person_id),
    status VARCHAR2(12) DEFAULT 'DRAFT' NOT NULL CHECK(status IN ('DRAFT','REVIEW','COMPLETE')),
    revision NUMBER DEFAULT 1 NOT NULL CHECK(revision>=1),
    submitted_json CLOB CHECK(submitted_json IS JSON),
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL)~');
  install('ROSTER_POD_CLAIMS',q'~CREATE TABLE roster_pod_claims (
    claim_id VARCHAR2(30) PRIMARY KEY,
    person_id VARCHAR2(30) NOT NULL REFERENCES roster_onboarding(person_id),
    title VARCHAR2(500) NOT NULL, starts_on DATE NOT NULL, ends_on DATE NOT NULL,
    total_hours NUMBER(10,2) NOT NULL CHECK(total_hours>0),
    role_code VARCHAR2(20) NOT NULL CHECK(role_code IN ('POD_LEAD','POD_MEMBER')),
    status VARCHAR2(12) DEFAULT 'PENDING' NOT NULL CHECK(status IN ('PENDING','LINKED','DISMISSED')),
    assignment_id VARCHAR2(30) UNIQUE REFERENCES pod_assignments(assignment_id),
    reviewed_by VARCHAR2(255), review_reason VARCHAR2(2000), reviewed_at TIMESTAMP WITH TIME ZONE,
    CHECK(ends_on>=starts_on),
    CHECK((status='LINKED' AND assignment_id IS NOT NULL) OR (status<>'LINKED' AND assignment_id IS NULL)))~');
  install('ROSTER_RESET_RUNS',q'~CREATE TABLE roster_reset_runs (
    batch_id VARCHAR2(30) PRIMARY KEY,
    status VARCHAR2(20) NOT NULL CHECK(status IN ('PREPARING','ARCHIVED','REHEARSED','RESET','RESTORED')),
    metadata_json CLOB NOT NULL CHECK(metadata_json IS JSON),
    operator_name VARCHAR2(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL)~');
  EXECUTE IMMEDIATE 'MERGE INTO roster_access_control d USING(SELECT 1 id FROM dual) s ON(d.control_id=s.id)
    WHEN NOT MATCHED THEN INSERT(control_id,revision) VALUES(1,1)';
  COMMIT;
  DBMS_OUTPUT.PUT_LINE('Roster onboarding/recovery structures prepared. Existing accounts/data unchanged.');
  DBMS_OUTPUT.PUT_LINE('Run python -m app.onboarding_schema --env-file .env before restarting.');
END;
/
