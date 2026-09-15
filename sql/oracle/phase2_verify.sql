-- Read-only verification. Run F5 as AI_POD_STAFFING after phase2.sql.
SET SERVEROUTPUT ON SIZE UNLIMITED
SET DEFINE OFF
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK
DECLARE
 n NUMBER; current_hash VARCHAR2(64); ddl_text CLOB;
 PROCEDURE demand(ok BOOLEAN,msg VARCHAR2) IS
 BEGIN IF ok IS NULL OR NOT ok THEN RAISE_APPLICATION_ERROR(-20160,msg); END IF; END;
BEGIN
 IF USER<>'AI_POD_STAFFING' OR SYS_CONTEXT('USERENV','SESSION_USER')<>'AI_POD_STAFFING'
 OR SYS_CONTEXT('USERENV','CURRENT_SCHEMA')<>'AI_POD_STAFFING' THEN
 RAISE_APPLICATION_ERROR(-20100,'Use AI_POD_STAFFING only.'); END IF;
 DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM,'SEGMENT_ATTRIBUTES',FALSE);
 DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM,'STORAGE',FALSE);
 DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM,'SQLTERMINATOR',FALSE);
 SELECT COUNT(*) INTO n FROM AIPS_P2_MIGRATION WHERE object_type IN ('TABLE','INDEX','TRIGGER') AND state='APPLIED';
 demand(n=45,'Some migration steps are incomplete.');
 FOR r IN (SELECT * FROM AIPS_P2_MIGRATION WHERE object_type IN ('TABLE','INDEX','TRIGGER')) LOOP
   ddl_text:=DBMS_METADATA.GET_DDL(r.object_type,r.object_name,'AI_POD_STAFFING');
   demand(DBMS_LOB.GETLENGTH(ddl_text)<=32767,'Metadata too long: '||r.object_name);
   SELECT LOWER(RAWTOHEX(STANDARD_HASH(DBMS_LOB.SUBSTR(ddl_text,32767,1),'SHA256'))) INTO current_hash FROM dual;
   demand(current_hash=r.after_hash,'Schema drift: '||r.object_name);
 END LOOP;
 SELECT COUNT(*) INTO n FROM user_constraints
 WHERE table_name IN ('STAFFING_POLICIES','ELIGIBILITY_RULES','LOAD_GUARDRAILS','SCORING_WEIGHTS','AGENT_EXECUTIONS','AGENT_EXECUTION_EVENTS','POD_PROPOSALS','POD_PROPOSAL_MEMBERS','APPROVAL_DECISIONS','POD_ASSIGNMENTS','ASSIGNMENT_DAYS','PERSON_CAPACITY_DAYS','AUDIT_EVENTS','NOTIFICATION_OUTBOX','STAFFING_RUNTIME')
 AND (status<>'ENABLED' OR validated<>'VALIDATED');
 demand(n=0,'A new table has a disabled/unvalidated constraint.');
 SELECT COUNT(*) INTO n FROM user_objects WHERE object_name IN
 ('P2_AUDIT_APPEND','P2_DECISION_APPEND','P2_EVENT_APPEND','P2_RULE_FREEZE','P2_LOAD_FREEZE','P2_WEIGHT_FREEZE','P2_POLICY_FREEZE','P2_MEMBER_FREEZE','P2_REQUEST_REVISION','P2_AVAIL_VERSION','P2_CAPACITY_VERSION','P2_DAY_VERSION','P2_ASSIGN_VERSION','P2_PROPOSAL_FREEZE','P2_DECISION_REVIEW','P2_DAY_BOUNDS') AND status<>'VALID';
 demand(n=0,'A phase-2 trigger is invalid. Inspect USER_ERRORS.');
 SELECT COUNT(*) INTO n FROM STAFFING_RUNTIME WHERE runtime_id=1;
 demand(n=1,'Runtime control row is missing.');
 SELECT COUNT(*) INTO n FROM STAFFING_POLICIES WHERE policy_version='staffing-v1-draft';
 demand(n=1,'Initial policy is missing.');
 SELECT COUNT(*) INTO n FROM ELIGIBILITY_RULES WHERE policy_version='staffing-v1-draft';
 demand(n=4,'Initial policy rule set is incomplete.');
 SELECT COUNT(*) INTO n FROM LOAD_GUARDRAILS WHERE policy_version='staffing-v1-draft';
 demand(n=1,'Initial guardrail missing.');
 SELECT COUNT(*) INTO n FROM SCORING_WEIGHTS WHERE policy_version='staffing-v1-draft';
 demand(n=1,'Initial score weights missing.');
 SELECT COUNT(*) INTO n FROM POD_ASSIGNMENTS a WHERE a.status='CONFIRMED' AND
 a.assigned_hours <> (SELECT NVL(SUM(d.assigned_hours),0) FROM ASSIGNMENT_DAYS d WHERE d.assignment_id=a.assignment_id);
 demand(n=0,'Confirmed assignment hours differ from daily totals.');
 SELECT COUNT(*) INTO n FROM POD_PROPOSALS p WHERE p.status IN ('READY_FOR_REVIEW','APPROVED','REJECTED') AND
 (p.total_hours <> (SELECT NVL(SUM(m.planned_hours),0) FROM POD_PROPOSAL_MEMBERS m WHERE m.proposal_id=p.proposal_id AND m.selected_flag='Y')
 OR p.lead_count <> (SELECT COUNT(*) FROM POD_PROPOSAL_MEMBERS m WHERE m.proposal_id=p.proposal_id AND m.selected_flag='Y' AND m.role_in_pod='POD_LEAD')
 OR p.member_count <> (SELECT COUNT(*) FROM POD_PROPOSAL_MEMBERS m WHERE m.proposal_id=p.proposal_id AND m.selected_flag='Y' AND m.role_in_pod='POD_MEMBER'));
 demand(n=0,'Published proposal totals/counts are inconsistent.');
 DBMS_OUTPUT.PUT_LINE('PASS: all phase-2 DDL fingerprints, constraints, triggers and structural invariants verified.');
 DBMS_OUTPUT.PUT_LINE('This is not an agent execution, policy approval, identity integration or email test.');
 FOR r IN (SELECT object_name,original_rows FROM AIPS_P2_MIGRATION WHERE object_type='BASELINE' ORDER BY object_name) LOOP
   EXECUTE IMMEDIATE 'SELECT COUNT(*) FROM AI_POD_STAFFING.'||DBMS_ASSERT.SIMPLE_SQL_NAME(r.object_name) INTO n;
   DBMS_OUTPUT.PUT_LINE(r.object_name||': current='||n||', before migration='||r.original_rows);
 END LOOP;
END;
/
SELECT agents_enabled,notifications_enabled,updated_at FROM STAFFING_RUNTIME WHERE runtime_id=1;
SELECT policy_version,status,approved_by,approved_at FROM STAFFING_POLICIES;
SELECT name,line,position,text FROM user_errors WHERE name LIKE 'P2\_%' ESCAPE '\' ORDER BY name,sequence;

