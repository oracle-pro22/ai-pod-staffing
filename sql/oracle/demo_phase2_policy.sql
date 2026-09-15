-- Run as a script (F5) in SQL Developer, connected as AI_POD_STAFFING.
-- Additive DML only: no schema changes, old policy edits, assignment edits,
-- worker enablement or notification enablement. One transaction, safe to rerun.
-- First run creates/verifies the DRAFT. After reviewing the documented rules,
-- set approve_policy to TRUE and replace approval_operator with your own name.
SET SERVEROUTPUT ON
SET DEFINE OFF
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK

DECLARE
  approve_policy CONSTANT BOOLEAN := TRUE;
  approval_operator CONSTANT VARCHAR2(255) := 'smaikoti';
  version_text CONSTANT VARCHAR2(60) := 'staffing-demo-v2';
  owner_text CONSTANT VARCHAR2(255) := 'ai-pod-staffing/demo-phase2';
  description_text CONSTANT VARCHAR2(1000) :=
    'Demonstration scheduling v2: use available weekdays; minimum contribution is the greater of 1 hour and 50 percent of an equal team share; exact total effort; maximum 100 percent of absence-adjusted weekly capacity; skill/deliverable/capacity/interest weights 50/30/15/5. Captain approval is final; rejection requires a reason.';
  step_json CONSTANT VARCHAR2(1000) :=
    '{"value":12,"scheduling":{"algorithm":"available-days-v2","minimum_member_hours":1,"minimum_equal_share_pct":50}}';
  n NUMBER;
  current_status VARCHAR2(12);
  PROCEDURE demand(ok BOOLEAN, message_text VARCHAR2) IS
  BEGIN
    IF NOT ok OR ok IS NULL THEN RAISE_APPLICATION_ERROR(-20220, message_text); END IF;
  END;
