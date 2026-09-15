-- Run with F5 in SQL Developer as AI_POD_STAFFING, with API and worker stopped.
-- Additive migration: existing policy, proposals, assignments and schedules are retained.
SET SERVEROUTPUT ON
SET DEFINE OFF
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK
ALTER SESSION DISABLE PARALLEL DML;
ALTER SESSION DISABLE PARALLEL QUERY;
DECLARE
  n NUMBER;
BEGIN
  IF USER <> 'AI_POD_STAFFING' OR SYS_CONTEXT('USERENV','CURRENT_SCHEMA') <> 'AI_POD_STAFFING' THEN
    RAISE_APPLICATION_ERROR(-20001,'Connect as AI_POD_STAFFING.');
  END IF;
  SELECT COUNT(*) INTO n FROM user_tables WHERE table_name='STAFFING_POLICY_CONTROL';
  IF n=0 THEN
    EXECUTE IMMEDIATE 'CREATE TABLE staffing_policy_control (
      control_id NUMBER(1) PRIMARY KEY CHECK (control_id=1),
      policy_version VARCHAR2(60) NOT NULL,
      policy_status VARCHAR2(12) DEFAULT ''APPROVED'' NOT NULL CHECK (policy_status=''APPROVED''),
      updated_by VARCHAR2(255) NOT NULL,
      updated_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
      FOREIGN KEY (policy_version,policy_status) REFERENCES staffing_policies(policy_version,status))';
  END IF;
END;
/
DECLARE
  n NUMBER;
  source_version CONSTANT VARCHAR2(60) := 'staffing-demo-v2';
  target_version CONSTANT VARCHAR2(60) := 'staffing-utilization-v1';
BEGIN
  SELECT COUNT(*) INTO n FROM staffing_policy_control WHERE control_id=1;
  IF n=1 THEN
    DBMS_OUTPUT.PUT_LINE('Already installed. Administrator changes were NOT overwritten.');
    RETURN;
  END IF;
  SELECT COUNT(*) INTO n FROM staffing_policies WHERE policy_version=source_version AND status='APPROVED';
  IF n<>1 THEN RAISE_APPLICATION_ERROR(-20002,'Approved staffing-demo-v2 source policy is required.'); END IF;
  SELECT COUNT(*) INTO n FROM staffing_policies WHERE policy_version=target_version;
  IF n<>0 THEN RAISE_APPLICATION_ERROR(-20003,'Target policy exists without its pointer. Inspect before retrying.'); END IF;
  INSERT INTO staffing_policies(policy_version,status,description,created_by)
    VALUES(target_version,'DRAFT','85 percent maximum utilization: daily, request period and complete weeks.',USER);
  INSERT INTO eligibility_rules(policy_version,rule_code,rule_value_json)
    SELECT target_version,rule_code,rule_value_json FROM eligibility_rules WHERE policy_version=source_version;
  IF SQL%ROWCOUNT<>4 THEN RAISE_APPLICATION_ERROR(-20006,'Expected four source eligibility rules.'); END IF;
  INSERT INTO scoring_weights(policy_version,skill_weight,deliverable_weight,capacity_weight,interest_weight)
    SELECT target_version,skill_weight,deliverable_weight,capacity_weight,interest_weight
    FROM scoring_weights WHERE policy_version=source_version;
  IF SQL%ROWCOUNT<>1 THEN RAISE_APPLICATION_ERROR(-20004,'Missing source scoring weights.'); END IF;
  INSERT INTO load_guardrails(policy_version,default_weekly_hours,maximum_allocation_pct,scheduling_timezone)
    SELECT target_version,default_weekly_hours,85,scheduling_timezone
    FROM load_guardrails WHERE policy_version=source_version;
  IF SQL%ROWCOUNT<>1 THEN RAISE_APPLICATION_ERROR(-20005,'Missing source load guardrail.'); END IF;
  UPDATE staffing_policies SET status='APPROVED',approved_by=USER,approved_at=SYSTIMESTAMP
    WHERE policy_version=target_version;
  INSERT INTO staffing_policy_control(control_id,policy_version,updated_by) VALUES(1,target_version,USER);
  INSERT INTO audit_events(audit_event_id,entity_type,entity_id,action_type,actor_subject,correlation_id,after_state_json,reason)
    VALUES(RAWTOHEX(SYS_GUID()),'STAFFING_POLICY',target_version,'UTILIZATION_LIMIT_CHANGED',USER,RAWTOHEX(SYS_GUID()),
      '{"previous_policy_version":"staffing-demo-v2","before_maximum_pct":100,"maximum_pct":85}',
      'Restore the requested 85 percent utilization limit; enable Administrator editing.');
  COMMIT;
  DBMS_OUTPUT.PUT_LINE('SUCCESS: 85% policy activated. Existing assignments and history retained.');
EXCEPTION WHEN OTHERS THEN
  ROLLBACK;
  DBMS_OUTPUT.PUT_LINE('Policy DML rolled back. Additive control table, if created, remains; do not drop existing tables.');
  RAISE;
END;
/
SELECT c.policy_version,p.status,l.maximum_allocation_pct,c.updated_by
FROM staffing_policy_control c JOIN staffing_policies p ON p.policy_version=c.policy_version
JOIN load_guardrails l ON l.policy_version=c.policy_version WHERE c.control_id=1;
