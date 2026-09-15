SET SERVEROUTPUT ON
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK
PROMPT Read-only Phase 5 verification - no migration or data changes
DECLARE
  n NUMBER;
BEGIN
  IF USER <> 'AI_POD_STAFFING' OR SYS_CONTEXT('USERENV','CURRENT_SCHEMA') <> 'AI_POD_STAFFING' THEN
    RAISE_APPLICATION_ERROR(-20001,'Wrong schema. Use the AI_POD_STAFFING connection only.');
  END IF;
  SELECT COUNT(*) INTO n FROM notification_outbox WHERE status <> 'DISABLED' OR sent_at IS NOT NULL OR attempt_count <> 0;
  IF n <> 0 THEN RAISE_APPLICATION_ERROR(-20002,'Email state changed. Review before proceeding; Phase 5 has no sender.'); END IF;
  SELECT COUNT(*) INTO n FROM pod_assignments a JOIN requests r ON r.request_id=a.request_id
   WHERE r.status='CLOSED' AND a.status='CONFIRMED';
  IF n <> 0 THEN RAISE_APPLICATION_ERROR(-20003,'Closed request still has confirmed assignments.'); END IF;
  SELECT COUNT(*) INTO n FROM pod_assignments a
   WHERE ABS(a.assigned_hours - NVL((SELECT SUM(d.assigned_hours) FROM assignment_days d WHERE d.assignment_id=a.assignment_id),0)) > 0.001;
  IF n <> 0 THEN RAISE_APPLICATION_ERROR(-20004,'Assignment/day hours differ.'); END IF;
  DBMS_OUTPUT.PUT_LINE('PASS: inspected lifecycle/outbox invariants. Not a live workflow or concurrency test.');
END;
/
SELECT status, COUNT(*) AS assignment_count FROM pod_assignments GROUP BY status;
SELECT status,last_error_code,COUNT(*) AS notification_count FROM notification_outbox GROUP BY status,last_error_code;
PROMPT Earlier Phase 4 approvals may have no outbox rows; no historical emails were backfilled.
SELECT a.request_id,a.assignment_id,a.person_id FROM pod_assignments a
 WHERE NOT EXISTS (SELECT 1 FROM notification_outbox o WHERE o.decision_id=a.decision_id AND o.recipient_person_id=a.person_id);
SELECT agents_enabled,notifications_enabled FROM staffing_runtime;
