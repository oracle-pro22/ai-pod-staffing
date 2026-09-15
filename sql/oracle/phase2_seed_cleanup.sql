-- OPTIONAL: deletes ONLY the five people / three requests created by phase2_seed.sql.
-- Never run for general database cleanup. Stop this app's writers first.
-- Change the confirmation constant to REMOVE_PHASE2_FIXTURES only after reviewing the IDs below.
-- Refuses if the real agent has begun processing any fixture; preserve governed history then.
SET SERVEROUTPUT ON
SET DEFINE OFF
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK
DECLARE
 confirmation CONSTANT VARCHAR2(40):='NO';
 batch CONSTANT VARCHAR2(60):='AIPS_BACKEND_P2_SEED_V1';
 n NUMBER;
 PROCEDURE demand(ok BOOLEAN,msg VARCHAR2) IS
 BEGIN IF ok IS NULL OR NOT ok THEN RAISE_APPLICATION_ERROR(-20181,msg); END IF; END;
BEGIN
 IF USER<>'AI_POD_STAFFING' OR SYS_CONTEXT('USERENV','SESSION_USER')<>'AI_POD_STAFFING'
 OR SYS_CONTEXT('USERENV','CURRENT_SCHEMA')<>'AI_POD_STAFFING' THEN
 RAISE_APPLICATION_ERROR(-20100,'Use AI_POD_STAFFING only.'); END IF;
 demand(confirmation='REMOVE_PHASE2_FIXTURES','Cleanup disabled. Review this script and explicitly confirm first.');
 EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL DML';
 EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL QUERY';
 SELECT COUNT(*) INTO n FROM STAFFING_RUNTIME WHERE runtime_id=1 AND agents_enabled='N' AND notifications_enabled='N';
 demand(n=1,'Disable staffing workers/email before cleanup.');
 SELECT COUNT(*) INTO n FROM AIPS_P2_MIGRATION WHERE step_key='SEED_V1' AND state='APPLIED';
 demand(n=1,'Seed provenance marker missing.');
 SELECT COUNT(*) INTO n FROM PEOPLE WHERE staffing_seed_batch=batch
   AND person_id IN ('P-900101','P-900102','P-900103','P-900104','P-900105');
 demand(n=5,'Expected fixture people do not match.');
 SELECT COUNT(*) INTO n FROM PEOPLE WHERE staffing_seed_batch=batch;
 demand(n=5,'Unexpected people tagged with this batch.');
 SELECT COUNT(*) INTO n FROM REQUESTS WHERE staffing_seed_batch=batch
   AND request_id IN ('REQ-900101','REQ-900102','REQ-900103');
 demand(n=3,'Expected fixture requests do not match.');
 SELECT COUNT(*) INTO n FROM REQUESTS WHERE staffing_seed_batch=batch;
 demand(n=3,'Unexpected requests tagged with this batch.');
 SELECT COUNT(*) INTO n FROM AGENT_EXECUTIONS WHERE request_id IN
   (SELECT request_id FROM REQUESTS WHERE staffing_seed_batch=batch);
 demand(n=0,'Fixture execution/history exists. Retain it; use a separately reviewed archival plan.');
 SELECT COUNT(*) INTO n FROM APP_USER_ROLES WHERE person_id IN
   (SELECT person_id FROM PEOPLE WHERE staffing_seed_batch=batch) AND assigned_by<>batch;
 demand(n=0,'A fixture person now has non-fixture identity grants. Stop and review.');
 -- Other-person/request references are deliberately NOT cascaded; FKs will stop cleanup and all deletes roll back.
 DELETE FROM RECOMMENDATIONS WHERE request_id IN (SELECT request_id FROM REQUESTS WHERE staffing_seed_batch=batch);
 DELETE FROM REQUIREMENTS WHERE request_id IN (SELECT request_id FROM REQUESTS WHERE staffing_seed_batch=batch);
 DELETE FROM REQUESTS WHERE staffing_seed_batch=batch;
 DELETE FROM PERSON_CAPACITY_DAYS WHERE person_id IN (SELECT person_id FROM PEOPLE WHERE staffing_seed_batch=batch);
 DELETE FROM AVAILABILITY WHERE person_id IN (SELECT person_id FROM PEOPLE WHERE staffing_seed_batch=batch);
 DELETE FROM PERSON_INTERESTS WHERE person_id IN (SELECT person_id FROM PEOPLE WHERE staffing_seed_batch=batch);
 DELETE FROM APP_USER_ROLES WHERE person_id IN (SELECT person_id FROM PEOPLE WHERE staffing_seed_batch=batch);
 DELETE FROM PEOPLE WHERE staffing_seed_batch=batch;
 DELETE FROM AIPS_P2_MIGRATION WHERE step_key='SEED_V1';
 COMMIT;
 DBMS_OUTPUT.PUT_LINE('Removed only the tagged phase-2 fixtures. Committed deletion requires a prior export to recover.');
 DBMS_OUTPUT.PUT_LINE('Catalogue, real users and unrelated requests retained; phase2_seed.sql can recreate fresh fixtures.');
EXCEPTION WHEN OTHERS THEN ROLLBACK; RAISE;
END;
/