BEGIN
  demand(USER = 'AI_POD_STAFFING', 'Connect as AI_POD_STAFFING; no changes applied.');
  IF approve_policy THEN
    demand(TRIM(approval_operator) IS NOT NULL AND approval_operator <> 'REPLACE_WITH_YOUR_NAME',
      'Review the policy and supply the real operator name before approving.');
  END IF;
  SELECT COUNT(*) INTO n FROM staffing_runtime
    WHERE runtime_id=1 AND agents_enabled='N' AND notifications_enabled='N';
  demand(n=1, 'Stop services and disable agents/notifications before installing this policy.');
  SELECT COUNT(*) INTO n FROM agent_executions WHERE status IN ('QUEUED','RUNNING');
  demand(n=0, 'Queued/running executions exist; finish or cancel them through the application first.');
  LOCK TABLE staffing_policies IN EXCLUSIVE MODE NOWAIT;
  LOCK TABLE eligibility_rules IN EXCLUSIVE MODE NOWAIT;
  LOCK TABLE load_guardrails IN EXCLUSIVE MODE NOWAIT;
  LOCK TABLE scoring_weights IN EXCLUSIVE MODE NOWAIT;
  SELECT COUNT(*) INTO n FROM staffing_policies WHERE policy_version=version_text;
  IF n=0 THEN
    INSERT INTO staffing_policies(policy_version,status,description,created_by)
      VALUES(version_text,'DRAFT',description_text,owner_text);
    INSERT INTO eligibility_rules(policy_version,rule_code,rule_value_json)
      VALUES(version_text,'MINIMUM_STRENGTH','{"value":3}');
    INSERT INTO eligibility_rules(policy_version,rule_code,rule_value_json)
      VALUES(version_text,'LEAD_ROLE','{"value":"POD_LEAD"}');
    INSERT INTO eligibility_rules(policy_version,rule_code,rule_value_json)
      VALUES(version_text,'MEMBER_ROLES','{"value":["POD_MEMBER","POD_LEAD"]}');
    INSERT INTO eligibility_rules(policy_version,rule_code,rule_value_json)
      VALUES(version_text,'MAX_AGENT_STEPS',step_json);
    INSERT INTO load_guardrails(policy_version,default_weekly_hours,maximum_allocation_pct,scheduling_timezone)
      VALUES(version_text,40,100,'Asia/Kolkata');
    INSERT INTO scoring_weights(policy_version,skill_weight,deliverable_weight,capacity_weight,interest_weight)
      VALUES(version_text,50,30,15,5);
  END IF;

  -- Never overwrite an existing version, even if it is still a draft.
  SELECT COUNT(*) INTO n FROM staffing_policies WHERE policy_version=version_text
    AND description=description_text AND created_by=owner_text AND status IN ('DRAFT','APPROVED');
  demand(n=1, 'Policy version already exists with different metadata; nothing was overwritten.');
  SELECT COUNT(*) INTO n FROM eligibility_rules WHERE policy_version=version_text;
  demand(n=4, 'Policy has unexpected eligibility rules; nothing was overwritten.');
  SELECT COUNT(*) INTO n FROM eligibility_rules WHERE policy_version=version_text AND (
    (rule_code='MINIMUM_STRENGTH' AND DBMS_LOB.COMPARE(rule_value_json,TO_CLOB('{"value":3}'))=0)
    OR (rule_code='LEAD_ROLE' AND DBMS_LOB.COMPARE(rule_value_json,TO_CLOB('{"value":"POD_LEAD"}'))=0)
    OR (rule_code='MEMBER_ROLES' AND DBMS_LOB.COMPARE(rule_value_json,TO_CLOB('{"value":["POD_MEMBER","POD_LEAD"]}'))=0)
    OR (rule_code='MAX_AGENT_STEPS' AND DBMS_LOB.COMPARE(rule_value_json,TO_CLOB(step_json))=0));
  demand(n=4, 'Policy JSON does not match this reviewed version; nothing was overwritten.');
  SELECT COUNT(*) INTO n FROM load_guardrails WHERE policy_version=version_text
    AND default_weekly_hours=40 AND maximum_allocation_pct=100 AND scheduling_timezone='Asia/Kolkata';
  demand(n=1, 'Policy load guardrails differ; nothing was overwritten.');
  SELECT COUNT(*) INTO n FROM scoring_weights WHERE policy_version=version_text
    AND skill_weight=50 AND deliverable_weight=30 AND capacity_weight=15 AND interest_weight=5;
  demand(n=1, 'Policy weights differ; nothing was overwritten.');
  SELECT status INTO current_status FROM staffing_policies WHERE policy_version=version_text;
  IF approve_policy AND current_status='DRAFT' THEN
    UPDATE staffing_policies SET status='APPROVED',approved_by=TRIM(approval_operator),approved_at=SYSTIMESTAMP
      WHERE policy_version=version_text AND status='DRAFT';
    current_status := 'APPROVED';
  END IF;
  COMMIT;
  DBMS_OUTPUT.PUT_LINE('SUCCESS: staffing-demo-v2 verified, status=' || current_status || '.');
  DBMS_OUTPUT.PUT_LINE('Original policies, projects and assignments unchanged. Agent and email switches remain OFF.');
  IF current_status='DRAFT' THEN
    DBMS_OUTPUT.PUT_LINE('Review the rules; explicitly approve with your operator name before testing final assignment.');
  ELSE
    DBMS_OUTPUT.PUT_LINE('Set STAFFING_POLICY_VERSION=staffing-demo-v2 in backend/python/.env, then restart the API and worker when ready.');
  END IF;
EXCEPTION WHEN OTHERS THEN
  ROLLBACK;
  DBMS_OUTPUT.PUT_LINE('STOP: this policy transaction rolled back. No schema changes were attempted.');
  RAISE;
END;
/

SELECT policy_version,status,approved_by,approved_at
FROM staffing_policies
WHERE policy_version IN ('staffing-v1-draft','staffing-baseline-v1','staffing-demo-v2')
ORDER BY policy_version;
