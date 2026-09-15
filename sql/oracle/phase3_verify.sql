-- Read-only phase-3 inspection. This does not queue work or contact OCI.
SET SERVEROUTPUT ON;
SET LINESIZE 220;
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK;
BEGIN
  IF USER <> 'AI_POD_STAFFING'
     OR SYS_CONTEXT('USERENV','CURRENT_SCHEMA') <> 'AI_POD_STAFFING' THEN
    RAISE_APPLICATION_ERROR(-20001, 'Wrong schema. Stop.');
  END IF;
END;
/

SELECT agents_enabled, notifications_enabled FROM AI_POD_STAFFING.STAFFING_RUNTIME WHERE runtime_id=1;

SELECT execution_id,request_id,request_revision,status,attempt_count,last_error_code
  FROM AI_POD_STAFFING.AGENT_EXECUTIONS
 WHERE prompt_version='staffing-tools-v1'
 ORDER BY created_at DESC FETCH FIRST 30 ROWS ONLY;

SELECT p.proposal_id,p.request_id,p.proposal_version,p.status,p.total_hours,
       COUNT(m.person_id) AS selected_people,SUM(m.planned_hours) AS selected_hours
  FROM AI_POD_STAFFING.POD_PROPOSALS p
  JOIN AI_POD_STAFFING.AGENT_EXECUTIONS e ON e.execution_id=p.execution_id
  LEFT JOIN AI_POD_STAFFING.POD_PROPOSAL_MEMBERS m ON m.proposal_id=p.proposal_id AND m.selected_flag='Y'
 WHERE e.prompt_version='staffing-tools-v1'
 GROUP BY p.proposal_id,p.request_id,p.proposal_version,p.status,p.total_hours
 ORDER BY p.request_id,p.proposal_version;

PROMPT The counts below should be zero during isolated phase-3 proposal testing, before phase-4 approval.
SELECT 'ASSIGNMENTS' AS record_type,COUNT(*) AS row_count
  FROM AI_POD_STAFFING.POD_ASSIGNMENTS a JOIN AI_POD_STAFFING.POD_PROPOSALS p ON p.proposal_id=a.proposal_id
  JOIN AI_POD_STAFFING.AGENT_EXECUTIONS e ON e.execution_id=p.execution_id
 WHERE e.prompt_version='staffing-tools-v1'
UNION ALL
SELECT 'DECISIONS',COUNT(*)
  FROM AI_POD_STAFFING.APPROVAL_DECISIONS d JOIN AI_POD_STAFFING.POD_PROPOSALS p ON p.proposal_id=d.proposal_id
  JOIN AI_POD_STAFFING.AGENT_EXECUTIONS e ON e.execution_id=p.execution_id
 WHERE e.prompt_version='staffing-tools-v1';

PROMPT Inspection complete. This is not an Oracle concurrency test or an OCI model validation.
