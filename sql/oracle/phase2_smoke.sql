-- OPTIONAL Oracle constraint smoke test, after phase2_seed.sql.
-- All test DML is rolled back, including successful inserts. No DDL, COMMIT, email or model calls.
-- Stop this app's writers first. Run F5 as AI_POD_STAFFING.
SET SERVEROUTPUT ON SIZE UNLIMITED
SET DEFINE OFF
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK
DECLARE
 n NUMBER; rev NUMBER; captain VARCHAR2(30); s DATE; e DATE;
 PROCEDURE expect_error(statement_text VARCHAR2, expected NUMBER, label_text VARCHAR2) IS
 BEGIN
   EXECUTE IMMEDIATE statement_text;
   RAISE_APPLICATION_ERROR(-20190,'Expected failure did not occur: '||label_text);
 EXCEPTION WHEN OTHERS THEN
   IF SQLCODE=expected THEN DBMS_OUTPUT.PUT_LINE('PASS: '||label_text); ELSE RAISE; END IF;
 END;
BEGIN
 IF USER<>'AI_POD_STAFFING' OR SYS_CONTEXT('USERENV','SESSION_USER')<>'AI_POD_STAFFING'
 OR SYS_CONTEXT('USERENV','CURRENT_SCHEMA')<>'AI_POD_STAFFING' THEN
 RAISE_APPLICATION_ERROR(-20100,'Use AI_POD_STAFFING only.'); END IF;
 EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL DML';
 EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL QUERY';
 SAVEPOINT p2_smoke;
 SELECT COUNT(*) INTO n FROM STAFFING_RUNTIME WHERE runtime_id=1 AND agents_enabled='N' AND notifications_enabled='N';
 IF n<>1 THEN RAISE_APPLICATION_ERROR(-20191,'Disable workers and notifications before testing.'); END IF;
 SELECT request_revision,responsible_captain_id,estimated_start_date,estimated_completion_date
 INTO rev,captain,s,e FROM REQUESTS WHERE request_id='REQ-900101' AND staffing_seed_batch='AIPS_BACKEND_P2_SEED_V1';
 SELECT COUNT(*) INTO n FROM AGENT_EXECUTIONS WHERE execution_id='P2CHECK-EXEC';
 IF n<>0 THEN RAISE_APPLICATION_ERROR(-20191,'Reserved test ID already exists; nothing overwritten.'); END IF;
 INSERT INTO AGENT_EXECUTIONS(execution_id,request_id,request_revision,policy_version,idempotency_key,request_snapshot_json,created_by)
 VALUES('P2CHECK-EXEC','REQ-900101',rev,'staffing-v1-draft','P2CHECK-IDEMPOTENCY','{}','phase2-constraint-check');
 INSERT INTO POD_PROPOSALS(proposal_id,request_id,proposal_version,request_revision,execution_id,policy_version,
 responsible_captain_id,starts_on,ends_on,total_hours,lead_count,member_count,rationale,evidence_refs_json,validation_json)
 VALUES('P2CHECK-PROP','REQ-900101',999999,rev,'P2CHECK-EXEC','staffing-v1-draft',captain,s,e,24,1,2,
 'Temporary constraint test; always rolled back.','[]','{}');
 FOR i IN 2..4 LOOP
   INSERT INTO POD_PROPOSAL_MEMBERS(proposal_id,person_id,role_in_pod,selected_flag,planned_hours,score,rank_position,
     responsibilities,deliverable_ids_json,evidence_json,factors_json,person_skills_version,person_workload_version)
   SELECT 'P2CHECK-PROP',person_id,CASE WHEN i=2 THEN 'POD_LEAD' ELSE 'POD_MEMBER' END,'Y',8,80,i,
     'Constraint test','[]','{}','{}',skills_version,workload_version FROM PEOPLE WHERE person_id='P-'||TO_CHAR(900100+i,'FM999999');
 END LOOP;
 UPDATE POD_PROPOSALS SET status='READY_FOR_REVIEW' WHERE proposal_id='P2CHECK-PROP';
 DBMS_OUTPUT.PUT_LINE('PASS: valid publication count/effort transition');
 expect_error(q'~UPDATE POD_PROPOSAL_MEMBERS SET score=99 WHERE proposal_id='P2CHECK-PROP'~',-20147,'Published member evidence is frozen');
 expect_error(q'~UPDATE POD_PROPOSALS SET total_hours=25 WHERE proposal_id='P2CHECK-PROP'~',-20149,'Published proposal snapshot is frozen');
 SAVEPOINT before_stale;
 UPDATE REQUESTS SET title=title WHERE request_id='REQ-900101';
 expect_error(q'~INSERT INTO APPROVAL_DECISIONS(decision_id,proposal_id,request_id,captain_person_id,actor_subject,action_type,reason,idempotency_key)
 VALUES('P2CHECK-DEC','P2CHECK-PROP','REQ-900101','P-900101','phase2-check','REJECTED','Capacity review','P2CHECK-DECISION-IDEM')~',
 -20153,'Stale request revision blocks a decision');
 ROLLBACK TO before_stale;
 expect_error(q'~INSERT INTO APPROVAL_DECISIONS(decision_id,proposal_id,request_id,captain_person_id,actor_subject,action_type,reason,idempotency_key)
 VALUES('P2CHECK-DEC','P2CHECK-PROP','REQ-900101','P-900101','phase2-check','REJECTED','   ','P2CHECK-DECISION-IDEM')~',
 -2290,'Rejection requires a nonblank reason');
 INSERT INTO APPROVAL_DECISIONS(decision_id,proposal_id,request_id,captain_person_id,actor_subject,action_type,reason,idempotency_key)
 VALUES('P2CHECK-DEC','P2CHECK-PROP','REQ-900101','P-900101','phase2-check','REJECTED','Capacity review','P2CHECK-DECISION-IDEM');
 expect_error(q'~DELETE FROM APPROVAL_DECISIONS WHERE decision_id='P2CHECK-DEC'~',-20140,'Decision history is append-only');
 -- Temporary policy state for the FK test only; rolled back with ALL test DML below.
 UPDATE STAFFING_POLICIES SET status='APPROVED',approved_by='phase2-constraint-check',approved_at=SYSTIMESTAMP
 WHERE policy_version='staffing-v1-draft' AND status='DRAFT';
 expect_error(q'~INSERT INTO POD_ASSIGNMENTS(assignment_id,request_id,proposal_id,person_id,role_in_pod,decision_id,policy_version,starts_on,ends_on,assigned_hours)
 SELECT 'P2CHECK-ASSIGN','REQ-900101','P2CHECK-PROP','P-900102','POD_LEAD','P2CHECK-DEC',policy_version,starts_on,ends_on,8
 FROM POD_PROPOSALS WHERE proposal_id='P2CHECK-PROP'~',-2291,'Rejected decision cannot create a final assignment');
 INSERT INTO AUDIT_EVENTS(audit_event_id,entity_type,entity_id,action_type,actor_subject,correlation_id)
 VALUES('P2CHECK-AUDIT','CHECK','P2CHECK','TEST','phase2-check','P2CHECK-CORRELATION');
 expect_error(q'~UPDATE AUDIT_EVENTS SET reason='changed' WHERE audit_event_id='P2CHECK-AUDIT'~',-20140,'Audit rows are append-only');
 ROLLBACK TO p2_smoke;
 DBMS_OUTPUT.PUT_LINE('SUCCESS: Oracle constraint checks passed. All temporary DML rolled back; no assignments remain.');
EXCEPTION WHEN OTHERS THEN
 ROLLBACK;
 DBMS_OUTPUT.PUT_LINE('Constraint check failed; test DML rolled back. Keep the application stopped and report the error.');
 RAISE;
END;
/
