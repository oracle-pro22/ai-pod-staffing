-- Read-only inspection AFTER later integrated testing. No approval, assignment or schema writes.
SET SERVEROUTPUT ON;
SET LINESIZE 220;
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK;
BEGIN
  IF USER <> 'AI_POD_STAFFING' OR SYS_CONTEXT('USERENV','CURRENT_SCHEMA') <> 'AI_POD_STAFFING' THEN
    RAISE_APPLICATION_ERROR(-20001, 'Wrong schema. Stop.');
  END IF;
END;
/

SELECT decision_id,proposal_id,request_id,captain_person_id,action_type,reason,decided_at
  FROM AI_POD_STAFFING.APPROVAL_DECISIONS ORDER BY decided_at DESC FETCH FIRST 20 ROWS ONLY;

SELECT a.assignment_id,a.request_id,a.person_id,a.role_in_pod,a.status,a.assigned_hours,
       NVL(d.daily_hours,0) AS daily_hours,
       CASE WHEN a.assigned_hours=NVL(d.daily_hours,0) THEN 'PASS' ELSE 'REVIEW' END AS effort_check
  FROM AI_POD_STAFFING.POD_ASSIGNMENTS a
  LEFT JOIN (SELECT assignment_id,SUM(assigned_hours) AS daily_hours FROM AI_POD_STAFFING.ASSIGNMENT_DAYS GROUP BY assignment_id) d
    ON d.assignment_id=a.assignment_id
 ORDER BY a.created_at DESC FETCH FIRST 30 ROWS ONLY;

PROMPT The following query must return no rows: assignments linked to rejected decisions.
SELECT a.assignment_id,d.action_type FROM AI_POD_STAFFING.POD_ASSIGNMENTS a
  JOIN AI_POD_STAFFING.APPROVAL_DECISIONS d ON d.decision_id=a.decision_id
 WHERE d.action_type<>'APPROVED';

PROMPT The following query must return no rows: duplicate active assignment for one request/person.
SELECT request_id,person_id,COUNT(*) AS duplicate_count FROM AI_POD_STAFFING.POD_ASSIGNMENTS
 WHERE status='CONFIRMED' GROUP BY request_id,person_id HAVING COUNT(*)>1;

PROMPT Inspection complete. This is not a live concurrency or identity-isolation test.
