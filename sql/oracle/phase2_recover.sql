-- Safe operational recovery, NOT destructive DDL rollback.
-- Stop only this app's Next.js/Python workers first. F5 as AI_POD_STAFFING.
-- Retains all tables, audit/decision history, proposals, assignments and existing data.
SET SERVEROUTPUT ON
SET DEFINE OFF
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK
DECLARE n NUMBER; marker VARCHAR2(4000);
BEGIN
 IF USER<>'AI_POD_STAFFING' OR SYS_CONTEXT('USERENV','SESSION_USER')<>'AI_POD_STAFFING'
 OR SYS_CONTEXT('USERENV','CURRENT_SCHEMA')<>'AI_POD_STAFFING' THEN
 RAISE_APPLICATION_ERROR(-20100,'Use AI_POD_STAFFING only.'); END IF;
 EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL DML';
 EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL QUERY';
 SELECT MAX(comments) INTO marker FROM user_tab_comments WHERE table_name='AIPS_P2_MIGRATION';
 IF marker IS NULL OR marker<>'AIPS_BACKEND_P2_V1' THEN RAISE_APPLICATION_ERROR(-20180,'Unknown migration. Nothing changed.'); END IF;
 SELECT COUNT(*) INTO n FROM AIPS_P2_MIGRATION WHERE step_key='STAFFING_RUNTIME' AND state='APPLIED';
 IF n=1 THEN
   EXECUTE IMMEDIATE q'~UPDATE AI_POD_STAFFING.STAFFING_RUNTIME SET agents_enabled='N',
     notifications_enabled='N',updated_by=USER,updated_at=SYSTIMESTAMP WHERE runtime_id=1~';
 END IF;
 SELECT COUNT(*) INTO n FROM AIPS_P2_MIGRATION WHERE step_key='ALTER_REQUESTS' AND state='APPLIED';
 IF n=1 THEN
   EXECUTE IMMEDIATE q'~UPDATE AI_POD_STAFFING.REQUESTS SET agent_enabled='N' WHERE agent_enabled='Y'~';
 END IF;
 COMMIT;
 DBMS_OUTPUT.PUT_LINE('Agent/email switches disabled where installed. No records or schema objects deleted.');
 DBMS_OUTPUT.PUT_LINE('In-flight workers must be stopped separately. Pending jobs and outbox rows are retained for review.');
 DBMS_OUTPUT.PUT_LINE('Keep the journal. Fix the issue and resume phase2.sql; never rerun setup.sql.');
EXCEPTION WHEN OTHERS THEN ROLLBACK; RAISE;
END;
/

